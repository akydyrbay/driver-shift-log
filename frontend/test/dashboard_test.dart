import 'dart:async';

import 'package:driver_shift_log/main.dart';
import 'package:driver_shift_log/models.dart';
import 'package:driver_shift_log/shift_time.dart';
import 'package:driver_shift_log/trip_api.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'fixtures.dart';

class FakeApi extends TripApi {
  final loaded = <String>[];
  final submitted = <Trip>[];
  Future<DayLog> Function(DateTime)? onLoad;
  Future<void> Function(Trip)? onCreate;

  @override
  Future<DayLog> loadDay(DateTime day) async {
    loaded.add(dayLabel(day));
    return onLoad == null ? dayLog(dayLabel(day)) : await onLoad!(day);
  }

  @override
  Future<void> createTrip(Trip trip) async {
    submitted.add(trip);
    await onCreate?.call(trip);
  }
}

Future<void> mount(WidgetTester tester, FakeApi api) async {
  addTearDown(api.close);
  await tester.pumpWidget(
    DriverShiftLogApp(api: api, initialDay: DateTime.utc(2026, 10, 1)),
  );
  await tester.pumpAndSettle();
}

Future<void> openForm(WidgetTester tester) async {
  await tester.tap(find.byKey(const ValueKey('add-trip')));
  await tester.pumpAndSettle();
}

Future<void> enter(WidgetTester tester, String key, String text) async {
  final field = find.byKey(ValueKey(key));
  await tester.ensureVisible(field);
  await tester.enterText(field, text);
  await tester.pump();
}

Future<void> save(WidgetTester tester) async {
  final button = find.byKey(const ValueKey('save-trip'));
  await tester.ensureVisible(button);
  await tester.tap(button);
  await tester.pumpAndSettle();
}

