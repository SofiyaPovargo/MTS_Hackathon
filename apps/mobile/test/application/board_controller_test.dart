import 'package:agreement_capture/application/providers.dart';
import 'package:agreement_capture/domain/models.dart';
import 'package:agreement_capture/domain/ports.dart';
import 'package:agreement_capture/domain/sync_models.dart';
import 'package:agreement_capture/infrastructure/api/api_exception.dart';
import 'package:agreement_capture/infrastructure/sync/sync_engine.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fakes.dart';

ProviderContainer buildContainer({
  required InMemoryBoardStore local,
  required FakeSyncApi api,
  BoardApi? boardApi,
}) {
  final outbox = InMemoryOutboxStore();
  final state = InMemorySyncStateStore();
  final engine = SyncEngine(
    syncApi: api,
    board: local,
    outbox: outbox,
    state: state,
    baseBackoff: const Duration(milliseconds: 1),
  );
  return ProviderContainer(
    overrides: <Override>[
      localBoardStoreProvider.overrideWithValue(local),
      syncEngineProvider.overrideWithValue(engine),
      if (boardApi != null) boardApiProvider.overrideWithValue(boardApi),
    ],
  );
}

void main() {
  test('build syncs and returns the local cache', () async {
    final local = InMemoryBoardStore()..tasks['t1'] = testTask(id: 't1');
    final api = FakeSyncApi()
      ..nextPull = SyncPullResult(
        changes: <SyncChange>[
          SyncChange(
            entityType: 'task',
            id: 't2',
            version: 1,
            updatedAt: DateTime.utc(2026, 10, 2),
            data: <String, dynamic>{
              'id': 't2',
              'title': 'Из синхронизации',
              'assignee_user_id': 'u1',
              'priority': 'high',
              'status': 'new',
            },
          ),
        ],
        syncToken: 'tok-1',
        hasMore: false,
      );
    final scope = buildContainer(local: local, api: api);
    addTearDown(scope.dispose);

    final tasks = await scope.read(boardControllerProvider.future);

    expect(tasks, hasLength(2));
    expect(local.tasks.containsKey('t2'), isTrue);
  });

  test('falls back to the cache when the sync fails', () async {
    final local = InMemoryBoardStore()..tasks['t1'] = testTask(id: 't1');
    final api = FakeSyncApi()
      ..pullError = const ApiException(ApiErrorKind.network, 'offline')
      ..pullFailures = 10;
    final scope = buildContainer(local: local, api: api);
    addTearDown(scope.dispose);

    final tasks = await scope.read(boardControllerProvider.future);
    expect(tasks.single.id, 't1');
  });

  test('refresh reloads tasks from the local cache', () async {
    final local = InMemoryBoardStore();
    final scope = buildContainer(local: local, api: FakeSyncApi());
    addTearDown(scope.dispose);
    await scope.read(boardControllerProvider.future);

    local.tasks['t5'] = testTask(id: 't5', title: 'Новая задача');
    await scope.read(boardControllerProvider.notifier).refresh();

    expect(scope.read(boardControllerProvider).value?.single.id, 't5');
  });

  test('loadFromServer caches the authoritative list', () async {
    final local = InMemoryBoardStore();
    final boardApi = FakeBoardApi(tasks: <TaskItem>[testTask(id: 'srv', title: 'С сервера')]);
    final scope = buildContainer(local: local, api: FakeSyncApi(), boardApi: boardApi);
    addTearDown(scope.dispose);
    await scope.read(boardControllerProvider.future);

    await scope.read(boardControllerProvider.notifier).loadFromServer();

    expect(local.tasks.containsKey('srv'), isTrue);
    expect(scope.read(boardControllerProvider).value?.single.title, 'С сервера');
  });
}
