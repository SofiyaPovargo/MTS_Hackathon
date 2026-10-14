import 'package:web_socket_channel/io.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../../domain/ports.dart';

/// WebSocket client for the live audio stream (`/api/ws/calls/{call_id}/audio`)
/// used for real-time analysis while the device is online.
///
/// Best-effort by design: the caller keeps buffering to the local store
/// regardless, so a failed socket never loses recorded audio (plan.md §13).
/// Authentication is the access token, exactly like [WebSocketCallEvents].
class WebSocketLiveAudio implements LiveAudioPort {
  WebSocketLiveAudio({
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

  /// `http(s)://host/api` → `ws(s)://host/api/ws/calls/{id}/audio?leg=mixed`.
  Uri wsUriFor(String callId, {String leg = 'mixed'}) {
    final base = Uri.parse(_baseUrl);
    final scheme = base.scheme == 'https' ? 'wss' : 'ws';
    final path =
        '${base.path.replaceAll(RegExp(r'/+$'), '')}/ws/calls/$callId/audio';
    return base.replace(
      scheme: scheme,
      path: path,
      queryParameters: <String, String>{'leg': leg},
    );
  }

  @override
  Future<void> connect(String callId) async {
    await close();
    final token = await _accessToken();
    final headers = <String, dynamic>{
      if (token != null) 'Authorization': 'Bearer $token',
    };
    _channel = _connect(wsUriFor(callId), headers: headers);
  }

  @override
  Future<void> send(List<int> frame) async {
    final channel = _channel;
    if (channel == null || frame.isEmpty) return;
    channel.sink.add(frame);
  }

  @override
  Future<void> close() async {
    final channel = _channel;
    _channel = null;
    await channel?.sink.close();
  }
}
