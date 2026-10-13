import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../domain/consent.dart';
import '../domain/enums.dart';
import '../domain/ports.dart';
import '../infrastructure/api/api_exception.dart';
import 'providers.dart';

/// The app user's recording / AI-consent. Local-first: the decision is cached
/// on the device and pushed to the server; a decision with `synced == false`
/// has not been accepted by the server yet (offline) and can be retried.
class ConsentController extends AsyncNotifier<AppConsent> {
  ConsentStore get _store => ref.read(consentStoreProvider);
  ConsentApi get _api => ref.read(consentApiProvider);

  @override
  Future<AppConsent> build() => _store.read();

  /// User agreed to recording + AI processing.
  Future<String?> grant() => _push(ConsentStatus.granted);

  /// User disabled recording/AI (calls stay ordinary; manual entry offered).
  Future<String?> deny() => _push(ConsentStatus.denied);

  /// Withdraws consent: recording stops and the server records the withdrawal.
  Future<String?> withdraw() => _push(ConsentStatus.withdrawn);

  /// Retries a local decision that the server has not accepted yet.
  Future<String?> retrySync() async {
    // The controller may not have built yet (nothing watched it).
    final current = state.valueOrNull ?? await _store.read();
    if (!current.decided || current.synced) {
      return null;
    }
    return _push(current.status!);
  }

  /// Requests the real data-deletion job. Returns an error message or null.
  Future<String?> requestDataDeletion() async {
    try {
      await _api.requestDataDeletion();
      return null;
    } on ApiException catch (error) {
      return error.message;
    }
  }

  Future<String?> _push(ConsentStatus status) async {
    final local = AppConsent(status: status);
    await _store.save(local);
    state = AsyncValue<AppConsent>.data(local);
    try {
      final record = status == ConsentStatus.withdrawn
          ? await _api.withdrawConsent()
          : await _api.setAppConsent(status == ConsentStatus.granted);
      final synced =
          AppConsent(status: record.status, synced: true);
      await _store.save(synced);
      state = AsyncValue<AppConsent>.data(synced);
      return null;
    } on ApiException catch (error) {
      // Local decision stays in effect; the UI shows the pending state.
      return 'Сохранено на устройстве, синхронизация не удалась: ${error.message}';
    }
  }
}