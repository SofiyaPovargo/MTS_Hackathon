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
from datetime import date

from app.config import get_settings
from app.domain.commitment import Commitment
from app.domain.dates import DateResolution, resolve_relative_date
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

    def __init__(
        self, transcript: Iterable[TranscriptSegment], *, today: date
    ) -> None:
        self._segments = list(transcript)
        self._text = " ".join(segment.text for segment in self._segments)
        self._duration = max((segment.end for segment in self._segments), default=0.0)
        self._today = today

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

    def resolve_due_date(self, commitment: Commitment) -> DateResolution | None:
        """Resolve the deadline deterministically from the conversation text.

        The LLM's ``due_date`` is never trusted as-is (AGENTS.md): the date
        phrase is re-resolved in code against ``conversation_date``. The quote
        is checked first, then the whole transcript as a fallback.
        """
        for text in (commitment.source_quote, self._text):
            if text:
                resolution = resolve_relative_date(text, today=self._today)
                if resolution is not None:
                    return resolution
        return None

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


def _apply_deterministic_due_date(
    commitment: Commitment, validator: CommitmentValidator
) -> None:
    """Override the LLM date with the code-resolved one (AGENTS.md).

    A resolved concrete date wins over the model's guess; a vague phrase
    ("на следующей неделе", "в конце месяца") raises ``vague_deadline`` so the
    agreement becomes ``needs_clarification`` instead of inventing a deadline.
    """
    resolution = validator.resolve_due_date(commitment)
    if resolution is None:
        return
    if resolution.ambiguous:
        commitment.ambiguity = _merge_ambiguity(
            commitment.ambiguity, AmbiguityFlags(vague_deadline=True)
        )
    elif resolution.due_date is not None:
        commitment.due_date = resolution.due_date
        # Code resolved a concrete date: the model's date uncertainty no longer
        # applies, so clear the flags it may have set for this deadline.
        commitment.ambiguity = replace(
            commitment.ambiguity, vague_deadline=False, missing_due_date=False
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
    validator = CommitmentValidator(context.transcript, today=context.conversation_date)
    validated: list[Commitment] = []
    for commitment in commitments:
        # Resolve the date first so ``missing_due_date`` reflects the code-
        # resolved deadline, not the (untrusted) model guess.
        _apply_deterministic_due_date(commitment, validator)
        commitment.ambiguity = _merge_ambiguity(commitment.ambiguity, validator.flags(commitment))
        if commitment.status is None:
            commitment.status = resolve_agreement_status(
                commitment.confidence, threshold=threshold, ambiguity=commitment.ambiguity
            )
        validated.append(commitment)
    return validated
