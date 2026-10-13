import 'package:agreement_capture/domain/enums.dart';
import 'package:agreement_capture/domain/ws_event.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('envelope parses schema-v1 frames', () {
    final event = CallEvent.fromJson(<String, dynamic>{
      'version': 1,
      'event': 'partial_transcript',
      'call_id': 'call-1',
      'payload': <String, dynamic>{'text': 'привет'},
    });

    expect(event.version, 1);
    expect(event.kind, CallEventKind.partialTranscript);
    expect(event.callId, 'call-1');
    expect(event.payload['text'], 'привет');
    expect(event.isSchemaSupported, isTrue);
  });

  test('every wire type maps to its enum value', () {
    expect(CallEventKind.fromWire('analysis_started'), CallEventKind.analysisStarted);
    expect(
      CallEventKind.fromWire('partial_transcript'),
      CallEventKind.partialTranscript,
    );
    expect(
      CallEventKind.fromWire('agreement_detected'),
      CallEventKind.agreementDetected,
    );
    expect(CallEventKind.fromWire('call_ended'), CallEventKind.callEnded);
  });

  test('a newer schema version is flagged unsupported', () {
    final event = CallEvent.fromJson(<String, dynamic>{
      'version': 2,
      'event': 'call_ended',
      'call_id': 'call-1',
    });

    expect(event.isSchemaSupported, isFalse);
  });

  test('unknown event kinds fall back to a known one instead of crashing', () {
    final event = CallEvent.fromJson(<String, dynamic>{
      'version': 1,
      'event': 'future_event',
      'call_id': 'call-1',
    });

    expect(event.kind, CallEventKind.analysisStarted);
  });

  test('transcript segment parses its payload', () {
    final segment = TranscriptSegment.fromPayload(<String, dynamic>{
      'speaker': 'user',
      'text': 'оплачу до пятницы',
      'start': 12.5,
      'end': 18.0,
    });

    expect(segment.speaker, 'user');
    expect(segment.text, 'оплачу до пятницы');
    expect(segment.start, 12.5);
    expect(segment.end, 18.0);
  });

  test('agreement payload parses into the domain Agreement', () {
    final agreement = agreementFromEventPayload(<String, dynamic>{
      'id': 'agr-1',
      'call_id': 'call-1',
      'type': 'payment',
      'title': 'Оплатить счёт',
      'owner': 'user',
      'due_date': '2026-10-15',
      'due_time': null,
      'source_quote': 'оплачу до пятницы',
      'audio_start': 12.5,
      'audio_end': 18.0,
      'confidence': 0.92,
      'status': 'detected',
    });

    expect(agreement.id, 'agr-1');
    expect(agreement.callId, 'call-1');
    expect(agreement.owner, AgreementOwner.user);
    expect(agreement.type, 'payment');
    expect(agreement.dueDate, DateTime(2026, 10, 15));
    expect(agreement.sourceQuote, 'оплачу до пятницы');
    expect(agreement.confidence, 0.92);
    expect(agreement.status, AgreementStatus.detected);
  });
}