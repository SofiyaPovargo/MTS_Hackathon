"""Обрезка тишины по краям ноги с сохранением таймлайна.

Внутреннюю тишину не трогаем: стриминговому ASR (T-one) она нужна как граница
фраз. Удаляем только мёртвый воздух до первой и после последней речевой зоны и
возвращаем смещение, чтобы таймкоды фраз можно было вернуть на исходный
таймлайн (AGENTS: не терять аудио-таймстемпы).
"""

from __future__ import annotations

import numpy as np


def trim_to_speech(
    pcm_int16: bytes,
    regions: list[tuple[float, float]],
    *,
    sample_rate: int,
    pad_sec: float = 0.2,
) -> tuple[bytes, float]:
    """Обрезать края до ``[первая-пад, последняя+пад]``; вернуть ``(pcm, offset_sec)``.

    Если речевых зон нет или аудио пустое — вернуть вход без изменений и offset 0.
    """
    samples = np.frombuffer(pcm_int16, dtype=np.int16)
    if not regions or samples.size == 0:
        return pcm_int16, 0.0

    duration = samples.size / sample_rate
    first = min(start for start, _ in regions)
    last = max(end for _, end in regions)
    start_sec = max(0.0, first - pad_sec)
    end_sec = min(duration, last + pad_sec)

    start_idx = int(start_sec * sample_rate)
    end_idx = int(end_sec * sample_rate)
    if end_idx <= start_idx:
        return pcm_int16, 0.0
    trimmed = samples[start_idx:end_idx]
    if trimmed.size == samples.size:
        return pcm_int16, 0.0
    return trimmed.tobytes(), start_sec
