"""Схемы транскрипта (зеркалит research/schemas.py)."""

from __future__ import annotations

from pydantic import BaseModel, Field

ROLE_OPERATOR = "operator"
ROLE_CLIENT = "client"
ROLE_UNKNOWN = "unknown"
ROLES = (ROLE_OPERATOR, ROLE_CLIENT, ROLE_UNKNOWN)


class TranscriptSegment(BaseModel):
    """Фраза с назначенным спикером и таймкодами."""

    speaker: str = Field(pattern="|".join(ROLES))
    text: str
    start: float = Field(ge=0)
    end: float = Field(ge=0)


class Transcript(BaseModel):
    """Транскрипт одного звонка."""

    conversation_id: str
    segments: list[TranscriptSegment]
