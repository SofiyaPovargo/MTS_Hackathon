"""Тесты доменной модели договорённости (app.domain.commitment)."""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.domain.commitment import Commitment
from app.domain.enums import Owner


def _commitment(**overrides: object) -> Commitment:
    values: dict[str, object] = {
        "type": "deadline",
        "title": "Отправить договор",
        "owner": Owner.counterparty,
        "source_quote": "я пришлю его до пятницы",
        "audio_start": 10.0,
        "audio_end": 14.0,
        "confidence": 0.9,
    }
    values.update(overrides)
    return Commitment(**values)


def test_valid_commitment() -> None:
    commitment = _commitment(
        due_date=date(2026, 10, 9),
        amount=Decimal("1500.00"),
        currency="RUB",
    )
    assert commitment.owner is Owner.counterparty
    assert commitment.status is None  # статус выводится позже по правилам домена


def test_amount_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        _commitment(amount=Decimal("0"), currency="RUB")


def test_amount_requires_currency() -> None:
    with pytest.raises(ValidationError):
        _commitment(amount=Decimal("1500"))


def test_audio_range_checked() -> None:
    with pytest.raises(ValidationError):
        _commitment(audio_start=15.0, audio_end=10.0)


def test_due_time_requires_due_date() -> None:
    with pytest.raises(ValidationError):
        _commitment(due_time=time(15, 0))


def test_invalid_owner_rejected() -> None:
    with pytest.raises(ValidationError):
        _commitment(owner="someone_else")  # mypy этому коду нужен ignore, но в strict он «не используется»
