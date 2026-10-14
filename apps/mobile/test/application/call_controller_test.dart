import 'package:agreement_capture/application/providers.dart';
import 'package:agreement_capture/application/recording_service.dart';
import 'package:agreement_capture/domain/audio.dart';
import 'package:agreement_capture/domain/call.dart';
import 'package:agreement_capture/domain/consent.dart';
import 'package:agreement_capture/domain/enums.dart';
import 'package:agreement_capture/domain/models.dart';
import 'package:agreement_capture/domain/ws_event.dart';
import 'package:agreement_capture/infrastructure/api/api_exception.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fakes.dart';

({
  ProviderContainer container,
  FakeVoiceCallProvider voice,
  FakeCallApi api,
  FakeCallEventsPort events,
  InMemoryAudioRecordingStore store,
  FakeAudioIngestApi ingest,
  FakeLiveAudioPort live,
  FakeScheduleApi schedule,
}) buildContainer({
  bool permission = true,
  ApiException? apiError,
  ApiException? eventsError,
  ApiException? agreementError,
  ApiException? scheduleError,
  AppConsent consent = AppConsent.undecided,
}) {
  final voice = FakeVoiceCallProvider(microphoneGranted: permission);
  final api = FakeCallApi(error: apiError);
  final events = FakeCallEventsPort(error: eventsError);
  final agreementApi = FakeAgreementApi(error: agreementError);
  final store = InMemoryAudioRecordingStore();
  final ingest = FakeAudioIngestApi();
  final live = FakeLiveAudioPort();
  final schedule = FakeScheduleApi(error: scheduleError);
  final container = ProviderContainer(
    overrides: <Override>[
      voiceCallProviderProvider.overrideWithValue(voice),
      callApiProvider.overrideWithValue(api),
      consentStoreProvider.overrideWithValue(InMemoryConsentStore(consent)),
      consentApiProvider.overrideWithValue(FakeConsentApi()),
      // Always fake the live feed: the real client opens a socket.
      callEventsProvider.overrideWithValue(events),
      agreementApiProvider.overrideWithValue(agreementApi),
      // Always fake the call summary: the real client hits the network.
      scheduleApiProvider.overrideWithValue(schedule),
      // Always fake Stage 6 audio: the real store opens sqflite and a socket.
      recordingServiceProvider.overrideWithValue(
        CallRecordingService(
          recorder: voice,
          store: store,
          ingest: ingest,
          live: live,
          chunkSize: 8,
        ),
      ),
    ],
  );
  return (
    container: container,
    voice: voice,
    api: api,
    events: events,
    store: store,
    ingest: ingest,
    live: live,
    schedule: schedule,
  );
}

const testCallId = '55555555-5555-5555-5555-555555555555';

CallEvent testEvent(String event, {Map<String, dynamic> payload = const {}}) {
  return CallEvent(
    version: 1,
    kind: CallEventKind.fromWire(event),
    callId: testCallId,
    payload: payload,
  );
}

