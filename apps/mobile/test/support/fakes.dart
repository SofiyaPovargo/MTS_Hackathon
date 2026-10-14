import 'dart:async';

import 'package:agreement_capture/domain/audio.dart';
import 'package:agreement_capture/domain/call.dart';
import 'package:agreement_capture/domain/consent.dart';
import 'package:agreement_capture/domain/enums.dart';
import 'package:agreement_capture/domain/models.dart';
import 'package:agreement_capture/domain/ports.dart';
import 'package:agreement_capture/domain/schedule.dart';
import 'package:agreement_capture/domain/sync_models.dart';
import 'package:agreement_capture/domain/ws_event.dart';
import 'package:agreement_capture/infrastructure/api/api_exception.dart';

UserProfile testUser({
  String id = '11111111-1111-1111-1111-111111111111',
  String phone = '+79000000002',
  String fullName = 'Анна',
  Role role = Role.user,
}) {
  return UserProfile(
    id: id,
    phone: phone,
    fullName: fullName,
    role: role,
    timezone: 'Europe/Moscow',
  );
}

AuthSession testSession({
  String accessToken = 'access-1',
  String refreshToken = 'refresh-1',
  UserProfile? user,
}) {
  return AuthSession(
    accessToken: accessToken,
    refreshToken: refreshToken,
    expiresIn: 3600,
    user: user ?? testUser(),
  );
}

TaskItem testTask({
  String id = '22222222-2222-2222-2222-222222222222',
  String title = 'Позвонить клиенту',
  TaskStatus status = TaskStatus.newTask,
  TaskPriority priority = TaskPriority.medium,
  DateTime? dueDate,
  String? description,
  String? agreementId,
  int version = 1,
}) {
  return TaskItem(
    id: id,
    title: title,
    description: description,
    assigneeUserId: '11111111-1111-1111-1111-111111111111',
    agreementId: agreementId,
    priority: priority,
    status: status,
    dueDate: dueDate,
    version: version,
    createdAt: DateTime.utc(2026, 10),
    updatedAt: DateTime.utc(2026, 10),
  );
}

TeamMember testMember({
  String id = '11111111-1111-1111-1111-111111111111',
  String phone = '+79000000002',
  String fullName = 'Анна',
  Role role = Role.user,
}) {
  return TeamMember(id: id, phone: phone, fullName: fullName, role: role);
}

TeamStats testStats({
  int membersCount = 2,
  int agreementsTotal = 3,
  int tasksTotal = 5,
  Map<String, int> tasksByStatus = const <String, int>{
    'new': 2,
    'done': 2,
    'overdue': 1,
  },
  int overdue = 1,
  int doneOnTime = 2,
  double doneOnTimePercent = 100,
  double? avgCloseHours = 12.5,
  double tasksFromCallsPercent = 80,
  List<MemberStats> memberStats = const <MemberStats>[],
}) {
  return TeamStats(
    membersCount: membersCount,
    agreementsTotal: agreementsTotal,
    tasksTotal: tasksTotal,
    tasksByStatus: tasksByStatus,
    overdue: overdue,
    doneOnTime: doneOnTime,
    doneOnTimePercent: doneOnTimePercent,
    avgCloseHours: avgCloseHours,
    tasksFromCallsPercent: tasksFromCallsPercent,
    memberStats: memberStats,
  );
}

Agreement testAgreement({
  String id = '33333333-3333-3333-3333-333333333333',
  int version = 1,
}) {
  return Agreement(
    id: id,
    callId: '44444444-4444-4444-4444-444444444444',
    owner: AgreementOwner.user,
    type: 'payment',
    title: 'Оплатить счёт',
    sourceQuote: 'оплачу до пятницы',
    audioStart: 12.5,
    audioEnd: 18.0,
    confidence: 0.92,
    status: AgreementStatus.detected,
    version: version,
    createdAt: DateTime.utc(2026, 10),
    updatedAt: DateTime.utc(2026, 10),
  );
}

