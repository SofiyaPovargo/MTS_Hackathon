import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../application/board_controller.dart';
import '../../application/providers.dart';
import '../../domain/enums.dart';
import '../../domain/models.dart';
import '../../domain/schedule.dart';
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
            const Divider(height: 24),
            // Calendar / reminder / client draft (plan.md §9). Every write is
            // confirmed first; the draft is never sent automatically.
            ListTile(
              leading: const Icon(Icons.event_available),
              title: const Text('Добавить в календарь'),
              onTap: () => _addToCalendar(context, ref),
            ),
            ListTile(
              leading: const Icon(Icons.event_busy),
              title: const Text('Удалить из календаря'),
              onTap: () => _deleteFromCalendar(context, ref),
            ),
            ListTile(
              leading: const Icon(Icons.sms_outlined),
              title: const Text('Черновик клиенту'),
              onTap: () => _messageDraft(context, ref),
            ),
            ListTile(
              leading: const Icon(Icons.alarm_add_outlined),
              title: const Text('Напоминание'),
              onTap: () => _createReminder(context, ref),
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

  /// Confirms an explicit action. Every calendar/reminder/draft write requires
  /// the user's confirmation (AGENTS.md: no external write without consent).
  Future<bool> _confirm(
    BuildContext context,
    String title,
    String message,
  ) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(title),
        content: Text(message),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('Отмена'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text('Подтвердить'),
          ),
        ],
      ),
    );
    return confirmed ?? false;
  }

  Future<void> _addToCalendar(BuildContext context, WidgetRef ref) async {
    final confirmed = await _confirm(
      context,
      'Добавить в календарь?',
      'Задача «${task.title}» будет добавлена в календарь.',
    );
    if (!confirmed || !context.mounted) return;
    final messenger = ScaffoldMessenger.of(context);
    final navigator = Navigator.of(context);
    final controller = ref.read(taskActionsControllerProvider.notifier);
    final error = await controller.addToCalendar(task.id);
    final event = ref.read(taskActionsControllerProvider).lastEvent;
    if (navigator.canPop()) navigator.pop();
    if (error != null) {
      messenger.showSnackBar(SnackBar(content: Text(error)));
      return;
    }
    messenger.showSnackBar(
      SnackBar(
        content: Text(
          'Событие создано: ${event?.title ?? task.title} · '
          '${formatDateTime(event?.startsAt)}',
        ),
      ),
    );
  }

  Future<void> _deleteFromCalendar(BuildContext context, WidgetRef ref) async {
    final confirmed = await _confirm(
      context,
      'Удалить из календаря?',
      'Событие задачи «${task.title}» будет удалено из календаря.',
    );
    if (!confirmed || !context.mounted) return;
    final messenger = ScaffoldMessenger.of(context);
    final navigator = Navigator.of(context);
    final controller = ref.read(taskActionsControllerProvider.notifier);
    final error = await controller.deleteFromCalendar(task.id);
    if (navigator.canPop()) navigator.pop();
    messenger.showSnackBar(
      SnackBar(
        content: Text(error ?? 'Событие удалено из календаря'),
      ),
    );
  }

  Future<void> _messageDraft(BuildContext context, WidgetRef ref) async {
    final confirmed = await _confirm(
      context,
      'Черновик сообщения клиенту?',
      'Будет создан черновик сообщения. Оно не отправляется автоматически.',
    );
    if (!confirmed || !context.mounted) return;
    final messenger = ScaffoldMessenger.of(context);
    final navigator = Navigator.of(context);
    final controller = ref.read(taskActionsControllerProvider.notifier);
    final draft = await controller.messageDraft(task.id);
    if (!context.mounted) return;
    if (draft == null) {
      final message = ref.read(taskActionsControllerProvider).error ??
          'Не удалось создать черновик';
      if (navigator.canPop()) navigator.pop();
      messenger.showSnackBar(SnackBar(content: Text(message)));
      return;
    }
    await showDialog<void>(
      context: context,
      builder: (_) => _DraftDialog(draft: draft),
    );
    if (navigator.canPop()) navigator.pop();
  }

  Future<void> _createReminder(BuildContext context, WidgetRef ref) async {
    final preset = await showDialog<_ReminderPreset>(
      context: context,
      builder: (dialogContext) => SimpleDialog(
        title: const Text('Напоминание'),
        children: <Widget>[
          for (final option in _ReminderPreset.values)
            SimpleDialogOption(
              onPressed: () => Navigator.of(dialogContext).pop(option),
              child: Text(option.label),
            ),
        ],
      ),
    );
    if (preset == null || !context.mounted) return;
    final remindAt = preset.resolve(DateTime.now());
    final messenger = ScaffoldMessenger.of(context);
    final navigator = Navigator.of(context);
    final controller = ref.read(taskActionsControllerProvider.notifier);
    final error = await controller.createReminder(task.id, remindAt: remindAt);
    if (navigator.canPop()) navigator.pop();
    if (error != null) {
      messenger.showSnackBar(SnackBar(content: Text(error)));
      return;
    }
    messenger.showSnackBar(
      SnackBar(content: Text('Напоминание создано: ${formatDateTime(remindAt)}')),
    );
  }
}

/// Reminder presets offered in the task actions sheet.
enum _ReminderPreset {
  inHour('Через час'),
  todayEvening('Сегодня в 19:00'),
  tomorrowMorning('Завтра в 9:00');

  const _ReminderPreset(this.label);

  final String label;

  /// The concrete time for this preset, relative to [now].
  DateTime resolve(DateTime now) {
    switch (this) {
      case _ReminderPreset.inHour:
        return now.add(const Duration(hours: 1));
      case _ReminderPreset.todayEvening:
        final today = DateTime(now.year, now.month, now.day, 19);
        return today.isAfter(now) ? today : today.add(const Duration(days: 1));
      case _ReminderPreset.tomorrowMorning:
        return DateTime(now.year, now.month, now.day + 1, 9);
    }
  }
}

/// The client-message draft. Explicitly labelled as not sent: the user sends it
/// themselves (AGENTS.md forbids automatic client messaging).
class _DraftDialog extends StatelessWidget {
  const _DraftDialog({required this.draft});

  final MessageDraft draft;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return AlertDialog(
      title: const Text('Черновик сообщения клиенту'),
      content: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Text(draft.phone, style: theme.textTheme.bodySmall),
            const SizedBox(height: 8),
            Text(draft.text),
            const SizedBox(height: 12),
            Text(
              'Сообщение не отправлено автоматически. Отправьте его сами.',
              style: theme.textTheme.bodySmall?.copyWith(
                fontStyle: FontStyle.italic,
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
          ],
        ),
      ),
      actions: <Widget>[
        TextButton.icon(
          onPressed: () async {
            await Clipboard.setData(ClipboardData(text: draft.text));
            if (context.mounted) {
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text('Скопировано')),
              );
            }
          },
          icon: const Icon(Icons.copy, size: 18),
          label: const Text('Копировать'),
        ),
        FilledButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Закрыть'),
        ),
      ],
    );
  }
}
