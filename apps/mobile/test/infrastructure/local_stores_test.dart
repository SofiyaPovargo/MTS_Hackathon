import 'package:agreement_capture/domain/enums.dart';
import 'package:agreement_capture/domain/sync_models.dart';
import 'package:agreement_capture/infrastructure/db/app_database.dart';
import 'package:agreement_capture/infrastructure/db/local_board_store.dart';
import 'package:agreement_capture/infrastructure/db/outbox_store.dart';
import 'package:agreement_capture/infrastructure/db/session_store.dart';
import 'package:agreement_capture/infrastructure/db/sync_state_store.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../support/fakes.dart';

void main() {
  late AppDatabase database;

  setUpAll(sqfliteFfiInit);

  setUp(() {
    database = AppDatabase(factory: databaseFactoryFfi, path: inMemoryDatabasePath);
  });

  tearDown(() => database.close());

  group('SqliteSessionStore', () {
    test('saves, reads and clears the session', () async {
      final store = SqliteSessionStore(database);
      expect(await store.read(), isNull);

      await store.save(testSession(accessToken: 'a', refreshToken: 'r'));
      final restored = await store.read();
      expect(restored?.accessToken, 'a');
      expect(restored?.refreshToken, 'r');
      expect(restored?.user.phone, '+79000000002');

      await store.clear();
      expect(await store.read(), isNull);
    });
  });

  group('SqliteOutboxStore', () {
    test('deduplicates by idempotency key and removes by entity', () async {
      final store = SqliteOutboxStore(database);
      const op = SyncOperation(
        entityType: SyncEntityType.task,
        entityId: 't1',
        operation: 'update',
        idempotencyKey: 'idem-1',
        version: 2,
        payload: <String, dynamic>{'status': 'done'},
      );
      await store.enqueue(op);
      await store.enqueue(op); // duplicate key → ignored

      final pending = await store.pending();
      expect(pending, hasLength(1));
      expect(pending.single.payload['status'], 'done');

      await store.removeByEntity('task', 't1');
      expect(await store.pending(), isEmpty);
    });

    test('keeps operations for other entities', () async {
      final store = SqliteOutboxStore(database);
      await store.enqueue(
        const SyncOperation(
          entityType: SyncEntityType.task,
          entityId: 't1',
          operation: 'update',
          idempotencyKey: 'idem-1',
        ),
      );
      await store.enqueue(
        const SyncOperation(
          entityType: SyncEntityType.agreement,
          entityId: 'a1',
          operation: 'update',
          idempotencyKey: 'idem-2',
        ),
      );
      await store.removeByEntity('task', 't1');
      final pending = await store.pending();
      expect(pending, hasLength(1));
      expect(pending.single.entityId, 'a1');
    });
  });

  group('SqliteSyncStateStore', () {
    test('stores the token and treats an empty token as null', () async {
      final store = SqliteSyncStateStore(database);
      expect(await store.readSyncToken(), isNull);

      await store.writeSyncToken('tok-1');
      expect(await store.readSyncToken(), 'tok-1');

      await store.writeSyncToken('');
      expect(await store.readSyncToken(), isNull);
    });

    test('stores per-record versions', () async {
      final store = SqliteSyncStateStore(database);
      expect(await store.readRecordVersion('task', 't1'), 0);

      await store.writeRecordVersion('task', 't1', 5);
      expect(await store.readRecordVersion('task', 't1'), 5);
      expect(await store.readRecordVersion('task', 'other'), 0);
    });
  });

  group('SqliteLocalBoardStore', () {
    test('upserts tasks and orders them with due dates first', () async {
      final store = SqliteLocalBoardStore(database);
      await store.upsertTask(testTask(id: 't2', title: 'Без срока'));
      await store.upsertTask(
        testTask(id: 't1', title: 'Со сроком', dueDate: DateTime(2026, 10, 15)),
      );
      await store.upsertTask(
        testTask(id: 't1', title: 'Со сроком (v2)', dueDate: DateTime(2026, 10, 15)),
      );

      final tasks = await store.allTasks();
      expect(tasks, hasLength(2));
      expect(tasks.first.id, 't1');
      expect(tasks.first.title, 'Со сроком (v2)');
    });

    test('stores and removes agreements', () async {
      final store = SqliteLocalBoardStore(database);
      await store.upsertAgreement(testAgreement(id: 'a1'));
      expect(await store.allAgreements(), hasLength(1));

      await store.removeAgreement('a1');
      expect(await store.allAgreements(), isEmpty);
    });
  });
}
