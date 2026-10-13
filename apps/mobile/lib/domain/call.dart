import 'enums.dart';

/// A provider signal (voice SDK / VoIP event) the [CallController] reacts to.
///
/// Mirrors the backend `CallEvent`; `phone`/`name` are only present when the
/// provider supplies them (e.g. an incoming call push carries the caller).
class CallSignal {
  const CallSignal({
    required this.kind,
    this.externalId,
    this.phone,
    this.name,
    this.error,
  });

  final CallSignalKind kind;

  /// Voice-provider call id, used to control the call (answer/hangup).
  final String? externalId;
  final String? phone;
  final String? name;
  final String? error;
}

/// Immutable local call state that drives the call UI.
///
/// The controller holds a nullable [CallState]: `null` means "no call".
class CallState {
  const CallState({
    required this.status,
    required this.direction,
    required this.phone,
    this.name,
    this.callId,
    this.externalId,
    this.muted = false,
    this.startedAt,
    this.answeredAt,
    this.endedAt,
  });

  final CallLifecycleStatus status;
  final CallDirection direction;
  final String phone;
  final String? name;

  /// Backend call id (`POST /calls`); absent for a UI-only incoming call.
  final String? callId;

  /// Voice-provider call id used for control calls.
  final String? externalId;

  final bool muted;
  final DateTime? startedAt;
  final DateTime? answeredAt;
  final DateTime? endedAt;

  bool get isIncoming => direction == CallDirection.inbound;
  bool get isTerminal => status.isTerminal;

  /// True once the two parties are connected (the timer runs).
  bool get isConnected =>
      status == CallLifecycleStatus.answered ||
      status == CallLifecycleStatus.consentNotice ||
      status == CallLifecycleStatus.consentResult ||
      status == CallLifecycleStatus.recording ||
      status == CallLifecycleStatus.analyzing ||
      status == CallLifecycleStatus.inProgress;

  /// Name when known, otherwise the number.
  String get displayName => (name == null || name!.isEmpty) ? phone : name!;

  CallState copyWith({
    CallLifecycleStatus? status,
    String? callId,
    String? externalId,
    String? name,
    bool? muted,
    DateTime? answeredAt,
    DateTime? endedAt,
  }) {
    return CallState(
      status: status ?? this.status,
      direction: direction,
      phone: phone,
      name: name ?? this.name,
      callId: callId ?? this.callId,
      externalId: externalId ?? this.externalId,
      muted: muted ?? this.muted,
      startedAt: startedAt,
      answeredAt: answeredAt ?? this.answeredAt,
      endedAt: endedAt ?? this.endedAt,
    );
  }
}

/// Client mirror of the backend call state machine
/// (`services/api/src/app/domain/state_machine.py`).
///
/// The server is the source of truth; the client validates the same transitions
/// so an out-of-order provider signal never leaves the UI in an impossible
/// state. `completed`/`missed`/`failed` are terminal.
const Map<CallLifecycleStatus, Set<CallLifecycleStatus>> callTransitions = {
  CallLifecycleStatus.incoming: {
    CallLifecycleStatus.ringing,
    CallLifecycleStatus.answered,
    CallLifecycleStatus.missed,
    CallLifecycleStatus.failed,
  },
  CallLifecycleStatus.ringing: {
    CallLifecycleStatus.answered,
    CallLifecycleStatus.missed,
    CallLifecycleStatus.failed,
  },
  CallLifecycleStatus.answered: {
    CallLifecycleStatus.consentNotice,
    CallLifecycleStatus.inProgress,
    CallLifecycleStatus.failed,
  },
  CallLifecycleStatus.consentNotice: {
    CallLifecycleStatus.consentResult,
    CallLifecycleStatus.completed,
    CallLifecycleStatus.failed,
  },
  CallLifecycleStatus.consentResult: {
    CallLifecycleStatus.recording,
    CallLifecycleStatus.inProgress,
    CallLifecycleStatus.completed,
    CallLifecycleStatus.failed,
  },
  CallLifecycleStatus.recording: {
    CallLifecycleStatus.analyzing,
    CallLifecycleStatus.completed,
    CallLifecycleStatus.failed,
  },
  CallLifecycleStatus.analyzing: {
    CallLifecycleStatus.inProgress,
    CallLifecycleStatus.completed,
    CallLifecycleStatus.failed,
  },
  CallLifecycleStatus.inProgress: {
    CallLifecycleStatus.completed,
    CallLifecycleStatus.failed,
  },
  CallLifecycleStatus.completed: <CallLifecycleStatus>{},
  CallLifecycleStatus.missed: <CallLifecycleStatus>{},
  CallLifecycleStatus.failed: <CallLifecycleStatus>{},
};

bool canTransitionCall(CallLifecycleStatus from, CallLifecycleStatus to) =>
    callTransitions[from]!.contains(to);

/// Raised when a transition is not allowed by the lifecycle.
class InvalidCallTransition implements Exception {
  const InvalidCallTransition(this.from, this.to);

  final CallLifecycleStatus from;
  final CallLifecycleStatus to;

  @override
  String toString() => 'InvalidCallTransition(${from.wire} -> ${to.wire})';
}
