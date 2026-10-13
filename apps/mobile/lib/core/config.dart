import 'package:flutter/foundation.dart';

/// Environment-driven app configuration.
///
/// The backend URL comes from build configuration, never hardcoded in feature
/// code (AGENTS.md):
/// - Android emulator reaches the host via `10.0.2.2`;
/// - iOS simulator uses `localhost`;
/// - physical devices need the host's LAN IP or an HTTPS domain, passed with
///   `--dart-define=API_BASE_URL=https://...`.
class AppConfig {
  AppConfig({String? baseUrl}) : baseUrl = baseUrl ?? defaultBaseUrl;

  static const String _fromEnvironment = String.fromEnvironment('API_BASE_URL');

  static String get defaultBaseUrl {
    if (_fromEnvironment.isNotEmpty) {
      return _fromEnvironment;
    }
    if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android) {
      return 'http://10.0.2.2:8000/api';
    }
    return 'http://localhost:8000/api';
  }

  final String baseUrl;

  static const Duration requestTimeout = Duration(seconds: 15);
}