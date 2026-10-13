"""Consent records. The consent flow is the product's critical path."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import (
    ConsentMethod,
    ConsentStatus,
    ConsentSubjectType,
    ConsentType,
)
from app.domain.errors import ConsentRequired, NotFound
from app.domain.rules import BLOCKING_CONSENT_STATUSES
from app.infrastructure.db import repositories
from app.infrastructure.db.models import Call, Consent, User

CONSENT_VERSION = "v1"


class ConsentService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def latest_app_recording_consent(self, user_id: uuid.UUID) -> Consent | None:
        return await repositories.latest_consent(
            self._session,
            user_id=user_id,
            subject_type=ConsentSubjectType.app_user,
            consent_type=ConsentType.recording,
        )

    async def set_app_consent(self, user: User, *, granted: bool) -> Consent:
        """App-level consent from the settings screen (method ``app_settings``)."""
        consent = Consent(
            user_id=user.id,
            subject_type=ConsentSubjectType.app_user,
            consent_type=ConsentType.recording,
            status=ConsentStatus.granted if granted else ConsentStatus.denied,
            method=ConsentMethod.app_settings,
            text_version=CONSENT_VERSION,
            granted_at=datetime.now(UTC) if granted else None,
        )
        self._session.add(consent)
        await self._session.flush()
        await repositories.record_audit(
            self._session,
            entity_type="consent",
            entity_id=consent.id,
            action="consent.set_app",
            actor_user_id=user.id,
            payload={"status": consent.status.value},
        )
        await self._session.flush()
        return consent

    async def record_participant_consent(
        self,
        *,
        call_id: uuid.UUID,
        status: ConsentStatus,
        method: ConsentMethod,
        user_id: uuid.UUID | None = None,
    ) -> Consent:
        consent = Consent(
            user_id=user_id,
            subject_type=ConsentSubjectType.call_participant,
            call_id=call_id,
            consent_type=ConsentType.recording,
            status=status,
            method=method,
            text_version=CONSENT_VERSION,
            granted_at=datetime.now(UTC) if status is ConsentStatus.granted else None,
        )
        self._session.add(consent)
        await self._session.flush()
        await repositories.record_audit(
            self._session,
            entity_type="consent",
            entity_id=consent.id,
            action="consent.participant",
            actor_user_id=user_id,
            payload={"call_id": str(call_id), "status": status.value, "method": method.value},
        )
        await self._session.flush()
        return consent

    async def withdraw(self, user: User) -> Consent:
        latest = await self.latest_app_recording_consent(user.id)
        if latest is None:
            raise NotFound("no app consent to withdraw")
        latest.status = ConsentStatus.withdrawn
        latest.withdrawn_at = datetime.now(UTC)
        await repositories.record_audit(
            self._session,
            entity_type="consent",
            entity_id=latest.id,
            action="consent.withdrawn",
            actor_user_id=user.id,
        )
        return latest


def require_recording_allowed(call: Call, app_consent: Consent | None, participant: Consent | None) -> None:
    """Domain gate: no bypass, not even in tests or demo mode."""
    from app.domain.rules import decide_recording

    decision = decide_recording(
        call.status,
        app_consent=app_consent.status if app_consent else None,
        participant_consent=participant.status if participant else None,
    )
    if not decision.allowed:
        raise ConsentRequired(decision.raise_reason())
    for existing in (app_consent, participant):
        if existing and existing.status in BLOCKING_CONSENT_STATUSES:
            raise ConsentRequired(f"consent {existing.status.value}")


def is_blocked(status: ConsentStatus | None) -> bool:
    return status in BLOCKING_CONSENT_STATUSES