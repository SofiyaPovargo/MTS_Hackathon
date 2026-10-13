"""Call lifecycle state machine.

The lifecycle is fixed by the product rules:

``incoming -> ringing -> answered -> consent_notice -> consent_result ->
recording -> analyzing -> in_progress -> completed``

plus the terminal states ``missed`` and ``failed``. An invalid transition is an
error, never a silent no-op.
"""

from __future__ import annotations

from app.domain.enums import CallStatus
from app.domain.errors import InvalidStateTransition

TERMINAL_STATUSES: frozenset[CallStatus] = frozenset(
    {CallStatus.completed, CallStatus.missed, CallStatus.failed}
)

# ``consent_result`` branches: recording is started only when consent is granted,
# otherwise the call continues as an ordinary (non-recorded) call. ``answered``
# goes straight to ``in_progress`` when the app user disabled recording entirely.
#
# Calls may be cut short by the provider at any point: ``completed`` is reachable
# from every non-terminal state so a hangup mid-call is not an error.
TRANSITIONS: dict[CallStatus, frozenset[CallStatus]] = {
    CallStatus.incoming: frozenset(
        {CallStatus.ringing, CallStatus.answered, CallStatus.missed, CallStatus.failed}
    ),
    CallStatus.ringing: frozenset(
        {CallStatus.answered, CallStatus.missed, CallStatus.failed}
    ),
    CallStatus.answered: frozenset(
        {CallStatus.consent_notice, CallStatus.in_progress, CallStatus.failed}
    ),
    CallStatus.consent_notice: frozenset(
        {CallStatus.consent_result, CallStatus.completed, CallStatus.failed}
    ),
    CallStatus.consent_result: frozenset(
        {CallStatus.recording, CallStatus.in_progress, CallStatus.completed, CallStatus.failed}
    ),
    CallStatus.recording: frozenset({CallStatus.analyzing, CallStatus.completed, CallStatus.failed}),
    CallStatus.analyzing: frozenset(
        {CallStatus.in_progress, CallStatus.completed, CallStatus.failed}
    ),
    CallStatus.in_progress: frozenset({CallStatus.completed, CallStatus.failed}),
    CallStatus.completed: frozenset(),
    CallStatus.missed: frozenset(),
    CallStatus.failed: frozenset(),
}


def is_terminal(status: CallStatus) -> bool:
    return status in TERMINAL_STATUSES


def can_transition(current: CallStatus, target: CallStatus) -> bool:
    return target in TRANSITIONS[current]


def next_status(current: CallStatus, target: CallStatus) -> CallStatus:
    """Return ``target`` when the transition is allowed, otherwise raise."""
    if not can_transition(current, target):
        raise InvalidStateTransition(current.value, target.value)
    return target


def allowed_targets(current: CallStatus) -> frozenset[CallStatus]:
    return TRANSITIONS[current]
