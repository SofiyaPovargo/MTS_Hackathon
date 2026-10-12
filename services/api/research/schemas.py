"""Research-stage Pydantic schemas for commitment extraction.

Mirrors the domain models that will later live in src/api/domain/.
"""
from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field


class CommitmentType(StrEnum):
    deadline = "deadline"  # обещанный срок/дедлайн
    meeting = "meeting"  # встреча/созвон
    payment = "payment"  # оплата/перевод
    promise = "promise"  # обещание/обязательство
    follow_up = "follow_up"  # перезвонить/напомнить
    open_question = "open_question"  # открытый вопрос


class Owner(StrEnum):
    user = "user"
    counterparty = "counterparty"
    unknown = "unknown"


class CommitmentStatus(StrEnum):
    proposed = "proposed"
    needs_clarification = "needs_clarification"
    confirmed = "confirmed"
    rejected = "rejected"


class Commitment(BaseModel):
    """Конечная договорённость (то, что должен вернуть экстрактор)."""

    type: CommitmentType
    title: str = Field(description="Краткая формулировка договорённости")
    owner: Owner
    due_date: date | None = None
    due_time: time | None = None
    amount: Decimal | None = Field(default=None, gt=0)
    currency: str | None = None
    context_quote: str = Field(description="Дословная цитата из транскрипта")
    audio_start: float = Field(ge=0)
    audio_end: float = Field(ge=0)
    confidence: float = Field(default=1.0, ge=0, le=1)
    status: CommitmentStatus = CommitmentStatus.proposed
    uncertainty: list[str] = Field(default_factory=list)


class TranscriptSegment(BaseModel):
    speaker: str  # operator | client | unknown
    text: str
    start: float
    end: float


class ConversationContext(BaseModel):
    conversation_id: str
    conversation_date: date
    user_timezone: str
    transcript: list[TranscriptSegment]


class ExtractionResult(BaseModel):
    commitments: list[Commitment]


class DialogueTurn(BaseModel):
    speaker: str
    text: str


class ExpectedCommitment(BaseModel):
    """Разметка ожидаемой договорённости в gold-файле.

    context_quote и аудио-таймстампы берутся из реплики dialogue[turn_index].
    """

    turn_index: int
    type: CommitmentType
    title: str
    owner: Owner
    due_date: date | None = None
    due_time: time | None = None
    amount: Decimal | None = Field(default=None, gt=0)
    currency: str | None = None
    status: CommitmentStatus = CommitmentStatus.proposed
    uncertainty: list[str] = Field(default_factory=list)


class GoldCase(BaseModel):
    id: str
    category: str
    conversation_date: date
    user_timezone: str
    participants: dict[str, str]
    dialogue: list[DialogueTurn]
    expected_commitments: list[ExpectedCommitment]
    notes: str = ""