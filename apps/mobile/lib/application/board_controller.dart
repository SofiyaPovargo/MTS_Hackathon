import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../domain/enums.dart';
import '../domain/models.dart';
import '../domain/ports.dart';
import '../domain/sync_models.dart';
import '../infrastructure/api/api_exception.dart';
import 'providers.dart';

/// The user's personal board: their own tasks, read from the local cache and
/// refreshed from the server via the sync cycle. Task edits are applied
/// optimistically to the cache and queued in the outbox, which the sync engine
/// pushes (plan.md §9: UI → Local DB → Outbox → Sync Engine → Server).
class BoardController extends AsyncNotifier<List<TaskItem>> {
  LocalBoardStore get _local => ref.read(localBoardStoreProvider);

  @override
  Future<List<TaskItem>> build() async {
    try {
      await ref.read(syncEngineProvider).run();
    } on ApiException {
      // Offline-first: fall back to the local cache on a failed sync.
    }
    return _local.allTasks();
  }

  /// Runs a sync and reloads the cache. Errors propagate so pull-to-refresh can
  /// surface them without dropping the already-loaded list.
  Future<void> refresh() async {
    await ref.read(syncEngineProvider).run();
    state = AsyncValue<List<TaskItem>>.data(await _local.allTasks());
  }

  /// Hard refresh: fetches the authoritative task list over `/me/tasks`.
  Future<void> loadFromServer() async {
    final tasks = await ref.read(boardApiProvider).fetchMyTasks();
    for (final task in tasks) {
      await _local.upsertTask(task);
    }
    state = AsyncValue<List<TaskItem>>.data(await _local.allTasks());
  }

  // ---- task actions (plan.md §14) -------------------------------------------

  /// Взять в работу: `new`/`overdue` → `in_progress`.
  Future<String?> startTask(String id) =>
      _patch(id, const TaskPatch(status: TaskStatus.inProgress));

  /// Отметить выполненной.
  Future<String?> completeTask(String id) =>
      _patch(id, const TaskPatch(status: TaskStatus.done));

  /// Отменить задачу.
  Future<String?> cancelTask(String id) =>
      _patch(id, const TaskPatch(status: TaskStatus.canceled));

  Future<String?> rescheduleTask(String id, DateTime dueDate) =>
      _patch(id, TaskPatch(dueDate: dueDate));

  Future<String?> setPriority(String id, TaskPriority priority) =>
      _patch(id, TaskPatch(priority: priority));

  /// Applies a patch optimistically to the cache, queues it in the outbox and
  /// pushes it via the sync cycle. Returns an error message, or `null`.
  Future<String?> _patch(String id, TaskPatch patch) async {
    final tasks = await _local.allTasks();
    final current = _find(tasks, id);
    if (current == null) return 'Задача не найдена';

    final optimistic = _apply(current, patch);
    await _local.upsertTask(optimistic);

    // Coalesce pending edits for this task so only the latest is pushed.
    final outbox = ref.read(outboxStoreProvider);
    await outbox.removeByEntity(SyncEntityType.task.wire, id);
    await outbox.enqueue(
      SyncOperation(
        entityType: SyncEntityType.task,
        entityId: id,
        operation: 'update',
        idempotencyKey: 'task-$id-${DateTime.now().microsecondsSinceEpoch}',
        version: current.version,
        payload: patch.toJson(),
      ),
    );

    state = AsyncValue<List<TaskItem>>.data(await _local.allTasks());
    try {
      await ref.read(syncEngineProvider).run();
    } on ApiException {
      // Offline: the change stays in the outbox for the next sync cycle.
    }
    state = AsyncValue<List<TaskItem>>.data(await _local.allTasks());
    return null;
  }

  TaskItem _apply(TaskItem task, TaskPatch patch) {
    final status = patch.status;
    return task.copyWith(
      title: patch.title,
      description: patch.description,
      dueDate: patch.dueDate,
      dueTime: patch.dueTime,
      priority: patch.priority,
      status: status,
      completedAt: status == TaskStatus.done
          ? DateTime.now()
          : task.completedAt,
      updatedAt: DateTime.now(),
    );
  }

  TaskItem? _find(List<TaskItem> tasks, String id) {
    for (final task in tasks) {
      if (task.id == id) return task;
    }
    return null;
  }
}
