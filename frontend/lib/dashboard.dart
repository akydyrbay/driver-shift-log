import 'package:flutter/material.dart';

import 'models.dart';
import 'shift_time.dart';
import 'trip_api.dart';
import 'trip_form.dart';

class Dashboard extends StatefulWidget {
  const Dashboard({super.key, required this.api, this.initialDay});
  final TripApi api;
  final DateTime? initialDay;

  @override
  State<Dashboard> createState() => _DashboardState();
}

class _DashboardState extends State<Dashboard> {
  late DateTime _day;
  DayLog? _log;
  String? _error;
  bool _loading = true;
  int _requestId = 0;

  @override
  void initState() {
    super.initState();
    _day = calendarDay(widget.initialDay ?? todayInAlmaty());
    _load();
  }

  Future<void> _load([DateTime? day]) async {
    final requestId = ++_requestId;
    setState(() {
      _day = calendarDay(day ?? _day);
      _loading = true;
      _error = null;
      _log = null;
    });
    try {
      final result = await widget.api.loadDay(_day);
      // Fast date changes must not let an older response replace today's view.
      if (!mounted || requestId != _requestId) return;
      setState(() {
        _log = result;
        _loading = false;
      });
    } on ApiException catch (error) {
      if (!mounted || requestId != _requestId) return;
      setState(() {
        _error = error.message;
        _loading = false;
      });
    }
  }

  Future<void> _chooseDay() async {
    final selected = await showDatePicker(
      context: context,
      initialDate: _day,
      firstDate: DateTime(1),
      lastDate: DateTime(9999, 12, 31),
      helpText: 'Выберите день смены',
    );
    if (selected != null && mounted) await _load(selected);
  }

