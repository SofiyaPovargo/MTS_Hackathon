import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../application/providers.dart';
import '../../domain/models.dart';
import '../../domain/schedule.dart';
import '../formats.dart';

/// A single call with its итог (`GET /calls/{id}`, `/calls/{id}/summary`).
///
/// Reached from the call history and from "перейти к звонку-источнику" on a task.
/// Read-only: the manager never sees another user's call, and no external system
/// is written from here (AGENTS.md).
class CallDetailScreen extends ConsumerWidget {
  const CallDetailScreen({super.key, required this.callId});

  final String callId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final call = ref.watch(callDetailProvider(callId));
    final summary = ref.watch(callSummaryProvider(callId));
    return Scaffold(
      appBar: AppBar(title: const Text('Звонок')),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(callDetailProvider(callId));
          ref.invalidate(callSummaryProvider(callId));
          await ref.read(callSummaryProvider(callId).future);
        },
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(16),
          children: <Widget>[
            call.when(
              data: (value) => _CallHeader(call: value),
              loading: () => const Center(
                child: Padding(
                  padding: EdgeInsets.all(24),
                  child: CircularProgressIndicator(),
                ),
              ),
              error: (error, _) => _Message('Не удалось загрузить звонок: $error'),
            ),
            const SizedBox(height: 24),
            Text('Сводка', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            summary.when(
              data: (value) => _SummaryCard(summary: value),
              loading: () => const Center(
                child: Padding(
                  padding: EdgeInsets.all(24),
                  child: CircularProgressIndicator(),
                ),
              ),
              error: (error, _) => _Message('Сводка пока недоступна: $error'),
            ),
          ],
        ),
      ),
    );
  }
}

class _CallHeader extends StatelessWidget {
  const _CallHeader({required this.call});

  final Call call;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final title = call.contactName?.isNotEmpty ?? false
        ? call.contactName!
        : call.contactPhone;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text(title, style: theme.textTheme.titleLarge),
        const SizedBox(height: 4),
        Text(call.contactPhone, style: theme.textTheme.bodyMedium),
        const SizedBox(height: 12),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: <Widget>[
            Chip(label: Text(callDirectionLabel(call.direction))),
            Chip(label: Text(callStatusWireLabel(call.status))),
          ],
        ),
        const SizedBox(height: 12),
        Text('Начало: ${formatDateTime(call.startedAt)}'),
        if (call.endedAt != null)
          Text('Завершён: ${formatDateTime(call.endedAt)}'),
      ],
    );
  }
}

class _SummaryCard extends StatelessWidget {
  const _SummaryCard({required this.summary});

  final CallSummary summary;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            if (summary.summary.isEmpty)
              const Text('Сводка пока не готова')
            else
              Text(summary.summary),
            const SizedBox(height: 12),
            Text(
              'Соглашений: ${summary.agreementsConfirmed} из '
              '${summary.agreementsTotal} подтверждено',
              style: theme.textTheme.bodySmall,
            ),
          ],
        ),
      ),
    );
  }
}

class _Message extends StatelessWidget {
  const _Message(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 16),
      child: Text(text),
    );
  }
}