Call testCall({
  String id = '55555555-5555-5555-5555-555555555555',
  CallDirection direction = CallDirection.outbound,
  String contactPhone = '+79000000002',
  String? contactName = 'Анна',
  String status = 'ringing',
}) {
  return Call(
    id: id,
    direction: direction,
    contactPhone: contactPhone,
    contactName: contactName,
    status: status,
    version: 1,
    createdAt: DateTime.utc(2026, 10),
    updatedAt: DateTime.utc(2026, 10),
  );
}

ConsentRecord testConsentRecord({
  String id = '66666666-6666-6666-6666-666666666666',
  ConsentStatus status = ConsentStatus.granted,
}) {
  return ConsentRecord(
    id: id,
    subjectType: 'app_user',
    status: status,
    method: ConsentMethod.appSettings,
  );
}

CallSummary testCallSummary({
  String callId = '55555555-5555-5555-5555-555555555555',
  String summary = 'Договорились оплатить счёт до пятницы.',
  int agreementsTotal = 2,
  int agreementsConfirmed = 1,
}) {
  return CallSummary(
    callId: callId,
    summary: summary,
    agreementsTotal: agreementsTotal,
    agreementsConfirmed: agreementsConfirmed,
  );
}

CalendarEvent testCalendarEvent({
  String taskId = 't1',
  String eventId = 'evt-1',
  String title = 'Позвонить клиенту',
  DateTime? startsAt,
  DateTime? endsAt,
}) {
  return CalendarEvent(
    taskId: taskId,
    eventId: eventId,
    title: title,
    startsAt: startsAt ?? DateTime.utc(2026, 10, 15, 9),
    endsAt: endsAt ?? DateTime.utc(2026, 10, 15, 9, 30),
  );
}

Reminder testReminder({
  String id = 'rem-1',
  String taskId = 't1',
  DateTime? remindAt,
  ReminderChannel channel = ReminderChannel.push,
  ReminderStatus status = ReminderStatus.scheduled,
}) {
  return Reminder(
    id: id,
    taskId: taskId,
    remindAt: remindAt ?? DateTime.utc(2026, 10, 15, 8),
    channel: channel,
    status: status,
  );
}

MessageDraft testMessageDraft({
  String taskId = 't1',
  String draftId = 'draft-1',
  String phone = '+79000000002',
  String text = 'Анна, добрый день! Подтвердите, пожалуйста, оплату счёта.',
  bool sent = false,
}) {
  return MessageDraft(
    taskId: taskId,
    draftId: draftId,
    phone: phone,
    text: text,
    sent: sent,
  );
}

class InMemorySessionStore implements SessionStore {
  AuthSession? session;

  @override
  Future<AuthSession?> read() async => session;

  @override
  Future<void> save(AuthSession value) async => session = value;

  @override
  Future<void> clear() async => session = null;
}

class FakeAuthApi implements AuthApi {
  FakeAuthApi({this.session, this.error, this.sessionStore});

  AuthSession? session;
  ApiException? error;
  SessionStore? sessionStore;
  int otpRequests = 0;
  int loginRequests = 0;
  int logoutRequests = 0;
  int refreshRequests = 0;

  @override
  Future<void> requestOtp(String phone) async {
    otpRequests++;
    final failure = error;
    if (failure != null) throw failure;
  }

  @override
  Future<AuthResult> login({required String phone, required String otp}) async {
    loginRequests++;
    final failure = error;
    if (failure != null) throw failure;
    final current = session;
    if (current == null) {
      throw const ApiException(ApiErrorKind.sessionExpired, 'No session');
    }
    // Mirrors HttpAuthApi: the session is persisted on login.
    await sessionStore?.save(current);
    return AuthResult(session: current);
  }

  @override
  Future<void> logout() async {
    logoutRequests++;
    await sessionStore?.clear();
  }

  @override
  Future<AuthSession?> refreshSession() async {
    refreshRequests++;
    return session;
  }
}

class FakeBoardApi implements BoardApi {
  FakeBoardApi({
    this.tasks = const <TaskItem>[],
    this.agreements = const <Agreement>[],
  });

  List<TaskItem> tasks;
  List<Agreement> agreements;

  @override
  Future<List<TaskItem>> fetchMyTasks() async => tasks;

  @override
  Future<List<Agreement>> fetchMyAgreements() async => agreements;
}

