import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../application/providers.dart';
import '../../domain/models.dart';

/// Device contacts with a graceful fallback: when the permission is denied the
/// screen offers manual number entry instead of failing (AGENTS.md).
class ContactsScreen extends ConsumerStatefulWidget {
  const ContactsScreen({super.key});

  @override
  ConsumerState<ContactsScreen> createState() => _ContactsScreenState();
}

class _ContactsScreenState extends ConsumerState<ContactsScreen> {
  final TextEditingController _searchController = TextEditingController();
  final TextEditingController _manualController = TextEditingController();
  final List<ContactItem> _manualItems = <ContactItem>[];
  String _query = '';

  @override
  void dispose() {
    _searchController.dispose();
    _manualController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final asyncContacts = ref.watch(contactsControllerProvider);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Контакты'),
        actions: <Widget>[
          IconButton(
            icon: const Icon(Icons.refresh),
            tooltip: 'Обновить',
            onPressed: () => ref.read(contactsControllerProvider.notifier).reload(),
          ),
        ],
      ),
      body: asyncContacts.when(
        data: (state) => state.allowed
            ? _buildList(<ContactItem>[...state.items, ..._manualItems])
            : _buildManualFallback(),
        error: (error, stackTrace) => _buildManualFallback(),
        loading: () => const Center(child: CircularProgressIndicator()),
      ),
    );
  }

  Widget _buildList(List<ContactItem> items) {
    final query = _query.toLowerCase();
    final filtered = query.isEmpty
        ? items
        : items
            .where((c) =>
                c.displayName.toLowerCase().contains(query) || c.phone.contains(query))
            .toList();
    return Column(
      children: <Widget>[
        Padding(
          padding: const EdgeInsets.all(12),
          child: TextField(
            controller: _searchController,
            onChanged: (value) => setState(() => _query = value),
            decoration: const InputDecoration(
              prefixIcon: Icon(Icons.search),
              hintText: 'Поиск по имени или номеру',
            ),
          ),
        ),
        Expanded(
          child: filtered.isEmpty
              ? const Center(child: Text('Контакты не найдены'))
              : ListView.builder(
                  itemCount: filtered.length,
                  itemBuilder: (context, index) {
                    final contact = filtered[index];
                    return ListTile(
                      leading: const Icon(Icons.person_outline),
                      title: Text(contact.displayName),
                      subtitle: Text(contact.phone),
                      trailing: IconButton(
                        icon: const Icon(Icons.call),
                        tooltip: 'Позвонить',
                        onPressed: () => _call(contact),
                      ),
                    );
                  },
                ),
        ),
      ],
    );
  }

  Widget _buildManualFallback() {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: <Widget>[
        const Text(
          'Доступ к контактам не разрешён. Введите номер вручную.',
        ),
        const SizedBox(height: 16),
        Row(
          children: <Widget>[
            Expanded(
              child: TextField(
                controller: _manualController,
                keyboardType: TextInputType.phone,
                decoration: const InputDecoration(hintText: '+79000000002'),
              ),
            ),
            const SizedBox(width: 8),
            FilledButton(onPressed: _addManual, child: const Text('Добавить')),
          ],
        ),
        const SizedBox(height: 16),
        ..._manualItems.map(
          (contact) => ListTile(
            leading: const Icon(Icons.person_add_alt),
            title: Text(contact.displayName),
            subtitle: Text(contact.phone),
            trailing: IconButton(
              icon: const Icon(Icons.call),
              tooltip: 'Позвонить',
              onPressed: () => _call(contact),
            ),
          ),
        ),
      ],
    );
  }

  void _addManual() {
    final phone = _manualController.text.trim();
    if (phone.isEmpty) return;
    setState(() {
      if (!_manualItems.any((c) => c.phone == phone)) {
        _manualItems.add(ContactItem(id: phone, displayName: phone, phone: phone));
      }
      _manualController.clear();
    });
  }

  /// Places an outgoing call; a failure (no permission, backend down) is shown
  /// as a message and the screen stays put.
  Future<void> _call(ContactItem contact) async {
    final error = await ref
        .read(callControllerProvider.notifier)
        .startOutgoing(contact.phone, name: contact.displayName);
    if (!mounted || error == null) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error)));
  }
}
