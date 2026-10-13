"""Celery worker entrypoint.

``api`` and the workers share one image with different start commands:
- celery -A app.worker worker -Q asr
- celery -A app.worker worker -Q ai
- celery -A app.worker worker -Q notifications

The ML pipeline (ASR / LLM) is implemented in stage 6; the tasks below are
explicit placeholders that signal which jobs exist and keep the queue healthy.
"""

from __future__ import annotations

from celery import Celery

from app.config import get_settings

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


@celery_app.task(queue="asr", name="process_asr")
def process_asr(call_id: str) -> dict[str, object]:
    """Stage 6: media stream -> VAD/chunking -> diarization -> ASR."""
    return {"call_id": call_id, "job": "asr", "implemented": False}


@celery_app.task(queue="ai", name="run_llm_extraction")
def run_llm_extraction(call_id: str) -> dict[str, object]:
    """Stage 6: transcript -> LLM -> validated Commitment -> Agreement Service."""
    return {"call_id": call_id, "job": "ai", "implemented": False}


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