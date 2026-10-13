import 'package:sqflite/sqflite.dart';

import '../../domain/models.dart';
import '../../domain/ports.dart';
import 'app_database.dart';

/// Cache of the user's own tasks and agreements (server stays authoritative).
class SqliteLocalBoardStore implements LocalBoardStore {
  SqliteLocalBoardStore(this._db);

  final AppDatabase _db;

  @override
  Future<void> upsertTask(TaskItem task) async {
    final db = await _db.open();
    await db.insert(
      'tasks',
      Map<String, Object?>.from(task.toJson()),
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  @override
  Future<void> removeTask(String id) async {
    final db = await _db.open();
    await db.delete('tasks', where: 'id = ?', whereArgs: <Object?>[id]);
  }

  @override
  Future<List<TaskItem>> allTasks() async {
    final db = await _db.open();
    final rows = await db.query(
      'tasks',
      orderBy: 'due_date IS NULL, due_date ASC, created_at DESC',
    );
    return rows
        .map((row) => TaskItem.fromJson(Map<String, dynamic>.from(row)))
        .toList();
  }

  @override
  Future<void> upsertAgreement(Agreement agreement) async {
    final db = await _db.open();
    await db.insert(
      'agreements',
      Map<String, Object?>.from(agreement.toJson()),
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  @override
  Future<void> removeAgreement(String id) async {
    final db = await _db.open();
    await db.delete('agreements', where: 'id = ?', whereArgs: <Object?>[id]);
  }

  @override
  Future<List<Agreement>> allAgreements() async {
    final db = await _db.open();
    final rows = await db.query(
      'agreements',
      orderBy: 'due_date IS NULL, due_date ASC, created_at DESC',
    );
    return rows
        .map((row) => Agreement.fromJson(Map<String, dynamic>.from(row)))
        .toList();
  }
}