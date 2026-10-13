"""Editing a «закреплённая» (confirmed) agreement: no freeze, the task follows.

plan.md §12–14: confirmation must not freeze the card. The user can edit or
reject even a confirmed agreement; the change is carried onto the linked task
(title, due date, assignee) and onto reminders, bumps ``version`` and is written
to ``audit_log``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.db import repositories
from app.infrastructure.db.models import AuditLog
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
    session_factory: async_sessionmaker[AsyncSession],
    *,
    title: str = "Отправить отчёт",
    due_date: str = "2026-10-20",
    owner_user_id: uuid.UUID | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """A confirmed agreement and the task created from it."""
    call = await create_call(client, headers)
    response = await client.post(
        f"/api/calls/{call['id']}/agreements",
        json={
            "type": "obligation",
            "title": title,
            "owner": "user",
            "owner_user_id": str(owner_user_id) if owner_user_id else None,
            "due_date": due_date,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    agreement = response.json()
    confirmed = await client.post(f"/api/agreements/{agreement['id']}/confirm", headers=headers)
    assert confirmed.status_code == 200, confirmed.text
    async with session_factory() as session:
        task = await repositories.get_task_for_agreement(session, uuid.UUID(agreement["id"]))
        assert task is not None
        return call, confirmed.json(), {"id": str(task.id), "version": task.version}


async def _audit_actions(session: AsyncSession, entity_id: uuid.UUID) -> list[str]:
    result = await session.execute(
        select(AuditLog.action).where(AuditLog.entity_id == entity_id)
    )
    return list(result.scalars().all())


async def test_editing_a_confirmed_agreement_updates_the_task(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    _, agreement, task = await _confirmed_task(client, headers, session_factory)

    edited = await client.patch(
        f"/api/agreements/{agreement['id']}",
        json={"title": "Отправить финальный отчёт", "due_date": "2026-10-27"},
        headers=headers,
    )
    assert edited.status_code == 200, edited.text
    body = edited.json()
    # Editing does not unfreeze the status: the agreement stays confirmed.
    assert body["status"] == "confirmed"
    assert body["title"] == "Отправить финальный отчёт"
    assert body["version"] == agreement["version"] + 1

    # The board (и уведомления) показывают актуальное значение задачи.
    board = (await client.get("/api/me/tasks", headers=headers)).json()
    assert [t["title"] for t in board] == ["Отправить финальный отчёт"]
    assert board[0]["due_date"] == "2026-10-27"
    assert board[0]["version"] == task["version"] + 1

    async with session_factory() as session:
        actions = await _audit_actions(session, uuid.UUID(str(task["id"])))
        assert "task.updated_from_agreement" in actions
        agreement_actions = await _audit_actions(session, uuid.UUID(str(agreement["id"])))
        assert "agreement.edited" in agreement_actions


async def test_editing_a_confirmed_agreement_reassigns_the_task(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    _, agreement, task = await _confirmed_task(
        client, headers, session_factory, owner_user_id=seeded_users["boris_id"]
    )

    async with session_factory() as session:
        row = await repositories.get_task(session, uuid.UUID(str(task["id"])))
        assert row is not None and row.assignee_user_id == seeded_users["boris_id"]

    edited = await client.patch(
        f"/api/agreements/{agreement['id']}",
        json={"owner_user_id": str(seeded_users["anna_id"])},
        headers=headers,
    )
    assert edited.status_code == 200, edited.text

    async with session_factory() as session:
        row = await repositories.get_task(session, uuid.UUID(str(task["id"])))
        assert row is not None and row.assignee_user_id == seeded_users["anna_id"]
    assert [t["id"] for t in (await client.get("/api/me/tasks", headers=headers)).json()] == [
        task["id"]
    ]


async def test_rejecting_a_confirmed_agreement_cancels_its_task(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    _, agreement, task = await _confirmed_task(client, headers, session_factory)

    rejected = await client.post(
        f"/api/agreements/{agreement['id']}/reject", headers=headers
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"

    board = (await client.get("/api/me/tasks", headers=headers)).json()
    assert [t["status"] for t in board] == ["canceled"]
    assert [t["version"] for t in board] == [task["version"] + 1]

    async with session_factory() as session:
        actions = await _audit_actions(session, uuid.UUID(str(agreement["id"])))
        assert "agreement.rejected" in actions


async def test_a_rejected_agreement_is_still_editable(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    """Отклонение — решение пользователя, а не блокировка карточки."""
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    call = await create_call(client, headers)
    agreement = await create_manual_agreement(client, headers, str(call["id"]))

    await client.post(f"/api/agreements/{agreement['id']}/reject", headers=headers)
    edited = await client.patch(
        f"/api/agreements/{agreement['id']}",
        json={"title": "Передумали: это не договорённость"},
        headers=headers,
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["title"] == "Передумали: это не договорённость"
    assert edited.json()["status"] == "rejected"


async def test_editing_an_unconfirmed_agreement_creates_no_task(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    call = await create_call(client, headers)
    agreement = await create_manual_agreement(client, headers, str(call["id"]))

    edited = await client.patch(
        f"/api/agreements/{agreement['id']}", json={"title": "Черновик"}, headers=headers
    )
    assert edited.status_code == 200, edited.text

    async with session_factory() as session:
        assert (
            await repositories.get_task_for_agreement(session, uuid.UUID(agreement["id"]))
            is None
        )
    assert (await client.get("/api/me/tasks", headers=headers)).json() == []


async def test_moving_the_due_date_shifts_pending_reminders(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    _, agreement, task = await _confirmed_task(client, headers, session_factory)

    remind_at = datetime.now(UTC) + timedelta(days=1)
    created = await client.post(
        f"/api/tasks/{task['id']}/reminders",
        json={"remind_at": remind_at.isoformat(), "channel": "push"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    reminder_id = created.json()["id"]

    # Срок сдвигается на неделю вперёд — напоминание едет вместе с ним.
    edited = await client.patch(
        f"/api/agreements/{agreement['id']}", json={"due_date": "2026-10-27"}, headers=headers
    )
    assert edited.status_code == 200, edited.text

    reminder = (
        await client.get(f"/api/tasks/{task['id']}/reminders", headers=headers)
    ).json()[0]
    assert reminder["id"] == reminder_id
    assert reminder["status"] == "scheduled"
    shifted = datetime.fromisoformat(reminder["remind_at"].replace("Z", "+00:00"))
    assert timedelta(days=6, hours=23, minutes=59) < (shifted - remind_at) < timedelta(
        days=7, minutes=1
    )


async def test_moving_the_due_date_into_the_past_cancels_the_reminder(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    _, agreement, task = await _confirmed_task(client, headers, session_factory)

    remind_at = datetime.now(UTC) + timedelta(days=1)
    created = await client.post(
        f"/api/tasks/{task['id']}/reminders",
        json={"remind_at": remind_at.isoformat(), "channel": "push"},
        headers=headers,
    )
    assert created.status_code == 201, created.text

    # Срок уезжает на две недели назад: напоминание оказалось бы в прошлом.
    edited = await client.patch(
        f"/api/agreements/{agreement['id']}", json={"due_date": "2026-10-06"}, headers=headers
    )
    assert edited.status_code == 200, edited.text

    reminder = (
        await client.get(f"/api/tasks/{task['id']}/reminders", headers=headers)
    ).json()[0]
    assert reminder["status"] == "canceled"
