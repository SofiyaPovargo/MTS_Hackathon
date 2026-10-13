import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../application/call_controller.dart';
import '../../application/providers.dart';
import '../../domain/call.dart';
import '../../domain/enums.dart';
import '../formats.dart';

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
