import 'models.dart';

/// Live call event kinds — the four events of the backend WS contract
/// (schema v1, see `services/api/src/app/services/events.py`).
enum CallEventKind {
  analysisStarted('analysis_started'),
  partialTranscript('partial_transcript'),
  agreementDetected('agreement_detected'),
  callEnded('call_ended');

  const CallEventKind(this.wire);
  final String wire;

  static CallEventKind fromWire(String value) => CallEventKind.values
      .firstWhere((e) => e.wire == value, orElse: () => CallEventKind.analysisStarted);
}

/// One frame of the live event stream; the envelope is versioned so a client can
/// refuse a breaking schema instead of mis-parsing it.
///
///     {"version": 1, "event": "analysis_started", "call_id": "<uuid>", "payload": {…}}
class CallEvent {
  const CallEvent({
    required this.version,
    required this.kind,
    required this.callId,
    this.payload = const <String, dynamic>{},
  });

  factory CallEvent.fromJson(Map<String, dynamic> json) => CallEvent(
        version: (json['version'] as num?)?.toInt() ?? 1,
        kind: CallEventKind.fromWire(json['event'] as String),
        callId: json['call_id'] as String,
        payload: (json['payload'] as Map<String, dynamic>?) ?? const <String, dynamic>{},
      );

  final int version;
  final CallEventKind kind;
  final String callId;
  final Map<String, dynamic> payload;

  /// Events are ignored when the schema version is newer than the client.
  bool get isSchemaSupported => version <= wsEventSchemaVersion;
}

/// The client-side schema version; bump together with the backend
/// `EVENT_SCHEMA_VERSION` only on a breaking change.
const int wsEventSchemaVersion = 1;

/// A transcribed utterance within a call (`partial_transcript` payload).
class TranscriptSegment {
  const TranscriptSegment({
    required this.speaker,
    required this.text,
    required this.start,
    required this.end,
  });

  factory TranscriptSegment.fromPayload(Map<String, dynamic> payload) =>
      TranscriptSegment(
        speaker: (payload['speaker'] as String?) ?? '',
        text: (payload['text'] as String?) ?? '',
        start: (payload['start'] as num?)?.toDouble() ?? 0,
        end: (payload['end'] as num?)?.toDouble() ?? 0,
      );

  final String speaker;
  final String text;
  final double start;
  final double end;
}

/// Parses the `agreement_detected` payload into the domain model. The payload is
/// a subset of `AgreementOut` (no version/timestamps), handled by `fromJson`.
Agreement agreementFromEventPayload(Map<String, dynamic> payload) =>
    Agreement.fromJson(payload);