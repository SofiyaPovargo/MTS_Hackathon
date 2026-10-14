"""LLM-суммаризатор звонка (Instructor + OpenAI-совместимый API, self-host Ollama)."""

from __future__ import annotations

from typing import Any, cast

import instructor
import openai
from pydantic import BaseModel

from app.ml.summary.ports import SummaryInput

# Версия промпта для аудита.
SUMMARY_PROMPT_VERSION = "v1"

_SYSTEM = """Ты — система, которая составляет краткое резюме телефонного разговора.

Правила:
1. Резюме строится ТОЛЬКО по транскрипту и переданным договорённостям.
2. НЕ выдумывай факты, даты, суммы, имена и обязательства, которых нет в данных.
3. Тон — нейтральный, кратко (2–4 предложения) на русском языке.
4. Если договорённостей нет — напиши, что договорённости не выделены.
5. Статусы не выдумывай: называй договорённость подтверждённой только если у неё
   status=confirmed; иначе — как «обнаружена/требует проверки/требует уточнения».

Ответ — строго по схеме CallSummary (поле text)."""


class CallSummary(BaseModel):
    """Ответ суммаризатора."""

    text: str


class InstructorLLMSummarizer:
    """Структурированное резюме (Pydantic-ответ, без ручного JSON)."""

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

    def _messages(self, data: SummaryInput) -> list[dict[str, str]]:
        transcript = "\n".join(
            f"[{segment.start:.2f}-{segment.end:.2f}] {segment.speaker}: {segment.text}"
            for segment in data.transcript
        )
        agreements = (
            "\n".join(
                f"- {fact.title} (type={fact.type}, owner={fact.owner}, "
                f"due={fact.due or 'не указан'}, status={fact.status})"
                for fact in data.agreements
            )
            or "нет"
        )
        user = (
            f"Звонок с {data.client_label}.\n\n"
            f"Транскрипт:\n{transcript or 'пусто'}\n\n"
            f"Договорённости:\n{agreements}\n\n"
            "Составь краткое резюме разговора по правилам."
        )
        return [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user},
        ]

    async def summarize(self, data: SummaryInput) -> str:
        result = await self._client.chat.completions.create(
            model=self.model,
            messages=self._messages(data),
            response_model=CallSummary,
            temperature=0,
            seed=0,
        )
        return cast(CallSummary, result).text.strip()