/// Controllable [ManagerApi]: records the filter arguments and returns canned
/// team data, so the controller and board can be tested without a server.
class FakeManagerApi implements ManagerApi {
  FakeManagerApi({
    this.tasks = const <TaskItem>[],
    TeamStats? stats,
    this.members = const <TeamMember>[],
    this.error,
  }) : stats = stats ?? testStats();

  List<TaskItem> tasks;
  TeamStats stats;
  List<TeamMember> members;
  ApiException? error;

  String? lastUserId;
  String? lastStatus;
  String? lastPriority;
  String? lastTaskType;
  DateTime? lastDueBefore;
  int taskCalls = 0;
  int statsCalls = 0;
  int memberCalls = 0;

  @override
  Future<List<TaskItem>> fetchTeamTasks({
    String? userId,
    String? status,
    String? priority,
    String? taskType,
    DateTime? dueBefore,
  }) async {
    taskCalls++;
    lastUserId = userId;
    lastStatus = status;
    lastPriority = priority;
    lastTaskType = taskType;
    lastDueBefore = dueBefore;
    final failure = error;
    if (failure != null) throw failure;
    return tasks;
  }

  @override
  Future<TeamStats> fetchTeamStats() async {
    statsCalls++;
    final failure = error;
    if (failure != null) throw failure;
    return stats;
  }

  @override
  Future<List<TeamMember>> fetchTeamMembers() async {
    memberCalls++;
    final failure = error;
    if (failure != null) throw failure;
    return members;
  }
}

class FakeSyncApi implements SyncApi {
  FakeSyncApi({this.nextPull, this.nextPush});

  SyncPullResult? nextPull;
  SyncPushResult? nextPush;
  ApiException? pullError;
  int pullFailures = 0;
  int pullCalls = 0;
  int pushCalls = 0;
  List<SyncOperation>? lastPushed;
  final List<String?> requestedSince = <String?>[];

  @override
  Future<SyncPullResult> pull({String? since}) async {
    pullCalls++;
    requestedSince.add(since);
    final failure = pullError;
    if (failure != null && pullFailures > 0) {
      pullFailures--;
      throw failure;
    }
    return nextPull ??
        SyncPullResult(
          changes: const <SyncChange>[],
          syncToken: 'token-$pullCalls',
          hasMore: false,
        );
  }

  @override
  Future<SyncPushResult> push(List<SyncOperation> operations) async {
    pushCalls++;
    lastPushed = operations;
    return nextPush ?? const SyncPushResult(results: <SyncOpResult>[]);
  }
}

class FakeContactsSource implements ContactsSource {
  FakeContactsSource({required this.result});

  ContactsLoadResult result;
  int loadCalls = 0;

  @override
  Future<ContactsLoadResult> load() async {
    loadCalls++;
    return result;
  }
}

class InMemoryBoardStore implements LocalBoardStore {
  final Map<String, TaskItem> tasks = <String, TaskItem>{};
  final Map<String, Agreement> agreements = <String, Agreement>{};

  @override
  Future<List<TaskItem>> allTasks() async => tasks.values.toList();

  @override
  Future<List<Agreement>> allAgreements() async => agreements.values.toList();

  @override
  Future<void> upsertTask(TaskItem task) async => tasks[task.id] = task;

  @override
  Future<void> removeTask(String id) async => tasks.remove(id);

  @override
  Future<void> upsertAgreement(Agreement agreement) async =>
      agreements[agreement.id] = agreement;

  @override
  Future<void> removeAgreement(String id) async => agreements.remove(id);
}

class InMemoryOutboxStore implements OutboxStore {
  final Map<String, SyncOperation> operations = <String, SyncOperation>{};

  @override
  Future<void> enqueue(SyncOperation operation) async {
    operations.putIfAbsent(operation.idempotencyKey, () => operation);
  }

  @override
  Future<List<SyncOperation>> pending() async => operations.values.toList();

  @override
  Future<void> removeByEntity(String entityType, String entityId) async {
    operations.removeWhere(
      (key, value) =>
          value.entityType.wire == entityType && value.entityId == entityId,
    );
  }
}

