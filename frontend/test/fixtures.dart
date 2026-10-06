import 'package:driver_shift_log/models.dart';

const sampleTripJson = {
  'id': 't1',
  'start': '2026-10-01T08:10:00+05:00',
  'end': '2026-10-01T08:32:00+05:00',
  'amount': 2400,
  'payment': 'card',
  'commission': 360,
};

Map<String, Object> summaryJson(String day, {bool empty = false}) => {
  'date': day,
  'trip_count': empty ? 0 : 1,
  'revenue': empty ? 0 : 2400,
  'commission': empty ? 0 : 360,
  'take_home': empty ? 0 : 2040,
  'cash_revenue': 0,
  'card_revenue': empty ? 0 : 2400,
};

DayLog dayLog(String day, {bool empty = false}) => DayLog(
  empty ? [] : [Trip.fromJson(sampleTripJson)],
  DailySummary.fromJson(summaryJson(day, empty: empty)),
);
