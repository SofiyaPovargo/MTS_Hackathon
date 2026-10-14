import 'dart:async';
import 'dart:math' as math;

import '../domain/audio.dart';
import '../domain/ports.dart';

/// Stage 6 coordination: once consent is granted the recording is **always**
/// saved.
///
/// Every captured chunk is appended to the local store first; while online the
/// same bytes are also streamed over `WS /ws/calls/{id}/audio` for real-time
/// analysis. When the call ends the recorder uploads through the resumable
/// `POST /calls/{id}/audio`; if the network is down the recording stays
/// `pending` and is retried later, resuming from the server-confirmed offset.
/// A dropped connection never loses already-recorded audio (plan.md §13).
///
/// Failures here must never break a call, so every public method swallows
/// transport/storage errors and reports its outcome.
class CallRecordingService {
  CallRecordingService({
    required VoiceCallProvider recorder,
    required AudioRecordingStore store,
    required AudioIngestApi ingest,
    required LiveAudioPort live,
    this.retentionLimit = 20,
    this.chunkSize = 256 * 1024,
  })  : _recorder = recorder,
        _store = store,
        _ingest = ingest,
        _live = live;

  /// How many uploaded recordings the local cache keeps (plan.md §8).
  final int retentionLimit;

  /// Bytes per resumable upload request.
  final int chunkSize;

  final VoiceCallProvider _recorder;
  final AudioRecordingStore _store;
  final AudioIngestApi _ingest;
  final LiveAudioPort _live;

  // ignore: cancel_subscriptions — cancelled in [_stopCapture].
  StreamSubscription<List<int>>? _capture;
  Future<void> _writeChain = Future<void>.value();
  String? _liveCallId;
  bool _liveDown = false;
  String? _activeCallId;

  /// The call currently being recorded, or null.
  String? get activeCallId => _activeCallId;

  /// Starts buffering the call's audio. Idempotent per call.
  Future<void> start(
    String callId, {
    required String externalId,
    Duration? keepFor,
  }) async {
    if (_activeCallId == callId) return;
    await _stopCapture();
    _activeCallId = callId;
    try {
      await _store.begin(callId, keepFor: keepFor);
    } catch (_) {
      _activeCallId = null;
      return;
    }
    _liveCallId = callId;
    _liveDown = false;
    unawaited(_connectLive(callId));
    // ignore: cancel_subscriptions — cancelled in [_stopCapture].
    _capture = _recorder.openMediaStream(externalId).listen(
          (chunk) => _onChunk(callId, chunk),
          onError: (Object _) {},
          cancelOnError: false,
        );
  }

  /// Stops capture, flushes the buffer and uploads the recording (best effort).
  Future<void> finish(String callId, {int? durationSec}) async {
    if (_activeCallId == callId) {
      await _stopCapture();
      _activeCallId = null;
    }
    await _safeStatus(callId, RecordingUploadStatus.pending);
    await _upload(callId, durationSec: durationSec);
  }

  /// Retries every recording that was not uploaded yet (app start / reconnect).
  Future<void> uploadPending() async {
    List<CallRecording> pending;
    try {
      pending = await _store.pending();
    } catch (_) {
      return;
    }
    for (final recording in pending) {
      await _upload(recording.callId);
    }
  }

  /// Releases capture and the live socket (logout / dispose).
  Future<void> dispose() async {
    await _stopCapture();
    _activeCallId = null;
    await _closeLive();
  }

  void _onChunk(String callId, List<int> bytes) {
    if (bytes.isEmpty) return;
    _writeChain = _writeChain.then((_) async {
      try {
        await _store.append(callId, bytes);
      } catch (_) {
        // The local buffer is best-effort; never break the call.
      }
    });
    unawaited(_sendLive(bytes));
  }

  Future<void> _stopCapture() async {
    final capture = _capture;
    _capture = null;
    await capture?.cancel();
    try {
      await _writeChain;
    } catch (_) {
      // ignore
    }
    _liveCallId = null;
    await _closeLive();
  }

  Future<void> _connectLive(String callId) async {
    try {
      await _live.connect(callId);
    } catch (_) {
      _liveDown = true;
    }
  }

  Future<void> _sendLive(List<int> bytes) async {
    if (_liveDown || _liveCallId == null) return;
    try {
      await _live.send(bytes);
    } catch (_) {
      _liveDown = true;
    }
  }

  Future<void> _closeLive() async {
    try {
      await _live.close();
    } catch (_) {
      // ignore
    }
  }

  Future<bool> _upload(String callId, {int? durationSec}) async {
    try {
      final recording = await _store.get(callId);
      if (recording == null) return false;
      if (!recording.needsUpload) {
        await _store.markUploaded(
          callId,
          uploadedBytes: recording.bytesTotal,
          complete: true,
        );
        await _store.enforceRetention(maxRecordings: retentionLimit);
        return true;
      }
      final total = recording.bytesTotal;
      final start = recording.uploadedBytes;
      final remaining = await _store.readFrom(callId, start);
      var offset = start;
      while (offset < total) {
        final end = math.min(offset + chunkSize, total);
        final chunk = remaining.sublist(offset - start, end - start);
        final result = await _ingest.upload(
          callId: callId,
          bytes: chunk,
          start: offset,
          total: total,
          contentType: recording.contentType,
          durationSec: durationSec,
        );
        if (result.offset <= offset && !result.complete) break;
        offset = result.offset;
        await _store.markUploaded(
          callId,
          uploadedBytes: offset,
          complete: offset >= total,
        );
      }
      await _store.markUploaded(callId, uploadedBytes: total, complete: true);
      await _store.enforceRetention(maxRecordings: retentionLimit);
      return true;
    } catch (_) {
      await _safeStatus(callId, RecordingUploadStatus.pending);
      return false;
    }
  }

  Future<void> _safeStatus(String callId, RecordingUploadStatus status) async {
    try {
      final recording = await _store.get(callId);
      if (recording == null) return;
      await _store.setStatus(callId, status);
    } catch (_) {
      // ignore
    }
  }
}