  Future<void> _addTrip() async {
    final savedDay = await showDialog<DateTime>(
      context: context,
      barrierDismissible: false,
      builder: (context) => TripForm(api: widget.api, day: _day),
    );
    if (!mounted) return;
    if (savedDay != null) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('Поездка сохранена')));
    }
    // Also refresh on dismissal: a response may have been lost after a commit.
    await _load(savedDay);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 1120),
            child: ListView(
              padding: const EdgeInsets.all(24),
              children: [
                Row(
                  children: [
                    Icon(
                      Icons.route_rounded,
                      color: theme.colorScheme.primary,
                      size: 32,
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        'Дневник смен',
                        style: theme.textTheme.headlineSmall?.copyWith(
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                const Text('Поездки и итоги дня · Asia/Almaty'),
                const SizedBox(height: 28),
                Wrap(
                  spacing: 16,
                  runSpacing: 12,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        IconButton(
                          tooltip: 'Предыдущий день',
                          onPressed: _day == DateTime.utc(1)
                              ? null
                              : () => _load(
                                  _day.subtract(const Duration(days: 1)),
                                ),
                          icon: const Icon(Icons.chevron_left),
                        ),
                        OutlinedButton.icon(
                          key: const ValueKey('choose-day'),
                          onPressed: _chooseDay,
                          icon: const Icon(
                            Icons.calendar_today_outlined,
                            size: 18,
                          ),
                          label: Text(dayLabel(_day)),
                        ),
                        IconButton(
                          tooltip: 'Следующий день',
                          onPressed: _day == DateTime.utc(9999, 12, 31)
                              ? null
                              : () => _load(_day.add(const Duration(days: 1))),
                          icon: const Icon(Icons.chevron_right),
                        ),
                      ],
                    ),
                    TextButton(
                      onPressed: () => _load(todayInAlmaty()),
                      child: const Text('Сегодня'),
                    ),
                    IconButton(
                      tooltip: 'Обновить',
                      onPressed: _loading ? null : () => _load(),
                      icon: const Icon(Icons.refresh),
                    ),
                    FilledButton.icon(
                      key: const ValueKey('add-trip'),
                      onPressed: _addTrip,
                      icon: const Icon(Icons.add),
                      label: const Text('Добавить поездку'),
                    ),
                  ],
                ),
                const SizedBox(height: 24),
                if (_loading)
                  const Padding(
                    padding: EdgeInsets.all(48),
                    child: Center(
                      child: CircularProgressIndicator(
                        semanticsLabel: 'Загрузка поездок',
                      ),
                    ),
                  )
                else if (_error != null)
                  _message(
                    Icons.cloud_off_outlined,
                    'Не удалось загрузить день',
                    _error!,
                    action: OutlinedButton(
                      onPressed: () => _load(),
                      child: const Text('Повторить'),
                    ),
                  )
                else if (_log != null) ...[
                  _summary(_log!.summary),
                  const SizedBox(height: 32),
                  Text(
                    'Поездки за день',
                    style: theme.textTheme.titleLarge?.copyWith(
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: 12),
                  if (_log!.trips.isEmpty)
                    _message(
                      Icons.route_outlined,
                      'В этот день поездок пока нет',
                      'Добавьте первую поездку — здесь появятся список поездок и итоги.',
                    )
                  else
                    ..._log!.trips.map(_tripCard),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _message(IconData icon, String title, String body, {Widget? action}) =>
      Card(
        child: Padding(
          padding: const EdgeInsets.all(28),
          child: Column(
            children: [
              Icon(
                icon,
                size: 36,
                color: Theme.of(context).colorScheme.primary,
              ),
              const SizedBox(height: 16),
              Text(
                title,
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 8),
              Text(body, textAlign: TextAlign.center),
              if (action != null) ...[const SizedBox(height: 16), action],
            ],
          ),
        ),
      );

  Widget _summary(DailySummary summary) {
    final values = [
      ('На руки', summary.takeHome, Icons.account_balance_wallet_outlined),
      ('Выручка', summary.revenue, Icons.payments_outlined),
      ('Комиссия', summary.commission, Icons.receipt_long_outlined),
      ('Поездки', summary.tripCount, Icons.route_outlined),
      ('Наличные', summary.cashRevenue, Icons.money_outlined),
      ('Карта', summary.cardRevenue, Icons.credit_card_outlined),
    ];
    return LayoutBuilder(
      builder: (context, constraints) {
        final columns = constraints.maxWidth >= 850
            ? 3
            : constraints.maxWidth >= 500
            ? 2
            : 1;
        final width = (constraints.maxWidth - (columns - 1) * 12) / columns;
        return Wrap(
          spacing: 12,
          runSpacing: 12,
          children: [
            for (final (label, value, icon) in values)
              SizedBox(
                width: width,
                child: Card(
                  margin: EdgeInsets.zero,
                  color: label == 'На руки'
                      ? Theme.of(context).colorScheme.primaryContainer
                      : null,
                  child: Padding(
                    padding: const EdgeInsets.all(20),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Icon(icon, size: 20),
                            const SizedBox(width: 8),
                            Text(label),
                          ],
                        ),
                        const SizedBox(height: 12),
                        Text(
                          money(value),
                          key: ValueKey('summary-$label'),
                          style: Theme.of(context).textTheme.headlineMedium
                              ?.copyWith(fontWeight: FontWeight.w700),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
          ],
        );
      },
    );
  }

  Widget _tripCard(Trip trip) {
    final endDay = dayLabel(inAlmaty(trip.end));
    final startDay = dayLabel(inAlmaty(trip.start));
    final end = endDay == startDay
        ? timeLabel(trip.end)
        : '$endDay ${timeLabel(trip.end)}';
    return Card(
      key: ValueKey('trip-${trip.id}'),
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '${timeLabel(trip.start)} → $end',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 24,
              runSpacing: 8,
              children: [
                Text('Сумма: ${money(trip.amount)}'),
                Text('Комиссия: ${money(trip.commission)}'),
                Text('На руки: ${money(trip.amount - trip.commission)}'),
                Text(trip.payment == 'cash' ? 'Наличные' : 'Карта'),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              'ID: ${trip.id}',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        ),
      ),
    );
  }
}
