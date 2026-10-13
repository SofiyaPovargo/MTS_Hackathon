"""Agreement lifecycle over HTTP: manual entry, edits, confirm -> task, reject."""

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


async def test_manual_agreement_confirm_creates_task(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))

    call = await create_call(client, headers)
    agreement = await create_manual_agreement(client, headers, str(call["id"]))
    assert agreement["status"] == "detected"
    assert agreement["source_quote"] == "manual entry"
    assert agreement["owner"] == "user"

    confirmed = await client.post(
        f"/api/agreements/{agreement['id']}/confirm", headers=headers
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "confirmed"

    tasks = (await client.get("/api/me/tasks", headers=headers)).json()
    assert len(tasks) == 1
    task = tasks[0]
    assert task["agreement_id"] == agreement["id"]
    assert task["assignee_user_id"] == str(seeded_users["anna_id"])
    assert task["status"] == "new"
    assert task["due_date"] == "2026-10-20"


async def test_patch_edits_editable_fields_and_guards_immutable(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))

    call = await create_call(client, headers)
    agreement = await create_manual_agreement(client, headers, str(call["id"]))
    original_version = agreement["version"]

    response = await client.patch(
        f"/api/agreements/{agreement['id']}",
        json={"title": "Новый заголовок", "due_date": "2026-10-25"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == "Новый заголовок"
    assert body["due_date"] == "2026-10-25"
    assert body["version"] == original_version + 1

    # Quote and audio timestamps are immutable for auditability.
    response = await client.patch(
        f"/api/agreements/{agreement['id']}", json={"source_quote": "x"}, headers=headers
    )
    assert response.status_code == 422

    # An empty patch is also rejected.
    response = await client.patch(
        f"/api/agreements/{agreement['id']}", json={}, headers=headers
    )
    assert response.status_code == 422


async def test_rejected_agreement_cannot_create_task(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))

    call = await create_call(client, headers)
    agreement = await create_manual_agreement(client, headers, str(call["id"]))

    rejected = await client.post(f"/api/agreements/{agreement['id']}/reject", headers=headers)
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"

    confirmation = await client.post(
        f"/api/agreements/{agreement['id']}/confirm", headers=headers
    )
    assert confirmation.status_code == 422

    assert (await client.get("/api/me/tasks", headers=headers)).json() == []


async def test_task_patch_and_complete(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))

    call = await create_call(client, headers)
    agreement = await create_manual_agreement(client, headers, str(call["id"]))
    await client.post(f"/api/agreements/{agreement['id']}/confirm", headers=headers)
    task = (await client.get("/api/me/tasks", headers=headers)).json()[0]

    patched = await client.patch(
        f"/api/tasks/{task['id']}",
        json={"title": "Важная задача", "status": "in_progress"},
        headers=headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["status"] == "in_progress"

    completed = await client.post(f"/api/tasks/{task['id']}/complete", headers=headers)
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "done"
    assert completed.json()["completed_at"] is not None

    # done is terminal: patching back is rejected.
    rollback = await client.patch(
        f"/api/tasks/{task['id']}", json={"status": "new"}, headers=headers
    )
    assert rollback.status_code == 422