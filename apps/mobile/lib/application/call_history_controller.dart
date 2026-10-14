import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../domain/models.dart';
import 'providers.dart';

/// The user's recent calls (`GET /calls`); owner-scoped on the server.
///
/// Only the user's own calls are returned; the manager board never exposes
/// another employee's call history. Read-only — nothing is cached in SQLite.
class CallHistoryController extends AsyncNotifier<List<Call>> {
  @override
  Future<List<Call>> build() => ref.watch(callApiProvider).calls();

  Future<void> refresh() async {
    state = const AsyncValue<List<Call>>.loading();
    state = await AsyncValue.guard(() => ref.read(callApiProvider).calls());
  }
}
