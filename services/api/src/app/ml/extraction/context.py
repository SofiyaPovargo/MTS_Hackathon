"""Вход извлечения: контекст разговора и транскрипт (выход STT-пайплайна)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from app.ml.stt.schemas import TranscriptSegment


class ConversationContext(BaseModel):
    """Контекст, который видит LLM при извлечении договорённостей."""

    conversation_id: str
    conversation_date: date
    user_timezone: str
    participants: dict[str, str] = Field(default_factory=dict)
    transcript: list[TranscriptSegment]

    @property
    def duration(self) -> float:
        """Длительность звонка (последний конец фразы)."""
        return max((segment.end for segment in self.transcript), default=0.0)
