import 'dart:io';

import 'package:agreement_capture/domain/audio.dart';
import 'package:agreement_capture/domain/consent.dart';
import 'package:agreement_capture/domain/enums.dart';
import 'package:agreement_capture/domain/sync_models.dart';
import 'package:agreement_capture/infrastructure/audio/file_audio_recording_store.dart';
import 'package:agreement_capture/infrastructure/db/app_database.dart';
import 'package:agreement_capture/infrastructure/db/consent_store.dart';
import 'package:agreement_capture/infrastructure/db/local_board_store.dart';
import 'package:agreement_capture/infrastructure/db/outbox_store.dart';
import 'package:agreement_capture/infrastructure/db/pending_call_store.dart';
import 'package:agreement_capture/infrastructure/db/session_store.dart';
import 'package:agreement_capture/infrastructure/db/sync_state_store.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:path/path.dart' as p;
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

  group('SqlitePendingCallStore', () {
    test('stores, replaces by call id and removes a queued call', () async {
      final store = SqlitePendingCallStore(database);
      expect(await store.pending(), isEmpty);

      await store.save(
        testPendingCall(
          callId: 'call-b',
          answeredAt: DateTime.utc(2026, 10, 14, 9, 1),
          endedAt: DateTime.utc(2026, 10, 14, 9, 5),
        ),
      );
      await store.save(
        testPendingCall(
          callId: 'call-a',
          calleePhone: '+79000000009',
        ),
      );

      final pending = await store.pending();
      expect(pending, hasLength(2));
      final a = pending.singleWhere((call) => call.callId == 'call-a');
      expect(a.calleePhone, '+79000000009');
      expect(a.answeredAt, isNull);
      final b = pending.singleWhere((call) => call.callId == 'call-b');
      expect(b.answeredAt, DateTime.utc(2026, 10, 14, 9, 1));
      expect(b.endedAt, DateTime.utc(2026, 10, 14, 9, 5));

      await store.remove('call-a');
      expect(
        (await store.pending()).map((call) => call.callId),
        <String>['call-b'],
      );
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

  group('SqliteConsentStore', () {
    test('starts undecided and round-trips a decision', () async {
      final store = SqliteConsentStore(database);
      expect(await store.read(), AppConsent.undecided);

      await store.save(
        const AppConsent(status: ConsentStatus.granted, synced: true),
      );
      final restored = await store.read();
      expect(restored.status, ConsentStatus.granted);
      expect(restored.synced, isTrue);
      expect(restored.recordingEnabled, isTrue);
    });

    test('schema v1 databases are upgraded with app_settings', () async {
      final dir = await Directory.systemTemp.createTemp('consent_migration');
      addTearDown(() => dir.delete(recursive: true));
      final path = p.join(dir.path, 'legacy.db');

      // A v1 database from before Stage 5 (no `app_settings` table yet).
      final legacy = await databaseFactoryFfi.openDatabase(
        path,
        options: OpenDatabaseOptions(
          version: 1,
          onCreate: (db, version) async {
            await db.execute(
              'CREATE TABLE session(key TEXT PRIMARY KEY, value TEXT NOT NULL)',
            );
          },
        ),
      );
      await legacy.insert('session', <String, Object?>{
        'key': 'current',
        'value': '{"x": 1}',
      });
      await legacy.close();

      final migrated = AppDatabase(factory: databaseFactoryFfi, path: path);
      addTearDown(migrated.close);
      final store = SqliteConsentStore(migrated);
      expect(await store.read(), AppConsent.undecided);

      await store.save(const AppConsent(status: ConsentStatus.denied));
      expect((await store.read()).status, ConsentStatus.denied);

      // The legacy table survived the upgrade.
      final db = await migrated.open();
      expect(
        await db.query('session', where: 'key = ?', whereArgs: const ['current']),
        hasLength(1),
      );
    });
  });

  group('FileAudioRecordingStore', () {
    late Directory audioDir;

    setUp(() async {
      audioDir = await Directory.systemTemp.createTemp('audio_store');
    });

    tearDown(() => audioDir.delete(recursive: true));

    FileAudioRecordingStore build() => FileAudioRecordingStore(
          database,
          resolveDirectory: () async => audioDir.path,
        );

    test('buffers bytes, tracks offsets and lists pending uploads', () async {
      final store = build();
      await store.begin('c1', keepFor: const Duration(days: 7));
      await store.append('c1', List<int>.filled(4, 1));
      await store.append('c1', List<int>.filled(6, 2));

      final recording = await store.get('c1');
      expect(recording!.bytesTotal, 10);
      expect(recording.needsUpload, isTrue);
      expect(recording.keepUntil, isNotNull);
      expect(await store.readFrom('c1', 4), hasLength(6));

      await store.setStatus('c1', RecordingUploadStatus.pending);
      expect(await store.pending(), hasLength(1));

      await store.markUploaded('c1', uploadedBytes: 10, complete: true);
      final done = await store.get('c1');
      expect(done!.status, RecordingUploadStatus.uploaded);
      expect(done.isUploaded, isTrue);
      expect(await store.pending(), isEmpty);
    });

    test('deletes the file and row', () async {
      final store = build();
      await store.begin('c1');
      await store.append('c1', List<int>.filled(2, 0));

      await store.delete('c1');
      expect(await store.get('c1'), isNull);
      expect(File('${audioDir.path}/c1.audio').existsSync(), isFalse);
    });

    test('drops the oldest uploaded recordings above the cap', () async {
      final store = build();
      for (final id in <String>['a', 'b', 'c']) {
        await store.begin(id);
        await store.append(id, List<int>.filled(2, 0));
        await store.markUploaded(id, uploadedBytes: 2, complete: true);
        await Future<void>.delayed(const Duration(milliseconds: 2));
      }

      await store.enforceRetention(maxRecordings: 2);

      final db = await database.open();
      final rows = await db.query('audio_recordings');
      expect(rows, hasLength(2));
    });
  });
}
