"""WebSocket call-event stream: handshake auth, ownership, replay and live delivery.

The route is exercised directly with a lightweight double instead of a real
handshake: httpx's ASGI transport cannot open WebSockets, and a sync
``TestClient`` cannot use this package's async fixtures. The double implements
exactly the ``WebSocket`` surface the route touches.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from starlette.websockets import WebSocket, WebSocketDisconnect

from app.api.ws import WS_FORBIDDEN, WS_NOT_FOUND, WS_UNAUTHORIZED
from app.services.events import EVENT_SCHEMA_VERSION, CallEventMessage
from tests.integration.conftest import (
    USER_PHONES,
    auth_headers,
    create_call,
    login,
)

pytestmark = pytest.mark.integration


class FakeWebSocket:
    """Minimal ``WebSocket`` double: records sends, can fail after N frames."""

    def __init__(self, app: FastAPI, *, token: str | None = None, fail_after: int | None = None) -> None:
        self.app = app
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.query_params: dict[str, str] = {}
        self.sent: list[str] = []
        self.accepted = False
        self.close_code: int | None = None
        self.fail_after = fail_after

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, data: str) -> None:
        self.sent.append(data)
        if self.fail_after is not None and len(self.sent) >= self.fail_after:
            raise WebSocketDisconnect(1000)

    async def close(self, code: int = 1000) -> None:
        self.close_code = code

    def events(self) -> list[dict[str, Any]]:
        return [cast("dict[str, Any]", json.loads(frame)) for frame in self.sent]


async def run_route(app: FastAPI, ws: FakeWebSocket, call_id: uuid.UUID) -> None:
    from app.api.ws import call_events

    await call_events(cast("WebSocket", ws), call_id)


async def test_missing_token_is_rejected(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    app, _ = app_and_client
    ws = FakeWebSocket(app, token=None)
    await run_route(app, ws, uuid.uuid4())
    assert ws.close_code == WS_UNAUTHORIZED
    assert ws.sent == []


async def test_invalid_token_is_rejected(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    app, _ = app_and_client
    ws = FakeWebSocket(app, token="not-a-jwt")
    await run_route(app, ws, uuid.uuid4())
    assert ws.close_code == WS_UNAUTHORIZED


async def test_unknown_call_is_not_found(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    app, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    ws = FakeWebSocket(app, token=str(anna["access_token"]))
    await run_route(app, ws, uuid.uuid4())
    assert ws.close_code == WS_NOT_FOUND


async def test_other_users_call_is_forbidden(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    app, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    call = await create_call(client, auth_headers(str(anna["access_token"])))

    boris = await login(client, USER_PHONES["boris"])
    ws = FakeWebSocket(app, token=str(boris["access_token"]))
    await run_route(app, ws, uuid.UUID(call["id"]))
    assert ws.close_code == WS_FORBIDDEN


async def test_replays_persisted_events_with_version(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    app, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    call = await create_call(client, auth_headers(str(anna["access_token"])))
    call_id = uuid.UUID(call["id"])

    await app.state.event_hub.emit(
        CallEventMessage(event="analysis_started", call_id=call_id, payload={})
    )
    await app.state.event_hub.emit(
        CallEventMessage(
            event="partial_transcript",
            call_id=call_id,
            payload={"speaker": "client", "text": "пришлите КП"},
        )
    )

    ws = FakeWebSocket(app, token=str(anna["access_token"]), fail_after=2)
    await run_route(app, ws, call_id)

    events = ws.events()
    assert [e["event"] for e in events] == ["analysis_started", "partial_transcript"]
    assert all(e["version"] == EVENT_SCHEMA_VERSION for e in events)
    assert events[1]["payload"]["text"] == "пришлите КП"


async def test_streams_live_events_after_connect(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    app, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    call = await create_call(client, auth_headers(str(anna["access_token"])))
    call_id = uuid.UUID(call["id"])

    ws = FakeWebSocket(app, token=str(anna["access_token"]), fail_after=1)
    task = asyncio.create_task(run_route(app, ws, call_id))
    for _ in range(1000):  # the route subscribes before accept() returns
        if ws.accepted:
            break
        await asyncio.sleep(0.001)
    assert ws.accepted, "route never accepted the connection"

    await app.state.event_hub.emit(
        CallEventMessage(event="call_ended", call_id=call_id, payload={"duration_sec": 12})
    )
    await task

    assert [e["event"] for e in ws.events()] == ["call_ended"]


async def test_ws_events_schema_endpoint(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    response = await client.get("/api/ws/events/schema")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["version"] == EVENT_SCHEMA_VERSION
    assert "agreement_detected" in body["events"]
    assert body["envelope"]["properties"]["version"]["default"] == EVENT_SCHEMA_VERSION
