"""Boards: personal views (``plan.md`` §14) and the manager team board (§15).

Filters (employee, status, priority, type, term), ordering (overdue first, then
the nearest deadline) and the per-member analytics are checked over HTTP, with
server-side role and team rules enforced.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
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


async def _make_task(
    client: httpx.AsyncClient,
    phone: str,
    *,
    due_date: str,
    priority: str | None = None,
    agreement_type: str = "obligation",
    complete: bool = False,
) -> dict[str, Any]:
    """Create a confirmed agreement -> task, optionally patched or completed."""
    auth = await login(client, phone)
    headers = auth_headers(str(auth["access_token"]))
    call = await create_call(client, headers)
    agreement = await create_manual_agreement(
        client, headers, str(call["id"]), due_date=due_date, agreement_type=agreement_type
    )
    confirmed = await client.post(f"/api/agreements/{agreement['id']}/confirm", headers=headers)
    assert confirmed.status_code == 200, confirmed.text

    task = next(
        item
        for item in (await client.get("/api/me/tasks", headers=headers)).json()
        if item["agreement_id"] == agreement["id"]
    )
    if priority is not None:
        patched = await client.patch(
            f"/api/tasks/{task['id']}", json={"priority": priority}, headers=headers
        )
        assert patched.status_code == 200, patched.text
        task = patched.json()
    if complete:
        done = await client.post(f"/api/tasks/{task['id']}/complete", headers=headers)
        assert done.status_code == 200, done.text
        task = done.json()

    return {
        "id": task["id"],
        "call_id": str(call["id"]),
        "agreement_id": agreement["id"],
    }


async def _task_ids(client: httpx.AsyncClient, headers: dict[str, str], query: str) -> set[str]:
    response = await client.get(f"/api/me/tasks?{query}", headers=headers)
    assert response.status_code == 200, response.text
    return {item["id"] for item in response.json()}


async def test_personal_board_views(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    today = date.today()
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))

    today_task = await _make_task(client, USER_PHONES["anna"], due_date=today.isoformat())
    overdue_task = await _make_task(
        client, USER_PHONES["anna"], due_date=(today - timedelta(days=2)).isoformat()
    )
    upcoming_task = await _make_task(
        client,
        USER_PHONES["anna"],
        due_date=(today + timedelta(days=5)).isoformat(),
        priority="high",
    )
    done_task = await _make_task(
        client, USER_PHONES["anna"], due_date=today.isoformat(), complete=True
    )

    assert await _task_ids(client, headers, "view=today") == {today_task["id"]}
    assert await _task_ids(client, headers, "view=overdue") == {overdue_task["id"]}
    assert await _task_ids(client, headers, "view=upcoming") == {upcoming_task["id"]}
    assert await _task_ids(client, headers, "view=done") == {done_task["id"]}
    assert len(await _task_ids(client, headers, "view=all")) == 4

    # Status and priority filters compose with the views.
    assert await _task_ids(client, headers, "status=done") == {done_task["id"]}
    assert await _task_ids(client, headers, "priority=high") == {upcoming_task["id"]}


async def test_manager_board_card_fields(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    created = await _make_task(
        client, USER_PHONES["anna"], due_date=(date.today() + timedelta(days=2)).isoformat()
    )

    manager = await login(client, USER_PHONES["manager"])
    headers = auth_headers(str(manager["access_token"]))
    response = await client.get("/api/manager/team/tasks", headers=headers)
    assert response.status_code == 200, response.text
    card = response.json()[0]
    assert card["assignee_user_id"] == str(seeded_users["anna_id"])
    assert card["assignee_name"] == "Анна"
    assert card["agreement_id"] == created["agreement_id"]
    assert card["agreement_type"] == "obligation"
    assert card["call_id"] == created["call_id"]
    assert card["contact_phone"] == "+79991230001"
    assert card["status"] == "new"


async def test_manager_board_filters_and_ordering(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    today = date.today()
    overdue = await _make_task(
        client,
        USER_PHONES["anna"],
        due_date=(today - timedelta(days=1)).isoformat(),
        priority="high",
    )
    payment = await _make_task(
        client,
        USER_PHONES["anna"],
        due_date=(today + timedelta(days=4)).isoformat(),
        priority="low",
        agreement_type="payment",
    )
    boris_task = await _make_task(
        client, USER_PHONES["boris"], due_date=(today + timedelta(days=1)).isoformat()
    )

    manager = await login(client, USER_PHONES["manager"])
    headers = auth_headers(str(manager["access_token"]))

    async def ids(query: str = "") -> list[str]:
        response = await client.get(f"/api/manager/team/tasks{query}", headers=headers)
        assert response.status_code == 200, response.text
        return [card["id"] for card in response.json()]

    # Default ordering: overdue first, then the nearest deadline.
    ordered = await ids()
    assert ordered[0] == overdue["id"]
    assert set(ordered) == {overdue["id"], payment["id"], boris_task["id"]}

    assert await ids("?priority=high") == [overdue["id"]]
    assert await ids("?task_type=payment") == [payment["id"]]
    assert await ids("?status=overdue") == [overdue["id"]]
    assert await ids(f"?due_after={today + timedelta(days=2)}") == [payment["id"]]

    # Sorting by priority: high before low.
    by_priority = await ids("?sort=priority")
    assert by_priority[0] == overdue["id"]


async def test_manager_stats_per_member(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    await _make_task(
        client, USER_PHONES["anna"], due_date=(date.today() + timedelta(days=1)).isoformat()
    )

    manager = await login(client, USER_PHONES["manager"])
    headers = auth_headers(str(manager["access_token"]))
    response = await client.get("/api/manager/team/stats", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["agreements_total"] == 1
    assert body["tasks_total"] == 1

    by_id = {member["user_id"]: member for member in body["members"]}
    anna_stats = by_id[str(seeded_users["anna_id"])]
    assert anna_stats["tasks_total"] == 1
    assert anna_stats["agreements_total"] == 1
    assert anna_stats["tasks_from_calls_percent"] == 100.0

    boris_stats = by_id[str(seeded_users["boris_id"])]
    assert boris_stats["tasks_total"] == 0
    assert boris_stats["agreements_total"] == 0
