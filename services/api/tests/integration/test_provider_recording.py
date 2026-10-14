"""Provider-side recordings: Exolve ``crr`` → object storage → ASR queue.

``crr`` only announces that a record exists; the audio is downloaded by a worker
through the Call Record API. These tests pin the product rule (the provider
recording is fetched only for a call our own flow recorded with consent) and the
idempotency of a re-delivered notification.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.enums import CallDirection, CallStatus
from app.infrastructure.db.models import AuditLog, Call, CallAudio
from app.infrastructure.storage import InMemoryStorage, key_from_url
from app.integrations.recording import ProviderRecording
from app.services.provider_recording import RECORD_PREFIX, ProviderRecordingService

pytestmark = pytest.mark.integration


class FakeRecordings:
    """Deterministic stand-in for the Call Record API client."""

    def __init__(self, data: bytes = b"MP3AUDIO", content_type: str = "audio/mpeg") -> None:
        self.data = data
        self.content_type = content_type
        self.fetched: list[str] = []

    async def fetch_recording(self, uid: str) -> ProviderRecording:
        self.fetched.append(uid)
        return ProviderRecording(data=self.data, content_type=self.content_type)


class RecordingQueue:
    """Captures the download jobs the webhook side would enqueue."""

    def __init__(self) -> None:
        self.downloads: list[str] = []

    def enqueue_recording_download(self, call_id: str) -> None:
        self.downloads.append(call_id)

    def enqueue_asr(self, call_id: str) -> None:
        return None

    def enqueue_extraction(self, call_id: str) -> None:
        return None

    def enqueue_live_asr(self, call_id: str) -> None:
        return None

    def enqueue_data_deletion(self, user_id: str) -> None:
        return None

    def enqueue_reminder(self, reminder_id: str, *, eta: datetime) -> None:
        return None


async def _make_call(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    recorded: bool = True,
) -> Call:
    call = Call(
        user_id=user_id,
        external_id=f"ex-{uuid.uuid4().hex[:8]}",
        contact_phone="+79995550000",
        direction=CallDirection.inbound,
        status=CallStatus.completed,
        recording_started_at=datetime.now(UTC) if recorded else None,
    )
    session.add(call)
    await session.flush()
    return call


async def _audit_actions(
    session: AsyncSession, call_id: uuid.UUID
) -> list[tuple[str, dict[str, object]]]:
    rows = await session.execute(
        select(AuditLog).where(AuditLog.entity_id == call_id).order_by(AuditLog.created_at)
    )
    return [(row.action, row.payload or {}) for row in rows.scalars().all()]


def _service(
    session: AsyncSession,
    *,
    storage: InMemoryStorage,
    queue: RecordingQueue,
    recordings: FakeRecordings | None = None,
) -> ProviderRecordingService:
    return ProviderRecordingService(
        session,
        settings=Settings(_env_file=None),
        storage=storage,
        analysis=queue,
        recordings=recordings,
    )


async def test_crr_queues_the_download_and_remembers_the_record_id(
    session_factory: async_sessionmaker[AsyncSession],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    storage, queue = InMemoryStorage(), RecordingQueue()
    async with session_factory() as session:
        call = await _make_call(session, user_id=seeded_users["anna_id"])
        service = _service(session, storage=storage, queue=queue)

        outcome = await service.mark_ready(call, uid="7135909209505402880")
        await session.commit()

        audio = await session.get(CallAudio, (await _audio_id(session, call.id)))
        assert outcome == "queued"
        assert audio is not None
        assert audio.storage_url == f"{RECORD_PREFIX}7135909209505402880"
        assert audio.expires_at is not None
        assert queue.downloads == [str(call.id)]

        actions = await _audit_actions(session, call.id)
        assert ("recording.ready", {"uid": "7135909209505402880"}) in actions


async def test_crr_without_consent_is_rejected_and_never_queued(
    session_factory: async_sessionmaker[AsyncSession],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    storage, queue = InMemoryStorage(), RecordingQueue()
    async with session_factory() as session:
        call = await _make_call(session, user_id=seeded_users["anna_id"], recorded=False)
        service = _service(session, storage=storage, queue=queue)

        outcome = await service.mark_ready(call, uid="42")
        await session.commit()

        assert outcome == "rejected"
        assert queue.downloads == []
        assert (await _audio_id(session, call.id)) is None
        actions = await _audit_actions(session, call.id)
        assert actions == [("recording.rejected", {"uid": "42"})]


async def test_crr_is_skipped_when_the_client_already_uploaded_the_audio(
    session_factory: async_sessionmaker[AsyncSession],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    storage, queue = InMemoryStorage(), RecordingQueue()
    async with session_factory() as session:
        call = await _make_call(session, user_id=seeded_users["anna_id"])
        session.add(
            CallAudio(call_id=call.id, storage_url="s3://audio/calls/x/audio/y.ogg")
        )
        await session.flush()
        service = _service(session, storage=storage, queue=queue)

        outcome = await service.mark_ready(call, uid="99")
        await session.commit()

        assert outcome == "skipped"
        assert queue.downloads == []


async def test_fetch_and_store_downloads_into_object_storage(
    session_factory: async_sessionmaker[AsyncSession],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    storage, queue = InMemoryStorage(), RecordingQueue()
    recordings = FakeRecordings()
    async with session_factory() as session:
        call = await _make_call(session, user_id=seeded_users["anna_id"])
        service = _service(session, storage=storage, queue=queue, recordings=recordings)
        await service.mark_ready(call, uid="77")

        stored = await service.fetch_and_store(call)
        await session.commit()

        assert stored is True
        assert recordings.fetched == ["77"]
        audio = await session.get(CallAudio, await _audio_id(session, call.id))
        assert audio is not None
        assert audio.storage_url.startswith("s3://")
        assert audio.storage_url.endswith(".mp3")
        assert audio.content_type == "audio/mpeg"
        assert await storage.get_bytes(key_from_url(audio.storage_url)) == b"MP3AUDIO"

        actions = await _audit_actions(session, call.id)
        assert ("recording.downloaded", {"uid": "77", "bytes": 8}) in actions


async def test_fetch_and_store_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    storage, queue = InMemoryStorage(), RecordingQueue()
    recordings = FakeRecordings()
    async with session_factory() as session:
        call = await _make_call(session, user_id=seeded_users["anna_id"])
        service = _service(session, storage=storage, queue=queue, recordings=recordings)
        await service.mark_ready(call, uid="77")
        assert await service.fetch_and_store(call) is True
        # A re-delivered ``crr`` (or the second ASR attempt) must not download twice.
        assert await service.fetch_and_store(call) is False
        await session.commit()

    assert recordings.fetched == ["77"]


async def test_fetch_and_store_keeps_an_in_flight_client_upload(
    session_factory: async_sessionmaker[AsyncSession],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    """A resumable client upload wins over the provider copy: never clobber it."""
    storage, queue = InMemoryStorage(), RecordingQueue()
    recordings = FakeRecordings()
    async with session_factory() as session:
        call = await _make_call(session, user_id=seeded_users["anna_id"])
        session.add(
            CallAudio(
                call_id=call.id,
                storage_url=f"{RECORD_PREFIX}77",
                pending_uploads={
                    "mixed": {
                        "upload_id": "u",
                        "offset": 10,
                        "total": 20,
                        "content_type": "audio/ogg",
                        "parts": [],
                    }
                },
            )
        )
        await session.flush()
        service = _service(session, storage=storage, queue=queue, recordings=recordings)

        assert await service.fetch_and_store(call) is False
        await session.commit()

    assert recordings.fetched == []


async def test_fetch_and_store_refuses_without_consent(
    session_factory: async_sessionmaker[AsyncSession],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    storage, queue = InMemoryStorage(), RecordingQueue()
    recordings = FakeRecordings()
    async with session_factory() as session:
        call = await _make_call(session, user_id=seeded_users["anna_id"], recorded=False)
        session.add(CallAudio(call_id=call.id, storage_url=f"{RECORD_PREFIX}77"))
        await session.flush()
        service = _service(session, storage=storage, queue=queue, recordings=recordings)

        assert await service.fetch_and_store(call) is False
        await session.commit()

    assert recordings.fetched == []


async def test_fetch_and_store_needs_a_record_id(
    session_factory: async_sessionmaker[AsyncSession],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    storage, queue = InMemoryStorage(), RecordingQueue()
    recordings = FakeRecordings()
    async with session_factory() as session:
        call = await _make_call(session, user_id=seeded_users["anna_id"])
        session.add(CallAudio(call_id=call.id, storage_url="provider://exolve-rec:cs-1"))
        await session.flush()
        service = _service(session, storage=storage, queue=queue, recordings=recordings)

        assert await service.fetch_and_store(call) is False
        await session.commit()

    assert recordings.fetched == []


async def _audio_id(session: AsyncSession, call_id: uuid.UUID) -> uuid.UUID | None:
    result = await session.execute(select(CallAudio.id).where(CallAudio.call_id == call_id))
    return result.scalar_one_or_none()
