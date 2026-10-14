import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../application/call_controller.dart';
import '../../application/providers.dart';
import '../../domain/call.dart';
import '../../domain/enums.dart';
import '../../domain/models.dart';
import '../../domain/schedule.dart';
import '../../domain/ws_event.dart';
import '../formats.dart';
import 'agreement_edit_dialog.dart';

/// Full-screen call UI layered above the whole app so an incoming call is shown
/// regardless of the current screen. No business logic lives here.
class CallOverlay extends ConsumerWidget {
  const CallOverlay({required this.child, super.key});

  final Widget child;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final call = ref.watch(callControllerProvider);
    return Stack(
      children: <Widget>[
        child,
        if (call != null) Positioned.fill(child: CallScreen(call: call)),
      ],
    );
  }
}

/// Active / incoming call screen. The state comes from the controller; the
/// screen only renders it and forwards taps.
class CallScreen extends ConsumerWidget {
  const CallScreen({required this.call, super.key});

  final CallState call;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final controller = ref.read(callControllerProvider.notifier);
    return Material(
      color: Theme.of(context).colorScheme.surface,
      child: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            children: <Widget>[
              const Spacer(),
              CircleAvatar(
                radius: 44,
                child: Text(
                  _initials(call),
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
              ),
              const SizedBox(height: 16),
              Text(
                call.displayName,
                style: Theme.of(context).textTheme.headlineSmall,
                textAlign: TextAlign.center,
              ),
              if (call.name != null && call.name!.isNotEmpty) ...<Widget>[
                const SizedBox(height: 4),
                Text(call.phone, style: Theme.of(context).textTheme.bodyMedium),
              ],
              const SizedBox(height: 12),
              Text(
                callStatusLabel(call.status),
                style: Theme.of(context).textTheme.titleMedium,
              ),
              if (call.isConnected) ...<Widget>[
                const SizedBox(height: 4),
                _CallTimer(call: call),
              ],
              if (call.muted) ...<Widget>[
                const SizedBox(height: 8),
                const Text('Микрофон выключен'),
              ],
              if (call.participantDeclined) ...<Widget>[
                const SizedBox(height: 8),
                const Text('Собеседник отказался от записи'),
              ],
              if (call.isConnected && !call.participantDeclined) ...<Widget>[
                const SizedBox(height: 8),
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: <Widget>[
                    Icon(
                      Icons.fiber_manual_record,
                      size: 12,
                      color: call.recordingEnabled
                          ? Colors.red
                          : Theme.of(context).colorScheme.outline,
                    ),
                    const SizedBox(width: 6),
                    Text(
                      call.recordingEnabled
                          ? 'Идёт запись'
                          : 'Запись выключена — договорённости вручную',
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                ),
              ],
              if (_liveCardVisible(call))
                Flexible(child: _LiveCard(call: call, controller: controller))
              else
                const Spacer(),
              _CallActions(call: call, controller: controller),
              const SizedBox(height: 12),
            ],
          ),
        ),
      ),
    );
  }

  String _initials(CallState call) {
    final source = call.displayName.trim();
    if (source.isEmpty) return '?';
    final parts = source.split(RegExp(r'\s+'));
    if (parts.length == 1) return parts.first.substring(0, 1).toUpperCase();
    return (parts.first.substring(0, 1) + parts.last.substring(0, 1)).toUpperCase();
  }

  /// Whether the live card may appear: not for an incoming/ringing/declined
  /// call, but already during the call (transcript/agreements) and as a recap
  /// after a completed one. On the no-consent path it offers manual entry.
  bool _liveCardVisible(CallState call) {
    if (call.status == CallLifecycleStatus.incoming ||
        call.status == CallLifecycleStatus.ringing ||
        call.status == CallLifecycleStatus.missed ||
        call.status == CallLifecycleStatus.failed) {
      return false;
    }
    return call.transcript.isNotEmpty ||
        call.agreements.isNotEmpty ||
        call.callSummary != null ||
        (call.isConnected && !call.recordingEnabled);
  }
}

class _CallActions extends StatelessWidget {
  const _CallActions({required this.call, required this.controller});

  final CallState call;
  final CallController controller;

