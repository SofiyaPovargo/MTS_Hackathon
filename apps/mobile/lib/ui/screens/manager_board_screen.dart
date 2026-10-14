import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../application/manager_controller.dart';
import '../../application/providers.dart';
import '../../domain/board.dart';
import '../../domain/enums.dart';
import '../../domain/models.dart';
import '../../infrastructure/api/api_exception.dart';
import '../formats.dart';

/// Manager board (plan.md §15): team tasks with filters and sorting, analytics
/// and the team list. Only reachable for a manager; the server re-checks the
/// role and team membership. Team data is kept in memory, never cached locally.
class ManagerBoardScreen extends ConsumerWidget {
  const ManagerBoardScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final board = ref.watch(managerControllerProvider);
    return DefaultTabController(
      length: 3,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Доска команды'),
          bottom: const TabBar(
            tabs: <Widget>[
              Tab(text: 'Задачи'),
              Tab(text: 'Аналитика'),
              Tab(text: 'Сотрудники'),
            ],
          ),
        ),
        body: board.when(
          data: (data) => TabBarView(
            children: <Widget>[
              _TasksTab(board: data),
              _AnalyticsTab(stats: data.stats),
              _MembersTab(members: data.members),
            ],
          ),
          error: (error, stackTrace) => Center(child: Text('Ошибка: $error')),
          loading: () => const Center(child: CircularProgressIndicator()),
        ),
      ),
    );
  }
}

class _TasksTab extends ConsumerWidget {
  const _TasksTab({required this.board});

  final ManagerBoard board;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final controller = ref.read(managerControllerProvider.notifier);
    final visible = filterManagerTasks(
      sortManagerTasks(board.tasks),
      priority: board.filter.priority,
    );
    return Column(
      children: <Widget>[
        _FilterBar(
          board: board,
          onChanged: (filter) => _apply(context, controller, filter),
        ),
        const Divider(height: 1),
        Expanded(
          child: visible.isEmpty
              ? const Center(child: Text('Нет задач по фильтру'))
              : ListView.builder(
                  itemCount: visible.length,
                  itemBuilder: (context, index) {
                    final task = visible[index];
                    return _ManagerTaskTile(
                      task: task,
                      assignee: board.memberName(task.assigneeUserId),
                    );
                  },
                ),
        ),
      ],
    );
  }

  Future<void> _apply(
    BuildContext context,
    ManagerController controller,
    ManagerFilter filter,
  ) async {
    final messenger = ScaffoldMessenger.of(context);
    try {
      await controller.applyFilter(filter);
    } on ApiException catch (error) {
      messenger.showSnackBar(SnackBar(content: Text(error.message)));
    }
  }
}

class _FilterBar extends StatelessWidget {
  const _FilterBar({required this.board, required this.onChanged});

  final ManagerBoard board;
  final ValueChanged<ManagerFilter> onChanged;

  @override
  Widget build(BuildContext context) {
    final filter = board.filter;
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      child: Row(
        children: <Widget>[
          DropdownButton<String?>(
            value: filter.userId,
            hint: const Text('Сотрудник'),
            items: <DropdownMenuItem<String?>>[
              const DropdownMenuItem<String?>(child: Text('Все сотрудники')),
              for (final member in board.members)
                DropdownMenuItem<String?>(
                  value: member.id,
                  child: Text(member.fullName),
                ),
            ],
            onChanged: (value) => onChanged(
              filter.copyWith(userId: value, clearUserId: value == null),
            ),
          ),
          const SizedBox(width: 12),
          DropdownButton<TaskStatus?>(
            value: filter.status,
            hint: const Text('Статус'),
            items: <DropdownMenuItem<TaskStatus?>>[
              const DropdownMenuItem<TaskStatus?>(child: Text('Все статусы')),
              for (final status in TaskStatus.values)
                DropdownMenuItem<TaskStatus?>(
                  value: status,
                  child: Text(taskStatusLabel(status)),
                ),
            ],
            onChanged: (value) => onChanged(
              filter.copyWith(status: value, clearStatus: value == null),
            ),
          ),
          const SizedBox(width: 12),
          DropdownButton<TaskPriority?>(
            value: filter.priority,
            hint: const Text('Приоритет'),
            items: <DropdownMenuItem<TaskPriority?>>[
              const DropdownMenuItem<TaskPriority?>(
                child: Text('Все приоритеты'),
              ),
              for (final priority in TaskPriority.values)
                DropdownMenuItem<TaskPriority?>(
                  value: priority,
                  child: Text(taskPriorityLabel(priority)),
                ),
            ],
            onChanged: (value) => onChanged(
              filter.copyWith(priority: value, clearPriority: value == null),
            ),
          ),
          const SizedBox(width: 12),
          if (filter.dueBefore != null)
            InputChip(
              label: Text('До ${formatDueDate(filter.dueBefore)}'),
              onDeleted: () => onChanged(filter.copyWith(clearDueBefore: true)),
            ),
          if (!filter.isEmpty)
            TextButton(
              onPressed: () => onChanged(const ManagerFilter()),
              child: const Text('Сбросить'),
            ),
        ],
      ),
    );
  }
}

