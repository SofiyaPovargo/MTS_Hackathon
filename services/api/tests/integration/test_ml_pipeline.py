"""ML pipeline end to end: channels -> transcript -> agreements -> events.

Runs against containers (PostgreSQL + Redis). The ASR/diarization/LLM adapters
are fakes, so the test is about roles, persistence, idempotency and the trigger —
not about model quality.
"""

from __future__ import annotations

import io
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from typing import Any

import httpx
import numpy as np
import pytest
import soundfile as sf  # type: ignore[import-untyped]
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.domain.commitment import Commitment
from app.domain.enums import AgreementStatus, CallDirection, CallStatus, Owner
from app.infrastructure.cache import Cache
from app.infrastructure.db import repositories
from app.infrastructure.db.models import Call, CallAudio
from app.infrastructure.storage import InMemoryStorage
from app.ml.asr.ports import TextPhrase
from app.ml.diarization.ports import SpeakerSegment
from app.ml.live import stream_transcribe_and_store
from app.ml.pipeline import extract_and_store, transcribe_and_store
from app.services.events import CallEventMessage
from app.services.live_audio import LiveAudioRelay
from tests.integration.conftest import USER_PHONES, auth_headers, create_call, login

pytestmark = pytest.mark.integration

SessionFactory = async_sessionmaker[AsyncSession]


def _wav(samples: np.ndarray, sample_rate: int = 8_000) -> bytes:
    buffer = io.BytesIO()
    sf.write(buffer, samples, sample_rate, format="WAV")
    return buffer.getvalue()


class FakeASR:
    """Отдаёт фразы нога за ногой: первая нога — оператор, вторая — клиент."""

    def __init__(self) -> None:
        self.calls = 0

    async def transcribe(self, pcm_int16: bytes) -> list[TextPhrase]:
        self.calls += 1
        if self.calls == 1:
            return [TextPhrase("Я пришлю договор до пятницы.", 2.0, 5.0)]
        return [TextPhrase("Хорошо, жду.", 0.0, 1.0)]


class FakeDiarizer:
    def __init__(self, segments: list[SpeakerSegment] | None = None) -> None:
        self._segments = segments or []
        self.calls = 0

    def diarize(self, audio_path: Any) -> list[SpeakerSegment]:
        self.calls += 1
        return self._segments


class FakeExtractor:
    def __init__(self, commitment: Commitment) -> None:
        self._commitment = commitment
        self.calls = 0

    async def extract(self, context: Any) -> list[Commitment]:
        self.calls += 1
        return [self._commitment.model_copy(deep=True)]


class FakeEvents:
    def __init__(self) -> None:
        self.messages: list[CallEventMessage] = []

    async def emit(self, message: CallEventMessage) -> None:
        self.messages.append(message)


class CapturingQueue:
    def __init__(self) -> None:
        self.asr: list[str] = []

    def enqueue_asr(self, call_id: str) -> None:
        self.asr.append(call_id)

    def enqueue_extraction(self, call_id: str) -> None:
        return None

    def enqueue_live_asr(self, call_id: str) -> None:
        return None


class FakeStreamingASR:
    """Consumes the stream and emits one phrase (live path double)."""

    def __init__(self, phrase: TextPhrase) -> None:
        self._phrase = phrase

    async def transcribe(self, pcm_int16: bytes) -> list[TextPhrase]:
        return []

    async def stream(
        self, chunks: AsyncIterator[bytes], on_phrase: Any
    ) -> None:
        async for _chunk in chunks:
            pass
        await on_phrase(self._phrase)


async def _recorded_call(
    session: AsyncSession, user_id: uuid.UUID, storage: InMemoryStorage
) -> Call:
    call = Call(
        user_id=user_id,
        direction=CallDirection.outbound,
        contact_phone="+79990000000",
        contact_name="Игорь Владимирович",
        status=CallStatus.recording,
        started_at=datetime(2026, 10, 5, 9, 0, tzinfo=UTC),
    )
    session.add(call)
    await session.flush()

    tone = np.full(8_000, 0.1, dtype=np.float32)
    operator_url = await storage.put_bytes(
        f"calls/{call.id}/operator.wav", _wav(tone), "audio/wav"
    )
    client_url = await storage.put_bytes(f"calls/{call.id}/client.wav", _wav(tone), "audio/wav")
    session.add(
        CallAudio(
            call_id=call.id,
            storage_url=operator_url,
            content_type="audio/wav",
            channel_urls={"operator": operator_url, "client": client_url},
        )
    )
    await session.flush()
    return call


