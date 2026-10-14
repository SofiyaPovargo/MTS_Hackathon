import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../application/providers.dart';
import '../../domain/board.dart';
import '../../domain/enums.dart';
import '../../domain/models.dart';
import '../../infrastructure/api/api_exception.dart';
import '../formats.dart';
import 'call_history_screen.dart';
import 'contacts_screen.dart';
import 'dialer_screen.dart';
import 'manager_board_screen.dart';
import 'settings_screen.dart';
import 'task_actions_sheet.dart';

/// Personal board: the user's own tasks in sections (overdue, today, upcoming,
/// without a due date, done). Pull-to-refresh runs a sync; tapping a task opens
/// its actions. Errors are shown without dropping the already-loaded list.
class BoardScreen extends ConsumerWidget {
  const BoardScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tasks = ref.watch(boardControllerProvider);
    final session = ref.watch(authControllerProvider).valueOrNull;
    final isManager = session?.user.role == Role.manager;
    return Scaffold(
      appBar: AppBar(
        title: Text(session == null ? 'Мои задачи' : session.user.fullName),
        actions: <Widget>[
          if (kDebugMode)
            IconButton(
              icon: const Icon(Icons.phone_callback),
              tooltip: 'Смоделировать входящий (dev)',
              onPressed: () => ref
                  .read(callControllerProvider.notifier)
                  .simulateIncomingCall(phone: '+79000000003', name: 'Борис'),
            ),
          if (isManager)
            IconButton(
              icon: const Icon(Icons.groups_outlined),
              tooltip: 'Доска команды',
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (_) => const ManagerBoardScreen(),
                ),
              ),
            ),
          IconButton(
            icon: const Icon(Icons.people_outline),
            tooltip: 'Контакты',
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(builder: (_) => const ContactsScreen()),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.history),
            tooltip: 'История звонков',
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(builder: (_) => const CallHistoryScreen()),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.settings_outlined),
            tooltip: 'Настройки',
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(builder: (_) => const SettingsScreen()),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.logout),
            tooltip: 'Выйти',
            onPressed: () => ref.read(authControllerProvider.notifier).logout(),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () => _refresh(context, ref),
        child: tasks.when(
          data: (items) => _TaskList(tasks: items),
          error: (error, stackTrace) => _Placeholder('Ошибка: $error'),
          loading: () => const Center(child: CircularProgressIndicator()),
        ),
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: () => Navigator.of(
          context,
        ).push(MaterialPageRoute<void>(builder: (_) => const DialerScreen())),
        tooltip: 'Новый звонок',
        child: const Icon(Icons.add_call),
      ),
    );
  }

  Future<void> _refresh(BuildContext context, WidgetRef ref) async {
    final messenger = ScaffoldMessenger.of(context);
    try {
      await ref.read(boardControllerProvider.notifier).refresh();
    } on ApiException catch (error) {
      messenger.showSnackBar(SnackBar(content: Text(error.message)));
    }
  }
}

/// Task sections in board order. Grouping/sorting lives in `domain/board.dart`.
class _TaskList extends StatelessWidget {
  const _TaskList({required this.tasks});

  final List<TaskItem> tasks;

  @override
  Widget build(BuildContext context) {
    if (tasks.isEmpty) {
      return const _Placeholder(
        'Пока нет задач. Потяните вниз, чтобы обновить.',
      );
    }
    final groups = groupForBoard(tasks, DateTime.now());
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      children: <Widget>[
        for (final bucket in TaskBucket.values)
          if ((groups[bucket] ?? const <TaskItem>[]).isNotEmpty) ...<Widget>[
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
              child: Text(
                bucket.label,
                style: Theme.of(context).textTheme.titleSmall,
              ),
            ),
            for (final task in groups[bucket]!) _TaskTile(task: task),
          ],
      ],
    );
  }
}

class _TaskTile extends ConsumerWidget {
  const _TaskTile({required this.task});

  final TaskItem task;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final overdue = task.status == TaskStatus.overdue;
    return ListTile(
      leading: Icon(
        overdue ? Icons.warning_amber : Icons.task_alt,
        color: overdue ? Theme.of(context).colorScheme.error : null,
      ),
      title: Text(task.title),
      subtitle: Text(
        '${formatDueDate(task.dueDate)} · ${taskPriorityLabel(task.priority)}',
      ),
      trailing: Chip(label: Text(taskStatusLabel(task.status))),
      onTap: () => showTaskActions(context, task),
    );
  }
}

class _Placeholder extends StatelessWidget {
  const _Placeholder(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      children: <Widget>[
        const SizedBox(height: 160),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 24),
          child: Text(text, textAlign: TextAlign.center),
        ),
      ],
    );
  }
}
