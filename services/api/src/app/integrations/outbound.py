"""Calendar, reminders and messaging ports.

Reminders and calendar events are never created without user confirmation;
messages are only drafted, never sent automatically.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Protocol, cast

from icalendar import Calendar, Event

from app.infrastructure.db.models import Task


class CalendarPort(Protocol):
    async def create_event(
        self,
        *,
        title: str,
        starts_at: datetime,
        ends_at: datetime | None,
        notes: str | None,
    ) -> str: ...


class NullCalendar:
    async def create_event(
        self,
        *,
        title: str,
        starts_at: datetime,
        ends_at: datetime | None,
        notes: str | None,
    ) -> str:
        return f"cal-{uuid.uuid4().hex[:12]}"


def make_ics_event(*, title: str, starts_at: datetime, ends_at: datetime | None, notes: str | None) -> str:
    """Deterministic .ics payload (used when no calendar integration is wired)."""

    calendar = Calendar()
    calendar.add("prodid", "-//Agreement Capture//MVP//RU")
    calendar.add("version", "2.0")
    event = Event()
    event.add("summary", title)
    event.add("dtstart", starts_at)
    if ends_at:
        event.add("dtend", ends_at)
    if notes:
        event.add("description", notes)
    calendar.add_component(event)
    return cast(str, calendar.to_ical().decode("utf-8"))


class RemindersPort(Protocol):
    async def create_reminder(self, *, task: Task, remind_at: datetime) -> str: ...


class NullReminders:
    async def create_reminder(self, *, task: Task, remind_at: datetime) -> str:
        return f"rem-{uuid.uuid4().hex[:12]}"


class MessagingPort(Protocol):
    async def draft_message(self, *, phone: str, text: str) -> str: ...


class NullMessaging:
    async def draft_message(self, *, phone: str, text: str) -> str:
        return f"msg-{uuid.uuid4().hex[:12]}"


def calendar_factory(name: str) -> CalendarPort:
    """Real calendar adapters (Google/Apple) are added later; ``ics`` is the
    in-app artifact and the default."""
    if name in {"ics", "null"}:
        return NullCalendar()
    raise ValueError(f"unknown calendar provider: {name}")


def reminders_factory(name: str) -> RemindersPort:
    if name in {"local", "null"}:
        return NullReminders()
    raise ValueError(f"unknown reminders provider: {name}")


def messaging_factory(name: str) -> MessagingPort:
    if name in {"draft", "null"}:
        return NullMessaging()
    raise ValueError(f"unknown messaging provider: {name}")