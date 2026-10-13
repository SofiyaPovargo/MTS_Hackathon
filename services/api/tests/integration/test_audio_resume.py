"""Resumable client audio upload: a network drop must not lose recorded audio.

The mobile client uploads the recording while the call is still going, so a
connection loss is expected (Wi-Fi hand-off, 4G dead spot, weak signal). These
tests drive the ``Content-Range`` chunk protocol and assert that whatever the
server acknowledged is durable, that a reconnect resumes from the reported
offset, that a retried chunk is idempotent, and that out-of-order chunks are
rejected with the offset to resume from.
"""

from __future__ import annotations

import uuid
from typing import cast

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.db import repositories
from app.infrastructure.db.models import CallAudio
from app.infrastructure.storage import StorageError, key_from_url
from tests.integration.conftest import USER_PHONES, auth_headers, login
from tests.integration.test_audio_ingest import AUDIO, _recorded_call, _RecordingQueue

pytestmark = pytest.mark.integration


def _pending(audio: CallAudio) -> dict[str, object]:
    """Test view of the in-flight chunked session for the mixed stream (JSONB)."""
    uploads = cast("dict[str, dict[str, object]]", audio.pending_uploads or {})
    return uploads["mixed"]


def _parts(audio: CallAudio) -> list[dict[str, object]]:
    return cast("list[dict[str, object]]", _pending(audio)["parts"])


def _audio(size: int, seed: bytes = b"a") -> bytes:
    return (seed * size)[:size]


def _chunk_headers(
    headers: dict[str, str], start: int, end: int, total: int, content_type: str = "audio/wav"
) -> dict[str, str]:
    return {
        **headers,
        "Content-Type": content_type,
        "Content-Range": f"bytes {start}-{end}/{total}",
    }


