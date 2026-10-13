"""Silero TTS synthesis helpers for research data generation."""

from __future__ import annotations

from typing import Any

import numpy as np
import torch

SAMPLE_RATE = 48000  # v4_ru поддерживает 8000/24000/48000

VOICES = {
    "operator": "xenia",  # женский голос
    "client": "aidar",  # мужской голос
    "default": "random",
}

_model: Any = None


def get_tts() -> Any:
    """Load Silero TTS v4_ru (downloaded once via torch.hub)."""
    global _model
    if _model is None:
        loaded = torch.hub.load(
            repo_or_dir="snakers4/silero-models",
            model="silero_tts",
            language="ru",
            speaker="v4_ru",
            trust_repo=True,
        )
        _model = loaded[0] if isinstance(loaded, tuple) else loaded
    return _model


def speak(text: str, voice: str, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Synthesize text, return float32 mono audio normalized to [-1, 1]."""
    model = get_tts()
    audio = model.apply_tts(text=text, speaker=voice, sample_rate=sample_rate)
    if hasattr(audio, "numpy"):
        audio = audio.numpy()
    if audio.ndim > 1:
        audio = audio[:, 0]
    return audio.astype(np.float32)
