"""Calendar event deletion and the task -> source-call link.

``DELETE /tasks/{id}/calendar`` removes an event the user previously created; the
event id is stored on the task (plan §12–14). The personal board and sync expose
the source ``call_id`` so the app can open the call a task came from.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.db.models import AuditLog, Task
from app.integrations.outbound import NullCalendar
from tests.integration.conftest import (
    USER_PHONES,
    auth_headers,
    create_call,
    create_manual_agreement,
    login,
)

pytestmark = pytest.mark.integration


class SpyCalendar(NullCalendar):
    """Records deletions so the test can assert the port was actually used."""

    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def delete_event(self, *, event_id: str) -> None:
        self.deleted.append(event_id)


async def _confirmed_task(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    call = await create_call(client, headers)
    agreement = await create_manual_agreement(client, headers, str(call["id"]))
    confirmed = await client.post(f"/api/agreements/{agreement['id']}/confirm", headers=headers)
    assert confirmed.status_code == 200, confirmed.text
    tasks = (await client.get("/api/me/tasks", headers=headers)).json()
    assert len(tasks) == 1
    return call, tasks[0]


async def test_task_out_exposes_source_call_id(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    call, task = await _confirmed_task(client, headers)

    # The personal board links each task back to the call it came from.
    assert task["call_id"] == call["id"]

    # Sync carries the same link for the local cache.
    sync = (await client.get("/api/sync", headers=headers)).json()
    task_items = [c for c in sync["changes"] if c["entity_type"] == "task"]
    assert task_items and task_items[0]["data"]["call_id"] == call["id"]


async def test_create_event_stores_the_event_id(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    _, task = await _confirmed_task(client, headers)

    created = await client.post(f"/api/tasks/{task['id']}/calendar", headers=headers)
    assert created.status_code == 200, created.text
    event_id = created.json()["event_id"]

    listed = (await client.get("/api/me/tasks", headers=headers)).json()
    assert listed[0]["calendar_event_id"] == event_id


async def test_delete_calendar_event_removes_it_and_audits(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    app, client = app_and_client
    spy = SpyCalendar()
    app.state.calendar = spy

    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    _, task = await _confirmed_task(client, headers)
    event_id = (
        await client.post(f"/api/tasks/{task['id']}/calendar", headers=headers)
    ).json()["event_id"]

    deleted = await client.delete(f"/api/tasks/{task['id']}/calendar", headers=headers)
    assert deleted.status_code == 204, deleted.text
    assert spy.deleted == [event_id]

    listed = (await client.get("/api/me/tasks", headers=headers)).json()
    assert listed[0]["calendar_event_id"] is None

    async with session_factory() as session:
        rows = await session.execute(
            select(AuditLog).where(
                AuditLog.entity_id == uuid.UUID(task["id"]),
                AuditLog.action == "task.calendar_deleted",
            )
        )
        audit = rows.scalars().all()
        assert len(audit) == 1
        assert audit[0].payload == {"event_id": event_id}

    # Deleting again is a clean 404 — there is no event left to remove.
    again = await client.delete(f"/api/tasks/{task['id']}/calendar", headers=headers)
    assert again.status_code == 404


async def test_other_user_cannot_delete_calendar_event(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    _, task = await _confirmed_task(client, auth_headers(str(anna["access_token"])))
    await client.post(
        f"/api/tasks/{task['id']}/calendar", headers=auth_headers(str(anna["access_token"]))
    )

    boris = await login(client, USER_PHONES["boris"])
    response = await client.delete(
        f"/api/tasks/{task['id']}/calendar", headers=auth_headers(str(boris["access_token"]))
    )
    assert response.status_code == 404


async def test_event_id_survives_a_relist(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    _, task = await _confirmed_task(client, headers)
    event_id = (
        await client.post(f"/api/tasks/{task['id']}/calendar", headers=headers)
    ).json()["event_id"]

    async with session_factory() as session:
        stored = await session.get(Task, uuid.UUID(task["id"]))
        assert stored is not None
        assert stored.calendar_event_id == event_id
