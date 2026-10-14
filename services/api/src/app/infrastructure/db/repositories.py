"""Thin data-access layer. Business rules live in ``app.domain``."""

from __future__ import annotations

import uuid
from collections.abc import Collection, Sequence
from datetime import date
from typing import Any, cast

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import ConsentSubjectType, ConsentType, TaskPriority
from app.infrastructure.db.models import (
    Agreement,
    AgreementEdit,
    AgreementExtraction,
    AuditLog,
    Call,
    CallAudio,
    Consent,
    IdempotencyKey,
    Reminder,
    Task,
    Team,
    Transcript,
    User,
)

USER_LIST_COLUMNS = (
    User.id,
    User.phone,
    User.full_name,
    User.role,
    User.team_id,
    User.timezone,
)


# ---- users ------------------------------------------------------------------


async def get_user_by_phone(session: AsyncSession, phone: str) -> User | None:
    result = await session.execute(select(User).where(User.phone == phone))
    return result.scalar_one_or_none()


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return cast("User | None", await session.get(User, user_id))


async def get_team(session: AsyncSession, team_id: uuid.UUID) -> Team | None:
    return cast("Team | None", await session.get(Team, team_id))


async def list_team_members(session: AsyncSession, team_id: uuid.UUID) -> Sequence[User]:
    result = await session.execute(
        select(User).where(User.team_id == team_id).order_by(User.full_name)
    )
    return result.scalars().all()


# ---- calls ------------------------------------------------------------------


async def get_call(session: AsyncSession, call_id: uuid.UUID) -> Call | None:
    return cast("Call | None", await session.get(Call, call_id))


async def get_call_by_external_id(session: AsyncSession, external_id: str) -> Call | None:
    """Find a call by the provider-side id (Exolve ``call_sid``)."""
    result = await session.execute(select(Call).where(Call.external_id == external_id))
    return result.scalar_one_or_none()


async def list_calls(session: AsyncSession, user_id: uuid.UUID, *, limit: int = 100) -> Sequence[Call]:
    result = await session.execute(
        select(Call).where(Call.user_id == user_id).order_by(Call.created_at.desc()).limit(limit)
    )
    return result.scalars().all()


async def list_calls_by_ids(
    session: AsyncSession, call_ids: Collection[uuid.UUID]
) -> Sequence[Call]:
    """Batch fetch for the manager board card (client / call-source metadata)."""
    if not call_ids:
        return []
    result = await session.execute(select(Call).where(Call.id.in_(call_ids)))
    return result.scalars().all()


# ---- audio and transcripts --------------------------------------------------


async def get_call_audio(session: AsyncSession, call_id: uuid.UUID) -> CallAudio | None:
    result = await session.execute(select(CallAudio).where(CallAudio.call_id == call_id))
    return result.scalar_one_or_none()


async def get_transcript(session: AsyncSession, call_id: uuid.UUID) -> Transcript | None:
    result = await session.execute(select(Transcript).where(Transcript.call_id == call_id))
    return result.scalar_one_or_none()


def build_transcript(
    *,
    call_id: uuid.UUID,
    language: str,
    full_text: str,
    segments: list[dict[str, object]],
    role_source: str,
    status: str = "done",
) -> Transcript:
    return Transcript(
        call_id=call_id,
        language=language,
        full_text=full_text,
        segments=segments,
        role_source=role_source,
        status=status,
    )


async def has_agreement_extractions(session: AsyncSession, call_id: uuid.UUID) -> bool:
    result = await session.execute(
        select(AgreementExtraction.id).where(AgreementExtraction.call_id == call_id).limit(1)
    )
    return result.scalar_one_or_none() is not None


# ---- agreements -------------------------------------------------------------


async def get_agreement(session: AsyncSession, agreement_id: uuid.UUID) -> Agreement | None:
    return cast("Agreement | None", await session.get(Agreement, agreement_id))


async def list_agreements_for_call(
    session: AsyncSession, call_id: uuid.UUID
) -> Sequence[Agreement]:
    result = await session.execute(
        select(Agreement).where(Agreement.call_id == call_id).order_by(Agreement.created_at)
    )
    return result.scalars().all()


