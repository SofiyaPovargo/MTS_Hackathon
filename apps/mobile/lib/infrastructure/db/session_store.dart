import 'dart:convert';

import 'package:sqflite/sqflite.dart';

import '../../domain/models.dart';
import '../../domain/ports.dart';
import 'app_database.dart';

/// Persists the auth session (access/refresh tokens + user) in SQLite so the
/// app can restore the session on start and refresh silently.
class SqliteSessionStore implements SessionStore {
  SqliteSessionStore(this._db);

  static const String _rowKey = 'current';

  final AppDatabase _db;

  @override
  Future<AuthSession?> read() async {
    final db = await _db.open();
    final rows = await db.query(
      'session',
      where: 'key = ?',
      whereArgs: const <Object?>[_rowKey],
      limit: 1,
    );
    if (rows.isEmpty) return null;
    final raw = rows.first['value'] as String?;
    if (raw == null) return null;
    final decoded = jsonDecode(raw);
    if (decoded is! Map<String, dynamic>) return null;
    return AuthSession.fromStored(decoded);
  }

  @override
  Future<void> save(AuthSession session) async {
    final db = await _db.open();
    await db.insert(
      'session',
      <String, Object?>{'key': _rowKey, 'value': jsonEncode(session.toJson())},
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  @override
  Future<void> clear() async {
    final db = await _db.open();
    await db.delete('session', where: 'key = ?', whereArgs: const <Object?>[_rowKey]);
  }
}