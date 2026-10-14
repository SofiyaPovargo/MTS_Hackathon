import 'package:agreement_capture/application/providers.dart';
import 'package:agreement_capture/infrastructure/sync/sync_engine.dart';
import 'package:agreement_capture/ui/screens/board_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fakes.dart';

Future<FakeScheduleApi> pumpBoard(
  WidgetTester tester, {
  required InMemoryBoardStore local,
  FakeScheduleApi? scheduleApi,
}) async {
  final schedule = scheduleApi ?? FakeScheduleApi();
  final outbox = InMemoryOutboxStore();
  final engine = SyncEngine(
    syncApi: FakeSyncApi(),
    board: local,
    outbox: outbox,
    state: InMemorySyncStateStore(),
    baseBackoff: const Duration(milliseconds: 1),
  );
  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[
        sessionStoreProvider.overrideWithValue(
          InMemorySessionStore()..session = testSession(),
        ),
        authApiProvider.overrideWithValue(FakeAuthApi(session: testSession())),
        localBoardStoreProvider.overrideWithValue(local),
        syncEngineProvider.overrideWithValue(engine),
        outboxStoreProvider.overrideWithValue(outbox),
        scheduleApiProvider.overrideWithValue(schedule),
      ],
      child: const MaterialApp(home: BoardScreen()),
    ),
  );
  await tester.pumpAndSettle();
  return schedule;
}

InMemoryBoardStore boardWithTask() =>
    InMemoryBoardStore()..tasks['t1'] = testTask(id: 't1');

Future<void> openTask(WidgetTester tester) async {
  await tester.tap(find.text('Позвонить клиенту'));
  await tester.pumpAndSettle();
}

void main() {
  // The actions sheet is long; a taller surface keeps every tile tappable.
  testWidgets('adding to the calendar confirms before calling the controller',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(800, 1400));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final schedule = await pumpBoard(tester, local: boardWithTask());

    await openTask(tester);
    expect(find.text('Добавить в календарь'), findsOneWidget);

    await tester.tap(find.text('Добавить в календарь'));
    await tester.pumpAndSettle();
    // A confirmation dialog opens before any write.
    expect(find.text('Добавить в календарь?'), findsOneWidget);
    expect(schedule.calendarCalls, 0);

    await tester.tap(find.text('Подтвердить'));
    await tester.pumpAndSettle();

    expect(schedule.calendarCalls, 1);
    expect(find.textContaining('Событие создано'), findsOneWidget);
  });

  testWidgets('cancelling the confirmation never calls the controller',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(800, 1400));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final schedule = await pumpBoard(tester, local: boardWithTask());

    await openTask(tester);
    await tester.tap(find.text('Добавить в календарь'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Отмена'));
    await tester.pumpAndSettle();

    expect(schedule.calendarCalls, 0);
  });

  testWidgets('the client-message draft is explicitly not sent automatically',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(800, 1400));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final schedule = await pumpBoard(tester, local: boardWithTask());

    await openTask(tester);
    await tester.tap(find.text('Черновик клиенту'));
    await tester.pumpAndSettle();
    expect(find.text('Черновик сообщения клиенту?'), findsOneWidget);

    await tester.tap(find.text('Подтвердить'));
    await tester.pumpAndSettle();

    expect(schedule.draftCalls, 1);
    expect(find.textContaining(schedule.draft.text), findsOneWidget);
    expect(find.textContaining('не отправлено автоматически'), findsOneWidget);
    expect(find.text('Копировать'), findsOneWidget);
  });

  testWidgets('a reminder preset schedules a reminder', (tester) async {
    await tester.binding.setSurfaceSize(const Size(800, 1400));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final schedule = await pumpBoard(tester, local: boardWithTask());

    await openTask(tester);
    await tester.tap(find.text('Напоминание'));
    await tester.pumpAndSettle();
    expect(find.text('Через час'), findsOneWidget);

    await tester.tap(find.text('Через час'));
    await tester.pumpAndSettle();

    expect(schedule.reminderCalls, 1);
    expect(find.textContaining('Напоминание создано'), findsOneWidget);
  });
}
