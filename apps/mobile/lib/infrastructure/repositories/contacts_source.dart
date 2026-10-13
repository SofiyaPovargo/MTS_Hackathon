import 'package:flutter_contacts/flutter_contacts.dart';

import '../../domain/models.dart';
import '../../domain/ports.dart';

/// Device contacts behind a [ContactsSource] port (AGENTS.md: no platform APIs
/// in feature code, and a graceful fallback when permission is denied).
///
/// On denial the caller receives `allowed = false` and the UI falls back to
/// manual number entry instead of failing.
class DeviceContactsSource implements ContactsSource {
  const DeviceContactsSource();

  @override
  Future<ContactsLoadResult> load() async {
    final allowed = await FlutterContacts.requestPermission();
    if (!allowed) {
      return const ContactsLoadResult(allowed: false, items: <ContactItem>[]);
    }
    final contacts = await FlutterContacts.getContacts(withProperties: true);
    final items = <ContactItem>[];
    for (final contact in contacts) {
      if (contact.phones.isEmpty) continue;
      final phone = contact.phones.first.number.trim();
      if (phone.isEmpty) continue;
      items.add(
        ContactItem(
          id: contact.id,
          displayName: contact.displayName.isEmpty ? phone : contact.displayName,
          phone: phone,
        ),
      );
    }
    return ContactsLoadResult(allowed: true, items: items);
  }
}
