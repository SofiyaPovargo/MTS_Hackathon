import 'dart:async';
import 'dart:io';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite/sqflite.dart';

import '../core/config.dart';
import '../domain/call.dart';
import '../domain/consent.dart';
import '../domain/models.dart';
import '../domain/ports.dart';
import '../domain/schedule.dart';
import '../infrastructure/api/agreement_api.dart';
import '../infrastructure/api/api_client.dart';
import '../infrastructure/api/audio_ingest_api.dart';
import '../infrastructure/api/auth_api.dart';
import '../infrastructure/api/board_api.dart';
import '../infrastructure/api/call_api.dart';
import '../infrastructure/api/consent_api.dart';
import '../infrastructure/api/manager_api.dart';
import '../infrastructure/api/schedule_api.dart';
import '../infrastructure/api/sync_api.dart';
import '../infrastructure/audio/file_audio_recording_store.dart';
import '../infrastructure/db/app_database.dart';
import '../infrastructure/db/consent_store.dart';
import '../infrastructure/db/local_board_store.dart';
import '../infrastructure/db/outbox_store.dart';
import '../infrastructure/db/session_store.dart';
import '../infrastructure/db/sync_state_store.dart';
import '../infrastructure/repositories/contacts_source.dart';
import '../infrastructure/sync/sync_engine.dart';
import '../infrastructure/voice/mock_voice_provider.dart';
import '../infrastructure/ws/ws_call_events.dart';
import '../infrastructure/ws/ws_live_audio.dart';
import 'auth_controller.dart';
import 'board_controller.dart';
import 'call_controller.dart';
import 'call_history_controller.dart';
import 'consent_controller.dart';
import 'contacts_controller.dart';
import 'manager_controller.dart';
import 'recording_service.dart';
import 'task_actions_controller.dart';

/// Application wiring. Tests override these providers with fakes; feature code
/// never constructs infrastructure directly.

final Provider<AppConfig> appConfigProvider =
    Provider<AppConfig>((ref) => AppConfig());

final Provider<AppDatabase> databaseProvider =
    Provider<AppDatabase>((ref) => AppDatabase());

// -- local stores ------------------------------------------------------------

final Provider<SessionStore> sessionStoreProvider =
    Provider<SessionStore>((ref) => SqliteSessionStore(ref.watch(databaseProvider)));

final Provider<LocalBoardStore> localBoardStoreProvider = Provider<LocalBoardStore>(
  (ref) => SqliteLocalBoardStore(ref.watch(databaseProvider)),
);

final Provider<OutboxStore> outboxStoreProvider =
    Provider<OutboxStore>((ref) => SqliteOutboxStore(ref.watch(databaseProvider)));

final Provider<SyncStateStore> syncStateStoreProvider = Provider<SyncStateStore>(
  (ref) => SqliteSyncStateStore(ref.watch(databaseProvider)),
);

final Provider<ConsentStore> consentStoreProvider =
    Provider<ConsentStore>((ref) => SqliteConsentStore(ref.watch(databaseProvider)));

/// Local cache of the user's own recent recordings plus their upload state
/// (plan.md §8 — a bounded cache, not a second system of record).
final Provider<AudioRecordingStore> audioRecordingStoreProvider =
    Provider<AudioRecordingStore>((ref) {
  final database = ref.watch(databaseProvider);
  return FileAudioRecordingStore(
    database,
    resolveDirectory: () async {
      final base = await databaseFactory.getDatabasesPath();
      final directory = Directory(p.join(base, 'audio'));
      if (!await directory.exists()) await directory.create(recursive: true);
      return directory.path;
    },
  );
});

// -- API clients -------------------------------------------------------------

final Provider<ApiClient> apiClientProvider = Provider<ApiClient>((ref) {
  return ApiClient(
    baseUrl: ref.watch(appConfigProvider).baseUrl,
    accessToken: () async => (await ref.read(sessionStoreProvider).read())?.accessToken,
    // Read lazily to break the build-time cycle with [authApiProvider].
    refreshToken: () async =>
        (await ref.read(authApiProvider).refreshSession())?.accessToken,
  );
});

final Provider<AuthApi> authApiProvider = Provider<AuthApi>(
  (ref) => HttpAuthApi(
    client: ref.watch(apiClientProvider),
    sessionStore: ref.watch(sessionStoreProvider),
  ),
);

final Provider<BoardApi> boardApiProvider =
    Provider<BoardApi>((ref) => HttpBoardApi(client: ref.watch(apiClientProvider)));

final Provider<ManagerApi> managerApiProvider =
    Provider<ManagerApi>((ref) => HttpManagerApi(client: ref.watch(apiClientProvider)));

final Provider<SyncApi> syncApiProvider =
    Provider<SyncApi>((ref) => HttpSyncApi(client: ref.watch(apiClientProvider)));

final Provider<CallApi> callApiProvider =
    Provider<CallApi>((ref) => HttpCallApi(client: ref.watch(apiClientProvider)));

final Provider<ConsentApi> consentApiProvider =
    Provider<ConsentApi>((ref) => HttpConsentApi(client: ref.watch(apiClientProvider)));

final Provider<AgreementApi> agreementApiProvider = Provider<AgreementApi>(
  (ref) => HttpAgreementApi(client: ref.watch(apiClientProvider)),
);

/// Call summary / calendar / reminders / client-message drafts (plan.md §9).
final Provider<ScheduleApi> scheduleApiProvider =
    Provider<ScheduleApi>((ref) => HttpScheduleApi(client: ref.watch(apiClientProvider)));

