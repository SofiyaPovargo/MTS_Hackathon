import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../domain/call.dart';
import '../domain/enums.dart';
import '../domain/ports.dart';
import '../infrastructure/api/api_exception.dart';
import 'providers.dart';

/// Drives the local call session: outgoing dialing, incoming answer/decline,
/// lifecycle transitions and mute.
///
/// All platform-specific behavior lives behind [VoiceCallProvider]; this
/// controller only reacts to provider signals and validates every transition
/// with the mirrored state machine ([canTransitionCall]). `state == null` means
/// there is no call.
class CallController extends Notifier<CallState?> {
  VoiceCallProvider get _voice => ref.read(voiceCallProviderProvider);
  CallApi get _api => ref.read(callApiProvider);

  @override
  CallState? build() {
    final subscription = _voice.signals.listen(_onSignal);
    ref.onDispose(subscription.cancel);
    return null;
  }

  /// Places an outgoing call. Returns an error message, or `null` on success.
  Future<String?> startOutgoing(String phone, {String? name}) async {
    final normalized = phone.trim();
    if (normalized.isEmpty) return 'Введите номер';

    if (!await _voice.ensureMicrophonePermission()) {
      return 'Нет доступа к микрофону. Разрешите его в настройках приложения.';
    }

    // The server owns the call record; without it there is nothing to analyze.
    String? callId;
    try {
      final call = await _api.createCall(
        direction: CallDirection.outbound,
        calleePhone: normalized,
        contactName: name,
      );
      callId = call.id;
    } on ApiException catch (error) {
      return error.message;
    }

    final externalId = await _voice.dial(normalized, name: name);
    final consent = await ref.read(consentControllerProvider.future);
    state = CallState(
      status: CallLifecycleStatus.ringing,
      direction: CallDirection.outbound,
      phone: normalized,
      name: name,
      callId: callId,
      externalId: externalId,
      recordingEnabled: consent.recordingEnabled,
      startedAt: DateTime.now(),
    );
    return null;
  }

  /// Answers the current incoming call. Returns false when the microphone
  /// permission is denied (the UI keeps the incoming screen with a message).
  Future<bool> answerIncoming() async {
    final current = state;
    if (current == null) return false;
    if (!await _voice.ensureMicrophonePermission()) return false;
    final consent = await ref.read(consentControllerProvider.future);
    state = current.copyWith(recordingEnabled: consent.recordingEnabled);
    final externalId = current.externalId;
    if (externalId != null) {
      await _voice.answer(externalId);
    }
    return true;
  }

  /// Declines the incoming call (the record becomes `missed`).
  Future<void> declineIncoming() async {
    final current = state;
    if (current == null) return;
    final externalId = current.externalId;
    if (externalId != null) {
      await _voice.decline(externalId);
    }
    _endAs(CallLifecycleStatus.missed);
  }

  /// Ends the active call.
  Future<void> hangup() async {
    final current = state;
    if (current == null) return;
    final externalId = current.externalId;
    if (externalId != null) {
      await _voice.hangup(externalId);
    }
    // The provider also emits `ended`; applying the terminal state twice is a
    // no-op guarded by the state machine.
    _endAs(CallLifecycleStatus.completed);
  }

  Future<void> toggleMute() async {
    final current = state;
    if (current == null) return;
    final muted = !current.muted;
    final externalId = current.externalId;
    if (externalId != null) {
      await _voice.setMuted(externalId, muted);
    }
    state = current.copyWith(muted: muted);
  }

  /// Clears the terminal state so the overlay closes.
  void clear() => state = null;

  // ---- server-driven lifecycle updates ---------------------------------------
  //
  // The backend owns the consent/recording transitions (play notice, record the
  // participant result, start recording/analysis). Stage 7 (WebSocket) will
  // call these; the mock and the tests drive them today. Every transition is
  // validated by the mirrored state machine ([canTransitionCall]).

  /// The counterparty notice is being played (backend `consent_notice`).
  void markConsentNotice() => _advance(CallLifecycleStatus.consentNotice);

  /// The consent result from the backend: recording starts when granted,
  /// otherwise the call continues as an ordinary non-recorded call.
  void markConsentResult({required bool granted}) {
    _advance(CallLifecycleStatus.consentNotice);
    _advance(CallLifecycleStatus.consentResult);
    if (granted) {
      _advance(CallLifecycleStatus.recording);
    } else {
      final current = state;
      if (current != null && !current.isTerminal) {
        state =
            current.copyWith(recordingEnabled: false, participantDeclined: true);
      }
      _advance(CallLifecycleStatus.inProgress);
    }
  }

  /// Recording + media stream started, ASR begins (backend `analyzing`).
  void markAnalysisStarted() => _advance(CallLifecycleStatus.analyzing);

  /// Live analysis is running (backend `in_progress`).
  void markCallActive() => _advance(CallLifecycleStatus.inProgress);

  /// Dev-only helper: synthesize an incoming call when the provider supports it
  /// (the mock does). Feature code stays on this controller.
  void simulateIncomingCall({required String phone, String? name}) {
    final VoiceCallProvider provider = _voice;
    if (provider case final IncomingCallSimulator simulator) {
      simulator.simulateIncoming(phone: phone, name: name);
    }
  }

  void _onSignal(CallSignal signal) {
    switch (signal.kind) {
      case CallSignalKind.incoming:
        if (state != null) return;
        state = CallState(
          status: CallLifecycleStatus.incoming,
          direction: CallDirection.inbound,
          phone: signal.phone ?? '',
          name: signal.name,
          externalId: signal.externalId,
          startedAt: DateTime.now(),
        );
      case CallSignalKind.ringing:
        _advance(CallLifecycleStatus.ringing);
      case CallSignalKind.answered:
        _advance(CallLifecycleStatus.answered);
        final active = state;
        // With app consent the backend plays the notice to the counterparty
        // (consent_notice); without it the call is ordinary (in_progress).
        if (active != null && active.recordingEnabled) {
          _advance(CallLifecycleStatus.consentNotice);
        } else {
          _advance(CallLifecycleStatus.inProgress);
        }
      case CallSignalKind.ended:
        _endAs(CallLifecycleStatus.completed);
      case CallSignalKind.dropped:
        _endAs(CallLifecycleStatus.failed);
      case CallSignalKind.missed:
        _endAs(CallLifecycleStatus.missed);
    }
  }

  /// Applies a terminal status, falling back to the matching terminal state
  /// when the provider hangs up before/after answering.
  void _endAs(CallLifecycleStatus terminal) {
    final current = state;
    if (current == null || current.status.isTerminal) return;

    var target = terminal;
    if (!canTransitionCall(current.status, target)) {
      final connected = current.status == CallLifecycleStatus.answered ||
          current.isConnected;
      target = connected
          ? CallLifecycleStatus.failed
          : CallLifecycleStatus.missed;
      if (!canTransitionCall(current.status, target)) return;
    }
    state = current.copyWith(status: target, endedAt: DateTime.now());
  }

  void _advance(CallLifecycleStatus target) {
    final current = state;
    if (current == null || current.status.isTerminal) return;
    if (!canTransitionCall(current.status, target)) return;
    final now = DateTime.now();
    state = current.copyWith(
      status: target,
      answeredAt: target == CallLifecycleStatus.answered ? now : null,
      endedAt: target.isTerminal ? now : null,
    );
  }
}
