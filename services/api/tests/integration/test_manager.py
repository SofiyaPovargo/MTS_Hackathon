"""Manager board: team tasks/members/stats with server-side role + team checks."""

from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.enums import Role
from app.infrastructure.db.models import Team, User
from tests.integration.conftest import (
    USER_PHONES,
    auth_headers,
    create_call,
    create_manual_agreement,
    login,
)

pytestmark = pytest.mark.integration


async def _task_for_user(client: httpx.AsyncClient, phone: str) -> None:
    auth = await login(client, phone)
    headers = auth_headers(str(auth["access_token"]))
    call = await create_call(client, headers)
    agreement = await create_manual_agreement(client, headers, str(call["id"]))
    response = await client.post(f"/api/agreements/{agreement['id']}/confirm", headers=headers)
    assert response.status_code == 200, response.text


async def test_manager_sees_only_its_team_tasks(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    await _task_for_user(client, USER_PHONES["anna"])
    await _task_for_user(client, USER_PHONES["boris"])

    manager = await login(client, USER_PHONES["manager"])
    headers = auth_headers(str(manager["access_token"]))

    response = await client.get("/api/manager/team/tasks", headers=headers)
    assert response.status_code == 200, response.text
    tasks = response.json()
    assert len(tasks) == 2
    assignees = {task["assignee_user_id"] for task in tasks}
    assert assignees == {str(seeded_users["anna_id"]), str(seeded_users["boris_id"])}

    # Filtering by a member of the team works.
    filtered = await client.get(
        f"/api/manager/team/tasks?user_id={seeded_users['anna_id']}", headers=headers
    )
    assert filtered.status_code == 200
    assert [t["assignee_user_id"] for t in filtered.json()] == [str(seeded_users["anna_id"])]


async def test_manager_cannot_query_foreign_team_member(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, client = app_and_client

    # A second team with its own user, outside the manager's reach.
    async with session_factory() as session:
        other_team = Team(name="Бета")
        session.add(other_team)
        await session.flush()
        foreign_user = User(
            team_id=other_team.id,
            phone="+79000000004",
            full_name="Виктор",
            role=Role.user,
            timezone="Europe/Moscow",
        )
        session.add(foreign_user)
        await session.flush()
        await session.commit()
        foreign_user_id = foreign_user.id

    manager = await login(client, USER_PHONES["manager"])
    headers = auth_headers(str(manager["access_token"]))

    response = await client.get(
        f"/api/manager/team/tasks?user_id={foreign_user_id}", headers=headers
    )
    assert response.status_code == 403


async def test_manager_stats_and_members(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    await _task_for_user(client, USER_PHONES["anna"])

    manager = await login(client, USER_PHONES["manager"])
    headers = auth_headers(str(manager["access_token"]))

    stats = await client.get("/api/manager/team/stats", headers=headers)
    assert stats.status_code == 200, stats.text
    body = stats.json()
    assert body["members_count"] == 3
    assert body["tasks_total"] == 1
    assert body["tasks_by_status"]["new"] == 1
    assert body["tasks_from_calls_percent"] == 100.0

    members = await client.get("/api/manager/team/members", headers=headers)
    assert members.status_code == 200
    phones = {member["phone"] for member in members.json()}
    assert phones == set(USER_PHONES.values())