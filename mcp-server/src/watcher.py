"""File-watch auto-presence for the AI Context Hub.

Watches a directory tree and reports the most recently modified source file as
the actor's ``current_file`` via the presence endpoint — so "what is everyone
working on" stays current without anyone calling ``update_presence`` by hand.

Run standalone (alongside the MCP server or your editor):

    WORKSPACE_SLUG=myproj uv run python mcp-server/src/watcher.py

Configuration (same env as ``client.py``, plus):

- ``WATCH_ROOT``       directory to watch (default: current working directory)
- ``WATCH_INTERVAL``   seconds between scans (default: 15)
- ``PRESENCE_NAME``    actor name to report (default: git user.name, else $USER)

No third-party deps: it's an mtime poll over ``os.scandir``, which is cheap for
repo-scale trees and avoids adding a watchdog dependency.
"""

import asyncio
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from client import APIClient  # noqa: E402

WATCH_ROOT = Path(os.environ.get("WATCH_ROOT", os.getcwd())).resolve()
WATCH_INTERVAL = float(os.environ.get("WATCH_INTERVAL", "15"))
# Presence entries go stale after 10 minutes server-side (STALE_AFTER); refresh
# well inside that window even when the current file hasn't changed.
HEARTBEAT_INTERVAL = 240.0

IGNORED_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".idea",
    ".vscode",
    ".ruff_cache",
    ".pytest_cache",
    ".mypy_cache",
    "dist",
    "build",
    ".vite",
}
IGNORED_FILES = {"dump.rdb", ".DS_Store"}


@dataclass(frozen=True)
class NewestFile:
    relpath: str
    mtime: float


def newest_file(root: Path) -> NewestFile | None:
    """Return the most recently modified file under ``root``, skipping caches,
    VCS internals, and hidden paths. ``relpath`` is relative to ``root``."""
    best: NewestFile | None = None
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entry.name in IGNORED_DIRS or entry.name in IGNORED_FILES:
                        continue
                    if entry.name.startswith("."):
                        continue  # hidden files/dirs (.env, .claude, ...)
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        else:
                            mtime = entry.stat(follow_symlinks=False).st_mtime
                            if best is None or mtime > best.mtime:
                                best = NewestFile(relpath=str(Path(entry.path).relative_to(root)), mtime=mtime)
                    except OSError:
                        continue  # file vanished mid-scan
        except PermissionError, NotADirectoryError:
            continue
    return best


def default_actor_name() -> str:
    """git user.name if available, else the OS user, else a neutral fallback."""
    try:
        result = subprocess.run(
            ["git", "config", "user.name"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except OSError, subprocess.SubprocessError:
        pass
    return os.environ.get("USER") or os.environ.get("USERNAME") or "watcher"


async def watch(slug: str, actor_name: str, root: Path = WATCH_ROOT, interval: float = WATCH_INTERVAL) -> None:
    """Poll ``root`` and post presence when the newest file changes (and at the
    heartbeat cadence) until cancelled."""
    client = APIClient()
    last_reported: str | None = None
    last_sent = 0.0
    try:
        while True:
            latest = newest_file(root)
            now = time.monotonic()
            if latest is not None and (latest.relpath != last_reported or now - last_sent >= HEARTBEAT_INTERVAL):
                try:
                    await client.update_presence(
                        slug,
                        actor_name,
                        actor_type="human",
                        current_file=latest.relpath,
                    )
                    last_reported, last_sent = latest.relpath, now
                    print(f"[watcher] {actor_name} → {latest.relpath}", flush=True)
                except Exception as exc:  # keep watching through transient API errors
                    print(f"[watcher] presence update failed: {exc}", flush=True)
            await asyncio.sleep(interval)
    finally:
        await client.close()


def main() -> None:
    slug = os.environ.get("WORKSPACE_SLUG", "")
    if not slug:
        print("[watcher] WORKSPACE_SLUG is not set; exiting.", file=sys.stderr)
        sys.exit(2)
    actor_name = os.environ.get("PRESENCE_NAME") or default_actor_name()
    print(f"[watcher] watching {WATCH_ROOT} as '{actor_name}' in workspace '{slug}'", flush=True)
    try:
        asyncio.run(watch(slug, actor_name))
    except KeyboardInterrupt:
        print("[watcher] stopped.", flush=True)


if __name__ == "__main__":
    main()
