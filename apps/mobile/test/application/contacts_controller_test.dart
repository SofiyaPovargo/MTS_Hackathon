import 'package:agreement_capture/application/providers.dart';
import 'package:agreement_capture/domain/models.dart';
import 'package:agreement_capture/domain/ports.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fakes.dart';

void main() {
  test('denied permission yields allowed=false with no items', () async {
    final source = FakeContactsSource(
      result: const ContactsLoadResult(allowed: false, items: <ContactItem>[]),
    );
    final container = ProviderContainer(
      overrides: <Override>[contactsSourceProvider.overrideWithValue(source)],
    );
    addTearDown(container.dispose);

    final state = await container.read(contactsControllerProvider.future);

    expect(state.allowed, isFalse);
    expect(state.items, isEmpty);
  });

  test('allowed permission returns the contacts', () async {
    final source = FakeContactsSource(
      result: const ContactsLoadResult(
        allowed: true,
        items: <ContactItem>[
          ContactItem(id: '1', displayName: 'Борис', phone: '+79000000003'),
        ],
      ),
    );
    final container = ProviderContainer(
      overrides: <Override>[contactsSourceProvider.overrideWithValue(source)],
    );
    addTearDown(container.dispose);

    final state = await container.read(contactsControllerProvider.future);

    expect(state.allowed, isTrue);
    expect(state.items.single.displayName, 'Борис');
  });
}
