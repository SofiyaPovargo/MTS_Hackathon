import 'package:agreement_capture/domain/enums.dart';
import 'package:agreement_capture/domain/offline_call.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('PendingCall round-trips through its row form', () {
    final call = PendingCall(
      callId: '11111111-1111-1111-1111-111111111111',
      direction: CallDirection.outbound,
      calleePhone: '+79000000002',
      contactName: 'Анна',
      startedAt: DateTime.utc(2026, 10, 14, 9),
      recordConsent: false,
      participantConsent: ConsentStatus.denied,
      consentMethod: ConsentMethod.dtmf,
      answeredAt: DateTime.utc(2026, 10, 14, 9, 1),
      endedAt: DateTime.utc(2026, 10, 14, 9, 5),
    );

    final row = call.toRow();
    final restored = PendingCall.fromRow(row);

    expect(restored.callId, call.callId);
    expect(restored.direction, CallDirection.outbound);
    expect(restored.calleePhone, '+79000000002');
    expect(restored.contactName, 'Анна');
    expect(restored.startedAt, DateTime.utc(2026, 10, 14, 9));
    expect(restored.recordConsent, isFalse);
    expect(restored.participantConsent, ConsentStatus.denied);
    expect(restored.consentMethod, ConsentMethod.dtmf);
    expect(restored.answeredAt, DateTime.utc(2026, 10, 14, 9, 1));
    expect(restored.endedAt, DateTime.utc(2026, 10, 14, 9, 5));
    // Unset times stay null instead of throwing.
    expect(restored.recordingStartedAt, isNull);
  });

  test('PendingCall defaults to granted consent and no times', () {
    final call = PendingCall(
      callId: '22222222-2222-2222-2222-222222222222',
      direction: CallDirection.outbound,
      calleePhone: '+79000000003',
      startedAt: DateTime.utc(2026, 10, 14, 9),
    );

    final restored = PendingCall.fromRow(call.toRow());

    expect(restored.recordConsent, isTrue);
    expect(restored.participantConsent, ConsentStatus.granted);
    expect(restored.consentMethod, ConsentMethod.audioNotice);
    expect(restored.contactName, isNull);
    expect(restored.answeredAt, isNull);
    expect(restored.recordingStartedAt, isNull);
    expect(restored.endedAt, isNull);
  });
}
