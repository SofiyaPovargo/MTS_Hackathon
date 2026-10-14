/// Ports (abstract contracts) that the Application layer depends on.
/// Infrastructure implements them; tests override them with fakes.
/// No Flutter/plugin imports here — keeps the domain layer testable.
library;

import 'audio.dart';
import 'call.dart';
import 'consent.dart';
import 'enums.dart';
import 'models.dart';
import 'offline_call.dart';
import 'schedule.dart';
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
    String? priority,
    String? taskType,
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

  /// Opens the recorded (mixed) media stream for [externalId] once recording is
  /// enabled. Bytes are encoded chunks in the provider's format (the MTS Exolve
  /// mobile SDK mix). Real adapters hide the platform capture; the mock emits
  /// synthetic chunks for local development. Ending the stream stops capture.
  Stream<List<int>> openMediaStream(String externalId);
}

/// Optional dev capability: synthesizes an incoming call without a real
/// provider. Implemented by the mock only; feature code checks the type.
abstract class IncomingCallSimulator {
  void simulateIncoming({required String phone, String? name});
}

/// Call records on the backend (`POST /calls`, `GET /calls`, `GET /calls/{id}`).
abstract class CallApi {
  /// Creates a call. A client [id] makes it idempotent (offline, plan.md §13):
  /// replaying the request after a network drop returns the same call instead of
  /// creating a duplicate. [startedAt] records the real conversation start and
  /// [recordConsent] the app user's decision (the offline client asserts both).
  Future<Call> createCall({
    required CallDirection direction,
    required String calleePhone,
    String? contactName,
    String? id,
    DateTime? startedAt,
    bool recordConsent = true,
  });

  Future<Call> getCall(String id);

  /// The user's own call history (`GET /calls`), newest first.
  Future<List<Call>> calls();

  /// Declares a call recorded on the client and its consent
  /// (`POST /calls/{id}/recordings`, plan.md §13, offline). The server records
  /// both consent events and only then fixes `recording_started_at`, so the
  /// audio upload stays impossible without consent. Idempotent.
  Future<Call> declareRecording(
    String callId, {
    bool recordConsent = true,
    ConsentStatus participantConsent = ConsentStatus.granted,
    ConsentMethod consentMethod = ConsentMethod.audioNotice,
    DateTime? answeredAt,
    DateTime? recordingStartedAt,
    DateTime? endedAt,
  });
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
  Future<Agreement> create({
    required String callId,
    required AgreementPatch patch,
  });

  /// User edits (`PATCH /agreements/{id}`).
  Future<Agreement> patch(String agreementId, AgreementPatch changes);

  /// Confirm → the server creates the task (`POST /agreements/{id}/confirm`).
  Future<Agreement> confirm(String agreementId);

  Future<Agreement> reject(String agreementId);
}

/// Local storage of recorded audio: a bounded cache of the user's own recent
/// calls plus the upload state of each recording (plan.md §8, Stage 6). Audio
/// bytes live in a file; metadata/status lives in the local DB.
abstract class AudioRecordingStore {
  /// Creates (or resets) the recording for [callId] and returns it.
  Future<CallRecording> begin(
    String callId, {
    String contentType,
    Duration? keepFor,
  });

  /// Appends captured bytes and returns the updated recording.
  Future<CallRecording> append(String callId, List<int> bytes);

  Future<CallRecording?> get(String callId);

  /// Bytes from [offset] to the end of the file (for a resumed upload).
  Future<List<int>> readFrom(String callId, int offset);

  /// Records the server-confirmed offset; [complete] clears the pending state.
  Future<void> markUploaded(
    String callId, {
    required int uploadedBytes,
    required bool complete,
  });

  Future<void> setStatus(String callId, RecordingUploadStatus status);

  /// Recordings that still need to be uploaded (offline / dropped network).
  Future<List<CallRecording>> pending();

  Future<void> delete(String callId);

  /// Drops uploaded recordings past their retention / above [maxRecordings]
  /// (keeps the local cache bounded).
  Future<void> enforceRetention({int maxRecordings});
}

/// Queue of calls the client registered itself while offline (plan.md §13).
///
/// An entry is removed only after the server accepts both the call and its
/// recording declaration. The queue lives in the local DB (a cache + offline
/// change queue), never in a second system of record.
abstract class PendingCallStore {
  /// Inserts or replaces the registration for [call] (keyed by `call_id`).
  Future<void> save(PendingCall call);

  Future<List<PendingCall>> pending();

  Future<void> remove(String callId);
}

/// Resumable ingest of a recording (`POST /calls/{id}/audio`).
///
/// With [start]/[total] the request carries `Content-Range` and is one chunk of
/// a resumable upload; the returned offset is the durable byte count, so a
/// reconnect resumes exactly there (plan.md §13).
abstract class AudioIngestApi {
  Future<AudioIngestResult> upload({
    required String callId,
    required List<int> bytes,
    int? start,
    int? total,
    String? contentType,
    int? durationSec,
  });
}

/// Live audio frames (`WS /ws/calls/{id}/audio`), used for real-time analysis
/// while online. Best-effort: a failure must never lose already-recorded audio.
abstract class LiveAudioPort {
  Future<void> connect(String callId);

  Future<void> send(List<int> frame);

  Future<void> close();
}

/// Call summary, calendar, reminders and client-message drafts (plan.md §9).
///
/// Every calendar/reminder/draft write is an explicit user action; the draft is
/// never sent automatically. Pure contract — no Flutter imports.
abstract class ScheduleApi {
  /// Итог звонка (`GET /calls/{call_id}/summary`), owner only.
  Future<CallSummary> callSummary(String callId);

  /// Writes the confirmed task into the calendar (`POST /tasks/{id}/calendar`).
  Future<CalendarEvent> createCalendarEvent(String taskId);

  /// Portable `.ics` (`GET /tasks/{id}/calendar.ics`), raw `text/calendar`.
  Future<String> ics(String taskId);

  /// Removes the task's calendar event (`DELETE /tasks/{id}/calendar`).
  Future<void> deleteCalendarEvent(String taskId);

  /// Schedules a reminder (`POST /tasks/{id}/reminders`).
  Future<Reminder> createReminder(
    String taskId, {
    required DateTime remindAt,
    ReminderChannel channel = ReminderChannel.push,
  });

  /// Lists the task's reminders (`GET /tasks/{id}/reminders`).
  Future<List<Reminder>> reminders(String taskId);

  /// Cancels a reminder (`POST /reminders/{id}/cancel`).
  Future<Reminder> cancelReminder(String reminderId);

  /// Builds a client-message draft (`POST /tasks/{id}/message-draft`); the
  /// draft is never sent automatically.
  Future<MessageDraft> draftMessage(String taskId);
}
