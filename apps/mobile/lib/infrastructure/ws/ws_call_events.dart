import 'dart:convert';

import 'package:web_socket_channel/io.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../../domain/ports.dart';
import '../../domain/ws_event.dart';

/// WebSocket client for the live call event stream (`/api/ws/calls/{call_id}`).
/// Authentication is the access token in the `Authorization` header, the same as
/// REST. The injected connect function keeps the channel mockable in tests.
class WebSocketCallEvents implements CallEventsPort {
  WebSocketCallEvents({
    required String baseUrl,
    required Future<String?> Function() accessToken,
    WebSocketChannel Function(Uri uri, {Map<String, dynamic>? headers})? connect,
  })  : _baseUrl = baseUrl,
        _accessToken = accessToken,
        _connect = connect ?? _defaultConnect;

  static WebSocketChannel _defaultConnect(
    Uri uri, {
    Map<String, dynamic>? headers,
  }) =>
      IOWebSocketChannel.connect(uri, headers: headers);

  final String _baseUrl;
  final Future<String?> Function() _accessToken;
  final WebSocketChannel Function(Uri uri, {Map<String, dynamic>? headers})
      _connect;

  WebSocketChannel? _channel;
  Stream<CallEvent>? _events;

  /// `http(s)://host/api` → `ws(s)://host/api/ws/calls/{id}`.
  Uri wsUriFor(String callId) {
    final base = Uri.parse(_baseUrl);
    final scheme = base.scheme == 'https' ? 'wss' : 'ws';
    final path =
        '${base.path.replaceAll(RegExp(r'/+$'), '')}/ws/calls/$callId';
    return base.replace(scheme: scheme, path: path);
  }

  @override
  Future<void> connect(String callId) async {
    final token = await _accessToken();
    final headers = <String, dynamic>{
      if (token != null) 'Authorization': 'Bearer $token',
    };
    final uri = wsUriFor(callId);
    final channel = _connect(uri, headers: headers);
    _channel = channel;
    _events = channel.stream.map((raw) {
      final decoded = jsonDecode(raw as String);
      return CallEvent.fromJson(decoded as Map<String, dynamic>);
    });
  }

  @override
  Stream<CallEvent> get events {
    final stream = _events;
    if (stream == null) {
      throw StateError('connect() must complete before reading events');
    }
    return stream;
  }

  @override
  Future<void> disconnect() async {
    final channel = _channel;
    _channel = null;
    _events = null;
    await channel?.sink.close();
  }
}