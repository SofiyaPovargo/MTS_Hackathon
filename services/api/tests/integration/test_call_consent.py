"""The critical product rule, end to end: recording starts only after
``answered`` and a successful consent flow. The mock Voice Provider history is
asserted so a recording cannot start without consent — in any mode."""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
from fastapi import FastAPI

from tests.integration.conftest import (
    USER_PHONES,
    VOICE_HEADERS,
    auth_headers,
    create_call,
    login,
)

pytestmark = pytest.mark.integration


def voice_ops(app: FastAPI) -> list[str]:
    return [op for op, _ in app.state.voice_provider.history]


async def test_answered_without_app_consent_never_records(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    app, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))

    call = await create_call(client, headers, external_id="ext-no-consent")
    response = await client.post(
        f"/api/calls/{call['id']}/events", json={"event": "answered"}, headers=VOICE_HEADERS
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "in_progress"
    assert body["recording_started_at"] is None
    assert body["answered_at"] is not None

    ops = voice_ops(app)
    assert "start_recording" not in ops
    assert "open_media_stream" not in ops
    assert "play_notice" not in ops


async def test_app_consent_notice_records_and_emits_events(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    app, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))

    consent = await client.put("/api/me/consent", json={"granted": True}, headers=headers)
    assert consent.status_code == 200, consent.text
    assert consent.json()["status"] == "granted"

    call = await create_call(client, headers, external_id="ext-notice")
    response = await client.post(
        f"/api/calls/{call['id']}/events", json={"event": "answered"}, headers=VOICE_HEADERS
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "in_progress"
    assert body["recording_started_at"] is not None

    ops = voice_ops(app)
    assert "play_notice:consent-notice-v1" in ops
    assert "start_recording" in ops
    assert "open_media_stream" in ops

    # Hangup mid-call ends in ``completed`` and posts the call_ended event.
    response = await client.post(
        f"/api/calls/{call['id']}/events", json={"event": "ended"}, headers=VOICE_HEADERS
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed"

    events = await app.state.cache.client.lrange(f"events:call:{call['id']}", 0, -1)
    names = [json.loads(event)["event"] for event in events]
    assert "analysis_started" in names
    assert "call_ended" in names


async def test_dtmf_refusal_blocks_recording(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    app, client = app_and_client
    settings = app.state.settings
    previous_mode = settings.consent_mode
    settings.consent_mode = "dtmf"
    app.state.voice_provider.dtmf_response = "2"
    try:
        anna = await login(client, USER_PHONES["anna"])
        headers = auth_headers(str(anna["access_token"]))
        await client.put("/api/me/consent", json={"granted": True}, headers=headers)

        call = await create_call(client, headers, external_id="ext-dtmf")
        response = await client.post(
            f"/api/calls/{call['id']}/events", json={"event": "answered"}, headers=VOICE_HEADERS
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "in_progress"
        assert body["recording_started_at"] is None

        ops = voice_ops(app)
        assert "play_consent_prompt" in ops
        assert "collect_dtmf" in ops
        assert "start_recording" not in ops
    finally:
        settings.consent_mode = previous_mode


async def test_withdrawn_consent_blocks_recording(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    app, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))

    await client.put("/api/me/consent", json={"granted": True}, headers=headers)
    withdrawn = await client.post("/api/me/consent/withdraw", headers=headers)
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["status"] == "withdrawn"

    call = await create_call(client, headers, external_id="ext-withdrawn")
    response = await client.post(
        f"/api/calls/{call['id']}/events", json={"event": "answered"}, headers=VOICE_HEADERS
    )
    assert response.status_code == 200, response.text
    assert response.json()["recording_started_at"] is None
    assert "start_recording" not in voice_ops(app)


async def test_invalid_provider_transition_is_409(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))

    # A call in ``ringing`` cannot jump straight to ``completed``.
    call = await create_call(client, headers)
    response = await client.post(
        f"/api/calls/{call['id']}/events", json={"event": "ended"}, headers=VOICE_HEADERS
    )
    assert response.status_code == 409


async def test_provider_event_requires_webhook_secret(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))

    call = await create_call(client, headers)
    response = await client.post(
        f"/api/calls/{call['id']}/events", json={"event": "answered"}, headers=headers
    )
    assert response.status_code == 403