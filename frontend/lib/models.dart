// JavaScript cannot represent all SQLite int64 values exactly. Fail visibly
// outside the safe range instead of displaying or submitting rounded money.
const maxSafeInteger = 9007199254740991;

int readInteger(Object? value) {
  if (value is! int || value < 0 || value > maxSafeInteger) {
    throw const FormatException('Expected a safe nonnegative integer');
  }
  return value;
}

String money(int value) => value.toString().replaceAllMapped(
  RegExp(r'(\d)(?=(\d{3})+$)'),
  (match) => '${match[1]} ',
);

class Trip {
  const Trip({
    required this.id,
    required this.start,
    required this.end,
    required this.amount,
    required this.payment,
    required this.commission,
  });

  factory Trip.fromJson(Map<String, dynamic> json) {
    final trip = Trip(
      id: json['id'] as String,
      start: DateTime.parse(json['start'] as String),
      end: DateTime.parse(json['end'] as String),
      amount: readInteger(json['amount']),
      payment: json['payment'] as String,
      commission: readInteger(json['commission']),
    );
    if (trip.id.isEmpty ||
        !trip.start.isUtc ||
        !trip.end.isUtc ||
        !trip.end.isAfter(trip.start) ||
        trip.amount == 0 ||
        trip.commission > trip.amount ||
        !{'cash', 'card'}.contains(trip.payment)) {
      throw const FormatException('Invalid trip');
    }
    return trip;
  }

  final String id;
  final DateTime start;
  final DateTime end;
  final int amount;
  final String payment;
  final int commission;

  Map<String, dynamic> toJson() => {
    'id': id,
    'start': start.toUtc().toIso8601String(),
    'end': end.toUtc().toIso8601String(),
    'amount': amount,
    'payment': payment,
    'commission': commission,
  };
}

class DailySummary {
  const DailySummary({
    required this.date,
    required this.tripCount,
    required this.revenue,
    required this.commission,
    required this.takeHome,
    required this.cashRevenue,
    required this.cardRevenue,
  });

  factory DailySummary.fromJson(Map<String, dynamic> json) => DailySummary(
    date: json['date'] as String,
    tripCount: readInteger(json['trip_count']),
    revenue: readInteger(json['revenue']),
    commission: readInteger(json['commission']),
    takeHome: readInteger(json['take_home']),
    cashRevenue: readInteger(json['cash_revenue']),
    cardRevenue: readInteger(json['card_revenue']),
  );

  final String date;
  final int tripCount;
  final int revenue;
  final int commission;
  final int takeHome;
  final int cashRevenue;
  final int cardRevenue;
}

class DayLog {
  const DayLog(this.trips, this.summary);
  final List<Trip> trips;
  final DailySummary summary;
}
