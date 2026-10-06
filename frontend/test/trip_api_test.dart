import 'dart:async';
import 'dart:convert';

import 'package:driver_shift_log/models.dart';
import 'package:driver_shift_log/trip_api.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'fixtures.dart';

void main() {
  test(
    'both daily endpoints receive the selected date and configured base URL',
    () async {
      final paths = <String>[];
      final api = TripApi(
        baseUrl: 'http://localhost:8000/',
        client: MockClient((request) async {
          expect(request.url.origin, 'http://localhost:8000');
          expect(request.url.queryParameters, {'date': '2026-10-01'});
          paths.add(request.url.path);
          return http.Response(
            jsonEncode(
              request.url.path.endsWith('summary')
                  ? summaryJson('2026-10-01')
                  : [sampleTripJson],
            ),
            200,
          );
        }),
      );
      addTearDown(api.close);
      final result = await api.loadDay(DateTime.utc(2026, 10, 1));
      expect(paths, containsAll(['/api/trips', '/api/summary']));
      expect(result.trips.single.amount, 2400);
      expect(result.summary.takeHome, 2040);
    },
  );

  test('default URLs are same-origin and POST 200/201 both succeed', () async {
    for (final status in [200, 201]) {
      final api = TripApi(
        baseUrl: '',
        client: MockClient((request) async {
          expect(request.url.toString(), '/api/trips');
          expect(request.method, 'POST');
          expect(request.headers['content-type'], 'application/json');
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          expect(body['id'], 't1');
          expect(body['start'], '2026-10-01T03:10:00.000Z');
          return http.Response(jsonEncode(sampleTripJson), status);
        }),
      );
      addTearDown(api.close);
      await api.createTrip(Trip.fromJson(sampleTripJson));
    }
  });

  for (final status in [409, 422, 503]) {
    test(
      'HTTP $status produces a readable error and correct save certainty',
      () async {
        final api = TripApi(
          client: MockClient((_) async => http.Response('{}', status)),
        );
        addTearDown(api.close);
        await expectLater(
          api.createTrip(Trip.fromJson(sampleTripJson)),
          throwsA(
            isA<ApiException>()
                .having((e) => e.statusCode, 'status', status)
                .having(
                  (e) => e.mayHaveSaved,
                  'uncertain write',
                  status >= 500,
                ),
          ),
        );
      },
    );
  }

  test('network errors and timeouts have retryable messages', () async {
    final offline = TripApi(
      client: MockClient((_) async => throw http.ClientException('offline')),
    );
    addTearDown(offline.close);
    await expectLater(
      offline.loadDay(DateTime.utc(2026, 10, 1)),
      throwsA(isA<ApiException>()),
    );
    final slow = TripApi(
      timeout: const Duration(milliseconds: 1),
      client: MockClient((_) => Completer<http.Response>().future),
    );
    addTearDown(slow.close);
    await expectLater(
      slow.createTrip(Trip.fromJson(sampleTripJson)),
      throwsA(
        isA<ApiException>().having(
          (e) => e.mayHaveSaved,
          'uncertain write',
          true,
        ),
      ),
    );
  });

  test(
    'malformed or unsafe server data produces errors, not wrong totals',
    () async {
      for (final body in [
        '<html>error</html>',
        jsonEncode({'unexpected': true}),
        jsonEncode({...summaryJson('2026-10-02')}),
        jsonEncode({
          ...summaryJson('2026-10-01'),
          'revenue': maxSafeInteger + 1,
        }),
      ]) {
        final api = TripApi(
          client: MockClient(
            (request) async => http.Response(
              request.url.path.endsWith('summary') ? body : '[]',
              200,
            ),
          ),
        );
        addTearDown(api.close);
        await expectLater(
          api.loadDay(DateTime.utc(2026, 10, 1)),
          throwsA(isA<ApiException>()),
        );
      }
    },
  );
}
