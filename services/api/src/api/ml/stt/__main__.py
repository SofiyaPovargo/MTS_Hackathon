"""CLI: python -m api.ml.stt <id> — распознать звонок, сохранить транскрипт JSON."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from api.ml.diarization.ports import DiarizationPort
from api.ml.stt.pipeline import TranscribePipeline, save_transcript
from api.settings import settings


def _diarizer(enable: bool) -> DiarizationPort | None:
    if enable and settings.hf_token:
        from api.ml.diarization.pyannote import PyannoteDiarizer

        return PyannoteDiarizer(settings.hf_token)
    return None


async def _run(args: argparse.Namespace) -> None:
    from api.ml.asr.tone import ToneASRClient

    audio_path = args.audio_dir / f"{args.conversation_id}.wav"
    if not audio_path.exists():
        raise FileNotFoundError(f"Аудио не найдено: {audio_path}")

    pipeline = TranscribePipeline(
        ToneASRClient(args.ws_url), _diarizer(not args.no_diarization)
    )
    transcript = await pipeline.transcribe_call(args.conversation_id, audio_path)

    out = save_transcript(transcript, args.out_dir)
    print(f"{args.conversation_id}: {len(transcript.segments)} сегментов -> {out}")
    for segment in transcript.segments:
        print(
            f"  [{segment.start:.2f}-{segment.end:.2f}] {segment.speaker}: {segment.text}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="STT-пайплайн: T-one ASR + pyannote диаризация"
    )
    parser.add_argument("conversation_id", help="Имя звонка <id>.wav в --audio-dir")
    parser.add_argument("--audio-dir", type=Path, default=settings.data_dir / "audio")
    parser.add_argument(
        "--out-dir", type=Path, default=settings.data_dir / "transcripts"
    )
    parser.add_argument("--ws-url", default=settings.asr_ws_url)
    parser.add_argument(
        "--no-diarization",
        action="store_true",
        help="Отключить диаризацию (все спикеры = unknown)",
    )
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
