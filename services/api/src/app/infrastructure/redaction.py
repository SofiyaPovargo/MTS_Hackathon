"""Redaction of personal data before anything reaches the logs.

AGENTS «ML and data rules»: LLM prompts and responses are logged only with
redaction (or user consent). The codebase logs counts and identifiers, never raw
transcripts, but a destination phone, an e-mail or a card number can still slip
into a log line through an exception message. ``redact`` masks those patterns so
a preview can be logged safely, and it is applied to the one LLM preview we emit.
"""

from __future__ import annotations

import re

#: Phone-like runs: at least 10 digits, optionally +, spaces, dashes, dots or
#: parentheses (``+7 (999) 123-45-67``). ``\d`` does not match separators, so the
#: count is enforced on the digits themselves.
_PHONE = re.compile(r"\+?\d(?:[\s().-]*\d){9,}")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_LONG_DIGITS = re.compile(r"\b\d{12,}\b")

_PHONE_TOKEN = "[phone]"
_EMAIL_TOKEN = "[email]"
_DIGITS_TOKEN = "[number]"


def redact(text: str) -> str:
    """Mask phone numbers, e-mails and long digit runs in ``text``."""
    redacted = _EMAIL.sub(_EMAIL_TOKEN, text)
    redacted = _LONG_DIGITS.sub(_DIGITS_TOKEN, redacted)
    return _PHONE.sub(_PHONE_TOKEN, redacted)


def redact_preview(text: str, *, limit: int = 500) -> str:
    """A redacted, length-capped preview for a log line."""
    masked = redact(text)
    return masked if len(masked) <= limit else f"{masked[:limit]}…"
