"""Тесты rule-based валидации, сервиса извлечения и промита.

Извлечённые сущности — `app.domain.commitment.Commitment` (контракт
Agreement-сервиса); статус выводится `resolve_agreement_status` по
`AmbiguityFlags` и порогу уверенности.
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal

import pytest

from app.config import get_settings
from app.domain.commitment import Commitment
from app.domain.enums import AgreementStatus, Owner
from app.ml.extraction.context import ConversationContext
from app.ml.extraction.llm import InstructorLLMExtractor
from app.ml.extraction.ports import ExtractionPort
from app.ml.extraction.service import ExtractionService
from app.ml.extraction.validation import CommitmentValidator, validate
from app.ml.stt.schemas import TranscriptSegment


def _context(segments: list[tuple[str, str, float, float]]) -> ConversationContext:
    return ConversationContext(
        conversation_id="meeting_02",
        conversation_date=date(2026, 10, 5),
        user_timezone="Europe/Moscow",
        participants={"operator": "Анна", "client": "Игорь Владимирович"},
        transcript=[TranscriptSegment(speaker=s, text=t, start=a, end=b) for s, t, a, b in segments],
    )


TRANSCRIPT = [
    ("operator", "Здравствуйте, мы подготовили для вас договор, я пришлю его до пятницы.", 10.0, 15.0),
    ("client", "Хорошо, буду ждать.", 15.5, 17.0),
]


def _commitment(
    *,
    type: str = "promise",
    title: str = "Менеджер пришлёт договор",
    owner: Owner = Owner.counterparty,
    due_date: date | None = None,
    due_time: time | None = None,
    amount: Decimal | None = None,
    currency: str | None = None,
    source_quote: str = "я пришлю его до пятницы",
    audio_start: float = 10.0,
    audio_end: float = 15.0,
    confidence: float = 0.9,
) -> Commitment:
    return Commitment(
        type=type,
        title=title,
        owner=owner,
        due_date=due_date,
        due_time=due_time,
        amount=amount,
        currency=currency,
        source_quote=source_quote,
        audio_start=audio_start,
        audio_end=audio_end,
        confidence=confidence,
    )


# --- Валидатор ------------------------------------------------------------


def test_quote_found_in_transcript() -> None:
    context = _context(TRANSCRIPT)
    validator = CommitmentValidator(context.transcript, today=context.conversation_date)
    assert validator.quote_found(_commitment())


def test_quote_not_found_flags_contradictory() -> None:
    context = _context(TRANSCRIPT)
    commitment = _commitment(source_quote="Пришлите счёт завтра")
    flags = CommitmentValidator(context.transcript, today=context.conversation_date).flags(commitment)
    assert flags.contradictory_quote


def test_bounds_out_of_call_flags_contradictory() -> None:
    context = _context(TRANSCRIPT)
    commitment = _commitment(audio_start=40.0, audio_end=50.0)
    flags = CommitmentValidator(context.transcript, today=context.conversation_date).flags(commitment)
    assert flags.contradictory_quote


def test_missing_due_date_flagged_for_deadline() -> None:
    context = _context(TRANSCRIPT)
    commitment = _commitment(type="deadline")
    flags = CommitmentValidator(context.transcript, today=context.conversation_date).flags(commitment)
    assert flags.missing_due_date


def test_unknown_owner_flagged() -> None:
    context = _context(TRANSCRIPT)
    commitment = _commitment(owner=Owner.unknown)
    flags = CommitmentValidator(context.transcript, today=context.conversation_date).flags(commitment)
    assert flags.unknown_owner


def test_validate_sets_ambiguous_status() -> None:
    context = _context(TRANSCRIPT)
    commitment = _commitment(source_quote="нет такой фразы", audio_start=50.0, audio_end=60.0)
    validated = validate(context, [commitment])
    assert validated[0].status is AgreementStatus.needs_clarification
    assert validated[0].ambiguity.contradictory_quote


def test_validate_keeps_confident_detected() -> None:
    context = _context(TRANSCRIPT)
    commitment = _commitment(due_date=date(2026, 10, 9))
    validated = validate(context, [commitment])
    assert validated[0].status is AgreementStatus.detected


def test_validate_empty_returns_empty() -> None:
    assert validate(_context(TRANSCRIPT), []) == []


def test_validate_overrides_llm_date_with_deterministic() -> None:
    # conversation_date = 2026-10-05 (понедельник); «до пятницы» — 09.10, не 13.10.
    context = _context(TRANSCRIPT)
    commitment = _commitment(due_date=date(2026, 10, 13))  # галлюцинация LLM
    validated = validate(context, [commitment])
    assert validated[0].due_date == date(2026, 10, 9)


def test_validate_vague_deadline_needs_clarification() -> None:
    context = _context([("operator", "Сдадим документы к концу месяца.", 0.0, 3.0)])
    commitment = _commitment(
        type="deadline",
        due_date=date(2026, 10, 31),
        source_quote="Сдадим документы к концу месяца.",
        audio_start=0.0,
        audio_end=3.0,
    )
    validated = validate(context, [commitment])
    assert validated[0].ambiguity.vague_deadline
    assert validated[0].status is AgreementStatus.needs_clarification


def test_concrete_date_clears_llm_vague_flag() -> None:
    from app.domain.rules import AmbiguityFlags

    context = _context(TRANSCRIPT)  # «до пятницы» резолвится в конкретную дату
    commitment = _commitment(due_date=date(2026, 10, 13))
    commitment.ambiguity = AmbiguityFlags(vague_deadline=True)
    validated = validate(context, [commitment])
    assert validated[0].due_date == date(2026, 10, 9)
    assert not validated[0].ambiguity.vague_deadline
    assert validated[0].status is AgreementStatus.detected


# --- Реалистичные кейсы из скилла (на уровне валидации фейковых LLM-выводов)


def test_explicit_deadline_confident_detected() -> None:
    context = _context([("operator", "Я пришлю договор до пятницы.", 0.0, 4.0)])
    commitment = _commitment(
        type="promise",
        title="Прислать договор",
        due_date=date(2026, 10, 9),
        source_quote="Я пришлю договор до пятницы.",
        audio_start=0.0,
        audio_end=4.0,
    )
    validated = validate(context, [commitment])
    assert validated[0].status is AgreementStatus.detected
    assert not validated[0].ambiguity.is_ambiguous


def test_ambiguity_flag_from_llm_stays_needs_clarification() -> None:
    from app.domain.rules import AmbiguityFlags

    context = _context([("client", "Постараемся сделать быстро.", 0.0, 3.0)])
    commitment = _commitment(
        type="deadline",
        owner=Owner.user,
        due_date=date(2026, 10, 7),
        source_quote="Постараемся сделать быстро.",
        audio_start=0.0,
        audio_end=3.0,
    )
    commitment.ambiguity = AmbiguityFlags(vague_deadline=True)
    validated = validate(context, [commitment])
    assert validated[0].status is AgreementStatus.needs_clarification
    assert validated[0].ambiguity.vague_deadline  # LLM-флаг не затёрт


def test_no_commitment_returns_nothing() -> None:
    context = _context(TRANSCRIPT)
    assert validate(context, []) == []


# --- Сервис -----------------------------------------------------------------


class FakeExtractor(ExtractionPort):
    def __init__(self, commitments: list[Commitment]) -> None:
        self._commitments = commitments
        self.calls: list[ConversationContext] = []

    async def extract(self, context: ConversationContext) -> list[Commitment]:
        self.calls.append(context)
        return self._commitments


@pytest.mark.asyncio
async def test_extraction_service_runs_validation() -> None:
    context = _context(TRANSCRIPT)
    raw = _commitment(source_quote="текста в транскрипте нет", audio_start=50.0, audio_end=60.0)
    service = ExtractionService(FakeExtractor([raw]))

    commitments = await service.extract(context)

    assert commitments[0].status is AgreementStatus.needs_clarification
    assert commitments[0].ambiguity.contradictory_quote


@pytest.mark.asyncio
async def test_extract_pair_keeps_raw_and_validated_apart() -> None:
    context = _context(TRANSCRIPT)
    raw = _commitment(source_quote="текста в транскрипте нет", audio_start=50.0, audio_end=60.0)
    service = ExtractionService(FakeExtractor([raw]))

    raw_out, validated = await service.extract_pair(context)

    # Сырой вывод LLM не мутируется валидатором (AGENTS: raw и validated раздельно).
    assert raw_out[0].status is None
    assert not raw_out[0].ambiguity.is_ambiguous
    assert validated[0].status is AgreementStatus.needs_clarification
    assert validated[0].ambiguity.contradictory_quote
    assert raw_out[0] is not validated[0]


# --- Промит -------------------------------------------------------------------


def test_prompt_includes_context_and_rules() -> None:
    extractor = InstructorLLMExtractor(api_key="x", base_url="http://localhost:11434/v1", model="qwen2.5:7b")
    context = _context([("operator", "Я пришлю договор до пятницы.", 0.0, 4.0)])
    messages = extractor._messages(context)

    user = messages[1]["content"]
    system = messages[0]["content"]
    assert "meeting_02" in user
    assert "2026-10-05" in user
    assert "договор" in user
    assert "source_quote" in system
    assert "contradictory_quote" in system or "ambiguity" in system
    # Порог уверенности из конфига доступен валидатору.
    assert get_settings().confidence_threshold == 0.8
