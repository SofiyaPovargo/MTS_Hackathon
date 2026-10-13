"""Confirmed-agreement side effects: calendar event, .ics, reminders, draft.

These actions are user-triggered only. A task exists solely from a confirmed
agreement, so the tests also pin the "confirmed only" rule at the service level.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.enums import (
    AgreementStatus,
    CallDirection,
    CallStatus,
    Owner,
    TaskPriority,
    TaskStatus,
)
from app.domain.errors import ValidationFailed
from app.infrastructure.db.models import Agreement, Call, Task, User
from app.integrations.outbound import NullCalendar, NullMessaging, NullReminders
from app.services.schedule import ScheduleService
from tests.integration.conftest import (
    USER_PHONES,
    auth_headers,
    create_call,
    create_manual_agreement,
    login,
)

pytestmark = pytest.mark.integration


async def _confirmed_task(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    due_date: str = "2026-10-20",
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    call = await create_call(client, headers)
    agreement = await create_manual_agreement(
        client, headers, str(call["id"]), due_date=due_date
    )
    confirmed = await client.post(
        f"/api/agreements/{agreement['id']}/confirm", headers=headers
    )
    assert confirmed.status_code == 200, confirmed.text
    tasks = (await client.get("/api/me/tasks", headers=headers)).json()
    assert len(tasks) == 1
    return call, agreement, tasks[0]


async def test_calendar_event_for_confirmed_task(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    _, _, task = await _confirmed_task(client, headers)

    response = await client.post(f"/api/tasks/{task['id']}/calendar", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["task_id"] == task["id"]
    assert body["event_id"].startswith("cal-")

    # 09:00 in Europe/Moscow (the default user timezone) is 06:00 UTC.
    start = datetime.fromisoformat(body["starts_at"])
    end = datetime.fromisoformat(body["ends_at"])
    assert start == datetime(2026, 10, 20, 6, 0, tzinfo=UTC)
    assert end - start == timedelta(minutes=30)


async def test_ics_download_is_valid_calendar(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    _, _, task = await _confirmed_task(client, headers)

    response = await client.get(f"/api/tasks/{task['id']}/calendar.ics", headers=headers)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/calendar")
    body = response.text
    assert "BEGIN:VCALENDAR" in body
    assert "END:VCALENDAR" in body
    assert "SUMMARY:" in body
    assert "DTSTART" in body


async def test_canceled_task_cannot_be_scheduled(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    _, _, task = await _confirmed_task(client, headers)

    canceled = await client.patch(
        f"/api/tasks/{task['id']}", json={"status": "canceled"}, headers=headers
    )
    assert canceled.status_code == 200, canceled.text

    assert (
        await client.post(f"/api/tasks/{task['id']}/calendar", headers=headers)
    ).status_code == 422
    assert (
        await client.post(f"/api/tasks/{task['id']}/message-draft", headers=headers)
    ).status_code == 422


async def test_reminder_create_list_cancel(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    _, _, task = await _confirmed_task(client, headers)

    when = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    created = await client.post(
        f"/api/tasks/{task['id']}/reminders",
        json={"remind_at": when, "channel": "push"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    reminder = created.json()
    assert reminder["status"] == "scheduled"
    assert reminder["channel"] == "push"

    listed = (
        await client.get(f"/api/tasks/{task['id']}/reminders", headers=headers)
    ).json()
    assert [r["id"] for r in listed] == [reminder["id"]]

    canceled = await client.post(f"/api/reminders/{reminder['id']}/cancel", headers=headers)
    assert canceled.status_code == 200, canceled.text
    assert canceled.json()["status"] == "canceled"


async def test_reminder_must_be_in_the_future(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    _, _, task = await _confirmed_task(client, headers)

    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    response = await client.post(
        f"/api/tasks/{task['id']}/reminders", json={"remind_at": past}, headers=headers
    )
    assert response.status_code == 422


async def test_message_draft_is_never_sent(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    _, _, task = await _confirmed_task(client, headers)

    response = await client.post(f"/api/tasks/{task['id']}/message-draft", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sent"] is False
    assert body["draft_id"].startswith("msg-")
    assert body["phone"] == "+79991230001"
    assert "Отправить отчёт" in body["text"]


async def test_other_user_cannot_schedule_task(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    _, _, task = await _confirmed_task(client, auth_headers(str(anna["access_token"])))

    boris = await login(client, USER_PHONES["boris"])
    headers = auth_headers(str(boris["access_token"]))
    when = (datetime.now(UTC) + timedelta(days=1)).isoformat()

    assert (
        await client.post(f"/api/tasks/{task['id']}/calendar", headers=headers)
    ).status_code == 404
    assert (
        await client.post(f"/api/tasks/{task['id']}/message-draft", headers=headers)
    ).status_code == 404
    assert (
        await client.post(
            f"/api/tasks/{task['id']}/reminders",
            json={"remind_at": when},
            headers=headers,
        )
    ).status_code == 404


async def test_scheduling_requires_confirmed_agreement(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A task linked to a non-confirmed agreement is rejected at the service level."""
    async with session_factory() as session:
        user = await session.get(User, seeded_users["anna_id"])
        assert user is not None
        call = Call(
            user_id=user.id,
            contact_phone="+79990000000",
            direction=CallDirection.outbound,
            status=CallStatus.in_progress,
        )
        session.add(call)
        await session.flush()

        agreement = Agreement(
            call_id=call.id,
            owner=Owner.user,
            type="obligation",
            title="X",
            source_quote="q",
            audio_start=0,
            audio_end=0,
            confidence=Decimal("0.90"),
            status=AgreementStatus.requires_review,
        )
        session.add(agreement)
        await session.flush()

        task = Task(
            agreement_id=agreement.id,
            assignee_user_id=user.id,
            title="X",
            priority=TaskPriority.medium,
            status=TaskStatus.new,
        )
        session.add(task)
        await session.flush()

        service = ScheduleService(
            session,
            calendar=NullCalendar(),
            reminders=NullReminders(),
            messaging=NullMessaging(),
        )
        with pytest.raises(ValidationFailed):
            await service.calendar_event(user, task)
        with pytest.raises(ValidationFailed):
            await service.draft_message(user, task)
