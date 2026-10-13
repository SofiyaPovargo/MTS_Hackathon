"""HTTP routes for the agreement-capture API.

Endpoints: /auth/login, /calls, /sync, /me/tasks, /tasks/{id} (PATCH),
/tasks/{id}/complete, /manager/team/tasks, /manager/team/stats,
/manager/team/members — plus the consent and agreement actions the product
rules require.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
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
    get_session,
    get_sync_service,
    get_task_service,
    require_voice_webhook,
)
from app.domain.errors import (
    NotFound,
    PermissionDenied,
    ValidationFailed,
)
from app.infrastructure.cache import Cache
from app.infrastructure.db import repositories
from app.infrastructure.db.models import User
from app.services.agreement import AgreementService
from app.services.auth import AuthService
from app.services.call_session import CallSessionService, get_call_or_404
from app.services.consent import ConsentService
from app.services.manager import ManagerDashboardService
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