"""Business rules: confidence threshold, ambiguity, consent gate, task guard."""

from __future__ import annotations

from datetime import date

import pytest

from app.domain.enums import AgreementStatus, CallStatus, ConsentStatus, TaskStatus
from app.domain.rules import (
    AmbiguityFlags,
    can_create_task,
    decide_recording,
    resolve_agreement_status,
    resolve_task_status,
)


def test_confidence_threshold_default_is_0_8() -> None:
    assert resolve_agreement_status(0.79, threshold=0.8) is AgreementStatus.requires_review
    assert resolve_agreement_status(0.8, threshold=0.8) is AgreementStatus.detected
    assert resolve_agreement_status(0.95, threshold=0.8) is AgreementStatus.detected


def test_custom_threshold_from_config() -> None:
    assert resolve_agreement_status(0.85, threshold=0.9) is AgreementStatus.requires_review


def test_ambiguity_beats_confidence() -> None:
    ambiguous = AmbiguityFlags(vague_deadline=True)
    status = resolve_agreement_status(0.99, ambiguity=ambiguous)
    assert status is AgreementStatus.needs_clarification


def test_unknown_owner_flags_ambiguity() -> None:
    status = resolve_agreement_status(0.9, ambiguity=AmbiguityFlags(unknown_owner=True))
    assert status is AgreementStatus.needs_clarification


@pytest.mark.parametrize(
    ("status", "confidence", "expected"),
    [
        (AgreementStatus.confirmed, 0.95, True),
        (AgreementStatus.confirmed, 0.5, False),
        (AgreementStatus.detected, 0.95, False),
        (AgreementStatus.requires_review, 0.95, False),
        (AgreementStatus.needs_clarification, 0.95, False),
        (AgreementStatus.rejected, 0.95, False),
    ],
)
def test_task_created_only_from_confirmed_agreement(
    status: AgreementStatus, confidence: float, expected: bool
) -> None:
    assert can_create_task(status, confidence=confidence, threshold=0.8) is expected


@pytest.mark.parametrize(
    ("call_status", "app", "participant", "expected"),
    [
        # The critical rule: recording only after answered and both consents.
        (CallStatus.ringing, ConsentStatus.granted, ConsentStatus.granted, False),
        (CallStatus.incoming, ConsentStatus.granted, ConsentStatus.granted, False),
        (CallStatus.answered, None, ConsentStatus.granted, False),
        (CallStatus.answered, ConsentStatus.granted, None, False),
        (CallStatus.answered, ConsentStatus.granted, ConsentStatus.granted, True),
        (CallStatus.consent_notice, ConsentStatus.granted, ConsentStatus.granted, True),
        (CallStatus.consent_result, ConsentStatus.granted, ConsentStatus.granted, True),
        # explicit refusal and withdrawal block recording forever
        (CallStatus.answered, ConsentStatus.granted, ConsentStatus.denied, False),
        (CallStatus.answered, ConsentStatus.denied, ConsentStatus.granted, False),
        (CallStatus.answered, ConsentStatus.withdrawn, ConsentStatus.granted, False),
    ],
)
def test_recording_consent_gate(
    call_status: CallStatus,
    app: ConsentStatus | None,
    participant: ConsentStatus | None,
    expected: bool,
) -> None:
    decision = decide_recording(call_status, app_consent=app, participant_consent=participant)
    assert decision.allowed is expected


def test_task_status_overdue_is_derived() -> None:
    today = date(2026, 10, 13)
    assert resolve_task_status(TaskStatus.new, date(2026, 10, 12), today=today) is TaskStatus.overdue
    assert resolve_task_status(TaskStatus.new, date(2026, 10, 13), today=today) is TaskStatus.new
    assert resolve_task_status(TaskStatus.in_progress, None, today=today) is TaskStatus.in_progress
    # done is never flipped back to overdue
    assert resolve_task_status(TaskStatus.done, date(2026, 1, 1), today=today) is TaskStatus.done
    assert resolve_task_status(TaskStatus.canceled, date(2026, 1, 1), today=today) is TaskStatus.canceled