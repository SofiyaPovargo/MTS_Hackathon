import '../../domain/models.dart';
import '../../domain/ports.dart';
import 'api_client.dart';

/// Personal board reads: `/me/tasks` and `/me/agreements`.
class HttpBoardApi implements BoardApi {
  HttpBoardApi({required ApiClient client}) : _client = client;

  final ApiClient _client;

  @override
  Future<List<TaskItem>> fetchMyTasks() async {
    final data = await _client.get('/me/tasks');
    return asJsonList(data).map(TaskItem.fromJson).toList();
  }

  @override
  Future<List<Agreement>> fetchMyAgreements() async {
    final data = await _client.get('/me/agreements');
    return asJsonList(data).map(Agreement.fromJson).toList();
  }
}