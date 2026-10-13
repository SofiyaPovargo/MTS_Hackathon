"""Тесты слияния фраз ASR с диаризацией и назначения ролей."""

from __future__ import annotations

from pathlib import Path

from app.ml.asr.ports import TextPhrase
from app.ml.diarization.ports import SpeakerSegment
from app.ml.stt.pipeline import build_role_map, merge, read_phone_pcm


def test_merge_assigns_speaker_by_max_overlap() -> None:
    phrases = [
        TextPhrase("первая", 0.0, 1.0),
        TextPhrase("вторая", 1.1, 2.0),
    ]
    diary = [
        SpeakerSegment("SPEAKER_01", 0.0, 1.0),
        SpeakerSegment("SPEAKER_00", 1.2, 2.2),
    ]
    segments = merge(phrases, diary)

    assert [s.text for s in segments] == ["первая", "вторая"]
    assert segments[0].speaker == "operator"
    assert segments[1].speaker == "client"


def test_build_role_map_first_operator_second_client() -> None:
    diary = [
        SpeakerSegment("SPEAKER_00", 5.0, 6.0),
        SpeakerSegment("SPEAKER_01", 0.0, 1.0),
        SpeakerSegment("SPEAKER_02", 2.0, 3.0),
    ]
    roles = build_role_map(diary)
    assert roles["SPEAKER_01"] == "operator"  # заговорил первым (start=0.0)
    assert roles["SPEAKER_02"] == "client"  # вторым (start=2.0)
    assert roles["SPEAKER_00"] == "unknown"


def test_merge_unknown_when_no_diary() -> None:
    segments = merge([TextPhrase("текст", 0.0, 1.0)], [])
    assert segments[0].speaker == "unknown"


def test_read_phone_pcm_resamples_to_8k(tmp_path: Path) -> None:
    import io

    import numpy as np
    import soundfile as sf  # type: ignore[import-untyped]

    buffer = io.BytesIO()
    sf.write(buffer, np.zeros(16_000, dtype=np.float32), 16_000, format="WAV")
    buffer.seek(0)

    path = tmp_path / "phone.wav"
    path.write_bytes(buffer.read())

    pcm = read_phone_pcm(path)
    assert len(pcm) == 16_000 // 2 * 2  # 8кГц int16
