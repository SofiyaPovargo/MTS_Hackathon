import '../../domain/ports.dart';
import '../../domain/schedule.dart';
import 'api_client.dart';

/// Call summary, calendar, reminders and message drafts over REST (plan.md §9).
class HttpScheduleApi implements ScheduleApi {
  HttpScheduleApi({required ApiClient client}) : _client = client;

  final ApiClient _client;

  @override
  Future<CallSummary> callSummary(String callId) async =>
      CallSummary.fromJson(asJsonMap(await _client.get('/calls/$callId/summary')));

  @override
  Future<CalendarEvent> createCalendarEvent(String taskId) async =>
      CalendarEvent.fromJson(
        asJsonMap(await _client.post('/tasks/$taskId/calendar')),
      );

  @override
  Future<String> ics(String taskId) => _client.getText('/tasks/$taskId/calendar.ics');

  @override
  Future<void> deleteCalendarEvent(String taskId) async {
    await _client.delete('/tasks/$taskId/calendar');
  }

  @override
  Future<Reminder> createReminder(
    String taskId, {
    required DateTime remindAt,
    ReminderChannel channel = ReminderChannel.push,
  }) async {
    final data = await _client.post(
      '/tasks/$taskId/reminders',
      body: <String, Object?>{
        'remind_at': remindAt.toUtc().toIso8601String(),
        'channel': channel.wire,
      },
    );
    return Reminder.fromJson(asJsonMap(data));
  }

  @override
  Future<List<Reminder>> reminders(String taskId) async {
    final data = await _client.get('/tasks/$taskId/reminders');
    return asJsonList(data).map(Reminder.fromJson).toList();
  }

  @override
  Future<Reminder> cancelReminder(String reminderId) async {
    final data = await _client.post('/reminders/$reminderId/cancel');
    return Reminder.fromJson(asJsonMap(data));
  }

  @override
  Future<MessageDraft> draftMessage(String taskId) async {
    final data = await _client.post('/tasks/$taskId/message-draft');
    return MessageDraft.fromJson(asJsonMap(data));
  }
}
