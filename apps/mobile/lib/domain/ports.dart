/// Ports (abstract contracts) that the Application layer depends on.
/// Infrastructure implements them; tests override them with fakes.
/// No Flutter/plugin imports here — keeps the domain layer testable.
library;

import 'models.dart';
import 'sync_models.dart';

class AuthResult {
  const AuthResult({required this.session});

  final AuthSession session;
}

abstract class AuthApi {
  Future<void> requestOtp(String phone);

  Future<AuthResult> login({required String phone, required String otp});

  Future<void> logout();

  /// Rotates the refresh token; returns the updated session or null on failure.
  Future<AuthSession?> refreshSession();
}

abstract class SessionStore {
  Future<AuthSession?> read();

  Future<void> save(AuthSession session);

  Future<void> clear();
}

abstract class BoardApi {
  Future<List<TaskItem>> fetchMyTasks();

  Future<List<Agreement>> fetchMyAgreements();
}

abstract class SyncApi {
  Future<SyncPullResult> pull({String? since});

  Future<SyncPushResult> push(List<SyncOperation> operations);
}

abstract class ContactsSource {
  Future<ContactsLoadResult> load();
}

class ContactsLoadResult {
  const ContactsLoadResult({required this.allowed, required this.items});

  final bool allowed;
  final List<ContactItem> items;
}

abstract class LocalBoardStore {
  Future<void> upsertTask(TaskItem task);

  Future<void> removeTask(String id);

  Future<List<TaskItem>> allTasks();

  Future<void> upsertAgreement(Agreement agreement);

  Future<void> removeAgreement(String id);

  Future<List<Agreement>> allAgreements();
}

abstract class OutboxStore {
  /// Adds an operation, deduplicating by idempotency key.
  Future<void> enqueue(SyncOperation operation);

  Future<List<SyncOperation>> pending();

  /// Drops every outbox row for the entity (terminal push result).
  Future<void> removeByEntity(String entityType, String entityId);
}

abstract class SyncStateStore {
  Future<String?> readSyncToken();

  Future<void> writeSyncToken(String token);

  Future<int> readRecordVersion(String entityType, String id);

  Future<void> writeRecordVersion(String entityType, String id, int version);
}