import 'package:agreement_capture/domain/board.dart';
import 'package:agreement_capture/domain/enums.dart';
import 'package:agreement_capture/domain/models.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fakes.dart';

void main() {
  final today = DateTime(2026, 10, 14);

  TaskItem task({
    required String id,
    TaskStatus status = TaskStatus.newTask,
    TaskPriority priority = TaskPriority.medium,
    DateTime? dueDate,
    String title = 'Задача',
  }) =>
      testTask(id: id, status: status, priority: priority, dueDate: dueDate, title: title);

  group('taskBucket', () {
    test('classifies a task into a section', () {
      expect(taskBucket(task(id: 'a', status: TaskStatus.overdue), today), TaskBucket.overdue);
      expect(taskBucket(task(id: 'b', dueDate: today), today), TaskBucket.today);
      expect(
        taskBucket(task(id: 'c', dueDate: DateTime(2026, 10, 20)), today),
        TaskBucket.upcoming,
      );
      expect(taskBucket(task(id: 'd'), today), TaskBucket.noDue);
      expect(taskBucket(task(id: 'e', status: TaskStatus.done), today), TaskBucket.done);
      expect(taskBucket(task(id: 'f', status: TaskStatus.canceled), today), TaskBucket.canceled);
    });

    test('a past due date counts as overdue even without the status', () {
      expect(
        taskBucket(task(id: 'g', dueDate: DateTime(2026, 10, 10)), today),
        TaskBucket.overdue,
      );
    });
  });

  test('groupForBoard sections and orders: overdue first, done last', () {
    final tasks = <TaskItem>[
      task(id: 'done', status: TaskStatus.done, dueDate: DateTime(2026, 10, 12)),
      task(id: 'upcoming', dueDate: DateTime(2026, 10, 20)),
      task(id: 'overdue', status: TaskStatus.overdue, dueDate: DateTime(2026, 10, 5)),
      task(id: 'today', dueDate: today),
    ];
    final groups = groupForBoard(tasks, today);

    expect(groups.keys.toList(), <TaskBucket>[
      TaskBucket.overdue,
      TaskBucket.today,
      TaskBucket.upcoming,
      TaskBucket.done,
    ]);
    expect(groups[TaskBucket.overdue]!.single.id, 'overdue');
  });

  test('sortForBoard orders by due date and priority within a section', () {
    final tasks = <TaskItem>[
      task(id: 'later', dueDate: DateTime(2026, 10, 20)),
      task(id: 'sooner', dueDate: DateTime(2026, 10, 16)),
      task(
        id: 'sameDayHigh',
        dueDate: DateTime(2026, 10, 16),
        priority: TaskPriority.high,
      ),
    ];
    final sorted = sortForBoard(tasks, today).map((t) => t.id).toList();
    expect(sorted.indexOf('sooner'), lessThan(sorted.indexOf('later')));
    // Same due date: high priority first.
    expect(sorted.indexOf('sameDayHigh'), lessThan(sorted.indexOf('sooner')));
  });

  test('sortManagerTasks puts overdue first then nearest deadlines', () {
    final tasks = <TaskItem>[
      task(id: 'later', dueDate: DateTime(2026, 10, 25)),
      task(id: 'overdue', status: TaskStatus.overdue, dueDate: DateTime(2026, 10, 5)),
      task(id: 'soon', dueDate: DateTime(2026, 10, 16)),
    ];
    final sorted = sortManagerTasks(tasks).map((t) => t.id).toList();
    expect(sorted, <String>['overdue', 'soon', 'later']);
  });

  test('filterManagerTasks narrows by priority', () {
    final tasks = <TaskItem>[
      task(id: 'high', priority: TaskPriority.high),
      task(id: 'low', priority: TaskPriority.low),
    ];
    expect(
      filterManagerTasks(tasks, priority: TaskPriority.high).map((t) => t.id),
      <String>['high'],
    );
    expect(filterManagerTasks(tasks), hasLength(2));
  });
}
