import '../domain/offline_call.dart';
import '../domain/ports.dart';
import '../infrastructure/api/api_exception.dart';

/// Registers calls that happened while the app could not reach the backend
/// (plan.md §13).
///
/// The client records such a call locally; when the network returns this
/// service pushes it idempotently: `POST /calls` (client id → no duplicate) and
/// then `POST /calls/{id}/recordings` (fixes the recording and both consent
/// events). The server gate is unchanged — without consent the recording is not
/// fixed and the audio upload is refused. Audio is uploaded afterwards by
/// [CallRecordingService.uploadPending].
///
/// Every method is best-effort: a still-offline flush keeps the entry queued and
/// never throws, so it can never break a call or a screen.
class OfflineCallService {
  OfflineCallService({required PendingCallStore store, required CallApi api})
      : _store = store,
        _api = api;

  final PendingCallStore _store;
  final CallApi _api;

  /// Queues (or updates) a locally-registered call, keyed by `call_id`.
  Future<void> register(PendingCall call) async {
    try {
      await _store.save(call);
    } catch (_) {
      // A storage failure must not break the call teardown.
    }
  }

  /// Pushes every queued call to the server. Returns how many were accepted
  /// this round; entries that still fail stay queued for the next reconnect.
  Future<int> flush() async {
    List<PendingCall> queued;
    try {
      queued = await _store.pending();
    } catch (_) {
      return 0;
    }
    var registered = 0;
    for (final call in queued) {
      if (await _push(call)) registered++;
    }
    return registered;
  }

  Future<bool> _push(PendingCall call) async {
    try {
      await _api.createCall(
        id: call.callId,
        direction: call.direction,
        calleePhone: call.calleePhone,
        contactName: call.contactName,
        startedAt: call.startedAt,
        recordConsent: call.recordConsent,
      );
      await _api.declareRecording(
        call.callId,
        recordConsent: call.recordConsent,
        participantConsent: call.participantConsent,
        consentMethod: call.consentMethod,
        answeredAt: call.answeredAt,
        recordingStartedAt: call.recordingStartedAt,
        endedAt: call.endedAt,
      );
      await _store.remove(call.callId);
      return true;
    } on ApiException {
      // Still offline / transient: keep it queued and try again later.
      return false;
    } catch (_) {
      // One bad entry must not block the others.
      return false;
    }
  }
}
