"""Сервис извлечения: LLM-экстрактор + rule-based валидация."""

from __future__ import annotations

from app.domain.commitment import Commitment
from app.ml.extraction.context import ConversationContext
from app.ml.extraction.ports import ExtractionPort
from app.ml.extraction.validation import validate


class ExtractionService:
    """Полный шаг extraction: структурный вывод LLM -> валидация."""

    def __init__(
        self,
        extractor: ExtractionPort,
        *,
        confidence_threshold: float | None = None,
    ) -> None:
        self._extractor = extractor
        self._confidence_threshold = confidence_threshold

    async def extract(self, context: ConversationContext) -> list[Commitment]:
        raw = await self._extractor.extract(context)
        return validate(context, raw, threshold=self._confidence_threshold)
