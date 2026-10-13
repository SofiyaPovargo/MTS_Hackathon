import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../application/providers.dart';

/// First-run consent gate (plan.md §10). Shown by the app gate until the user
/// decides; the decision is cached locally and pushed to the server.
class ConsentScreen extends ConsumerStatefulWidget {
  const ConsentScreen({super.key});

  @override
  ConsumerState<ConsentScreen> createState() => _ConsentScreenState();
}

class _ConsentScreenState extends ConsumerState<ConsentScreen> {
  bool _busy = false;

  Future<void> _choose(bool granted) async {
    setState(() => _busy = true);
    final message = granted
        ? await ref.read(consentControllerProvider.notifier).grant()
        : await ref.read(consentControllerProvider.notifier).deny();
    if (!mounted) return;
    setState(() => _busy = false);
    if (message != null) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(message)));
    }
  }

  void _showPolicy() {
    showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Политика обработки данных'),
        content: const Text(
          'Аудио и расшифровки разговоров обрабатываются только для выделения '
          'договорённостей. Записи хранятся ограниченное время, доступ к ним '
          'ограничен. Вы можете отозвать согласие и удалить данные в любой '
          'момент в настройках.',
        ),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Закрыть'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: <Widget>[
                Icon(
                  Icons.record_voice_over,
                  size: 56,
                  color: Theme.of(context).colorScheme.primary,
                ),
                const SizedBox(height: 16),
                Text(
                  'Запись и ИИ-обработка звонков',
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
                const SizedBox(height: 16),
                const Text(
                  'Чтобы фиксировать договорённости из звонков, приложение может '
                  'записывать и обрабатывать аудиоразговоры с помощью ИИ. Мы '
                  'распознаём речь, выделяем задачи, сроки и обязательства. '
                  'Запись хранится ограниченное время, доступ к ней ограничен. '
                  'Вы можете отключить запись и удалить данные в любой момент.',
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 8),
                TextButton(
                  onPressed: _showPolicy,
                  child: const Text('Политика обработки данных'),
                ),
                const SizedBox(height: 16),
                FilledButton(
                  onPressed: _busy ? null : () => _choose(true),
                  child: const Text('Согласен и включить запись'),
                ),
                const SizedBox(height: 8),
                OutlinedButton(
                  onPressed: _busy ? null : () => _choose(false),
                  child: const Text('Не включать запись'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}