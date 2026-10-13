"""The validated form of an extracted commitment.

This is the contract between the ML layer and the Agreement Service: the raw LLM
output is stored separately, and only a payload that satisfies this model may
become an agreement.
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import AgreementStatus, Owner
from app.domain.rules import AmbiguityFlags, resolve_agreement_status


class Commitment(BaseModel):
    """One agreement extracted from a transcript, before user confirmation."""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(
        min_length=1,
        max_length=64,
        description=(
            "Free-form agreement type. Base vocabulary: deadline, meeting, payment, "
            "promise, follow_up, open_question; other values such as send_document "
            "are allowed."
        ),
    )
    title: str = Field(min_length=1, max_length=500)
    object: str | None = Field(default=None, max_length=500)
    owner: Owner = Owner.unknown
    owner_user_id: str | None = None
    due_date: date | None = None
    due_time: time | None = None
    amount: Decimal | None = Field(default=None, gt=0)
    currency: str | None = Field(default=None, max_length=8)
    source_quote: str = Field(min_length=1, max_length=2000)
    audio_start: float = Field(ge=0)
    audio_end: float = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    ambiguity: AmbiguityFlags = Field(default_factory=AmbiguityFlags)
    status: AgreementStatus | None = None

    @model_validator(mode="after")
    def _check(self) -> Commitment:
        if self.audio_end < self.audio_start:
            raise ValueError("audio_end must be greater than or equal to audio_start")
        if self.due_time is not None and self.due_date is None:
            raise ValueError("due_time requires due_date")
        if self.amount is not None and self.currency is None:
            raise ValueError("amount requires currency")
        return self

    def status_for(self, threshold: float) -> AgreementStatus:
        return resolve_agreement_status(
            self.confidence, threshold=threshold, ambiguity=self.ambiguity
        )