/// Resumable ingest of recorded audio (`POST /calls/{id}/audio`).
final Provider<AudioIngestApi> audioIngestApiProvider = Provider<AudioIngestApi>(
  (ref) => HttpAudioIngestApi(client: ref.watch(apiClientProvider)),
);

/// Live audio frames (`/api/ws/calls/{call_id}/audio`); best-effort.
final Provider<LiveAudioPort> liveAudioProvider = Provider<LiveAudioPort>(
  (ref) => WebSocketLiveAudio(
    baseUrl: ref.watch(appConfigProvider).baseUrl,
    accessToken: () async =>
        (await ref.read(sessionStoreProvider).read())?.accessToken,
  ),
);

/// Live per-call events (`/api/ws/calls/{call_id}`). The access token comes from
/// the session store, exactly like the REST clients.
final Provider<CallEventsPort> callEventsProvider = Provider<CallEventsPort>(
  (ref) => WebSocketCallEvents(
    baseUrl: ref.watch(appConfigProvider).baseUrl,
    accessToken: () async =>
        (await ref.read(sessionStoreProvider).read())?.accessToken,
  ),
);

// -- voice provider ----------------------------------------------------------

/// The concrete mock is exposed so the demo can synthesize an incoming call.
/// Real adapters (CallKit/Telecom/Exolve SDK) replace it behind the port.
final Provider<MockVoiceCallProvider> mockVoiceCallProvider =
    Provider<MockVoiceCallProvider>((ref) => MockVoiceCallProvider());

final Provider<VoiceCallProvider> voiceCallProviderProvider =
    Provider<VoiceCallProvider>((ref) => ref.watch(mockVoiceCallProvider));

/// Stage 6 recording coordinator (local buffer + live stream + resumable upload).
final Provider<CallRecordingService> recordingServiceProvider =
    Provider<CallRecordingService>(
  (ref) => CallRecordingService(
    recorder: ref.watch(voiceCallProviderProvider),
    store: ref.watch(audioRecordingStoreProvider),
    ingest: ref.watch(audioIngestApiProvider),
    live: ref.watch(liveAudioProvider),
  ),
);

/// Retries recordings that were buffered while offline as soon as a session
/// exists (app start / next login). Read once by the authenticated area.
final Provider<void> recordingRetryProvider = Provider<void>((ref) {
  ref.listen<AsyncValue<AuthSession?>>(
    authControllerProvider,
    (_, next) {
      if (next.valueOrNull != null) {
        unawaited(ref.read(recordingServiceProvider).uploadPending());
      }
    },
    fireImmediately: true,
  );
});

final Provider<ContactsSource> contactsSourceProvider =
    Provider<ContactsSource>((ref) => const DeviceContactsSource());

final Provider<SyncEngine> syncEngineProvider = Provider<SyncEngine>(
  (ref) => SyncEngine(
    syncApi: ref.watch(syncApiProvider),
    board: ref.watch(localBoardStoreProvider),
    outbox: ref.watch(outboxStoreProvider),
    state: ref.watch(syncStateStoreProvider),
  ),
);

// -- controllers -------------------------------------------------------------

final AsyncNotifierProvider<AuthController, AuthSession?> authControllerProvider =
    AsyncNotifierProvider<AuthController, AuthSession?>(AuthController.new);

final AsyncNotifierProvider<BoardController, List<TaskItem>> boardControllerProvider =
    AsyncNotifierProvider<BoardController, List<TaskItem>>(BoardController.new);

/// Manager board (team tasks, analytics, members). Only read for a manager; the
/// server enforces the role and team membership.
final AsyncNotifierProvider<ManagerController, ManagerBoard> managerControllerProvider =
    AsyncNotifierProvider<ManagerController, ManagerBoard>(ManagerController.new);

final AsyncNotifierProvider<ContactsController, ContactsState> contactsControllerProvider =
    AsyncNotifierProvider<ContactsController, ContactsState>(ContactsController.new);

/// The app user's recording/AI consent (local-first cache + server write-through).
final AsyncNotifierProvider<ConsentController, AppConsent> consentControllerProvider =
    AsyncNotifierProvider<ConsentController, AppConsent>(ConsentController.new);

/// Local call session; `null` means no call is in progress. The call overlay
/// watches this provider.
final NotifierProvider<CallController, CallState?> callControllerProvider =
    NotifierProvider<CallController, CallState?>(CallController.new);

/// Calendar / reminder / client-draft actions on the personal board (plan.md §9).
final NotifierProvider<TaskActionsController, TaskActionsState>
    taskActionsControllerProvider =
    NotifierProvider<TaskActionsController, TaskActionsState>(
  TaskActionsController.new,
);

/// The user's own call history (`GET /calls`); see [CallHistoryController].
final AsyncNotifierProvider<CallHistoryController, List<Call>>
    callHistoryProvider =
    AsyncNotifierProvider<CallHistoryController, List<Call>>(
  CallHistoryController.new,
);

/// A single call (`GET /calls/{id}`), used by the call detail screen.
final FutureProviderFamily<Call, String> callDetailProvider =
    FutureProvider.family<Call, String>(
  (ref, callId) => ref.watch(callApiProvider).getCall(callId),
);

/// A call's итог (`GET /calls/{id}/summary`), shared by the history detail and
/// the live card.
final FutureProviderFamily<CallSummary, String> callSummaryProvider =
    FutureProvider.family<CallSummary, String>(
  (ref, callId) => ref.watch(scheduleApiProvider).callSummary(callId),
);
