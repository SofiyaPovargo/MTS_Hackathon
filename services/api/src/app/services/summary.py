"""Итог звонка (``plan.md`` §9, Этап 9): резюме разговора.

Резюме собирается **детерминированно** из уже извлечённых и провалидированных
договорённостей звонка (как и черновик письма в ``schedule.py``): мы не
придумываем факты, которых нет в данных, не подставляем даты/суммы, которых не
было в разговоре, и не зависим от доступности LLM. Текст — производная величина
от договорённостей; он кэшируется в ``calls.summary`` (виден в
``GET /calls/{id}``, sync и в событии ``call_ended``).

Пайплайн обновляет резюме после извлечения (``ml.pipeline``), а эндпоинт
итога всегда пересобирает его из актуальных договорённостей, поэтому правка или
подтверждение договорённости не оставляют устаревший текст.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import AgreementStatus, Owner
from app.infrastructure.db import repositories
from app.infrastructure.db.models import Agreement, Call

_OWNER_LABELS: dict[Owner, str] = {
    Owner.user: "на нас",
    Owner.counterparty: "на клиента",
    Owner.unknown: "ответственный неизвестен",
}

_STATUS_LABELS: dict[AgreementStatus, str] = {
    AgreementStatus.detected: "обнаружено",
    AgreementStatus.requires_review: "требует проверки",
    AgreementStatus.needs_clarification: "нужно уточнить",
    AgreementStatus.confirmed: "подтверждено",
}


def _due_text(agreement: Agreement) -> str | None:
    if agreement.due_date is None:
        return None
    if agreement.due_time is None:
        return agreement.due_date.isoformat()
    return f"{agreement.due_date.isoformat()} {agreement.due_time.strftime('%H:%M')}"


def _describe(agreement: Agreement) -> str:
    details: list[str] = []
    owner = _OWNER_LABELS.get(agreement.owner)
    if owner is not None:
        details.append(owner)
    due = _due_text(agreement)
    if due is not None:
        details.append(f"срок {due}")
    suffix = f" ({', '.join(details)})" if details else ""
    status = _STATUS_LABELS.get(agreement.status, agreement.status.value)
    return f"{agreement.title}{suffix} — {status}"


def active_agreements(agreements: Sequence[Agreement]) -> list[Agreement]:
    """Rejected agreements are not part of the outcome of a call."""
    return [agreement for agreement in agreements if agreement.status is not AgreementStatus.rejected]


def build_summary(call: Call, agreements: Sequence[Agreement]) -> str:
    """Deterministic Russian summary of a call from its agreements."""
    client = call.contact_name or call.contact_phone
    active = active_agreements(agreements)
    if not active:
        return f"Итог звонка с {client}: договорённости не выделены."
    confirmed = sum(1 for agreement in active if agreement.status is AgreementStatus.confirmed)
    lines = [
        f"Итог звонка с {client}. Договорённостей: {len(active)}, подтверждено: {confirmed}."
    ]
    lines.extend(
        f"{index}. {_describe(agreement)}" for index, agreement in enumerate(active, start=1)
    )
    return "\n".join(lines)


class CallSummaryService:
    """Builds and stores the call summary; access is checked by the caller."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def refresh(self, call: Call) -> str:
        agreements = await repositories.list_agreements_for_call(self._session, call.id)
        call.summary = build_summary(call, agreements)
        await self._session.flush()
        return call.summary

    async def summary_for(self, call: Call) -> dict[str, object]:
        """Rebuild from current agreements, persist, and return the итог + counts."""
        agreements = active_agreements(
            await repositories.list_agreements_for_call(self._session, call.id)
        )
        call.summary = build_summary(call, agreements)
        await self._session.flush()
        confirmed = sum(1 for agreement in agreements if agreement.status is AgreementStatus.confirmed)
        return {
            "call_id": call.id,
            "summary": call.summary,
            "agreements_total": len(agreements),
            "agreements_confirmed": confirmed,
        }


async def generate_call_summary(session: AsyncSession, call_id: uuid.UUID) -> str | None:
    """Pipeline hook: refresh ``calls.summary`` for an existing call (no-op if absent)."""
    call = await repositories.get_call(session, call_id)
    if call is None:
        return None
    return await CallSummaryService(session).refresh(call)


__all__ = [
    "CallSummaryService",
    "active_agreements",
    "build_summary",
    "generate_call_summary",
]
