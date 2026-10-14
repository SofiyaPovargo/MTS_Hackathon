/// Ports (abstract contracts) that the Application layer depends on.
/// Infrastructure implements them; tests override them with fakes.
/// No Flutter/plugin imports here — keeps the domain layer testable.
library;

import 'call.dart';
import 'consent.dart';
import 'enums.dart';
import 'models.dart';
import 'sync_models.dart';
import 'ws_event.dart';

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

/// Manager dashboard (`/manager/team/*`). Team data is never persisted locally
/// (AGENTS: the phone stores only the user's own data), so the manager board
/// keeps it in memory and re-fetches on refresh. The server re-checks the role
/// and team membership on every call.
abstract class ManagerApi {
  Future<List<TaskItem>> fetchTeamTasks({
    String? userId,
    String? status,
    DateTime? dueBefore,
  });

  Future<TeamStats> fetchTeamStats();

  Future<List<TeamMember>> fetchTeamMembers();
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

/// Voice provider (VoIP / PSTN) behind a port.
///
/// Platform-specific implementations (CallKit/PushKit on iOS,
/// Telecom/ConnectionService on Android, or the MTS Exolve mobile SDK) are
/// injected through DI; feature code never calls a platform API directly
/// (AGENTS.md). A mock implementation backs local development and tests.
abstract class VoiceCallProvider {
  /// Contextual microphone permission. `false` means the call must not start.
  Future<bool> ensureMicrophonePermission();

  /// Provider signals: incoming, ringing, answered, ended, dropped, missed.
  Stream<CallSignal> get signals;

  /// Places an outgoing call and returns the provider call id.
  Future<String> dial(String phone, {String? name});

  Future<void> answer(String externalId);

  Future<void> decline(String externalId);

  Future<void> hangup(String externalId);

  Future<void> setMuted(String externalId, bool muted);
}

/// Optional dev capability: synthesizes an incoming call without a real
/// provider. Implemented by the mock only; feature code checks the type.
abstract class IncomingCallSimulator {
  void simulateIncoming({required String phone, String? name});
}

/// Call records on the backend (`POST /calls`, `GET /calls/{id}`).
abstract class CallApi {
  Future<Call> createCall({
    required CallDirection direction,
    required String calleePhone,
    String? contactName,
  });

  Future<Call> getCall(String id);
}

/// The app user's consent to recording / AI processing
/// (`PUT /me/consent`, `POST /me/consent/withdraw`, `POST /me/data/delete`).
abstract class ConsentApi {
  Future<ConsentRecord> setAppConsent(bool granted);

  Future<ConsentRecord> withdrawConsent();

  /// Enqueues the real data-deletion job on the server.
  Future<void> requestDataDeletion();
}

/// Local cache of the app user's consent decision. The server has no read
/// endpoint for it, so the decision is cached here and written through on
/// change; a fresh install asks again.
abstract class ConsentStore {
  Future<AppConsent> read();

  Future<void> save(AppConsent consent);
}

/// Live per-call events over WebSocket (`/api/ws/calls/{call_id}`, schema v1).
/// Connecting replays what was missed; the stream then delivers live frames.
abstract class CallEventsPort {
  Future<void> connect(String callId);

  Stream<CallEvent> get events;

  Future<void> disconnect();
}

/// Agreement actions over REST (`/calls/{id}/agreements*`, `/agreements/{id}*`).
abstract class AgreementApi {
  Future<List<Agreement>> listForCall(String callId);

  /// Manual entry / no-consent path (`POST /calls/{id}/agreements`).
  Future<Agreement> create({required String callId, required AgreementPatch patch});

  /// User edits (`PATCH /agreements/{id}`).
  Future<Agreement> patch(String agreementId, AgreementPatch changes);

  /// Confirm → the server creates the task (`POST /agreements/{id}/confirm`).
  Future<Agreement> confirm(String agreementId);

  Future<Agreement> reject(String agreementId);
}