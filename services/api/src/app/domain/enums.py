"""Domain enums shared by the API, services and ML layers."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    user = "user"
    manager = "manager"


class CallDirection(StrEnum):
    inbound = "inbound"
    outbound = "outbound"


class CallStatus(StrEnum):
    incoming = "incoming"
    ringing = "ringing"
    answered = "answered"
    consent_notice = "consent_notice"
    consent_result = "consent_result"
    recording = "recording"
    analyzing = "analyzing"
    in_progress = "in_progress"
    completed = "completed"
    missed = "missed"
    failed = "failed"


class CallEvent(StrEnum):
    incoming = "incoming"
    ringing = "ringing"
    answered = "answered"
    ended = "ended"
    dropped = "dropped"
    missed = "missed"


class AgreementStatus(StrEnum):
    detected = "detected"
    requires_review = "requires_review"
    needs_clarification = "needs_clarification"
    confirmed = "confirmed"
    rejected = "rejected"


class Owner(StrEnum):
    user = "user"
    counterparty = "counterparty"
    unknown = "unknown"


class TaskStatus(StrEnum):
    new = "new"
    in_progress = "in_progress"
    done = "done"
    overdue = "overdue"
    canceled = "canceled"


class TaskPriority(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class TaskView(StrEnum):
    """Personal-board slices (``plan.md`` §14): upcoming, overdue, today, done."""

    all = "all"
    today = "today"
    overdue = "overdue"
    upcoming = "upcoming"
    done = "done"


class TaskSort(StrEnum):
    """Manager-board ordering (``plan.md`` §15); default is overdue-first."""

    overdue = "overdue"
    due_date = "due_date"
    priority = "priority"
    created = "created"


class ReminderChannel(StrEnum):
    push = "push"
    local = "local"
    sms = "sms"


class ReminderStatus(StrEnum):
    scheduled = "scheduled"
    sent = "sent"
    canceled = "canceled"
    failed = "failed"


class ConsentSubjectType(StrEnum):
    app_user = "app_user"
    call_participant = "call_participant"


class ConsentType(StrEnum):
    recording = "recording"
    ai_processing = "ai_processing"
    data_storage = "data_storage"
    notification = "notification"


class ConsentStatus(StrEnum):
    granted = "granted"
    denied = "denied"
    withdrawn = "withdrawn"


class ConsentMethod(StrEnum):
    app_settings = "app_settings"
    audio_notice = "audio_notice"
    dtmf = "dtmf"
    sms_link = "sms_link"


class SyncEntity(StrEnum):
    call = "call"
    agreement = "agreement"
    task = "task"
    reminder = "reminder"
