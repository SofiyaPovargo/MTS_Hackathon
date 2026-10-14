import 'package:agreement_capture/application/manager_controller.dart';
import 'package:agreement_capture/application/providers.dart';
import 'package:agreement_capture/domain/enums.dart';
import 'package:agreement_capture/domain/models.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fakes.dart';

ProviderContainer buildContainer(FakeManagerApi api) {
  return ProviderContainer(
    overrides: <Override>[managerApiProvider.overrideWithValue(api)],
  );
}

void main() {
  test('build loads team tasks, stats and members', () async {
    final api = FakeManagerApi(
      tasks: <TaskItem>[testTask(id: 't1', title: 'Задача команды')],
      members: <TeamMember>[testMember(id: 'u1')],
      stats: testStats(tasksTotal: 3),
    );
    final scope = buildContainer(api);
    addTearDown(scope.dispose);

    final board = await scope.read(managerControllerProvider.future);

    expect(board.tasks.single.id, 't1');
    expect(board.members.single.fullName, 'Анна');
    expect(board.stats.tasksTotal, 3);
    expect(board.memberName('u1'), 'Анна');
    expect(board.memberName('unknown'), '—');
  });

  test('applyFilter sends the priority/type/due filters to the server', () async {
    final api = FakeManagerApi(members: <TeamMember>[testMember(id: 'u1')]);
    final scope = buildContainer(api);
    addTearDown(scope.dispose);
    await scope.read(managerControllerProvider.future);

    await scope.read(managerControllerProvider.notifier).applyFilter(
          ManagerFilter(
            userId: 'u1',
            status: TaskStatus.overdue,
            priority: TaskPriority.high,
            taskType: 'payment',
            dueBefore: DateTime(2026, 10, 20),
          ),
        );

    expect(api.lastUserId, 'u1');
    expect(api.lastStatus, 'overdue');
    expect(api.lastPriority, 'high');
    expect(api.lastTaskType, 'payment');
    expect(api.lastDueBefore, DateTime(2026, 10, 20));
    final board = scope.read(managerControllerProvider).value!;
    expect(board.filter.priority, TaskPriority.high);
    expect(board.filter.taskType, 'payment');
  });

  test('clearing a task-type filter drops it from the request', () async {
    final api = FakeManagerApi();
    final scope = buildContainer(api);
    addTearDown(scope.dispose);
    await scope.read(managerControllerProvider.future);
    final notifier = scope.read(managerControllerProvider.notifier);

    await notifier.applyFilter(const ManagerFilter(taskType: 'payment'));
    expect(api.lastTaskType, 'payment');

    await notifier.applyFilter(const ManagerFilter().copyWith(clearTaskType: true));
    expect(api.lastTaskType, isNull);
  });

  test('refresh re-fetches with the current filter', () async {
    final api = FakeManagerApi();
    final scope = buildContainer(api);
    addTearDown(scope.dispose);
    await scope.read(managerControllerProvider.future);
    final notifier = scope.read(managerControllerProvider.notifier);
    await notifier.applyFilter(const ManagerFilter(status: TaskStatus.done));

    await notifier.refresh();

    expect(api.lastStatus, 'done');
  });
}
