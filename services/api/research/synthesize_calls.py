"""Synthesize gold dialogues into telephony-like calls and refresh timestamps.

For each data/gold/<id>.json:
  1. synthesize each turn with Silero TTS (operator: xenia, client: aidar)
  2. concatenate turns with pauses -> orig wav (data/audio/<id>_orig.wav)
  3. apply telephony degradation via ffmpeg -> data/audio/<id>.wav
  4. rewrite gold dialogue turn timestamps and commitment audio times
     using the real synthesized durations.
"""

from __future__ import annotations

import json
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from synth_tts import SAMPLE_RATE, VOICES, speak

RESEARCH_DIR = Path(__file__).resolve().parent
GOLD_DIR = RESEARCH_DIR / "data" / "gold"
AUDIO_DIR = RESEARCH_DIR / "data" / "audio"

PAUSE_SEC = 0.35
FFMPEG = "ffmpeg"


def voice_for(speaker: str) -> str:
    return VOICES.get(speaker, VOICES["default"])


def write_wav(path: Path, audio: np.ndarray, sr: int = SAMPLE_RATE) -> None:
    data = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(data.tobytes())


def concat(
    segments: list[np.ndarray], pause: int
) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """Join segments with silence; return full buffer and (start,end) sample offsets."""
    out: list[np.ndarray] = []
    starts: list[tuple[int, int]] = []
    cur = 0
    for i, seg in enumerate(segments):
        start = cur + (pause if i else 0)
        end = start + len(seg)
        starts.append((start, end))
        if i:
            out.append(np.zeros(pause, dtype=np.float32))
        out.append(seg)
        cur = end
    return np.concatenate(out) if out else np.zeros(0, dtype=np.float32), starts


def to_phone_wav(src: Path, dst: Path) -> None:
    """Simulate a phone channel: band-limit, 8 kHz mono, G.711 mu-law."""
    tmp = dst.with_suffix(".mulaw")
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(src),
            "-af",
            "highpass=f=100,lowpass=f=3400",
            "-ar",
            "8000",
            "-ac",
            "1",
            "-c:a",
            "pcm_mulaw",
            "-f",
            "mulaw",
            str(tmp),
        ],
        check=True,
    )
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "mulaw",
            "-ar",
            "8000",
            "-ac",
            "1",
            "-i",
            str(tmp),
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            "-f",
            "wav",
            str(dst),
        ],
        check=True,
    )
    tmp.unlink(missing_ok=True)


def timestamp_for(start: int, end: int) -> tuple[float, float]:
    return round(start / SAMPLE_RATE, 2), round(end / SAMPLE_RATE, 2)


def process_case(case_path: Path, tts_ready: bool) -> bool:
    case = json.loads(case_path.read_text(encoding="utf-8"))
    turns = case["dialogue"]

    orig_path = AUDIO_DIR / f"{case['id']}_orig.wav"
    out_path = AUDIO_DIR / f"{case['id']}.wav"

    # reuse existing synthesis if durations already match the gold file
    if orig_path.exists():
        with wave.open(str(orig_path)) as wv:
            dur = wv.getnframes() / wv.getframerate()
        last_end = turns[-1]["end"] if turns else 0.0
        if abs(dur - last_end) < 0.1:
            to_phone_wav(orig_path, out_path)
            print(f"  {case['id']:28s} reuse  -> {out_path.relative_to(RESEARCH_DIR)}")
            return True

    segments: list[np.ndarray] = []
    for turn in turns:
        if not tts_ready:
            return False
        segments.append(speak(turn["text"], voice_for(turn["speaker"])))

    pause = int(PAUSE_SEC * SAMPLE_RATE)
    full, spans = concat(segments, pause)
    duration = len(full) / SAMPLE_RATE
    if len(full) == 0:
        return False

    write_wav(orig_path, full)

    # refresh dialogue timestamps
    for turn, (s, e) in zip(turns, spans):
        start, end = timestamp_for(s, e)
        turn["start"] = start
        turn["end"] = end

    # refresh commitment timestamps matched by quote
    quote_to_span = {}
    for turn, (s, e) in zip(turns, spans):
        quote_to_span[turn["text"]] = (s, e)
    for comm in case.get("expected_commitments", []):
        span = quote_to_span.get(comm["context_quote"])
        if span is None:
            print(f"  WARN {case['id']}: quote not matched: {comm['context_quote']!r}")
            continue
        start, end = timestamp_for(*span)
        comm["audio_start"] = start
        comm["audio_end"] = end

    # degrade and write final call audio
    to_phone_wav(orig_path, out_path)

    case_path.write_text(
        json.dumps(case, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"  {case['id']:28s} {duration:6.1f}s -> {out_path.relative_to(RESEARCH_DIR)}"
    )
    return True


def main() -> None:
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    cases = sorted(GOLD_DIR.glob("*.json"))
    if not cases:
        print("No gold cases found")
        return

    try:
        speak("тест", "aidar")  # force model download once
        tts_ready = True
    except Exception as exc:  # noqa: BLE001
        print(
            f"TTS unavailable: {exc}. Skipping synthesis (timestamps stay placeholder)."
        )
        tts_ready = False

    done = 0
    for case_path in cases:
        try:
            done += process_case(case_path, tts_ready)
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR {case_path.name}: {exc}")

    print(f"Processed {done}/{len(cases)} cases (TTS ready: {tts_ready}).")


if __name__ == "__main__":
    sys.path.insert(0, str(RESEARCH_DIR))
    main()
