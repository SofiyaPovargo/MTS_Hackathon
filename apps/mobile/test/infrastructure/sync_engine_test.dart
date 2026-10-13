import 'package:agreement_capture/domain/enums.dart';
import 'package:agreement_capture/domain/sync_models.dart';
import 'package:agreement_capture/infrastructure/api/api_exception.dart';
import 'package:agreement_capture/infrastructure/db/app_database.dart';
import 'package:agreement_capture/infrastructure/db/local_board_store.dart';
import 'package:agreement_capture/infrastructure/db/outbox_store.dart';
import 'package:agreement_capture/infrastructure/db/sync_state_store.dart';
import 'package:agreement_capture/infrastructure/sync/sync_engine.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../support/fakes.dart';

Map<String, dynamic> taskDelta({String id = 't1', String status = 'new'}) =>
    <String, dynamic>{
      'id': id,
      'title': 'Позвонить клиенту',
      'assignee_user_id': 'u1',
      'priority': 'medium',
      'status': status,
    };

void main() {
  late AppDatabase database;
  late SqliteLocalBoardStore board;
  late SqliteOutboxStore outbox;
  late SqliteSyncStateStore state;
  late FakeSyncApi api;
  late SyncEngine engine;

  setUpAll(sqfliteFfiInit);

  setUp(() {
    database = AppDatabase(factory: databaseFactoryFfi, path: inMemoryDatabasePath);
    board = SqliteLocalBoardStore(database);
    outbox = SqliteOutboxStore(database);
    state = SqliteSyncStateStore(database);
    api = FakeSyncApi();
    engine = SyncEngine(
      syncApi: api,
      board: board,
      outbox: outbox,
      state: state,
      baseBackoff: const Duration(milliseconds: 1),
    );
  });

  tearDown(() => database.close());

  test('pull applies task changes and advances the token', () async {
    api.nextPull = SyncPullResult(
      changes: <SyncChange>[
        SyncChange(
          entityType: 'task',
          id: 't1',
          version: 2,
          updatedAt: DateTime.utc(2026, 10, 2),
          data: taskDelta(),
        ),
      ],
      syncToken: 'tok-1',
      hasMore: false,
    );

    final result = await engine.run();

    expect(result.pulled, 1);
    expect(api.requestedSince.single, isNull);
    final tasks = await board.allTasks();
    expect(tasks.single.title, 'Позвонить клиенту');
    expect(await state.readSyncToken(), 'tok-1');
  });

  test('replayed change with an unchanged version is skipped', () async {
    api.nextPull = SyncPullResult(
      changes: <SyncChange>[
        SyncChange(
          entityType: 'task',
          id: 't1',
          version: 2,
          updatedAt: DateTime.utc(2026, 10, 2),
          data: taskDelta(),
        ),
      ],
      syncToken: 'tok-1',
      hasMore: false,
    );

    await engine.run();
    final second = await engine.run();

    expect(second.pulled, 0);
    expect(api.requestedSince, <String?>[null, 'tok-1']);
  });

  test('accepted push removes the outbox op and records the version', () async {
    await outbox.enqueue(
      const SyncOperation(
        entityType: SyncEntityType.task,
        entityId: 't1',
        operation: 'update',
        idempotencyKey: 'idem-1',
        version: 2,
        payload: <String, dynamic>{'status': 'done'},
      ),
    );
    api.nextPush = const SyncPushResult(
      results: <SyncOpResult>[
        SyncOpResult(entityType: 'task', entityId: 't1', status: 'accepted', version: 3),
      ],
    );

    final result = await engine.run();

    expect(result.pushed, 1);
    expect(result.conflicts, 0);
    expect(await outbox.pending(), isEmpty);
    expect(await state.readRecordVersion('task', 't1'), 3);
  });

  test('conflict drops the op and forces a full re-pull', () async {
    await state.writeSyncToken('tok-prev');
    await outbox.enqueue(
      const SyncOperation(
        entityType: SyncEntityType.task,
        entityId: 't1',
        operation: 'update',
        idempotencyKey: 'idem-1',
        version: 2,
      ),
    );
    api.nextPush = const SyncPushResult(
      results: <SyncOpResult>[
        SyncOpResult(entityType: 'task', entityId: 't1', status: 'conflict', serverVersion: 5),
      ],
    );

    final result = await engine.run();

    expect(result.conflicts, 1);
    expect(await outbox.pending(), isEmpty);
    expect(await state.readSyncToken(), isNull);
  });

  test('retries retryable network failures with backoff', () async {
    api.pullError = const ApiException(ApiErrorKind.network, 'offline');
    api.pullFailures = 2;

    final result = await engine.run();

    expect(api.pullCalls, 3);
    expect(result.pulled, 0);
  });

  test('does not retry authorization errors', () async {
    api.pullError = const ApiException(ApiErrorKind.unauthorized, 'no token');
    api.pullFailures = 5;

    await expectLater(engine.run(), throwsA(isA<ApiException>()));
    expect(api.pullCalls, 1);
  });
}
