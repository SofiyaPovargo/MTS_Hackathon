"""Redaction of PII for logs."""

from __future__ import annotations

from app.infrastructure.redaction import redact


def test_masks_email() -> None:
    assert redact("пишите на ivan.petrov@example.com") == "пишите на [email]"


def test_masks_phone() -> None:
    assert "[phone]" in redact("звоните +7 916 123-45-67 завтра")


def test_masks_long_number() -> None:
    assert "[number]" in redact("карта 4276123456789012")


def test_keeps_plain_text() -> None:
    assert redact("пришлю договор до пятницы") == "пришлю договор до пятницы"
