"""HTTP routes for the agreement-capture API.

Endpoints: /auth/login, /calls, /sync, /me/tasks, /tasks/{id} (PATCH),
/tasks/{id}/complete, /manager/team/tasks, /manager/team/stats,
/manager/team/members — plus the consent and agreement actions the product
rules require.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import schemas
from app.api.dependencies import (
    get_agreement_service,
    get_auth_service,
    get_cache,
    get_call_session_service,
    get_consent_service,
    get_current_user,
    get_manager_service,
    get_schedule_service,
    get_session,
    get_sync_service,
    get_task_service,
    require_voice_webhook,
)
from app.domain.errors import (
    Conflict,
    NotFound,
    PermissionDenied,
    ValidationFailed,
)
from app.infrastructure.cache import Cache
from app.infrastructure.db import repositories
from app.infrastructure.db.models import User
from app.services.agreement import AgreementService
from app.services.audio_ingest import AudioIngestService, AudioUpload
from app.services.auth import AuthService
from app.services.call_session import CallSessionService, get_call_or_404
from app.services.consent import ConsentService
from app.services.manager import ManagerDashboardService
from app.services.schedule import ScheduleService
from app.services.sync import SyncService
from app.services.task import TaskService

router = APIRouter()


# ---- auth -------------------------------------------------------------------


@router.post("/auth/otp/request", status_code=204)
async def request_otp(payload: schemas.OtpRequest, service: AuthService = Depends(get_auth_service)) -> None:
    await service.request_otp(payload.phone)


@router.post("/auth/login", response_model=schemas.AuthResponse)
async def login(
    payload: schemas.LoginRequest,
    service: AuthService = Depends(get_auth_service),
) -> schemas.AuthResponse:
    result = await service.login(payload.phone, payload.otp)
    return schemas.AuthResponse.model_validate(result, from_attributes=True)


@router.post("/auth/refresh", response_model=schemas.AuthResponse)
async def refresh(
    payload: schemas.RefreshRequest,
    service: AuthService = Depends(get_auth_service),
) -> schemas.AuthResponse:
    result = await service.refresh(payload.refresh_token)
    return schemas.AuthResponse.model_validate(result, from_attributes=True)


@router.post("/auth/logout", status_code=204)
async def logout(payload: schemas.RefreshRequest, service: AuthService = Depends(get_auth_service)) -> None:
    await service.logout(payload.refresh_token)


# ---- me ---------------------------------------------------------------------


@router.get("/me", response_model=schemas.UserOut)
async def me(user: User = Depends(get_current_user)) -> schemas.UserOut:
    return schemas.UserOut.model_validate(user, from_attributes=True)


@router.put("/me/consent", response_model=schemas.ConsentOut)
async def set_app_consent(
    payload: schemas.ConsentSetRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    consents: ConsentService = Depends(get_consent_service),
) -> schemas.ConsentOut:
    consent = await consents.set_app_consent(user, granted=payload.granted)
    await session.commit()
    return schemas.ConsentOut.model_validate(consent, from_attributes=True)


@router.post("/me/consent/withdraw", response_model=schemas.ConsentOut)
async def withdraw_consent(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    consents: ConsentService = Depends(get_consent_service),
) -> schemas.ConsentOut:
    consent = await consents.withdraw(user)
    await session.commit()
    return schemas.ConsentOut.model_validate(consent, from_attributes=True)


@router.post("/me/data/delete", status_code=202)
async def request_data_deletion(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    consents: ConsentService = Depends(get_consent_service),
    cache: Cache = Depends(get_cache),
) -> dict[str, str]:
    """Real deletion flow: withdraw consent, audit, and enqueue the job."""
    await consents.withdraw(user)
    await repositories.record_audit(
        session,
        entity_type="user",
        entity_id=user.id,
        action="data.deletion_requested",
        actor_user_id=user.id,
    )
    await cache.lpush("jobs:data-deletion", str(user.id))
    await session.commit()
    return {"status": "scheduled", "message": "data deletion requested"}


# ---- calls ------------------------------------------------------------------


@router.post("/calls", response_model=schemas.CallOut, status_code=201)
async def create_call(
    payload: schemas.CallCreateRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    calls: CallSessionService = Depends(get_call_session_service),
) -> schemas.CallOut:
    call = await calls.create_call(
        user,
        direction=payload.direction,
        contact_phone=payload.callee_phone,
        contact_name=payload.contact_name,
        external_id=payload.external_id,
    )
    await session.commit()
    return schemas.CallOut.model_validate(call, from_attributes=True)


@router.get("/calls", response_model=list[schemas.CallOut])
async def list_calls(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[schemas.CallOut]:
    calls = await repositories.list_calls(session, user.id)
    return [schemas.CallOut.model_validate(call, from_attributes=True) for call in calls]


@router.get("/calls/{call_id}", response_model=schemas.CallOut)
async def get_call(
    call_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> schemas.CallOut:
    call = await get_call_or_404(session, call_id)
    await _require_call_owner(user, call.user_id)
    return schemas.CallOut.model_validate(call, from_attributes=True)


@router.post(
    "/calls/{call_id}/events",
    response_model=schemas.CallOut,
    dependencies=[Depends(require_voice_webhook)],
)
async def call_provider_event(
    call_id: uuid.UUID,
    payload: schemas.CallEventRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    calls: CallSessionService = Depends(get_call_session_service),
) -> schemas.CallOut:
    """Webhook from the Voice Provider (or the demo driver)."""
    call = await get_call_or_404(session, call_id)
    owner = await repositories.get_user(session, call.user_id)
    if owner is None:
        raise NotFound("call owner not found")
    call = await calls.handle_provider_event(owner, call, payload.event, at=payload.at)
    await session.commit()
    return schemas.CallOut.model_validate(call, from_attributes=True)


@router.post(
    "/calls/{call_id}/analyze",
    response_model=schemas.CallAnalyzeResponse,
    status_code=202,
)
async def analyze_call(
    call_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> schemas.CallAnalyzeResponse:
    """Queue ASR + extraction for a recorded call and return immediately.

    The pipeline is asynchronous (queue -> worker-asr -> worker-ai); this only
    enqueues the job. Recording exists solely after ``answered`` + consent.
    """
    call = await get_call_or_404(session, call_id)
    await _require_call_owner(user, call.user_id)
    if call.recording_started_at is None:
        raise Conflict("call was not recorded")
    request.app.state.analysis_queue.enqueue_asr(str(call.id))
    return schemas.CallAnalyzeResponse(call_id=call.id, status="queued")


@router.post(
    "/calls/{call_id}/audio",
    response_model=schemas.CallAudioAccepted,
    status_code=202,
    # The body is the raw recording (binary), so it is not a Pydantic model.
    # Declare it explicitly: the generated API client sends the bytes as-is and
    # nothing is spooled to the container filesystem.
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "audio/wav": {"schema": {"type": "string", "format": "binary"}},
                "audio/ogg": {"schema": {"type": "string", "format": "binary"}},
                "audio/opus": {"schema": {"type": "string", "format": "binary"}},
                "audio/mpeg": {"schema": {"type": "string", "format": "binary"}},
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}},
            },
        }
    },
)
async def upload_call_audio(
    call_id: uuid.UUID,
    request: Request,
    leg: str | None = Query(default=None, pattern="^(operator|client)$"),
    duration_sec: int | None = Query(default=None, ge=0),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> schemas.CallAudioAccepted:
    """Upload the recorded audio of a call; ASR is queued once it is complete.

    The mobile client POSTs the raw audio as the request body (``Content-Type:
    audio/*``). Without ``?leg`` it is the mixed stream; with ``?leg=operator``
    or ``?leg=client`` it is one per-leg track — upload both for channel
    separation. Refused unless the call was recorded (``answered`` + consent);
    an oversized body is 413, an unsupported type is 422, a foreign call is 403.
    """
    call = await get_call_or_404(session, call_id)
    await _require_call_owner(user, call.user_id)

    service = AudioIngestService(
        session,
        storage=request.app.state.storage,
        analysis=request.app.state.analysis_queue,
        settings=request.app.state.settings,
    )
    service.check_declared_size(request.headers.get("content-length"))
    body = await request.body()
    audio, queued = await service.ingest(
        user,
        call,
        upload=AudioUpload(body, request.headers.get("content-type")),
        role=leg,
        duration_sec=duration_sec,
    )
    await session.commit()
    return schemas.CallAudioAccepted(
        call_id=call.id,
        role=leg,
        content_type=audio.content_type,
        bytes_stored=len(body),
        legs_present=sorted((audio.channel_urls or {}).keys()),
        analysis_queued=queued,
    )


# ---- agreements ---------------------------------------------------------------


@router.get("/calls/{call_id}/agreements", response_model=list[schemas.AgreementOut])
async def list_call_agreements(
    call_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[schemas.AgreementOut]:
    call = await get_call_or_404(session, call_id)
    await _require_call_owner(user, call.user_id)
    agreements = await repositories.list_agreements_for_call(session, call_id)
    return [schemas.AgreementOut.model_validate(a, from_attributes=True) for a in agreements]


@router.post("/calls/{call_id}/agreements", response_model=schemas.AgreementOut, status_code=201)
async def create_manual_agreement(
    call_id: uuid.UUID,
    payload: schemas.AgreementCreateManualRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    agreements: AgreementService = Depends(get_agreement_service),
) -> schemas.AgreementOut:
    """Manual entry (no-consent path / user corrections)."""
    call = await get_call_or_404(session, call_id)
    await _require_call_owner(user, call.user_id)
    agreement = await agreements.create_manual(
        user,
        call,
        type=payload.type,
        title=payload.title,
        object=payload.object,
        owner=payload.owner,
        owner_user_id=payload.owner_user_id,
        due_date=payload.due_date,
        due_time=payload.due_time,
        amount=payload.amount,
        currency=payload.currency,
    )
    await session.commit()
    return schemas.AgreementOut.model_validate(agreement, from_attributes=True)


@router.get("/me/agreements", response_model=list[schemas.AgreementOut])
async def list_my_agreements(
    user: User = Depends(get_current_user),
    agreements: AgreementService = Depends(get_agreement_service),
) -> list[schemas.AgreementOut]:
    rows = await agreements.list_for_user(user)
    return [schemas.AgreementOut.model_validate(a, from_attributes=True) for a in rows]


@router.patch("/agreements/{agreement_id}", response_model=schemas.AgreementOut)
async def patch_agreement(
    agreement_id: uuid.UUID,
    payload: schemas.AgreementPatchRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    agreements: AgreementService = Depends(get_agreement_service),
) -> schemas.AgreementOut:
    agreement = await agreements.get_owned(user, agreement_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise ValidationFailed("no fields to update")
    agreement = await agreements.patch(user, agreement, changes)
    await session.commit()
    return schemas.AgreementOut.model_validate(agreement, from_attributes=True)


@router.post("/agreements/{agreement_id}/confirm", response_model=schemas.AgreementOut)
async def confirm_agreement(
    agreement_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    agreements: AgreementService = Depends(get_agreement_service),
) -> schemas.AgreementOut:
    agreement = await agreements.get_owned(user, agreement_id)
    agreement = await agreements.confirm(user, agreement)
    await session.commit()
    return schemas.AgreementOut.model_validate(agreement, from_attributes=True)


@router.post("/agreements/{agreement_id}/reject", response_model=schemas.AgreementOut)
async def reject_agreement(
    agreement_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    agreements: AgreementService = Depends(get_agreement_service),
) -> schemas.AgreementOut:
    agreement = await agreements.get_owned(user, agreement_id)
    agreement = await agreements.reject(user, agreement)
    await session.commit()
    return schemas.AgreementOut.model_validate(agreement, from_attributes=True)


# ---- tasks -------------------------------------------------------------------


@router.get("/me/tasks", response_model=list[schemas.TaskOut])
async def list_my_tasks(
    user: User = Depends(get_current_user),
    tasks: TaskService = Depends(get_task_service),
) -> list[schemas.TaskOut]:
    rows = await tasks.list_for_user(user)
    return [schemas.TaskOut.model_validate(task, from_attributes=True) for task in rows]


@router.patch("/tasks/{task_id}", response_model=schemas.TaskOut)
async def patch_task(
    task_id: uuid.UUID,
    payload: schemas.TaskPatchRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    tasks: TaskService = Depends(get_task_service),
) -> schemas.TaskOut:
    task = await tasks.get_for_user(user, task_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise ValidationFailed("no fields to update")
    task = await tasks.patch(user, task, changes)
    await session.commit()
    return schemas.TaskOut.model_validate(task, from_attributes=True)


@router.post("/tasks/{task_id}/complete", response_model=schemas.TaskOut)
async def complete_task(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    tasks: TaskService = Depends(get_task_service),
) -> schemas.TaskOut:
    task = await tasks.get_for_user(user, task_id)
    task = await tasks.complete(user, task)
    await session.commit()
    return schemas.TaskOut.model_validate(task, from_attributes=True)


# ---- calendar / reminders / draft (only after confirmation) ---------------------


@router.post("/tasks/{task_id}/calendar", response_model=schemas.CalendarEventOut)
async def create_task_calendar_event(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    tasks: TaskService = Depends(get_task_service),
    schedule: ScheduleService = Depends(get_schedule_service),
) -> schemas.CalendarEventOut:
    """Explicit user action: write the confirmed task into the calendar."""
    task = await tasks.get_for_user(user, task_id)
    result = await schedule.calendar_event(user, task)
    await session.commit()
    return schemas.CalendarEventOut.model_validate(result)


@router.get("/tasks/{task_id}/calendar.ics")
async def download_task_ics(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    tasks: TaskService = Depends(get_task_service),
    schedule: ScheduleService = Depends(get_schedule_service),
) -> Response:
    """Portable ``.ics`` — no external system is touched."""
    task = await tasks.get_for_user(user, task_id)
    content = await schedule.ics(user, task)
    return Response(
        content=content,
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="task-{task.id}.ics"'},
    )


@router.post("/tasks/{task_id}/reminders", response_model=schemas.ReminderOut, status_code=201)
async def create_task_reminder(
    task_id: uuid.UUID,
    payload: schemas.ReminderCreateRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    tasks: TaskService = Depends(get_task_service),
    schedule: ScheduleService = Depends(get_schedule_service),
) -> schemas.ReminderOut:
    task = await tasks.get_for_user(user, task_id)
    reminder = await schedule.create_reminder(
        user, task, remind_at=payload.remind_at, channel=payload.channel
    )
    await session.commit()
    return schemas.ReminderOut.model_validate(reminder, from_attributes=True)


@router.get("/tasks/{task_id}/reminders", response_model=list[schemas.ReminderOut])
async def list_task_reminders(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    tasks: TaskService = Depends(get_task_service),
    schedule: ScheduleService = Depends(get_schedule_service),
) -> list[schemas.ReminderOut]:
    task = await tasks.get_for_user(user, task_id)
    rows = await schedule.list_reminders(task)
    return [schemas.ReminderOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("/reminders/{reminder_id}/cancel", response_model=schemas.ReminderOut)
async def cancel_reminder(
    reminder_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    tasks: TaskService = Depends(get_task_service),
    schedule: ScheduleService = Depends(get_schedule_service),
) -> schemas.ReminderOut:
    reminder = await repositories.get_reminder(session, reminder_id)
    if reminder is None:
        raise NotFound("reminder not found")
    task = await tasks.get_for_user(user, reminder.task_id)
    reminder = await schedule.cancel_reminder(user, task, reminder)
    await session.commit()
    return schemas.ReminderOut.model_validate(reminder, from_attributes=True)


@router.post("/tasks/{task_id}/message-draft", response_model=schemas.MessageDraftOut)
async def draft_task_message(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    tasks: TaskService = Depends(get_task_service),
    schedule: ScheduleService = Depends(get_schedule_service),
) -> schemas.MessageDraftOut:
    """Draft a client message. It is never sent automatically."""
    task = await tasks.get_for_user(user, task_id)
    result = await schedule.draft_message(user, task)
    await session.commit()
    return schemas.MessageDraftOut.model_validate(result)


# ---- manager board -------------------------------------------------------------


@router.get("/manager/team/tasks")
async def manager_team_tasks(
    user_id: uuid.UUID | None = None,
    status: str | None = None,
    due_before: str | None = None,
    user: User = Depends(get_current_user),
    manager: ManagerDashboardService = Depends(get_manager_service),
) -> list[dict[str, object]]:
    from datetime import date as _date

    builtin: _date | None = None
    if due_before is not None:
        builtin = _date.fromisoformat(due_before)
    return await manager.team_tasks(user, user_id=user_id, status=status, due_before=builtin)


@router.get("/manager/team/stats")
async def manager_team_stats(
    user: User = Depends(get_current_user),
    manager: ManagerDashboardService = Depends(get_manager_service),
) -> dict[str, object]:
    return await manager.team_stats(user)


@router.get("/manager/team/members")
async def manager_team_members(
    user: User = Depends(get_current_user),
    manager: ManagerDashboardService = Depends(get_manager_service),
) -> list[dict[str, object]]:
    return await manager.team_members(user)


# ---- sync ---------------------------------------------------------------------


@router.get("/sync", response_model=schemas.SyncPullResponse)
async def sync_pull(
    since: str | None = Query(default=None, description="ISO-8601 sync token"),
    user: User = Depends(get_current_user),
    sync: SyncService = Depends(get_sync_service),
) -> schemas.SyncPullResponse:
    from datetime import UTC, datetime

    parsed = datetime.fromisoformat(since).replace(tzinfo=UTC) if since else None
    result = await sync.pull(user, parsed)
    return schemas.SyncPullResponse.model_validate(result)


@router.post("/sync", response_model=schemas.SyncPushResponse)
async def sync_push(
    payload: schemas.SyncPushRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    sync: SyncService = Depends(get_sync_service),
) -> schemas.SyncPushResponse:
    operations = [op.model_dump(mode="json") for op in payload.operations]
    result = await sync.push(user, operations)
    await session.commit()
    return schemas.SyncPushResponse.model_validate(result)


# ---- health --------------------------------------------------------------------


@router.get("/healthz")
async def healthz(
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    from sqlalchemy import text

    await session.execute(text("SELECT 1"))
    return {"status": "ok"}


async def _require_call_owner(user: User, call_user_id: uuid.UUID) -> None:
    if user.id != call_user_id:
        raise PermissionDenied("call belongs to another user")