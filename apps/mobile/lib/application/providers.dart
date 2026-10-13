import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/config.dart';
import '../domain/models.dart';
import '../domain/ports.dart';
import '../infrastructure/api/api_client.dart';
import '../infrastructure/api/auth_api.dart';
import '../infrastructure/api/board_api.dart';
import '../infrastructure/api/sync_api.dart';
import '../infrastructure/db/app_database.dart';
import '../infrastructure/db/local_board_store.dart';
import '../infrastructure/db/outbox_store.dart';
import '../infrastructure/db/session_store.dart';
import '../infrastructure/db/sync_state_store.dart';
import '../infrastructure/repositories/contacts_source.dart';
import '../infrastructure/sync/sync_engine.dart';
import 'auth_controller.dart';
import 'board_controller.dart';
import 'contacts_controller.dart';

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

final Provider<SyncApi> syncApiProvider =
    Provider<SyncApi>((ref) => HttpSyncApi(client: ref.watch(apiClientProvider)));

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

final AsyncNotifierProvider<ContactsController, ContactsState> contactsControllerProvider =
    AsyncNotifierProvider<ContactsController, ContactsState>(ContactsController.new);
