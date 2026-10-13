"""МТС Exolve webhooks end to end.

The call-control webhook routes an inbound call to the app user and plays the
consent notice; the progress-notification webhook then drives the *same*
consent-gated lifecycle the mock provider uses. These tests pin both the wire
contract (JSON-RPC routing body) and the product rule (recording only after
``answered`` + consent).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.db.models import CallAudio
from tests.integration.conftest import (
    USER_PHONES,
    VOICE_HEADERS,
    auth_headers,
    login,
)

pytestmark = pytest.mark.integration

CONTROL_URL = "/api/voice/exolve/control"
EVENTS_URL = "/api/voice/exolve/events"


@pytest.fixture
async def exolve(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
) -> AsyncIterator[FastAPI]:
    """Configure inbound routing: SIP 1001 -> Анна, 1002 -> Борис."""
    app, _ = app_and_client
    settings = app.state.settings
    previous = (
        settings.exolve_sip_routes,
        settings.exolve_consent_notice_file_id,
        settings.public_base_url,
    )
    settings.exolve_sip_routes = (
        "1001=+79000000002:sip:anna@pbx,1002=+79000000003:sip:boris@pbx"
    )
    settings.exolve_consent_notice_file_id = "notice-file-1"
    settings.public_base_url = "https://api.example.test"
    try:
        yield app
    finally:
        (
            settings.exolve_sip_routes,
            settings.exolve_consent_notice_file_id,
            settings.public_base_url,
        ) = previous


async def control(
    client: httpx.AsyncClient,
    *,
    sip_id: str = "1001",
    number_a: str = "+79995550000",
    call_sid: str = "ex-call-1",
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return await client.post(
        CONTROL_URL,
        json={"sip_id": sip_id, "numberA": number_a, "call_sid": call_sid},
        headers=headers if headers is not None else VOICE_HEADERS,
    )


async def event(
    client: httpx.AsyncClient,
    *,
    kind: str,
    call_sid: str = "ex-call-1",
    client_id: str | None = None,
    uid: str | int | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    payload: dict[str, object] = {"type": kind, "call_sid": call_sid}
    if client_id is not None:
        payload["client_id"] = client_id
    if uid is not None:
        payload["uid"] = uid
    return await client.post(
        EVENTS_URL, json=payload, headers=headers if headers is not None else VOICE_HEADERS
    )


async def test_control_routes_inbound_call_to_app_user(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    exolve: FastAPI,
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    response = await control(client, number_a="+79995550000")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["jsonrpc"] == "2.0"
    assert body["sip_id"] == "1001"
    result = body["result"]
    client_id = uuid.UUID(result["client_id"])  # our own call id, echoed back
    assert result["redirect_type"] == 1
    assert result["file_to_A"] == "notice-file-1"
    assert result["event_URL"] == (
        f"https://api.example.test/api/voice/exolve/events?secret={VOICE_HEADERS['X-Voice-Webhook-Secret']}"
    )
    assert result["followme_struct"][1][0]["SIP_URI"] == "sip:anna@pbx"

    # The call row belongs to Анна and carries the provider id for correlation.
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    call = await client.get(f"/api/calls/{client_id}", headers=headers)
    assert call.status_code == 200, call.text
    created = call.json()
    assert created["direction"] == "inbound"
    assert created["contact_phone"] == "+79995550000"
    assert created["status"] == "incoming"


async def test_control_is_idempotent_for_a_repeated_call_sid(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    exolve: FastAPI,
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    first = (await control(client)).json()
    second = (await control(client)).json()
    assert first["result"]["client_id"] == second["result"]["client_id"]

    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    calls = await client.get("/api/calls", headers=headers)
    assert len(calls.json()) == 1


async def test_control_refuses_unknown_sip_resource(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    exolve: FastAPI,
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    response = await control(client, sip_id="9999")
    assert response.status_code == 200, response.text
    body = response.json()
    assert "result" not in body
    assert body["error"]["code"] == -32000
    assert body["sip_id"] == "9999"
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    calls = await client.get("/api/calls", headers=headers)
    assert calls.json() == []


async def test_control_requires_the_voice_secret(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    exolve: FastAPI,
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    response = await control(client, headers={})
    assert response.status_code == 403


async def test_events_drive_consent_gated_recording(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    exolve: FastAPI,
    seeded_users: dict[str, uuid.UUID],
) -> None:
    app, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    consent = await client.put("/api/me/consent", json={"granted": True}, headers=headers)
    assert consent.status_code == 200, consent.text

    call_id = (await control(client)).json()["result"]["client_id"]

    ringing = await event(client, kind="o", client_id=call_id)
    assert ringing.status_code == 200, ringing.text
    assert ringing.json()["status"] == "handled"

    answered = await event(client, kind="s", client_id=call_id)
    assert answered.status_code == 200, answered.text

    call = await client.get(f"/api/calls/{call_id}", headers=headers)
    body = call.json()
    assert body["status"] == "in_progress"
    assert body["recording_started_at"] is not None

    ops = [op for op, _ in app.state.voice_provider.history]
    assert "start_recording" in ops
    assert "open_media_stream" in ops

    ended = await event(client, kind="e", client_id=call_id)
    assert ended.status_code == 200, ended.text
    assert (await client.get(f"/api/calls/{call_id}", headers=headers)).json()["status"] == (
        "completed"
    )

    events = await app.state.cache.client.lrange(f"events:call:{call_id}", 0, -1)
    names = [json.loads(entry)["event"] for entry in events]
    assert "analysis_started" in names
    assert "call_ended" in names


async def test_events_fall_back_to_call_sid_when_client_id_is_absent(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    exolve: FastAPI,
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    await client.put("/api/me/consent", json={"granted": True}, headers=headers)

    call_id = (await control(client, call_sid="ex-fallback")).json()["result"]["client_id"]

    response = await event(client, kind="s", call_sid="ex-fallback")  # no client_id
    assert response.status_code == 200, response.text

    call = await client.get(f"/api/calls/{call_id}", headers=headers)
    assert call.json()["recording_started_at"] is not None


async def test_events_acknowledge_unknown_type_without_a_transition(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    exolve: FastAPI,
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    call_id = (await control(client)).json()["result"]["client_id"]
    response = await event(client, kind="z", client_id=call_id)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ignored"


async def test_events_accept_query_secret(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    exolve: FastAPI,
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    call_id = (await control(client)).json()["result"]["client_id"]
    secret = VOICE_HEADERS["X-Voice-Webhook-Secret"]
    response = await client.post(
        f"{EVENTS_URL}?secret={secret}",
        json={"type": "o", "call_sid": "ex-call-1", "client_id": call_id},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "handled"


async def test_events_require_the_voice_secret(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    exolve: FastAPI,
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    response = await event(client, kind="o", headers={})
    assert response.status_code == 403


async def test_event_for_unknown_call_is_404(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    exolve: FastAPI,
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    response = await event(client, kind="o", call_sid="no-such-call")
    assert response.status_code == 404


async def _audio_url(session_factory: async_sessionmaker[AsyncSession], call_id: str) -> str | None:
    async with session_factory() as session:
        result = await session.execute(
            select(CallAudio.storage_url).where(CallAudio.call_id == uuid.UUID(call_id))
        )
        return result.scalar_one_or_none()


async def test_crr_remembers_the_record_id_for_the_download_worker(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    exolve: FastAPI,
    seeded_users: dict[str, uuid.UUID],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    await client.put("/api/me/consent", json={"granted": True}, headers=headers)

    call_id = (await control(client)).json()["result"]["client_id"]
    await event(client, kind="s", client_id=call_id)  # answered + consent -> recording

    response = await event(client, kind="crr", client_id=call_id, uid=7135909209505402880)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "queued"

    # The record id is parked on the audio row; a worker downloads the audio.
    assert await _audio_url(session_factory, call_id) == "provider://exolve/7135909209505402880"


async def test_crr_without_consent_is_rejected(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    exolve: FastAPI,
    seeded_users: dict[str, uuid.UUID],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """No ``answered``+consent in our flow: the provider recording is not ours."""
    _, client = app_and_client
    call_id = (await control(client)).json()["result"]["client_id"]

    response = await event(client, kind="crr", client_id=call_id, uid=42)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "rejected"
    assert await _audio_url(session_factory, call_id) is None


async def test_crr_without_a_record_id_is_ignored(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    exolve: FastAPI,
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    call_id = (await control(client)).json()["result"]["client_id"]
    response = await event(client, kind="crr", client_id=call_id)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ignored"
