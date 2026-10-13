"""ORM models for the server-side source of truth.

Differences from the SQL draft in ``plan.md`` follow ``AGENTS.md``:
the transcript lives only in ``transcripts`` (never in ``calls``), agreements
carry ``owner`` plus audio timestamps, and raw LLM output, validated output and
user edits are stored separately.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    Uuid,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import (
    AgreementStatus,
    CallDirection,
    CallStatus,
    ConsentMethod,
    ConsentStatus,
    ConsentSubjectType,
    ConsentType,
    Owner,
    ReminderChannel,
    ReminderStatus,
    Role,
    TaskPriority,
    TaskStatus,
)
from app.infrastructure.crypto import EncryptedJSON, EncryptedText
from app.infrastructure.db.base import (
    Base,
    CreatedAtMixin,
    UpdatedAtMixin,
    UUIDPrimaryKeyMixin,
    VersionMixin,
)


def enum_column(enum_cls: type[StrEnum], name: str) -> SAEnum:
    """Store enums as checked VARCHAR, matching the SQL draft in plan.md."""

    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        length=32,
        validate_strings=True,
        values_callable=lambda enum: [member.value for member in enum],
    )


class Team(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "teams"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", use_alter=True, name="fk_teams_manager"),
        unique=True,
        nullable=True,
    )

    users: Mapped[list[User]] = relationship(
        back_populates="team", foreign_keys="User.team_id", lazy="selectin"
    )
    manager: Mapped[User | None] = relationship(foreign_keys=[manager_id], post_update=True)


class User(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "users"

    team_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True
    )
    phone: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[Role] = mapped_column(enum_column(Role, "user_role"), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Europe/Moscow")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    team: Mapped[Team | None] = relationship(back_populates="users", foreign_keys=[team_id])


class Call(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, VersionMixin, Base):
    __tablename__ = "calls"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    contact_phone: Mapped[str] = mapped_column(String(32), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    direction: Mapped[CallDirection] = mapped_column(
        enum_column(CallDirection, "call_direction"), nullable=False
    )
    status: Mapped[CallStatus] = mapped_column(
        enum_column(CallStatus, "call_status"), nullable=False, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recording_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    agreements: Mapped[list[Agreement]] = relationship(
        back_populates="call", cascade="all, delete-orphan", lazy="selectin"
    )
    audio: Mapped[CallAudio | None] = relationship(
        back_populates="call", cascade="all, delete-orphan", uselist=False, lazy="selectin"
    )
    transcript: Mapped[Transcript | None] = relationship(
        back_populates="call", cascade="all, delete-orphan", uselist=False, lazy="selectin"
    )


class CallAudio(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "call_audio"

    call_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("calls.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    storage_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False, default="audio/ogg")
    duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Per-leg objects for channel-separated (VoIP) recordings: role -> storage
    # url (``{"operator": ..., "client": ...}``). ``storage_url`` stays the
    # mixed/primary object; when legs exist diarization is not needed.
    channel_urls: Mapped[dict[str, str] | None] = mapped_column(JSONB, nullable=True)
    # In-flight chunked upload state per role (``mixed``/``operator``/``client``):
    # ``{role: {upload_id, offset, total, content_type, parts: [{key, size}]}}``.
    # Let a client resume after a network drop: whatever was acknowledged here is
    # already durable in object storage.
    pending_uploads: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    # Audio contains personal data and must not be kept forever.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    call: Mapped[Call] = relationship(back_populates="audio")


class Transcript(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "transcripts"

    call_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("calls.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="ru")
    # The transcript is personal data: encrypted at rest (plan §16).
    full_text: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    # Segmented transcript with speaker roles, as produced by the STT pipeline.
    segments: Mapped[list[dict[str, object]] | None] = mapped_column(
        EncryptedJSON, nullable=True
    )
    # Audit field: how speaker roles were obtained (channel | diarization | unknown).
    role_source: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="processing")

    call: Mapped[Call] = relationship(back_populates="transcript")


class Agreement(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, VersionMixin, Base):
    __tablename__ = "agreements"

    call_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("calls.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    owner: Mapped[Owner] = mapped_column(enum_column(Owner, "agreement_owner"), nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    object: Mapped[str | None] = mapped_column(String(500), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    source_quote: Mapped[str] = mapped_column(Text, nullable=False)
    audio_start: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    audio_end: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)
    status: Mapped[AgreementStatus] = mapped_column(
        enum_column(AgreementStatus, "agreement_status"), nullable=False, index=True
    )

    call: Mapped[Call] = relationship(back_populates="agreements")


class AgreementExtraction(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Raw and validated LLM output, kept apart from the agreement itself."""

    __tablename__ = "agreement_extractions"

    call_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("calls.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agreement_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("agreements.id", ondelete="SET NULL"), nullable=True
    )
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    # Raw and validated LLM output carry the transcript quotes: encrypted at rest.
    raw_output: Mapped[dict[str, object]] = mapped_column(EncryptedJSON, nullable=False)
    validated_output: Mapped[dict[str, object] | None] = mapped_column(
        EncryptedJSON, nullable=True
    )


class AgreementEdit(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Audit trail of user edits: the agreement row holds the current value."""

    __tablename__ = "agreement_edits"

    agreement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("agreements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    changes: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)


class Task(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, VersionMixin, Base):
    __tablename__ = "tasks"

    agreement_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("agreements.id", ondelete="SET NULL"), nullable=True, index=True
    )
    assignee_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    due_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    priority: Mapped[TaskPriority] = mapped_column(
        enum_column(TaskPriority, "task_priority"), nullable=False, default=TaskPriority.medium
    )
    status: Mapped[TaskStatus] = mapped_column(
        enum_column(TaskStatus, "task_status"),
        nullable=False,
        default=TaskStatus.new,
        index=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Reminder(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "reminders"

    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    remind_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    channel: Mapped[ReminderChannel] = mapped_column(
        enum_column(ReminderChannel, "reminder_channel"), nullable=False
    )
    status: Mapped[ReminderStatus] = mapped_column(
        enum_column(ReminderStatus, "reminder_status"),
        nullable=False,
        default=ReminderStatus.scheduled,
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Consent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "consents"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    subject_type: Mapped[ConsentSubjectType] = mapped_column(
        enum_column(ConsentSubjectType, "consent_subject_type"), nullable=False
    )
    call_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("calls.id", ondelete="CASCADE"), nullable=True, index=True
    )
    consent_type: Mapped[ConsentType] = mapped_column(
        enum_column(ConsentType, "consent_type"), nullable=False
    )
    status: Mapped[ConsentStatus] = mapped_column(
        enum_column(ConsentStatus, "consent_status"), nullable=False
    )
    method: Mapped[ConsentMethod] = mapped_column(
        enum_column(ConsentMethod, "consent_method"), nullable=False
    )
    text_version: Mapped[str] = mapped_column(String(32), nullable=False)
    granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    meta: Mapped[dict[str, object] | None] = mapped_column("metadata", JSONB, nullable=True)


class AuditLog(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "audit_log"

    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)


class IdempotencyKey(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Server-side record of a repeated submission (sync push, call creation)."""

    __tablename__ = "idempotency_keys"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)

    __table_args__ = ()
