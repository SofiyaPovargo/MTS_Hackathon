import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../application/providers.dart';
import '../../infrastructure/api/api_exception.dart';

/// Two-step OTP login: phone → code. On success the [HomeGate] swaps to the
/// board, so this screen never navigates manually.
class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final TextEditingController _phoneController = TextEditingController(text: '+7');
  final TextEditingController _otpController = TextEditingController();
  String? _error;
  bool _otpRequested = false;
  bool _busy = false;

  @override
  void dispose() {
    _phoneController.dispose();
    _otpController.dispose();
    super.dispose();
  }

  Future<void> _requestOtp() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref
          .read(authControllerProvider.notifier)
          .requestOtp(_phoneController.text.trim());
      if (mounted) setState(() => _otpRequested = true);
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _login() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    await ref.read(authControllerProvider.notifier).login(
          phone: _phoneController.text.trim(),
          otp: _otpController.text.trim(),
        );
    if (mounted) setState(() => _busy = false);
  }

  @override
  Widget build(BuildContext context) {
    // A failed login is surfaced from the controller state.
    final asyncError = ref.watch(authControllerProvider).error;
    final message = _error ?? _errorMessage(asyncError);
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: <Widget>[
                Text(
                  'Захват соглашений',
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
                const SizedBox(height: 24),
                TextField(
                  controller: _phoneController,
                  enabled: !_otpRequested && !_busy,
                  keyboardType: TextInputType.phone,
                  decoration: const InputDecoration(
                    labelText: 'Телефон',
                    hintText: '+79000000002',
                  ),
                ),
                if (_otpRequested) ...<Widget>[
                  const SizedBox(height: 16),
                  TextField(
                    controller: _otpController,
                    enabled: !_busy,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                      labelText: 'Код из SMS',
                      hintText: '1234',
                    ),
                  ),
                ],
                const SizedBox(height: 24),
                FilledButton(
                  onPressed: _busy ? null : (_otpRequested ? _login : _requestOtp),
                  child: _busy
                      ? const SizedBox(
                          height: 20,
                          width: 20,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : Text(_otpRequested ? 'Войти' : 'Получить код'),
                ),
                if (message != null) ...<Widget>[
                  const SizedBox(height: 16),
                  Text(
                    message,
                    textAlign: TextAlign.center,
                    style: TextStyle(color: Theme.of(context).colorScheme.error),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }

  String? _errorMessage(Object? error) {
    if (error == null) return null;
    if (error is ApiException) return error.message;
    return 'Не удалось выполнить вход';
  }
}
