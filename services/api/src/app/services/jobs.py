"""Enqueue ML jobs on the Celery queues without importing the worker module.

The API image installs runtime dependencies only (no ML extra), so it must not
import ``app.worker`` — that module pulls in the ML pipeline (numpy, torch, …).
Celery's ``send_task`` publishes by task name over the broker, so the API can
trigger ASR / extraction while staying light.
"""

from __future__ import annotations

import logging
from typing import Protocol

from celery import Celery

from app.config import Settings

logger = logging.getLogger(__name__)

ASR_TASK = "process_asr"
AI_TASK = "run_llm_extraction"
LIVE_ASR_TASK = "stream_asr"
DATA_DELETION_TASK = "request_data_deletion"
RECORDING_TASK = "download_recording"


class AnalysisQueuePort(Protocol):
    """Enqueue the asynchronous analysis steps for a recorded call."""

    def enqueue_asr(self, call_id: str) -> None: ...
    def enqueue_extraction(self, call_id: str) -> None: ...
    def enqueue_live_asr(self, call_id: str) -> None: ...
    def enqueue_data_deletion(self, user_id: str) -> None: ...
    def enqueue_recording_download(self, call_id: str) -> None: ...


class NullAnalysisQueue:
    """No-op queue so broker-less runs (unit tests, local) keep working."""

    def enqueue_asr(self, call_id: str) -> None:
        return None

    def enqueue_extraction(self, call_id: str) -> None:
        return None

    def enqueue_live_asr(self, call_id: str) -> None:
        return None

    def enqueue_data_deletion(self, user_id: str) -> None:
        return None

    def enqueue_recording_download(self, call_id: str) -> None:
        return None


class CeleryAnalysisQueue:
    """Publish to the ``asr`` / ``ai`` queues, best-effort.

    A missing broker must not break the API: the call already succeeded, so
    enqueue failures are logged and swallowed.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._app: Celery | None = None

    def _client(self) -> Celery:
        if self._app is None:
            self._app = Celery(
                "agreement_api_client",
                broker=self._settings.redis_url,
                backend=self._settings.redis_url,
            )
        return self._app

    def enqueue_asr(self, call_id: str) -> None:
        self._send(ASR_TASK, "asr", call_id)

    def enqueue_extraction(self, call_id: str) -> None:
        self._send(AI_TASK, "ai", call_id)

    def enqueue_live_asr(self, call_id: str) -> None:
        self._send(LIVE_ASR_TASK, "asr-live", call_id)

    def enqueue_data_deletion(self, user_id: str) -> None:
        self._send(DATA_DELETION_TASK, "notifications", user_id)

    def enqueue_recording_download(self, call_id: str) -> None:
        self._send(RECORDING_TASK, "asr", call_id)

    def _send(self, task: str, queue: str, call_id: str) -> None:
        try:
            self._client().send_task(task, args=[call_id], queue=queue)
        except Exception:  # best-effort trigger
            logger.warning("could not enqueue %s for call %s", task, call_id, exc_info=True)
