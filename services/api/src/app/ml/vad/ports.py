"""Порт VAD: где в ноге/потоке есть речь."""

from __future__ import annotations

from typing import Protocol


class VadPort(Protocol):
    """Контракт детектора речи (Silero VAD в проде, fake — в тестах)."""

    def speech_segments(
        self, pcm_int16: bytes, *, sample_rate: int
    ) -> list[tuple[float, float]]:
        """Вернуть речевые интервалы ``(start_sec, end_sec)`` на таймлайне аудио."""
        ...
