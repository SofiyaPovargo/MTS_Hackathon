import 'package:agreement_capture/application/providers.dart';
import 'package:agreement_capture/domain/call.dart';
import 'package:agreement_capture/domain/enums.dart';
import 'package:agreement_capture/ui/screens/call_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fakes.dart';

Widget wrap(Widget child) {
  return ProviderScope(
    overrides: <Override>[
      voiceCallProviderProvider.overrideWithValue(FakeVoiceCallProvider()),
      callApiProvider.overrideWithValue(FakeCallApi()),
    ],
    child: MaterialApp(home: child),
  );
}

void main() {
  testWidgets('incoming call offers answer and decline', (tester) async {
    const call = CallState(
      status: CallLifecycleStatus.incoming,
      direction: CallDirection.inbound,
      phone: '+79000000003',
      name: 'Борис',
    );
    await tester.pumpWidget(wrap(const CallScreen(call: call)));
    await tester.pump();

    expect(find.text('Борис'), findsOneWidget);
    expect(find.text('Входящий вызов'), findsOneWidget);
    expect(find.byTooltip('Ответить'), findsOneWidget);
    expect(find.byTooltip('Отклонить'), findsOneWidget);
  });

  testWidgets('active call offers mute and hangup and a timer', (tester) async {
    final call = CallState(
      status: CallLifecycleStatus.inProgress,
      direction: CallDirection.outbound,
      phone: '+79000000002',
      name: 'Анна',
      answeredAt: DateTime.now(),
    );
    await tester.pumpWidget(wrap(CallScreen(call: call)));
    await tester.pump();

    expect(find.text('Разговор'), findsOneWidget);
    expect(find.byTooltip('Выключить микрофон'), findsOneWidget);
    expect(find.byTooltip('Завершить'), findsOneWidget);

    // Dispose the tree so the periodic timer is cancelled before teardown.
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('terminal call offers a close button', (tester) async {
    const call = CallState(
      status: CallLifecycleStatus.completed,
      direction: CallDirection.outbound,
      phone: '+79000000002',
    );
    await tester.pumpWidget(wrap(const CallScreen(call: call)));
    await tester.pump();

    expect(find.text('Звонок завершён'), findsOneWidget);
    expect(find.text('Закрыть'), findsOneWidget);
  });
}
