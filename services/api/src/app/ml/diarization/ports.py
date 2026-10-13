"""Диаризация: порт и результат спикер-сегментации."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class SpeakerSegment:
    """Сегмент речи одного спикера."""

    speaker: str
    start: float
    end: float


class DiarizationPort(Protocol):
    """Контракт диаризации: кто говорит в каждый момент."""

    def diarize(self, audio_path: Path) -> list[SpeakerSegment]:
        """Вернуть сегменты спикеров для аудиофайла."""
        ...
