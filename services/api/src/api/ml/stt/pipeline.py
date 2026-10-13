"""Оркестрация STT: загрузка аудио, ASR, диаризация, слияние, роли, JSON."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf  # type: ignore[import-untyped]
import soxr  # type: ignore[import-untyped]

from api.ml.asr.ports import ASRPort, TextPhrase
from api.ml.diarization.ports import DiarizationPort, SpeakerSegment
from api.ml.stt.schemas import (
    ROLE_CLIENT,
    ROLE_OPERATOR,
    ROLE_UNKNOWN,
    Transcript,
    TranscriptSegment,
)

PHONE_SAMPLE_RATE = 8_000


def read_phone_pcm(path: Path) -> bytes:
    """Прочитать wav и вернуть 8кГц mono int16 PCM (вход T-one)."""
    data, sample_rate = sf.read(path, dtype="float32")
    if data.ndim == 2:
        data = data[:, 0]
    if sample_rate != PHONE_SAMPLE_RATE:
        data = soxr.resample(data, sample_rate, PHONE_SAMPLE_RATE)
    int16 = (np.clip(data, -1.0, 1.0) * 32767.0).astype(np.int16)
    return int16.tobytes()


def overlap_seconds(
    a_start: float, a_end: float, b_start: float, b_end: float
) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def assign_speaker(phrase: TextPhrase, diary: list[SpeakerSegment]) -> str:
    """Выбрать спикера по максимальному пересечению с диаризацией."""
    best: SpeakerSegment | None = None
    best_overlap = 0.0
    for segment in diary:
        overlap = overlap_seconds(
            phrase.start_time, phrase.end_time, segment.start, segment.end
        )
        if overlap > best_overlap:
            best_overlap = overlap
            best = segment
    return best.speaker if best is not None else ROLE_UNKNOWN


def role_for_speaker(speaker: str, roles: dict[str, str]) -> str:
    return roles.get(speaker, ROLE_UNKNOWN)


def build_role_map(diary: list[SpeakerSegment]) -> dict[str, str]:
    """Operator = спикер, заговоривший первым; client = второй; остальные unknown."""
    order: list[str] = []
    for segment in sorted(diary, key=lambda s: s.start):
        if segment.speaker not in order:
            order.append(segment.speaker)
    return {
        speaker: ROLE_OPERATOR if i == 0 else ROLE_CLIENT if i == 1 else ROLE_UNKNOWN
        for i, speaker in enumerate(order)
    }


def merge(
    phrases: list[TextPhrase], diary: list[SpeakerSegment]
) -> list[TranscriptSegment]:
    """Привязать каждую фразу к спикеру и назначить роли operator/client."""
    roles = build_role_map(diary)
    return [
        TranscriptSegment(
            speaker=role_for_speaker(assign_speaker(phrase, diary), roles),
            text=phrase.text,
            start=phrase.start_time,
            end=phrase.end_time,
        )
        for phrase in phrases
    ]


def save_transcript(transcript: Transcript, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{transcript.conversation_id}.json"
    path.write_text(
        json.dumps(transcript.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


class TranscribePipeline:
    """Полный пайплайн: аудио -> сегментированный транскрипт с ролями."""

    def __init__(self, asr: ASRPort, diarizer: DiarizationPort | None = None) -> None:
        self._asr = asr
        self._diarizer = diarizer

    async def transcribe_call(
        self, conversation_id: str, audio_path: Path
    ) -> Transcript:
        pcm = read_phone_pcm(audio_path)
        phrases = await self._asr.transcribe(pcm)
        if self._diarizer is not None:
            diary = self._diarizer.diarize(audio_path)
            segments = merge(phrases, diary)
        else:
            segments = [
                TranscriptSegment(
                    speaker=ROLE_UNKNOWN,
                    text=p.text,
                    start=p.start_time,
                    end=p.end_time,
                )
                for p in phrases
            ]
        return Transcript(conversation_id=conversation_id, segments=segments)
