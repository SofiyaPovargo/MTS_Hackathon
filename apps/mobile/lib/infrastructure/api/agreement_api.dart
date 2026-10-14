import '../../domain/models.dart';
import '../../domain/ports.dart';
import 'api_client.dart';

/// Agreement actions over REST:
/// `GET|POST /calls/{id}/agreements`, `PATCH /agreements/{id}`,
/// `POST /agreements/{id}/confirm|reject`.
class HttpAgreementApi implements AgreementApi {
  HttpAgreementApi({required ApiClient client}) : _client = client;

  final ApiClient _client;

  @override
  Future<List<Agreement>> listForCall(String callId) async {
    final data = await _client.get('/calls/$callId/agreements');
    return asJsonList(data).map(Agreement.fromJson).toList();
  }

  @override
  Future<Agreement> create({
    required String callId,
    required AgreementPatch patch,
  }) async {
    final data =
        await _client.post('/calls/$callId/agreements', body: patch.toJson());
    return Agreement.fromJson(asJsonMap(data));
  }

  @override
  Future<Agreement> patch(String agreementId, AgreementPatch changes) async {
    final data = await _client.patch(
      '/agreements/$agreementId',
      body: changes.toJson(),
    );
    return Agreement.fromJson(asJsonMap(data));
  }

  @override
  Future<Agreement> confirm(String agreementId) async {
    final data = await _client.post('/agreements/$agreementId/confirm');
    return Agreement.fromJson(asJsonMap(data));
  }

  @override
  Future<Agreement> reject(String agreementId) async {
    final data = await _client.post('/agreements/$agreementId/reject');
    return Agreement.fromJson(asJsonMap(data));
  }
}