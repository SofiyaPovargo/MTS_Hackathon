import 'package:agreement_capture/application/providers.dart';
import 'package:agreement_capture/domain/enums.dart';
import 'package:agreement_capture/ui/screens/consent_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fakes.dart';

({InMemoryConsentStore store, FakeConsentApi api}) buildScope() {
  final store = InMemoryConsentStore();
  final api = FakeConsentApi();
  return (store: store, api: api);
}

Widget wrap(InMemoryConsentStore store, FakeConsentApi api, Widget child) {
  return ProviderScope(
    overrides: <Override>[
      consentStoreProvider.overrideWithValue(store),
      consentApiProvider.overrideWithValue(api),
    ],
    child: MaterialApp(home: child),
  );
}

void main() {
  testWidgets('renders the consent text and both actions', (tester) async {
    final scope = buildScope();
    await tester.pumpWidget(wrap(scope.store, scope.api, const ConsentScreen()));
    await tester.pumpAndSettle();

    expect(find.text('Запись и ИИ-обработка звонков'), findsOneWidget);
    expect(find.text('Согласен и включить запись'), findsOneWidget);
    expect(find.text('Не включать запись'), findsOneWidget);
    expect(find.text('Политика обработки данных'), findsOneWidget);
  });

  testWidgets('agreeing stores the decision and enables recording',
      (tester) async {
    final scope = buildScope();
    await tester.pumpWidget(wrap(scope.store, scope.api, const ConsentScreen()));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Согласен и включить запись'));
    await tester.pumpAndSettle();

    expect(scope.store.consent.status, ConsentStatus.granted);
    expect(scope.store.consent.recordingEnabled, isTrue);
    expect(scope.api.decisions, <bool>[true]);
  });

  testWidgets('declining keeps recording off', (tester) async {
    final scope = buildScope();
    await tester.pumpWidget(wrap(scope.store, scope.api, const ConsentScreen()));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Не включать запись'));
    await tester.pumpAndSettle();

    expect(scope.store.consent.status, ConsentStatus.denied);
    expect(scope.store.consent.recordingEnabled, isFalse);
    expect(scope.api.decisions, <bool>[false]);
  });
}