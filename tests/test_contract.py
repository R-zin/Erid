"""API contract checks.

1. ``api/openapi.json`` matches what the app generates, so a route or schema
   change can't land without regenerating the spec
   (``uv run python scripts/export_openapi.py``).
2. Every HTTP call the hand-written clients make (``mcp-server/src/client.py``,
   which the VS Code and JetBrains plugins also reach through the bridge, and
   ``web/src/api.js``) targets a real method + path in that spec, so renaming or
   removing a route fails here instead of in an editor.
"""

import json
import re
import sys
from pathlib import Path

from app.main import app

ROOT = Path(__file__).resolve().parent.parent
WS_ROOT = "/api/workspaces/{}"


def _norm(path: str) -> str:
    """Collapse every path parameter (``{task_id}``, ``${id}``) to ``{}`` and drop the query."""
    path = path.split("?", 1)[0]
    return re.sub(r"\$?\{[^}]*\}", "{}", path).rstrip("/") or "/"


def _spec_operations() -> set[tuple[str, str]]:
    spec = json.loads((ROOT / "api" / "openapi.json").read_text())
    return {(method.upper(), _norm(path)) for path, ops in spec["paths"].items() for method in ops}


def test_committed_openapi_spec_is_current():
    sys.path.insert(0, str(ROOT / "scripts"))
    from export_openapi import render

    committed = (ROOT / "api" / "openapi.json").read_text()
    assert committed == render(), "api/openapi.json is stale: run `uv run python scripts/export_openapi.py`"
    assert app.openapi()["paths"], "spec unexpectedly empty"


def _python_client_calls() -> set[tuple[str, str]]:
    src = (ROOT / "mcp-server" / "src" / "client.py").read_text()
    calls = {
        (m.upper(), _norm(WS_ROOT + path))
        for m, path in re.findall(r'self\._client\.(get|post|put|delete)\(\s*self\._url\(slug,\s*f?"([^"]*)"', src)
    }
    calls |= {
        (m.upper(), _norm(path))
        for m, path in re.findall(r'self\._client\.(get|post|put|delete)\(\s*f"\{self\._base\}([^"]*)"', src)
    }
    return calls


def _web_client_calls() -> set[tuple[str, str]]:
    src = (ROOT / "web" / "src" / "api.js").read_text()
    verbs = {"get": "GET", "post": "POST", "put": "PUT", "del": "DELETE"}
    calls = {
        (verbs[v], _norm(WS_ROOT + path)) for v, path in re.findall(r"\b(get|post|put|del)\(\s*['`](/[^'`]*)['`]", src)
    }
    # Top-level helpers that fetch() outside the workspace root.
    for match in re.finditer(r"fetch\(`\$\{base\}(/api/[^`]*)`(?:,\s*\{\s*method:\s*'(\w+)')?", src):
        calls.add(((match.group(2) or "GET").upper(), _norm(match.group(1))))
    return calls


def test_python_client_only_calls_real_routes():
    calls = _python_client_calls()
    assert len(calls) >= 15, f"parser found suspiciously few calls: {sorted(calls)}"
    missing = calls - _spec_operations()
    assert not missing, f"mcp-server/src/client.py calls routes the API doesn't have: {sorted(missing)}"


def test_web_client_only_calls_real_routes():
    calls = _web_client_calls()
    assert len(calls) >= 15, f"parser found suspiciously few calls: {sorted(calls)}"
    missing = calls - _spec_operations()
    assert not missing, f"web/src/api.js calls routes the API doesn't have: {sorted(missing)}"