void main() {
  test('outgoing call dials, connects and completes', () async {
    final scope = buildContainer();
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(callControllerProvider.notifier);

    final error = await controller.startOutgoing('+79000000002', name: 'Анна');
    expect(error, isNull);
    expect(scope.voice.dialed, <String>['+79000000002']);
    expect(scope.api.created.single.contactPhone, '+79000000002');
    expect(
      scope.container.read(callControllerProvider)?.status,
      CallLifecycleStatus.ringing,
    );

    scope.voice.emit(const CallSignal(kind: CallSignalKind.answered));
    await pumpEventQueue();
    expect(
      scope.container.read(callControllerProvider)?.status,
      CallLifecycleStatus.inProgress,
    );
    expect(scope.container.read(callControllerProvider)?.answeredAt, isNotNull);

    await controller.hangup();
    await pumpEventQueue();
    expect(
      scope.container.read(callControllerProvider)?.status,
      CallLifecycleStatus.completed,
    );
    expect(scope.container.read(callControllerProvider)?.endedAt, isNotNull);
  });

  test('granted consent records the call and uploads on hangup', () async {
    final scope = buildContainer(
      consent: const AppConsent(status: ConsentStatus.granted, synced: true),
    );
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(callControllerProvider.notifier);

    await controller.startOutgoing('+79000000002', name: 'Анна');
    final callId = scope.api.created.single.id;

    scope.voice.emit(const CallSignal(kind: CallSignalKind.answered));
    await pumpEventQueue();

    // The backend reports the counterparty granted consent → recording starts,
    // the audio is buffered locally and streamed live.
    controller.markConsentResult(granted: true);
    await pumpEventQueue();
    await pumpEventQueue();

    expect(scope.voice.mediaStreamOpened, isNotEmpty);
    expect(scope.live.connected, <String>[callId]);

    scope.voice.emitAudio(List<int>.filled(12, 1));
    await pumpEventQueue();

    await controller.hangup();
    await pumpEventQueue();

    final recorded = await scope.store.get(callId);
    expect(recorded, isNotNull);
    expect(recorded!.bytesTotal, 12);
    expect(recorded.status, RecordingUploadStatus.uploaded);
    expect(scope.ingest.calls, isNotEmpty);
  });

  test('outgoing call is blocked without microphone permission', () async {
    final scope = buildContainer(permission: false);
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(callControllerProvider.notifier);

    final error = await controller.startOutgoing('+79000000002');

    expect(error, contains('микрофон'));
    expect(scope.voice.dialed, isEmpty);
    expect(scope.api.created, isEmpty);
    expect(scope.container.read(callControllerProvider), isNull);
  });

  test('empty number is rejected without dialing', () async {
    final scope = buildContainer();
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(callControllerProvider.notifier);

    expect(await controller.startOutgoing('   '), 'Введите номер');
    expect(scope.voice.dialed, isEmpty);
  });

  test('backend failure surfaces the message and does not dial', () async {
    final scope = buildContainer(
      apiError: const ApiException(ApiErrorKind.network, 'offline'),
    );
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(callControllerProvider.notifier);

    expect(await controller.startOutgoing('+79000000002'), 'offline');
    expect(scope.voice.dialed, isEmpty);
    expect(scope.container.read(callControllerProvider), isNull);
  });

  test('incoming call can be answered', () async {
    final scope = buildContainer();
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(callControllerProvider.notifier);

    scope.voice.simulateIncoming(phone: '+79000000003', name: 'Борис');
    await pumpEventQueue();
    final incoming = scope.container.read(callControllerProvider);
    expect(incoming?.status, CallLifecycleStatus.incoming);
    expect(incoming?.isIncoming, isTrue);
    expect(incoming?.displayName, 'Борис');

    expect(await controller.answerIncoming(), isTrue);
    await pumpEventQueue();
    expect(scope.voice.answered, isNotEmpty);
    expect(
      scope.container.read(callControllerProvider)?.status,
      CallLifecycleStatus.inProgress,
    );
  });

  test('permission denied keeps the incoming call on screen', () async {
    final scope = buildContainer(permission: false);
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(callControllerProvider.notifier);

    scope.voice.simulateIncoming(phone: '+79000000003');
    await pumpEventQueue();

    expect(await controller.answerIncoming(), isFalse);
    expect(scope.voice.answered, isEmpty);
    expect(
      scope.container.read(callControllerProvider)?.status,
      CallLifecycleStatus.incoming,
    );
  });

  test('declined incoming call becomes missed', () async {
    final scope = buildContainer();
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(callControllerProvider.notifier);

    scope.voice.simulateIncoming(phone: '+79000000003');
    await pumpEventQueue();
    await controller.declineIncoming();
    await pumpEventQueue();

    expect(scope.voice.declined, isNotEmpty);
    expect(
      scope.container.read(callControllerProvider)?.status,
      CallLifecycleStatus.missed,
    );
  });

  test('a dropped transport marks the call failed', () async {
    final scope = buildContainer();
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(callControllerProvider.notifier);

    await controller.startOutgoing('+79000000002');
    scope.voice.emit(const CallSignal(kind: CallSignalKind.dropped));
    await pumpEventQueue();

    expect(
      scope.container.read(callControllerProvider)?.status,
      CallLifecycleStatus.failed,
    );
  });

  test('missed while ringing becomes missed', () async {
    final scope = buildContainer();
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(callControllerProvider.notifier);

    await controller.startOutgoing('+79000000002');
    await controller.hangup();
    await pumpEventQueue();

    expect(
      scope.container.read(callControllerProvider)?.status,
      CallLifecycleStatus.missed,
    );
  });

  test('mute toggles and clears with the terminal state', () async {
    final scope = buildContainer();
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(callControllerProvider.notifier);

    await controller.startOutgoing('+79000000002');
    await controller.toggleMute();
    expect(scope.container.read(callControllerProvider)?.muted, isTrue);
    expect(scope.voice.muted, <bool>[true]);

    await controller.toggleMute();
    expect(scope.container.read(callControllerProvider)?.muted, isFalse);

    await controller.hangup();
    await pumpEventQueue();
    controller.clear();
    expect(scope.container.read(callControllerProvider), isNull);
  });

  test('a signal without an active call is ignored', () async {
    final scope = buildContainer();
    addTearDown(scope.container.dispose);
    scope.container.read(callControllerProvider.notifier);

    scope.voice.emit(const CallSignal(kind: CallSignalKind.answered));
    await pumpEventQueue();

    expect(scope.container.read(callControllerProvider), isNull);
  });

  test('granted consent routes an answered call through the consent flow',
      () async {
    final scope = buildContainer(
      consent: const AppConsent(status: ConsentStatus.granted, synced: true),
    );
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(callControllerProvider.notifier);

    await controller.startOutgoing('+79000000002');
    expect(
      scope.container.read(callControllerProvider)?.recordingEnabled,
      isTrue,
    );

    scope.voice.emit(const CallSignal(kind: CallSignalKind.answered));
    await pumpEventQueue();
    expect(
      scope.container.read(callControllerProvider)?.status,
      CallLifecycleStatus.consentNotice,
    );

    controller.markConsentResult(granted: true);
    expect(
      scope.container.read(callControllerProvider)?.status,
      CallLifecycleStatus.recording,
    );

    controller.markAnalysisStarted();
    expect(
      scope.container.read(callControllerProvider)?.status,
      CallLifecycleStatus.analyzing,
    );

    controller.markCallActive();
    expect(
      scope.container.read(callControllerProvider)?.status,
      CallLifecycleStatus.inProgress,
    );
  });

  test('counterparty refusal continues as a non-recorded ordinary call',
      () async {
    final scope = buildContainer(
      consent: const AppConsent(status: ConsentStatus.granted, synced: true),
    );
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(callControllerProvider.notifier);

    await controller.startOutgoing('+79000000002');
    scope.voice.emit(const CallSignal(kind: CallSignalKind.answered));
    await pumpEventQueue();
    expect(
      scope.container.read(callControllerProvider)?.status,
      CallLifecycleStatus.consentNotice,
    );

    controller.markConsentResult(granted: false);

    final call = scope.container.read(callControllerProvider);
    expect(call?.status, CallLifecycleStatus.inProgress);
    expect(call?.recordingEnabled, isFalse);
    expect(call?.participantDeclined, isTrue);
  });

  test('no app consent keeps the call ordinary and recording off', () async {
    final scope = buildContainer();
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(callControllerProvider.notifier);

    await controller.startOutgoing('+79000000002');
    expect(
      scope.container.read(callControllerProvider)?.recordingEnabled,
      isFalse,
    );

    scope.voice.emit(const CallSignal(kind: CallSignalKind.answered));
    await pumpEventQueue();

    final call = scope.container.read(callControllerProvider);
    expect(call?.status, CallLifecycleStatus.inProgress);
    expect(call?.recordingEnabled, isFalse);
    expect(call?.participantDeclined, isFalse);
  });

  test('answered incoming call carries the app consent recording flag',
      () async {
    final scope = buildContainer(
      consent: const AppConsent(status: ConsentStatus.granted, synced: true),
    );
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(callControllerProvider.notifier);

    scope.voice.simulateIncoming(phone: '+79000000003', name: 'Борис');
    await pumpEventQueue();

    expect(await controller.answerIncoming(), isTrue);
    await pumpEventQueue();

    final call = scope.container.read(callControllerProvider);
    expect(call?.status, CallLifecycleStatus.consentNotice);
    expect(call?.recordingEnabled, isTrue);
  });

  test('live: the feed connects for a recorded call and streams segments',
      () async {
    final scope = buildContainer(
      consent: const AppConsent(status: ConsentStatus.granted, synced: true),
    );
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(callControllerProvider.notifier);

    await controller.startOutgoing('+79000000002');
    scope.voice.emit(const CallSignal(kind: CallSignalKind.answered));
    await pumpEventQueue();
    await pumpEventQueue();
    expect(scope.events.connected, <String>[testCallId]);

    scope.events.emit(testEvent('partial_transcript', payload: {
      'speaker': 'user',
      'text': 'оплачу до пятницы',
      'start': 12.5,
      'end': 18.0,
    }));
    scope.events.emit(testEvent('partial_transcript', payload: {
      'speaker': 'counterparty',
      'text': 'отлично, жду',
      'start': 19.0,
      'end': 21.0,
    }));
    await pumpEventQueue();

    final transcript =
        scope.container.read(callControllerProvider)?.transcript;
    expect(transcript, hasLength(2));
    expect(transcript?.first.text, 'оплачу до пятницы');
    expect(transcript?.last.speaker, 'counterparty');
  });

  test('live: analysis_started drives the consent → recording → analyzing chain',
      () async {
    final scope = buildContainer(
      consent: const AppConsent(status: ConsentStatus.granted, synced: true),
    );
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(callControllerProvider.notifier);

    await controller.startOutgoing('+79000000002');
    scope.voice.emit(const CallSignal(kind: CallSignalKind.answered));
    await pumpEventQueue();
    expect(
      scope.container.read(callControllerProvider)?.status,
      CallLifecycleStatus.consentNotice,
    );

    scope.events.emit(testEvent('analysis_started'));
    await pumpEventQueue();

    expect(
      scope.container.read(callControllerProvider)?.status,
      CallLifecycleStatus.analyzing,
    );
    expect(
      scope.container.read(callControllerProvider)?.recordingEnabled,
      isTrue,
    );
  });

  test('live: agreement_detected upserts cards, newest first, no duplicates',
      () async {
    final scope = buildContainer(
      consent: const AppConsent(status: ConsentStatus.granted, synced: true),
    );
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(callControllerProvider.notifier);

    await controller.startOutgoing('+79000000002');
    scope.voice.emit(const CallSignal(kind: CallSignalKind.answered));
    await pumpEventQueue();
    await pumpEventQueue();

    scope.events.emit(testEvent('agreement_detected', payload: {
      'id': 'agr-1',
      'call_id': testCallId,
      'type': 'payment',
      'title': 'Оплатить счёт',
      'owner': 'user',
      'due_date': null,
      'due_time': null,
      'source_quote': 'оплачу до пятницы',
      'audio_start': 12.5,
      'audio_end': 18.0,
      'confidence': 0.92,
      'status': 'detected',
    }));
    scope.events.emit(testEvent('agreement_detected', payload: {
      'id': 'agr-2',
      'call_id': testCallId,
      'type': 'follow_up',
      'title': 'Перезвонить завтра',
      'owner': 'counterparty',
      'due_date': null,
      'due_time': null,
      'source_quote': 'перезвоню завтра',
      'audio_start': 30.0,
      'audio_end': 34.0,
      'confidence': 0.81,
      'status': 'detected',
    }));
    await pumpEventQueue();

    var agreements = scope.container.read(callControllerProvider)?.agreements;
    expect(agreements, hasLength(2));
    expect(agreements?.first.id, 'agr-2');

    // Re-delivery of the same agreement replaces the card, not duplicates it.
    scope.events.emit(testEvent('agreement_detected', payload: {
      'id': 'agr-1',
      'call_id': testCallId,
      'type': 'payment',
      'title': 'Оплатить счёт (обновлено)',
      'owner': 'user',
      'due_date': '2026-10-15',
      'due_time': null,
      'source_quote': 'оплачу до пятницы',
      'audio_start': 12.5,
      'audio_end': 18.0,
      'confidence': 0.97,
      'status': 'detected',
    }));
    await pumpEventQueue();

    agreements = scope.container.read(callControllerProvider)?.agreements;
    expect(agreements, hasLength(2));
    expect(agreements?.first.id, 'agr-1');
    expect(agreements?.first.title, 'Оплатить счёт (обновлено)');
    expect(agreements?.first.dueDate, DateTime(2026, 10, 15));
  });

  test('live: call_ended completes the call and disconnects', () async {
    final scope = buildContainer(
      consent: const AppConsent(status: ConsentStatus.granted, synced: true),
    );
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(callControllerProvider.notifier);

    await controller.startOutgoing('+79000000002');
    scope.voice.emit(const CallSignal(kind: CallSignalKind.answered));
    await pumpEventQueue();
    await pumpEventQueue();

    scope.events.emit(testEvent('call_ended'));
    await pumpEventQueue();

    expect(
      scope.container.read(callControllerProvider)?.status,
      CallLifecycleStatus.completed,
    );
    expect(scope.events.disconnectCalls, greaterThanOrEqualTo(1));
  });

  test('live: events for another call are ignored', () async {
    final scope = buildContainer(
      consent: const AppConsent(status: ConsentStatus.granted, synced: true),
    );
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(callControllerProvider.notifier);

    await controller.startOutgoing('+79000000002');
    scope.voice.emit(const CallSignal(kind: CallSignalKind.answered));
    await pumpEventQueue();
    await pumpEventQueue();

    scope.events.emit(const CallEvent(
      version: 1,
      kind: CallEventKind.partialTranscript,
      callId: '00000000-0000-0000-0000-000000000000',
      payload: <String, dynamic>{'text': 'чужой сегмент'},
    ));
    await pumpEventQueue();

    expect(scope.container.read(callControllerProvider)?.transcript, isEmpty);
  });

  test('live: recording-off or UI-only calls never open the feed', () async {
    final scope = buildContainer();
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(callControllerProvider.notifier);

    // App consent off → ordinary call.
    await controller.startOutgoing('+79000000002');
    scope.voice.emit(const CallSignal(kind: CallSignalKind.answered));
    await pumpEventQueue();
    await pumpEventQueue();
    expect(scope.events.connected, isEmpty);

    // Incoming mock has no backend id → nothing to subscribe to.
    scope.voice.simulateIncoming(phone: '+79000000003');
    await pumpEventQueue();
    await controller.answerIncoming();
    await pumpEventQueue();
    expect(scope.events.connected, isEmpty);
  });

  test('live: a failed handshake leaves the call usable (no crash)', () async {
    final scope = buildContainer(
      eventsError: const ApiException(ApiErrorKind.network, 'no network'),
      consent: const AppConsent(status: ConsentStatus.granted, synced: true),
    );
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(callControllerProvider.notifier);

    await controller.startOutgoing('+79000000002');
    scope.voice.emit(const CallSignal(kind: CallSignalKind.answered));
    await pumpEventQueue();
    await pumpEventQueue();

    expect(scope.events.connected, isEmpty);
    expect(
      scope.container.read(callControllerProvider)?.status,
      CallLifecycleStatus.consentNotice,
    );
    expect(scope.container.read(callControllerProvider), isNotNull);
  });

  test('agreements: confirm, reject, edit and manual create round-trip',
      () async {
    final scope = buildContainer(
      consent: const AppConsent(status: ConsentStatus.granted, synced: true),
    );
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(callControllerProvider.notifier);

    await controller.startOutgoing('+79000000002');

    // Confirm a detected agreement (server flips the status → task is created).
    await controller.confirmAgreement('33333333-3333-3333-3333-333333333333');
    expect(
      scope.container.read(callControllerProvider)?.agreements.single.status,
      AgreementStatus.confirmed,
    );

    // Reject another one.
    await controller.rejectAgreement('77777777-7777-7777-7777-777777777777');
    expect(
      scope.container
          .read(callControllerProvider)
          ?.agreements
          .firstWhere((a) => a.id == '77777777-7777-7777-7777-777777777777')
          .status,
      AgreementStatus.rejected,
    );

    // Edit a card.
    await controller.editAgreement(
      '33333333-3333-3333-3333-333333333333',
      const AgreementPatch(title: 'Оплатить счёт до 20-го'),
    );
    expect(
      scope.container
          .read(callControllerProvider)
          ?.agreements
          .firstWhere((a) => a.id == '33333333-3333-3333-3333-333333333333')
          .title,
      'Оплатить счёт до 20-го',
    );

    // Manual entry (no-consent path) creates a card on the server.
    expect(
      await controller.createManualAgreement(
        const AgreementPatch(title: 'Встреча в пятницу', type: 'meeting'),
      ),
      isNull,
    );
    final cards = scope.container.read(callControllerProvider)?.agreements;
    expect(cards?.first.id, 'created-1');
    expect(cards?.first.callId, testCallId);
    expect(cards?.first.title, 'Встреча в пятницу');
    expect(cards?.first.type, 'meeting');
  });

  test('agreements: manual create requires an active call', () async {
    final scope = buildContainer();
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(callControllerProvider.notifier);

    expect(
      await controller.createManualAgreement(
        const AgreementPatch(title: 'Встреча'),
      ),
      'Нет активного звонка',
    );
  });

  test('agreements: a server error is surfaced without touching the card',
      () async {
    final scope = buildContainer(
      agreementError: const ApiException(ApiErrorKind.server, 'boom'),
      consent: const AppConsent(status: ConsentStatus.granted, synced: true),
    );
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(callControllerProvider.notifier);

    await controller.startOutgoing('+79000000002');
    expect(
      await controller.confirmAgreement('33333333-3333-3333-3333-333333333333'),
      'boom',
    );
    expect(scope.container.read(callControllerProvider)?.agreements, isEmpty);
  });

  test('summary: a completed call auto-loads the итог onto CallState',
      () async {
    final scope = buildContainer();
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(callControllerProvider.notifier);

    await controller.startOutgoing('+79000000002');
    scope.voice.emit(const CallSignal(kind: CallSignalKind.answered));
    await pumpEventQueue();

    await controller.hangup();
    await pumpEventQueue();

    final call = scope.container.read(callControllerProvider);
    expect(call?.status, CallLifecycleStatus.completed);
    expect(call?.callSummary?.agreementsTotal, 2);
    expect(call?.callSummary?.agreementsConfirmed, 1);
    expect(call?.callSummary?.summary, isNotEmpty);
    expect(scope.schedule.summaryCalls, 1);
  });

  test('summary: loadSummary surfaces the error without touching the call',
      () async {
    final scope = buildContainer(
      scheduleError: const ApiException(ApiErrorKind.network, 'offline'),
    );
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(callControllerProvider.notifier);

    await controller.startOutgoing('+79000000002');

    expect(await controller.loadSummary(), 'offline');
    expect(scope.container.read(callControllerProvider)?.callSummary, isNull);
    expect(scope.container.read(callControllerProvider), isNotNull);
  });
}
