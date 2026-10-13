"""Оркестрация STT: загрузка аудио, ASR, роли по каналам, диаризация, JSON.

Роли спикеров берутся двумя путями:

- **Каналы (VoIP).** Если запись разделена по ногам (стерео: левый канал —
  оператор, правый — собеседник), ASR гоняется по каждой ноге отдельно, а роли
  известны заранее из канала. Диаризация не нужна.
- **Диаризация (mono/PSTN).** Если есть только смешанный поток, фразы
  размечаются pyannote, а список ролей строится по первому/второму говорящему.

Пайплайн не решает, откуда пришло аудио: он принимает ``CallAudio`` с уже
декодированными 8 кГц int16 PCM ногами/смесью и выбирает путь по наличию ног.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import cast

import numpy as np
import soundfile as sf  # type: ignore[import-untyped]
import soxr  # type: ignore[import-untyped]

from app.ml.asr.ports import ASRPort, TextPhrase
from app.ml.diarization.ports import DiarizationPort, SpeakerSegment
from app.ml.stt.schemas import (
    ROLE_CLIENT,
    ROLE_OPERATOR,
    ROLE_UNKNOWN,
    RoleSource,
    Transcript,
    TranscriptSegment,
)
from app.ml.vad.ports import VadPort
from app.ml.vad.trim import trim_to_speech

PHONE_SAMPLE_RATE = 8_000


@dataclass(frozen=True)
class CallAudio:
    """Декодированные каналы звонка: ноги VoIP или смешанный поток (PSTN).

    ``operator``/``client`` заполнены, когда запись канало-раздельная; иначе
    используется ``mixed`` и диаризация.
    """

    operator: bytes | None = None
    client: bytes | None = None
    mixed: bytes | None = None

    @property
    def has_legs(self) -> bool:
        return self.operator is not None and self.client is not None


def _float_to_pcm(data: np.ndarray, sample_rate: int) -> bytes:
    if sample_rate != PHONE_SAMPLE_RATE:
        data = cast(np.ndarray, soxr.resample(data, sample_rate, PHONE_SAMPLE_RATE))
    int16 = (np.clip(data, -1.0, 1.0) * 32767.0).astype(np.int16)
    # numpy stubs type np.clip() as Any even for ndarray input; cast the result.
    return cast(bytes, int16.tobytes())


def read_phone_pcm(path: Path) -> bytes:
    """Прочитать wav и вернуть 8кГц mono int16 PCM (вход T-one)."""
    data, sample_rate = cast(tuple[np.ndarray, int], sf.read(path, dtype="float32"))
    if data.ndim == 2:
        data = data[:, 0]
    return _float_to_pcm(data, sample_rate)


def read_phone_pcm_legs(path: Path) -> tuple[bytes, bytes] | None:
    """Прочитать стерео-wav как две ноги (левый=operator, правый=client).

    ``None``, если файл не многоканальный — тогда нужен mono + диаризация.
    """
    data, sample_rate = cast(tuple[np.ndarray, int], sf.read(path, dtype="float32"))
    if data.ndim != 2 or data.shape[1] < 2:
        return None
    return (
        _float_to_pcm(data[:, 0], sample_rate),
        _float_to_pcm(data[:, 1], sample_rate),
    )


def decode_phone_pcm(data: bytes) -> bytes:
    """Декодировать байты аудио в 8кГц mono int16 PCM (для одной ноги)."""
    samples, sample_rate = cast(
        tuple[np.ndarray, int], sf.read(BytesIO(data), dtype="float32")
    )
    mono = samples[:, 0] if samples.ndim == 2 else samples
    return _float_to_pcm(mono, sample_rate)


def decode_phone_audio(data: bytes) -> CallAudio:
    """Декодировать байты аудио в 8кГц int16 PCM ноги/смесь.

    Стерео трактуется как раздельные ноги (левый=operator, правый=client);
    mono идёт как ``mixed`` и размечается диаризацией.
    """
    samples, sample_rate = cast(
        tuple[np.ndarray, int], sf.read(BytesIO(data), dtype="float32")
    )
    if samples.ndim == 2 and samples.shape[1] >= 2:
        return CallAudio(
            operator=_float_to_pcm(samples[:, 0], sample_rate),
            client=_float_to_pcm(samples[:, 1], sample_rate),
        )
    mono = samples[:, 0] if samples.ndim == 2 else samples
    return CallAudio(mixed=_float_to_pcm(mono, sample_rate))


def write_phone_pcm(pcm: bytes, path: Path) -> None:
    """Записать 8кГц int16 PCM во временный wav (вход диаризации)."""
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32767.0
    sf.write(path, samples, PHONE_SAMPLE_RATE, subtype="PCM_16")


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


def to_segments(phrases: list[TextPhrase], speaker: str) -> list[TranscriptSegment]:
    """Фразы одной ноги/спикера -> сегменты транскрипта."""
    return [
        TranscriptSegment(
            speaker=speaker, text=p.text, start=p.start_time, end=p.end_time
        )
        for p in phrases
    ]


def shift_phrases(phrases: list[TextPhrase], offset: float) -> list[TextPhrase]:
    """Сдвинуть таймкоды фраз на ``offset`` (после обрезки тишины по краям)."""
    if not offset:
        return phrases
    return [
        TextPhrase(
            text=p.text,
            start_time=p.start_time + offset,
            end_time=p.end_time + offset,
        )
        for p in phrases
    ]


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


def channel_transcript(
    conversation_id: str,
    operator_phrases: list[TextPhrase],
    client_phrases: list[TextPhrase],
) -> Transcript:
    """Транскрипт VoIP: роли берутся из каналов, фразы сортируются по времени."""
    segments = to_segments(operator_phrases, ROLE_OPERATOR) + to_segments(
        client_phrases, ROLE_CLIENT
    )
    segments.sort(key=lambda segment: (segment.start, segment.end))
    return Transcript(
        conversation_id=conversation_id,
        segments=segments,
        role_source=RoleSource.channel,
    )


def plain_transcript(
    conversation_id: str, phrases: list[TextPhrase]
) -> Transcript:
    """Транскрипт без ролей (диаризация недоступна)."""
    return Transcript(
        conversation_id=conversation_id,
        segments=to_segments(phrases, ROLE_UNKNOWN),
        role_source=RoleSource.unknown,
    )


def diarized_transcript(
    conversation_id: str, phrases: list[TextPhrase], diary: list[SpeakerSegment]
) -> Transcript:
    """Транскрипт mono/PSTN: роли берутся из диаризации."""
    return Transcript(
        conversation_id=conversation_id,
        segments=merge(phrases, diary),
        role_source=RoleSource.diarization,
    )


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

    def __init__(
        self,
        asr: ASRPort,
        diarizer: DiarizationPort | None = None,
        vad: VadPort | None = None,
        *,
        vad_pad_sec: float = 0.2,
    ) -> None:
        self._asr = asr
        self._diarizer = diarizer
        self._vad = vad
        self._vad_pad_sec = vad_pad_sec

    def _prepare(self, pcm: bytes) -> tuple[bytes, float]:
        """VAD-обрезка краёв (если VAD задан); вернуть ``(pcm, offset_sec)``."""
        if self._vad is None:
            return pcm, 0.0
        regions = self._vad.speech_segments(pcm, sample_rate=PHONE_SAMPLE_RATE)
        return trim_to_speech(
            pcm, regions, sample_rate=PHONE_SAMPLE_RATE, pad_sec=self._vad_pad_sec
        )

    async def _transcribe_leg(self, pcm: bytes) -> list[TextPhrase]:
        """Прогнать одну ногу через VAD + ASR; вернуть фразы на исходном таймлайне."""
        prepared, offset = self._prepare(pcm)
        phrases = await self._asr.transcribe(prepared)
        return shift_phrases(phrases, offset)

    async def transcribe_audio(
        self, conversation_id: str, audio: CallAudio
    ) -> Transcript:
        """Выбрать путь по каналам: ноги VoIP или смесь + диаризация."""
        if audio.has_legs:
            operator_phrases = await self._transcribe_leg(cast(bytes, audio.operator))
            client_phrases = await self._transcribe_leg(cast(bytes, audio.client))
            return channel_transcript(
                conversation_id, operator_phrases, client_phrases
            )

        mixed = audio.mixed or b""
        # С диаризацией ASR и pyannote делят один таймлайн полного потока,
        # поэтому VAD-обрезку не применяем; без диаризации — обрезаем края.
        if self._diarizer is None:
            return plain_transcript(conversation_id, await self._transcribe_leg(mixed))
        phrases = await self._asr.transcribe(mixed)
        diary = self._diarize(mixed)
        if diary is not None:
            return diarized_transcript(conversation_id, phrases, diary)
        return plain_transcript(conversation_id, phrases)

    async def transcribe_call(
        self, conversation_id: str, audio_path: Path
    ) -> Transcript:
        """CLI-путь: читает файл, стерео — как ноги, mono — как смесь."""
        legs = read_phone_pcm_legs(audio_path)
        audio = (
            CallAudio(operator=legs[0], client=legs[1])
            if legs is not None
            else CallAudio(mixed=read_phone_pcm(audio_path))
        )
        return await self.transcribe_audio(conversation_id, audio)

    def _diarize(self, pcm: bytes) -> list[SpeakerSegment] | None:
        """Диаризация смешанного потока через временный wav (pyannote — файл)."""
        if self._diarizer is None:
            return None
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mixed.wav"
            write_phone_pcm(pcm, path)
            return self._diarizer.diarize(path)
