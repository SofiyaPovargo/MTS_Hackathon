"""Client audio ingest: the app uploads the call recording, the pipeline runs.

Covers the storage-side consent gate (no recording -> refusal), owner-only
access, size/type limits, per-leg uploads and idempotent re-upload.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.db import repositories
from app.infrastructure.storage import StorageError, key_from_url
from tests.integration.conftest import (
    USER_PHONES,
    VOICE_HEADERS,
    auth_headers,
    create_call,
    login,
)

pytestmark = pytest.mark.integration

# Not real audio: the endpoint stores bytes; decoding happens in the worker.
AUDIO = b"RIFF\x00\x00\x00\x00WAVEfmt " + b"\x00" * 64


class _RecordingQueue:
    """Analysis queue spy: records the calls whose ASR was enqueued."""

    def __init__(self) -> None:
        self.asr: list[str] = []

    def enqueue_asr(self, call_id: str) -> None:
        self.asr.append(call_id)

    def enqueue_extraction(self, call_id: str) -> None:  # pragma: no cover - unused
        return None


async def _recorded_call(
    client: httpx.AsyncClient, headers: dict[str, str], *, external_id: str
) -> dict[str, object]:
    """Drive answered + consent so the call really is recorded."""
    consent = await client.put("/api/me/consent", json={"granted": True}, headers=headers)
    assert consent.status_code == 200, consent.text
    call = await create_call(client, headers, external_id=external_id)
    response = await client.post(
        f"/api/calls/{call['id']}/events", json={"event": "answered"}, headers=VOICE_HEADERS
    )
    assert response.status_code == 200, response.text
    assert response.json()["recording_started_at"] is not None
    return call


async def test_mixed_upload_stores_queues_and_replaces_placeholder(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    app, client = app_and_client
    queue = _RecordingQueue()
    app.state.analysis_queue = queue

    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    call = await _recorded_call(client, headers, external_id="ext-mixed")

    response = await client.post(
        f"/api/calls/{call['id']}/audio",
        content=AUDIO,
        headers={**headers, "Content-Type": "audio/wav"},
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["analysis_queued"] is True
    assert body["legs_present"] == []
    assert body["role"] is None
    assert body["content_type"] == "audio/wav"
    assert body["bytes_stored"] == len(AUDIO)
    assert queue.asr == [call["id"]]

    async with session_factory() as session:
        audio = await repositories.get_call_audio(session, uuid.UUID(str(call["id"])))
        assert audio is not None
        assert audio.storage_url.startswith("s3://memory/calls/")
        assert audio.storage_url.endswith(".wav")
        assert audio.channel_urls is None
        assert audio.expires_at is not None


async def test_upload_without_recording_is_refused(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    # Never answered: recording (and therefore upload) must be impossible.
    call = await create_call(client, headers)

    response = await client.post(
        f"/api/calls/{call['id']}/audio",
        content=AUDIO,
        headers={**headers, "Content-Type": "audio/wav"},
    )
    assert response.status_code == 409, response.text

    async with session_factory() as session:
        assert await repositories.get_call_audio(session, uuid.UUID(str(call["id"]))) is None


async def test_upload_requires_call_owner(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    call = await _recorded_call(client, auth_headers(str(anna["access_token"])), external_id="ext-x")

    boris = await login(client, USER_PHONES["boris"])
    response = await client.post(
        f"/api/calls/{call['id']}/audio",
        content=AUDIO,
        headers={**auth_headers(str(boris["access_token"])), "Content-Type": "audio/wav"},
    )
    assert response.status_code == 403, response.text


async def test_upload_requires_authentication(
    app_and_client: tuple[FastAPI, httpx.AsyncClient], seeded_users: dict[str, uuid.UUID]
) -> None:
    _, client = app_and_client
    response = await client.post(f"/api/calls/{uuid.uuid4()}/audio", content=AUDIO)
    assert response.status_code == 401, response.text


async def test_two_leg_uploads_queue_only_when_complete(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    app, client = app_and_client
    queue = _RecordingQueue()
    app.state.analysis_queue = queue

    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    call = await _recorded_call(client, headers, external_id="ext-legs")

    first = await client.post(
        f"/api/calls/{call['id']}/audio?leg=operator",
        content=AUDIO,
        headers={**headers, "Content-Type": "audio/wav"},
    )
    assert first.status_code == 202, first.text
    assert first.json()["analysis_queued"] is False
    assert first.json()["legs_present"] == ["operator"]
    assert queue.asr == []

    second = await client.post(
        f"/api/calls/{call['id']}/audio?leg=client",
        content=AUDIO,
        headers={**headers, "Content-Type": "audio/ogg"},
    )
    assert second.status_code == 202, second.text
    assert second.json()["analysis_queued"] is True
    assert second.json()["legs_present"] == ["client", "operator"]
    assert queue.asr == [call["id"]]

    async with session_factory() as session:
        audio = await repositories.get_call_audio(session, uuid.UUID(str(call["id"])))
        assert audio is not None
        channels = audio.channel_urls or {}
        assert set(channels) == {"operator", "client"}
        assert channels["operator"] != channels["client"]
        assert audio.storage_url == channels["operator"]


async def test_invalid_leg_is_refused(
    app_and_client: tuple[FastAPI, httpx.AsyncClient], seeded_users: dict[str, uuid.UUID]
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    call = await _recorded_call(client, headers, external_id="ext-badleg")

    response = await client.post(
        f"/api/calls/{call['id']}/audio?leg=channel3",
        content=AUDIO,
        headers={**headers, "Content-Type": "audio/wav"},
    )
    assert response.status_code == 422, response.text


async def test_unsupported_content_type_is_refused(
    app_and_client: tuple[FastAPI, httpx.AsyncClient], seeded_users: dict[str, uuid.UUID]
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    call = await _recorded_call(client, headers, external_id="ext-type")

    response = await client.post(
        f"/api/calls/{call['id']}/audio",
        content=b"{}",
        headers={**headers, "Content-Type": "application/json"},
    )
    assert response.status_code == 422, response.text


async def test_oversized_upload_is_413(
    app_and_client: tuple[FastAPI, httpx.AsyncClient], seeded_users: dict[str, uuid.UUID]
) -> None:
    app, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    call = await _recorded_call(client, headers, external_id="ext-big")

    previous = app.state.settings.max_audio_upload_mb
    app.state.settings.max_audio_upload_mb = 0
    try:
        response = await client.post(
            f"/api/calls/{call['id']}/audio",
            content=AUDIO,
            headers={**headers, "Content-Type": "audio/wav"},
        )
    finally:
        app.state.settings.max_audio_upload_mb = previous
    assert response.status_code == 413, response.text


async def test_reupload_replaces_and_deletes_previous_object(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    app, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    call = await _recorded_call(client, headers, external_id="ext-reupload")

    await client.post(
        f"/api/calls/{call['id']}/audio",
        content=AUDIO,
        headers={**headers, "Content-Type": "audio/wav"},
    )
    async with session_factory() as session:
        first = await repositories.get_call_audio(session, uuid.UUID(str(call["id"])))
        assert first is not None
        first_url = first.storage_url

    second = await client.post(
        f"/api/calls/{call['id']}/audio",
        content=AUDIO,
        headers={**headers, "Content-Type": "audio/ogg"},
    )
    assert second.status_code == 202, second.text

    async with session_factory() as session:
        audio = await repositories.get_call_audio(session, uuid.UUID(str(call["id"])))
        assert audio is not None
        assert audio.storage_url != first_url
        assert audio.storage_url.endswith(".ogg")

    # The superseded object is gone: personal data is not left behind.
    with pytest.raises(StorageError):
        await app.state.storage.get_bytes(key_from_url(first_url))
