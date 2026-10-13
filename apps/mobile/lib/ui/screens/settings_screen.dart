import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../application/providers.dart';
import '../../domain/consent.dart';
import '../formats.dart';

/// Recording / AI settings: the app user's consent, withdrawal and data
/// deletion. Changes are written to the server; a pending state (offline) is
/// surfaced and can be retried.
class SettingsScreen extends ConsumerWidget {
  const SettingsScreen({super.key});

  Future<void> _run(
    BuildContext context,
    Future<String?> Function() action,
  ) async {
    final messenger = ScaffoldMessenger.of(context);
    final message = await action();
    if (message != null) {
      messenger.showSnackBar(SnackBar(content: Text(message)));
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final consent = ref.watch(consentControllerProvider).valueOrNull ??
        AppConsent.undecided;
    final controller = ref.read(consentControllerProvider.notifier);
    return Scaffold(
      appBar: AppBar(title: const Text('Настройки')),
      body: ListView(
        children: <Widget>[
          SwitchListTile(
            secondary: const Icon(Icons.mic),
            title: const Text('Запись и ИИ-обработка'),
            subtitle: Text(consentStatusLabel(consent.status)),
            value: consent.recordingEnabled,
            onChanged: (value) => _run(
              context,
              () => value ? controller.grant() : controller.deny(),
            ),
          ),
          if (!consent.synced && consent.decided)
            ListTile(
              leading: const Icon(Icons.cloud_off),
              title: const Text('Не синхронизировано с сервером'),
              subtitle: const Text('Решение сохранено на устройстве'),
              trailing: TextButton(
                onPressed: () => _run(context, controller.retrySync),
                child: const Text('Повторить'),
              ),
            ),
          const Divider(),
          ListTile(
            leading: const Icon(Icons.privacy_tip_outlined),
            title: const Text('Политика обработки данных'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => _showPolicy(context),
          ),
          ListTile(
            leading: const Icon(Icons.block),
            title: const Text('Отозвать согласие'),
            subtitle: const Text('Запись новых звонков будет недоступна'),
            enabled: consent.recordingEnabled,
            onTap: () async {
              final confirmed = await _confirm(
                context,
                title: 'Отозвать согласие?',
                message: 'Запись и ИИ-обработка новых звонков будет отключена.',
              );
              if (confirmed && context.mounted) {
                await _run(context, controller.withdraw);
              }
            },
          ),
          ListTile(
            leading: const Icon(Icons.delete_forever),
            title: const Text('Удалить мои данные'),
            subtitle: const Text('Отзыв согласия и удаление данных на сервере'),
            onTap: () async {
              final confirmed = await _confirm(
                context,
                title: 'Удалить все данные?',
                message: 'Это действие нельзя отменить.',
              );
              if (confirmed && context.mounted) {
                await _run(context, controller.requestDataDeletion);
              }
            },
          ),
        ],
      ),
    );
  }
}

Future<bool> _confirm(
  BuildContext context, {
  required String title,
  required String message,
}) async {
  final result = await showDialog<bool>(
    context: context,
    builder: (context) => AlertDialog(
      title: Text(title),
      content: Text(message),
      actions: <Widget>[
        TextButton(
          onPressed: () => Navigator.of(context).pop(false),
          child: const Text('Отмена'),
        ),
        FilledButton(
          onPressed: () => Navigator.of(context).pop(true),
          child: const Text('Подтвердить'),
        ),
      ],
    ),
  );
  return result ?? false;
}

void _showPolicy(BuildContext context) {
  showDialog<void>(
    context: context,
    builder: (context) => AlertDialog(
      title: const Text('Политика обработки данных'),
      content: const Text(
        'Аудио и расшифровки разговоров обрабатываются только для выделения '
        'договорённостей. Записи хранятся ограниченное время, доступ к ним '
        'ограничен. Вы можете отозвать согласие и удалить данные в любой '
        'момент.',
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