"""Offline call (§13): a conversation recorded without network is pushed later.

The client generates the call id locally, creates the call when it is back
online (idempotently), declares the recording + consent, and only then uploads
the audio. The critical rule is unchanged: recording — and therefore the audio
upload — is impossible without consent.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI

from tests.integration.conftest import USER_PHONES, auth_headers, login

pytestmark = pytest.mark.integration

AUDIO = b"RIFF\x00\x00\x00\x00WAVEfmt " + b"\x00" * 64


class _RecordingQueue:
    """Analysis queue spy: records the calls whose ASR was enqueued."""

    def __init__(self) -> None:
        self.asr: list[str] = []

    def enqueue_asr(self, call_id: str) -> None:
        self.asr.append(call_id)

    def enqueue_extraction(self, call_id: str) -> None:  # pragma: no cover - unused
        return None


async def _create_offline_call(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    call_id: uuid.UUID | None = None,
    record_consent: bool = True,
) -> dict[str, Any]:
    """Create a call the way the offline outbox does: with a client-side id."""
    payload: dict[str, object] = {
        "id": str(call_id or uuid.uuid4()),
        "direction": "outbound",
        "callee_phone": "+79991234000",
        "contact_name": "Игорь",
        "started_at": "2026-10-13T09:00:00Z",
        "record_consent": record_consent,
    }
    response = await client.post("/api/calls", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return cast("dict[str, Any]", response.json())


async def _declare(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    call_id: str,
    *,
    record_consent: bool = True,
    participant_consent: str = "granted",
    ended_at: str | None = "2026-10-13T09:12:00Z",
) -> httpx.Response:
    body: dict[str, object] = {
        "record_consent": record_consent,
        "participant_consent": participant_consent,
        "consent_method": "audio_notice",
        "answered_at": "2026-10-13T09:00:05Z",
        "recording_started_at": "2026-10-13T09:00:06Z",
    }
    if ended_at is not None:
        body["ended_at"] = ended_at
    return await client.post(f"/api/calls/{call_id}/recordings", json=body, headers=headers)


async def _upload(
    client: httpx.AsyncClient, headers: dict[str, str], call_id: str
) -> httpx.Response:
    return await client.post(
        f"/api/calls/{call_id}/audio",
        content=AUDIO,
        headers={**headers, "Content-Type": "audio/wav"},
    )


async def test_offline_call_creation_is_idempotent(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    call_id = uuid.uuid4()

    first = await _create_offline_call(client, headers, call_id=call_id)
    second = await _create_offline_call(client, headers, call_id=call_id)

    assert first["id"] == str(call_id)
    assert second["id"] == str(call_id)
    # The real conversation time travels with the client-created call.
    assert first["started_at"].startswith("2026-10-13T09:00:00")

    listing = await client.get("/api/calls", headers=headers)
    assert listing.status_code == 200, listing.text
    assert [c["id"] for c in listing.json()] == [str(call_id)]


async def test_offline_call_client_id_belongs_to_one_owner(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    call_id = uuid.uuid4()
    await _create_offline_call(client, auth_headers(str(anna["access_token"])), call_id=call_id)

    boris = await login(client, USER_PHONES["boris"])
    response = await client.post(
        "/api/calls",
        json={
            "id": str(call_id),
            "direction": "outbound",
            "callee_phone": "+79991234000",
        },
        headers=auth_headers(str(boris["access_token"])),
    )
    assert response.status_code == 403, response.text


async def test_declared_offline_recording_is_accepted_and_processed(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    app, client = app_and_client
    queue = _RecordingQueue()
    app.state.analysis_queue = queue

    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    call = await _create_offline_call(client, headers)

    declared = await _declare(client, headers, str(call["id"]))
    assert declared.status_code == 200, declared.text
    body = declared.json()
    assert body["recording_started_at"] is not None
    assert body["status"] == "completed"
    assert body["ended_at"] is not None

    uploaded = await _upload(client, headers, str(call["id"]))
    assert uploaded.status_code == 202, uploaded.text
    assert uploaded.json()["analysis_queued"] is True
    assert queue.asr == [str(call["id"])]


async def test_offline_declaration_is_idempotent(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    call = await _create_offline_call(client, headers)

    first = await _declare(client, headers, str(call["id"]))
    second = await _declare(client, headers, str(call["id"]))
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["recording_started_at"] == second.json()["recording_started_at"]


async def test_declaration_record_consent_false_leaves_call_unrecorded(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    call = await _create_offline_call(client, headers)

    declared = await _declare(client, headers, str(call["id"]), record_consent=False)
    assert declared.status_code == 200, declared.text
    body = declared.json()
    assert body["recording_started_at"] is None
    assert body["status"] == "completed"

    upload = await _upload(client, headers, str(call["id"]))
    assert upload.status_code == 409, upload.text


async def test_creation_record_consent_false_blocks_later_declaration(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    # The call was created as explicitly non-recordable: a later declaration
    # must not turn recording on for it.
    call = await _create_offline_call(client, headers, record_consent=False)

    declared = await _declare(client, headers, str(call["id"]))
    assert declared.status_code == 403, declared.text

    upload = await _upload(client, headers, str(call["id"]))
    assert upload.status_code == 409, upload.text


async def test_participant_refusal_leaves_call_unrecorded(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    call = await _create_offline_call(client, headers)

    declared = await _declare(client, headers, str(call["id"]), participant_consent="denied")
    assert declared.status_code == 200, declared.text
    assert declared.json()["recording_started_at"] is None

    upload = await _upload(client, headers, str(call["id"]))
    assert upload.status_code == 409, upload.text


async def test_withdrawn_app_consent_blocks_offline_declaration(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    await client.put("/api/me/consent", json={"granted": True}, headers=headers)
    await client.post("/api/me/consent/withdraw", headers=headers)

    call = await _create_offline_call(client, headers)
    declared = await _declare(client, headers, str(call["id"]))
    assert declared.status_code == 403, declared.text
    assert "consent" in declared.json()["detail"]

    upload = await _upload(client, headers, str(call["id"]))
    assert upload.status_code == 409, upload.text


async def test_declaration_requires_call_owner(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    call = await _create_offline_call(client, auth_headers(str(anna["access_token"])))

    boris = await login(client, USER_PHONES["boris"])
    response = await _declare(client, auth_headers(str(boris["access_token"])), str(call["id"]))
    assert response.status_code == 403, response.text


async def test_declaration_requires_authentication(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    response = await client.post(
        f"/api/calls/{uuid.uuid4()}/recordings", json={"record_consent": True}
    )
    assert response.status_code == 401, response.text
