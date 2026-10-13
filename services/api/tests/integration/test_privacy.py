"""Privacy flows: data deletion and audio retention (containers required)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.enums import AgreementStatus, CallDirection, CallStatus, Owner
from app.infrastructure.db import repositories
from app.infrastructure.db.models import Agreement, Call, CallAudio, Task, Transcript
from app.infrastructure.storage import InMemoryStorage, StorageError
from app.services.data_deletion import delete_user_data, purge_expired_audio

pytestmark = pytest.mark.integration

SessionFactory = async_sessionmaker[AsyncSession]


async def _call_with_data(
    session: AsyncSession,
    user_id: uuid.UUID,
    storage: InMemoryStorage,
    *,
    audio_expires_at: datetime | None = None,
) -> tuple[uuid.UUID, str]:
    call = Call(
        user_id=user_id,
        direction=CallDirection.inbound,
        contact_phone="+79990000000",
        contact_name="Клиент",
        status=CallStatus.recording,
        started_at=datetime(2026, 10, 5, 9, 0, tzinfo=UTC),
        recording_started_at=datetime(2026, 10, 5, 9, 0, 5, tzinfo=UTC),
    )
    session.add(call)
    await session.flush()

    key = f"calls/{call.id}/audio.wav"
    url = await storage.put_bytes(key, b"audio-bytes", "audio/wav")
    session.add(
        CallAudio(
            call_id=call.id,
            storage_url=url,
            content_type="audio/wav",
            expires_at=audio_expires_at,
        )
    )
    session.add(
        Transcript(
            call_id=call.id,
            language="ru",
            full_text="я пришлю договор до пятницы",
            segments=[],
            role_source="channel",
            status="done",
        )
    )
    session.add(
        Agreement(
            call_id=call.id,
            owner=Owner.counterparty,
            type="promise",
            title="Прислать договор",
            source_quote="я пришлю договор до пятницы",
            audio_start=0,
            audio_end=1,
            confidence=Decimal("0.90"),
            status=AgreementStatus.detected,
        )
    )
    session.add(Task(assignee_user_id=user_id, title="Прислать договор"))
    await session.commit()
    return call.id, key


async def test_delete_user_data_purges_everything(
    session_factory: SessionFactory,
    seeded_users: dict[str, uuid.UUID],
) -> None:
    anna_id = seeded_users["anna_id"]
    storage = InMemoryStorage()
    async with session_factory() as session:
        call_id, key = await _call_with_data(session, anna_id, storage)

    async with session_factory() as session:
        result = await delete_user_data(session, user_id=anna_id, storage=storage)
        await session.commit()

    assert result == {"calls": 1, "tasks": 1, "objects": 1}

    async with session_factory() as session:
        assert await repositories.get_call(session, call_id) is None
        assert await repositories.get_transcript(session, call_id) is None
    with pytest.raises(StorageError):
        await storage.get_bytes(key)


async def test_purge_expired_audio_keeps_transcript(
    session_factory: SessionFactory,
    seeded_users: dict[str, uuid.UUID],
) -> None:
    anna_id = seeded_users["anna_id"]
    storage = InMemoryStorage()
    past = datetime(2020, 1, 1, tzinfo=UTC)
    async with session_factory() as session:
        call_id, key = await _call_with_data(
            session, anna_id, storage, audio_expires_at=past
        )

    async with session_factory() as session:
        result = await purge_expired_audio(session, storage=storage)
        await session.commit()

    assert result["audio"] == 1
    async with session_factory() as session:
        assert await repositories.get_call_audio(session, call_id) is None
        # Transcript survives (only audio has a retention limit).
        assert await repositories.get_transcript(session, call_id) is not None
    with pytest.raises(StorageError):
        await storage.get_bytes(key)


async def test_purge_keeps_fresh_audio(
    session_factory: SessionFactory,
    seeded_users: dict[str, uuid.UUID],
) -> None:
    anna_id = seeded_users["anna_id"]
    storage = InMemoryStorage()
    future = datetime.now(UTC) + timedelta(days=10)
    async with session_factory() as session:
        call_id, _ = await _call_with_data(session, anna_id, storage, audio_expires_at=future)

    async with session_factory() as session:
        result = await purge_expired_audio(session, storage=storage)
        await session.commit()

    assert result["audio"] == 0
    async with session_factory() as session:
        assert await repositories.get_call_audio(session, call_id) is not None


async def test_purge_deletes_legs_and_abandoned_resumable_chunks(
    session_factory: SessionFactory,
    seeded_users: dict[str, uuid.UUID],
) -> None:
    """Every object behind a recording goes: mixed stream, legs, in-flight chunks.

    A resumable upload (``Content-Range``) stores each chunk as its own object
    until the last one arrives; an upload the client never finished must not
    leave those chunks in storage past the retention window.
    """
    anna_id = seeded_users["anna_id"]
    storage = InMemoryStorage()
    past = datetime(2020, 1, 1, tzinfo=UTC)
    async with session_factory() as session:
        call_id, mixed = await _call_with_data(
            session, anna_id, storage, audio_expires_at=past
        )
        leg = f"calls/{call_id}/operator.wav"
        chunk = f"calls/{call_id}/upload-1/part-00000"
        audio = await repositories.get_call_audio(session, call_id)
        assert audio is not None
        audio.channel_urls = {"operator": await storage.put_bytes(leg, b"leg", "audio/wav")}
        audio.pending_uploads = {
            "mixed": {
                "upload_id": "upload-1",
                "offset": 5,
                "total": 100,
                "content_type": "audio/wav",
                "parts": [{"key": chunk, "size": 5}],
            }
        }
        await session.commit()

    async with session_factory() as session:
        result = await purge_expired_audio(session, storage=storage)
        await session.commit()

    assert result == {"audio": 1, "objects": 3}
    for deleted in (mixed, leg, chunk):
        with pytest.raises(StorageError):
            await storage.get_bytes(deleted)


async def test_purge_respects_batch_limit(
    session_factory: SessionFactory,
    seeded_users: dict[str, uuid.UUID],
) -> None:
    """One pass removes at most ``limit`` recordings; ``beat`` repeats."""
    anna_id = seeded_users["anna_id"]
    storage = InMemoryStorage()
    past = datetime(2020, 1, 1, tzinfo=UTC)
    async with session_factory() as session:
        first, _ = await _call_with_data(session, anna_id, storage, audio_expires_at=past)
        second, _ = await _call_with_data(session, anna_id, storage, audio_expires_at=past)

    async with session_factory() as session:
        result = await purge_expired_audio(session, storage=storage, limit=1)
        await session.commit()
    assert result["audio"] == 1

    async with session_factory() as session:
        remaining = [
            (await repositories.get_call_audio(session, call_id)) is not None
            for call_id in (first, second)
        ]
    assert remaining.count(True) == 1
