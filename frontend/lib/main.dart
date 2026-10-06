import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'dashboard.dart';
import 'trip_api.dart';

void main() => runApp(const DriverShiftLogApp());

class DriverShiftLogApp extends StatefulWidget {
  const DriverShiftLogApp({super.key, this.api, this.initialDay});
  final TripApi? api;
  final DateTime? initialDay;

  @override
  State<DriverShiftLogApp> createState() => _DriverShiftLogAppState();
}

class _DriverShiftLogAppState extends State<DriverShiftLogApp> {
  late final _api = widget.api ?? TripApi();

  @override
  void dispose() {
    if (widget.api == null) _api.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'Дневник смен водителя',
    debugShowCheckedModeBanner: false,
    locale: const Locale('ru'),
    supportedLocales: const [Locale('ru')],
    localizationsDelegates: GlobalMaterialLocalizations.delegates,
    theme: ThemeData(
      colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF176B5B)),
      scaffoldBackgroundColor: const Color(0xFFF5F7F6),
      useMaterial3: true,
    ),
    home: Dashboard(api: _api, initialDay: widget.initialDay),
  );
}
