import 'enums.dart';

/// A call the client had to register itself because the app could not reach the
/// backend while it was happening (plan.md §13).
///
/// The app generates [callId] (a UUID) and keeps the registration here until the
/// server accepts it. The same id is reused as the server call id, so replaying
/// `POST /calls` after a network drop returns the existing call instead of
/// creating a duplicate (idempotent by client id).
class PendingCall {
  const PendingCall({
    required this.callId,
    required this.direction,
    required this.calleePhone,
    required this.startedAt,
    this.contactName,
    this.recordConsent = true,
    this.participantConsent = ConsentStatus.granted,
    this.consentMethod = ConsentMethod.audioNotice,
    this.answeredAt,
    this.recordingStartedAt,
    this.endedAt,
  });

  factory PendingCall.fromRow(Map<String, Object?> row) => PendingCall(
        callId: row['call_id']! as String,
        direction: CallDirection.fromWire(row['direction']! as String),
        calleePhone: row['callee_phone']! as String,
        contactName: row['contact_name'] as String?,
        startedAt: DateTime.parse(row['started_at']! as String),
        recordConsent: ((row['record_consent'] as int?) ?? 1) != 0,
        participantConsent: ConsentStatus.fromWire(
          (row['participant_consent'] as String?) ?? 'granted',
        ),
        consentMethod: ConsentMethod.fromWire(
          (row['consent_method'] as String?) ?? 'audio_notice',
        ),
        answeredAt: _parse(row['answered_at']),
        recordingStartedAt: _parse(row['recording_started_at']),
        endedAt: _parse(row['ended_at']),
      );

  /// Client-generated UUID, reused as the server call id (idempotency key).
  final String callId;

  final CallDirection direction;
  final String calleePhone;
  final String? contactName;

  /// Real conversation start, reported so the server timeline is accurate.
  final DateTime startedAt;

  /// The app user's own consent decision at call time (never the counterparty
  /// refusal flag).
  final bool recordConsent;

  /// The counterparty consent obtained through the real flow; the client never
  /// grants it on its own.
  final ConsentStatus participantConsent;
  final ConsentMethod consentMethod;

  final DateTime? answeredAt;
  final DateTime? recordingStartedAt;
  final DateTime? endedAt;

  Map<String, Object?> toRow() => <String, Object?>{
        'call_id': callId,
        'direction': direction.wire,
        'callee_phone': calleePhone,
        'contact_name': contactName,
        'started_at': startedAt.toUtc().toIso8601String(),
        'record_consent': recordConsent ? 1 : 0,
        'participant_consent': participantConsent.wire,
        'consent_method': consentMethod.wire,
        'answered_at': answeredAt?.toUtc().toIso8601String(),
        'recording_started_at': recordingStartedAt?.toUtc().toIso8601String(),
        'ended_at': endedAt?.toUtc().toIso8601String(),
      };

  static DateTime? _parse(Object? value) =>
      value is String ? DateTime.parse(value) : null;
}
