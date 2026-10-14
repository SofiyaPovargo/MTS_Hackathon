import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../domain/ports.dart';
import '../domain/schedule.dart';
import '../infrastructure/api/api_exception.dart';
import 'providers.dart';

/// Result of the task actions: the last created calendar event, the task's
/// reminders, the last generated message draft and the last error (for the
/// `messageDraft` path, whose return value is the draft itself).
class TaskActionsState {
  const TaskActionsState({
    this.lastEvent,
    this.reminders = const <Reminder>[],
    this.draft,
    this.error,
  });

  final CalendarEvent? lastEvent;
  final List<Reminder> reminders;
  final MessageDraft? draft;
  final String? error;

  TaskActionsState copyWith({
    CalendarEvent? lastEvent,
    List<Reminder>? reminders,
    MessageDraft? draft,
    String? error,
    bool clearError = false,
  }) {
    return TaskActionsState(
      lastEvent: lastEvent ?? this.lastEvent,
      reminders: reminders ?? this.reminders,
      draft: draft ?? this.draft,
      error: clearError ? null : (error ?? this.error),
    );
  }
}

/// Calendar / reminder / client-draft actions for a confirmed task (plan.md §9).
///
/// Every method is an explicit user action behind a confirmation in the UI; the
/// message draft is never sent automatically. Methods return a user-facing error
/// string, or `null` on success (message drafts are returned as a value instead,
/// with the error kept on [TaskActionsState.error]).
class TaskActionsController extends Notifier<TaskActionsState> {
  ScheduleApi get _api => ref.read(scheduleApiProvider);

  @override
  TaskActionsState build() => const TaskActionsState();

  /// Writes the task into the calendar (`POST /tasks/{id}/calendar`).
  Future<String?> addToCalendar(String taskId) async {
    try {
      final event = await _api.createCalendarEvent(taskId);
      state = state.copyWith(lastEvent: event, clearError: true);
      return null;
    } on ApiException catch (error) {
      state = state.copyWith(error: error.message);
      return error.message;
    }
  }

  /// Removes the task's calendar event (`DELETE /tasks/{id}/calendar`).
  ///
  /// The backend endpoint is not merged yet, so a 404/405 is treated as an
  /// expected, friendly message rather than an error.
  Future<String?> deleteFromCalendar(String taskId) async {
    try {
      await _api.deleteCalendarEvent(taskId);
      state = state.copyWith(clearError: true);
      return null;
    } on ApiException catch (error) {
      if (error.statusCode == 404 || error.statusCode == 405) {
        const message = 'Удаление события из календаря пока недоступно';
        state = state.copyWith(error: message);
        return message;
      }
      state = state.copyWith(error: error.message);
      return error.message;
    }
  }

  /// Builds a client-message draft. Returns `null` on failure (the message is on
  /// [TaskActionsState.error]); the draft is never sent automatically.
  Future<MessageDraft?> messageDraft(String taskId) async {
    try {
      final draft = await _api.draftMessage(taskId);
      state = state.copyWith(draft: draft, clearError: true);
      return draft;
    } on ApiException catch (error) {
      state = state.copyWith(error: error.message);
      return null;
    }
  }

  /// Schedules a reminder (`POST /tasks/{id}/reminders`).
  Future<String?> createReminder(
    String taskId, {
    required DateTime remindAt,
    ReminderChannel channel = ReminderChannel.push,
  }) async {
    try {
      final reminder = await _api.createReminder(
        taskId,
        remindAt: remindAt,
        channel: channel,
      );
      state = state.copyWith(
        reminders: <Reminder>[...state.reminders, reminder],
        clearError: true,
      );
      return null;
    } on ApiException catch (error) {
      state = state.copyWith(error: error.message);
      return error.message;
    }
  }

  /// Loads the task's reminders (`GET /tasks/{id}/reminders`).
  Future<String?> loadReminders(String taskId) async {
    try {
      final list = await _api.reminders(taskId);
      state = state.copyWith(reminders: list, clearError: true);
      return null;
    } on ApiException catch (error) {
      state = state.copyWith(error: error.message);
      return error.message;
    }
  }

  /// Cancels a reminder (`POST /reminders/{id}/cancel`).
  Future<String?> cancelReminder(String reminderId) async {
    try {
      final canceled = await _api.cancelReminder(reminderId);
      state = state.copyWith(
        reminders: <Reminder>[
          for (final reminder in state.reminders)
            if (reminder.id == reminderId) canceled else reminder,
        ],
        clearError: true,
      );
      return null;
    } on ApiException catch (error) {
      state = state.copyWith(error: error.message);
      return error.message;
    }
  }
}
