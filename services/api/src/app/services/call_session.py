"""Call session: lifecycle transitions and the consent-gated recording start."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.domain.enums import (
    CallDirection,
    CallEvent,
    CallStatus,
    ConsentMethod,
    ConsentStatus,
)
from app.domain.errors import Conflict, InvalidStateTransition, NotFound
from app.domain.state_machine import is_terminal, next_status
from app.infrastructure.db import repositories
from app.infrastructure.db.models import Call, User
from app.integrations.voice import VoiceProviderPort
from app.services.consent import ConsentService, require_recording_allowed
from app.services.events import CallEventMessage
from app.services.jobs import AnalysisQueuePort


class EventsPort(Protocol):
    async def emit(self, message: CallEventMessage) -> None: ...


class CallSessionService:
    """Owns ``Call`` records and the consent gate around recording."""

    def __init__(
        self,
        session: AsyncSession,
        voice: VoiceProviderPort,
        consents: ConsentService,
        events: EventsPort,
        settings: Settings,
        analysis: AnalysisQueuePort | None = None,
    ) -> None:
        self._session = session
        self._voice = voice
        self._consents = consents
        self._events = events
        self._settings = settings
        self._analysis = analysis
        self._stream_id: str | None = None

    # -- creation -------------------------------------------------------------

    async def create_call(
        self,
        user: User,
        *,
        direction: CallDirection,
        contact_phone: str,
        contact_name: str | None,
        external_id: str | None = None,
    ) -> Call:
        initial = CallStatus.incoming if direction is CallDirection.inbound else CallStatus.ringing
        call = Call(
            user_id=user.id,
            direction=direction,
            contact_phone=contact_phone,
            contact_name=contact_name,
            external_id=external_id,
            status=initial,
            started_at=datetime.now(UTC),
        )
        self._session.add(call)
        await self._session.flush()
        await repositories.record_audit(
            self._session,
            entity_type="call",
            entity_id=call.id,
            action="call.created",
            actor_user_id=user.id,
            payload={"direction": direction.value},
        )
        return call

    # -- provider events ------------------------------------------------------

    async def handle_provider_event(
        self, actor: User, call: Call, event: CallEvent, at: datetime | None = None
    ) -> Call:
        timestamp = at or datetime.now(UTC)
        if event is CallEvent.answered:
            await self._on_answered(actor, call, timestamp)
        elif event is CallEvent.ringing:
            await self._transition(call, CallStatus.ringing, actor)
        elif event is CallEvent.incoming:
            if call.status is CallStatus.incoming:
                return call  # provider push duplicated the event
            await self._transition(call, CallStatus.incoming, actor)
        elif event is CallEvent.ended:
            call.ended_at = timestamp
            await self._transition(call, CallStatus.completed, actor)
            await self._events.emit(
                CallEventMessage(
                    event="call_ended",
                    call_id=call.id,
                    payload={"duration_sec": 0, "summary": call.summary},
                )
            )
            await self._maybe_enqueue_analysis(call)
        elif event is CallEvent.dropped:
            call.ended_at = timestamp
            await self._transition(call, CallStatus.failed, actor)
        elif event is CallEvent.missed:
            call.ended_at = timestamp
            await self._transition(call, CallStatus.missed, actor)
        else:
            raise InvalidStateTransition(call.status.value, event.value)

        call.updated_at = timestamp
        await self._session.flush()
        return call

    # -- consent flow ---------------------------------------------------------

    async def _on_answered(self, actor: User, call: Call, at: datetime) -> None:
        call.answered_at = at
        # The lifecycle fixes ``answered`` as a real intermediate state:
        # ``ringing -> answered -> (consent flow)``.
        await self._transition(call, CallStatus.answered, actor)
        app_consent = await self._consents.latest_app_recording_consent(call.user_id)

        # 1-2. No app consent -> ordinary call, recording is never enabled.
        if app_consent is None or app_consent.status is not ConsentStatus.granted:
            await self._transition(call, CallStatus.in_progress, actor)
            return

        # 3. Play the audio notice to the other party.
        await self._transition(call, CallStatus.consent_notice, actor)
        assert call.external_id, "provider call id is required to play the notice"
        await self._voice.play_notice(call.external_id, "consent-notice-v1")

        # 4. Decide the participant's answer.
        mode = self._settings.consent_mode
        if mode == "notice":  # continuing the call implies consent
            participant = await self._consents.record_participant_consent(
                call_id=call.id, status=ConsentStatus.granted, method=ConsentMethod.audio_notice
            )
        elif mode == "dtmf":  # active consent: 1 = yes, 2 = no
            await self._voice.play_consent_prompt(call.external_id)
            digit = await self._voice.collect_dtmf(call.external_id)
            status = ConsentStatus.granted if digit == "1" else ConsentStatus.denied
            participant = await self._consents.record_participant_consent(
                call_id=call.id, status=status, method=ConsentMethod.dtmf
            )
        elif mode == "sms_link":  # prior consent via SMS/app link
            participant = await self._consents.record_participant_consent(
                call_id=call.id, status=ConsentStatus.granted, method=ConsentMethod.sms_link
            )
        else:  # pragma: no cover - guarded by settings validation
            raise ValueError(f"unknown consent mode: {mode}")

        await self._transition(call, CallStatus.consent_result, actor)

        # 5. Refused -> recording is not enabled; the call can continue normally.
        if participant.status is not ConsentStatus.granted or consent_is_blocked(participant.status):
            await self._transition(call, CallStatus.in_progress, actor)
            return

        # 6-8. Granted -> start recording and the media stream, then analysis.
        require_recording_allowed(call, app_consent, participant)
        await self._transition(call, CallStatus.recording, actor)
        call.recording_started_at = datetime.now(UTC)
        recording_id = await self._voice.start_recording(call.external_id)
        stream_id = await self._voice.open_media_stream(call.external_id)

        from app.infrastructure.db.models import CallAudio
        from app.infrastructure.storage import retention_expiry

        self._session.add(
            CallAudio(
                call_id=call.id,
                storage_url=f"provider://{recording_id}",
                expires_at=retention_expiry(self._settings),
            )
        )
        await repositories.record_audit(
            self._session,
            entity_type="call",
            entity_id=call.id,
            action="recording.started",
            actor_user_id=actor.id,
            payload={"recording_id": recording_id, "stream_id": stream_id},
        )

        await self._transition(call, CallStatus.analyzing, actor)
        await self._events.emit(
            CallEventMessage(event="analysis_started", call_id=call.id, payload={})
        )
        await self._transition(call, CallStatus.in_progress, actor)
        self._stream_id = stream_id

    # -- helpers --------------------------------------------------------------

    async def _maybe_enqueue_analysis(self, call: Call) -> None:
        """Kick off the ML pipeline once a real recording is in object storage.

        Recording requires ``answered`` + consent (``recording_started_at`` is
        only set after the consent gate), and the provider uploads the audio to
        S3/MinIO; until the object is there the pipeline has nothing to read.
        """
        if self._analysis is None or call.recording_started_at is None:
            return
        audio = await repositories.get_call_audio(self._session, call.id)
        if audio is None or not audio.storage_url.startswith("s3://"):
            return
        self._analysis.enqueue_asr(str(call.id))

    async def _transition(self, call: Call, target: CallStatus, actor: User) -> None:
        if is_terminal(call.status):
            raise Conflict(f"call is already {call.status.value}")
        next_status(call.status, target)
        previous = call.status
        call.status = target
        await repositories.record_audit(
            self._session,
            entity_type="call",
            entity_id=call.id,
            action="call.transition",
            actor_user_id=actor.id,
            payload={"from": previous.value, "to": target.value},
        )


def consent_is_blocked(status: ConsentStatus) -> bool:
    return status in (ConsentStatus.denied, ConsentStatus.withdrawn)


async def get_call_or_404(session: AsyncSession, call_id: uuid.UUID) -> Call:
    call = await repositories.get_call(session, call_id)
    if call is None:
        raise NotFound("call not found")
    return call