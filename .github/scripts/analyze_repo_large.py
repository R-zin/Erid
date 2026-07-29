"""Chunked large-repository analysis via NVIDIA NIM.

Scans the repo, packs source files into token-bounded chunks, asks the model to
review each chunk, then synthesizes a single report. Written for GitHub Actions
(see .github/workflows/repo_analysis_large.yml) but runnable locally:

    NVIDIA_API_KEY=... uv run python .github/scripts/analyze_repo_large.py

Configuration is via environment variables so behaviour can be tuned without
editing code:

    NVIDIA_API_KEY     (required) NIM API key.
    NIM_BASE_URL       default https://integrate.api.nvidia.com/v1
    NIM_MODEL          default z-ai/glm-5.2
    NIM_MAX_CHUNKS     default 15 (safety cap on huge repos)
    NIM_MAX_FILE_KB    default 100 (skip oversized files)
    NIM_TIMEOUT_S      default 120 (per-request timeout)
    NIM_MAX_DIFF_FILES default 40 (cap on files shown in the change patch)
    NIM_MAX_DIFF_CHARS default 12000 (cap on the change patch text)

The artifact (repo_analysis.md) opens with a "Changes in This Run" section:
commit/PR metadata, a diffstat, and a bounded unified diff of what changed. In
CI the diff range comes from GITHUB_EVENT_NAME plus GITHUB_BEFORE (push) or
GITHUB_BASE_SHA / GITHUB_BASE_REF (pull_request); locally it diffs HEAD~1.
"""

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from openai import APIError, OpenAI, RateLimitError

BASE_URL = os.getenv("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")
MODEL = os.getenv("NIM_MODEL", "z-ai/glm-5.2")

INCLUDE_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".java",
    ".go",
    ".rs",
    ".cpp",
    ".c",
    ".h",
    ".cs",
    ".rb",
    ".php",
    ".swift",
    ".kt",
    ".yml",
    ".yaml",
    ".json",
    ".toml",
    ".md",
    ".sh",
    ".sql",
}
SKIP_DIRS = {
    ".git",
    ".github",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".next",
    "vendor",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".idea",
    "coverage",
    ".claude",
}
# Core-logic source dirs are prioritised so a token cap spends budget on the
# implementation rather than tests/docs/reports.
PRIORITY_DIRS = ("api", "mcp-server", "web/src", "scripts", "shared", "infra")
DEPRIORITIZED_DIRS = ("tests", "test", "docs", "clients")
# Generated/lock files are not analyzable source.
EXCLUDE_FILES = {"package-lock.json", "uv.lock", "yarn.lock", "pnpm-lock.yaml", "poetry.lock"}

MAX_FILE_SIZE_KB = int(os.getenv("NIM_MAX_FILE_KB", "100"))
MAX_CHUNKS = int(os.getenv("NIM_MAX_CHUNKS", "15"))
# Reserve headroom below the model context for prompt scaffolding + response.
MAX_CHUNK_TOKENS = 24_000
REQUEST_TIMEOUT_S = float(os.getenv("NIM_TIMEOUT_S", "120"))
CHARS_PER_TOKEN = 4  # rough, model-agnostic estimate


@dataclass
class RepoFile:
    path: str
    content: str
    tokens: int
    priority: int  # lower = analysed first


# ── Collection ────────────────────────────────────────────────────────────────
def _priority(rel_path: str) -> int:
    top = rel_path.split("/", 1)[0]
    if top in PRIORITY_DIRS:
        return 0
    if top in DEPRIORITIZED_DIRS:
        return 2
    return 1


