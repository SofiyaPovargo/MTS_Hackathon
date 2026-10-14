/// Pure board helpers (grouping, sorting, filtering). No Flutter imports — the
/// widgets stay thin and the rules are unit-testable (AGENTS: no business logic
/// in widgets). Today is always passed in so tests are deterministic.
library;

import 'enums.dart';
import 'models.dart';

/// Section of the personal board (plan.md §14): overdue, today, upcoming,
/// without a due date, done and canceled.
enum TaskBucket {
  overdue('Просроченные'),
  today('Сегодня'),
  upcoming('Предстоящие'),
  noDue('Без срока'),
  done('Выполненные'),
  canceled('Отменённые');

  const TaskBucket(this.label);
  final String label;
}

TaskBucket taskBucket(TaskItem task, DateTime today) {
  if (task.status == TaskStatus.canceled) return TaskBucket.canceled;
  if (task.status == TaskStatus.done) return TaskBucket.done;
  if (task.status == TaskStatus.overdue) return TaskBucket.overdue;
  final due = task.dueDate;
  if (due == null) return TaskBucket.noDue;
  final d = DateTime(due.year, due.month, due.day);
  final t = DateTime(today.year, today.month, today.day);
  if (d.isBefore(t)) return TaskBucket.overdue;
  if (d.isAtSameMomentAs(t)) return TaskBucket.today;
  return TaskBucket.upcoming;
}

/// Board order: overdue first, then today and nearest deadlines; done/canceled
/// last. Ties break by priority (high first) and title.
List<TaskItem> sortForBoard(List<TaskItem> tasks, DateTime today) {
  final indexed = tasks.toList();
  indexed.sort((a, b) {
    final bucketA = _order[taskBucket(a, today)]!;
    final bucketB = _order[taskBucket(b, today)]!;
    if (bucketA != bucketB) return bucketA.compareTo(bucketB);
    final dueA = a.dueDate;
    final dueB = b.dueDate;
    if (dueA != null && dueB != null) {
      final cmp = dueA.compareTo(dueB);
      if (cmp != 0) return cmp;
    } else if (dueA == null && dueB != null) {
      return 1;
    } else if (dueA != null) {
      return -1;
    }
    final prio = _priorityRank(b.priority).compareTo(_priorityRank(a.priority));
    if (prio != 0) return prio;
    return a.title.compareTo(b.title);
  });
  return indexed;
}

/// Groups the sorted tasks into non-empty sections, in board order.
Map<TaskBucket, List<TaskItem>> groupForBoard(
  List<TaskItem> tasks,
  DateTime today,
) {
  final result = <TaskBucket, List<TaskItem>>{};
  for (final task in sortForBoard(tasks, today)) {
    result.putIfAbsent(taskBucket(task, today), () => <TaskItem>[]).add(task);
  }
  return result;
}

/// Manager board filters that the server does not apply (plan.md §15): priority.
/// "Type" is not a field on a task in the MVP data model.
List<TaskItem> filterManagerTasks(
  List<TaskItem> tasks, {
  TaskPriority? priority,
}) {
  if (priority == null) return tasks;
  return tasks.where((task) => task.priority == priority).toList();
}

/// Manager board order: overdue first, then nearest deadlines (§15). Ties break
/// by priority and title.
List<TaskItem> sortManagerTasks(List<TaskItem> tasks) {
  final indexed = tasks.toList();
  indexed.sort((a, b) {
    final overdueA = a.status == TaskStatus.overdue ? 0 : 1;
    final overdueB = b.status == TaskStatus.overdue ? 0 : 1;
    if (overdueA != overdueB) return overdueA.compareTo(overdueB);
    final dueA = a.dueDate;
    final dueB = b.dueDate;
    if (dueA != null && dueB != null) {
      final cmp = dueA.compareTo(dueB);
      if (cmp != 0) return cmp;
    } else if (dueA == null && dueB != null) {
      return 1;
    } else if (dueA != null) {
      return -1;
    }
    final prio = _priorityRank(b.priority).compareTo(_priorityRank(a.priority));
    if (prio != 0) return prio;
    return a.title.compareTo(b.title);
  });
  return indexed;
}

const Map<TaskBucket, int> _order = <TaskBucket, int>{
  TaskBucket.overdue: 0,
  TaskBucket.today: 1,
  TaskBucket.upcoming: 2,
  TaskBucket.noDue: 3,
  TaskBucket.done: 4,
  TaskBucket.canceled: 5,
};

int _priorityRank(TaskPriority priority) => switch (priority) {
  TaskPriority.high => 3,
  TaskPriority.medium => 2,
  TaskPriority.low => 1,
};
