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


def issue_token(
    *,
    workspace_slug: str,
    subject: str,
    role: str | None = None,
    name: str | None = None,
    workspace_id: str | None = None,
    key_fingerprint: str | None = None,
) -> str:
    """Sign a short-lived access token identifying a principal in a workspace.

    ``subject`` is the actor's **id** (``str(actor.id)``) for actor tokens, so a
    token can never alias a different actor that happens to share a name. The
    only other form is the legacy workspace-key token, whose subject is the
    workspace slug with ``role="owner"``. ``name`` is informational (display /
    attribution hints for clients); verification never trusts it.

    ``workspace_id`` pins the token to one workspace *instance*, so a token
    can't carry over to a different workspace that later reuses the slug.
    ``key_fingerprint`` (workspace-key tokens only) pins it to the key that
    minted it, so rotating a leaked key also kills the tokens minted from it.
    """
    now = datetime.now(UTC)
    claims = {
        "sub": subject,
        "workspace": workspace_slug,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.jwt_ttl_seconds)).timestamp()),
        "iss": "context-hub",
    }
    if name is not None:
        claims["name"] = name
    if workspace_id is not None:
        claims["wid"] = workspace_id
    if key_fingerprint is not None:
        claims["kfp"] = key_fingerprint
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


def key_fingerprint(key_hash: str | None) -> str | None:
    """Short, non-reversible tag of a stored key digest, embedded in workspace-key tokens."""
    return key_hash[:16] if key_hash else None
