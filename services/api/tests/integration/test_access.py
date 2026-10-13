"""Server-side access rights: a user never touches other users' data; the
manager endpoints reject non-managers. Enforcement is on the server, not in
the UI."""

from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI

from tests.integration.conftest import (
    USER_PHONES,
    auth_headers,
    create_call,
    create_manual_agreement,
    login,
)

pytestmark = pytest.mark.integration


async def test_user_cannot_read_another_users_call(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    boris = await login(client, USER_PHONES["boris"])
    anna_headers = auth_headers(str(anna["access_token"]))
    boris_headers = auth_headers(str(boris["access_token"]))

    call = await create_call(client, anna_headers)

    response = await client.get(f"/api/calls/{call['id']}", headers=boris_headers)
    assert response.status_code == 403


async def test_user_cannot_edit_another_users_agreement(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    boris = await login(client, USER_PHONES["boris"])
    anna_headers = auth_headers(str(anna["access_token"]))
    boris_headers = auth_headers(str(boris["access_token"]))

    call = await create_call(client, anna_headers)
    agreement = await create_manual_agreement(client, anna_headers, str(call["id"]))

    response = await client.patch(
        f"/api/agreements/{agreement['id']}", json={"title": "взлом"}, headers=boris_headers
    )
    assert response.status_code == 403


async def test_user_cannot_confirm_another_users_agreement(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    boris = await login(client, USER_PHONES["boris"])
    anna_headers = auth_headers(str(anna["access_token"]))
    boris_headers = auth_headers(str(boris["access_token"]))

    call = await create_call(client, anna_headers)
    agreement = await create_manual_agreement(client, anna_headers, str(call["id"]))

    response = await client.post(
        f"/api/agreements/{agreement['id']}/confirm", headers=boris_headers
    )
    assert response.status_code == 403


async def test_user_cannot_touch_another_users_task(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    boris = await login(client, USER_PHONES["boris"])
    anna_headers = auth_headers(str(anna["access_token"]))
    boris_headers = auth_headers(str(boris["access_token"]))

    call = await create_call(client, anna_headers)
    agreement = await create_manual_agreement(client, anna_headers, str(call["id"]))
    await client.post(f"/api/agreements/{agreement['id']}/confirm", headers=anna_headers)
    tasks = (await client.get("/api/me/tasks", headers=anna_headers)).json()
    assert len(tasks) == 1

    # Tasks are scoped like the agreement: a foreign user gets 404, never the row.
    response = await client.patch(
        f"/api/tasks/{tasks[0]['id']}", json={"title": "взлом"}, headers=boris_headers
    )
    assert response.status_code == 404


async def test_user_sync_never_exposes_foreign_data(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    boris = await login(client, USER_PHONES["boris"])
    anna_headers = auth_headers(str(anna["access_token"]))
    boris_headers = auth_headers(str(boris["access_token"]))

    # Only boris has data.
    await create_call(client, boris_headers, external_id="ext-boris")

    response = await client.get("/api/sync", headers=anna_headers)
    assert response.status_code == 200
    assert response.json()["changes"] == []


async def test_non_manager_blocked_from_manager_endpoints(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))

    for path in ("/api/manager/team/tasks", "/api/manager/team/stats", "/api/manager/team/members"):
        response = await client.get(path, headers=headers)
        assert response.status_code == 403, path