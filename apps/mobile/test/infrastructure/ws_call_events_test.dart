import 'package:agreement_capture/infrastructure/ws/ws_call_events.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('ws URI derives from the API base URL (https → wss)', () {
    final client = WebSocketCallEvents(
      baseUrl: 'https://api.example.com/api',
      accessToken: () async => 'token',
    );
    expect(
      client.wsUriFor('call-1').toString(),
      'wss://api.example.com/api/ws/calls/call-1',
    );
  });

  test('http base maps to ws (emulator/simulator dev hosts)', () {
    final client = WebSocketCallEvents(
      baseUrl: 'http://10.0.2.2:8000/api',
      accessToken: () async => null,
    );
    expect(
      client.wsUriFor('call-2').toString(),
      'ws://10.0.2.2:8000/api/ws/calls/call-2',
    );
  });

  test('connect attaches the bearer token header on the handshake', () async {
    Uri? seenUri;
    Map<String, dynamic>? seenHeaders;
    final client = WebSocketCallEvents(
      baseUrl: 'https://api.example.com/api',
      accessToken: () async => 'secret-token',
      connect: (uri, {headers}) {
        seenUri = uri;
        seenHeaders = headers;
        throw UnimplementedError('socket is not opened in tests');
      },
    );

    await expectLater(
      client.connect('call-1'),
      throwsA(isA<UnimplementedError>()),
    );
    expect(seenUri.toString(), 'wss://api.example.com/api/ws/calls/call-1');
    expect(seenHeaders?['Authorization'], 'Bearer secret-token');
  });

  test('events require a completed connect', () {
    final client = WebSocketCallEvents(
      baseUrl: 'https://api.example.com/api',
      accessToken: () async => null,
    );
    expect(() => client.events, throwsStateError);
  });
}