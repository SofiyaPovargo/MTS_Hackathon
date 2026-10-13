import '../../domain/models.dart';
import '../../domain/ports.dart';
import 'api_client.dart';

/// Consent over REST: `PUT /me/consent`, `POST /me/consent/withdraw`,
/// `POST /me/data/delete`.
class HttpConsentApi implements ConsentApi {
  HttpConsentApi({required ApiClient client}) : _client = client;

  final ApiClient _client;

  @override
  Future<ConsentRecord> setAppConsent(bool granted) async {
    final data = await _client.put(
      '/me/consent',
      body: <String, Object?>{'granted': granted},
    );
    return ConsentRecord.fromJson(asJsonMap(data));
  }

  @override
  Future<ConsentRecord> withdrawConsent() async {
    final data = await _client.post('/me/consent/withdraw');
    return ConsentRecord.fromJson(asJsonMap(data));
  }

  @override
  Future<void> requestDataDeletion() async {
    await _client.post('/me/data/delete');
  }
}