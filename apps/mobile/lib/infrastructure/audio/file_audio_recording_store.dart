import 'dart:io';

import 'package:path/path.dart' as p;
import 'package:sqflite/sqflite.dart';

import '../../domain/audio.dart';
import '../../domain/ports.dart';
import '../db/app_database.dart';

/// File-backed [AudioRecordingStore].
///
/// Audio bytes live in one file per call under the app's private directory
/// (never a shared/external one — AGENTS.md); metadata and upload state live in
/// the `audio_recordings` table. The recording is a bounded cache of the user's
/// own recent calls, not a second system of record (plan.md §8).
class FileAudioRecordingStore implements AudioRecordingStore {
  FileAudioRecordingStore(this._database, {required this.resolveDirectory});

  static const String _table = 'audio_recordings';

  final AppDatabase _database;

  /// Returns the directory that holds the audio files (created on demand).
  final Future<String> Function() resolveDirectory;

  Future<File> _file(String callId) async =>
      File(p.join(await resolveDirectory(), '$callId.audio'));

  @override
  Future<CallRecording> begin(
    String callId, {
    String contentType = 'audio/wav',
    Duration? keepFor,
  }) async {
    final db = await _database.open();
    final now = DateTime.now().toUtc();
    final file = await _file(callId);
    if (await file.exists()) await file.delete();
    await file.create(recursive: true);
    final row = <String, Object?>{
      'call_id': callId,
      'path': file.path,
      'content_type': contentType,
      'bytes_total': 0,
      'uploaded_bytes': 0,
      'status': RecordingUploadStatus.recording.name,
      'created_at': now.toIso8601String(),
      'uploaded_at': null,
      'keep_until': keepFor == null ? null : now.add(keepFor).toIso8601String(),
    };
    await db.insert(_table, row, conflictAlgorithm: ConflictAlgorithm.replace);
    return _fromRow(row);
  }

  @override
  Future<CallRecording> append(String callId, List<int> bytes) async {
    if (bytes.isEmpty) {
      return (await get(callId)) ?? (await begin(callId));
    }
    final db = await _database.open();
    final file = await _file(callId);
    await file.writeAsBytes(bytes, mode: FileMode.append, flush: true);
    final total = await file.length();
    await db.update(
      _table,
      <String, Object?>{'bytes_total': total},
      where: 'call_id = ?',
      whereArgs: <Object?>[callId],
    );
    final row = await _row(db, callId);
    return _fromRow(row!);
  }

  @override
  Future<CallRecording?> get(String callId) async {
    final db = await _database.open();
    final row = await _row(db, callId);
    return row == null ? null : _fromRow(row);
  }

  @override
  Future<List<int>> readFrom(String callId, int offset) async {
    final file = await _file(callId);
    if (!await file.exists()) return const <int>[];
    final bytes = await file.readAsBytes();
    if (offset >= bytes.length) return const <int>[];
    return bytes.sublist(offset);
  }

  @override
  Future<void> markUploaded(
    String callId, {
    required int uploadedBytes,
    required bool complete,
  }) async {
    final db = await _database.open();
    await db.update(
      _table,
      <String, Object?>{
        'uploaded_bytes': uploadedBytes,
        if (complete) 'status': RecordingUploadStatus.uploaded.name,
        if (complete) 'uploaded_at': DateTime.now().toUtc().toIso8601String(),
      },
      where: 'call_id = ?',
      whereArgs: <Object?>[callId],
    );
  }

  @override
  Future<void> setStatus(String callId, RecordingUploadStatus status) async {
    final db = await _database.open();
    await db.update(
      _table,
      <String, Object?>{'status': status.name},
      where: 'call_id = ?',
      whereArgs: <Object?>[callId],
    );
  }

  @override
  Future<List<CallRecording>> pending() async {
    final db = await _database.open();
    final rows = await db.query(
      _table,
      where: 'status = ?',
      whereArgs: <Object?>[RecordingUploadStatus.pending.name],
      orderBy: 'created_at ASC',
    );
    return rows.map(_fromRow).toList();
  }

  @override
  Future<void> delete(String callId) async {
    final db = await _database.open();
    await db.delete(_table, where: 'call_id = ?', whereArgs: <Object?>[callId]);
    final file = await _file(callId);
    if (await file.exists()) await file.delete();
  }

  @override
  Future<void> enforceRetention({int maxRecordings = 20}) async {
    final db = await _database.open();
    // Expired retention first.
    final now = DateTime.now().toUtc().toIso8601String();
    final expired = await db.query(
      _table,
      columns: <String>['call_id'],
      where: 'keep_until IS NOT NULL AND keep_until < ?',
      whereArgs: <Object?>[now],
    );
    for (final row in expired) {
      await delete(row['call_id']! as String);
    }
    // Then the oldest uploaded recordings above the cap.
    final uploaded = await db.query(
      _table,
      columns: <String>['call_id'],
      where: 'status = ?',
      whereArgs: <Object?>[RecordingUploadStatus.uploaded.name],
      orderBy: 'created_at DESC',
    );
    for (final row in uploaded.skip(maxRecordings)) {
      await delete(row['call_id']! as String);
    }
  }

  Future<Map<String, Object?>?> _row(Database db, String callId) async {
    final rows = await db.query(
      _table,
      where: 'call_id = ?',
      whereArgs: <Object?>[callId],
      limit: 1,
    );
    return rows.isEmpty ? null : rows.first;
  }

  CallRecording _fromRow(Map<String, Object?> row) {
    final keepUntil = row['keep_until'] as String?;
    return CallRecording(
      callId: row['call_id']! as String,
      path: row['path']! as String,
      bytesTotal: (row['bytes_total'] as num?)?.toInt() ?? 0,
      uploadedBytes: (row['uploaded_bytes'] as num?)?.toInt() ?? 0,
      status: RecordingUploadStatus.values.firstWhere(
        (s) => s.name == row['status'],
        orElse: () => RecordingUploadStatus.pending,
      ),
      createdAt: DateTime.parse(row['created_at']! as String),
      contentType: (row['content_type'] as String?) ?? 'audio/wav',
      keepUntil: keepUntil == null ? null : DateTime.parse(keepUntil),
      uploadedAt:
          row['uploaded_at'] == null ? null : DateTime.parse(row['uploaded_at']! as String),
    );
  }
}
