"""LLM-экстрактор договорённостей через Instructor + OpenAI-совместимый API.

Ответ — Pydantic-модель `app.domain.commitment.Commitment` (контракт
Agreement-сервиса). LLM-вывод валидируется rule-пасом в `validation.py`.
"""

from __future__ import annotations

from typing import Any, cast

import instructor
import openai
from pydantic import BaseModel

from app.domain.commitment import Commitment
from app.ml.extraction.context import ConversationContext

_FIELDS = ", ".join(
    (
        "type",
        "title",
        "object",
        "owner",
        "owner_user_id",
        "due_date",
        "due_time",
        "amount",
        "currency",
        "source_quote",
        "audio_start",
        "audio_end",
        "confidence",
        "ambiguity",
    )
)

_SYSTEM = f"""Ты — система извлечения договорённостей из телефонных разговоров.

Правила:
1. Извлекай ТОЛЬКО обязательства, явно озвученные или однозначно подразумеваемые в разговоре.
2. НЕ выдумывай даты, суммы, имена или обязательства. Если данные неоднозначны —
   заполни соответствующее поле ambiguity (vague_deadline, missing_due_date, missing_amount,
   unknown_owner, contradictory_quote).
3. Относительные сроки («до пятницы», «через неделю») решай относительно conversation_date
   и user_timezone. Невозможные или противоречивые сроки отмечай ambiguity.contradictory_quote.
4. НЕ проставляй статус или owner_user_id — их вычисляет система.
5. owner: user (пользователь приложения), counterparty (собеседник) или unknown. НЕ гадай ответственного.
6. source_quote — дословная цитата из транскрипта; audio_start/audio_end — таймкоды
   соответствующей фразы из транскрипта. Для каждой договорённости обязательны и quote, и таймкоды.
7. Если договорённостей нет — верни пустой список commitments.
8. amount указывай, только если сумма названа явно и с валютой (currency обязательна при amount).
   due_time заполняй только вместе с due_date.
9. title — краткая формулировка на русском.

Используй ТОЛЬКО следующие поля договорённости: {_FIELDS}.
Ответ — строго по схеме ExtractionResult (commitments: список таких договорённостей)."""


class ExtractionResult(BaseModel):
    """Обёртка ответа LLM: список договорённостей."""

    commitments: list[Commitment]


class InstructorLLMExtractor:
    """Структурированное извлечение (Pydantic-ответ, без ручного JSON)."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        *,
        mode: instructor.Mode = instructor.Mode.JSON,
    ) -> None:
        client = openai.AsyncOpenAI(base_url=base_url, api_key=api_key)
        self._client: Any = instructor.from_openai(client, mode=mode)
        self.model = model

    def _messages(self, context: ConversationContext) -> list[dict[str, str]]:
        transcript = "\n".join(
            f"{i + 1}. [{segment.start:.2f}-{segment.end:.2f}] {segment.speaker}: {segment.text}"
            for i, segment in enumerate(context.transcript)
        )
        participants = ", ".join(f"{k}: {v}" for k, v in context.participants.items()) or "неизвестны"
        user = (
            f"Разговор: {context.conversation_id}\n"
            f"Дата разговора: {context.conversation_date.isoformat()}\n"
            f"Часовой пояс пользователя: {context.user_timezone}\n"
            f"Участники: {participants}\n\n"
            f"Транскрипт:\n{transcript}\n\n"
            "Извлеки все договорённости согласно правилам. "
            "source_quote бери дословно из транскрипта, audio_start/audio_end — по таймкодам фразы."
        )
        return [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user},
        ]

    async def extract(self, context: ConversationContext) -> list[Commitment]:
        result = await self._client.chat.completions.create(
            model=self.model,
            messages=self._messages(context),
            response_model=ExtractionResult,
            temperature=0,
            seed=0,
        )
        response = cast(ExtractionResult, result)
        return response.commitments
