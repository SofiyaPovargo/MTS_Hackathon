"""Pydantic v2 request/response schemas for every endpoint."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import (
    AgreementStatus,
    CallDirection,
    CallEvent,
    ConsentStatus,
    Owner,
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
    direction: CallDirection
    callee_phone: str = Field(pattern=r"^\+[0-9]{10,15}$")
    contact_name: str | None = Field(default=None, max_length=200)
    external_id: str | None = None
    record_consent: bool = True


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
    assignee_user_id: uuid.UUID
    title: str
    description: str | None
    due_date: date | None
    due_time: time | None
    priority: TaskPriority
    status: TaskStatus
    completed_at: datetime | None
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


class ErrorBody(BaseModel):
    detail: str
    correlation_id: str | None = None