async def test_resume_after_a_dropped_connection(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Wi-Fi drop mid-call: the bytes sent before the drop survive in storage."""
    app, client = app_and_client
    queue = _RecordingQueue()
    app.state.analysis_queue = queue

    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    call = await _recorded_call(client, headers, external_id="ext-resume")
    call_id = call["id"]

    first, second = _audio(50, b"a"), _audio(50, b"b")
    total = len(first) + len(second)

    # Chunk 1 arrives, then the connection drops: nothing more is sent.
    response = await client.post(
        f"/api/calls/{call_id}/audio",
        content=first,
        headers=_chunk_headers(headers, 0, len(first) - 1, total),
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["offset"] == len(first)
    assert body["complete"] is False
    assert body["analysis_queued"] is False
    assert queue.asr == []

    # The acknowledged offset is durable: the chunk is already in storage.
    async with session_factory() as session:
        audio = await repositories.get_call_audio(session, uuid.UUID(str(call_id)))
        assert audio is not None
        assert audio.pending_uploads is not None
        session_state = _pending(audio)
        assert session_state["offset"] == len(first)
    async with session_factory() as session:
        audio = await repositories.get_call_audio(session, uuid.UUID(str(call_id)))
        assert audio is not None
        part_key = _parts(audio)[0]["key"]
    assert await app.state.storage.get_bytes(part_key) == first

    # Reconnect on 4G and continue from the reported offset.
    resumed = await client.post(
        f"/api/calls/{call_id}/audio",
        content=second,
        headers=_chunk_headers(headers, len(first), total - 1, total),
    )
    assert resumed.status_code == 202, resumed.text
    body = resumed.json()
    assert body["offset"] == total
    assert body["complete"] is True
    assert body["analysis_queued"] is True
    assert queue.asr == [call_id]

    # The assembled object holds every byte, and the chunks are gone.
    async with session_factory() as session:
        audio = await repositories.get_call_audio(session, uuid.UUID(str(call_id)))
        assert audio is not None
        assert audio.pending_uploads is None
    assert await app.state.storage.get_bytes(key_from_url(audio.storage_url)) == first + second
    with pytest.raises(StorageError):
        await app.state.storage.get_bytes(part_key)


async def test_retrying_a_chunk_is_idempotent(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A weak signal resends a chunk that already arrived; it must not duplicate."""
    app, client = app_and_client
    queue = _RecordingQueue()
    app.state.analysis_queue = queue

    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    call = await _recorded_call(client, headers, external_id="ext-retry")
    call_id = call["id"]
    data = _audio(80, b"c")
    half = len(data) // 2

    for _ in range(2):  # the same first chunk twice
        response = await client.post(
            f"/api/calls/{call_id}/audio",
            content=data[:half],
            headers=_chunk_headers(headers, 0, half - 1, len(data)),
        )
        assert response.status_code == 202, response.text
        assert response.json()["offset"] == half

    final = await client.post(
        f"/api/calls/{call_id}/audio",
        content=data[half:],
        headers=_chunk_headers(headers, half, len(data) - 1, len(data)),
    )
    assert final.status_code == 202, final.text
    assert final.json()["complete"] is True

    async with session_factory() as session:
        audio = await repositories.get_call_audio(session, uuid.UUID(str(call_id)))
        assert audio is not None
        assert await app.state.storage.get_bytes(key_from_url(audio.storage_url)) == data


async def test_out_of_order_chunk_reports_the_offset_to_resume_from(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    """A gap (chunk 3 arrives before chunk 2) is a 409 with ``expected_offset``."""
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    call = await _recorded_call(client, headers, external_id="ext-gap")
    call_id = call["id"]

    first = await client.post(
        f"/api/calls/{call_id}/audio",
        content=_audio(10, b"a"),
        headers=_chunk_headers(headers, 0, 9, 30),
    )
    assert first.status_code == 202, first.text

    gap = await client.post(
        f"/api/calls/{call_id}/audio",
        content=_audio(10, b"c"),
        headers=_chunk_headers(headers, 20, 29, 30),
    )
    assert gap.status_code == 409, gap.text
    assert gap.json()["expected_offset"] == 10
    assert gap.json()["total"] == 30


async def test_first_chunk_must_start_at_zero(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    call = await _recorded_call(client, headers, external_id="ext-nostart")

    response = await client.post(
        f"/api/calls/{call['id']}/audio",
        content=_audio(10, b"a"),
        headers=_chunk_headers(headers, 10, 19, 30),
    )
    assert response.status_code == 409, response.text
    assert response.json()["expected_offset"] == 0


async def test_declared_total_over_the_limit_is_413(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    app, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    call = await _recorded_call(client, headers, external_id="ext-huge")

    previous = app.state.settings.max_audio_upload_mb
    app.state.settings.max_audio_upload_mb = 0
    try:
        response = await client.post(
            f"/api/calls/{call['id']}/audio",
            content=_audio(10, b"a"),
            headers=_chunk_headers(headers, 0, 9, 1000),
        )
    finally:
        app.state.settings.max_audio_upload_mb = previous
    assert response.status_code == 413, response.text


async def test_malformed_content_range_is_422(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    call = await _recorded_call(client, headers, external_id="ext-malformed")
    url = f"/api/calls/{call['id']}/audio"

    for value in ("items 0-9/30", "bytes 0-9", "bytes 5-4/30", "bytes 0-9/0", "bytes a-b/30"):
        response = await client.post(
            url,
            content=_audio(10, b"a"),
            headers={**headers, "Content-Type": "audio/wav", "Content-Range": value},
        )
        assert response.status_code == 422, (value, response.text)


async def test_content_range_must_match_the_body(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    call = await _recorded_call(client, headers, external_id="ext-length")

    response = await client.post(
        f"/api/calls/{call['id']}/audio",
        content=_audio(10, b"a"),
        headers=_chunk_headers(headers, 0, 99, 200),
    )
    assert response.status_code == 422, response.text


async def test_chunked_upload_requires_a_recorded_call(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    """The consent gate holds for the resumable path too."""
    _, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    call = await client.post(
        "/api/calls",
        json={"direction": "outbound", "callee_phone": "+79991230001"},
        headers=headers,
    )
    assert call.status_code == 201, call.text

    response = await client.post(
        f"/api/calls/{call.json()['id']}/audio",
        content=_audio(10, b"a"),
        headers=_chunk_headers(headers, 0, 9, 30),
    )
    assert response.status_code == 409, response.text


async def test_restart_discards_pending_chunks(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The client may abandon a broken upload and start the recording over."""
    app, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    call = await _recorded_call(client, headers, external_id="ext-restart")
    call_id = call["id"]

    await client.post(
        f"/api/calls/{call_id}/audio",
        content=_audio(10, b"a"),
        headers=_chunk_headers(headers, 0, 9, 30),
    )
    async with session_factory() as session:
        audio = await repositories.get_call_audio(session, uuid.UUID(str(call_id)))
        assert audio is not None
        stale_key = _parts(audio)[0]["key"]

    fresh = await client.post(
        f"/api/calls/{call_id}/audio?restart=true",
        content=_audio(4, b"z"),
        headers=_chunk_headers(headers, 0, 3, 4),
    )
    assert fresh.status_code == 202, fresh.text
    assert fresh.json()["offset"] == 4
    assert fresh.json()["complete"] is True

    # The abandoned chunk was removed, not left behind as personal data.
    with pytest.raises(StorageError):
        await app.state.storage.get_bytes(stale_key)


async def test_chunked_per_leg_uploads_queue_only_when_both_complete(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    app, client = app_and_client
    queue = _RecordingQueue()
    app.state.analysis_queue = queue

    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    call = await _recorded_call(client, headers, external_id="ext-leg-chunks")
    call_id = call["id"]

    operator = await client.post(
        f"/api/calls/{call_id}/audio?leg=operator",
        content=_audio(6, b"o"),
        headers=_chunk_headers(headers, 0, 5, 6, content_type="audio/wav"),
    )
    assert operator.status_code == 202, operator.text
    assert operator.json()["legs_present"] == ["operator"]
    assert operator.json()["analysis_queued"] is False

    client_leg = await client.post(
        f"/api/calls/{call_id}/audio?leg=client",
        content=_audio(6, b"c"),
        headers=_chunk_headers(headers, 0, 5, 6, content_type="audio/ogg"),
    )
    assert client_leg.status_code == 202, client_leg.text
    assert client_leg.json()["legs_present"] == ["client", "operator"]
    assert client_leg.json()["analysis_queued"] is True
    assert queue.asr == [call_id]


async def test_whole_object_upload_supersedes_a_pending_chunked_upload(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    app, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    call = await _recorded_call(client, headers, external_id="ext-supersede")
    call_id = call["id"]

    await client.post(
        f"/api/calls/{call_id}/audio",
        content=_audio(10, b"a"),
        headers=_chunk_headers(headers, 0, 9, 30),
    )
    async with session_factory() as session:
        audio = await repositories.get_call_audio(session, uuid.UUID(str(call_id)))
        assert audio is not None
        stale_key = _parts(audio)[0]["key"]

    response = await client.post(
        f"/api/calls/{call_id}/audio",
        content=AUDIO,
        headers={**headers, "Content-Type": "audio/wav"},
    )
    assert response.status_code == 202, response.text
    assert response.json()["complete"] is True

    async with session_factory() as session:
        audio = await repositories.get_call_audio(session, uuid.UUID(str(call_id)))
        assert audio is not None
        assert audio.pending_uploads is None
        assert await app.state.storage.get_bytes(key_from_url(audio.storage_url)) == AUDIO
    with pytest.raises(StorageError):
        await app.state.storage.get_bytes(stale_key)
