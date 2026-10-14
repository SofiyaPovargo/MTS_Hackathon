"""Порт LLM-резюме звонка и входной контракт."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.ml.stt.schemas import TranscriptSegment


@dataclass(frozen=True)
class AgreementFact:
    """Факты договорённости, которые видит суммаризатор (без PII сверх нужного)."""

    type: str
    title: str
    owner: str
    due: str | None
    status: str


@dataclass(frozen=True)
class SummaryInput:
    """Вход суммаризатора: контекст звонка, транскрипт и извлечённые договорённости."""

    conversation_id: str
    client_label: str
    transcript: list[TranscriptSegment]
    agreements: list[AgreementFact]


class SummaryPort(Protocol):
    """Контракт генерации резюме разговора."""

    async def summarize(self, data: SummaryInput) -> str:
        """Вернуть краткое резюме разговора по транскрипту и договорённостям."""
        ...
