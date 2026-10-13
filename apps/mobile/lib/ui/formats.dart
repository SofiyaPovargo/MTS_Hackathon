import 'package:intl/intl.dart';

import '../domain/enums.dart';

final DateFormat _dueDateFormat = DateFormat('dd.MM.yyyy');

/// Formats a due date for display. The MVP language is Russian; localization is
/// wired through [MaterialApp] later.
String formatDueDate(DateTime? date) =>
    date == null ? 'без срока' : _dueDateFormat.format(date.toLocal());

String taskStatusLabel(TaskStatus status) => switch (status) {
      TaskStatus.newTask => 'Новая',
      TaskStatus.inProgress => 'В работе',
      TaskStatus.done => 'Готово',
      TaskStatus.overdue => 'Просрочена',
      TaskStatus.canceled => 'Отменена',
    };

String callStatusLabel(CallLifecycleStatus status) => switch (status) {
      CallLifecycleStatus.incoming => 'Входящий вызов',
      CallLifecycleStatus.ringing => 'Вызов…',
      CallLifecycleStatus.answered => 'Соединение установлено',
      CallLifecycleStatus.consentNotice => 'Уведомление о записи',
      CallLifecycleStatus.consentResult => 'Согласие',
      CallLifecycleStatus.recording => 'Идёт запись',
      CallLifecycleStatus.analyzing => 'Анализ разговора',
      CallLifecycleStatus.inProgress => 'Разговор',
      CallLifecycleStatus.completed => 'Звонок завершён',
      CallLifecycleStatus.missed => 'Пропущенный звонок',
      CallLifecycleStatus.failed => 'Ошибка соединения',
    };
