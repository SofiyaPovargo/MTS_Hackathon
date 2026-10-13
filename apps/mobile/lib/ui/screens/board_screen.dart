import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../application/providers.dart';
import '../../domain/models.dart';
import '../../infrastructure/api/api_exception.dart';
import '../formats.dart';
import 'contacts_screen.dart';

/// Personal board: the user's own tasks. Pull-to-refresh runs a sync; errors are
/// shown without dropping the already-loaded list.
class BoardScreen extends ConsumerWidget {
  const BoardScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tasks = ref.watch(boardControllerProvider);
    final session = ref.watch(authControllerProvider).valueOrNull;
    return Scaffold(
      appBar: AppBar(
        title: Text(session == null ? 'Мои задачи' : session.user.fullName),
        actions: <Widget>[
          IconButton(
            icon: const Icon(Icons.people_outline),
            tooltip: 'Контакты',
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(builder: (_) => const ContactsScreen()),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.logout),
            tooltip: 'Выйти',
            onPressed: () => ref.read(authControllerProvider.notifier).logout(),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () => _refresh(context, ref),
        child: tasks.when(
          data: (items) => items.isEmpty
              ? const _Placeholder(text: 'Пока нет задач. Потяните вниз, чтобы обновить.')
              : ListView.builder(
                  physics: const AlwaysScrollableScrollPhysics(),
                  itemCount: items.length,
                  itemBuilder: (context, index) => _TaskTile(task: items[index]),
                ),
          error: (error, stackTrace) => _Placeholder(text: 'Ошибка: $error'),
          loading: () => const Center(child: CircularProgressIndicator()),
        ),
      ),
    );
  }

  Future<void> _refresh(BuildContext context, WidgetRef ref) async {
    final messenger = ScaffoldMessenger.of(context);
    try {
      await ref.read(boardControllerProvider.notifier).refresh();
    } on ApiException catch (error) {
      messenger.showSnackBar(SnackBar(content: Text(error.message)));
    }
  }
}

class _TaskTile extends StatelessWidget {
  const _TaskTile({required this.task});

  final TaskItem task;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      leading: const Icon(Icons.task_alt),
      title: Text(task.title),
      subtitle: Text(formatDueDate(task.dueDate)),
      trailing: Chip(label: Text(taskStatusLabel(task.status))),
    );
  }
}

class _Placeholder extends StatelessWidget {
  const _Placeholder({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      children: <Widget>[
        const SizedBox(height: 160),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 24),
          child: Text(text, textAlign: TextAlign.center),
        ),
      ],
    );
  }
}
