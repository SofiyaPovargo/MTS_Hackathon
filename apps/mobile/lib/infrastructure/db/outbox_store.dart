import 'dart:convert';

import 'package:sqflite/sqflite.dart';
import 'package:uuid/uuid.dart';

import '../../domain/enums.dart';
import '../../domain/ports.dart';
import '../../domain/sync_models.dart';
import 'app_database.dart';

/// Offline change queue. Every operation carries an idempotency key (unique in
/// the table) so retries never duplicate work server-side.
class SqliteOutboxStore implements OutboxStore {
  SqliteOutboxStore(this._db, {Uuid uuid = const Uuid()}) : _uuid = uuid;

  final AppDatabase _db;
  final Uuid _uuid;

  @override
  Future<void> enqueue(SyncOperation operation) async {
    final db = await _db.open();
    await db.insert(
      'outbox',
      <String, Object?>{
        'id': _uuid.v4(),
        'entity_type': operation.entityType.wire,
        'entity_id': operation.entityId,
        'operation': operation.operation,
        'idempotency_key': operation.idempotencyKey,
        'version': operation.version,
        'payload': jsonEncode(operation.payload),
        'created_at': DateTime.now().millisecondsSinceEpoch,
      },
      // Deduplicate by idempotency key: re-enqueueing the same op is a no-op.
      conflictAlgorithm: ConflictAlgorithm.ignore,
    );
  }

  @override
  Future<List<SyncOperation>> pending() async {
    final db = await _db.open();
    final rows = await db.query('outbox', orderBy: 'created_at ASC');
    return rows.map(_toOperation).toList();
  }

  @override
  Future<void> removeByEntity(String entityType, String entityId) async {
    final db = await _db.open();
    await db.delete(
      'outbox',
      where: 'entity_type = ? AND entity_id = ?',
      whereArgs: <Object?>[entityType, entityId],
    );
  }

  SyncOperation _toOperation(Map<String, Object?> row) {
    final entityType = SyncEntityType.tryFromWire(row['entity_type'] as String);
    if (entityType == null) {
      throw StateError('Unknown outbox entity type: ${row['entity_type']}');
    }
    final decoded = jsonDecode(row['payload'] as String);
    return SyncOperation(
      entityType: entityType,
      entityId: row['entity_id'] as String,
      operation: row['operation'] as String,
      idempotencyKey: row['idempotency_key'] as String,
      version: (row['version'] as num?)?.toInt(),
      payload: decoded is Map<String, dynamic> ? decoded : const <String, dynamic>{},
    );
  }
}