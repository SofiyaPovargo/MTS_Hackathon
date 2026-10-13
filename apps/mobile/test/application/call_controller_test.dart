import 'package:agreement_capture/application/providers.dart';
import 'package:agreement_capture/domain/call.dart';
import 'package:agreement_capture/domain/enums.dart';
import 'package:agreement_capture/infrastructure/api/api_exception.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fakes.dart';

({ProviderContainer container, FakeVoiceCallProvider voice, FakeCallApi api})
    buildContainer({bool permission = true, ApiException? apiError}) {
  final voice = FakeVoiceCallProvider(microphoneGranted: permission);
  final api = FakeCallApi(error: apiError);
  final container = ProviderContainer(
    overrides: <Override>[
      voiceCallProviderProvider.overrideWithValue(voice),
      callApiProvider.overrideWithValue(api),
    ],
  );
  return (container: container, voice: voice, api: api);
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
}