class InMemorySyncStateStore implements SyncStateStore {
  String? token;
  final Map<String, int> versions = <String, int>{};

  @override
  Future<String?> readSyncToken() async => token;

  @override
  Future<void> writeSyncToken(String value) async =>
      token = value.isEmpty ? null : value;

  @override
  Future<int> readRecordVersion(String entityType, String id) async =>
      versions['$entityType:$id'] ?? 0;

  @override
  Future<void> writeRecordVersion(
    String entityType,
    String id,
    int version,
  ) async => versions['$entityType:$id'] = version;
}

/// Controllable [VoiceCallProvider]: records control calls and lets tests emit
/// provider signals explicitly (no timers, no platform channels).
class FakeVoiceCallProvider
    implements VoiceCallProvider, IncomingCallSimulator {
  FakeVoiceCallProvider({this.microphoneGranted = true});

  bool microphoneGranted;
  final StreamController<CallSignal> _controller =
      StreamController<CallSignal>.broadcast();
  final List<String> dialed = <String>[];
  final List<String> answered = <String>[];
  final List<String> declined = <String>[];
  final List<String> hungUp = <String>[];
  final List<bool> muted = <bool>[];
  int _sequence = 0;

  @override
  Stream<CallSignal> get signals => _controller.stream;

  @override
  Future<bool> ensureMicrophonePermission() async => microphoneGranted;

  @override
  Future<String> dial(String phone, {String? name}) async {
    dialed.add(phone);
    return 'fake-${++_sequence}';
  }

  @override
  Future<void> answer(String externalId) async {
    answered.add(externalId);
    emit(CallSignal(kind: CallSignalKind.answered, externalId: externalId));
  }

  @override
  Future<void> decline(String externalId) async {
    declined.add(externalId);
    emit(CallSignal(kind: CallSignalKind.missed, externalId: externalId));
  }

  @override
  Future<void> hangup(String externalId) async {
    hungUp.add(externalId);
    emit(CallSignal(kind: CallSignalKind.ended, externalId: externalId));
  }

  @override
  Future<void> setMuted(String externalId, bool value) async =>
      muted.add(value);

  final List<String> mediaStreamOpened = <String>[];
  StreamController<List<int>>? _mediaController;

  @override
  Stream<List<int>> openMediaStream(String externalId) {
    mediaStreamOpened.add(externalId);
    final controller = StreamController<List<int>>();
    _mediaController = controller;
    controller.onCancel = () {
      if (identical(_mediaController, controller)) _mediaController = null;
    };
    return controller.stream;
  }

  /// Pushes a captured audio chunk to the active media stream (tests).
  void emitAudio(List<int> bytes) {
    final controller = _mediaController;
    if (controller != null && !controller.isClosed) controller.add(bytes);
  }

  @override
  void simulateIncoming({required String phone, String? name}) {
    emit(
      CallSignal(
        kind: CallSignalKind.incoming,
        externalId: 'fake-${++_sequence}',
        phone: phone,
        name: name,
      ),
    );
  }

  void emit(CallSignal signal) {
    if (!_controller.isClosed) _controller.add(signal);
  }

  Future<void> dispose() => _controller.close();
}

class FakeCallApi implements CallApi {
  FakeCallApi({this.error});

  ApiException? error;
  final List<Call> created = <Call>[];

  @override
  Future<Call> createCall({
    required CallDirection direction,
    required String calleePhone,
    String? contactName,
  }) async {
    final failure = error;
    if (failure != null) throw failure;
    final call = testCall(
      direction: direction,
      contactPhone: calleePhone,
      contactName: contactName,
    );
    created.add(call);
    return call;
  }

  @override
  Future<Call> getCall(String id) async => testCall(id: id);
}

class InMemoryConsentStore implements ConsentStore {
  InMemoryConsentStore([this.consent = AppConsent.undecided]);

  AppConsent consent;

  @override
  Future<AppConsent> read() async => consent;

  @override
  Future<void> save(AppConsent value) async => consent = value;
}

class FakeConsentApi implements ConsentApi {
  FakeConsentApi({this.error});

  ApiException? error;
  final List<bool> decisions = <bool>[];
  int withdrawals = 0;
  int deletions = 0;

