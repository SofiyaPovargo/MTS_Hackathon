import '../../domain/models.dart';
import '../../domain/ports.dart';
import 'api_client.dart';

/// Manager dashboard reads: `/manager/team/tasks`, `/manager/team/stats`,
/// `/manager/team/members`. Query parameters carry the server-side filters.
class HttpManagerApi implements ManagerApi {
  HttpManagerApi({required ApiClient client}) : _client = client;

  final ApiClient _client;

  @override
  Future<List<TaskItem>> fetchTeamTasks({
    String? userId,
    String? status,
    DateTime? dueBefore,
  }) async {
    final data = await _client.get(
      '/manager/team/tasks',
      query: <String, Object?>{
        'user_id': ?userId,
        'status': ?status,
        if (dueBefore != null) 'due_before': formatDateOnly(dueBefore),
      },
    );
    return asJsonList(data).map(TaskItem.fromJson).toList();
  }

  @override
  Future<TeamStats> fetchTeamStats() async {
    final data = await _client.get('/manager/team/stats');
    return TeamStats.fromJson(asJsonMap(data));
  }

  @override
  Future<List<TeamMember>> fetchTeamMembers() async {
    final data = await _client.get('/manager/team/members');
    return asJsonList(data).map(TeamMember.fromJson).toList();
  }
}
