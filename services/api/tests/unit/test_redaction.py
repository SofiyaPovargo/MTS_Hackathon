"""Log redaction of personal data (AGENTS «ML and data rules»)."""

from __future__ import annotations

from app.infrastructure.redaction import redact, redact_preview


def test_redacts_phone_numbers() -> None:
    assert redact("позвони на +7 (999) 123-45-67 завтра") == "позвони на [phone] завтра"
    assert redact("номер 89991234567") == "номер [phone]"


def test_redacts_emails_and_long_numbers() -> None:
    assert redact("пиши на ivan.petrov@example.com") == "пиши на [email]"
    assert redact("счёт 40817810099910004312") == "счёт [number]"


def test_leaves_ordinary_text_untouched() -> None:
    text = "обсудили поставку и сроки до пятницы"
    assert redact(text) == text


def test_preview_is_redacted_and_capped() -> None:
    preview = redact_preview("тел +79990001122 " + "x" * 50, limit=20)
    assert preview.startswith("тел [phone]")
    assert preview.endswith("…")
    assert len(preview) == 21
