import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import 'models.dart';
import 'shift_time.dart';

class ApiException implements Exception {
  const ApiException(this.message, {this.statusCode});
  final String message;
  final int? statusCode;

  // A failed response can arrive after the server has committed a write.
  bool get mayHaveSaved => statusCode == null || statusCode! >= 500;
}

class TripApi {
  TripApi({
    http.Client? client,
    String? baseUrl,
    this.timeout = const Duration(seconds: 15),
  }) : _client = client ?? http.Client(),
       _baseUrl = (baseUrl ?? const String.fromEnvironment('API_BASE_URL'))
           .replaceFirst(RegExp(r'/+$'), '');

  final http.Client _client;
  final String _baseUrl;
  final Duration timeout;

  Uri _uri(String path, [DateTime? day]) => Uri.parse('$_baseUrl/api/$path')
      .replace(queryParameters: day == null ? null : {'date': dayLabel(day)});

  Future<Object?> _request(String path, {DateTime? day, Trip? trip}) async {
    try {
      final response =
          await (trip == null
                  ? _client.get(_uri(path, day))
                  : _client.post(
                      _uri(path),
                      headers: {'Content-Type': 'application/json'},
                      body: jsonEncode(trip.toJson()),
                    ))
              .timeout(timeout);
      if (response.statusCode != 200 && response.statusCode != 201) {
        final message = switch (response.statusCode) {
          409 => 'Поездка с таким ID уже существует с другими данными. Проверьте список поездок.',
          422 => 'Сервер отклонил данные. Проверьте даты, время и суммы.',
          503 => 'Хранилище временно недоступно. Попробуйте ещё раз.',
          _ => 'Ошибка сервера (${response.statusCode}). Попробуйте ещё раз.',
        };
        throw ApiException(message, statusCode: response.statusCode);
      }
      return jsonDecode(utf8.decode(response.bodyBytes));
    } on TimeoutException {
      throw const ApiException(
        'Сервер не ответил вовремя. Проверьте соединение и повторите запрос.',
      );
    } on http.ClientException {
      throw const ApiException(
        'Нет связи с сервером. Проверьте соединение и повторите запрос.',
      );
    } on FormatException {
      throw const ApiException('Сервер вернул некорректные данные.');
    }
  }

  Future<DayLog> loadDay(DateTime day) async {
    final results = await Future.wait([
      _request('trips', day: day),
      _request('summary', day: day),
    ]);
    try {
      final trips = (results[0] as List)
          .map((item) => Trip.fromJson(item as Map<String, dynamic>))
          .toList();
      final summary = DailySummary.fromJson(results[1] as Map<String, dynamic>);
      if (summary.date != dayLabel(day)) {
        throw const FormatException('Wrong day');
      }
      return DayLog(trips, summary);
    } on FormatException {
      throw const ApiException(
        'Данные сервера некорректны или суммы слишком велики для браузера.',
      );
    } on TypeError {
      throw const ApiException('Сервер вернул некорректные данные.');
    }
  }

  Future<void> createTrip(Trip trip) async {
    // HTTP 200 is the successful idempotent replay; 201 is a new record.
    await _request('trips', trip: trip);
  }

  void close() => _client.close();
}
