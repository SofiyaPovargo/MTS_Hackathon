import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../domain/models.dart';
import 'providers.dart';

/// Contacts state. When the permission is denied `allowed` is false and the UI
/// falls back to manual number entry (AGENTS.md).
class ContactsState {
  const ContactsState({required this.allowed, required this.items});

  static const ContactsState empty =
      ContactsState(allowed: true, items: <ContactItem>[]);

  final bool allowed;
  final List<ContactItem> items;
}

class ContactsController extends AsyncNotifier<ContactsState> {
  @override
  Future<ContactsState> build() async {
    final result = await ref.read(contactsSourceProvider).load();
    return ContactsState(allowed: result.allowed, items: result.items);
  }

  Future<void> reload() async {
    state = const AsyncValue<ContactsState>.loading();
    state = await AsyncValue.guard(() async {
      final result = await ref.read(contactsSourceProvider).load();
      return ContactsState(allowed: result.allowed, items: result.items);
    });
  }
}
