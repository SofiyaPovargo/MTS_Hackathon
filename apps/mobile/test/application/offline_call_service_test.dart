import 'package:agreement_capture/application/offline_call_service.dart';
import 'package:agreement_capture/domain/enums.dart';
import 'package:agreement_capture/infrastructure/api/api_exception.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fakes.dart';

void main() {
  test('flush creates the call idempotently and declares its recording',
      () async {
    final store = InMemoryPendingCallStore();
    final api = FakeCallApi();
    final service = OfflineCallService(store: store, api: api);
    await store.save(
      testPendingCall(
        callId: 'call-1',
        answeredAt: DateTime.utc(2026, 10, 14, 9, 1),
        endedAt: DateTime.utc(2026, 10, 14, 9, 5),
      ),
    );

    expect(await service.flush(), 1);

    // The client id was sent so a retry cannot duplicate the call.
    expect(api.createdWithId, <String>['call-1']);
    expect(api.created.single.id, 'call-1');
    final declared = api.declared.single;
    expect(declared.callId, 'call-1');
    expect(declared.recordConsent, isTrue);
    expect(declared.participantConsent, ConsentStatus.granted);
    expect(declared.endedAt, DateTime.utc(2026, 10, 14, 9, 5));
    expect(store.calls, isEmpty);
  });

  test('still offline keeps the entry queued and reports nothing accepted',
      () async {
    final store = InMemoryPendingCallStore();
    final api = FakeCallApi(
      error: const ApiException(ApiErrorKind.network, 'offline'),
    );
    final service = OfflineCallService(store: store, api: api);
    await store.save(testPendingCall(callId: 'call-1'));

    expect(await service.flush(), 0);
    expect(store.calls, hasLength(1));
    expect(api.declared, isEmpty);
  });

  test('a failed declaration keeps the entry for a later idempotent retry',
      () async {
    final store = InMemoryPendingCallStore();
    final api = FakeCallApi(
      declareError: const ApiException(ApiErrorKind.network, 'offline'),
    );
    final service = OfflineCallService(store: store, api: api);
    await store.save(testPendingCall(callId: 'call-1'));

    // Create succeeds, the declaration fails: the entry must survive so the
    // retry replays both (create is idempotent).
    expect(await service.flush(), 0);
    expect(store.calls, hasLength(1));

    api.declareError = null;
    expect(await service.flush(), 1);
    expect(store.calls, isEmpty);
    expect(api.declared.single.callId, 'call-1');
  });

  test('a refused counterparty consent is pushed as denied', () async {
    final store = InMemoryPendingCallStore();
    final api = FakeCallApi();
    final service = OfflineCallService(store: store, api: api);
    await store.save(
      testPendingCall(
        callId: 'call-1',
        participantConsent: ConsentStatus.denied,
      ),
    );

    await service.flush();

    expect(api.declared.single.participantConsent, ConsentStatus.denied);
  });

  test('flush pushes every queued call in start order', () async {
    final store = InMemoryPendingCallStore();
    final api = FakeCallApi();
    final service = OfflineCallService(store: store, api: api);
    await store.save(
      testPendingCall(
        callId: 'call-2',
        startedAt: DateTime.utc(2026, 10, 14, 10),
      ),
    );
    await store.save(
      testPendingCall(
        callId: 'call-1',
        startedAt: DateTime.utc(2026, 10, 14, 9),
      ),
    );

    expect(await service.flush(), 2);
    expect(api.createdWithId, <String>['call-1', 'call-2']);
    expect(store.calls, isEmpty);
  });

  test('register replaces an existing entry with the same call id', () async {
    final store = InMemoryPendingCallStore();
    final service = OfflineCallService(store: store, api: FakeCallApi());

    await service.register(testPendingCall(callId: 'call-1'));
    await service.register(
      testPendingCall(callId: 'call-1', calleePhone: '+79000000009'),
    );

    expect(store.calls, hasLength(1));
    expect(store.calls.values.single.calleePhone, '+79000000009');
  });
}
