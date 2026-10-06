import 'package:driver_shift_log/models.dart';
import 'package:driver_shift_log/shift_time.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('calendar parsing rejects invalid and normalized dates', () {
    expect(parseDay('2024-02-29'), DateTime.utc(2024, 2, 29));
    for (final input in [
      '2026-02-29',
      '2026-13-01',
      '2026-10-32',
      '2026-1-01',
      '0000-01-01',
      'abc',
    ]) {
      expect(parseDay(input), isNull, reason: input);
    }
  });

  test('form times use Almaty instead of browser timezone', () {
    expect(
      parseAlmatyTime('2026-10-01', '08:10'),
      DateTime.utc(2026, 10, 1, 3, 10),
    );
    expect(
      parseAlmatyTime('2026-10-02', '00:10'),
      DateTime.utc(2026, 10, 1, 19, 10),
    );
    // Almaty used UTC+06 before March 2024.
    expect(
      parseAlmatyTime('2023-10-01', '08:10'),
      DateTime.utc(2023, 10, 1, 2, 10),
    );
    for (final time in ['24:00', '12:60', '8:30', '', '09:30:00']) {
      expect(parseAlmatyTime('2026-10-01', time), isNull);
    }
  });

  test('display converts UTC midnight boundary to Almaty', () {
    final instant = DateTime.parse('2026-09-30T19:10:00Z');
    expect(dayLabel(inAlmaty(instant)), '2026-10-01');
    expect(timeLabel(instant), '00:10');
  });

  test('money formatting and browser integer precision are explicit', () {
    expect(money(3900), '3 900');
    expect(money(0), '0');
    expect(readInteger(maxSafeInteger), maxSafeInteger);
    expect(() => readInteger(maxSafeInteger + 1), throwsFormatException);
    expect(() => readInteger(1.5), throwsFormatException);
  });
}