async def test_pipeline_roles_persistence_and_idempotency(
    session_factory: SessionFactory,
    seeded_users: dict[str, uuid.UUID],
) -> None:
    settings = get_settings()
    storage = InMemoryStorage()
    asr = FakeASR()
    diarizer = FakeDiarizer()
    events = FakeEvents()
    commitment = Commitment(
        type="promise",
        title="Прислать договор",
        owner=Owner.counterparty,
        due_date=date(2026, 10, 9),
        source_quote="Я пришлю договор до пятницы.",
        audio_start=2.0,
        audio_end=5.0,
        confidence=0.9,
    )
    extractor = FakeExtractor(commitment)

    async with session_factory() as session:
        call = await _recorded_call(session, seeded_users["anna_id"], storage)
        await session.commit()
        call_id = call.id

    # worker-asr: роли берутся из каналов, диаризация не вызывается.
    async with session_factory() as session:
        row = await transcribe_and_store(
            session,
            call_id=call_id,
            storage=storage,
            asr=asr,
            diarizer=diarizer,
            events=events,
            settings=settings,
        )
        await session.commit()
    assert row is not None
    assert row.role_source == "channel"
    assert [segment["speaker"] for segment in row.segments or []] == ["client", "operator"]
    assert asr.calls == 2
    assert diarizer.calls == 0
    assert any(message.event == "partial_transcript" for message in events.messages)

    # Повторная обработка того же аудио — no-op (транскрипт переиспользован).
    async with session_factory() as session:
        await transcribe_and_store(
            session,
            call_id=call_id,
            storage=storage,
            asr=asr,
            diarizer=diarizer,
            events=events,
            settings=settings,
        )
        await session.commit()
    assert asr.calls == 2

    # worker-ai: валидированные договорённости + событие.
    async with session_factory() as session:
        created = await extract_and_store(
            session, call_id=call_id, extractor=extractor, events=events, settings=settings
        )
        await session.commit()
    assert len(created) == 1
    assert created[0].status is AgreementStatus.detected
    assert created[0].owner is Owner.counterparty
    assert extractor.calls == 1
    assert any(message.event == "agreement_detected" for message in events.messages)

    # Итог звонка (§9) собран детерминированно из валидированных договорённостей.
    async with session_factory() as session:
        call_row = await repositories.get_call(session, call_id)
        assert call_row is not None and call_row.summary
        assert "Прислать договор" in call_row.summary
        assert "на клиента" in call_row.summary

    # Повторное извлечение — no-op (LLM не вызывается снова).
    async with session_factory() as session:
        again = await extract_and_store(
            session, call_id=call_id, extractor=extractor, events=events, settings=settings
        )
        assert len(again) == 1
    assert extractor.calls == 1


async def test_analyze_endpoint_queues_after_recording(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    session_factory: SessionFactory,
    seeded_users: dict[str, uuid.UUID],
) -> None:
    app, client = app_and_client
    anna = await login(client, USER_PHONES["anna"])
    headers = auth_headers(str(anna["access_token"]))
    call = await create_call(client, headers)
    call_id = uuid.UUID(str(call["id"]))

    # Звонок без записи (не было answered + consent) в анализ не уходит.
    blocked = await client.post(f"/api/calls/{call_id}/analyze", headers=headers)
    assert blocked.status_code == 409, blocked.text

    # Эмулируем наличие записи (в реальном flow ставится после consent).
    async with session_factory() as session:
        record = await repositories.get_call(session, call_id)
        assert record is not None
        record.recording_started_at = datetime.now(UTC)
        await session.commit()

    queue = CapturingQueue()
    app.state.analysis_queue = queue
    response = await client.post(f"/api/calls/{call_id}/analyze", headers=headers)
    assert response.status_code == 202, response.text
    assert response.json() == {"call_id": str(call_id), "status": "queued"}
    assert queue.asr == [str(call_id)]


async def _live_call(session: AsyncSession, user_id: uuid.UUID) -> Call:
    call = Call(
        user_id=user_id,
        direction=CallDirection.inbound,
        contact_phone="+79990000001",
        contact_name="Клиент",
        status=CallStatus.in_progress,
        started_at=datetime(2026, 10, 5, 9, 0, tzinfo=UTC),
        recording_started_at=datetime(2026, 10, 5, 9, 0, 5, tzinfo=UTC),
    )
    session.add(call)
    await session.flush()
    return call


async def test_live_stream_persists_transcript_and_roles(
    session_factory: SessionFactory,
    seeded_users: dict[str, uuid.UUID],
) -> None:
    settings = get_settings()
    cache = Cache.from_settings(settings)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    relay = LiveAudioRelay(cache)

    async with session_factory() as session:
        call = await _live_call(session, seeded_users["anna_id"])
        await session.commit()
        call_id = call.id

    frame = np.zeros(2_400, dtype=np.int16).tobytes()
    for leg in ("operator", "client"):
        await relay.push(str(call_id), leg, frame)
        await relay.end(str(call_id), leg)

    events = FakeEvents()
    asr = FakeStreamingASR(TextPhrase("Я пришлю договор до пятницы.", 1.0, 2.0))
    queued: list[str] = []

    try:
        async with session_factory() as session:
            row = await stream_transcribe_and_store(
                session,
                call_id=call_id,
                legs=["operator", "client"],
                redis=redis,
                asr=asr,
                events=events,
                settings=settings,
                enqueue_extract=lambda: queued.append(str(call_id)),
            )
            await session.commit()
    finally:
        await redis.aclose()
        await cache.close()

    assert row is not None
    assert row.status == "done"
    assert row.role_source == "channel"
    assert {segment["speaker"] for segment in row.segments or []} == {"operator", "client"}
    assert any(message.event == "partial_transcript" for message in events.messages)
    assert queued == [str(call_id)]  # финальный extraction поставлен
