import 'package:agreement_capture/domain/enums.dart';
import 'package:agreement_capture/domain/models.dart';
import 'package:agreement_capture/domain/ports.dart';
import 'package:agreement_capture/domain/sync_models.dart';
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
