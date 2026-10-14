import 'dart:async';

import 'package:agreement_capture/domain/call.dart';
import 'package:agreement_capture/domain/consent.dart';
import 'package:agreement_capture/domain/enums.dart';
import 'package:agreement_capture/domain/models.dart';
import 'package:agreement_capture/domain/ports.dart';
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
  int version = 1,
}) {
  return TaskItem(
    id: id,
    title: title,
    assigneeUserId: '11111111-1111-1111-1111-111111111111',
    priority: priority,
    status: status,
    dueDate: dueDate,
    version: version,
    createdAt: DateTime.utc(2026, 10),
    updatedAt: DateTime.utc(2026, 10),
  );
}

Agreement testAgreement({String id = '33333333-3333-3333-3333-333333333333', int version = 1}) {
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
  FakeBoardApi({this.tasks = const <TaskItem>[], this.agreements = const <Agreement>[]});

  List<TaskItem> tasks;
  List<Agreement> agreements;

  @override
  Future<List<TaskItem>> fetchMyTasks() async => tasks;

  @override
  Future<List<Agreement>> fetchMyAgreements() async => agreements;
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
  Future<void> writeSyncToken(String value) async => token = value.isEmpty ? null : value;

  @override
  Future<int> readRecordVersion(String entityType, String id) async =>
      versions['$entityType:$id'] ?? 0;

  @override
  Future<void> writeRecordVersion(String entityType, String id, int version) async =>
      versions['$entityType:$id'] = version;
}

/// Controllable [VoiceCallProvider]: records control calls and lets tests emit
/// provider signals explicitly (no timers, no platform channels).
class FakeVoiceCallProvider implements VoiceCallProvider, IncomingCallSimulator {
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
  Future<void> setMuted(String externalId, bool value) async => muted.add(value);

  @override
  void simulateIncoming({required String phone, String? name}) {
    emit(CallSignal(
      kind: CallSignalKind.incoming,
      externalId: 'fake-${++_sequence}',
      phone: phone,
      name: name,
    ));
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
