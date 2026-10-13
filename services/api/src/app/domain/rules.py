"""Business rules that must stay testable and free of I/O.

The rules here are the ones the product specification declares critical:
recording without consent is impossible, a task is created only from a
confirmed agreement, and a low-confidence extraction never becomes a task
automatically.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.domain.enums import (
    AgreementStatus,
    CallStatus,
    ConsentStatus,
    Owner,
    TaskStatus,
)

DEFAULT_CONFIDENCE_THRESHOLD = 0.8

# Consent states that block recording forever, regardless of a later "granted" row.
BLOCKING_CONSENT_STATUSES = frozenset({ConsentStatus.denied, ConsentStatus.withdrawn})

# The call must have reached one of these states before recording can start.
CONSENT_READY_STATUSES = frozenset(
    {CallStatus.answered, CallStatus.consent_notice, CallStatus.consent_result}
)

RECORDABLE_STATUSES = frozenset(
    {CallStatus.recording, CallStatus.analyzing, CallStatus.in_progress}
)


@dataclass(frozen=True, slots=True)
class AmbiguityFlags:
    """Signals that make an extraction ambiguous and require clarification."""

    vague_deadline: bool = False
    missing_due_date: bool = False
    missing_amount: bool = False
    unknown_owner: bool = False
    contradictory_quote: bool = False

    def reasons(self) -> list[str]:
        reasons: list[str] = []
        if self.vague_deadline:
            reasons.append("vague_deadline")
        if self.missing_due_date:
            reasons.append("missing_due_date")
        if self.missing_amount:
            reasons.append("missing_amount")
        if self.unknown_owner:
            reasons.append("unknown_owner")
        if self.contradictory_quote:
            reasons.append("contradictory_quote")
        return reasons

    @property
    def is_ambiguous(self) -> bool:
        return bool(self.reasons())


def is_confident(confidence: float, threshold: float = DEFAULT_CONFIDENCE_THRESHOLD) -> bool:
    return confidence >= threshold


def resolve_agreement_status(
    confidence: float,
    *,
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    ambiguity: AmbiguityFlags | None = None,
    ambiguous: bool | None = None,
) -> AgreementStatus:
    """Map an extraction result to an agreement status.

    Ambiguity wins over confidence: an ambiguous deadline is clarified even when
    the model is very sure of the wording.
    """
    flags = ambiguity or AmbiguityFlags()
    if ambiguous is None:
        ambiguous = flags.is_ambiguous
    if ambiguous:
        return AgreementStatus.needs_clarification
    if not is_confident(confidence, threshold):
        return AgreementStatus.requires_review
    return AgreementStatus.detected


def _consent_granted(statuses: Iterable[ConsentStatus | None]) -> tuple[bool, list[str]]:
    values = list(statuses)
    if any(status in BLOCKING_CONSENT_STATUSES for status in values if status is not None):
        return False, ["consent_denied_or_withdrawn"]
    if not values or any(status is not ConsentStatus.granted for status in values):
        return False, ["consent_missing"]
    return True, []


@dataclass(frozen=True, slots=True)
class RecordingDecision:
    allowed: bool
    reasons: list[str] = field(default_factory=list)

    def raise_reason(self) -> str:
        return ", ".join(self.reasons) or "unknown"


def decide_recording(
    call_status: CallStatus,
    *,
    app_consent: ConsentStatus | None,
    participant_consent: ConsentStatus | None,
) -> RecordingDecision:
    """Recording is allowed only after ``answered`` and with both consents granted."""
    if call_status not in CONSENT_READY_STATUSES:
        return RecordingDecision(False, [f"call_status={call_status.value}"])
    allowed, reasons = _consent_granted((app_consent, participant_consent))
    return RecordingDecision(allowed, reasons)


def can_create_task(
    agreement_status: AgreementStatus,
    *,
    confidence: float,
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> bool:
    """A task is created only from a confirmed, confident agreement."""
    if agreement_status is not AgreementStatus.confirmed:
        return False
    return is_confident(confidence, threshold)


def resolve_task_status(
    status: TaskStatus, due_date: date | None, *, today: date
) -> TaskStatus:
    """Overdue is derived, never set by hand while the task is open."""
    if status in (TaskStatus.done, TaskStatus.canceled):
        return status
    if due_date is not None and due_date < today:
        return TaskStatus.overdue
    return status


def is_ambiguous_owner(owner: Owner) -> bool:
    return owner is Owner.unknown


def next_week_start(today: date) -> date:
    """Monday of the following ISO week."""
    return today + timedelta(days=7 - today.weekday())
