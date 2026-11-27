"""The API image installs api/requirements.lock (hash-pinned, --no-deps), so it
must be exactly what uv.lock resolves; otherwise CI would test and audit one
set of versions and ship another."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
REGENERATE = "uv export --frozen --no-dev --no-emit-project --format requirements-txt -o api/requirements.lock"


def _requirements(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]


@pytest.mark.skipif(shutil.which("uv") is None, reason="needs the uv CLI")
def test_image_lock_matches_uv_lock():
    expected = subprocess.run(
        ["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--format", "requirements-txt"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    actual = (ROOT / "api" / "requirements.lock").read_text()
    assert _requirements(actual) == _requirements(expected), f"api/requirements.lock is stale; run: {REGENERATE}"


def test_image_installs_only_the_hash_pinned_lock():
    dockerfile = (ROOT / "api" / "Dockerfile").read_text()
    assert "--require-hashes" in dockerfile and "--no-deps" in dockerfile and "requirements.lock" in dockerfile
    lock = (ROOT / "api" / "requirements.lock").read_text()
    pins = [line for line in _requirements(lock) if not line.startswith(" ")]
    assert pins and all("==" in p for p in pins)
    assert lock.count("--hash=sha256:") >= len(pins)
