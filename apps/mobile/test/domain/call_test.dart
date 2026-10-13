import 'package:agreement_capture/domain/call.dart';
import 'package:agreement_capture/domain/enums.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('call state machine mirrors the backend', () {
    test('allows the documented transitions', () {
      expect(
        canTransitionCall(CallLifecycleStatus.incoming, CallLifecycleStatus.ringing),
        isTrue,
      );
      expect(
        canTransitionCall(CallLifecycleStatus.ringing, CallLifecycleStatus.answered),
        isTrue,
      );
      expect(
        canTransitionCall(CallLifecycleStatus.answered, CallLifecycleStatus.consentNotice),
        isTrue,
      );
      expect(
        canTransitionCall(CallLifecycleStatus.answered, CallLifecycleStatus.inProgress),
        isTrue,
      );
      expect(
        canTransitionCall(CallLifecycleStatus.consentResult, CallLifecycleStatus.recording),
        isTrue,
      );
      expect(
        canTransitionCall(CallLifecycleStatus.recording, CallLifecycleStatus.analyzing),
        isTrue,
      );
      expect(
        canTransitionCall(CallLifecycleStatus.analyzing, CallLifecycleStatus.inProgress),
        isTrue,
      );
      expect(
        canTransitionCall(CallLifecycleStatus.inProgress, CallLifecycleStatus.completed),
        isTrue,
      );
    });

    test('rejects invalid transitions', () {
      expect(
        canTransitionCall(CallLifecycleStatus.incoming, CallLifecycleStatus.completed),
        isFalse,
      );
      expect(
        canTransitionCall(CallLifecycleStatus.ringing, CallLifecycleStatus.completed),
        isFalse,
      );
      expect(
        canTransitionCall(CallLifecycleStatus.inProgress, CallLifecycleStatus.ringing),
        isFalse,
      );
      expect(
        canTransitionCall(CallLifecycleStatus.completed, CallLifecycleStatus.inProgress),
        isFalse,
      );
    });

    test('terminal states have no outgoing transitions', () {
      const terminals = <CallLifecycleStatus>[
        CallLifecycleStatus.completed,
        CallLifecycleStatus.missed,
        CallLifecycleStatus.failed,
      ];
      for (final status in terminals) {
        expect(callTransitions[status], isEmpty);
        expect(status.isTerminal, isTrue);
      }
      expect(CallLifecycleStatus.inProgress.isTerminal, isFalse);
      expect(CallLifecycleStatus.incoming.isTerminal, isFalse);
    });
  });

  group('CallState', () {
    test('displayName falls back to the number', () {
      const state = CallState(
        status: CallLifecycleStatus.ringing,
        direction: CallDirection.outbound,
        phone: '+79000000002',
      );
      expect(state.displayName, '+79000000002');
      expect(state.isIncoming, isFalse);
    });

    test('isConnected covers the connected statuses only', () {
      CallState withStatus(CallLifecycleStatus status) => CallState(
            status: status,
            direction: CallDirection.inbound,
            phone: '+7',
          );
      expect(withStatus(CallLifecycleStatus.answered).isConnected, isTrue);
      expect(withStatus(CallLifecycleStatus.inProgress).isConnected, isTrue);
      expect(withStatus(CallLifecycleStatus.ringing).isConnected, isFalse);
      expect(withStatus(CallLifecycleStatus.completed).isConnected, isFalse);
    });
  });

  test('wire values round-trip and degrade safely', () {
    expect(CallLifecycleStatus.fromWire('consent_notice'), CallLifecycleStatus.consentNotice);
    expect(CallSignalKind.fromWire('dropped'), CallSignalKind.dropped);
    expect(CallLifecycleStatus.fromWire('unknown'), CallLifecycleStatus.failed);
  });
}
