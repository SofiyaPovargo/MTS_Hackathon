import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../domain/enums.dart';
import '../../domain/models.dart';
import '../formats.dart';

/// Edit/create dialog for an agreement card. Returns the edited fields as an
/// [AgreementPatch], or `null` when cancelled. Used both for editing a detected
/// agreement and for manual entry on the no-consent path (the product rule:
/// the user can edit every proposed action before confirming it).
class AgreementEditDialog extends StatefulWidget {
  const AgreementEditDialog({super.key, this.initial});

  /// Existing agreement being edited, or `null` for manual creation.
  final Agreement? initial;

  @override
  State<AgreementEditDialog> createState() => _AgreementEditDialogState();
}

class _AgreementEditDialogState extends State<AgreementEditDialog> {
  late final TextEditingController _title =
      TextEditingController(text: widget.initial?.title ?? '');
  late final TextEditingController _type =
      TextEditingController(text: widget.initial?.type ?? '');
  late final TextEditingController _amount = TextEditingController(
    text: widget.initial?.amount == null
        ? ''
        : widget.initial!.amount.toString(),
  );

  DateTime? _dueDate;
  late AgreementOwner _owner;

  @override
  void initState() {
    super.initState();
    _dueDate = widget.initial?.dueDate;
    _owner = widget.initial?.owner ?? AgreementOwner.unknown;
  }

  @override
  void dispose() {
    _title.dispose();
    _type.dispose();
    _amount.dispose();
    super.dispose();
  }

  Future<void> _pickDate() async {
    final now = DateTime.now();
    final picked = await showDatePicker(
      context: context,
      initialDate: _dueDate ?? now,
      firstDate: now.subtract(const Duration(days: 365)),
      lastDate: now.add(const Duration(days: 365 * 3)),
      helpText: 'Срок',
    );
    if (picked != null) setState(() => _dueDate = picked);
  }

  double? get _parsedAmount =>
      double.tryParse(_amount.text.trim().replaceAll(',', '.'));

  void _submit() {
    final title = _title.text.trim();
    if (title.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Укажите название договорённости')),
      );
      return;
    }
    // The type is a free string in the MVP (plan.md). When it is left empty on
    // edit, carry the current value so the server PATCH does not clear it.
    String? type;
    if (_type.text.trim().isNotEmpty) {
      type = _type.text.trim();
    } else if (widget.initial != null) {
      type = widget.initial?.type;
    }
    Navigator.of(context).pop(
      AgreementPatch(
        title: title,
        type: type,
        owner: _owner,
        dueDate: _dueDate,
        amount: _parsedAmount,
        currency: _parsedAmount == null ? null : 'RUB',
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final isEdit = widget.initial != null;
    return AlertDialog(
      title: Text(isEdit ? 'Изменить договорённость' : 'Добавить вручную'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            TextField(
              controller: _title,
              decoration: const InputDecoration(labelText: 'Название *'),
              autofocus: !isEdit,
            ),
            const SizedBox(height: 8),
            TextField(
              controller: _type,
              decoration: const InputDecoration(
                labelText: 'Тип (обязательство, встреча, платёж…)',
              ),
            ),
            const SizedBox(height: 8),
            DropdownButtonFormField<AgreementOwner>(
              initialValue: _owner,
              decoration: const InputDecoration(labelText: 'Ответственный'),
              items: AgreementOwner.values
                  .map(
                    (owner) => DropdownMenuItem<AgreementOwner>(
                      value: owner,
                      child: Text(agreementOwnerLabel(owner)),
                    ),
                  )
                  .toList(),
              onChanged: (value) =>
                  setState(() => _owner = value ?? _owner),
            ),
            const SizedBox(height: 8),
            Row(
              children: <Widget>[
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: _pickDate,
                    icon: const Icon(Icons.calendar_today, size: 18),
                    label: Text(
                      _dueDate == null
                          ? 'Без срока'
                          : DateFormat('dd.MM.yyyy').format(_dueDate!),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: TextField(
                    controller: _amount,
                    keyboardType:
                        const TextInputType.numberWithOptions(decimal: true),
                    decoration: const InputDecoration(labelText: 'Сумма'),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Text(
              isEdit
                  ? 'Цитата и временные метки сохраняются без изменений'
                  : 'Тип и срок можно уточнить позже',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        ),
      ),
      actions: <Widget>[
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Отмена'),
        ),
        FilledButton(onPressed: _submit, child: const Text('Сохранить')),
      ],
    );
  }
}