"""Unit tests for token encryption helpers."""

from __future__ import annotations

import pytest

from src.persistence.encryption import (
    CIPHERTEXT_VERSION,
    EncryptionError,
    decrypt_token_payload,
    encrypt_token_payload,
)


def test_encrypt_decrypt_round_trip():
    key = "test-key-32bytes-long-for-fernet!!"
    # Fernet needs valid key - generate one
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    payload = {
        "access_token": "secret-token",
        "refresh_token": "refresh",
        "expires_in": 3600,
        "token_type": "Bearer",
        "obtained_at": "2026-06-13T12:00:00+00:00",
    }
    blob, version = encrypt_token_payload(key, payload)
    assert version == CIPHERTEXT_VERSION
    restored = decrypt_token_payload(key, blob, version=version)
    assert restored["access_token"] == "secret-token"


def test_decrypt_wrong_key_raises():
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    blob, version = encrypt_token_payload(key, {"access_token": "x", "expires_in": 1})
    other = Fernet.generate_key().decode()
    with pytest.raises(EncryptionError):
        decrypt_token_payload(other, blob, version=version)
