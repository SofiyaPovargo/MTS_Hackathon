"""Field-level encryption for personal data at rest.

Plan §16 and AGENTS «Code and data security»: audio and transcripts are personal
and commercial data and must be encrypted. Audio is encrypted server-side in
object storage (SSE, see ``MinioStorage.put_bytes``); free-text columns that hold
transcript and LLM output are encrypted here, transparently at the ORM boundary,
so no reader can forget to decrypt.

Values are encrypted with Fernet (AES-128-CBC + HMAC-SHA256) under
``DATA_ENCRYPTION_KEY`` and stored as ``enc:v1:<base64>``. A value without the
prefix is read back untouched, so rows written before encryption was enabled keep
working. Changing the key makes previously encrypted rows unreadable — set it
once and keep it secret.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from app.config import get_settings

logger = logging.getLogger(__name__)

#: Marks an encrypted value and its scheme version.
PREFIX = "enc:v1:"


@lru_cache(maxsize=1)
def _cipher() -> Fernet | None:
    """The Fernet cipher for the configured key, or ``None`` to store in clear.

    ``DATA_ENCRYPTION_KEY`` may be a ready Fernet key or any passphrase, which is
    stretched to a deterministic 32-byte key so a human-readable ``.env`` value
    works. Encrypting with an empty key would be fake security, so it is refused.
    """
    key = get_settings().data_encryption_key.strip()
    if not key:
        logger.warning(
            "DATA_ENCRYPTION_KEY is empty: transcripts and LLM output are stored "
            "in clear text (local development only)"
        )
        return None
    raw = key.encode()
    try:
        return Fernet(raw)
    except ValueError:
        return Fernet(base64.urlsafe_b64encode(hashlib.sha256(raw).digest()))


def encrypt(value: str) -> str:
    """Encrypt ``value``; clear text is returned when no key is configured."""
    cipher = _cipher()
    if cipher is None:
        return value
    return PREFIX + cipher.encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    """Decrypt a stored value; legacy clear text without the prefix passes through."""
    if not value.startswith(PREFIX):
        return value
    cipher = _cipher()
    if cipher is None:  # pragma: no cover - key removed after data was written
        raise ValueError("encrypted value found but DATA_ENCRYPTION_KEY is not set")
    try:
        return cipher.decrypt(value[len(PREFIX) :].encode()).decode()
    except InvalidToken as exc:
        raise ValueError(
            "cannot decrypt stored value: DATA_ENCRYPTION_KEY does not match the key used to write it"
        ) from exc


class EncryptedText(TypeDecorator[str]):
    """A ``Text`` column whose value is encrypted at rest."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Any) -> str | None:
        return None if value is None else encrypt(value)

    def process_result_value(self, value: str | None, dialect: Any) -> str | None:
        return None if value is None else decrypt(value)


class EncryptedJSON(TypeDecorator[Any]):
    """A ``Text`` column holding JSON that is encrypted at rest.

    Encrypting the serialized JSON (rather than individual fields) keeps lists
    and nested dicts intact with a single ciphertext per row.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        return encrypt(json.dumps(value, separators=(",", ":"), ensure_ascii=False))

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, str):  # legacy JSONB row read as a JSON value
            return value
        return json.loads(decrypt(value))
