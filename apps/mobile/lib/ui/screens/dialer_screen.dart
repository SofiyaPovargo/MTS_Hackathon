import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../application/providers.dart';

/// Manual dialer for an outgoing call. Failures (bad number, permission denied,
/// backend unavailable) are surfaced without leaving the screen.
class DialerScreen extends ConsumerStatefulWidget {
  const DialerScreen({super.key});

  @override
  ConsumerState<DialerScreen> createState() => _DialerScreenState();
}

class _DialerScreenState extends ConsumerState<DialerScreen> {
  final TextEditingController _controller = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _call() async {
    final phone = _controller.text.trim();
    if (phone.isEmpty) return;
    setState(() => _busy = true);
    final error = await ref.read(callControllerProvider.notifier).startOutgoing(phone);
    if (!mounted) return;
    setState(() => _busy = false);
    if (error != null) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error)));
      return;
    }
    // The call overlay is shown by the app; return to the previous screen.
    Navigator.of(context).maybePop();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Новый звонок')),
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          children: <Widget>[
            TextField(
              controller: _controller,
              keyboardType: TextInputType.phone,
              autofocus: true,
              decoration: const InputDecoration(
                labelText: 'Номер',
                hintText: '+79000000002',
              ),
              onSubmitted: (_) => _call(),
            ),
            const SizedBox(height: 24),
            FilledButton.icon(
              onPressed: _busy ? null : _call,
              icon: const Icon(Icons.call),
              label: const Text('Позвонить'),
            ),
          ],
        ),
      ),
    );
  }
}
