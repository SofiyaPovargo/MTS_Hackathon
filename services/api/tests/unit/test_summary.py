"""Итог звонка (§9): детерминированное резюме из договорённостей (без LLM)."""

from __future__ import annotations

import uuid
from datetime import date, time

from app.domain.enums import AgreementStatus, CallDirection, CallStatus, Owner
from app.infrastructure.db.models import Agreement, Call
from app.ml.stt.schemas import TranscriptSegment
from app.ml.summary.llm import InstructorLLMSummarizer
from app.ml.summary.ports import AgreementFact, SummaryInput
from app.services.summary import build_summary


def _call(*, contact_name: str | None = "Игорь Владимирович", contact_phone: str = "+79990000000") -> Call:
    return Call(
        user_id=uuid.uuid4(),
        direction=CallDirection.outbound,
        contact_phone=contact_phone,
        contact_name=contact_name,
        status=CallStatus.completed,
    )


def _agreement(
    *,
    title: str = "Отправить КП",
    owner: Owner = Owner.user,
    status: AgreementStatus = AgreementStatus.detected,
    due_date: date | None = None,
    due_time: time | None = None,
) -> Agreement:
    return Agreement(
        call_id=uuid.uuid4(),
        owner=owner,
        type="obligation",
        title=title,
        source_quote="цитата из разговора",
        audio_start=1.0,
        audio_end=2.0,
        confidence=0.9,
        status=status,
        due_date=due_date,
        due_time=due_time,
    )


def test_build_summary_without_agreements() -> None:
    summary = build_summary(_call(), [])
    assert summary == "Итог звонка с Игорь Владимирович: договорённости не выделены."


def test_build_summary_falls_back_to_phone() -> None:
    summary = build_summary(_call(contact_name=None), [])
    assert summary == "Итог звонка с +79990000000: договорённости не выделены."


def test_build_summary_lists_active_agreements_and_excludes_rejected() -> None:
    agreements = [
        _agreement(
            title="Отправить КП",
            owner=Owner.user,
            status=AgreementStatus.confirmed,
            due_date=date(2026, 10, 16),
        ),
        _agreement(title="Встреча", owner=Owner.unknown, status=AgreementStatus.requires_review),
        _agreement(title="Черновик", status=AgreementStatus.rejected),
    ]

    summary = build_summary(_call(), agreements)

    assert "Итог звонка с Игорь Владимирович." in summary
    assert "Договорённостей: 2, подтверждено: 1." in summary
    assert "1. Отправить КП (на нас, срок 2026-10-16) — подтверждено" in summary
    assert "2. Встреча (ответственный неизвестен) — требует проверки" in summary
    assert "Черновик" not in summary


def test_build_summary_formats_due_time() -> None:
    agreement = _agreement(
        title="Созвон",
        owner=Owner.counterparty,
        status=AgreementStatus.needs_clarification,
        due_date=date(2026, 10, 16),
        due_time=time(15, 30),
    )

    summary = build_summary(_call(), [agreement])

    assert "1. Созвон (на клиента, срок 2026-10-16 15:30) — нужно уточнить" in summary


def test_llm_summary_prompt_includes_transcript_and_agreements() -> None:
    summarizer = InstructorLLMSummarizer(
        api_key="x", base_url="http://localhost:11434/v1", model="qwen2.5:7b"
    )
    data = SummaryInput(
        conversation_id="c1",
        client_label="Игорь",
        transcript=[
            TranscriptSegment(
                speaker="operator", text="я пришлю договор до пятницы", start=1.0, end=2.0
            )
        ],
        agreements=[
            AgreementFact(
                type="promise",
                title="Прислать договор",
                owner="counterparty",
                due="2026-10-09",
                status="detected",
            )
        ],
    )

    messages = summarizer._messages(data)
    system = messages[0]["content"]
    user = messages[1]["content"]

    assert "Игорь" in user
    assert "пришлю договор" in user
    assert "Прислать договор" in user
    assert "2026-10-09" in user
    assert "выдумывай" in system
