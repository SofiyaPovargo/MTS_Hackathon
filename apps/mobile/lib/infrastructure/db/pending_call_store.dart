import 'package:sqflite/sqflite.dart';

import '../../domain/offline_call.dart';
import '../../domain/ports.dart';
import 'app_database.dart';

/// SQLite-backed [PendingCallStore] (`pending_calls`).
///
/// Holds the calls the client created while offline until the server accepts
/// them (plan.md §13). Keyed by the client-generated `call_id`, so saving again
/// updates the same registration instead of duplicating it.
class SqlitePendingCallStore implements PendingCallStore {
  SqlitePendingCallStore(this._db);

  final AppDatabase _db;

  @override
  Future<void> save(PendingCall call) async {
    final db = await _db.open();
    await db.insert(
      'pending_calls',
      call.toRow(),
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  @override
  Future<List<PendingCall>> pending() async {
    final db = await _db.open();
    final rows = await db.query('pending_calls', orderBy: 'started_at ASC');
    return rows.map(PendingCall.fromRow).toList();
  }

  @override
  Future<void> remove(String callId) async {
    final db = await _db.open();
    await db.delete(
      'pending_calls',
      where: 'call_id = ?',
      whereArgs: <Object?>[callId],
    );
  }
}
