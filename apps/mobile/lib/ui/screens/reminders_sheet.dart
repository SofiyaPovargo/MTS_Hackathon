import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../application/providers.dart';
import '../../domain/models.dart';
import '../../domain/schedule.dart';
import '../formats.dart';

/// Opens the task's reminders: the scheduled ones with a cancel action, plus a
/// quick way to add one. Loading a reminder never writes to an external system;
/// creating one is an explicit user action (plan.md §9).
Future<void> showRemindersSheet(BuildContext context, TaskItem task) {
  return showModalBottomSheet<void>(
    context: context,
    showDragHandle: true,
    isScrollControlled: true,
    builder: (_) => _RemindersSheet(task: task),
  );
}

class _RemindersSheet extends ConsumerStatefulWidget {
  const _RemindersSheet({required this.task});

  final TaskItem task;

  @override
  ConsumerState<_RemindersSheet> createState() => _RemindersSheetState();
}

class _RemindersSheetState extends ConsumerState<_RemindersSheet> {
  bool _loading = true;
  String? _message;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final error = await ref
        .read(taskActionsControllerProvider.notifier)
        .loadReminders(widget.task.id);
    if (!mounted) return;
    setState(() {
      _loading = false;
      _message = error;
    });
  }

  Future<void> _add() async {
    final preset = await showDialog<ReminderPreset>(
      context: context,
      builder: (dialogContext) => SimpleDialog(
        title: const Text('Когда напомнить?'),
        children: <Widget>[
          for (final preset in ReminderPreset.values)
            SimpleDialogOption(
              onPressed: () => Navigator.of(dialogContext).pop(preset),
              child: Text(preset.label),
            ),
        ],
      ),
    );
    if (preset == null || !mounted) return;
    final remindAt = preset.resolve(DateTime.now());
    final error = await ref
        .read(taskActionsControllerProvider.notifier)
        .createReminder(widget.task.id, remindAt: remindAt);
    if (!mounted) return;
    final messenger = ScaffoldMessenger.of(context);
    messenger.showSnackBar(
      SnackBar(
        content: Text(
          error ?? 'Напоминание создано: ${formatDateTime(remindAt)}',
        ),
      ),
    );
  }

  Future<void> _cancel(Reminder reminder) async {
    final error = await ref
        .read(taskActionsControllerProvider.notifier)
        .cancelReminder(reminder.id);
    if (!mounted || error == null) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error)));
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final state = ref.watch(taskActionsControllerProvider);
    final reminders = state.reminders
        .where((reminder) => reminder.taskId == widget.task.id)
        .toList();
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            Text('Напоминания', style: theme.textTheme.titleMedium),
            const SizedBox(height: 4),
            Text(widget.task.title, style: theme.textTheme.bodySmall),
            if (_loading) const LinearProgressIndicator(),
            if (_message != null)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(
                  _message!,
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: theme.colorScheme.error),
                ),
              ),
            if (!_loading && reminders.isEmpty)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 16),
                child: Text('Напоминаний пока нет'),
              ),
            for (final reminder in reminders)
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.alarm),
                title: Text(formatDateTime(reminder.remindAt)),
                subtitle: Text(reminderStatusLabel(reminder.status)),
                trailing: reminder.status == ReminderStatus.scheduled
                    ? IconButton(
                        icon: const Icon(Icons.alarm_off),
                        tooltip: 'Отменить',
                        onPressed: () => _cancel(reminder),
                      )
                    : null,
              ),
            const Divider(height: 24),
            ListTile(
              leading: const Icon(Icons.alarm_add_outlined),
              title: const Text('Добавить напоминание'),
              onTap: _add,
            ),
          ],
        ),
      ),
    );
  }
}

/// Reminder presets offered when scheduling one.
enum ReminderPreset {
  inHour('Через час'),
  todayEvening('Сегодня в 19:00'),
  tomorrowMorning('Завтра в 9:00');

  const ReminderPreset(this.label);

  final String label;

  /// The concrete time for this preset, relative to [now].
  DateTime resolve(DateTime now) {
    switch (this) {
      case ReminderPreset.inHour:
        return now.add(const Duration(hours: 1));
      case ReminderPreset.todayEvening:
        final today = DateTime(now.year, now.month, now.day, 19);
        return today.isAfter(now) ? today : today.add(const Duration(days: 1));
      case ReminderPreset.tomorrowMorning:
        return DateTime(now.year, now.month, now.day + 1, 9);
    }
  }
}