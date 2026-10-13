import '../../domain/models.dart';
import '../../domain/ports.dart';
import 'api_client.dart';
import 'api_exception.dart';

/// Backend auth endpoints (`/auth/*`). On login the session is persisted to the
/// local store; `refreshSession` rotates the refresh token and re-persists.
class HttpAuthApi implements AuthApi {
  HttpAuthApi({required ApiClient client, required SessionStore sessionStore})
      : _client = client,
        _sessionStore = sessionStore;

  final ApiClient _client;
  final SessionStore _sessionStore;

  @override
  Future<void> requestOtp(String phone) async {
    await _client.post('/auth/otp/request', body: {'phone': phone}, auth: false);
  }

  @override
  Future<AuthResult> login({required String phone, required String otp}) async {
    final data = await _client.post(
      '/auth/login',
      body: {'phone': phone, 'otp': otp},
      auth: false,
    );
    final session = AuthSession.fromJson(asJsonMap(data));
    await _sessionStore.save(session);
    return AuthResult(session: session);
  }

  @override
  Future<void> logout() async {
    try {
      await _client.post('/auth/logout');
    } on ApiException {
      // Local logout must succeed even if the server call fails.
    } finally {
      await _sessionStore.clear();
    }
  }

  @override
  Future<AuthSession?> refreshSession() async {
    final current = await _sessionStore.read();
    if (current == null) return null;
    try {
      final data = await _client.post(
        '/auth/refresh',
        body: {'refresh_token': current.refreshToken},
        auth: false,
      );
      final session = AuthSession.fromJson(asJsonMap(data));
      await _sessionStore.save(session);
      return session;
    } on ApiException {
      await _sessionStore.clear();
      return null;
    }
  }
}