"""Relative date resolution is deterministic and never invents dates."""

from __future__ import annotations

from datetime import date

from app.domain.dates import DateResolution, resolve_relative_date

TODAY = date(2026, 10, 13)  # Tuesday


def resolve(text: str) -> DateResolution:
    result = resolve_relative_date(text, today=TODAY)
    assert result is not None, f"no date phrase resolved in {text!r}"
    return result


def test_explicit_weekday() -> None:
    result = resolve("Мы пришлем счет до пятницы")
    assert result is not None
    assert result.due_date == date(2026, 10, 16)
    assert result.ambiguous is False


def test_today_tomorrow_after_tomorrow() -> None:
    assert resolve("сегодня").due_date == TODAY
    assert resolve("завтра").due_date == date(2026, 10, 14)
    assert resolve("послезавтра").due_date == date(2026, 10, 15)


def test_through_n_days() -> None:
    result = resolve("через 3 дня")
    assert result.due_date == date(2026, 10, 16)
    assert result.ambiguous is False


def test_next_week_is_ambiguous() -> None:
    result = resolve("на следующей неделе")
    assert result is not None
    assert result.due_date == date(2026, 10, 19)  # Monday of the next ISO week
    assert result.ambiguous is True


def test_month_end_is_ambiguous() -> None:
    result = resolve("до конца месяца")
    assert result is not None
    assert result.due_date == date(2026, 10, 31)
    assert result.ambiguous is True


def test_iso_date() -> None:
    result = resolve("пришлите к 2026-10-16")
    assert result.due_date == date(2026, 10, 16)
    assert result.ambiguous is False


def test_russian_numeric_date() -> None:
    result = resolve("оплата 16.10.2026")
    assert result.due_date == date(2026, 10, 16)


def test_day_month() -> None:
    result = resolve("встреча 25 октября")
    assert result.due_date == date(2026, 10, 25)


def test_no_date_returns_none() -> None:
    assert resolve_relative_date("обсудили план работ", today=TODAY) is None


def test_contradictory_phrases_flagged_or_resolved_first() -> None:
    # deterministic: the first resolvable phrase wins
    result = resolve("сначала 20 октября, потом 21 октября")
    assert result.due_date == date(2026, 10, 20)