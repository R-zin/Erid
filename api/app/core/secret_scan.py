"""Secret scanning for text written to a workspace.

Everything in Erid is shared with every collaborator and pasted into AI
prompts, so a credential written into a handoff ("ran `export
GITHUB_TOKEN=ghp_...`") leaks to everyone. Writes are scanned with
gitleaks-style rules for well-known credential formats:

- ``redact`` (default): each match is replaced by ``[REDACTED:<rule>]`` and
  the write goes through;
- ``reject``: the write fails with 422 naming the field and rule;
- ``off``: no scanning.

Set with ``ERID_SECRET_SCANNING``. Rules target formats with distinctive
prefixes or structure, to keep false positives rare; they can't recognize an
arbitrary random password.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.settings import settings


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    # Capture group holding the secret (0 = the whole match). Lets a rule keep
    # context, e.g. redact only the password in a connection URL.
    group: int = 0


def _r(name: str, pattern: str, group: int = 0, flags: int = 0) -> Rule:
    return Rule(name, re.compile(pattern, flags), group)


RULES: tuple[Rule, ...] = (
    _r(
        "private_key",
        r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----[\s\S]*?"
        r"(?:-----END (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----|$)",
    ),
    _r("aws_access_key_id", r"\b(?:A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA)[A-Z0-9]{16}\b"),
    _r("github_token", r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,255}\b"),
    _r("github_fine_grained_token", r"\bgithub_pat_[A-Za-z0-9_]{22,255}\b"),
    _r("anthropic_api_key", r"\bsk-ant-(?:api|admin)\d{2}-[A-Za-z0-9_\-]{20,}"),
    _r("openai_api_key", r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{8,}T3BlbkFJ[A-Za-z0-9_\-]{8,}"),
    _r("slack_token", r"\bxox[abposr]-[A-Za-z0-9-]{10,}"),
    _r("slack_webhook", r"https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+"),
    _r("stripe_live_key", r"\b(?:sk|rk)_live_[A-Za-z0-9]{20,}\b"),
    _r("google_api_key", r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    _r("npm_token", r"\bnpm_[A-Za-z0-9]{36}\b"),
    _r("jwt", r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    # user:password@host in any URL scheme (postgres://, redis://, https://...).
    _r("url_password", r"\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:([^\s@/]{3,})@", group=1, flags=re.IGNORECASE),
    _r("bearer_token", r"\bauthorization:\s*bearer\s+([A-Za-z0-9._~+/=\-]{20,})", group=1, flags=re.IGNORECASE),
)


@dataclass(frozen=True)
class Finding:
    field: str
    rule: str


def redact(text: str) -> tuple[str, list[str]]:
    """Return ``text`` with every secret replaced, and the rules that matched."""
    hits: list[str] = []
    for rule in RULES:

        def _sub(m: re.Match[str], rule: Rule = rule) -> str:
            hits.append(rule.name)
            if rule.group == 0:
                return f"[REDACTED:{rule.name}]"
            start, end = m.span(rule.group)
            base = m.start()
            whole = m.group(0)
            return whole[: start - base] + f"[REDACTED:{rule.name}]" + whole[end - base :]

        text = rule.pattern.sub(_sub, text)
    return text, hits


def mode() -> str:
    value = settings.secret_scanning.strip().lower()
    return value if value in ("redact", "reject", "off") else "redact"


def scan_fields(values: dict[str, str | None]) -> tuple[dict[str, str | None], list[Finding]]:
    """Scan named text fields; return (redacted values, findings)."""
    if mode() == "off":
        return values, []
    out: dict[str, str | None] = {}
    findings: list[Finding] = []
    for field, value in values.items():
        if not value:
            out[field] = value
            continue
        cleaned, hits = redact(value)
        out[field] = cleaned
        findings.extend(Finding(field, rule) for rule in dict.fromkeys(hits))
    return out, findings
