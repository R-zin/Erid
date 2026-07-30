"""Ed25519 (EdDSA) access-token signing and verification.

A workspace actor exchanges its API key for a short-lived JWT bearer token at
``POST /workspaces/{slug}/token``; subsequent requests authenticate with
``Authorization: Bearer <jwt>`` instead of re-sending the raw key.

Keys come from settings (``ERID_JWT_PRIVATE_KEY``/``ERID_JWT_PUBLIC_KEY``,
PEM-encoded). When unset, an ephemeral pair is generated at startup — tokens
then stop verifying after a restart, which is acceptable for local dev. Set
explicit keys in production for stable tokens across restarts/instances.
"""

from datetime import UTC, datetime, timedelta

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from app.core.settings import settings


def _load_signing_key() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    """Return the (private, public) Ed25519 keypair, generating an ephemeral one
    if no private key is configured."""
    if settings.jwt_private_key:
        private = serialization.load_pem_private_key(settings.jwt_private_key.encode(), password=None)
        public = (
            serialization.load_pem_public_key(settings.jwt_public_key.encode())
            if settings.jwt_public_key
            else private.public_key()
        )
        return private, public
    # No configured key: ephemeral pair for this process.
    private = Ed25519PrivateKey.generate()
    return private, private.public_key()


_PRIVATE_KEY, _PUBLIC_KEY = _load_signing_key()


def issue_token(*, workspace_slug: str, actor_name: str, role: str | None = None) -> str:
    """Sign a short-lived access token identifying an actor in a workspace."""
    now = datetime.now(UTC)
    claims = {
        "sub": actor_name,
        "workspace": workspace_slug,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.jwt_ttl_seconds)).timestamp()),
        "iss": "context-hub",
    }
    return jwt.encode(claims, _PRIVATE_KEY, algorithm="EdDSA")


def verify_token(token: str) -> dict | None:
    """Verify a token and return its claims, or ``None`` if invalid/expired."""
    try:
        return jwt.decode(
            token,
            _PUBLIC_KEY,
            algorithms=["EdDSA"],
            issuer="context-hub",
            options={"require": ["sub", "workspace", "exp"]},
        )
    except jwt.PyJWTError:
        return None
