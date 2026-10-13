"""Field-level encryption of personal data (plan §16)."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.infrastructure import crypto


def test_round_trip_hides_the_plaintext() -> None:
    plaintext = "Обсудили поставку до пятницы, сумма 120000 ₽"
    stored = crypto.encrypt(plaintext)
    assert stored != plaintext
    assert stored.startswith(crypto.PREFIX)
    assert plaintext not in stored
    assert crypto.decrypt(stored) == plaintext


def test_legacy_clear_text_passes_through() -> None:
    # Rows written before encryption was enabled do not carry the prefix.
    assert crypto.decrypt("[]") == "[]"
    assert crypto.decrypt("обычный текст") == "обычный текст"


def test_wrong_key_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    stored = crypto.encrypt("секрет")
    monkeypatch.setattr(crypto, "_cipher", lambda: Fernet(Fernet.generate_key()))
    with pytest.raises(ValueError, match="DATA_ENCRYPTION_KEY"):
        crypto.decrypt(stored)


def test_encrypted_text_type_round_trip() -> None:
    column = crypto.EncryptedText()
    stored = column.process_bind_param("привет", None)
    assert stored is not None and stored.startswith(crypto.PREFIX)
    assert column.process_result_value(stored, None) == "привет"
    assert column.process_bind_param(None, None) is None
    assert column.process_result_value(None, None) is None


def test_encrypted_json_type_round_trip() -> None:
    column = crypto.EncryptedJSON()
    value = [{"speaker": "operator", "text": "позвоню в 15:00", "start": 0.0}]
    stored = column.process_bind_param(value, None)
    assert isinstance(stored, str) and stored.startswith(crypto.PREFIX)
    assert "позвоню" not in stored
    assert column.process_result_value(stored, None) == value


def test_encrypted_json_reads_legacy_jsonb_values() -> None:
    # Before the migration the column was JSONB: a legacy value arrives decoded,
    # not as a ciphertext string.
    column = crypto.EncryptedJSON()
    legacy = [{"speaker": "client", "text": "ок"}]
    assert column.process_result_value(legacy, None) == legacy
