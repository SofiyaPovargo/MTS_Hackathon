"""ASR-порт и примитивы для интеграции со streaming-распознаванием T-one."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

# Модель T-one обучена на 8 кГц, 300 мс чанк = 2400 сэмплов.
SAMPLE_RATE = 8_000
CHUNK_SAMPLES = 2_400
BYTES_PER_SAMPLE = 2
CHUNK_BYTES = CHUNK_SAMPLES * BYTES_PER_SAMPLE


@dataclass(frozen=True)
class TextPhrase:
    """Распознанная фраза с таймкодами (событие `transcript`)."""

    text: str
    start_time: float
    end_time: float


class ASRPort(Protocol):
    """Контракт streaming-распознавания речи."""

    async def transcribe(self, pcm_int16: bytes) -> list[TextPhrase]:
        """Распознать поток 8кГц int16 PCM, вернуть фразы с таймкодами."""
        ...
