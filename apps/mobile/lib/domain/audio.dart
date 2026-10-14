/// Recorded call audio (Stage 6): the phone keeps a bounded local cache of the
/// user's own recent conversations and tracks how much of each recording has
/// reached the server. The server stays the source of truth (plan.md §8, §13).
library;

/// Where a recording is in the upload pipeline.
///
/// `recording` — capture is running; `pending` — the file is complete locally
/// but not fully uploaded yet (offline / network drop); `uploaded` — the server
/// confirmed the whole object.
enum RecordingUploadStatus { recording, pending, uploaded }

/// One recorded call. [path] points at the audio file in the app's private
/// storage; [uploadedBytes] is the server-confirmed byte offset, so a resumed
/// upload continues exactly where it stopped.
class CallRecording {
  const CallRecording({
    required this.callId,
    required this.path,
    required this.bytesTotal,
    required this.uploadedBytes,
    required this.status,
    required this.createdAt,
    this.contentType = 'audio/wav',
    this.keepUntil,
    this.uploadedAt,
  });

  final String callId;
  final String path;
  final int bytesTotal;
  final int uploadedBytes;
  final RecordingUploadStatus status;
  final DateTime createdAt;
  final String contentType;
  final DateTime? keepUntil;
  final DateTime? uploadedAt;

  /// The whole recording reached the server.
  bool get isUploaded => bytesTotal > 0 && uploadedBytes >= bytesTotal;

  /// There is audio that still needs uploading.
  bool get needsUpload => bytesTotal > 0 && uploadedBytes < bytesTotal;

  CallRecording copyWith({
    String? path,
    int? bytesTotal,
    int? uploadedBytes,
    RecordingUploadStatus? status,
    DateTime? uploadedAt,
    DateTime? keepUntil,
  }) {
    return CallRecording(
      callId: callId,
      path: path ?? this.path,
      bytesTotal: bytesTotal ?? this.bytesTotal,
      uploadedBytes: uploadedBytes ?? this.uploadedBytes,
      status: status ?? this.status,
      createdAt: createdAt,
      contentType: contentType,
      keepUntil: keepUntil ?? this.keepUntil,
      uploadedAt: uploadedAt ?? this.uploadedAt,
    );
  }
}

/// Result of one ingest request (`POST /calls/{id}/audio`): [offset] is the
/// durable byte count on the server, [complete] whether the object is stored.
class AudioIngestResult {
  const AudioIngestResult({
    required this.offset,
    required this.complete,
    this.analysisQueued = false,
  });

  final int offset;
  final bool complete;
  final bool analysisQueued;
}
