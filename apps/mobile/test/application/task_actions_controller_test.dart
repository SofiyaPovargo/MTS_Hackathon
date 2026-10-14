import 'package:agreement_capture/application/providers.dart';
import 'package:agreement_capture/domain/schedule.dart';
import 'package:agreement_capture/infrastructure/api/api_exception.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fakes.dart';

({ProviderContainer container, FakeScheduleApi api}) buildContainer({
  FakeScheduleApi? api,
}) {
  final schedule = api ?? FakeScheduleApi();
  final container = ProviderContainer(
    overrides: <Override>[scheduleApiProvider.overrideWithValue(schedule)],
  );
  return (container: container, api: schedule);
}

void main() {
  group('calendar', () {
    test('addToCalendar creates an event and stores it in the state', () async {
      final scope = buildContainer();
      addTearDown(scope.container.dispose);
      final controller = scope.container.read(taskActionsControllerProvider.notifier);

      final error = await controller.addToCalendar('t1');

      expect(error, isNull);
      expect(scope.api.calendarCalls, 1);
      final state = scope.container.read(taskActionsControllerProvider);
      expect(state.lastEvent?.taskId, 't1');
      expect(state.lastEvent?.title, isNotEmpty);
    });

    test('addToCalendar surfaces a server error', () async {
      final scope = buildContainer(
        api: FakeScheduleApi(
          error: const ApiException(ApiErrorKind.server, 'boom'),
        ),
      );
      addTearDown(scope.container.dispose);
      final controller = scope.container.read(taskActionsControllerProvider.notifier);

      expect(await controller.addToCalendar('t1'), 'boom');
      expect(
        scope.container.read(taskActionsControllerProvider).lastEvent,
        isNull,
      );
    });

    test('deleteFromCalendar succeeds when the endpoint exists', () async {
      final scope = buildContainer();
      addTearDown(scope.container.dispose);
      final controller = scope.container.read(taskActionsControllerProvider.notifier);

      expect(await controller.deleteFromCalendar('t1'), isNull);
      expect(scope.api.deleteCalls, 1);
    });

    test('deleteFromCalendar degrades gracefully on 404/405', () async {
      for (final status in <int>[404, 405]) {
        final scope = buildContainer(api: FakeScheduleApi(deleteStatus: status));
        addTearDown(scope.container.dispose);
        final controller =
            scope.container.read(taskActionsControllerProvider.notifier);

        expect(
          await controller.deleteFromCalendar('t1'),
          'Удаление события из календаря пока недоступно',
        );
        expect(scope.api.deleteCalls, 1);
      }
    });
  });

  group('reminders', () {
    test('createReminder passes the time/channel and appends to the state',
        () async {
      final scope = buildContainer();
      addTearDown(scope.container.dispose);
      final controller = scope.container.read(taskActionsControllerProvider.notifier);
      final remindAt = DateTime.utc(2026, 10, 16, 7);

      final error = await controller.createReminder(
        't1',
        remindAt: remindAt,
        channel: ReminderChannel.sms,
      );

      expect(error, isNull);
      expect(scope.api.reminderCalls, 1);
      expect(scope.api.lastRemindAt, remindAt);
      expect(scope.api.lastChannel, ReminderChannel.sms);
      final state = scope.container.read(taskActionsControllerProvider);
      expect(state.reminders, hasLength(1));
      expect(state.reminders.single.channel, ReminderChannel.sms);
    });

    test('loadReminders replaces the stored list', () async {
      final scope = buildContainer(
        api: FakeScheduleApi(
          storedReminders: <Reminder>[
            testReminder(id: 'r1'),
            testReminder(id: 'r2', taskId: 't2'),
          ],
        ),
      );
      addTearDown(scope.container.dispose);
      final controller = scope.container.read(taskActionsControllerProvider.notifier);

      expect(await controller.loadReminders('t1'), isNull);
      final state = scope.container.read(taskActionsControllerProvider);
      expect(state.reminders.map((r) => r.id), <String>['r1']);
      expect(scope.api.listReminderCalls, 1);
    });

    test('cancelReminder flips the reminder to canceled in the state', () async {
      final scope = buildContainer(
        api: FakeScheduleApi(
          storedReminders: <Reminder>[testReminder(id: 'r1')],
        ),
      );
      addTearDown(scope.container.dispose);
      final controller = scope.container.read(taskActionsControllerProvider.notifier);
      await controller.loadReminders('t1');

      expect(await controller.cancelReminder('r1'), isNull);

      final state = scope.container.read(taskActionsControllerProvider);
      expect(state.reminders.single.status, ReminderStatus.canceled);
      expect(scope.api.cancelCalls, 1);
    });
  });

  group('message draft', () {
    test('messageDraft returns the draft and stores it', () async {
      final scope = buildContainer();
      addTearDown(scope.container.dispose);
      final controller = scope.container.read(taskActionsControllerProvider.notifier);

      final draft = await controller.messageDraft('t1');

      expect(draft, isNotNull);
      expect(draft!.sent, isFalse);
      expect(draft.text, isNotEmpty);
      expect(scope.api.draftCalls, 1);
      expect(
        scope.container.read(taskActionsControllerProvider).draft?.draftId,
        draft.draftId,
      );
      expect(scope.container.read(taskActionsControllerProvider).error, isNull);
    });

    test('a failed draft returns null and records the error', () async {
      final scope = buildContainer(
        api: FakeScheduleApi(
          error: const ApiException(ApiErrorKind.network, 'offline'),
        ),
      );
      addTearDown(scope.container.dispose);
      final controller = scope.container.read(taskActionsControllerProvider.notifier);

      expect(await controller.messageDraft('t1'), isNull);
      expect(
        scope.container.read(taskActionsControllerProvider).error,
        'offline',
      );
    });
  });
}
