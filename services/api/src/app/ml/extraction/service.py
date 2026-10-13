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

    async def extract_pair(
        self, context: ConversationContext
    ) -> tuple[list[Commitment], list[Commitment]]:
        """Вернуть ``(raw, validated)``: LLM-вывод и его провалидированную копию.

        ``raw`` сохраняется как есть (без rule-based правок) — AGENTS требует
        хранить сырой вывод LLM, валидированный вывод и правки пользователя
        раздельно. Валидация не мутирует ``raw``.
        """
        raw = await self._extractor.extract(context)
        to_validate = [commitment.model_copy(deep=True) for commitment in raw]
        validated = validate(context, to_validate, threshold=self._confidence_threshold)
        return raw, validated