void main() {
  setUp(() {
    // The default 800x600 surface puts the list below the fold.
    final testView = TestWidgetsFlutterBinding.ensureInitialized()
        .platformDispatcher
        .views
        .first;
    testView.physicalSize = const Size(1280, 1000);
    testView.devicePixelRatio = 1;
    addTearDown(testView.resetPhysicalSize);
    addTearDown(testView.resetDevicePixelRatio);
  });

  testWidgets(
    'saving a cash trip replaces empty totals with refreshed API data',
    (tester) async {
      final api = FakeApi();
      Trip? saved;
      api.onCreate = (trip) async {
        saved = trip;
      };
      api.onLoad = (day) async => saved == null
          ? dayLog(dayLabel(day), empty: true)
          : DayLog(
              [saved!],
              DailySummary(
                date: dayLabel(day),
                tripCount: 1,
                revenue: 1500,
                commission: 225,
                takeHome: 1275,
                cashRevenue: 1500,
                cardRevenue: 0,
              ),
            );
      await mount(tester, api);
      expect(find.text('В этот день поездок пока нет'), findsOneWidget);
      await openForm(tester);
      await enter(tester, 'amount', '1500');
      await enter(tester, 'commission', '225');
      await tester.ensureVisible(find.byKey(const ValueKey('payment')));
      await tester.tap(find.byKey(const ValueKey('payment')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Наличные').last);
      await tester.pumpAndSettle();
      await save(tester);
      expect(saved!.payment, 'cash');
      expect(
        tester.widget<Text>(find.byKey(const ValueKey('summary-На руки'))).data,
        '1 275',
      );
      expect(
        tester
            .widget<Text>(find.byKey(const ValueKey('summary-Наличные')))
            .data,
        '1 500',
      );
      expect(find.byKey(ValueKey('trip-${saved!.id}')), findsOneWidget);
      expect(find.text('В этот день поездок пока нет'), findsNothing);
    },
  );

  testWidgets('late requests do not update a disposed dashboard', (
    tester,
  ) async {
    final api = FakeApi();
    addTearDown(api.close);
    final pending = Completer<DayLog>();
    api.onLoad = (_) => pending.future;
    await tester.pumpWidget(
      DriverShiftLogApp(api: api, initialDay: DateTime.utc(2026, 10, 1)),
    );
    await tester.pumpWidget(const SizedBox());
    pending.complete(dayLog('2026-10-01'));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });
  testWidgets('shows API values and changes day with navigation and calendar', (
    tester,
  ) async {
    final api = FakeApi();
    api.onLoad = (day) async => dayLog(dayLabel(day), empty: day.day != 1);
    await mount(tester, api);
    expect(find.text('2 040'), findsOneWidget);
    expect(find.text('08:10 → 08:32'), findsOneWidget);
    await tester.tap(find.byTooltip('Следующий день'));
    await tester.pumpAndSettle();
    expect(api.loaded.last, '2026-10-02');
    expect(find.text('В этот день поездок пока нет'), findsOneWidget);
    expect(find.text('08:10 → 08:32'), findsNothing);
    await tester.tap(find.byKey(const ValueKey('choose-day')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('3').last);
    await tester.tap(find.text('ОК'));
    await tester.pumpAndSettle();
    expect(api.loaded.last, '2026-10-03');
  });

  testWidgets('loading is visible and out-of-order responses are ignored', (
    tester,
  ) async {
    final api = FakeApi();
    final first = Completer<DayLog>();
    final second = Completer<DayLog>();
    api.onLoad = (day) => day.day == 1 ? first.future : second.future;
    addTearDown(api.close);
    await tester.pumpWidget(
      DriverShiftLogApp(api: api, initialDay: DateTime.utc(2026, 10, 1)),
    );
    await tester.pump();
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    await tester.tap(find.byTooltip('Следующий день'));
    second.complete(dayLog('2026-10-02', empty: true));
    await tester.pumpAndSettle();
    first.complete(dayLog('2026-10-01'));
    await tester.pumpAndSettle();
    expect(find.text('2026-10-02'), findsOneWidget);
    expect(find.text('В этот день поездок пока нет'), findsOneWidget);
    expect(find.text('2 040'), findsNothing);
  });

  testWidgets('network error can be retried', (tester) async {
    final api = FakeApi();
    api.onLoad = (_) async => throw const ApiException('Нет связи с сервером');
    await mount(tester, api);
    expect(find.text('Нет связи с сервером'), findsOneWidget);
    api.onLoad = (day) async => dayLog(dayLabel(day));
    await tester.tap(find.text('Повторить'));
    await tester.pumpAndSettle();
    expect(find.text('2 040'), findsOneWidget);
  });

  testWidgets(
    'invalid form is not posted; corrected overnight trip refreshes day',
    (tester) async {
      final api = FakeApi();
      await mount(tester, api);
      await openForm(tester);
      await enter(tester, 'amount', '0');
      await enter(tester, 'commission', '2500');
      await enter(tester, 'start-time', '23:50');
      await enter(tester, 'end-time', '00:10');
      await save(tester);
      expect(api.submitted, isEmpty);
      expect(find.text('Окончание должно быть позже начала'), findsOneWidget);
      await enter(tester, 'amount', '2400');
      await enter(tester, 'commission', '360');
      await enter(tester, 'end-date', '2026-10-02');
      await save(tester);
      expect(api.submitted, hasLength(1));
      expect(api.submitted.single.end, DateTime.utc(2026, 10, 1, 19, 10));
      expect(api.submitted.single.id, matches(RegExp(r'^[0-9a-f-]{36}$')));
      expect(api.loaded, ['2026-10-01', '2026-10-01']);
      expect(find.text('Поездка сохранена'), findsOneWidget);
    },
  );

  testWidgets(
    'uncertain save keeps identical payload and blocks double submission',
    (tester) async {
      final api = FakeApi();
      final saving = Completer<void>();
      api.onCreate = (_) => saving.future;
      await mount(tester, api);
      await openForm(tester);
      await enter(tester, 'amount', '1500');
      await tester.ensureVisible(find.byKey(const ValueKey('save-trip')));
      await tester.tap(find.byKey(const ValueKey('save-trip')));
      await tester.pump();
      expect(
        tester
            .widget<FilledButton>(find.byKey(const ValueKey('save-trip')))
            .onPressed,
        isNull,
      );
      expect(api.submitted, hasLength(1));
      saving.completeError(const ApiException('Нет связи с сервером'));
      await tester.pumpAndSettle();
      expect(
        tester
            .widget<TextFormField>(find.byKey(const ValueKey('amount')))
            .enabled,
        isFalse,
      );
      api.onCreate = (_) async {};
      await save(tester);
      expect(api.submitted, hasLength(2));
      expect(api.submitted[0].toJson(), api.submitted[1].toJson());
      expect(find.text('Поездка сохранена'), findsOneWidget);
    },
  );

  testWidgets('definitive validation failure keeps form data editable', (
    tester,
  ) async {
    final api = FakeApi();
    api.onCreate = (_) async =>
        throw const ApiException('Проверьте данные', statusCode: 422);
    await mount(tester, api);
    await openForm(tester);
    await enter(tester, 'amount', '1500');
    await save(tester);
    expect(find.text('Проверьте данные'), findsOneWidget);
    expect(
      tester
          .widget<TextFormField>(find.byKey(const ValueKey('amount')))
          .enabled,
      isTrue,
    );
    expect(
      tester
          .widget<TextFormField>(find.byKey(const ValueKey('amount')))
          .controller!
          .text,
      '1500',
    );
  });

  testWidgets('dashboard and form work at 360px without overflow', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(360, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final api = FakeApi();
    await mount(tester, api);
    expect(tester.takeException(), isNull);
    await openForm(tester);
    await enter(tester, 'amount', '1200');
    await save(tester);
    expect(api.submitted.single.amount, 1200);
    expect(tester.takeException(), isNull);
  });
}
