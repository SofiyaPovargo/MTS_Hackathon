import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../application/providers.dart';
import '../../domain/enums.dart';
import '../../domain/models.dart';
import '../formats.dart';
import 'call_detail_screen.dart';

/// The user's own call history (`GET /calls`), newest first. Tapping a call
/// opens its detail with the итог. Only the current user's calls are ever shown
/// (the server scopes the list to the owner).
class CallHistoryScreen extends ConsumerWidget {
  const CallHistoryScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final calls = ref.watch(callHistoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('История звонков')),
      body: RefreshIndicator(
        onRefresh: () => ref.read(callHistoryProvider.notifier).refresh(),
        child: calls.when(
          data: (items) => items.isEmpty
              ? const _Empty()
              : ListView.separated(
                  physics: const AlwaysScrollableScrollPhysics(),
                  itemCount: items.length,
                  separatorBuilder: (_, _) => const Divider(height: 1),
                  itemBuilder: (_, index) => _CallTile(call: items[index]),
                ),
          error: (error, _) => _Empty(text: 'Не удалось загрузить историю: $error'),
          loading: () => const Center(child: CircularProgressIndicator()),
        ),
      ),
    );
  }
}

class _CallTile extends StatelessWidget {
  const _CallTile({required this.call});

  final Call call;

  @override
  Widget build(BuildContext context) {
    final title = (call.contactName ?? '').isNotEmpty
        ? call.contactName!
        : call.contactPhone;
    final subtitle = <String>[
      callDirectionLabel(call.direction),
      formatDateTime(call.startedAt),
      if ((call.summary ?? '').isNotEmpty) call.summary!,
    ].join(' · ');
    return ListTile(
      leading: Icon(
        call.direction == CallDirection.inbound
            ? Icons.call_received
            : Icons.call_made,
      ),
      title: Text(title),
      subtitle: Text(subtitle, maxLines: 2, overflow: TextOverflow.ellipsis),
      trailing: Chip(label: Text(callStatusWireLabel(call.status))),
      onTap: () => Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) => CallDetailScreen(callId: call.id),
        ),
      ),
    );
  }
}

class _Empty extends StatelessWidget {
  const _Empty({this.text = 'Звонков пока нет'});

  final String text;

  @override
  Widget build(BuildContext context) {
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.all(32),
      children: <Widget>[
        Center(child: Text(text, textAlign: TextAlign.center)),
      ],
    );
  }
}
