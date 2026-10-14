import 'package:agreement_capture/application/providers.dart';
import 'package:agreement_capture/domain/enums.dart';
import 'package:agreement_capture/domain/models.dart';
import 'package:agreement_capture/ui/screens/call_history_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fakes.dart';

Future<void> pumpHistory(
  WidgetTester tester, {
  required FakeCallApi callApi,
  FakeScheduleApi? scheduleApi,
}) async {
  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[
        callApiProvider.overrideWithValue(callApi),
        scheduleApiProvider.overrideWithValue(scheduleApi ?? FakeScheduleApi()),
      ],
      child: const MaterialApp(home: CallHistoryScreen()),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('the history lists the user\'s calls and opens the detail',
      (tester) async {
    final callApi = FakeCallApi(
      history: <Call>[
        testCall(
          id: 'c1',
          direction: CallDirection.inbound,
          status: 'completed',
        ),
      ],
    );
    final schedule = FakeScheduleApi(
      summary: testCallSummary(callId: 'c1', summary: 'Оплатить счёт до пятницы'),
    );
    await pumpHistory(tester, callApi: callApi, scheduleApi: schedule);

    expect(callApi.listCalls, 1);
    expect(find.text('Анна'), findsOneWidget);
    expect(find.text('Завершён'), findsOneWidget);

    await tester.tap(find.text('Анна'));
    await tester.pumpAndSettle();

    // The detail screen fetches the call and its итог.
    expect(find.text('Сводка'), findsOneWidget);
    expect(schedule.summaryCalls, 1);
    expect(find.textContaining('Оплатить счёт до пятницы'), findsOneWidget);
  });

  testWidgets('an empty history shows a placeholder', (tester) async {
    await pumpHistory(tester, callApi: FakeCallApi());

    expect(find.text('Звонков пока нет'), findsOneWidget);
  });
}
