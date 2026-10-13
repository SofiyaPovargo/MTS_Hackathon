"""Роли спикеров: каналы (VoIP) против диаризации (mono/PSTN)."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf  # type: ignore[import-untyped]

from app.ml.asr.ports import TextPhrase
from app.ml.diarization.ports import SpeakerSegment
from app.ml.stt.pipeline import (
    CallAudio,
    TranscribePipeline,
    channel_transcript,
    decode_phone_audio,
    read_phone_pcm_legs,
)
from app.ml.stt.schemas import RoleSource


class FakeASR:
    """Отдаёт заранее заданные фразы по номеру вызова (нога за ногой)."""

    def __init__(self, phrases: list[list[TextPhrase]]) -> None:
        self._phrases = phrases
        self.calls: list[bytes] = []

    async def transcribe(self, pcm_int16: bytes) -> list[TextPhrase]:
        index = len(self.calls)
        self.calls.append(pcm_int16)
        return self._phrases[index] if index < len(self._phrases) else []


class FakeDiarizer:
    def __init__(self, segments: list[SpeakerSegment]) -> None:
        self._segments = segments
        self.calls = 0

    def diarize(self, audio_path: Path) -> list[SpeakerSegment]:
        self.calls += 1
        return self._segments


def _leg(marker: int) -> bytes:
    """Один int16-сэмпл как псевдо-нога (содержимое для FakeASR не важно)."""
    return np.array([marker], dtype=np.int16).tobytes()


def test_channel_transcript_roles_and_order() -> None:
    transcript = channel_transcript(
        "c1",
        operator_phrases=[TextPhrase("оператор", 2.0, 3.0)],
        client_phrases=[TextPhrase("клиент", 0.0, 1.0)],
    )
    assert transcript.role_source is RoleSource.channel
    assert [s.speaker for s in transcript.segments] == ["client", "operator"]
    assert [s.text for s in transcript.segments] == ["клиент", "оператор"]


@pytest.mark.asyncio
async def test_legs_use_channels_without_diarization() -> None:
    asr = FakeASR(
        [
            [TextPhrase("оператор", 2.0, 3.0)],
            [TextPhrase("клиент", 0.0, 1.0)],
        ]
    )
    diarizer = FakeDiarizer([])
    pipeline = TranscribePipeline(asr, diarizer)

    transcript = await pipeline.transcribe_audio(
        "c1", CallAudio(operator=_leg(1), client=_leg(2))
    )

    assert transcript.role_source is RoleSource.channel
    assert [s.speaker for s in transcript.segments] == ["client", "operator"]
    assert len(asr.calls) == 2  # по ноге на канал
    assert diarizer.calls == 0  # диаризация не нужна


@pytest.mark.asyncio
async def test_mixed_audio_uses_diarization() -> None:
    asr = FakeASR([[TextPhrase("первая", 0.0, 1.0), TextPhrase("вторая", 1.2, 1.8)]])
    diary = [SpeakerSegment("A", 0.0, 1.0), SpeakerSegment("B", 1.1, 2.0)]
    diarizer = FakeDiarizer(diary)
    pipeline = TranscribePipeline(asr, diarizer)

    transcript = await pipeline.transcribe_audio("c1", CallAudio(mixed=_leg(0)))

    assert transcript.role_source is RoleSource.diarization
    assert [s.speaker for s in transcript.segments] == ["operator", "client"]
    assert diarizer.calls == 1


@pytest.mark.asyncio
async def test_mixed_audio_without_diarizer_is_unknown() -> None:
    asr = FakeASR([[TextPhrase("текст", 0.0, 1.0)]])
    pipeline = TranscribePipeline(asr)

    transcript = await pipeline.transcribe_audio("c1", CallAudio(mixed=_leg(0)))

    assert transcript.role_source is RoleSource.unknown
    assert transcript.segments[0].speaker == "unknown"


def _wav(channels: np.ndarray, sample_rate: int = 8_000) -> bytes:
    buffer = io.BytesIO()
    sf.write(buffer, channels, sample_rate, format="WAV")
    return buffer.getvalue()


def test_decode_stereo_splits_legs() -> None:
    left = np.full(8_000, 0.5, dtype=np.float32)
    right = np.full(8_000, -0.5, dtype=np.float32)
    audio = decode_phone_audio(_wav(np.stack([left, right], axis=1)))
    assert audio.has_legs
    assert audio.operator is not None and audio.client is not None


def test_decode_mono_falls_back_to_mixed() -> None:
    audio = decode_phone_audio(_wav(np.zeros(8_000, dtype=np.float32)))
    assert not audio.has_legs
    assert audio.mixed is not None


def test_read_phone_pcm_legs_none_for_mono(tmp_path: Path) -> None:
    path = tmp_path / "mono.wav"
    path.write_bytes(_wav(np.zeros(8_000, dtype=np.float32)))
    assert read_phone_pcm_legs(path) is None


def test_read_phone_pcm_legs_for_stereo(tmp_path: Path) -> None:
    path = tmp_path / "stereo.wav"
    audio = np.stack(
        [np.full(16_000, 0.5, dtype=np.float32), np.full(16_000, -0.5, dtype=np.float32)],
        axis=1,
    )
    path.write_bytes(_wav(audio, sample_rate=16_000))
    legs = read_phone_pcm_legs(path)
    assert legs is not None
    assert len(legs[0]) == 8_000 * 2  # 16кГц -> 8кГц int16
