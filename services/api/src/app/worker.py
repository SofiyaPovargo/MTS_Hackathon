"""Celery worker entrypoint.

``api`` and the workers share one image with different start commands:
- celery -A app.worker worker -Q asr
- celery -A app.worker worker -Q ai
- celery -A app.worker worker -Q notifications

The ML tasks (``process_asr``, ``run_llm_extraction``) run the async pipeline
from ``app.ml.pipeline`` inside a fresh event loop (Celery tasks are sync). Each
task builds its own short-lived runtime (engine + cache + storage + adapters),
so nothing is shared across event loops. Transcription and extraction are
idempotent by ``call_id`` — a repeated job reuses the stored transcript /
extracted agreements instead of recomputing.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

from celery import Celery
from celery.schedules import crontab
from redis.asyncio import Redis

from app.config import Settings, get_settings
from app.infrastructure.cache import Cache
from app.infrastructure.db import repositories
from app.infrastructure.db.session import create_engine_and_factory
from app.infrastructure.storage import MinioStorage
from app.integrations.exolve import exolve_recording_client
from app.integrations.notifications import push_factory
from app.ml.asr.ports import StreamingASRPort
from app.ml.diarization.ports import DiarizationPort
from app.ml.extraction.ports import ExtractionPort
from app.ml.live import stream_transcribe_and_store
from app.ml.pipeline import extract_and_store, extract_incremental, transcribe_and_store
from app.ml.vad.ports import VadPort
from app.services.data_deletion import delete_user_data, purge_expired_audio
from app.services.events import EventHub
from app.services.notifications import ReminderDeliveryService
from app.services.provider_recording import ProviderRecordingService

logger = logging.getLogger(__name__)

settings = get_settings()

celery_app = Celery(
    "agreement_api",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.worker"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    task_track_started=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        # Enforce the audio retention period daily (AGENTS: limited retention).
        "purge-expired-audio": {
            "task": "purge_expired_audio",
            "schedule": crontab(hour=3, minute=0),
        },
    },
)


def _build_asr(settings: Settings) -> StreamingASRPort:
    """T-one WebSocket client (lazy import keeps the API image ML-free)."""
    from app.ml.asr.tone import ToneASRClient

    return ToneASRClient(settings.asr_ws_url)


def _build_diarizer(settings: Settings) -> DiarizationPort | None:
    """Pyannote diarizer for mono/PSTN audio; off without a HF token."""
    if not settings.hf_token:
        return None
    try:
        from app.ml.diarization.pyannote import PyannoteDiarizer
    except ImportError:  # pragma: no cover - ml extra not installed
        logger.warning("pyannote is not installed; channel roles only")
        return None
    return PyannoteDiarizer(settings.hf_token)


def _build_vad(settings: Settings) -> VadPort | None:
    """Silero VAD for trimming silence before ASR; off unless enabled."""
    if not settings.vad_enabled:
        return None
    try:
        from app.ml.vad.silero import SileroVad
    except ImportError:  # pragma: no cover - ml extra not installed
        logger.warning("silero-vad is not installed; running without VAD")
        return None
    return SileroVad(
        min_speech_ms=settings.vad_min_speech_ms,
        min_silence_ms=settings.vad_min_silence_ms,
    )


def _build_extractor(settings: Settings) -> ExtractionPort | None:
    """Instructor LLM extractor; off unless an LLM endpoint is configured."""
    if not settings.llm_enabled:
        logger.info("LLM extractor is disabled (LLM_BASE_URL/LLM_MODEL unset)")
        return None
    from app.ml.extraction.llm import InstructorLLMExtractor

    return InstructorLLMExtractor(
        api_key=settings.llm_api_key or "not-needed",
        base_url=settings.llm_base_url,
        model=settings.llm_model,
    )


@celery_app.task(queue="asr", name="process_asr")
def process_asr(call_id: str) -> dict[str, object]:
    """worker-asr: recording -> segmented transcript (roles from channels)."""
    transcribed = asyncio.run(_process_asr(call_id))
    if transcribed:
        # Hand off to worker-ai (separate queue) once the transcript exists.
        run_llm_extraction.delay(call_id)
    return {"call_id": call_id, "job": "asr", "transcribed": transcribed}


@celery_app.task(queue="ai", name="run_llm_extraction")
def run_llm_extraction(call_id: str) -> dict[str, object]:
    """worker-ai: transcript -> validated agreements + ``agreement_detected``."""
    extracted = asyncio.run(_run_llm_extraction(call_id))
    return {"call_id": call_id, "job": "ai", "agreements": extracted}


@celery_app.task(queue="asr", name="download_recording")
def download_recording(call_id: str) -> dict[str, object]:
    """worker-asr: fetch the provider's finished recording into object storage.

    Exolve ``crr`` only announces the file (plan.md §11.1); this job downloads
    it and then hands off to ASR, which is idempotent by ``call_id``.
    """
    stored = asyncio.run(_download_recording(call_id))
    if stored:
        process_asr.delay(call_id)
    return {"call_id": call_id, "job": "recording", "stored": stored}


async def _download_recording(call_id: str) -> bool:
    settings = get_settings()
    call_uuid = uuid.UUID(call_id)
    engine, factory = create_engine_and_factory(settings.database_url)
    storage = MinioStorage(settings)
    recordings = exolve_recording_client(settings)
    try:
        async with factory() as session:
            call = await repositories.get_call(session, call_uuid)
            if call is None:
                return False
            service = ProviderRecordingService(
                session, settings=settings, storage=storage, recordings=recordings
            )
            stored = await service.fetch_and_store(call)
            await session.commit()
            return stored
    finally:
        if recordings is not None:
            await recordings.aclose()
        await engine.dispose()


async def _process_asr(call_id: str) -> bool:
    settings = get_settings()
    call_uuid = uuid.UUID(call_id)
    engine, factory = create_engine_and_factory(settings.database_url)
    cache = Cache.from_settings(settings)
    try:
        events = EventHub(cache)
        storage = MinioStorage(settings)
        asr = _build_asr(settings)
        diarizer = _build_diarizer(settings)
        vad = _build_vad(settings)
        async with factory() as session:
            row = await transcribe_and_store(
                session,
                call_id=call_uuid,
                storage=storage,
                asr=asr,
                diarizer=diarizer,
                events=events,
                settings=settings,
                vad=vad,
            )
            await session.commit()
            return row is not None
    finally:
        await cache.close()
        await engine.dispose()


async def _run_llm_extraction(call_id: str) -> int:
    settings = get_settings()
    call_uuid = uuid.UUID(call_id)
    engine, factory = create_engine_and_factory(settings.database_url)
    cache = Cache.from_settings(settings)
    try:
        events = EventHub(cache)
        extractor = _build_extractor(settings)
        async with factory() as session:
            agreements = await extract_and_store(
                session,
                call_id=call_uuid,
                extractor=extractor,
                events=events,
                settings=settings,
            )
            await session.commit()
            return len(agreements)
    finally:
        await cache.close()
        await engine.dispose()


@celery_app.task(queue="asr-live", name="stream_asr")
def stream_asr(call_id: str) -> dict[str, object]:
    """worker-asr-live: live-стримы аудио -> транскрипт + ``partial_transcript``."""
    if not get_settings().live_asr_enabled:
        return {"call_id": call_id, "job": "asr-live", "skipped": "disabled"}
    segments = asyncio.run(_stream_asr(call_id))
    return {"call_id": call_id, "job": "asr-live", "segments": segments}


@celery_app.task(queue="ai-live", name="stream_extract")
def stream_extract(call_id: str) -> dict[str, object]:
    """worker-ai-live: инкрементальное извлечение по ходу разговора."""
    changed = asyncio.run(_stream_extract(call_id))
    return {"call_id": call_id, "job": "ai-live", "agreements": changed}


async def _discover_legs(redis: Redis, call_id: str, *, wait_sec: float = 3.0) -> list[str]:
    """Найти ноги звонка по ключам ``audio:call:{call_id}:*`` (короткое ожидание)."""
    pattern = f"audio:call:{call_id}:*"
    deadline = time.monotonic() + wait_sec
    while time.monotonic() < deadline:
        keys = await redis.keys(pattern)
        legs = sorted({str(key).rsplit(":", 1)[-1] for key in keys})
        if legs:
            return legs
        await asyncio.sleep(0.2)
    return []


async def _stream_asr(call_id: str) -> int:
    settings = get_settings()
    call_uuid = uuid.UUID(call_id)
    engine, factory = create_engine_and_factory(settings.database_url)
    cache = Cache.from_settings(settings)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        events = EventHub(cache)
        asr = _build_asr(settings)
        legs = await _discover_legs(redis, call_id) or ["mixed"]

        def _enqueue_extract() -> None:
            stream_extract.delay(call_id)

        async with factory() as session:
            row = await stream_transcribe_and_store(
                session,
                call_id=call_uuid,
                legs=legs,
                redis=redis,
                asr=asr,
                events=events,
                settings=settings,
                enqueue_extract=_enqueue_extract,
            )
            await session.commit()
            return len(row.segments) if row is not None and row.segments else 0
    finally:
        await redis.aclose()
        await cache.close()
        await engine.dispose()


async def _stream_extract(call_id: str) -> int:
    settings = get_settings()
    call_uuid = uuid.UUID(call_id)
    engine, factory = create_engine_and_factory(settings.database_url)
    cache = Cache.from_settings(settings)
    try:
        events = EventHub(cache)
        extractor = _build_extractor(settings)
        async with factory() as session:
            changed = await extract_incremental(
                session,
                call_id=call_uuid,
                extractor=extractor,
                events=events,
                settings=settings,
            )
            await session.commit()
            return len(changed)
    finally:
        await cache.close()
        await engine.dispose()


@celery_app.task(queue="notifications", name="send_reminder")
def send_reminder(reminder_id: str) -> dict[str, object]:
    """worker-notifications: deliver a due reminder through the push port.

    Idempotent by reminder status: a reminder that is no longer ``scheduled`` is
    left untouched, so a redelivered job cannot notify the user twice.
    """
    status = asyncio.run(_send_reminder(reminder_id))
    return {"reminder_id": reminder_id, "job": "notifications", "status": status}


async def _send_reminder(reminder_id: str) -> str:
    settings = get_settings()
    engine, factory = create_engine_and_factory(settings.database_url)
    try:
        push = push_factory(settings.push_provider)
        async with factory() as session:
            service = ReminderDeliveryService(session, push=push)
            reminder = await service.deliver(uuid.UUID(reminder_id))
            await session.commit()
            return reminder.status.value
    finally:
        await engine.dispose()


@celery_app.task(queue="notifications", name="request_data_deletion")
def request_data_deletion(user_id: str) -> dict[str, object]:
    """Purge a user's personal data (audio, calls, tasks) after deletion request."""
    result = asyncio.run(_delete_user_data(user_id))
    return {"user_id": user_id, "job": "data_deletion", **result}


@celery_app.task(queue="notifications", name="purge_expired_audio")
def purge_expired_audio_task() -> dict[str, object]:
    """Celery-beat: drop audio recordings past their retention expiry."""
    result = asyncio.run(_purge_expired_audio())
    return {"job": "retention", **result}


async def _delete_user_data(user_id: str) -> dict[str, int]:
    settings = get_settings()
    engine, factory = create_engine_and_factory(settings.database_url)
    try:
        storage = MinioStorage(settings)
        async with factory() as session:
            result = await delete_user_data(
                session, user_id=uuid.UUID(user_id), storage=storage
            )
            await session.commit()
            return result
    finally:
        await engine.dispose()


async def _purge_expired_audio() -> dict[str, int]:
    settings = get_settings()
    engine, factory = create_engine_and_factory(settings.database_url)
    try:
        storage = MinioStorage(settings)
        async with factory() as session:
            result = await purge_expired_audio(session, storage=storage)
            await session.commit()
            return result
    finally:
        await engine.dispose()


def main() -> None:
    celery_app.worker_main(
        [
            "-A",
            "app.worker",
            "worker",
            "-Q",
            "asr,ai,asr-live,ai-live,notifications",
            "-l",
            "info",
        ]
    )
