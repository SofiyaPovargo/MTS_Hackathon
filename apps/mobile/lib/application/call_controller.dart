import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../domain/call.dart';
import '../domain/enums.dart';
import '../domain/models.dart';
import '../domain/offline_call.dart';
import '../domain/ports.dart';
import '../domain/ws_event.dart';
import '../infrastructure/api/api_exception.dart';
import 'offline_call_service.dart';
import 'providers.dart';
import 'recording_service.dart';

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
  CallEventsPort get _events => ref.read(callEventsProvider);
  AgreementApi get _agreements => ref.read(agreementApiProvider);
  ScheduleApi get _schedule => ref.read(scheduleApiProvider);
  CallRecordingService get _recording => ref.read(recordingServiceProvider);
  OfflineCallService get _offline => ref.read(offlineCallServiceProvider);
  String Function() get _newCallId => ref.read(callIdFactoryProvider);

  // ignore: cancel_subscriptions — cancelled in [_disconnectLive] / onDispose.
  StreamSubscription<CallEvent>? _liveSub;

  /// The port we connected through; held so disposal never reads a provider.
  CallEventsPort? _connectedPort;

  @override
  CallState? build() {
    final subscription = _voice.signals.listen(_onSignal);
    ref.onDispose(subscription.cancel);
    ref.onDispose(_disconnectLive);
    return null;
  }

  /// Places an outgoing call. Returns an error message, or `null` on success.
  ///
  /// A client-generated id is sent so the call is idempotent: if the network
  /// drops after the trigger but before the response, the call is still created
  /// once and never duplicated (plan.md §13). When the backend is unreachable
  /// the call proceeds as an **offline** call and is registered later
  /// ([OfflineCallService]); a non-retryable error (validation/forbidden) is
  /// surfaced instead.
  Future<String?> startOutgoing(String phone, {String? name}) async {
    final normalized = phone.trim();
    if (normalized.isEmpty) return 'Введите номер';

    if (!await _voice.ensureMicrophonePermission()) {
      return 'Нет доступа к микрофону. Разрешите его в настройках приложения.';
    }

    var callId = _newCallId();
    var offline = false;
    final startedAt = DateTime.now();
    try {
      final call = await _api.createCall(
        direction: CallDirection.outbound,
        calleePhone: normalized,
        contactName: name,
        id: callId,
        startedAt: startedAt,
      );
      callId = call.id;
    } on ApiException catch (error) {
      // No backend yet: keep the call usable locally and register it later.
      if (!error.isRetryable) return error.message;
      offline = true;
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
      offline: offline,
      startedAt: startedAt,
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
  void clear() {
    final callId = state?.callId;
    if (callId != null) unawaited(_recording.finish(callId));
    _disconnectLive();
    state = null;
  }

  // ---- call summary (plan.md §9) -------------------------------------------

  /// Loads the call's итог (`GET /calls/{id}/summary`) and stores it on the
  /// [CallState]. Best-effort: it never throws, returning a user-facing message
  /// only on a real failure (and `null` otherwise). Called automatically when
  /// the call reaches a terminal status and from the live card's refresh.
  Future<String?> loadSummary() async {
    final callId = state?.callId;
    if (callId == null) return null;
    try {
      final summary = await _schedule.callSummary(callId);
      final current = state;
      if (current != null && current.callId == callId) {
        state = current.copyWith(callSummary: summary);
      }
      return null;
    } on ApiException catch (error) {
      return error.message;
    } catch (_) {
      return 'Не удалось загрузить итог звонка';
    }
  }

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

  // ---- agreement actions (live card) ---------------------------------------

  /// Confirms an agreement on the server; the backend creates the task from a
  /// `confirmed` agreement. Returns an error message, or `null` on success.
  Future<String?> confirmAgreement(String agreementId) async {
    try {
      _upsertAgreement(await _agreements.confirm(agreementId));
      return null;
    } on ApiException catch (error) {
      return error.message;
    }
  }

  Future<String?> rejectAgreement(String agreementId) async {
    try {
      _upsertAgreement(await _agreements.reject(agreementId));
      return null;
    } on ApiException catch (error) {
      return error.message;
    }
  }

  /// Applies the user's edits (`PATCH /agreements/{id}`).
  Future<String?> editAgreement(String agreementId, AgreementPatch changes) async {
    try {
      _upsertAgreement(await _agreements.patch(agreementId, changes));
      return null;
    } on ApiException catch (error) {
      return error.message;
    }
  }

  /// Manual entry on the no-consent path (`POST /calls/{id}/agreements`).
  Future<String?> createManualAgreement(AgreementPatch patch) async {
    final callId = state?.callId;
    if (callId == null) return 'Нет активного звонка';
    try {
      _upsertAgreement(await _agreements.create(callId: callId, patch: patch));
      return null;
    } on ApiException catch (error) {
      return error.message;
    }
  }

  // ---- live WebSocket events -------------------------------------------------
  //
  // The backend pushes the four WS events (schema v1). `analysis_started` also
  // implies consent was granted, so it drives the consent → recording →
  // analyzing chain; `partial_transcript` appends lines; `agreement_detected`
  // upserts a card; `call_ended` completes the call.

  void _onCallEvent(CallEvent event) {
    if (state == null || event.callId != state?.callId) return;
    switch (event.kind) {
      case CallEventKind.analysisStarted:
        markConsentResult(granted: true);
        markAnalysisStarted();
      case CallEventKind.partialTranscript:
        _appendTranscript(TranscriptSegment.fromPayload(event.payload));
      case CallEventKind.agreementDetected:
        if (event.payload.isNotEmpty) {
          _upsertAgreement(Agreement.fromJson(event.payload));
        }
      case CallEventKind.callEnded:
        _endAs(CallLifecycleStatus.completed);
    }
  }

  Future<void> _connectLive() async {
    final callId = state?.callId;
    if (callId == null || state == null || !state!.recordingEnabled) return;
    if (_liveSub != null) return;
    final events = _events;
    try {
      await events.connect(callId);
      _connectedPort = events;
      _liveSub = events.events.listen(
        _onCallEvent,
        onError: (_) {
          // The live feed is best-effort; the board stays usable without it.
          _liveSub = null;
        },
        onDone: () => _liveSub = null,
      );
    } on Object {
      _liveSub = null;
    }
  }

  void _disconnectLive() {
    final sub = _liveSub;
    _liveSub = null;
    final events = _connectedPort;
    _connectedPort = null;
    if (sub == null && events == null) return;
    unawaited(sub?.cancel());
    unawaited(events?.disconnect());
  }

  void _appendTranscript(TranscriptSegment segment) {
    final current = state;
    if (current == null) return;
    state = current.copyWith(
      transcript: <TranscriptSegment>[...current.transcript, segment],
    );
  }

  void _upsertAgreement(Agreement agreement) {
    final current = state;
    if (current == null) return;
    final others = current.agreements
        .where((a) => a.id != agreement.id)
        .toList();
    state = current.copyWith(
      agreements: <Agreement>[agreement, ...others],
    );
  }

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
        // Subscribe to the live feed so `analysis_started`/transcript/agreements
        // reach the call card as soon as they exist. Replay covers anything that
        // happened before the handshake.
        unawaited(_connectLive());
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
    final ended = current.copyWith(status: target, endedAt: DateTime.now());
    state = ended;
    if (ended.callId != null) {
      unawaited(_finalize(ended));
    }
    _disconnectLive();
  }

  /// Stops capture, saves the recording and registers an offline call on the
  /// server once the network allows it. Best-effort: a still-offline flush keeps
  /// everything queued, so nothing is lost.
  Future<void> _finalize(CallState ended) async {
    final callId = ended.callId!;
    await _recording.finish(callId);
    if (ended.offline) {
      await _offline.register(_pendingFrom(ended));
      final registered = await _offline.flush();
      if (registered > 0) await _recording.uploadPending();
    }
    // The summary becomes available once the call is terminal; [loadSummary]
    // never throws, so an offline failure stays silent.
    await loadSummary();
  }

  /// Builds the offline registration. The counterparty consent is only ever the
  /// real result ([CallState.participantDeclined]); the controller never grants
  /// it on its own (AGENTS consent gate).
  PendingCall _pendingFrom(CallState ended) {
    final appConsent = ref.read(consentControllerProvider).valueOrNull;
    return PendingCall(
      callId: ended.callId!,
      direction: ended.direction,
      calleePhone: ended.phone,
      contactName: ended.name,
      startedAt: ended.startedAt ?? DateTime.now(),
      recordConsent: appConsent?.recordingEnabled ?? false,
      participantConsent: ended.participantDeclined
          ? ConsentStatus.denied
          : ConsentStatus.granted,
      answeredAt: ended.answeredAt,
      endedAt: ended.endedAt,
    );
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
    if (target == CallLifecycleStatus.recording) _maybeStartRecording();
  }

  /// Starts buffering the call's audio once consent is granted (`recording`).
  /// The recording is always saved; see [CallRecordingService].
  void _maybeStartRecording() {
    final current = state;
    if (current == null || !current.recordingEnabled) return;
    final callId = current.callId;
    final externalId = current.externalId;
    if (callId == null || externalId == null) return;
    unawaited(_recording.start(callId, externalId: externalId));
  }
}
