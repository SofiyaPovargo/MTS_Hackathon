import 'package:agreement_capture/application/providers.dart';
import 'package:agreement_capture/domain/consent.dart';
import 'package:agreement_capture/domain/enums.dart';
import 'package:agreement_capture/infrastructure/api/api_exception.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fakes.dart';

({ProviderContainer container, InMemoryConsentStore store, FakeConsentApi api})
    buildContainer({AppConsent? consent, ApiException? apiError}) {
  final store = InMemoryConsentStore(consent ?? AppConsent.undecided);
  final api = FakeConsentApi(error: apiError);
  final container = ProviderContainer(
    overrides: <Override>[
      consentStoreProvider.overrideWithValue(store),
      consentApiProvider.overrideWithValue(api),
    ],
  );
  return (container: container, store: store, api: api);
}

void main() {
  test('a fresh install starts undecided', () async {
    final scope = buildContainer();
    addTearDown(scope.container.dispose);

    expect(
      await scope.container.read(consentControllerProvider.future),
      AppConsent.undecided,
    );
  });

  test('grant records the decision locally and notifies the server', () async {
    final scope = buildContainer();
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(consentControllerProvider.notifier);

    final message = await controller.grant();

    expect(message, isNull);
    expect(scope.api.decisions, <bool>[true]);
    final consent = scope.container.read(consentControllerProvider).valueOrNull;
    expect(consent?.status, ConsentStatus.granted);
    expect(consent?.recordingEnabled, isTrue);
    expect(consent?.synced, isTrue);
    expect(scope.store.consent.status, ConsentStatus.granted);
  });

  test('deny keeps the local decision and reports it to the server', () async {
    final scope = buildContainer();
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(consentControllerProvider.notifier);

    final message = await controller.deny();

    expect(message, isNull);
    expect(scope.api.decisions, <bool>[false]);
    final consent = scope.container.read(consentControllerProvider).valueOrNull;
    expect(consent?.status, ConsentStatus.denied);
    expect(consent?.recordingEnabled, isFalse);
    expect(consent?.synced, isTrue);
  });

  test('an offline decision stays local and is marked pending', () async {
    final scope = buildContainer(
      apiError: const ApiException(ApiErrorKind.network, 'offline'),
    );
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(consentControllerProvider.notifier);

    final message = await controller.grant();

    expect(message, contains('не удалась'));
    final consent = scope.container.read(consentControllerProvider).valueOrNull;
    expect(consent?.status, ConsentStatus.granted);
    expect(consent?.recordingEnabled, isTrue);
    expect(consent?.synced, isFalse);
    expect(scope.store.consent.synced, isFalse);
  });

  test('retrySync pushes a previously pending decision', () async {
    final scope = buildContainer(
      consent: const AppConsent(status: ConsentStatus.denied),
    );
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(consentControllerProvider.notifier);

    final message = await controller.retrySync();

    expect(message, isNull);
    expect(scope.api.decisions, <bool>[false]);
    final consent = scope.container.read(consentControllerProvider).valueOrNull;
    expect(consent?.synced, isTrue);
  });

  test('withdraw revokes consent on the device and the server', () async {
    final scope = buildContainer(
      consent: const AppConsent(status: ConsentStatus.granted, synced: true),
    );
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(consentControllerProvider.notifier);

    final message = await controller.withdraw();

    expect(message, isNull);
    expect(scope.api.withdrawals, 1);
    final consent = scope.container.read(consentControllerProvider).valueOrNull;
    expect(consent?.status, ConsentStatus.withdrawn);
    expect(consent?.recordingEnabled, isFalse);
  });

  test('requestDataDeletion enqueues the server-side job', () async {
    final scope = buildContainer();
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(consentControllerProvider.notifier);

    final message = await controller.requestDataDeletion();

    expect(message, isNull);
    expect(scope.api.deletions, 1);
  });
}