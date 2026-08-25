"""Unit tests for the shared API client in ``server.py``.

No API subprocess needed — these only exercise the lazy ``_get_client()``
getter and the patch surface tests/future code rely on (``_client`` global +
the ``APIClient`` symbol).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "mcp-server" / "src"))

import server  # noqa: E402


def test_get_client_is_shared(monkeypatch):
    """The getter returns one process-wide client (connection pooling)."""
    monkeypatch.setattr(server, "_client", None)
    first = server._get_client()
    assert server._get_client() is first
    monkeypatch.setattr(server, "_client", None)


def test_get_client_patchable(monkeypatch):
    """Monkeypatching ``server.APIClient`` wins on the next lazy build."""
    sentinel = object()
    monkeypatch.setattr(server, "_client", None)
    monkeypatch.setattr(server, "APIClient", lambda: sentinel)
    assert server._get_client() is sentinel
