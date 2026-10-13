import 'package:sqflite/sqflite.dart';

import '../../domain/ports.dart';
import 'app_database.dart';

/// Key/value store for the sync token and per-record versions, used to apply
/// deltas idempotently (a replayed row with an older version is skipped).
class SqliteSyncStateStore implements SyncStateStore {
  SqliteSyncStateStore(this._db);

  static const String _tokenKey = 'sync_token';

  final AppDatabase _db;

  @override
  Future<String?> readSyncToken() async {
    final raw = await _read(_tokenKey);
    // An empty token means "force a full re-pull".
    return (raw == null || raw.isEmpty) ? null : raw;
  }

  @override
  Future<void> writeSyncToken(String token) => _write(_tokenKey, token);

  @override
  Future<int> readRecordVersion(String entityType, String id) async {
    final raw = await _read(_versionKey(entityType, id));
    return int.tryParse(raw ?? '') ?? 0;
  }

  @override
  Future<void> writeRecordVersion(String entityType, String id, int version) =>
      _write(_versionKey(entityType, id), version.toString());

  String _versionKey(String entityType, String id) => 'version:$entityType:$id';

  Future<String?> _read(String key) async {
    final db = await _db.open();
    final rows = await db.query(
      'sync_state',
      columns: const <String>['value'],
      where: 'key = ?',
      whereArgs: <Object?>[key],
      limit: 1,
    );
    if (rows.isEmpty) return null;
    return rows.first['value'] as String?;
  }

  Future<void> _write(String key, String value) async {
    final db = await _db.open();
    await db.insert(
      'sync_state',
      <String, Object?>{'key': key, 'value': value},
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }
}