class _ManagerTaskTile extends StatelessWidget {
  const _ManagerTaskTile({required this.task, required this.assignee});

  final TaskItem task;
  final String assignee;

  @override
  Widget build(BuildContext context) {
    final overdue = task.status == TaskStatus.overdue;
    return ListTile(
      leading: Icon(
        overdue ? Icons.warning_amber : Icons.task_alt,
        color: overdue ? Theme.of(context).colorScheme.error : null,
      ),
      title: Text(task.title),
      subtitle: Text(
        '$assignee · ${formatDueDate(task.dueDate)} · ${taskPriorityLabel(task.priority)}',
      ),
      trailing: Chip(label: Text(taskStatusLabel(task.status))),
    );
  }
}

class _AnalyticsTab extends StatelessWidget {
  const _AnalyticsTab({required this.stats});

  final TeamStats stats;

  @override
  Widget build(BuildContext context) {
    final closeHours = stats.avgCloseHours;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: <Widget>[
        _StatCard(title: 'Сотрудников', value: '${stats.membersCount}'),
        _StatCard(title: 'Всего задач', value: '${stats.tasksTotal}'),
        _StatCard(title: 'Просрочено', value: '${stats.overdue}'),
        _StatCard(title: 'Выполнено вовремя', value: '${stats.doneOnTime}'),
        _StatCard(
          title: 'Выполнение в срок',
          value: '${stats.doneOnTimePercent.toStringAsFixed(1)}%',
        ),
        _StatCard(
          title: 'Среднее время закрытия',
          value: closeHours == null
              ? '—'
              : '${closeHours.toStringAsFixed(1)} ч',
        ),
        _StatCard(
          title: 'Задач из звонков',
          value: '${stats.tasksFromCallsPercent.toStringAsFixed(1)}%',
        ),
        const SizedBox(height: 8),
        Text('По статусам', style: Theme.of(context).textTheme.titleSmall),
        for (final status in TaskStatus.values)
          ListTile(
            dense: true,
            title: Text(taskStatusLabel(status)),
            trailing: Text('${stats.statusCount(status)}'),
          ),
      ],
    );
  }
}

class _StatCard extends StatelessWidget {
  const _StatCard({required this.title, required this.value});

  final String title;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: ListTile(
        title: Text(title),
        trailing: Text(value, style: Theme.of(context).textTheme.titleMedium),
      ),
    );
  }
}

class _MembersTab extends StatelessWidget {
  const _MembersTab({required this.members});

  final List<TeamMember> members;

  @override
  Widget build(BuildContext context) {
    if (members.isEmpty) {
      return const Center(child: Text('Нет сотрудников'));
    }
    return ListView.builder(
      itemCount: members.length,
      itemBuilder: (context, index) {
        final member = members[index];
        return ListTile(
          leading: const CircleAvatar(child: Icon(Icons.person_outline)),
          title: Text(member.fullName),
          subtitle: Text(member.phone),
          trailing: Chip(label: Text(member.role.wire)),
        );
      },
    );
  }
}
