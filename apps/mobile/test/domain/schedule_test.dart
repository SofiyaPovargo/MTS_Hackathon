import 'package:agreement_capture/domain/schedule.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('CallSummary parses the /calls/{id}/summary payload', () {
    final summary = CallSummary.fromJson(<String, dynamic>{
      'call_id': 'c1',
      'summary': 'Договорились оплатить счёт до пятницы.',
      'agreements_total': 3,
      'agreements_confirmed': 2,
    });

    expect(summary.callId, 'c1');
    expect(summary.summary, isNotEmpty);
    expect(summary.agreementsTotal, 3);
    expect(summary.agreementsConfirmed, 2);
  });

  test('CallSummary tolerates missing fields', () {
    final summary = CallSummary.fromJson(<String, dynamic>{});

    expect(summary.callId, '');
    expect(summary.summary, '');
    expect(summary.agreementsTotal, 0);
    expect(summary.agreementsConfirmed, 0);
  });

  test('CalendarEvent parses ISO-8601 start/end as local DateTime', () {
    final event = CalendarEvent.fromJson(<String, dynamic>{
      'task_id': 't1',
      'event_id': 'evt-1',
      'title': 'Позвонить клиенту',
      'starts_at': '2026-10-15T09:00:00Z',
      'ends_at': '2026-10-15T09:30:00Z',
    });

    expect(event.taskId, 't1');
    expect(event.eventId, 'evt-1');
    expect(event.title, 'Позвонить клиенту');
    expect(event.startsAt, isNotNull);
    expect(event.endsAt, isNotNull);
    expect(event.endsAt!.isAfter(event.startsAt!), isTrue);
  });

  test('CalendarEvent tolerates null dates', () {
    final event = CalendarEvent.fromJson(<String, dynamic>{
      'event_id': 'evt-1',
      'starts_at': null,
      'ends_at': null,
    });

    expect(event.taskId, '');
    expect(event.startsAt, isNull);
    expect(event.endsAt, isNull);
  });

  test('Reminder parses the reminder payload', () {
    final reminder = Reminder.fromJson(<String, dynamic>{
      'id': 'r1',
      'task_id': 't1',
      'remind_at': '2026-10-15T08:00:00Z',
      'channel': 'sms',
      'status': 'sent',
    });

    expect(reminder.id, 'r1');
    expect(reminder.taskId, 't1');
    expect(reminder.remindAt, isNotNull);
    expect(reminder.channel, ReminderChannel.sms);
    expect(reminder.status, ReminderStatus.sent);
  });

  test('Reminder falls back to safe enum defaults on unknown values', () {
    final reminder = Reminder.fromJson(<String, dynamic>{
      'id': 'r1',
      'task_id': 't1',
      'channel': 'telepathy',
      'status': 'weird',
    });

    expect(reminder.channel, ReminderChannel.push);
    expect(reminder.status, ReminderStatus.scheduled);
    expect(reminder.remindAt, isNull);
  });

  test('MessageDraft parses the draft payload and keeps sent=false', () {
    final draft = MessageDraft.fromJson(<String, dynamic>{
      'task_id': 't1',
      'draft_id': 'd1',
      'phone': '+79000000003',
      'text': 'Добрый день!',
      'sent': false,
    });

    expect(draft.taskId, 't1');
    expect(draft.draftId, 'd1');
    expect(draft.phone, '+79000000003');
    expect(draft.text, 'Добрый день!');
    expect(draft.sent, isFalse);
  });

  test('MessageDraft defaults sent to false when the field is absent', () {
    final draft = MessageDraft.fromJson(<String, dynamic>{
      'task_id': 't1',
      'draft_id': 'd1',
    });

    expect(draft.sent, isFalse);
    expect(draft.phone, '');
    expect(draft.text, '');
  });
}
