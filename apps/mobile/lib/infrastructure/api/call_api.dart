import '../../domain/enums.dart';
import '../../domain/models.dart';
import '../../domain/ports.dart';
import 'api_client.dart';

/// Call records over REST: `POST /calls` and `GET /calls/{id}`.
class HttpCallApi implements CallApi {
  HttpCallApi({required ApiClient client}) : _client = client;

  final ApiClient _client;

  @override
  Future<Call> createCall({
    required CallDirection direction,
    required String calleePhone,
    String? contactName,
  }) async {
    final data = await _client.post('/calls', body: <String, Object?>{
      'direction': direction.wire,
      'callee_phone': calleePhone,
      'contact_name': contactName,
      'record_consent': true,
    });
    return Call.fromJson(asJsonMap(data));
  }

  @override
  Future<Call> getCall(String id) async {
    final data = await _client.get('/calls/$id');
    return Call.fromJson(asJsonMap(data));
  }
}
