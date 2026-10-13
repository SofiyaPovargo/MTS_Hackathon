import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../domain/models.dart';
import '../domain/ports.dart';
import 'providers.dart';

/// Holds the current session (`null` = unauthenticated) and drives the OTP
/// login flow. Widgets watch the state; no business logic lives in widgets.
class AuthController extends AsyncNotifier<AuthSession?> {
  AuthApi get _authApi => ref.read(authApiProvider);
  SessionStore get _sessionStore => ref.read(sessionStoreProvider);

  @override
  Future<AuthSession?> build() => _sessionStore.read();

  /// Sends the OTP. Errors propagate so the screen can show a message.
  Future<void> requestOtp(String phone) => _authApi.requestOtp(phone);

  Future<void> login({required String phone, required String otp}) async {
    state = const AsyncValue<AuthSession?>.loading();
    state = await AsyncValue.guard(() async {
      final result = await _authApi.login(phone: phone, otp: otp);
      return result.session;
    });
  }

  Future<void> logout() async {
    await _authApi.logout();
    state = const AsyncValue<AuthSession?>.data(null);
  }
}
