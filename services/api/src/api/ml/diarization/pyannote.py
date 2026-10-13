"""Pyannote-диаризация через gated-модель speaker-diarization-3.1."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from api.ml.diarization.ports import SpeakerSegment

_MODEL = "pyannote/speaker-diarization-3.1"


class PyannoteDiarizer:
    """Обёртка над pyannote Pipeline (CPU-детект на стороне Mac)."""

    def __init__(self, hf_token: str) -> None:
        from pyannote.audio import Pipeline

        self._pipeline: Any = Pipeline.from_pretrained(_MODEL, token=hf_token)

    def diarize(self, audio_path: Path) -> list[SpeakerSegment]:
        output = self._pipeline(str(audio_path))
        annotation = output.speaker_diarization
        return [
            SpeakerSegment(speaker=label, start=segment.start, end=segment.end)
            for segment, _, label in annotation.itertracks(yield_label=True)
        ]