  @override
  Future<ConsentRecord> setAppConsent(bool granted) async {
    final failure = error;
    if (failure != null) throw failure;
    decisions.add(granted);
    return testConsentRecord(
      status: granted ? ConsentStatus.granted : ConsentStatus.denied,
    );
  }

  @override
  Future<ConsentRecord> withdrawConsent() async {
    final failure = error;
    if (failure != null) throw failure;
    withdrawals++;
    return testConsentRecord(status: ConsentStatus.withdrawn);
  }

  @override
  Future<void> requestDataDeletion() async {
    final failure = error;
    if (failure != null) throw failure;
    deletions++;
  }
}

/// Controllable [CallEventsPort]: tests connect explicitly and push live events
/// instead of a WebSocket (the real client is `WebSocketCallEvents`).
class FakeCallEventsPort implements CallEventsPort {
  FakeCallEventsPort({this.error});

  ApiException? error;
  final StreamController<CallEvent> _controller =
      StreamController<CallEvent>.broadcast();
  final List<String> connected = <String>[];
  int disconnectCalls = 0;

  @override
  Future<void> connect(String callId) async {
    final failure = error;
    if (failure != null) throw failure;
    connected.add(callId);
  }

  @override
  Stream<CallEvent> get events => _controller.stream;

  @override
  Future<void> disconnect() async {
    disconnectCalls++;
    if (!_controller.isClosed) await _controller.close();
  }

  void emit(CallEvent event) => _controller.add(event);
}

/// In-memory [AgreementApi] with server-like semantics: confirm/reject flip the
/// status (final), patch applies the provided fields and bumps the version.
class FakeAgreementApi implements AgreementApi {
  FakeAgreementApi({this.error});

  ApiException? error;
  final Map<String, Agreement> stored = <String, Agreement>{};
  final List<AgreementPatch> created = <AgreementPatch>[];
  int listCalls = 0;

  @override
  Future<List<Agreement>> listForCall(String callId) async {
    listCalls++;
    return stored.values.where((a) => a.callId == callId).toList();
  }

  @override
  Future<Agreement> create({
    required String callId,
    required AgreementPatch patch,
  }) async {
    final failure = error;
    if (failure != null) throw failure;
    created.add(patch);
    final agreement = Agreement(
      id: 'created-${created.length}',
      callId: callId,
      owner: patch.owner ?? AgreementOwner.unknown,
      type: patch.type ?? 'other',
      title: patch.title ?? '',
      object: patch.object,
      dueDate: patch.dueDate,
      amount: patch.amount,
      currency: patch.currency,
      sourceQuote: '',
      audioStart: 0,
      audioEnd: 0,
      confidence: 0,
      status: AgreementStatus.detected,
      version: 1,
      createdAt: DateTime.utc(2026, 10),
      updatedAt: DateTime.utc(2026, 10),
    );
    stored[agreement.id] = agreement;
    return agreement;
  }

  @override
  Future<Agreement> patch(String agreementId, AgreementPatch changes) async {
    final failure = error;
    if (failure != null) throw failure;
    final current = stored[agreementId] ?? testAgreement(id: agreementId);
    final updated = current.copyWith(
      owner: changes.owner ?? current.owner,
      type: changes.type ?? current.type,
      title: changes.title ?? current.title,
      object: changes.object ?? current.object,
      dueDate: changes.dueDate ?? current.dueDate,
      amount: changes.amount ?? current.amount,
      currency: changes.currency ?? current.currency,
      version: current.version + 1,
      updatedAt: DateTime.utc(2026, 10),
    );
    stored[updated.id] = updated;
    return updated;
  }

  @override
  Future<Agreement> confirm(String agreementId) async {
    final failure = error;
    if (failure != null) throw failure;
    final updated = (stored[agreementId] ?? testAgreement(id: agreementId))
        .copyWith(status: AgreementStatus.confirmed, version: 100);
    stored[updated.id] = updated;
    return updated;
  }