  @override
  Widget build(BuildContext context) {
    if (call.status == CallLifecycleStatus.incoming) {
      return Row(
        mainAxisAlignment: MainAxisAlignment.spaceEvenly,
        children: <Widget>[
          _RoundAction(
            icon: Icons.call_end,
            color: Colors.red,
            tooltip: 'Отклонить',
            onTap: controller.declineIncoming,
          ),
          _RoundAction(
            icon: Icons.call,
            color: Colors.green,
            tooltip: 'Ответить',
            onTap: controller.answerIncoming,
          ),
        ],
      );
    }
    if (call.isTerminal) {
      return FilledButton(onPressed: controller.clear, child: const Text('Закрыть'));
    }
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceEvenly,
      children: <Widget>[
        _RoundAction(
          icon: call.muted ? Icons.mic_off : Icons.mic,
          tooltip: call.muted ? 'Включить микрофон' : 'Выключить микрофон',
          onTap: controller.toggleMute,
        ),
        _RoundAction(
          icon: Icons.call_end,
          color: Colors.red,
          tooltip: 'Завершить',
          onTap: controller.hangup,
        ),
      ],
    );
  }
}

class _RoundAction extends StatelessWidget {
  const _RoundAction({
    required this.icon,
    required this.tooltip,
    required this.onTap,
    this.color,
  });

  final IconData icon;
  final String tooltip;
  final VoidCallback onTap;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: tooltip,
      child: FloatingActionButton(
        heroTag: null,
        backgroundColor: color,
        onPressed: onTap,
        child: Icon(icon),
      ),
    );
  }
}

/// Elapsed time since the call connected, refreshed every second.
class _CallTimer extends StatefulWidget {
  const _CallTimer({required this.call});

  final CallState call;

  @override
  State<_CallTimer> createState() => _CallTimerState();
}

class _CallTimerState extends State<_CallTimer> {
  Timer? _timer;
  Duration _elapsed = Duration.zero;

  @override
  void initState() {
    super.initState();
    _elapsed = _current();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() => _elapsed = _current());
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Duration _current() {
    final start = widget.call.answeredAt ?? widget.call.startedAt ?? DateTime.now();
    final end = widget.call.endedAt ?? DateTime.now();
    final diff = end.difference(start);
    return diff.isNegative ? Duration.zero : diff;
  }

  @override
  Widget build(BuildContext context) {
    final minutes = _elapsed.inMinutes.remainder(60).toString().padLeft(2, '0');
    final seconds = _elapsed.inSeconds.remainder(60).toString().padLeft(2, '0');
    return Text('$minutes:$seconds', style: Theme.of(context).textTheme.titleMedium);
  }
}

/// Scrollable live area: transcript lines, agreement cards and the manual-entry
/// action on the no-consent path. Pure rendering; actions go to the controller.
class _LiveCard extends StatelessWidget {
  const _LiveCard({required this.call, required this.controller});

  final CallState call;
  final CallController controller;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final segments = _lastSegments(call.transcript);
    return ListView(
      shrinkWrap: true,
      padding: const EdgeInsets.only(bottom: 8),
      children: <Widget>[
        if (call.callSummary != null) ...<Widget>[
          _CallSummaryCard(
            summary: call.callSummary!,
            onRefresh: () => _refreshSummary(context),
          ),
          const SizedBox(height: 8),
        ],
        if (call.agreements.isNotEmpty) ...<Widget>[
          for (final agreement in call.agreements) ...<Widget>[
            _AgreementCard(agreement: agreement, controller: controller),
            const SizedBox(height: 8),
          ],
        ],
        if (segments.isNotEmpty) ...<Widget>[
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Text('Разговор', style: theme.textTheme.labelLarge),
                  const SizedBox(height: 4),
                  for (final segment in segments)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 2),
                      child: Text.rich(
                        TextSpan(
                          children: <InlineSpan>[
                            TextSpan(
                              text: '${_speakerLabel(segment.speaker)}: ',
                              style: TextStyle(
                                fontWeight: FontWeight.w600,
                                color: theme.colorScheme.primary,
                              ),
                            ),
                            TextSpan(text: segment.text),
                          ],
                        ),
                        style: theme.textTheme.bodySmall,
                      ),
                    ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 8),
        ],
        if (!call.recordingEnabled && call.isConnected)
          OutlinedButton.icon(
            onPressed: () => _openManualEntry(context),
            icon: const Icon(Icons.add),
            label: const Text('Добавить договорённость вручную'),
          ),
      ],
    );
  }

  List<TranscriptSegment> _lastSegments(List<TranscriptSegment> all) {
    const maxLines = 6;
    return all.length <= maxLines ? all : all.sublist(all.length - maxLines);
  }

  String _speakerLabel(String speaker) => speaker.isEmpty ? '—' : speaker;

  Future<void> _openManualEntry(BuildContext context) async {
    final patch = await showDialog<AgreementPatch>(
      context: context,
      builder: (_) => const AgreementEditDialog(),
    );
    if (patch == null) return;
    final error = await controller.createManualAgreement(patch);
    if (error != null && context.mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(error)));
    }
  }

  /// Reloads the call итог and surfaces an error, if any.
  Future<void> _refreshSummary(BuildContext context) async {
    final messenger = ScaffoldMessenger.of(context);
    final error = await controller.loadSummary();
    if (error != null) {
      messenger.showSnackBar(SnackBar(content: Text(error)));
    }
  }
}

