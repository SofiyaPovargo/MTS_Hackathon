"""Reminder queueing and delivery.

Creating a push reminder queues ``send_reminder`` (worker-notifications) for
``remind_at``; the worker delivers it through the ``PushPort`` and marks the
reminder ``sent``. Delivery is idempotent, and a provider failure marks the
reminder ``failed`` instead of losing it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.enums import ReminderStatus
from app.infrastructure.db.models import Reminder, User
from app.services.notifications import ReminderDeliveryService
from tests.integration.conftest import (
    USER_PHONES,
    auth_headers,
    create_call,
    create_manual_agreement,
    login,
)

pytestmark = pytest.mark.integration


class FakeQueue:
    """Captures reminder jobs the API would publish to Celery."""

    def __init__(self) -> None:
        self.reminders: list[tuple[str, datetime]] = []

    def enqueue_reminder(self, reminder_id: str, *, eta: datetime) -> None:
        self.reminders.append((reminder_id, eta))

    def enqueue_asr(self, call_id: str) -> None:
        return None

    def enqueue_extraction(self, call_id: str) -> None:
        return None

    def enqueue_live_asr(self, call_id: str) -> None:
        return None

    def enqueue_data_deletion(self, user_id: str) -> None:
        return None

    def enqueue_recording_download(self, call_id: str) -> None:
        return None


class FakePush:
    """Records deliveries; returns a deterministic message id."""

    def __init__(self) -> None:
        self.sent: list[tuple[uuid.UUID, str, str, dict[str, str]]] = []

    async def send(
        self, *, user: User, title: str, body: str, data: dict[str, str]
    ) -> str | None:
        self.sent.append((user.id, title, body, data))
        return "push-1"


class FailingPush:
    async def send(
        self, *, user: User, title: str, body: str, data: dict[str, str]
    ) -> str | None:
        raise RuntimeError("provider down")


async def _confirmed_task(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    call = await create_call(client, headers)
    agreement = await create_manual_agreement(client, headers, str(call["id"]))
    confirmed = await client.post(f"/api/agreements/{agreement['id']}/confirm", headers=headers)
    assert confirmed.status_code == 200, confirmed.text
    tasks = (await client.get("/api/me/tasks", headers=headers)).json()
    return str(tasks[0]["id"])


async def _create_reminder(
    client: httpx.AsyncClient, headers: dict[str, str], task_id: str, *, channel: str = "push"
) -> dict[str, Any]:
    when = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    response = await client.post(
        f"/api/tasks/{task_id}/reminders",
        json={"remind_at": when, "channel": channel},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return cast("dict[str, Any]", response.json())


async def test_push_reminder_is_enqueued_with_eta(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    app, client = app_and_client
    queue = FakeQueue()
    app.state.analysis_queue = queue

    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    task_id = await _confirmed_task(client, headers)

    reminder = await _create_reminder(client, headers, task_id, channel="push")
    assert len(queue.reminders) == 1
    reminder_id, eta = queue.reminders[0]
    assert reminder_id == reminder["id"]
    assert eta == datetime.fromisoformat(str(reminder["remind_at"]))


async def test_local_reminder_is_not_pushed(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    app, client = app_and_client
    queue = FakeQueue()
    app.state.analysis_queue = queue

    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    task_id = await _confirmed_task(client, headers)

    await _create_reminder(client, headers, task_id, channel="local")
    # A device-local reminder is created on the phone, not pushed by the server.
    assert queue.reminders == []


async def test_delivery_marks_sent_and_is_idempotent(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    task_id = await _confirmed_task(client, headers)
    reminder = await _create_reminder(client, headers, task_id)

    push = FakePush()
    async with session_factory() as session:
        row = await session.get(Reminder, uuid.UUID(str(reminder["id"])))
        assert row is not None
        service = ReminderDeliveryService(session, push=push)

        delivered = await service.deliver(row.id)
        await session.commit()
        assert delivered.status is ReminderStatus.sent
        assert delivered.sent_at is not None
        assert [entry[0] for entry in push.sent] == [seeded_users["anna_id"]]
        assert push.sent[0][2] == "Отправить отчёт"

        # A redelivered job must not notify twice.
        again = await service.deliver(row.id)
        assert again.status is ReminderStatus.sent
    assert len(push.sent) == 1


async def test_provider_failure_marks_failed(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    task_id = await _confirmed_task(client, headers)
    reminder = await _create_reminder(client, headers, task_id)

    async with session_factory() as session:
        row = await session.get(Reminder, uuid.UUID(str(reminder["id"])))
        assert row is not None
        service = ReminderDeliveryService(session, push=FailingPush())
        with pytest.raises(RuntimeError):
            await service.deliver(row.id)
        await session.commit()
        assert row.status is ReminderStatus.failed
        assert row.sent_at is None


async def test_canceled_reminder_is_not_delivered(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    task_id = await _confirmed_task(client, headers)
    reminder = await _create_reminder(client, headers, task_id)

    canceled = await client.post(f"/api/reminders/{reminder['id']}/cancel", headers=headers)
    assert canceled.status_code == 200, canceled.text

    push = FakePush()
    async with session_factory() as session:
        row = await session.get(Reminder, uuid.UUID(str(reminder["id"])))
        assert row is not None
        result = await ReminderDeliveryService(session, push=push).deliver(row.id)
        assert result.status is ReminderStatus.canceled
    assert push.sent == []


async def test_worker_task_delivers_through_the_null_adapter(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The Celery task body delivers a due reminder end to end (Null push)."""
    from app.worker import _send_reminder

    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    task_id = await _confirmed_task(client, headers)
    reminder = await _create_reminder(client, headers, task_id)

    status = await _send_reminder(str(reminder["id"]))
    assert status == "sent"

    async with session_factory() as session:
        row = await session.get(Reminder, uuid.UUID(str(reminder["id"])))
        assert row is not None
        assert row.status is ReminderStatus.sent
        assert row.sent_at is not None
