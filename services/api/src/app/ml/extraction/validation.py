"""Rule-based валидация извлечённых договорённостей после LLM.

Не доверяем LLM-выводу: `source_quote` обязан встречаться в транскрипте,
таймкоды — лежать внутри длительности звонка. Проблемы упаковываются в
`AmbiguityFlags`, а статус договорённости выводится `resolve_agreement_status`
(needs_clarification / requires_review / detected).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import replace

from app.config import get_settings
from app.domain.commitment import Commitment
from app.domain.enums import Owner
from app.domain.rules import AmbiguityFlags, resolve_agreement_status
from app.ml.extraction.context import ConversationContext
from app.ml.stt.schemas import TranscriptSegment

_COMPACT = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]")

# Типы, для которых отсутствие срока — сигнал к уточнению.
DUE_REQUIRING_TYPES = frozenset({"deadline", "payment", "meeting"})


def normalize(text: str) -> str:
    """Нижний регистр, ё->е, пунктуация -> пробелы, схлопывание пробелов."""
    cleaned = _PUNCT.sub(" ", text.lower().replace("ё", "е"))
    return _COMPACT.sub(" ", cleaned).strip()


class CommitmentValidator:
    """Проверяет договорённости на соответствие транскрипту и длительности."""

    BOUNDS_TOLERANCE = 0.1

    def __init__(self, transcript: Iterable[TranscriptSegment]) -> None:
        self._segments = list(transcript)
        self._text = " ".join(segment.text for segment in self._segments)
        self._duration = max((segment.end for segment in self._segments), default=0.0)

    def quote_found(self, commitment: Commitment) -> bool:
        quote = normalize(commitment.source_quote)
        return bool(quote) and quote in normalize(self._text)

    def bounds_ok(self, commitment: Commitment) -> bool:
        tolerance = self.BOUNDS_TOLERANCE
        return (
            commitment.audio_start >= -tolerance
            and commitment.audio_end <= self._duration + tolerance
            and commitment.audio_start <= commitment.audio_end
        )

    def flags(self, commitment: Commitment) -> AmbiguityFlags:
        """Превратить расхождения quote/таймкодов/срока в сигналы неоднозначности."""
        flags = AmbiguityFlags()
        if not self.quote_found(commitment):
            flags = replace(flags, contradictory_quote=True)
        if not self.bounds_ok(commitment):
            flags = replace(flags, contradictory_quote=True)
        if commitment.type in DUE_REQUIRING_TYPES and commitment.due_date is None:
            flags = replace(flags, missing_due_date=True)
        if commitment.owner is Owner.unknown:
            flags = replace(flags, unknown_owner=True)
        return flags


def _merge_ambiguity(base: AmbiguityFlags, extra: AmbiguityFlags) -> AmbiguityFlags:
    """OR-объединение сигналов неоднозначности (LLM + rule-based)."""
    return replace(
        base,
        vague_deadline=base.vague_deadline or extra.vague_deadline,
        missing_due_date=base.missing_due_date or extra.missing_due_date,
        missing_amount=base.missing_amount or extra.missing_amount,
        unknown_owner=base.unknown_owner or extra.unknown_owner,
        contradictory_quote=base.contradictory_quote or extra.contradictory_quote,
    )


def validate(
    context: ConversationContext,
    commitments: Iterable[Commitment],
    *,
    threshold: float | None = None,
) -> list[Commitment]:
    """Прогнать договорённости через валидатор; статус — по правилам домена."""
    if threshold is None:
        threshold = get_settings().confidence_threshold
    validator = CommitmentValidator(context.transcript)
    validated: list[Commitment] = []
    for commitment in commitments:
        commitment.ambiguity = _merge_ambiguity(commitment.ambiguity, validator.flags(commitment))
        if commitment.status is None:
            commitment.status = resolve_agreement_status(
                commitment.confidence, threshold=threshold, ambiguity=commitment.ambiguity
            )
        validated.append(commitment)
    return validated
