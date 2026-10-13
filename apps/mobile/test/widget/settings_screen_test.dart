import 'package:agreement_capture/application/providers.dart';
import 'package:agreement_capture/domain/consent.dart';
import 'package:agreement_capture/domain/enums.dart';
import 'package:agreement_capture/ui/screens/settings_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fakes.dart';

({
  InMemoryConsentStore store,
  FakeConsentApi api,
}) buildScope({AppConsent consent = AppConsent.undecided}) {
  final store = InMemoryConsentStore(consent);
  final api = FakeConsentApi();
  return (store: store, api: api);
}

Widget wrap(InMemoryConsentStore store, FakeConsentApi api) {
  return ProviderScope(
    overrides: <Override>[
      consentStoreProvider.overrideWithValue(store),
      consentApiProvider.overrideWithValue(api),
    ],
    child: const MaterialApp(home: SettingsScreen()),
  );
}

void main() {
  testWidgets('shows the current recording status', (tester) async {
    final scope = buildScope(
      consent: const AppConsent(status: ConsentStatus.granted, synced: true),
    );
    await tester.pumpWidget(wrap(scope.store, scope.api));
    await tester.pumpAndSettle();

    expect(find.text('Запись и ИИ-обработка'), findsOneWidget);
    expect(find.text('Запись и ИИ-обработка включены'), findsOneWidget);
    expect(tester.widget<Switch>(find.byType(Switch)).value, isTrue);
  });

  testWidgets('toggling the switch denies recording on the server',
      (tester) async {
    final scope = buildScope(
      consent: const AppConsent(status: ConsentStatus.granted, synced: true),
    );
    await tester.pumpWidget(wrap(scope.store, scope.api));
    await tester.pumpAndSettle();

    await tester.tap(find.byType(Switch));
    await tester.pumpAndSettle();

    expect(scope.api.decisions, <bool>[false]);
    expect(scope.store.consent.status, ConsentStatus.denied);
    expect(scope.store.consent.recordingEnabled, isFalse);
  });

  testWidgets('a pending offline decision is surfaced with a retry',
      (tester) async {
    final scope = buildScope(
      consent: const AppConsent(status: ConsentStatus.denied),
    );
    await tester.pumpWidget(wrap(scope.store, scope.api));
    await tester.pumpAndSettle();

    expect(find.text('Не синхронизировано с сервером'), findsOneWidget);

    await tester.tap(find.text('Повторить'));
    await tester.pumpAndSettle();

    expect(scope.api.decisions, <bool>[false]);
    expect(scope.store.consent.synced, isTrue);
  });

  testWidgets('withdrawal requires confirmation before running', (tester) async {
    final scope = buildScope(
      consent: const AppConsent(status: ConsentStatus.granted, synced: true),
    );
    await tester.pumpWidget(wrap(scope.store, scope.api));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Отозвать согласие'));
    await tester.pumpAndSettle();
    expect(find.text('Отозвать согласие?'), findsOneWidget);

    await tester.tap(find.text('Подтвердить'));
    await tester.pumpAndSettle();

    expect(scope.api.withdrawals, 1);
    expect(scope.store.consent.status, ConsentStatus.withdrawn);
  });

  testWidgets('data deletion is confirmed and enqueued on the server',
      (tester) async {
    final scope = buildScope();
    await tester.pumpWidget(wrap(scope.store, scope.api));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Удалить мои данные'));
    await tester.pumpAndSettle();
    expect(find.text('Удалить все данные?'), findsOneWidget);

    await tester.tap(find.text('Подтвердить'));
    await tester.pumpAndSettle();

    expect(scope.api.deletions, 1);
  });
}