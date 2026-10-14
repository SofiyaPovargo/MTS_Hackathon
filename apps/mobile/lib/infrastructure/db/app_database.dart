import 'package:path/path.dart' as p;
import 'package:sqflite/sqflite.dart';

/// Local SQLite cache. The server is the single source of truth; this database
/// only stores the user's own data: tasks, agreements, the sync outbox, the
/// sync token / record versions, and the auth session (plan.md §8).
///
/// All tables use the API's snake_case field names so rows round-trip through
/// the same `fromJson` parsers.
class AppDatabase {
  AppDatabase({DatabaseFactory? factory, String fileName = 'agreement_capture.db', String? path})
      : _factory = factory,
        _fileName = fileName,
        _path = path;

  static const int schemaVersion = 3;

  static const String _appSettingsTableSql = '''
      CREATE TABLE app_settings(
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
      )
    ''';

  static const String _audioRecordingsTableSql = '''
      CREATE TABLE audio_recordings(
        call_id TEXT PRIMARY KEY,
        path TEXT NOT NULL,
        content_type TEXT NOT NULL DEFAULT 'audio/wav',
        bytes_total INTEGER NOT NULL DEFAULT 0,
        uploaded_bytes INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        uploaded_at TEXT,
        keep_until TEXT
      )
    ''';

  /// The sqflite factory is resolved lazily so constructing the database (and
  /// therefore wiring providers) never touches the platform channel.
  final DatabaseFactory? _factory;
  final String _fileName;
  final String? _path;
  Future<Database>? _opening;

  Future<Database> open() => _opening ??= _open();

  Future<void> close() async {
    final opening = _opening;
    _opening = null;
    if (opening != null) {
      await (await opening).close();
    }
  }

  Future<Database> _open() async {
    final factory = _factory ?? databaseFactory;
    final location = _path ?? p.join(await factory.getDatabasesPath(), _fileName);
    return factory.openDatabase(
      location,
      options: OpenDatabaseOptions(
        version: schemaVersion,
        onCreate: _createSchema,
        onUpgrade: _upgradeSchema,
        onConfigure: (db) => db.execute('PRAGMA foreign_keys = ON'),
      ),
    );
  }

  Future<void> _upgradeSchema(Database db, int oldVersion, int newVersion) async {
    if (oldVersion < 2) {
      await db.execute(_appSettingsTableSql);
    }
    if (oldVersion < 3) {
      await db.execute(_audioRecordingsTableSql);
    }
  }

  Future<void> _createSchema(Database db, int version) async {
    final batch = db.batch();
    batch.execute('''
      CREATE TABLE tasks(
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        description TEXT,
        assignee_user_id TEXT NOT NULL,
        agreement_id TEXT,
        priority TEXT NOT NULL,
        status TEXT NOT NULL,
        due_date TEXT,
        due_time TEXT,
        completed_at TEXT,
        version INTEGER NOT NULL DEFAULT 0,
        created_at TEXT,
        updated_at TEXT
      )
    ''');
    batch.execute('''
      CREATE TABLE agreements(
        id TEXT PRIMARY KEY,
        call_id TEXT NOT NULL,
        owner TEXT NOT NULL,
        type TEXT NOT NULL,
        title TEXT NOT NULL,
        object TEXT,
        due_date TEXT,
        due_time TEXT,
        amount REAL,
        currency TEXT,
        source_quote TEXT NOT NULL,
        audio_start REAL NOT NULL DEFAULT 0,
        audio_end REAL NOT NULL DEFAULT 0,
        confidence REAL NOT NULL DEFAULT 0,
        status TEXT NOT NULL,
        version INTEGER NOT NULL DEFAULT 0,
        created_at TEXT,
        updated_at TEXT
      )
    ''');
    batch.execute('''
      CREATE TABLE outbox(
        id TEXT PRIMARY KEY,
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        operation TEXT NOT NULL,
        idempotency_key TEXT NOT NULL UNIQUE,
        version INTEGER,
        payload TEXT NOT NULL,
        created_at INTEGER NOT NULL
      )
    ''');
    batch.execute('''
      CREATE TABLE sync_state(
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
      )
    ''');
    batch.execute('''
      CREATE TABLE session(
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
      )
    ''');
    batch.execute(_appSettingsTableSql);
    batch.execute(_audioRecordingsTableSql);
    await batch.commit(noResult: true);
  }
}