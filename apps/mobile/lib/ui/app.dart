import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../application/providers.dart';
import 'screens/board_screen.dart';
import 'screens/call_screen.dart';
import 'screens/login_screen.dart';

class AgreementCaptureApp extends StatelessWidget {
  const AgreementCaptureApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Соглашения',
      theme: ThemeData(
        colorSchemeSeed: const Color(0xFF0A66C2),
        useMaterial3: true,
      ),
      home: const HomeGate(),
      builder: (context, child) =>
          CallOverlay(child: child ?? const SizedBox.shrink()),
    );
  }
}

/// Chooses the screen from the auth session state: unauthenticated → login,
/// authenticated → personal board.
class HomeGate extends ConsumerWidget {
  const HomeGate({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final session = ref.watch(authControllerProvider);
    return session.when(
      data: (value) => value == null ? const LoginScreen() : const BoardScreen(),
      error: (error, stackTrace) => const LoginScreen(),
      loading: () => const Scaffold(
        body: Center(child: CircularProgressIndicator()),
      ),
    );
  }
}
