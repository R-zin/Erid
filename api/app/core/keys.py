"""Key generation, kept import-neutral so both the security layer and service
layer can use it without a circular dependency."""

import hashlib
import secrets


def generate_api_key() -> str:
    return secrets.token_urlsafe(32)


def hash_api_key(raw: str) -> str:
    """Stable SHA-256 digest used to store/look up keys (never stored raw)."""
    return hashlib.sha256(raw.encode()).hexdigest()


def key_matches(raw: str | None, digest: str | None) -> bool:
    """Constant-time check of a presented raw key against a stored digest."""
    if not raw or not digest:
        return False
    return secrets.compare_digest(hash_api_key(raw), digest)
