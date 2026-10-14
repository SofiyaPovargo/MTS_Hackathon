import 'dart:async';

import '../../domain/call.dart';
import '../../domain/enums.dart';
import '../../domain/ports.dart';

/// In-memory [VoiceCallProvider] used for local development and tests.
///
/// It never touches a network or a platform channel. On a real device the
/// native/MTS Exolve adapter replaces it through DI (see `providers.dart`).
///
/// By default it answers outgoing calls after [answerDelay] so the call flow is
/// demoable without the SDK; tests construct it with `simulateAnswer: false`
/// and drive signals through [emit].
class MockVoiceCallProvider implements VoiceCallProvider, IncomingCallSimulator {
  MockVoiceCallProvider({
    this.microphoneGranted = true,
    this.simulateAnswer = true,
    this.answerDelay = const Duration(seconds: 2),
  });

  final bool microphoneGranted;
  final bool simulateAnswer;
  final Duration answerDelay;

  final StreamController<CallSignal> _controller =
      StreamController<CallSignal>.broadcast();
  int _sequence = 0;

  @override
  Stream<CallSignal> get signals => _controller.stream;

  @override
  Future<bool> ensureMicrophonePermission() async => microphoneGranted;

  @override
  Future<String> dial(String phone, {String? name}) async {
    final id = _nextId();
    emit(CallSignal(
      kind: CallSignalKind.ringing,
      externalId: id,
      phone: phone,
      name: name,
    ));
    if (simulateAnswer) {
      Timer(answerDelay, () {
        emit(CallSignal(
          kind: CallSignalKind.answered,
          externalId: id,
          phone: phone,
          name: name,
        ));
      });
    }
    return id;
  }

  @override
  Future<void> answer(String externalId) async {
    emit(CallSignal(kind: CallSignalKind.answered, externalId: externalId));
  }

  @override
  Future<void> decline(String externalId) async {
    emit(CallSignal(kind: CallSignalKind.missed, externalId: externalId));
  }

  @override
  Future<void> hangup(String externalId) async {
    emit(CallSignal(kind: CallSignalKind.ended, externalId: externalId));
  }

  @override
  Future<void> setMuted(String externalId, bool muted) async {}

  /// Emits synthetic 8 kHz mono PCM16 chunks (200 ms of silence) so the Stage 6
  /// pipeline — local buffer, live WS stream, resumable upload — is demoable
  /// without the native SDK. Cancelling the subscription stops capture.
  /// Emits synthetic 8 kHz mono PCM16 chunks (200 ms of silence) so the Stage 6
  /// pipeline — local buffer, live WS stream, resumable upload — is demoable
  /// without the native SDK. Cancelling the subscription stops capture.
  @override
  Stream<List<int>> openMediaStream(String externalId) =>
      Stream<List<int>>.periodic(const Duration(milliseconds: 200))
          .map((_) => List<int>.filled(3200, 0));

  @override
  void simulateIncoming({required String phone, String? name}) {
    emit(CallSignal(
      kind: CallSignalKind.incoming,
      externalId: _nextId(),
      phone: phone,
      name: name,
    ));
  }

  /// Pushes a provider signal (tests and the demo driver).
  void emit(CallSignal signal) {
    if (!_controller.isClosed) _controller.add(signal);
  }

  String _nextId() => 'mock-${++_sequence}';

  Future<void> dispose() => _controller.close();
}
