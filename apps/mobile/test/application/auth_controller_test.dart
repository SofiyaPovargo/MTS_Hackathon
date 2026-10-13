import 'package:agreement_capture/application/providers.dart';
import 'package:agreement_capture/infrastructure/api/api_exception.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fakes.dart';

void main() {
  test('restores a stored session on build', () async {
    final store = InMemorySessionStore()..session = testSession();
    final container = ProviderContainer(
      overrides: <Override>[
        sessionStoreProvider.overrideWithValue(store),
        authApiProvider.overrideWithValue(FakeAuthApi(session: testSession())),
      ],
    );
    addTearDown(container.dispose);

    final session = await container.read(authControllerProvider.future);
    expect(session?.accessToken, 'access-1');
  });

  test('starts unauthenticated without a stored session', () async {
    final container = ProviderContainer(
      overrides: <Override>[
        sessionStoreProvider.overrideWithValue(InMemorySessionStore()),
        authApiProvider.overrideWithValue(FakeAuthApi(session: testSession())),
      ],
    );
    addTearDown(container.dispose);

    expect(await container.read(authControllerProvider.future), isNull);
  });

  test('login persists the session and updates the state', () async {
    final store = InMemorySessionStore();
    final container = ProviderContainer(
      overrides: <Override>[
        sessionStoreProvider.overrideWithValue(store),
        authApiProvider.overrideWithValue(
          FakeAuthApi(
            session: testSession(accessToken: 'new-token'),
            sessionStore: store,
          ),
        ),
      ],
    );
    addTearDown(container.dispose);
    await container.read(authControllerProvider.future);

    await container
        .read(authControllerProvider.notifier)
        .login(phone: '+79000000002', otp: '1234');

    expect(container.read(authControllerProvider).value?.accessToken, 'new-token');
    expect(store.session?.accessToken, 'new-token');
  });

  test('login failure surfaces an error state', () async {
    final container = ProviderContainer(
      overrides: <Override>[
        sessionStoreProvider.overrideWithValue(InMemorySessionStore()),
        authApiProvider.overrideWithValue(
          FakeAuthApi(error: const ApiException(ApiErrorKind.unauthorized, 'Неверный код')),
        ),
      ],
    );
    addTearDown(container.dispose);
    await container.read(authControllerProvider.future);

    await container
        .read(authControllerProvider.notifier)
        .login(phone: '+79000000002', otp: '0000');

    final state = container.read(authControllerProvider);
    expect(state.hasError, isTrue);
    expect((state.error! as ApiException).message, 'Неверный код');
  });

  test('logout clears the stored session', () async {
    final store = InMemorySessionStore()..session = testSession();
    final api = FakeAuthApi(session: testSession(), sessionStore: store);
    final container = ProviderContainer(
      overrides: <Override>[
        sessionStoreProvider.overrideWithValue(store),
        authApiProvider.overrideWithValue(api),
      ],
    );
    addTearDown(container.dispose);
    await container.read(authControllerProvider.future);

    await container.read(authControllerProvider.notifier).logout();

    expect(container.read(authControllerProvider).value, isNull);
    expect(store.session, isNull);
    expect(api.logoutRequests, 1);
  });
}
