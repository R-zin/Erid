"""Unit tests for the file-watch auto-presence scanner (no server needed)."""

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "mcp-server" / "src"))

import watcher  # noqa: E402


def _write(path: Path, *, mtime_offset: float = 0.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    mtime = time.time() + mtime_offset
    os.utime(path, (mtime, mtime))


def test_newest_file_returns_latest(tmp_path):
    _write(tmp_path / "old.py")
    _write(tmp_path / "src" / "new.py", mtime_offset=60)
    latest = watcher.newest_file(tmp_path)
    assert latest is not None
    assert latest.relpath == str(Path("src") / "new.py")


def test_newest_file_ignores_vcs_and_cache_dirs(tmp_path):
    _write(tmp_path / "app" / "main.py")
    _write(tmp_path / ".git" / "HEAD", mtime_offset=60)
    _write(tmp_path / "node_modules" / "pkg" / "index.js", mtime_offset=60)
    _write(tmp_path / ".venv" / "lib" / "x.py", mtime_offset=60)
    latest = watcher.newest_file(tmp_path)
    assert latest is not None
    assert latest.relpath == str(Path("app") / "main.py")


def test_newest_file_ignores_hidden_and_binary_artifacts(tmp_path):
    _write(tmp_path / "visible.py")
    _write(tmp_path / ".env", mtime_offset=60)
    _write(tmp_path / ".DS_Store", mtime_offset=60)
    _write(tmp_path / "dump.rdb", mtime_offset=60)
    latest = watcher.newest_file(tmp_path)
    assert latest is not None
    assert latest.relpath == "visible.py"


def test_newest_file_empty_tree_returns_none(tmp_path):
    assert watcher.newest_file(tmp_path) is None


def test_relpath_is_relative_even_when_root_has_other_files(tmp_path):
    nested = tmp_path / "repo"
    _write(nested / "pkg" / "module.py", mtime_offset=60)
    latest = watcher.newest_file(nested)
    assert latest is not None
    assert not latest.relpath.startswith("/")
    assert latest.relpath == str(Path("pkg") / "module.py")
