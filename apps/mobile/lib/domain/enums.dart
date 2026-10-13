/// Wire enums mirroring the backend contract (`services/api/src/app/domain/enums.py`).
/// Stored on the wire as lowercase strings; parsers are lenient so a server
/// enum addition degrades to a safe default instead of crashing the client.
library;

enum Role {
  user('user'),
  manager('manager');

  const Role(this.wire);
  final String wire;

  static Role fromWire(String value) =>
      Role.values.firstWhere((r) => r.wire == value, orElse: () => Role.user);
}

enum CallDirection {
  inbound('inbound'),
  outbound('outbound');

  const CallDirection(this.wire);
  final String wire;

  static CallDirection fromWire(String value) =>
      CallDirection.values.firstWhere((d) => d.wire == value, orElse: () => CallDirection.outbound);
}

/// Call lifecycle (backend `CallStatus`). Mirrors the server state machine
/// (`services/api/src/app/domain/state_machine.py`); the server stays the source
/// of truth, the client only validates the same transitions for the UI.
enum CallLifecycleStatus {
  incoming('incoming'),
  ringing('ringing'),
  answered('answered'),
  consentNotice('consent_notice'),
  consentResult('consent_result'),
  recording('recording'),
  analyzing('analyzing'),
  inProgress('in_progress'),
  completed('completed'),
  missed('missed'),
  failed('failed');

  const CallLifecycleStatus(this.wire);
  final String wire;

  bool get isTerminal =>
      this == CallLifecycleStatus.completed ||
      this == CallLifecycleStatus.missed ||
      this == CallLifecycleStatus.failed;

  static CallLifecycleStatus fromWire(String value) => CallLifecycleStatus.values.firstWhere(
        (s) => s.wire == value,
        orElse: () => CallLifecycleStatus.failed,
      );
}

/// Provider signals the app reacts to (backend `CallEvent`).
enum CallSignalKind {
  incoming('incoming'),
  ringing('ringing'),
  answered('answered'),
  ended('ended'),
  dropped('dropped'),
  missed('missed');

  const CallSignalKind(this.wire);
  final String wire;

  static CallSignalKind fromWire(String value) => CallSignalKind.values.firstWhere(
        (k) => k.wire == value,
        orElse: () => CallSignalKind.dropped,
      );
}

enum AgreementStatus {
  detected('detected'),
  requiresReview('requires_review'),
  needsClarification('needs_clarification'),
  confirmed('confirmed'),
  rejected('rejected');

  const AgreementStatus(this.wire);
  final String wire;

  static AgreementStatus fromWire(String value) => AgreementStatus.values.firstWhere(
        (s) => s.wire == value,
        orElse: () => AgreementStatus.detected,
      );
}

enum AgreementOwner {
  user('user'),
  counterparty('counterparty'),
  unknown('unknown');

  const AgreementOwner(this.wire);
  final String wire;

  static AgreementOwner fromWire(String value) =>
      AgreementOwner.values.firstWhere((o) => o.wire == value, orElse: () => AgreementOwner.unknown);
}

enum TaskStatus {
  newTask('new'),
  inProgress('in_progress'),
  done('done'),
  overdue('overdue'),
  canceled('canceled');

  const TaskStatus(this.wire);
  final String wire;

  static TaskStatus fromWire(String value) =>
      TaskStatus.values.firstWhere((s) => s.wire == value, orElse: () => TaskStatus.newTask);
}

enum TaskPriority {
  low('low'),
  medium('medium'),
  high('high');

  const TaskPriority(this.wire);
  final String wire;

  static TaskPriority fromWire(String value) =>
      TaskPriority.values.firstWhere((p) => p.wire == value, orElse: () => TaskPriority.medium);
}

/// Entities syncable via `/sync` (backend `SyncEntity`).
enum SyncEntityType {
  call('call'),
  agreement('agreement'),
  task('task'),
  reminder('reminder');

  const SyncEntityType(this.wire);
  final String wire;

  static SyncEntityType? tryFromWire(String value) =>
      SyncEntityType.values.firstWhereOrNull((e) => e.wire == value);
}

extension FirstWhereOrNullExtension<E> on Iterable<E> {
  E? firstWhereOrNull(bool Function(E element) test) {
    for (final element in this) {
      if (test(element)) return element;
    }
    return null;
  }
}