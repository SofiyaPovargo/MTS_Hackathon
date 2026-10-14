import 'package:agreement_capture/application/recording_service.dart';
import 'package:agreement_capture/domain/audio.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fakes.dart';

void main() {
  late FakeVoiceCallProvider voice;
  late InMemoryAudioRecordingStore store;
  late FakeAudioIngestApi ingest;
  late FakeLiveAudioPort live;
  late CallRecordingService service;

  setUp(() {
    voice = FakeVoiceCallProvider();
    store = InMemoryAudioRecordingStore();
    ingest = FakeAudioIngestApi();
    live = FakeLiveAudioPort();
    service = CallRecordingService(
      recorder: voice,
      store: store,
      ingest: ingest,
      live: live,
      chunkSize: 16,
    );
  });

  test('online: buffers locally, streams live and uploads on finish', () async {
    await service.start('c1', externalId: 'ext-1');
    expect(voice.mediaStreamOpened, <String>['ext-1']);
    expect(live.connected, <String>['c1']);

    voice.emitAudio(List<int>.filled(10, 1));
    await pumpEventQueue();
    voice.emitAudio(List<int>.filled(6, 2));
    await pumpEventQueue();

    final buffered = await store.get('c1');
    expect(buffered!.bytesTotal, 16);
    expect(live.frames, hasLength(16));

    await service.finish('c1');

    final done = await store.get('c1');
    expect(done!.status, RecordingUploadStatus.uploaded);
    expect(done.isUploaded, isTrue);
    expect(
      ingest.calls.fold<int>(0, (sum, call) => sum + call.length),
      16,
    );
    expect(live.closes, greaterThanOrEqualTo(1));
  });

  test('offline: keeps the whole call locally and uploads when back online',
      () async {
    await service.start('c2', externalId: 'ext-2');
    voice.emitAudio(List<int>.filled(20, 7));
    await pumpEventQueue();

    ingest.failRemaining = 100; // every attempt fails
    await service.finish('c2');

    final pending = await store.get('c2');
    expect(pending!.bytesTotal, 20);
    expect(pending.status, RecordingUploadStatus.pending);
    expect(await store.pending(), hasLength(1));

    ingest.failRemaining = 0;
    await service.uploadPending();

    final done = await store.get('c2');
    expect(done!.status, RecordingUploadStatus.uploaded);
    expect(await store.pending(), isEmpty);
  });

  test('network drop mid-upload leaves the rest pending to resume', () async {
    await service.start('c3', externalId: 'ext-3');
    voice.emitAudio(List<int>.filled(40, 9));
    await pumpEventQueue();

    ingest.failRemaining = 1; // the first chunk fails
    await service.finish('c3'); // chunkSize 16 → several requests
    expect((await store.get('c3'))!.status, RecordingUploadStatus.pending);

    await service.uploadPending();
    expect((await store.get('c3'))!.status, RecordingUploadStatus.uploaded);
    // The retry resumes from the beginning because no chunk was confirmed.
    expect(ingest.calls.first.start, 0);
  });

  test('a dead live socket never loses recorded audio', () async {
    live.down = true;
    await service.start('c4', externalId: 'ext-4');
    voice.emitAudio(List<int>.filled(8, 5));
    await pumpEventQueue();

    await service.finish('c4');
    final done = await store.get('c4');
    expect(done!.bytesTotal, 8);
    expect(done.status, RecordingUploadStatus.uploaded);
    expect(ingest.calls, isNotEmpty);
  });

  test('finish on a call that was never recorded is a no-op', () async {
    await service.finish('missing');
    expect(await store.get('missing'), isNull);
    expect(ingest.calls, isEmpty);
  });
}
