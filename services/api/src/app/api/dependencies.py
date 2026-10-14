"""FastAPI dependencies: session, cache, settings, current user."""

from __future__ import annotations

import hmac
import uuid
from collections.abc import AsyncIterator
from typing import cast

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.errors import PermissionDenied
from app.infrastructure.cache import Cache
from app.infrastructure.db import repositories
from app.infrastructure.db.models import User
from app.infrastructure.security import ACCESS, TokenError, decode_token
from app.services.access import AccessService
from app.services.agreement import AgreementService
from app.services.auth import AuthService
from app.services.call_session import CallSessionService
from app.services.consent import ConsentService
from app.services.manager import ManagerDashboardService
from app.services.provider_recording import ProviderRecordingService
from app.services.schedule import ScheduleService
from app.services.sync import SyncService
from app.services.task import TaskService
from app.services.voice_webhooks import ExolveWebhookService


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        yield session


def get_cache(request: Request) -> Cache:
    return cast(Cache, request.app.state.cache)


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> User:
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        raise TokenError("missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    payload = decode_token(token, settings=request.app.state.settings, expected_type=ACCESS)
    user = await repositories.get_user(session, uuid.UUID(str(payload["sub"])))
    if user is None or not user.is_active:
        raise PermissionDenied("user is inactive")
    return user


def require_voice_webhook(request: Request) -> None:
    expected = request.app.state.settings.voice_webhook_secret
    # The mock/demo driver signs with a header; Exolve cannot set custom headers
    # on its callbacks, so the shared secret is accepted from the query string too
    # (the callback URL is configured per SIP resource).
    header = request.headers.get("X-Voice-Webhook-Secret", "")
    query = request.query_params.get("secret", "")
    if not (
        hmac.compare_digest(header, expected) or hmac.compare_digest(query, expected)
    ):
        raise PermissionDenied("invalid voice webhook secret")


# -- service containers --------------------------------------------------------


def get_consent_service(session: AsyncSession = Depends(get_session)) -> ConsentService:
    return ConsentService(session)


def get_task_service(session: AsyncSession = Depends(get_session)) -> TaskService:
    return TaskService(session)


def get_schedule_service(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> ScheduleService:
    return ScheduleService(
        session,
        calendar=request.app.state.calendar,
        reminders=request.app.state.reminders,
        messaging=request.app.state.messaging,
        jobs=request.app.state.analysis_queue,
    )


def get_agreement_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    tasks: TaskService = Depends(get_task_service),
) -> AgreementService:
    return AgreementService(session, settings, tasks)


def get_access_service(session: AsyncSession = Depends(get_session)) -> AccessService:
    return AccessService(session)


def get_sync_service(
    session: AsyncSession = Depends(get_session),
    tasks: TaskService = Depends(get_task_service),
    agreements: AgreementService = Depends(get_agreement_service),
) -> SyncService:
    return SyncService(session, tasks, agreements)


def get_manager_service(
    session: AsyncSession = Depends(get_session),
    access: AccessService = Depends(get_access_service),
) -> ManagerDashboardService:
    return ManagerDashboardService(session, access)


def get_call_session_service(
    request: Request,
    session: AsyncSession = Depends(get_session),
    consents: ConsentService = Depends(get_consent_service),
    settings: Settings = Depends(get_settings),
) -> CallSessionService:
    return CallSessionService(
        session,
        voice=request.app.state.voice_provider,
        consents=consents,
        events=request.app.state.event_hub,
        settings=settings,
        analysis=request.app.state.analysis_queue,
    )


def get_auth_service(
    session: AsyncSession = Depends(get_session),
    cache: Cache = Depends(get_cache),
    settings: Settings = Depends(get_settings),
) -> AuthService:
    return AuthService(session, cache, settings)


def get_provider_recording_service(
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ProviderRecordingService:
    """API-side view: records the ``crr`` record id and queues the worker job.

    The download itself runs in a worker (an Exolve callback must be answered
    quickly), so the API instance needs no provider HTTP client.
    """
    return ProviderRecordingService(
        session,
        settings=settings,
        storage=request.app.state.storage,
        analysis=request.app.state.analysis_queue,
    )


def get_exolve_webhook_service(
    request: Request,
    session: AsyncSession = Depends(get_session),
    calls: CallSessionService = Depends(get_call_session_service),
    recordings: ProviderRecordingService = Depends(get_provider_recording_service),
    settings: Settings = Depends(get_settings),
) -> ExolveWebhookService:
    return ExolveWebhookService(session, settings=settings, calls=calls, recordings=recordings)
