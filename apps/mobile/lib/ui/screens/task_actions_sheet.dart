import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../application/board_controller.dart';
import '../../application/providers.dart';
import '../../domain/enums.dart';
import '../../domain/models.dart';
import '../formats.dart';

/// Bottom sheet with the personal-board task actions (plan.md §14): start,
/// complete, reschedule, change priority, cancel. It also shows the link to the
/// source call/agreement. All actions go to [BoardController]; no logic here.
Future<void> showTaskActions(BuildContext context, TaskItem task) {
  return showModalBottomSheet<void>(
    context: context,
    showDragHandle: true,
    builder: (_) => _TaskActionsSheet(task: task),
  );
}

class _TaskActionsSheet extends ConsumerWidget {
  const _TaskActionsSheet({required this.task});

  final TaskItem task;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final controller = ref.read(boardControllerProvider.notifier);
    final open =
        task.status != TaskStatus.done && task.status != TaskStatus.canceled;
    return SafeArea(
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Text(task.title, style: theme.textTheme.titleMedium),
                  const SizedBox(height: 4),
                  Text(
                    '${taskStatusLabel(task.status)} · ${formatDueDate(task.dueDate)} · '
                    'Приоритет: ${taskPriorityLabel(task.priority)}',
                    style: theme.textTheme.bodySmall,
                  ),
                  if ((task.description ?? '').isNotEmpty) ...<Widget>[
                    const SizedBox(height: 8),
                    Text(
                      'Источник: ${task.description}',
                      style: theme.textTheme.bodySmall?.copyWith(
                        fontStyle: FontStyle.italic,
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ],
              ),
            ),
            const Divider(height: 24),
            if (open && task.status != TaskStatus.inProgress)
              ListTile(
                leading: const Icon(Icons.play_arrow),
                title: const Text('Взять в работу'),
                onTap: () => _run(context, () => controller.startTask(task.id)),
              ),
            if (open)
              ListTile(
                leading: const Icon(Icons.check),
                title: const Text('Отметить выполненной'),
                onTap: () =>
                    _run(context, () => controller.completeTask(task.id)),
              ),
            if (open)
              ListTile(
                leading: const Icon(Icons.event),
                title: const Text('Перенести срок'),
                onTap: () => _reschedule(context, controller),
              ),
            if (open)
              ListTile(
                leading: const Icon(Icons.flag_outlined),
                title: const Text('Изменить приоритет'),
                onTap: () => _priority(context, controller),
              ),
            if (open)
              ListTile(
                leading: const Icon(Icons.cancel_outlined),
                title: const Text('Отменить задачу'),
                onTap: () =>
                    _run(context, () => controller.cancelTask(task.id)),
              ),
          ],
        ),
      ),
    );
  }

  Future<void> _reschedule(
    BuildContext context,
    BoardController controller,
  ) async {
    final now = DateTime.now();
    final picked = await showDatePicker(
      context: context,
      initialDate: task.dueDate ?? now,
      firstDate: DateTime(now.year - 1),
      lastDate: DateTime(now.year + 5),
      helpText: 'Новый срок',
    );
    if (picked == null) return;
    if (!context.mounted) return;
    await _run(context, () => controller.rescheduleTask(task.id, picked));
  }

  Future<void> _priority(
    BuildContext context,
    BoardController controller,
  ) async {
    final chosen = await showDialog<TaskPriority>(
      context: context,
      builder: (dialogContext) => SimpleDialog(
        title: const Text('Приоритет'),
        children: <Widget>[
          for (final priority in TaskPriority.values)
            SimpleDialogOption(
              onPressed: () => Navigator.of(dialogContext).pop(priority),
              child: Text(taskPriorityLabel(priority)),
            ),
        ],
      ),
    );
    if (chosen == null) return;
    if (!context.mounted) return;
    await _run(context, () => controller.setPriority(task.id, chosen));
  }

  /// Runs an action, closes the sheet and surfaces an error, if any.
  Future<void> _run(
    BuildContext context,
    Future<String?> Function() action,
  ) async {
    final messenger = ScaffoldMessenger.of(context);
    final navigator = Navigator.of(context);
    final error = await action();
    if (navigator.canPop()) navigator.pop();
    if (error != null) {
      messenger.showSnackBar(SnackBar(content: Text(error)));
    }
  }
}
