"""PII redaction for logs.

AGENTS.md: log LLM prompts and responses only with redaction (and user consent).
The ML pipeline does not log transcript/prompt content by default; when it must
be logged for debugging, run it through :func:`redact` first. Over-redaction is
safe for logs, so the patterns are deliberately aggressive.
"""

from __future__ import annotations

import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"\+?\d[\d\s\-()]{7,}\d")
_LONG_NUMBER = re.compile(r"\b\d{12,19}\b")


def redact(text: str) -> str:
    """Mask emails, phone numbers and long digit runs (cards/accounts)."""
    # Long digit runs first: a card number would otherwise match the phone rule.
    masked = _LONG_NUMBER.sub("[number]", text)
    masked = _EMAIL.sub("[email]", masked)
    return _PHONE.sub("[phone]", masked)
