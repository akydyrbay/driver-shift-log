import 'package:timezone/data/latest.dart' as database;
import 'package:timezone/timezone.dart' as tz;

final tz.Location _almaty = _loadAlmaty();

tz.Location _loadAlmaty() {
  database.initializeTimeZones();
  return tz.getLocation('Asia/Almaty');
}

DateTime inAlmaty(DateTime instant) => tz.TZDateTime.from(instant, _almaty);

// Calendar dates are carried as UTC midnight, not browser-local instants.
DateTime calendarDay(DateTime value) =>
    DateTime.utc(value.year, value.month, value.day);

DateTime todayInAlmaty() => calendarDay(inAlmaty(DateTime.now()));

String dayLabel(DateTime day) =>
    '${day.year.toString().padLeft(4, '0')}-${_two(day.month)}-${_two(day.day)}';

String timeLabel(DateTime instant) {
  final value = inAlmaty(instant);
  return '${_two(value.hour)}:${_two(value.minute)}';
}

String _two(int value) => value.toString().padLeft(2, '0');

DateTime? parseDay(String input) {
  final value = input.trim();
  if (!RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(value)) return null;
  final result = DateTime.tryParse('${value}T00:00:00Z');
  return result != null && result.year >= 1 && dayLabel(result) == value
      ? result
      : null;
}

DateTime? parseAlmatyTime(String date, String time) {
  final day = parseDay(date);
  final match = RegExp(r'^([01]\d|2[0-3]):([0-5]\d)$').firstMatch(time.trim());
  if (day == null || match == null) return null;
  final hour = int.parse(match[1]!);
  final minute = int.parse(match[2]!);
  final result = tz.TZDateTime(
    _almaty,
    day.year,
    day.month,
    day.day,
    hour,
    minute,
  );
  // Do not silently normalize nonexistent wall times during historical DST.
  if (result.hour != hour || result.minute != minute || result.day != day.day) {
    return null;
  }
  return result.toUtc();
}
