"""Fernet encryption for org-scoped token blobs at rest."""

from __future__ import annotations

import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

CIPHERTEXT_VERSION = 1


class EncryptionError(Exception):
    """Raised when token encryption or decryption fails."""


def _fernet(key: str) -> Fernet:
    if not key:
        raise EncryptionError("PERSISTENCE_ENCRYPTION_KEY is required for DynamoDB persistence")
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError) as exc:
        raise EncryptionError("Invalid PERSISTENCE_ENCRYPTION_KEY format") from exc


def encrypt_token_payload(key: str, payload: dict[str, Any]) -> tuple[str, int]:
    """Serialize and encrypt a token payload; returns ciphertext and version."""
    raw = json.dumps(payload, default=str).encode("utf-8")
    token = _fernet(key).encrypt(raw).decode("ascii")
    return token, CIPHERTEXT_VERSION


def decrypt_token_payload(key: str, token_blob: str, *, version: int = CIPHERTEXT_VERSION) -> dict[str, Any]:
    """Decrypt a token blob and return the payload dict."""
    if version != CIPHERTEXT_VERSION:
        raise EncryptionError(f"Unsupported ciphertext_version: {version}")
    try:
        raw = _fernet(key).decrypt(token_blob.encode("ascii"))
    except InvalidToken as exc:
        raise EncryptionError("Failed to decrypt token blob") from exc
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise EncryptionError("Decrypted token payload must be a JSON object")
    return data
