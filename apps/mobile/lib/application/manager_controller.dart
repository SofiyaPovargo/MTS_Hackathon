import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../domain/enums.dart';
import '../domain/models.dart';
import '../domain/ports.dart';
import 'providers.dart';

/// Manager board filter (plan.md §15). Employee/status/due are applied by the
/// server; priority is applied client-side (the backend has no priority filter).
class ManagerFilter {
  const ManagerFilter({
    this.userId,
    this.status,
    this.dueBefore,
    this.priority,
  });

  final String? userId;
  final TaskStatus? status;
  final DateTime? dueBefore;
  final TaskPriority? priority;

  bool get isEmpty =>
      userId == null && status == null && dueBefore == null && priority == null;

  ManagerFilter copyWith({
    String? userId,
    TaskStatus? status,
    DateTime? dueBefore,
    TaskPriority? priority,
    bool clearUserId = false,
    bool clearStatus = false,
    bool clearDueBefore = false,
    bool clearPriority = false,
  }) {
    return ManagerFilter(
      userId: clearUserId ? null : (userId ?? this.userId),
      status: clearStatus ? null : (status ?? this.status),
      dueBefore: clearDueBefore ? null : (dueBefore ?? this.dueBefore),
      priority: clearPriority ? null : (priority ?? this.priority),
    );
  }
}

/// Manager board data. Team data is never written to the local database
/// (AGENTS: the phone stores only the user's own data) — it lives in memory and
/// is re-fetched on refresh.
class ManagerBoard {
  const ManagerBoard({
    required this.tasks,
    required this.stats,
    required this.members,
    required this.filter,
  });

  final List<TaskItem> tasks;
  final TeamStats stats;
  final List<TeamMember> members;
  final ManagerFilter filter;

  ManagerBoard copyWith({List<TaskItem>? tasks, ManagerFilter? filter}) =>
      ManagerBoard(
        tasks: tasks ?? this.tasks,
        stats: stats,
        members: members,
        filter: filter ?? this.filter,
      );

  String memberName(String userId) {
    for (final member in members) {
      if (member.id == userId) return member.fullName;
    }
    return '—';
  }
}

/// Loads the team board from `/manager/team/*`. The server re-checks the role
/// and team membership, so this controller never decides access itself.
class ManagerController extends AsyncNotifier<ManagerBoard> {
  ManagerApi get _api => ref.read(managerApiProvider);

  @override
  Future<ManagerBoard> build() => _load(const ManagerFilter());

  Future<ManagerBoard> _load(ManagerFilter filter) async {
    final members = await _api.fetchTeamMembers();
    final stats = await _api.fetchTeamStats();
    final tasks = await _api.fetchTeamTasks(
      userId: filter.userId,
      status: filter.status?.wire,
      dueBefore: filter.dueBefore,
    );
    return ManagerBoard(
      tasks: tasks,
      stats: stats,
      members: members,
      filter: filter,
    );
  }

  /// Applies a filter. Employee/status/due re-query the server; priority is a
  /// client-side narrowing. Errors propagate so the UI can surface them.
  Future<void> applyFilter(ManagerFilter filter) async {
    final current = state.valueOrNull;
    if (current == null) {
      state = AsyncValue<ManagerBoard>.data(await _load(filter));
      return;
    }
    final tasks = await _api.fetchTeamTasks(
      userId: filter.userId,
      status: filter.status?.wire,
      dueBefore: filter.dueBefore,
    );
    state = AsyncValue<ManagerBoard>.data(
      current.copyWith(tasks: tasks, filter: filter),
    );
  }

  Future<void> refresh() async {
    final filter = state.valueOrNull?.filter ?? const ManagerFilter();
    state = const AsyncValue<ManagerBoard>.loading();
    state = AsyncValue<ManagerBoard>.data(await _load(filter));
  }
}
