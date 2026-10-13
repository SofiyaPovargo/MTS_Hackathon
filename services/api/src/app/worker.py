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
import uuid

from celery import Celery

from app.config import Settings, get_settings
from app.infrastructure.cache import Cache
from app.infrastructure.db.session import create_engine_and_factory
from app.infrastructure.storage import MinioStorage
from app.ml.asr.ports import ASRPort
from app.ml.diarization.ports import DiarizationPort
from app.ml.extraction.ports import ExtractionPort
from app.ml.pipeline import extract_and_store, transcribe_and_store
from app.services.events import EventHub

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
)


def _build_asr(settings: Settings) -> ASRPort:
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
        async with factory() as session:
            row = await transcribe_and_store(
                session,
                call_id=call_uuid,
                storage=storage,
                asr=asr,
                diarizer=diarizer,
                events=events,
                settings=settings,
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


@celery_app.task(queue="notifications", name="send_reminder")
def send_reminder(reminder_id: str) -> dict[str, object]:
    """Stage 7/9: send a reminder through the RemindersPort (never skipped)."""
    return {"reminder_id": reminder_id, "job": "notifications", "implemented": False}


@celery_app.task(queue="notifications", name="request_data_deletion")
def request_data_deletion(user_id: str) -> dict[str, object]:
    """Consume the data-deletion queue: purge audio and transcripts for a user."""
    return {"user_id": user_id, "job": "data_deletion", "implemented": False}


def main() -> None:
    celery_app.worker_main(["-A", "app.worker", "worker", "-Q", "asr,ai,notifications", "-l", "info"])
