import 'package:agreement_capture/application/providers.dart';
import 'package:agreement_capture/domain/call.dart';
import 'package:agreement_capture/domain/consent.dart';
import 'package:agreement_capture/domain/enums.dart';
import 'package:agreement_capture/domain/models.dart';
import 'package:agreement_capture/domain/ws_event.dart';
import 'package:agreement_capture/ui/screens/call_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fakes.dart';

/// Mirrors [CallOverlay]: watches the controller and renders the call screen on
/// top, so the live card rebuilds when transcript/agreements arrive.
class Overlay extends ConsumerWidget {
  const Overlay({required this.child, super.key});

  final Widget child;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final call = ref.watch(callControllerProvider);
    return Stack(
      children: <Widget>[
        child,
        if (call != null) Positioned.fill(child: CallScreen(call: call)),
      ],
    );
  }
}

typedef Scope = ({
  ProviderContainer container,
  FakeVoiceCallProvider voice,
  FakeAgreementApi agreementApi,
  FakeCallEventsPort events,
});

Scope setup({AppConsent consent = AppConsent.undecided}) {
  final voice = FakeVoiceCallProvider();
  final agreementApi = FakeAgreementApi();
  final events = FakeCallEventsPort();
  final container = ProviderContainer(
    overrides: <Override>[
      voiceCallProviderProvider.overrideWithValue(voice),
      callApiProvider.overrideWithValue(FakeCallApi()),
      consentStoreProvider.overrideWithValue(InMemoryConsentStore(consent)),
      consentApiProvider.overrideWithValue(FakeConsentApi()),
      callEventsProvider.overrideWithValue(events),
      agreementApiProvider.overrideWithValue(agreementApi),
    ],
  );
  return (
    container: container,
    voice: voice,
    agreementApi: agreementApi,
    events: events,
  );
}

Future<void> pumpOverlay(WidgetTester tester, Scope scope) async {
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: scope.container,
      child: const MaterialApp(
        home: Overlay(child: Scaffold(body: SizedBox.expand())),
      ),
    ),
  );
}

const testCallId = '55555555-5555-5555-5555-555555555555';

void main() {
  testWidgets('no-consent path offers manual entry and shows the card',
      (tester) async {
    final scope = setup();
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(callControllerProvider.notifier);

    await pumpOverlay(tester, scope);
    await controller.startOutgoing('+79000000002');
    scope.voice.emit(const CallSignal(kind: CallSignalKind.answered));
    await tester.pumpAndSettle();

    expect(find.text('Добавить договорённость вручную'), findsOneWidget);

    await controller.createManualAgreement(
      const AgreementPatch(title: 'Встреча в пятницу', type: 'meeting'),
    );
    await tester.pumpAndSettle();

    expect(find.text('Встреча в пятницу'), findsOneWidget);
    expect(find.text('meeting'), findsOneWidget);
    expect(find.text('Подтвердить'), findsOneWidget);
    expect(find.text('Отклонить'), findsOneWidget);
  });

  testWidgets('confirm flips the card to a final confirmed state',
      (tester) async {
    final scope = setup();
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(callControllerProvider.notifier);

    await pumpOverlay(tester, scope);
    await controller.startOutgoing('+79000000002');
    scope.voice.emit(const CallSignal(kind: CallSignalKind.answered));
    await tester.pumpAndSettle();

    await controller.createManualAgreement(
      const AgreementPatch(title: 'Оплатить счёт', type: 'payment'),
    );
    await tester.pumpAndSettle();
    expect(find.text('Подтвердить'), findsOneWidget);

    await tester.tap(find.text('Подтвердить'));
    await tester.pumpAndSettle();

    // The local card reflects the confirmed server state (task was created).
    expect(scope.agreementApi.stored['created-1']?.status, AgreementStatus.confirmed);
    expect(find.text('Подтверждено'), findsOneWidget);
    expect(find.text('Подтвердить'), findsNothing);
    expect(find.text('Отклонить'), findsNothing);
  });

  testWidgets('live transcript and agreement_detected render on the card',
      (tester) async {
    final scope = setup(
      consent: const AppConsent(status: ConsentStatus.granted, synced: true),
    );
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(callControllerProvider.notifier);

    await pumpOverlay(tester, scope);
    await controller.startOutgoing('+79000000002');
    scope.voice.emit(const CallSignal(kind: CallSignalKind.answered));
    await tester.pumpAndSettle();
    expect(scope.events.connected, <String>[testCallId]);

    scope.events.emit(const CallEvent(
      version: 1,
      kind: CallEventKind.partialTranscript,
      callId: testCallId,
      payload: <String, dynamic>{
        'speaker': 'user',
        'text': 'оплачу до пятницы',
        'start': 12.5,
        'end': 18.0,
      },
    ));
    scope.events.emit(const CallEvent(
      version: 1,
      kind: CallEventKind.agreementDetected,
      callId: testCallId,
      payload: <String, dynamic>{
        'id': 'agr-live-1',
        'call_id': testCallId,
        'type': 'payment',
        'title': 'Оплатить счёт',
        'owner': 'user',
        'due_date': null,
        'due_time': null,
        'source_quote': 'оплачу до пятницы',
        'audio_start': 12.5,
        'audio_end': 18.0,
        'confidence': 0.9,
        'status': 'detected',
      },
    ));
    await tester.pumpAndSettle();

    expect(find.text('Оплатить счёт'), findsOneWidget);
    expect(find.textContaining('оплачу до пятницы'), findsWidgets);
    expect(find.text('Подтвердить'), findsOneWidget);

    // A call_ended event completes the call; the card remains as a recap.
    scope.events.emit(const CallEvent(
      version: 1,
      kind: CallEventKind.callEnded,
      callId: testCallId,
    ));
    await tester.pumpAndSettle();
    expect(find.text('Звонок завершён'), findsOneWidget);
    expect(find.text('Оплатить счёт'), findsOneWidget);
  });

  testWidgets('edit opens the dialog and saves the new title', (tester) async {
    final scope = setup();
    addTearDown(scope.container.dispose);
    final controller = scope.container.read(callControllerProvider.notifier);

    await pumpOverlay(tester, scope);
    await controller.startOutgoing('+79000000002');
    scope.voice.emit(const CallSignal(kind: CallSignalKind.answered));
    await tester.pumpAndSettle();

    await controller.createManualAgreement(
      const AgreementPatch(title: 'Оплатить счёт', type: 'payment'),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('Изменить'));
    await tester.pumpAndSettle();
    expect(find.text('Изменить договорённость'), findsOneWidget);

    await tester.enterText(find.byType(TextField).first, 'Оплатить до 20-го');
    await tester.tap(find.text('Сохранить'));
    await tester.pumpAndSettle();

    expect(find.text('Оплатить до 20-го'), findsOneWidget);
    expect(scope.agreementApi.stored['created-1']?.title, 'Оплатить до 20-го');
  });
}