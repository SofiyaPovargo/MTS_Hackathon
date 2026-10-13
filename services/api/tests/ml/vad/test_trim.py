"""Trim-функция VAD: обрезка краёв с сохранением таймлайна."""

from __future__ import annotations

import numpy as np
import pytest

from app.ml.vad.trim import trim_to_speech

SR = 8_000


def _pcm(seconds: float) -> bytes:
    return np.zeros(int(seconds * SR), dtype=np.int16).tobytes()


def test_trims_edges_and_returns_offset() -> None:
    trimmed, offset = trim_to_speech(_pcm(20.0), [(10.0, 11.0)], sample_rate=SR, pad_sec=0.2)
    assert offset == pytest.approx(9.8)
    assert len(trimmed) == pytest.approx((11.2 - 9.8) * SR * 2, abs=4)


def test_no_regions_returns_unchanged() -> None:
    pcm = _pcm(5.0)
    trimmed, offset = trim_to_speech(pcm, [], sample_rate=SR)
    assert trimmed == pcm
    assert offset == 0.0


def test_empty_pcm_returns_unchanged() -> None:
    assert trim_to_speech(b"", [(0.0, 1.0)], sample_rate=SR) == (b"", 0.0)


def test_full_span_keeps_audio() -> None:
    pcm = _pcm(5.0)
    trimmed, offset = trim_to_speech(pcm, [(0.0, 5.0)], sample_rate=SR, pad_sec=0.2)
    assert offset == 0.0
    assert len(trimmed) == len(pcm)


def test_internal_silence_preserved() -> None:
    # Речь в начале и в конце: середина (пауза) остаётся, ничего не режем.
    pcm = _pcm(10.0)
    trimmed, offset = trim_to_speech(
        pcm, [(0.0, 1.0), (9.0, 10.0)], sample_rate=SR, pad_sec=0.0
    )
    assert offset == 0.0
    assert len(trimmed) == len(pcm)
