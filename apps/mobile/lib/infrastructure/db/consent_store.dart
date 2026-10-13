import 'dart:convert';

import 'package:sqflite/sqflite.dart';

import '../../domain/consent.dart';
import '../../domain/ports.dart';
import 'app_database.dart';

/// Persists the app user's consent decision locally (`app_settings`). The
/// server is the source of truth; this is the offline cache read on start.
class SqliteConsentStore implements ConsentStore {
  SqliteConsentStore(this._db);

  static const String _rowKey = 'app_consent';

  final AppDatabase _db;

  @override
  Future<AppConsent> read() async {
    final db = await _db.open();
    final rows = await db.query(
      'app_settings',
      where: 'key = ?',
      whereArgs: const <Object?>[_rowKey],
      limit: 1,
    );
    if (rows.isEmpty) return AppConsent.undecided;
    final raw = rows.first['value'] as String?;
    if (raw == null) return AppConsent.undecided;
    final decoded = jsonDecode(raw);
    if (decoded is! Map<String, dynamic>) return AppConsent.undecided;
    return AppConsent.fromJson(decoded);
  }

  @override
  Future<void> save(AppConsent consent) async {
    final db = await _db.open();
    await db.insert(
      'app_settings',
      <String, Object?>{'key': _rowKey, 'value': jsonEncode(consent.toJson())},
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }
}