import 'models.dart';

/// Call summary / calendar / reminder / message-draft models (plan.md §9).
///
/// Mirrors the backend Pydantic schemas (`CallSummaryOut`, `CalendarEventOut`,
/// `ReminderOut`, `MessageDraftOut`). Parsing is lenient: missing or nullable
/// fields fall back to safe defaults so a schema addition never crashes the
/// client. A message draft is only ever a draft — it is never sent to the
/// counterparty automatically.

/// Delivery channel of a reminder (backend `ReminderChannel`).
enum ReminderChannel {
  push('push'),
  local('local'),
  sms('sms');

  const ReminderChannel(this.wire);
  final String wire;

  static ReminderChannel fromWire(String? value) => ReminderChannel.values
      .firstWhere((c) => c.wire == value, orElse: () => ReminderChannel.push);
}

/// Lifecycle status of a reminder (backend `ReminderStatus`).
enum ReminderStatus {
  scheduled('scheduled'),
  sent('sent'),
  canceled('canceled'),
  failed('failed');

  const ReminderStatus(this.wire);
  final String wire;

  static ReminderStatus fromWire(String? value) => ReminderStatus.values
      .firstWhere((s) => s.wire == value, orElse: () => ReminderStatus.scheduled);
}

/// Итог звонка (`GET /calls/{id}/summary`, owner only).
class CallSummary {
  const CallSummary({
    required this.callId,
    required this.summary,
    required this.agreementsTotal,
    required this.agreementsConfirmed,
  });

  factory CallSummary.fromJson(Map<String, dynamic> json) => CallSummary(
    callId: json['call_id'] as String? ?? '',
    summary: json['summary'] as String? ?? '',
    agreementsTotal: (json['agreements_total'] as num?)?.toInt() ?? 0,
    agreementsConfirmed: (json['agreements_confirmed'] as num?)?.toInt() ?? 0,
  );

  final String callId;
  final String summary;
  final int agreementsTotal;
  final int agreementsConfirmed;
}

/// A calendar event created from a confirmed task
/// (`POST /tasks/{id}/calendar`). External writes only happen on an explicit
/// user action.
class CalendarEvent {
  const CalendarEvent({
    required this.taskId,
    required this.eventId,
    required this.title,
    this.startsAt,
    this.endsAt,
  });

  factory CalendarEvent.fromJson(Map<String, dynamic> json) => CalendarEvent(
    taskId: json['task_id'] as String? ?? '',
    eventId: json['event_id'] as String? ?? '',
    title: json['title'] as String? ?? '',
    startsAt: parseDate(json['starts_at'] as String?),
    endsAt: parseDate(json['ends_at'] as String?),
  );

  final String taskId;
  final String eventId;
  final String title;
  final DateTime? startsAt;
  final DateTime? endsAt;
}

/// A scheduled reminder (`POST/GET /tasks/{id}/reminders`).
class Reminder {
  const Reminder({
    required this.id,
    required this.taskId,
    this.remindAt,
    this.channel = ReminderChannel.push,
    this.status = ReminderStatus.scheduled,
  });

  factory Reminder.fromJson(Map<String, dynamic> json) => Reminder(
    id: json['id'] as String? ?? '',
    taskId: json['task_id'] as String? ?? '',
    remindAt: parseDate(json['remind_at'] as String?),
    channel: ReminderChannel.fromWire(json['channel'] as String?),
    status: ReminderStatus.fromWire(json['status'] as String?),
  );

  final String id;
  final String taskId;
  final DateTime? remindAt;
  final ReminderChannel channel;
  final ReminderStatus status;
}

/// A draft client message (`POST /tasks/{id}/message-draft`). [sent] is always
/// false: sending is the user's own action, never the app's.
class MessageDraft {
  const MessageDraft({
    required this.taskId,
    required this.draftId,
    required this.phone,
    required this.text,
    this.sent = false,
  });

  factory MessageDraft.fromJson(Map<String, dynamic> json) => MessageDraft(
    taskId: json['task_id'] as String? ?? '',
    draftId: json['draft_id'] as String? ?? '',
    phone: json['phone'] as String? ?? '',
    text: json['text'] as String? ?? '',
    sent: json['sent'] as bool? ?? false,
  );

  final String taskId;
  final String draftId;
  final String phone;
  final String text;
  final bool sent;
}
