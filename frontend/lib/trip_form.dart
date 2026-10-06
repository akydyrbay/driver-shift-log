import 'package:flutter/material.dart';
import 'package:uuid/uuid.dart';

import 'models.dart';
import 'shift_time.dart';
import 'trip_api.dart';

class TripForm extends StatefulWidget {
  const TripForm({super.key, required this.api, required this.day});
  final TripApi api;
  final DateTime day;

  @override
  State<TripForm> createState() => _TripFormState();
}

class _TripFormState extends State<TripForm> {
  final _form = GlobalKey<FormState>();
  late final _startDate = TextEditingController(text: dayLabel(widget.day));
  late final _endDate = TextEditingController(text: dayLabel(widget.day));
  final _startTime = TextEditingController(text: '08:00');
  final _endTime = TextEditingController(text: '08:30');
  final _amount = TextEditingController();
  final _commission = TextEditingController(text: '0');
  String _payment = 'card';
  bool _saving = false;
  String? _error;
  Trip? _pending;

  @override
  void dispose() {
    for (final controller in [
      _startDate,
      _endDate,
      _startTime,
      _endTime,
      _amount,
      _commission,
    ]) {
      controller.dispose();
    }
    super.dispose();
  }

  int? _integer(String? input) {
    final value = (input ?? '').trim();
    if (!RegExp(r'^\d+$').hasMatch(value)) return null;
    final number = int.tryParse(value);
    return number != null && number <= maxSafeInteger ? number : null;
  }

  Future<void> _save() async {
    if (_saving) return;
    if (_pending == null) {
      if (!_form.currentState!.validate()) return;
      _pending = Trip(
        id: const Uuid().v4(),
        start: parseAlmatyTime(_startDate.text, _startTime.text)!,
        end: parseAlmatyTime(_endDate.text, _endTime.text)!,
        amount: _integer(_amount.text)!,
        commission: _integer(_commission.text)!,
        payment: _payment,
      );
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await widget.api.createTrip(_pending!);
      if (!mounted) return;
      Navigator.of(context).pop(calendarDay(inAlmaty(_pending!.start)));
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _error = error.message;
        // Only allow changing the payload when the server definitely rejected it.
        if (!error.mayHaveSaved) _pending = null;
      });
    }
  }

  Widget _field(
    String key,
    String label,
    TextEditingController controller,
    String? Function(String?) validate, {
    String? hint,
    bool numeric = false,
  }) => TextFormField(
    key: ValueKey(key),
    controller: controller,
    enabled: !_saving && _pending == null,
    decoration: InputDecoration(
      labelText: label,
      hintText: hint,
      border: const OutlineInputBorder(),
    ),
    keyboardType: numeric ? TextInputType.number : TextInputType.datetime,
    validator: validate,
    autovalidateMode: AutovalidateMode.onUserInteraction,
    textInputAction: TextInputAction.next,
  );

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: !_saving,
      child: Dialog(
        insetPadding: const EdgeInsets.all(16),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 520),
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: Form(
              key: _form,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    'Новая поездка',
                    style: Theme.of(context).textTheme.headlineSmall,
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    'Время — Asia/Almaty. Для ночной поездки укажите дату окончания следующего дня.',
                  ),
                  const SizedBox(height: 24),
                  _field(
                    'start-date',
                    'Дата начала',
                    _startDate,
                    (value) => parseDay(value ?? '') == null
                        ? 'Введите дату ГГГГ-ММ-ДД'
                        : null,
                    hint: 'ГГГГ-ММ-ДД',
                  ),
                  const SizedBox(height: 16),
                  _field(
                    'start-time',
                    'Время начала',
                    _startTime,
                    (value) =>
                        parseAlmatyTime(_startDate.text, value ?? '') == null
                        ? 'Введите время ЧЧ:ММ'
                        : null,
                    hint: 'ЧЧ:ММ',
                  ),
                  const SizedBox(height: 16),
                  _field(
                    'end-date',
                    'Дата окончания',
                    _endDate,
                    (value) => parseDay(value ?? '') == null
                        ? 'Введите дату ГГГГ-ММ-ДД'
                        : null,
                    hint: 'ГГГГ-ММ-ДД',
                  ),
                  const SizedBox(height: 16),
                  _field('end-time', 'Время окончания', _endTime, (value) {
                    final start = parseAlmatyTime(
                      _startDate.text,
                      _startTime.text,
                    );
                    final end = parseAlmatyTime(_endDate.text, value ?? '');
                    if (end == null) return 'Введите время ЧЧ:ММ';
                    if (start != null && !end.isAfter(start)) {
                      return 'Окончание должно быть позже начала';
                    }
                    return null;
                  }, hint: 'ЧЧ:ММ'),
                  const SizedBox(height: 16),
                  _field('amount', 'Сумма поездки', _amount, (value) {
                    final amount = _integer(value);
                    return amount == null || amount <= 0
                        ? 'Целая сумма от 1 до $maxSafeInteger'
                        : null;
                  }, numeric: true),
                  const SizedBox(height: 16),
                  _field('commission', 'Комиссия', _commission, (value) {
                    final commission = _integer(value);
                    final amount = _integer(_amount.text);
                    return commission == null ||
                            (amount != null && commission > amount)
                        ? 'От 0 до суммы поездки, целое число'
                        : null;
                  }, numeric: true),
                  const SizedBox(height: 16),
                  DropdownButtonFormField<String>(
                    key: const ValueKey('payment'),
                    initialValue: _payment,
                    decoration: const InputDecoration(
                      labelText: 'Способ оплаты',
                      border: OutlineInputBorder(),
                    ),
                    items: const [
                      DropdownMenuItem(value: 'card', child: Text('Карта')),
                      DropdownMenuItem(value: 'cash', child: Text('Наличные')),
                    ],
                    onChanged: _saving || _pending != null
                        ? null
                        : (value) => setState(() => _payment = value!),
                  ),
                  if (_error != null) ...[
                    const SizedBox(height: 16),
                    Text(
                      _error!,
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.error,
                      ),
                    ),
                    if (_pending != null)
                      const Padding(
                        padding: EdgeInsets.only(top: 8),
                        child: Text(
                          'Результат сохранения неизвестен. Повторите отправку без изменения данных — дубль не появится. Если закроете форму, сначала проверьте список поездок.',
                        ),
                      ),
                  ],
                  const SizedBox(height: 24),
                  FilledButton.icon(
                    key: const ValueKey('save-trip'),
                    onPressed: _saving ? null : _save,
                    icon: _saving
                        ? const SizedBox.square(
                            dimension: 18,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.check),
                    label: Text(
                      _saving
                          ? 'Сохранение…'
                          : _pending == null
                          ? 'Сохранить поездку'
                          : 'Повторить отправку',
                    ),
                  ),
                  const SizedBox(height: 8),
                  TextButton(
                    onPressed: _saving
                        ? null
                        : () => Navigator.of(context).pop(),
                    child: const Text('Закрыть'),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
