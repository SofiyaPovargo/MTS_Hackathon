import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../domain/models.dart';
import '../domain/ports.dart';
import '../infrastructure/api/api_exception.dart';
import 'providers.dart';

/// The user's personal board: their own tasks, read from the local cache and
/// refreshed from the server via the sync cycle.
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
}
