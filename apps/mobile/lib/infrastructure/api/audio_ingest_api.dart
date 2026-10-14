import '../../domain/audio.dart';
import '../../domain/ports.dart';
import 'api_client.dart';

/// Client for the resumable audio ingest (`POST /calls/{id}/audio`).
///
/// A whole recording is a single request without `Content-Range`; a resumed
/// upload sends one chunk with `Content-Range: bytes <start>-<end>/<total>` and
/// continues from the `offset` the server reports (plan.md §13).
class HttpAudioIngestApi implements AudioIngestApi {
  HttpAudioIngestApi({required ApiClient client}) : _client = client;

  final ApiClient _client;

  @override
  Future<AudioIngestResult> upload({
    required String callId,
    required List<int> bytes,
    int? start,
    int? total,
    String? contentType,
    int? durationSec,
  }) async {
    final headers = <String, String>{};
    if (start != null && bytes.isNotEmpty) {
      final boundary = total ?? (start + bytes.length);
      headers['Content-Range'] = 'bytes $start-${start + bytes.length - 1}/$boundary';
    }
    final query = <String, Object?>{};
    if (durationSec != null) query['duration_sec'] = durationSec;
    final raw = await _client.postBytes(
      '/calls/$callId/audio',
      bytes: bytes,
      contentType: contentType ?? 'audio/wav',
      query: query.isEmpty ? null : query,
      extraHeaders: headers.isEmpty ? null : headers,
    );
    final map = asJsonMap(raw);
    return AudioIngestResult(
      offset: (map['offset'] as num?)?.toInt() ?? 0,
      complete: map['complete'] == true,
      analysisQueued: map['analysis_queued'] == true,
    );
  }
}
