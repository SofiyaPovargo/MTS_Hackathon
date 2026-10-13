"""Deterministic resolution of relative dates from Russian transcripts.

A date extracted by the LLM is never trusted as-is: it is resolved in code
against the conversation date in the user's timezone. When a phrase is vague
("на следующей неделе", "в конце месяца") the result is returned with
``ambiguous=True`` so the agreement becomes ``needs_clarification`` instead of
inventing a precise deadline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from app.domain.rules import next_week_start

WEEKDAYS: dict[str, int] = {
    "понедельник": 0,
    "вторник": 1,
    "среда": 2,
    "среду": 2,
    "среды": 2,
    "четверг": 3,
    "пятница": 4,
    "пятницу": 4,
    "пятницы": 4,
    "суббота": 5,
    "субботу": 5,
    "воскресенье": 6,
    "воскресенья": 6,
}

MONTHS: dict[str, int] = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}

WEEKDAY_RE = re.compile(r"\b(" + "|".join(WEEKDAYS) + r")\b")
ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
RU_DATE_RE = re.compile(r"\b(\d{1,2})[.\s](\d{1,2})(?:[.\s](\d{2,4}))?\b")
DAY_MONTH_RE = re.compile(r"\b(\d{1,2})\s+(" + "|".join(MONTHS) + r")\b")
IN_N_DAYS_RE = re.compile(r"\bчерез\s+(\d{1,2})\s+(?:день|дня|дней)\b")
IN_WEEKS_RE = re.compile(r"\bчерез\s+(\d{1,2})\s+(?:неделю|недели|недель)\b")


@dataclass(frozen=True, slots=True)
class DateResolution:
    """Result of resolving a date phrase."""

    due_date: date | None
    ambiguous: bool
    rule: str
    phrase: str

    @property
    def is_resolved(self) -> bool:
        return self.due_date is not None


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().replace("ё", "е")).strip()


def next_weekday(today: date, weekday: int) -> date:
    """Next occurrence of ``weekday``; today counts as next week when it matches."""
    delta = (weekday - today.weekday()) % 7
    if delta == 0:
        delta = 7
    return today + timedelta(days=delta)


def last_day_of_month(today: date) -> date:
    if today.month == 12:
        return date(today.year, 12, 31)
    return date(today.year, today.month + 1, 1) - timedelta(days=1)


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def resolve_relative_date(text: str, *, today: date) -> DateResolution | None:
    """Resolve the first date phrase found in ``text``, or ``None`` if there is none."""
    phrase = normalize(text)

    match = ISO_DATE_RE.search(phrase)
    if match:
        value = _safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if value:
            return DateResolution(value, False, "iso_date", match.group(0))

    match = DAY_MONTH_RE.search(phrase)
    if match:
        value = _safe_date(today.year, MONTHS[match.group(2)], int(match.group(1)))
        if value:
            # A day/month without a year that already passed is ambiguous.
            return DateResolution(value, value < today, "day_month", match.group(0))

    match = RU_DATE_RE.search(phrase)
    if match:
        day, month, year = match.groups()
        resolved_year = today.year
        if year:
            resolved_year = int(year)
            if resolved_year < 100:
                resolved_year += 2000
        value = _safe_date(resolved_year, int(month), int(day))
        if value:
            return DateResolution(value, False, "numeric_date", match.group(0))

    if "послезавтра" in phrase:
        return DateResolution(today + timedelta(days=2), False, "day_after_tomorrow", "послезавтра")
    if "завтра" in phrase:
        return DateResolution(today + timedelta(days=1), False, "tomorrow", "завтра")
    if "сегодня" in phrase:
        return DateResolution(today, False, "today", "сегодня")

    if "конц" in phrase and ("месяц" in phrase):
        return DateResolution(
            last_day_of_month(today), True, "month_end", "конец месяца"
        )

    if "следующ" in phrase and ("недел" in phrase):
        return DateResolution(next_week_start(today), True, "next_week", "следующая неделя")

    match = IN_N_DAYS_RE.search(phrase)
    if match:
        days = int(match.group(1))
        return DateResolution(today + timedelta(days=days), False, "in_n_days", match.group(0))

    match = IN_WEEKS_RE.search(phrase)
    if match:
        weeks = int(match.group(1))
        return DateResolution(today + timedelta(weeks=weeks), False, "in_n_weeks", match.group(0))

    match = WEEKDAY_RE.search(phrase)
    if match:
        return DateResolution(
            next_weekday(today, WEEKDAYS[match.group(1)]), False, "weekday", match.group(0)
        )

    if "через месяц" in phrase:
        return DateResolution(today + timedelta(days=30), True, "in_a_month", "через месяц")

    return None
