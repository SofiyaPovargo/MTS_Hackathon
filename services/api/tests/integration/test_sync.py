"""Delta sync: pull deltas, idempotent push with replay, version conflicts."""

from __future__ import annotations

import uuid
from typing import Any

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


async def _setup_task(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Create a call + manual agreement and confirm it; return (agreement, task)."""
    call = await create_call(client, headers)
    agreement = await create_manual_agreement(client, headers, str(call["id"]))
    response = await client.post(f"/api/agreements/{agreement['id']}/confirm", headers=headers)
    assert response.status_code == 200, response.text
    tasks = (await client.get("/api/me/tasks", headers=headers)).json()
    assert len(tasks) == 1
    return agreement, tasks[0]


def _operation(
    entity_type: str,
    entity_id: str,
    operation: str,
    *,
    version: int | None = None,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "operation": operation,
        "idempotency_key": f"key-{uuid.uuid4().hex}",
        "version": version,
        "payload": payload or {},
    }


async def test_pull_returns_deltas_and_token(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    await _setup_task(client, headers)

    response = await client.get("/api/sync", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert {"call", "agreement", "task"} <= {c["entity_type"] for c in body["changes"]}
    token = body["sync_token"]
    assert body["has_more"] is False

    # Incremental pull since the token sees nothing new.
    incremental = await client.get(f"/api/sync?since={token}", headers=headers)
    assert incremental.status_code == 200
    assert incremental.json()["changes"] == []


async def test_push_update_accepted_and_replay_idempotent(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    _, task = await _setup_task(client, headers)

    op = _operation(
        "task",
        str(task["id"]),
        "update",
        version=int(task["version"]),
        payload={"title": "Обновлённый заголовок"},
    )
    first = await client.post("/api/sync", json={"operations": [op]}, headers=headers)
    assert first.status_code == 200, first.text
    result = first.json()["results"][0]
    assert result["status"] == "accepted"
    assert result["version"] == int(task["version"]) + 1

    # Replaying the same operation with the same key is a no-op, not an error.
    replay = await client.post("/api/sync", json={"operations": [op]}, headers=headers)
    assert replay.status_code == 200
    replayed = replay.json()["results"][0]
    assert replayed["status"] == "accepted"
    assert replayed["version"] == result["version"]

    tasks = (await client.get("/api/me/tasks", headers=headers)).json()
    assert tasks[0]["title"] == "Обновлённый заголовок"


async def test_push_stale_version_is_conflict(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    _, task = await _setup_task(client, headers)

    # The server version is 1; pushing with an older/equal-but-stale version
    # (after the first accepted push) is a conflict that returns the server's.
    op = _operation(
        "task", str(task["id"]), "update", version=1, payload={"title": "устарело"}
    )
    response = await client.post("/api/sync", json={"operations": [op]}, headers=headers)
    assert response.status_code == 200, response.text
    result = response.json()["results"][0]
    assert result["status"] == "accepted"
    assert result["version"] == 2

    stale = _operation(
        "task", str(task["id"]), "update", version=1, payload={"title": "ещё устарело"}
    )
    response = await client.post("/api/sync", json={"operations": [stale]}, headers=headers)
    assert response.status_code == 200
    conflicting = response.json()["results"][0]
    assert conflicting["status"] == "conflict"
    assert conflicting["server_version"] == 2


async def test_push_delete_cancels_task(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    _, task = await _setup_task(client, headers)

    op = _operation("task", str(task["id"]), "delete", version=int(task["version"]))
    response = await client.post("/api/sync", json={"operations": [op]}, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["results"][0]["status"] == "accepted"

    tasks = (await client.get("/api/me/tasks", headers=headers)).json()
    assert tasks[0]["status"] == "canceled"


async def test_push_rejects_foreign_and_unsupported(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    boris = await login(client, USER_PHONES["boris"])
    anna_headers = auth_headers(str(anna["access_token"]))
    boris_headers = auth_headers(str(boris["access_token"]))

    _, task = await _setup_task(client, anna_headers)

    # A foreign user's push is rejected, never applied.
    foreign = _operation(
        "task", str(task["id"]), "update", version=1, payload={"title": "чужое"}
    )
    response = await client.post("/api/sync", json={"operations": [foreign]}, headers=boris_headers)
    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "rejected"

    # Only task and agreement are pushable in this MVP.
    unsupported = _operation(
        "reminder", str(uuid.uuid4()), "update", version=1, payload={}
    )
    response = await client.post("/api/sync", json={"operations": [unsupported]}, headers=anna_headers)
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["status"] == "rejected"
    assert "unsupported" in result["message"]


async def test_push_agreement_update(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    agreement, _ = await _setup_task(client, headers)

    # Confirming bumped the version past the creation snapshot; use the live row.
    live = (await client.get("/api/me/agreements", headers=headers)).json()[0]

    op = _operation(
        "agreement",
        str(agreement["id"]),
        "update",
        version=int(live["version"]),
        payload={"due_date": "2026-11-01"},
    )
    response = await client.post("/api/sync", json={"operations": [op]}, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["results"][0]["status"] == "accepted"

    agreements = (await client.get("/api/me/agreements", headers=headers)).json()
    assert agreements[0]["due_date"] == "2026-11-01"