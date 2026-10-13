import 'package:agreement_capture/application/providers.dart';
import 'package:agreement_capture/infrastructure/sync/sync_engine.dart';
import 'package:agreement_capture/ui/app.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fakes.dart';

void main() {
  testWidgets('shows the login screen when unauthenticated', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: <Override>[
          sessionStoreProvider.overrideWithValue(InMemorySessionStore()),
          authApiProvider.overrideWithValue(FakeAuthApi(session: testSession())),
        ],
        child: const AgreementCaptureApp(),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Захват соглашений'), findsOneWidget);
    expect(find.text('Получить код'), findsOneWidget);
  });

  testWidgets('shows the personal board when authenticated', (tester) async {
    final local = InMemoryBoardStore()..tasks['t1'] = testTask();
    final engine = SyncEngine(
      syncApi: FakeSyncApi(),
      board: local,
      outbox: InMemoryOutboxStore(),
      state: InMemorySyncStateStore(),
      baseBackoff: const Duration(milliseconds: 1),
    );
    final session = InMemorySessionStore()..session = testSession();

    await tester.pumpWidget(
      ProviderScope(
        overrides: <Override>[
          sessionStoreProvider.overrideWithValue(session),
          authApiProvider.overrideWithValue(FakeAuthApi(session: testSession())),
          localBoardStoreProvider.overrideWithValue(local),
          syncEngineProvider.overrideWithValue(engine),
        ],
        child: const AgreementCaptureApp(),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Позвонить клиенту'), findsOneWidget);
  });
}