async def list_agreements_for_user(
    session: AsyncSession, user_id: uuid.UUID, *, limit: int = 200
) -> Sequence[Agreement]:
    result = await session.execute(
        select(Agreement)
        .join(Call, Call.id == Agreement.call_id)
        .where(Call.user_id == user_id)
        .order_by(Agreement.updated_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


async def list_agreements_by_ids(
    session: AsyncSession, agreement_ids: Collection[uuid.UUID]
) -> Sequence[Agreement]:
    """Batch fetch for the manager board card (agreement type per task)."""
    if not agreement_ids:
        return []
    result = await session.execute(select(Agreement).where(Agreement.id.in_(agreement_ids)))
    return result.scalars().all()


async def count_agreements_by_member(
    session: AsyncSession, team_id: uuid.UUID
) -> dict[uuid.UUID, int]:
    """Agreements per team member: counts ``calls`` owned by each member (§15)."""
    result = await session.execute(
        select(Call.user_id, func.count(Agreement.id))
        .join(Agreement, Agreement.call_id == Call.id)
        .join(User, User.id == Call.user_id)
        .where(User.team_id == team_id)
        .group_by(Call.user_id)
    )
    return dict(result.all())


async def record_agreement_edit(
    session: AsyncSession,
    *,
    agreement_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    changes: dict[str, object],
) -> None:
    session.add(AgreementEdit(agreement_id=agreement_id, actor_user_id=actor_user_id, changes=changes))


# ---- tasks ------------------------------------------------------------------


async def get_task(session: AsyncSession, task_id: uuid.UUID) -> Task | None:
    return cast("Task | None", await session.get(Task, task_id))


async def get_task_for_agreement(session: AsyncSession, agreement_id: uuid.UUID) -> Task | None:
    """The task created from an agreement, if any (one per confirmed agreement)."""
    result = await session.execute(
        select(Task).where(Task.agreement_id == agreement_id).order_by(Task.created_at).limit(1)
    )
    return result.scalars().first()


async def list_tasks_for_user(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    priority: TaskPriority | None = None,
    due_before: date | None = None,
    due_after: date | None = None,
    limit: int = 500,
) -> Sequence[Task]:
    statement = select(Task).where(Task.assignee_user_id == user_id)
    if priority is not None:
        statement = statement.where(Task.priority == priority)
    if due_before is not None:
        statement = statement.where(Task.due_date <= due_before)
    if due_after is not None:
        statement = statement.where(Task.due_date >= due_after)
    result = await session.execute(
        statement.order_by(Task.due_date.asc().nulls_last(), Task.created_at.desc()).limit(limit)
    )
    return result.scalars().all()


def _task_team_statement(team_id: uuid.UUID) -> Select[Any]:
    return (
        select(Task)
        .join(User, User.id == Task.assignee_user_id)
        .where(User.team_id == team_id)
    )


async def list_tasks_for_team(
    session: AsyncSession,
    team_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None = None,
    priority: TaskPriority | None = None,
    due_before: date | None = None,
    due_after: date | None = None,
    agreement_type: str | None = None,
) -> Sequence[Task]:
    """Team tasks for the manager board.

    Filters that map directly to columns are pushed to SQL; the derived
    ``overdue`` status and the board ordering are resolved in the service
    (overdue depends on "today"). A ``status`` filter is therefore *not*
    applied here: stored and derived statuses are reconciled by the caller.
    """
    statement = _task_team_statement(team_id)
    if user_id is not None:
        statement = statement.where(Task.assignee_user_id == user_id)
    if priority is not None:
        statement = statement.where(Task.priority == priority)
    if due_before is not None:
        statement = statement.where(Task.due_date <= due_before)
    if due_after is not None:
        statement = statement.where(Task.due_date >= due_after)
    if agreement_type is not None:
        statement = statement.join(Agreement, Agreement.id == Task.agreement_id).where(
            Agreement.type == agreement_type
        )
    result = await session.execute(
        statement.order_by(Task.due_date.asc().nulls_last(), Task.created_at.desc())
    )
    return cast("Sequence[Task]", result.scalars().all())


async def count_tasks_for_team(
    session: AsyncSession, team_id: uuid.UUID, user_id: uuid.UUID | None = None
) -> int:
    statement = _task_team_statement(team_id)
    if user_id is not None:
        statement = statement.where(Task.assignee_user_id == user_id)
    result = await session.execute(statement)
    return len(result.scalars().all())


# ---- consents ---------------------------------------------------------------


async def latest_consent(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    subject_type: ConsentSubjectType,
    consent_type: ConsentType,
) -> Consent | None:
    """The latest **user-level** consent (``call_id`` is null).

    A per-call assertion written by the offline declaration (``call_id`` set,
    §13) must never shadow the user's global setting, so call-scoped rows are
    excluded here.
    """
    result = await session.execute(
        select(Consent)
        .where(
            Consent.user_id == user_id,
            Consent.subject_type == subject_type,
            Consent.consent_type == consent_type,
            Consent.call_id.is_(None),
        )
        .order_by(Consent.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def latest_call_consent(
    session: AsyncSession,
    *,
    call_id: uuid.UUID,
    consent_type: ConsentType,
    subject_type: ConsentSubjectType | None = None,
) -> Consent | None:
    """The latest consent scoped to one call (optionally by subject)."""
    query = select(Consent).where(
        Consent.call_id == call_id,
        Consent.consent_type == consent_type,
    )
    if subject_type is not None:
        query = query.where(Consent.subject_type == subject_type)
    result = await session.execute(
        query.order_by(Consent.created_at.desc()).limit(1)
    )
    return result.scalar_one_or_none()


# ---- audit ------------------------------------------------------------------


async def record_audit(
    session: AsyncSession,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    action: str,
    actor_user_id: uuid.UUID | None,
    payload: dict[str, object] | None = None,
) -> None:
    session.add(
        AuditLog(
            entity_type=entity_type,
            entity_id=entity_id,
            actor_user_id=actor_user_id,
            action=action,
            payload=payload,
        )
    )


# ---- idempotency ------------------------------------------------------------


async def get_idempotent_response(
    session: AsyncSession, *, user_id: uuid.UUID, scope: str, key: str
) -> IdempotencyKey | None:
    result = await session.execute(
        select(IdempotencyKey).where(
            IdempotencyKey.user_id == user_id,
            IdempotencyKey.scope == scope,
            IdempotencyKey.key == key,
        )
    )
    return result.scalar_one_or_none()


async def store_idempotent_response(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    scope: str,
    key: str,
    request_hash: str,
    response_status: int,
    response_body: dict[str, object],
) -> None:
    session.add(
        IdempotencyKey(
            user_id=user_id,
            scope=scope,
            key=key,
            request_hash=request_hash,
            response_status=response_status,
            response_body=response_body,
        )
    )


# ---- reminders --------------------------------------------------------------


async def get_reminder(session: AsyncSession, reminder_id: uuid.UUID) -> Reminder | None:
    return cast("Reminder | None", await session.get(Reminder, reminder_id))


async def list_reminders_for_task(
    session: AsyncSession, task_id: uuid.UUID
) -> Sequence[Reminder]:
    result = await session.execute(
        select(Reminder).where(Reminder.task_id == task_id).order_by(Reminder.remind_at)
    )
    return result.scalars().all()