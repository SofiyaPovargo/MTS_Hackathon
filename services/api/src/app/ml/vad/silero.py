"""Silero VAD адаптер (silero-vad из optional-группы `ml`).

Импорт тяжёлых зависимостей — ленивый, внутри методов: модуль импортируется и
без установленной группы `ml` (важно для лёгкого API-образа и тестов).
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.ml.vad.ports import VadPort


class SileroVad(VadPort):
    """Детектор речи Silero VAD, работает на 8 или 16 кГц."""

    def __init__(
        self,
        *,
        threshold: float = 0.5,
        min_speech_ms: int = 100,
        min_silence_ms: int = 100,
    ) -> None:
        self._threshold = threshold
        self._min_speech_ms = min_speech_ms
        self._min_silence_ms = min_silence_ms
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            from silero_vad import load_silero_vad

            self._model = load_silero_vad()
        return self._model

    def speech_segments(
        self, pcm_int16: bytes, *, sample_rate: int
    ) -> list[tuple[float, float]]:
        import torch
        from silero_vad import get_speech_timestamps

        model = self._load()
        samples = np.frombuffer(pcm_int16, dtype=np.int16).astype(np.float32) / 32768.0
        tensor = torch.from_numpy(samples)
        stamps = get_speech_timestamps(
            tensor,
            model,
            sampling_rate=sample_rate,
            threshold=self._threshold,
            min_speech_duration_ms=self._min_speech_ms,
            min_silence_duration_ms=self._min_silence_ms,
        )
        return [
            (stamp["start"] / sample_rate, stamp["end"] / sample_rate)
            for stamp in stamps
        ]