def collect_repo_files(root_path: str) -> list[RepoFile]:
    root = Path(root_path)
    files: list[RepoFile] = []
    for file_path in sorted(root.rglob("*")):
        if not file_path.is_file():
            continue
        try:
            rel = file_path.relative_to(root)
        except ValueError:
            continue
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if file_path.name in EXCLUDE_FILES:
            continue
        if file_path.suffix.lower() not in INCLUDE_EXTENSIONS:
            continue
        if file_path.stat().st_size / 1024 > MAX_FILE_SIZE_KB:
            continue
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        text = content.strip()
        if not text:
            continue
        files.append(
            RepoFile(
                path=str(rel),
                content=content,
                tokens=max(1, len(content) // CHARS_PER_TOKEN),
                priority=_priority(str(rel)),
            )
        )
    # Analyse core logic first, then the rest, so a monorepo cap is well spent.
    return sorted(files, key=lambda f: (f.priority, f.path))


# ── Chunking ──────────────────────────────────────────────────────────────────
def chunk_files(files: list[RepoFile]) -> list[list[RepoFile]]:
    chunks: list[list[RepoFile]] = []
    current: list[RepoFile] = []
    current_tokens = 0
    skipped_oversized = 0

    for f in files:
        if f.tokens > MAX_CHUNK_TOKENS:
            skipped_oversized += 1
            continue
        if current_tokens + f.tokens > MAX_CHUNK_TOKENS and current:
            chunks.append(current)
            current, current_tokens = [], 0
            if len(chunks) >= MAX_CHUNKS:
                break
        current.append(f)
        current_tokens += f.tokens

    if current and len(chunks) < MAX_CHUNKS:
        chunks.append(current)

    if skipped_oversized:
        print(f"   ⚠️  Skipped {skipped_oversized} file(s) larger than one chunk.")
    return chunks


# ── What changed in this commit / PR ──────────────────────────────────────────
MAX_DIFF_FILES = int(os.getenv("NIM_MAX_DIFF_FILES", "40"))
MAX_DIFF_CHARS = int(os.getenv("NIM_MAX_DIFF_CHARS", "12000"))


def _git(root: str, *args: str) -> str | None:
    """Run a git command in `root`, returning stripped stdout or None on failure.

    Never raises: git may be unavailable or the diff range may not resolve
    (shallow clones), in which case the caller just omits the section.
    """
    try:
        out = subprocess.run(
            ["git", "-C", root, *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except OSError, subprocess.SubprocessError:
        return None
    if out.returncode != 0:
        return None
    text = out.stdout.strip()
    return text or None


def _base_ref(root: str) -> str | None:
    """Resolve the base commit to diff against for this CI run.

    Push to main  -> the commit before HEAD (GITHUB_BEFORE).
    Pull request  -> the merge base with the base branch.
    """
    if os.getenv("GITHUB_EVENT_NAME") == "pull_request":
        base_sha = os.getenv("GITHUB_BASE_SHA")
        if base_sha and _git(root, "cat-file", "-e", f"{base_sha}^{{commit}}"):
            return base_sha
        base_branch = os.getenv("GITHUB_BASE_REF")
        if base_branch:
            return _git(root, "merge-base", "HEAD", f"origin/{base_branch}")
        return None
    before = os.getenv("GITHUB_BEFORE", "")
    if before and set(before) != {"0"}:  # GitHub sends all-zeros for a brand-new branch
        return before
    return "HEAD~1"


def collect_change_context(root: str) -> str:
    """Build a Markdown section describing what this commit / PR changes.

    Combines commit metadata, a per-file diffstat, a name-status list, and a
    bounded unified diff so the LLM (and a human reading the artifact) can see
    exactly what changed, not just the whole repo.
    """
    if _git(root, "rev-parse", "--is-inside-work-tree") is None:
        return ""

    sha = _git(root, "rev-parse", "--short", "HEAD") or "?"
    subject = _git(root, "log", "-1", "--pretty=%s") or ""
    author = _git(root, "log", "-1", "--pretty=%an") or ""
    date = _git(root, "log", "-1", "--pretty=%cs") or ""

    lines = ["# 🔄 Changes in This Run", ""]
    lines.append(f"**Commit** `{sha}` — {subject}")
    if author or date:
        lines.append(f"**Author** {author} · **Date** {date}")
    event = os.getenv("GITHUB_EVENT_NAME")
    if event:
        lines.append(f"**Trigger** `{event}`")
    lines.append("")

    base = _base_ref(root)
    if base:
        stat = _git(root, "diff", "--shortstat", base, "HEAD")
        name_status = _git(root, "diff", "--name-status", base, "HEAD") or ""
        if stat or name_status:
            lines += [f"## Diff vs `{base}`", ""]
            if stat:
                lines.append(f"**{stat}**")
                lines.append("")
            if name_status:
                lines.append("```")
                lines.append(name_status)
                lines.append("```")
                lines.append("")

        if name_status:
            shown_files = [ln.split("\t")[-1] for ln in name_status.splitlines()[:MAX_DIFF_FILES]]
            diff = _git(root, "diff", "--unified=3", base, "HEAD", "--", *shown_files) or ""
            if diff:
                if len(diff) > MAX_DIFF_CHARS:
                    diff = diff[:MAX_DIFF_CHARS] + "\n\n… [diff truncated] …"
                lines += [
                    f"## Patch (first {min(len(shown_files), MAX_DIFF_FILES)} file(s), bounded)",
                    "",
                    "```diff",
                    diff,
                    "```",
                    "",
                ]
    else:
        lines.append("_Could not determine a base commit to diff against._")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


# ── API call with backoff ─────────────────────────────────────────────────────
def call_nim(client: OpenAI, messages: list[dict], max_tokens: int) -> str:
    """Call the chat API with exponential backoff on rate limits.

    Always returns a string or raises — never returns None silently.
    """
    delay = 2.0
    last_err: Exception | None = None
    for attempt in range(4):
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                temperature=0.2,
                top_p=0.8,
                max_tokens=max_tokens,
                timeout=REQUEST_TIMEOUT_S,
            )
            content = resp.choices[0].message.content
            if content is None:
                raise APIError("empty completion content", request=None, body=None)
            return content
        except RateLimitError as e:  # retryable
            last_err = e
            if attempt < 3:
                print(f"   ⏳ Rate limited (attempt {attempt + 1}); retrying in {delay:.0f}s...")
                time.sleep(delay)
                delay *= 2
        except APIError as e:
            last_err = e
            if attempt < 3:
                print(f"   ⏳ API error (attempt {attempt + 1}): {e}; retrying in {delay:.0f}s...")
                time.sleep(delay)
                delay *= 2
    raise RuntimeError(f"NIM request failed after retries: {last_err}")


# ── Prompts ───────────────────────────────────────────────────────────────────
CHUNK_SYSTEM = "You are an expert code reviewer. Be concise and precise."

CHUNK_PROMPT = """You are analyzing a subset of a codebase.
Files in this chunk: {names}

{contents}

Provide a concise analysis (max 500 words) covering:
1. **Purpose**: What do these files do?
2. **Bugs/Security**: Any logical errors, crashes, or security flaws?
3. **Code Smells**: Poor patterns, duplication, or complexity?
Be direct. Use bullet points."""

SYNTHESIS_SYSTEM = "You are a Principal Software Architect. Write a professional, actionable report."

SYNTHESIS_PROMPT = """You have analyzed a large repository in {n} chunks.
Here are the findings from each chunk:

{summaries}

Now synthesize these into a comprehensive, unified final report. Do not just
list the chunks — merge duplicate findings and identify cross-cutting issues.

Structure the report exactly like this:

# 🏗️ Repository Analysis Report

## 1. Executive Summary
(2-3 sentences on what the project is and its overall health)

## 2. Architecture & Design
(High-level patterns, component interaction, structural strengths/weaknesses)

## 3. 🚨 Critical Issues (Bugs & Security)
(Most severe bugs/crashes/vulnerabilities, with file paths)

## 4. 🧹 Code Quality & Smells
(Patterns of poor code, duplication, technical debt)

## 5. ✅ What's Done Well
(Good practices observed)

## 6. 🚀 Top 5 Actionable Recommendations
(Prioritized, highest-impact changes first)

Format in clean Markdown."""


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description="Chunked repo analysis via NVIDIA NIM")
    parser.add_argument("root", nargs="?", default=".", help="repository root to scan")
    args = parser.parse_args()

    if not os.getenv("NVIDIA_API_KEY"):
        print("❌ NVIDIA_API_KEY is not set.", file=sys.stderr)
        return 1

    print(f"\n{'=' * 60}\n  REPO ANALYZER — {MODEL} on NVIDIA NIM\n{'=' * 60}\n")

    print("📁 Scanning repository...")
    files = collect_repo_files(args.root)
    print(f"✅ Found {len(files)} analyzable files.")
    if not files:
        print("❌ No files found.", file=sys.stderr)
        return 1

    chunks = chunk_files(files)
    print(f"📦 Split into {len(chunks)} chunk(s).\n")

    client = OpenAI(base_url=BASE_URL, api_key=os.environ["NVIDIA_API_KEY"])

    chunk_summaries: list[str] = []
    for idx, chunk in enumerate(chunks):
        names = [f.path for f in chunk]
        print(f"🤖 Analyzing chunk {idx + 1}/{len(chunks)} ({len(chunk)} files)...")
        contents = "\n\n".join(f"### {f.path}\n```{Path(f.path).suffix.lstrip('.')}\n{f.content}\n```" for f in chunk)
        summary = call_nim(
            client,
            [
                {"role": "system", "content": CHUNK_SYSTEM},
                {"role": "user", "content": CHUNK_PROMPT.format(names=", ".join(names), contents=contents)},
            ],
            max_tokens=1024,
        )
        preview = ", ".join(names[:3]) + ("…" if len(names) > 3 else "")
        chunk_summaries.append(f"### Chunk {idx + 1} ({preview})\n{summary}")
        print(f"   ✅ Chunk {idx + 1} complete.\n")
        if idx < len(chunks) - 1:
            time.sleep(2)  # gentle pacing between chunk calls

    # Synthesis runs ONCE, after every chunk summarised above.
    print("🔗 Synthesizing final report...\n")
    combined = "\n\n".join(chunk_summaries)
    if len(combined) > 100_000:
        combined = combined[:100_000] + "\n\n[Truncated due to size...]"

    report = call_nim(
        client,
        [
            {"role": "system", "content": SYNTHESIS_SYSTEM},
            {"role": "user", "content": SYNTHESIS_PROMPT.format(n=len(chunks), summaries=combined)},
        ],
        max_tokens=4096,
    )

    # Document what this commit / PR actually changed ahead of the analysis.
    changes = collect_change_context(args.root)
    document = f"{changes}\n---\n\n{report}" if changes else report

    output_path = Path("repo_analysis.md")
    output_path.write_text(document, encoding="utf-8")
    print(f"{'=' * 60}\n  REPORT GENERATED\n{'=' * 60}")
    print(f"\n💾 Saved to: {output_path.resolve()}")

    # Surface the report in the Actions run summary.
    summary_file = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as fh:
            fh.write(document + "\n")

    if os.getenv("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.write("analysis_complete=true\n")
            fh.write(f"chunks_processed={len(chunks)}\n")
            fh.write(f"files_scanned={len(files)}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
