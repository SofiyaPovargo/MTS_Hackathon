"""VAD (voice activity detection) — речевые интервалы в mono PCM (plan.md §12)."""

from app.ml.vad.ports import VadPort
from app.ml.vad.silero import SileroVad
from app.ml.vad.trim import trim_to_speech

__all__ = ["SileroVad", "VadPort", "trim_to_speech"]
