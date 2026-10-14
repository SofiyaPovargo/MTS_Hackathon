import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../application/providers.dart';
import 'screens/board_screen.dart';
import 'screens/call_screen.dart';
import 'screens/consent_screen.dart';
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
/// authenticated → consent gate, then the personal board.
class HomeGate extends ConsumerWidget {
  const HomeGate({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Retries offline-buffered recordings once a session is available.
    ref.watch(recordingRetryProvider);
    final session = ref.watch(authControllerProvider);
    return session.when(
      data: (value) => value == null ? const LoginScreen() : const AuthedGate(),
      error: (error, stackTrace) => const LoginScreen(),
      loading: () => const Scaffold(
        body: Center(child: CircularProgressIndicator()),
      ),
    );
  }
}

/// Authenticated area: the consent gate (until the app user decides on
/// recording/AI) then the board.
class AuthedGate extends ConsumerWidget {
  const AuthedGate({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final consent = ref.watch(consentControllerProvider);
    return consent.when(
      data: (value) =>
          value.decided ? const BoardScreen() : const ConsentScreen(),
      error: (error, stackTrace) => const ConsentScreen(),
      loading: () => const Scaffold(
        body: Center(child: CircularProgressIndicator()),
      ),
    );
  }
}
