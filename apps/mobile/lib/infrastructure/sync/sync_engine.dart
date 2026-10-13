import '../../domain/models.dart';
import '../../domain/ports.dart';
import '../../domain/sync_models.dart';
import '../api/api_exception.dart';

/// Runs the sync cycle from plan.md §9:
///
///   pull (deltas) → apply to the local DB → push the outbox → ack → update token.
///
/// - Replayed rows (`version <=` the known record version) are skipped, so the
///   cycle is idempotent.
/// - Network/5xx errors retry with exponential backoff; auth errors bubble up so
///   the caller can re-authenticate.
/// - On a version conflict the server is authoritative: the local op is dropped
///   and the sync token is cleared, forcing a full re-pull that overwrites the
///   local row with the server version.
class SyncEngine {
  SyncEngine({
    required SyncApi syncApi,
    required LocalBoardStore board,
    required OutboxStore outbox,
    required SyncStateStore state,
    this.maxAttempts = 4,
    Duration baseBackoff = const Duration(milliseconds: 400),
  })  : _syncApi = syncApi,
        _board = board,
        _outbox = outbox,
        _state = state,
        _baseBackoff = baseBackoff;

  final SyncApi _syncApi;
  final LocalBoardStore _board;
  final OutboxStore _outbox;
  final SyncStateStore _state;
  final int maxAttempts;
  final Duration _baseBackoff;

  Future<SyncResult> run() async {
    var pulled = 0;
    var token = await _state.readSyncToken();
    var hasMore = true;
    while (hasMore) {
      final page = await _withRetry(() => _syncApi.pull(since: token));
      for (final change in page.changes) {
        if (await _apply(change)) pulled++;
      }
      token = page.syncToken;
      hasMore = page.hasMore;
      await _state.writeSyncToken(token);
    }

    var pushed = 0;
    var conflicts = 0;
    var forceFullResync = false;
    final pending = await _outbox.pending();
    if (pending.isNotEmpty) {
      final response = await _withRetry(() => _syncApi.push(pending));
      for (final result in response.results) {
        pushed++;
        if (result.isConflict) conflicts++;
        if (await _handleResult(result)) forceFullResync = true;
      }
    }
    if (forceFullResync) {
      // Clearing the token makes the next pull return every row again.
      await _state.writeSyncToken('');
    }
    return SyncResult(pulled: pulled, pushed: pushed, conflicts: conflicts);
  }

  Future<bool> _apply(SyncChange change) async {
    final known = await _state.readRecordVersion(change.entityType, change.id);
    if (change.version <= known) return false;

    // Pull deltas omit `version`/`created_at`: the version lives on the change.
    final data = <String, dynamic>{...change.data, 'version': change.version};
    var cached = true;
    if (change.entityType == 'task') {
      await _board.upsertTask(TaskItem.fromJson(data));
    } else if (change.entityType == 'agreement') {
      await _board.upsertAgreement(Agreement.fromJson(data));
    } else {
      // Calls and reminders are not cached locally yet (Stage 3 scope).
      cached = false;
    }
    await _state.writeRecordVersion(change.entityType, change.id, change.version);
    return cached;
  }

  /// Returns true when the caller must force a full re-pull.
  Future<bool> _handleResult(SyncOpResult result) async {
    if (result.isAccepted) {
      await _outbox.removeByEntity(result.entityType, result.entityId);
      final version = result.version;
      if (version != null) {
        await _state.writeRecordVersion(result.entityType, result.entityId, version);
      }
      return false;
    }
    if (result.isConflict) {
      await _outbox.removeByEntity(result.entityType, result.entityId);
      return true;
    }
    if (result.isRejected) {
      // Nothing to apply; drop it so we do not retry forever.
      await _outbox.removeByEntity(result.entityType, result.entityId);
    }
    return false;
  }

  Future<T> _withRetry<T>(Future<T> Function() action) async {
    var attempt = 0;
    while (true) {
      try {
        return await action();
      } on ApiException catch (error) {
        attempt++;
        if (!error.isRetryable || attempt >= maxAttempts) rethrow;
        await Future<void>.delayed(_backoff(attempt));
      }
    }
  }

  Duration _backoff(int attempt) =>
      Duration(milliseconds: _baseBackoff.inMilliseconds * (1 << (attempt - 1)));
}
