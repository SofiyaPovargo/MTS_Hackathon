"""Call state machine transitions are validated by the domain layer."""

from __future__ import annotations

import itertools

import pytest

from app.domain.enums import CallStatus
from app.domain.errors import InvalidStateTransition
from app.domain.state_machine import (
    allowed_targets,
    can_transition,
    is_terminal,
    next_status,
)


def test_happy_path_chain() -> None:
    chain = [
        CallStatus.incoming,
        CallStatus.ringing,
        CallStatus.answered,
        CallStatus.consent_notice,
        CallStatus.consent_result,
        CallStatus.recording,
        CallStatus.analyzing,
        CallStatus.in_progress,
        CallStatus.completed,
    ]
    for current, target in itertools.pairwise(chain):
        assert can_transition(current, target), f"{current} -> {target}"


def test_terminal_missed_and_failed() -> None:
    assert is_terminal(CallStatus.completed)
    assert is_terminal(CallStatus.missed)
    assert is_terminal(CallStatus.failed)
    assert not is_terminal(CallStatus.ringing)


def test_skipping_consent_is_an_error() -> None:
    # recording without the consent flow is impossible
    with pytest.raises(InvalidStateTransition):
        next_status(CallStatus.answered, CallStatus.recording)
    with pytest.raises(InvalidStateTransition):
        next_status(CallStatus.incoming, CallStatus.in_progress)


def test_recording_cannot_precede_answered() -> None:
    for start in (CallStatus.incoming, CallStatus.ringing):
        assert CallStatus.recording not in allowed_targets(start)


def test_no_consent_shortcut() -> None:
    # documented: app user disabled recording -> ordinary call
    assert can_transition(CallStatus.answered, CallStatus.in_progress)


def test_terminal_states_are_final() -> None:
    for terminal in (CallStatus.completed, CallStatus.missed, CallStatus.failed):
        assert allowed_targets(terminal) == frozenset()
        with pytest.raises(InvalidStateTransition):
            next_status(terminal, CallStatus.in_progress)


def test_hangup_mid_analysis_is_allowed() -> None:
    assert can_transition(CallStatus.analyzing, CallStatus.completed)
    assert can_transition(CallStatus.consent_result, CallStatus.completed)
    assert can_transition(CallStatus.recording, CallStatus.failed)