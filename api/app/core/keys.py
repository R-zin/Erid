"""Key generation, kept import-neutral so both the security layer and service
layer can use it without a circular dependency."""

import secrets


def generate_api_key() -> str:
    return secrets.token_urlsafe(32)
