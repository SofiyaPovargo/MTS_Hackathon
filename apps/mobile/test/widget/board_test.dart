import 'package:agreement_capture/application/providers.dart';
import 'package:agreement_capture/domain/enums.dart';
import 'package:agreement_capture/domain/models.dart';
import 'package:agreement_capture/infrastructure/sync/sync_engine.dart';
import 'package:agreement_capture/ui/screens/board_screen.dart';
import 'package:agreement_capture/ui/screens/manager_board_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fakes.dart';

Future<void> pumpBoard(
  WidgetTester tester, {
  required InMemoryBoardStore local,
  UserProfile? user,
}) async {
  final profile = user ?? testUser();
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
        sessionStoreProvider.overrideWithValue(InMemorySessionStore()..session = testSession(user: profile)),
        authApiProvider.overrideWithValue(FakeAuthApi(session: testSession(user: profile))),
        localBoardStoreProvider.overrideWithValue(local),
        syncEngineProvider.overrideWithValue(engine),
        outboxStoreProvider.overrideWithValue(outbox),
      ],
      child: const MaterialApp(home: BoardScreen()),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('personal board groups tasks into sections and runs an action',
      (tester) async {
    final now = DateTime.now();
    final local = InMemoryBoardStore()
      ..tasks['overdue'] = testTask(
        id: 'overdue',
        title: 'Просроченная задача',
        status: TaskStatus.overdue,
        dueDate: now.subtract(const Duration(days: 2)),
      )
      ..tasks['today'] = testTask(
        id: 'today',
        title: 'Задача на сегодня',
        dueDate: now,
      );
    await pumpBoard(tester, local: local);

    expect(find.text('Просроченные'), findsOneWidget);
    expect(find.text('Сегодня'), findsOneWidget);
    expect(find.text('Просроченная задача'), findsOneWidget);

    // Tapping a task opens its actions; completing it updates the local store.
    await tester.tap(find.text('Просроченная задача'));
    await tester.pumpAndSettle();
    expect(find.text('Отметить выполненной'), findsOneWidget);

    await tester.tap(find.text('Отметить выполненной'));
    await tester.pumpAndSettle();

    expect(local.tasks['overdue']!.status, TaskStatus.done);
    expect(find.text('Выполненные'), findsOneWidget);
  });

  testWidgets('manager sees a link to the team board', (tester) async {
    final local = InMemoryBoardStore()..tasks['t1'] = testTask();
    await pumpBoard(tester, local: local, user: testUser(role: Role.manager));

    expect(find.byTooltip('Доска команды'), findsOneWidget);
  });

  testWidgets('a regular user has no team board link', (tester) async {
    final local = InMemoryBoardStore()..tasks['t1'] = testTask();
    await pumpBoard(tester, local: local);

    expect(find.byTooltip('Доска команды'), findsNothing);
  });

  testWidgets('manager board shows tasks, analytics and members', (tester) async {
    final api = FakeManagerApi(
      tasks: <TaskItem>[
        testTask(id: 't1', title: 'Задача команды'),
      ],
      members: <TeamMember>[testMember()],
      stats: testStats(tasksTotal: 7, overdue: 2),
    );
    await tester.pumpWidget(
      ProviderScope(
        overrides: <Override>[managerApiProvider.overrideWithValue(api)],
        child: const MaterialApp(home: ManagerBoardScreen()),
      ),
    );
    await tester.pumpAndSettle();

    // Tasks tab (default).
    expect(find.text('Задача команды'), findsOneWidget);
    expect(find.textContaining('Анна'), findsOneWidget);

    await tester.tap(find.text('Аналитика'));
    await tester.pumpAndSettle();
    expect(find.text('Всего задач'), findsOneWidget);
    expect(find.text('7'), findsOneWidget);

    await tester.tap(find.text('Сотрудники'));
    await tester.pumpAndSettle();
    expect(find.text('Анна'), findsOneWidget);
    expect(find.text('+79000000002'), findsOneWidget);
  });
}
