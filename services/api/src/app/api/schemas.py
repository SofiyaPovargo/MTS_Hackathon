"""Pydantic v2 request/response schemas for every endpoint."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import (
    AgreementStatus,
    CallDirection,
    CallEvent,
    ConsentMethod,
    ConsentStatus,
    Owner,
    ReminderChannel,
    ReminderStatus,
    Role,
    SyncEntity,
    TaskPriority,
    TaskStatus,
)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    phone: str
    full_name: str
    role: Role
    team_id: uuid.UUID | None
    timezone: str


class OtpRequest(BaseModel):
    phone: str = Field(pattern=r"^\+[0-9]{10,15}$")


class LoginRequest(OtpRequest):
    otp: str = Field(min_length=4, max_length=8)


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class RefreshRequest(BaseModel):
    refresh_token: str


class CallCreateRequest(BaseModel):
    """Create a call. A client ``id`` makes the request idempotent (§13).

    The offline client generates the UUID locally, so replaying the request
    after a network drop returns the same call instead of a duplicate.
    """

    id: uuid.UUID | None = Field(
        default=None, description="Client-generated call id (offline); idempotency key."
    )
    direction: CallDirection
    callee_phone: str = Field(pattern=r"^\+[0-9]{10,15}$")
    contact_name: str | None = Field(default=None, max_length=200)
    external_id: str | None = None
    started_at: datetime | None = Field(
        default=None, description="Real conversation start (offline); defaults to now."
    )
    record_consent: bool = True


class CallRecordingRequest(BaseModel):
    """Declare a call recorded on the client and its consent (§13, offline).

    The call happened without network: the app recorded locally and now pushes
    it. The owner JWT carries the assertion that the app user consented
    (``record_consent``) and that the counterparty consent was obtained
    (``participant_consent`` + ``consent_method``). The server stores both
    consent events and only then fixes ``recording_started_at``; a refused
    party leaves the call unrecorded and the audio upload is refused.
    """

    record_consent: bool = True
    participant_consent: ConsentStatus = ConsentStatus.granted
    consent_method: ConsentMethod = ConsentMethod.audio_notice
    answered_at: datetime | None = None
    recording_started_at: datetime | None = None
    ended_at: datetime | None = None


class CallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    direction: CallDirection
    contact_phone: str
    contact_name: str | None
    status: str
    started_at: datetime | None
    answered_at: datetime | None
    ended_at: datetime | None
    recording_started_at: datetime | None
    summary: str | None
    version: int
    created_at: datetime
    updated_at: datetime


class CallEventRequest(BaseModel):
    event: CallEvent
    at: datetime | None = None


class CallAnalyzeResponse(BaseModel):
    """Accepted analysis job (async: the call is queued, not processed)."""

    call_id: uuid.UUID
    status: str


class CallSummaryOut(BaseModel):
    """Итог звонка (§9): резюме разговора и счётчики договорённостей."""

    call_id: uuid.UUID
    summary: str
    agreements_total: int
    agreements_confirmed: int


class CallAudioAccepted(BaseModel):
    """Stored client audio (a whole object or one resumable chunk).

    ``offset`` is the durable byte count for the role after the request and
    ``complete`` whether the recording is fully stored: a client resuming after
    a network drop continues from ``offset`` (see ``services/audio_ingest.py``).
    """

    call_id: uuid.UUID
    role: str | None
    content_type: str
    bytes_stored: int
    legs_present: list[str]
    analysis_queued: bool
    offset: int
    complete: bool


class ExolveControlRequest(BaseModel):
    """Call-control webhook payload: a call arrived on a SIP resource."""

    model_config = ConfigDict(extra="allow")

    sip_id: int | str
    number_a: str = Field(alias="numberA")
    call_sid: str


class ExolveControlResponse(BaseModel):
    """JSON-RPC 2.0 routing body answered to the call-control webhook.

    Exactly one of ``result`` (route the call) or ``error`` (do not route) is set.
    """

    id: int = 1
    jsonrpc: str = "2.0"
    sip_id: str
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class ExolveEventRequest(BaseModel):
    """Progress-notification webhook payload (``b``/``o``/``s``/``h``/``e``/``crr``)."""

    model_config = ConfigDict(extra="allow")

    type: str
    call_sid: str = ""
    client_id: str | None = None
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None
    record_call: bool = False
    # ``crr`` only: the Call Record id whose audio is fetched by the worker.
    uid: str | int | None = None
    record_duration: int | None = None


class ExolveEventAck(BaseModel):
    """Outcome of one progress notification."""

    status: str
    call_id: uuid.UUID
    event: str


class AgreementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    call_id: uuid.UUID
    owner_user_id: uuid.UUID | None
    owner: Owner
    type: str
    title: str
    object: str | None
    due_date: date | None
    due_time: time | None
    amount: Decimal | None
    currency: str | None
    source_quote: str
    audio_start: float
    audio_end: float
    confidence: float
    status: AgreementStatus
    version: int
    created_at: datetime
    updated_at: datetime


class AgreementCreateManualRequest(BaseModel):
    type: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=500)
    object: str | None = Field(default=None, max_length=500)
    owner: Owner = Owner.unknown
    owner_user_id: uuid.UUID | None = None
    due_date: date | None = None
    due_time: time | None = None
    amount: Decimal | None = Field(default=None, gt=0)
    currency: str | None = None


class AgreementPatchRequest(BaseModel):
    type: str | None = Field(default=None, min_length=1, max_length=64)
    title: str | None = Field(default=None, min_length=1, max_length=500)
    object: str | None = Field(default=None, max_length=500)
    owner: Owner | None = None
    owner_user_id: uuid.UUID | None = None
    due_date: date | None = None
    due_time: time | None = None
    amount: Decimal | None = Field(default=None, gt=0)
    currency: str | None = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agreement_id: uuid.UUID | None
    call_id: uuid.UUID | None = None
    assignee_user_id: uuid.UUID
    title: str
    description: str | None
    due_date: date | None
    due_time: time | None
    priority: TaskPriority
    status: TaskStatus
    completed_at: datetime | None
    calendar_event_id: str | None = None
    version: int
    created_at: datetime
    updated_at: datetime


class TaskPatchRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    due_date: date | None = None
    due_time: time | None = None
    priority: TaskPriority | None = None
    status: TaskStatus | None = None


class ManagerTaskOut(BaseModel):
    """A card on the team board (§15): assignee, client, call source, deadline."""

    id: uuid.UUID
    assignee_user_id: uuid.UUID
    assignee_name: str | None = None
    agreement_id: uuid.UUID | None = None
    agreement_type: str | None = None
    call_id: uuid.UUID | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    title: str
    description: str | None = None
    due_date: date | None = None
    due_time: time | None = None
    priority: TaskPriority
    status: TaskStatus
    version: int
    created_at: datetime
    updated_at: datetime


class TeamMemberOut(BaseModel):
    id: uuid.UUID
    phone: str
    full_name: str
    role: Role


class MemberStatsOut(BaseModel):
    """Per-employee analytics (§15)."""

    user_id: uuid.UUID
    full_name: str
    agreements_total: int
    tasks_total: int
    tasks_by_status: dict[str, int]
    overdue: int
    done_on_time: int
    done_on_time_percent: float
    avg_close_hours: float | None = None
    tasks_from_calls_percent: float


class TeamStatsOut(BaseModel):
    """Team analytics (§15): aggregate metrics plus a per-member breakdown."""

    members_count: int
    agreements_total: int
    tasks_total: int
    tasks_by_status: dict[str, int]
    overdue: int
    done_on_time: int
    done_on_time_percent: float
    avg_close_hours: float | None = None
    tasks_from_calls_percent: float
    members: list[MemberStatsOut]


class CalendarEventOut(BaseModel):
    task_id: uuid.UUID
    event_id: str
    title: str
    starts_at: datetime
    ends_at: datetime


class ReminderCreateRequest(BaseModel):
    remind_at: datetime
    channel: ReminderChannel = ReminderChannel.push


class ReminderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    remind_at: datetime
    channel: ReminderChannel
    status: ReminderStatus


class MessageDraftOut(BaseModel):
    """A draft only — never sent to the counterparty automatically."""

    task_id: uuid.UUID
    draft_id: str
    phone: str
    text: str
    sent: bool = False


class SyncChange(BaseModel):
    entity_type: str
    id: str
    version: int
    updated_at: datetime
    data: dict[str, object]


class SyncPullResponse(BaseModel):
    changes: list[SyncChange]
    sync_token: str
    has_more: bool


class SyncOperation(BaseModel):
    entity_type: SyncEntity
    entity_id: uuid.UUID
    operation: str = Field(pattern=r"^(update|delete)$")
    idempotency_key: str = Field(min_length=8, max_length=128)
    version: int | None = None
    payload: dict[str, object] = Field(default_factory=dict)


class SyncPushRequest(BaseModel):
    operations: list[SyncOperation] = Field(min_length=1, max_length=100)


class SyncResultOut(BaseModel):
    entity_type: str
    entity_id: str
    status: str
    version: int | None
    server_version: int | None = None
    message: str | None = None


class SyncPushResponse(BaseModel):
    results: list[SyncResultOut]


class ConsentSetRequest(BaseModel):
    granted: bool


class ConsentOut(BaseModel):
    id: uuid.UUID
    subject_type: str
    status: ConsentStatus
    method: str
    granted_at: datetime | None
    withdrawn_at: datetime | None


class CallEventEnvelope(BaseModel):
    """Versioned WebSocket frame on ``/api/ws/calls/{call_id}``.

    The ``payload`` shape depends on ``event`` (``partial_transcript``,
    ``agreement_detected``, ``analysis_started``, ``call_ended``); see
    ``plan.md`` §13.
    """

    version: int = 1
    event: str
    call_id: uuid.UUID
    payload: dict[str, object] = Field(default_factory=dict)


class ErrorBody(BaseModel):
    detail: str
    correlation_id: str | None = None