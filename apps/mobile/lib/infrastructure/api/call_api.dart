import '../../domain/enums.dart';
import '../../domain/models.dart';
import '../../domain/ports.dart';
import 'api_client.dart';

/// Call records over REST: `POST /calls`, `GET /calls/{id}` and the offline
/// recording declaration (`POST /calls/{id}/recordings`, plan.md §13).
class HttpCallApi implements CallApi {
  HttpCallApi({required ApiClient client}) : _client = client;

  final ApiClient _client;

  @override
  Future<Call> createCall({
    required CallDirection direction,
    required String calleePhone,
    String? contactName,
    String? id,
    DateTime? startedAt,
    bool recordConsent = true,
  }) async {
    final data = await _client.post('/calls', body: <String, Object?>{
      'id': ?id,
      'direction': direction.wire,
      'callee_phone': calleePhone,
      'contact_name': contactName,
      if (startedAt != null) 'started_at': startedAt.toUtc().toIso8601String(),
      'record_consent': recordConsent,
    });
    return Call.fromJson(asJsonMap(data));
  }

  @override
  Future<Call> getCall(String id) async {
    final data = await _client.get('/calls/$id');
    return Call.fromJson(asJsonMap(data));
  }

  @override
  Future<List<Call>> calls() async {
    final data = await _client.get('/calls');
    return asJsonList(data).map(Call.fromJson).toList();
  }

  @override
  Future<Call> declareRecording(
    String callId, {
    bool recordConsent = true,
    ConsentStatus participantConsent = ConsentStatus.granted,
    ConsentMethod consentMethod = ConsentMethod.audioNotice,
    DateTime? answeredAt,
    DateTime? recordingStartedAt,
    DateTime? endedAt,
  }) async {
    final data = await _client.post('/calls/$callId/recordings', body: <String, Object?>{
      'record_consent': recordConsent,
      'participant_consent': participantConsent.wire,
      'consent_method': consentMethod.wire,
      if (answeredAt != null) 'answered_at': answeredAt.toUtc().toIso8601String(),
      if (recordingStartedAt != null)
        'recording_started_at': recordingStartedAt.toUtc().toIso8601String(),
      if (endedAt != null) 'ended_at': endedAt.toUtc().toIso8601String(),
    });
    return Call.fromJson(asJsonMap(data));
  }
}
