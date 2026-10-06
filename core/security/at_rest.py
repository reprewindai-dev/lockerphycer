"""Encryption of secrets that must be readable again (TOTP secrets).

A TOTP secret cannot be hashed: the server needs the real value to check a
code. So it is stored encrypted with a Fernet key derived from SECRET_KEY, and
a copy of the users table yields no working second factor without that key.

Storage format: ``enc1:<fernet token>``. The prefix lets the migration and the
column type tell an encrypted value from a legacy plaintext row that has not
been converted yet, and leaves room for a later key or scheme change.

Consequence for operators: rotating SECRET_KEY invalidates every stored TOTP
secret (as it already invalidates every JWT). Decrypt failures are logged and
read as "no secret", so an affected account fails closed at login instead of
crashing every query that loads a user row.
"""

from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

ENCRYPTED_PREFIX = "enc1:"
_KEY_CONTEXT = b"lockerphycer:mfa-secret-at-rest:v1:"

logger = logging.getLogger(__name__)


def _fernet(secret_key: str | None = None) -> Fernet:
    if secret_key is None:
        from core.config.settings import settings

        secret_key = settings.SECRET_KEY
    derived = hashlib.sha256(_KEY_CONTEXT + secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def is_encrypted(stored: str | None) -> bool:
    return bool(stored) and stored.startswith(ENCRYPTED_PREFIX)


def encrypt_secret(plaintext: str, secret_key: str | None = None) -> str:
    return ENCRYPTED_PREFIX + _fernet(secret_key).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(stored: str, secret_key: str | None = None) -> str | None:
    """Plaintext of a stored value; a legacy plaintext row is returned as is.

    Returns None when the value cannot be decrypted with the current key.
    """
    if not is_encrypted(stored):
        return stored
    token = stored[len(ENCRYPTED_PREFIX):].encode("ascii")
    try:
        return _fernet(secret_key).decrypt(token).decode("utf-8")
    except InvalidToken:
        logger.error("Stored secret cannot be decrypted with the current SECRET_KEY; treating it as absent")
        return None


class EncryptedSecret(TypeDecorator):
    """String column whose value is encrypted at rest and plaintext in Python."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if is_encrypted(value):  # already ciphertext (e.g. copied row); do not double-wrap
            return value
        return encrypt_secret(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return decrypt_secret(value)
