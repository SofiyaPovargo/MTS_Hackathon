"""Порт извлечения договорённостей."""

from __future__ import annotations

from typing import Protocol

from app.domain.commitment import Commitment
from app.ml.extraction.context import ConversationContext


class ExtractionPort(Protocol):
    """Контракт LLM-извлечения договорённостей из транскрипта."""

    async def extract(self, context: ConversationContext) -> list[Commitment]:
        """Вернуть извлечённые договорённости (до rule-based валидации)."""
        ...
