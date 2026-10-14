"""Итог звонка (§9): резюме из договорённостей, счётчики и доступ владельца."""

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


async def test_call_summary_reflects_agreements(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    call = await create_call(client, headers)

    first = await create_manual_agreement(
        client, headers, str(call["id"]), title="Отправить КП", due_date="2026-10-16"
    )
    await create_manual_agreement(
        client, headers, str(call["id"]), title="Согласовать смету", owner="counterparty"
    )
    rejected = await create_manual_agreement(
        client, headers, str(call["id"]), title="Черновик", due_date="2026-10-18"
    )
    rejected_response = await client.post(
        f"/api/agreements/{rejected['id']}/reject", headers=headers
    )
    assert rejected_response.status_code == 200, rejected_response.text
    confirmed = await client.post(f"/api/agreements/{first['id']}/confirm", headers=headers)
    assert confirmed.status_code == 200, confirmed.text

    response = await client.get(f"/api/calls/{call['id']}/summary", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["call_id"] == call["id"]
    assert body["agreements_total"] == 2
    assert body["agreements_confirmed"] == 1
    assert "Отправить КП" in body["summary"]
    assert "Согласовать смету" in body["summary"]
    assert "Черновик" not in body["summary"]

    # Итог хранится в звонке (CallOut.summary) — его получают sync и call_ended.
    stored = await client.get(f"/api/calls/{call['id']}", headers=headers)
    assert stored.status_code == 200, stored.text
    assert stored.json()["summary"] == body["summary"]


async def test_call_summary_is_owner_only(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    anna_headers = auth_headers(str(anna["access_token"]))
    call = await create_call(client, anna_headers)

    boris = await login(client, USER_PHONES["boris"])
    response = await client.get(
        f"/api/calls/{call['id']}/summary",
        headers=auth_headers(str(boris["access_token"])),
    )
    assert response.status_code == 403, response.text


async def test_call_summary_empty_without_agreements(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    call = await create_call(client, headers)

    response = await client.get(f"/api/calls/{call['id']}/summary", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["agreements_total"] == 0
    assert body["agreements_confirmed"] == 0
    assert "не выделены" in body["summary"]