  @override
  Future<Agreement> reject(String agreementId) async {
    final failure = error;
    if (failure != null) throw failure;
    final updated = (stored[agreementId] ?? testAgreement(id: agreementId))
        .copyWith(status: AgreementStatus.rejected, version: 100);
    stored[updated.id] = updated;
    return updated;
  }
}

/// In-memory [AudioRecordingStore] for tests: bytes are held per call.
class InMemoryAudioRecordingStore implements AudioRecordingStore {
  final Map<String, List<int>> bytes = <String, List<int>>{};
  final Map<String, CallRecording> records = <String, CallRecording>{};

  @override
  Future<CallRecording> begin(
    String callId, {
    String contentType = 'audio/wav',
    Duration? keepFor,
  }) async {
    bytes[callId] = <int>[];
    final now = DateTime.now().toUtc();
    final recording = CallRecording(
      callId: callId,
      path: 'memory://$callId',
      bytesTotal: 0,
      uploadedBytes: 0,
      status: RecordingUploadStatus.recording,
      createdAt: now,
      contentType: contentType,
      keepUntil: keepFor == null ? null : now.add(keepFor),
    );
    records[callId] = recording;
    return recording;
  }

  @override
  Future<CallRecording> append(String callId, List<int> chunk) async {
    final current = records[callId] ?? await begin(callId);
    final buffer = bytes.putIfAbsent(callId, () => <int>[]);
    buffer.addAll(chunk);
    final updated = current.copyWith(bytesTotal: buffer.length);
    records[callId] = updated;
    return updated;
  }

  @override
  Future<CallRecording?> get(String callId) async => records[callId];

  @override
  Future<List<int>> readFrom(String callId, int offset) async {
    final buffer = bytes[callId] ?? const <int>[];
    if (offset >= buffer.length) return <int>[];
    return buffer.sublist(offset);
  }

  @override
  Future<void> markUploaded(
    String callId, {
    required int uploadedBytes,
    required bool complete,
  }) async {
    final current = records[callId];
    if (current == null) return;
    records[callId] = current.copyWith(
      uploadedBytes: uploadedBytes,
      status: complete ? RecordingUploadStatus.uploaded : current.status,
      uploadedAt: complete ? DateTime.now().toUtc() : current.uploadedAt,
    );
  }

  @override
  Future<void> setStatus(String callId, RecordingUploadStatus status) async {
    final current = records[callId];
    if (current == null) return;
    records[callId] = current.copyWith(status: status);
  }

  @override
  Future<List<CallRecording>> pending() async => records.values
      .where((r) => r.status == RecordingUploadStatus.pending)
      .toList();

  @override
  Future<void> delete(String callId) async {
    records.remove(callId);
    bytes.remove(callId);
  }

  @override
  Future<void> enforceRetention({int maxRecordings = 20}) async {
    final uploaded = records.values
        .where((r) => r.status == RecordingUploadStatus.uploaded)
        .toList()
      ..sort((a, b) => b.createdAt.compareTo(a.createdAt));
    for (final recording in uploaded.skip(maxRecordings)) {
      await delete(recording.callId);
    }
  }
}

/// Records ingest requests; can fail to simulate a dropped network.
class FakeAudioIngestApi implements AudioIngestApi {
  final List<({String callId, int? start, int? total, int length})> calls =
      <({String callId, int? start, int? total, int length})>[];
  int failRemaining = 0;

  /// Offsets the server reports; defaults to start + length.
  int? forcedOffset;

  @override
  Future<AudioIngestResult> upload({
    required String callId,
    required List<int> bytes,
    int? start,
    int? total,
    String? contentType,
    int? durationSec,
  }) async {
    if (failRemaining > 0) {
      failRemaining--;
      throw const ApiException(ApiErrorKind.network, 'offline');
    }
    calls.add((callId: callId, start: start, total: total, length: bytes.length));
    final offset = forcedOffset ?? (start ?? 0) + bytes.length;
    final boundary = total ?? offset;
    return AudioIngestResult(offset: offset, complete: offset >= boundary);
  }
}

/// Collects live frames; can fail to simulate a socket drop.
class FakeLiveAudioPort implements LiveAudioPort {
  final List<String> connected = <String>[];
  final List<int> frames = <int>[];
  bool down = false;
  int closes = 0;