/// Итог звонка card (plan.md §9): the summary text plus the agreement counters,
/// with a refresh action. Shown once the backend has produced a summary.
class _CallSummaryCard extends StatelessWidget {
  const _CallSummaryCard({required this.summary, required this.onRefresh});

  final CallSummary summary;
  final Future<void> Function() onRefresh;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Row(
              children: <Widget>[
                Expanded(
                  child: Text('Итог звонка', style: theme.textTheme.labelLarge),
                ),
                IconButton(
                  icon: const Icon(Icons.refresh, size: 20),
                  tooltip: 'Обновить итог',
                  onPressed: () => onRefresh(),
                ),
              ],
            ),
            if (summary.summary.isNotEmpty) ...<Widget>[
              const SizedBox(height: 4),
              Text(summary.summary, style: theme.textTheme.bodyMedium),
            ],
            const SizedBox(height: 4),
            Text(
              'Договорённостей: ${summary.agreementsTotal} · '
              'подтверждено: ${summary.agreementsConfirmed}',
              style: theme.textTheme.bodySmall,
            ),
          ],
        ),
      ),
    );
  }
}

/// One detected agreement with confirm/reject/edit actions. Confirming creates
/// the task on the server; a `confirmed` agreement stays editable (§12–14: the
/// card is not frozen) and only `rejected` is final.
class _AgreementCard extends StatelessWidget {
  const _AgreementCard({required this.agreement, required this.controller});

  final Agreement agreement;
  final CallController controller;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final confirmed = agreement.status == AgreementStatus.confirmed;
    final rejected = agreement.status == AgreementStatus.rejected;
    // Only `rejected` is final; a confirmed agreement can still be edited or
    // rejected. "Подтвердить" makes no sense once it is already confirmed.
    final canConfirm = !confirmed && !rejected;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Expanded(
                  child: Text(
                    agreement.title,
                    style: theme.textTheme.titleSmall,
                  ),
                ),
                Text(
                  'Уверенность: ${formatConfidence(agreement.confidence)}',
                  style: theme.textTheme.labelSmall,
                ),
              ],
            ),
            if (agreement.type.isNotEmpty) ...<Widget>[
              const SizedBox(height: 2),
              Text(agreement.type, style: theme.textTheme.bodySmall),
            ],
            const SizedBox(height: 4),
            Text(
              'Ответственный: ${agreementOwnerLabel(agreement.owner)} · '
              'Срок: ${formatDueDate(agreement.dueDate)}',
              style: theme.textTheme.bodySmall,
            ),
            if (agreement.sourceQuote.isNotEmpty) ...<Widget>[
              const SizedBox(height: 4),
              Text(
                '«${agreement.sourceQuote}»',
                style: theme.textTheme.bodySmall?.copyWith(
                  fontStyle: FontStyle.italic,
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
            ],
            const SizedBox(height: 8),
            Row(
              children: <Widget>[
                if (confirmed) ...<Widget>[
                  const Icon(Icons.check_circle, size: 16, color: Colors.green),
                  const SizedBox(width: 4),
                ],
                Expanded(
                  child: Text(
                    agreementStatusLabel(agreement.status),
                    style: theme.textTheme.labelMedium,
                  ),
                ),
                if (rejected)
                  Icon(Icons.block, size: 20, color: theme.colorScheme.outline)
                else ...<Widget>[
                  if (canConfirm)
                    TextButton(
                      onPressed: () => _run(
                          context, () => controller.confirmAgreement(agreement.id)),
                      child: const Text('Подтвердить'),
                    ),
                  TextButton(
                    onPressed: () =>
                        _run(context, () => controller.rejectAgreement(agreement.id)),
                    child: const Text('Отклонить'),
                  ),
                  IconButton(
                    icon: const Icon(Icons.edit, size: 20),
                    tooltip: 'Изменить',
                    onPressed: () => _edit(context),
                  ),
                ],
              ],
            ),
          ],
        ),
      ),
    );
  }

  /// Runs an agreement action and surfaces the server error, if any.
  Future<void> _run(
    BuildContext context,
    Future<String?> Function() action,
  ) async {
    final error = await action();
    if (error != null && context.mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(error)));
    }
  }

  Future<void> _edit(BuildContext context) async {
    final patch = await showDialog<AgreementPatch>(
      context: context,
      builder: (_) => AgreementEditDialog(initial: agreement),
    );
    if (patch == null) return;
    final error = await controller.editAgreement(agreement.id, patch);
    if (error != null && context.mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(error)));
    }
  }
}
