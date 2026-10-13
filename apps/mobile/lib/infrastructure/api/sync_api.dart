import '../../domain/ports.dart';
import '../../domain/sync_models.dart';
import 'api_client.dart';

/// `/sync` deltas: pull changed rows since a token, push the local outbox.
class HttpSyncApi implements SyncApi {
  HttpSyncApi({required ApiClient client}) : _client = client;

  final ApiClient _client;

  @override
  Future<SyncPullResult> pull({String? since}) async {
    final data = await _client.get(
      '/sync',
      query: since == null ? null : <String, Object?>{'since': since},
    );
    return SyncPullResult.fromJson(asJsonMap(data));
  }

  @override
  Future<SyncPushResult> push(List<SyncOperation> operations) async {
    final data = await _client.post(
      '/sync',
      body: <String, Object?>{
        'operations': operations.map((op) => op.toJson()).toList(),
      },
    );
    return SyncPushResult.fromJson(asJsonMap(data));
  }
}