"""LLM-резюме звонка (опционально вместо детерминированного `services/summary.py`).

Пакет держим «лёгким»: ``llm.py`` (Instructor/OpenAI из ml-extra) не импортируется
на уровне пакета, чтобы `services/summary.py` можно было импортировать в лёгком
API-образе. Тяжёлый адаптер берётся напрямую: `app.ml.summary.llm`.
"""

from app.ml.summary.ports import AgreementFact, SummaryInput, SummaryPort

__all__ = ["AgreementFact", "SummaryInput", "SummaryPort"]