  @override
  Future<void> connect(String callId) async {
    if (down) throw const ApiException(ApiErrorKind.network, 'offline');
    connected.add(callId);
  }

  @override
  Future<void> send(List<int> frame) async {
    if (down) throw const ApiException(ApiErrorKind.network, 'offline');
    frames.addAll(frame);
  }

  @override
  Future<void> close() async {
    closes++;
  }
}

/// Controllable [ScheduleApi]: returns canned summary/calendar/reminder/draft
/// data and records calls. `error` fails every method; [deleteStatus] simulates
/// the not-yet-implemented calendar delete (404/405).
class FakeScheduleApi implements ScheduleApi {
  FakeScheduleApi({
    CallSummary? summary,
    CalendarEvent? event,
    MessageDraft? draft,
    List<Reminder>? storedReminders,
    this.icsContent = 'BEGIN:VCALENDAR\r\nEND:VCALENDAR',
    this.error,
    this.deleteStatus,
  })  : summary = summary ?? testCallSummary(),
        event = event ?? testCalendarEvent(),
        draft = draft ?? testMessageDraft(),
        storedReminders = storedReminders ?? <Reminder>[];

  CallSummary summary;
  CalendarEvent event;
  MessageDraft draft;
  List<Reminder> storedReminders;
  String icsContent;
  ApiException? error;

  /// When set, [deleteCalendarEvent] throws with this status (404/405).
  int? deleteStatus;

  int summaryCalls = 0;
  int calendarCalls = 0;
  int icsCalls = 0;
  int deleteCalls = 0;
  int reminderCalls = 0;
  int listReminderCalls = 0;
  int cancelCalls = 0;
  int draftCalls = 0;
  DateTime? lastRemindAt;
  ReminderChannel? lastChannel;

  int _reminderIdSeq = 0;

  void _maybeThrow() {
    final failure = error;
    if (failure != null) throw failure;
  }

  @override
  Future<CallSummary> callSummary(String callId) async {
    summaryCalls++;
    _maybeThrow();
    return summary;
  }

  @override
  Future<CalendarEvent> createCalendarEvent(String taskId) async {
    calendarCalls++;
    _maybeThrow();
    return event;
  }

  @override
  Future<String> ics(String taskId) async {
    icsCalls++;
    _maybeThrow();
    return icsContent;
  }

  @override
  Future<void> deleteCalendarEvent(String taskId) async {
    deleteCalls++;
    final status = deleteStatus;
    if (status != null) {
      throw ApiException(
        ApiErrorKind.notFound,
        'Calendar delete not available',
        statusCode: status,
      );
    }
    _maybeThrow();
  }

  @override
  Future<Reminder> createReminder(
    String taskId, {
    required DateTime remindAt,
    ReminderChannel channel = ReminderChannel.push,
  }) async {
    reminderCalls++;
    _maybeThrow();
    lastRemindAt = remindAt;
    lastChannel = channel;
    final reminder = testReminder(
      id: 'rem-${++_reminderIdSeq}',
      taskId: taskId,
      remindAt: remindAt,
      channel: channel,
    );
    storedReminders = <Reminder>[...storedReminders, reminder];
    return reminder;
  }

  @override
  Future<List<Reminder>> reminders(String taskId) async {
    listReminderCalls++;
    _maybeThrow();
    return storedReminders.where((r) => r.taskId == taskId).toList();
  }

  @override
  Future<Reminder> cancelReminder(String reminderId) async {
    cancelCalls++;
    _maybeThrow();
    final current = storedReminders.firstWhere(
      (r) => r.id == reminderId,
      orElse: () => testReminder(id: reminderId),
    );
    final canceled = Reminder(
      id: current.id,
      taskId: current.taskId,
      remindAt: current.remindAt,
      channel: current.channel,
      status: ReminderStatus.canceled,
    );
    storedReminders = <Reminder>[
      for (final reminder in storedReminders)
        if (reminder.id == reminderId) canceled else reminder,
    ];
    return canceled;
  }

  @override
  Future<MessageDraft> draftMessage(String taskId) async {
    draftCalls++;
    _maybeThrow();
    return draft;
  }
}
