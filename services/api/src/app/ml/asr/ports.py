"""ASR-порт и примитивы для интеграции со streaming-распознаванием T-one."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
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
    """Контракт потокового распознавания речи (батч)."""

    async def transcribe(self, pcm_int16: bytes) -> list[TextPhrase]:
        """Распознать поток 8кГц int16 PCM, вернуть фразы с таймкодами."""
        ...


class StreamingASRPort(ASRPort, Protocol):
    """Контракт live-распознавания: чанки на вход, фразы колбэком на выход."""

    async def stream(
        self,
        chunks: AsyncIterator[bytes],
        on_phrase: Callable[[TextPhrase], Awaitable[None]],
    ) -> None:
        """Стримить PCM-чанки и отдавать распознанные фразы по мере готовности."""
        ...
