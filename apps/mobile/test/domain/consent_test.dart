import 'package:agreement_capture/domain/consent.dart';
import 'package:agreement_capture/domain/enums.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('undecided consent is not decided and recording stays off', () {
    expect(AppConsent.undecided.decided, isFalse);
    expect(AppConsent.undecided.recordingEnabled, isFalse);
  });

  test('granted enables recording', () {
    const consent = AppConsent(status: ConsentStatus.granted, synced: true);
    expect(consent.decided, isTrue);
    expect(consent.recordingEnabled, isTrue);
    expect(consent.synced, isTrue);
  });

  test('denied counts as decided but keeps recording off', () {
    const consent = AppConsent(status: ConsentStatus.denied);
    expect(consent.decided, isTrue);
    expect(consent.recordingEnabled, isFalse);
  });

  test('withdrawn disables recording', () {
    const consent = AppConsent(status: ConsentStatus.withdrawn);
    expect(consent.decided, isTrue);
    expect(consent.recordingEnabled, isFalse);
  });

  test('json round-trip preserves the decision', () {
    const consent = AppConsent(status: ConsentStatus.granted, synced: true);
    final restored = AppConsent.fromJson(consent.toJson());
    expect(restored.status, ConsentStatus.granted);
    expect(restored.synced, isTrue);
    expect(restored.textVersion, consentTextVersion);
    expect(restored.recordingEnabled, isTrue);
  });

  test('json without a status restores undecided', () {
    final restored = AppConsent.fromJson(<String, dynamic>{'synced': false});
    expect(restored.decided, isFalse);
  });

  test('text version bump requires a new decision', () {
    const consent = AppConsent(status: ConsentStatus.granted);
    expect(consent.needsReconsent(consentTextVersion), isFalse);
    expect(consent.needsReconsent('v2'), isTrue);
  });
}