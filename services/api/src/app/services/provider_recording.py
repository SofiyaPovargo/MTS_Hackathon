"""Provider-side call recordings: Exolve ``crr`` → object storage → ASR queue.

МТС Exolve records the conversation at the SIP-resource level and announces the
finished file with the ``crr`` progress notification (``plan.md`` §11.1). The
audio is then pulled through the Call Record API and stored like any other
recording, so the ML pipeline (§12) keeps reading from one place.

Product rules enforced here (AGENTS «Consent flow», «ML and data rules»):

- the provider recording is fetched **only** for a call our own flow recorded
  (``recording_started_at`` set, i.e. ``answered`` + consent); otherwise the
  audio is never downloaded, stored or analysed;
- an object that is already in storage short-circuits, so a re-delivered ``crr``
  is idempotent and a client upload always wins over the provider copy;
- audio is personal data: it gets a retention expiry and both the notification
  and the download are written to ``audit_log``;
- the download runs in a worker, never in the webhook — Exolve expects a fast
  acknowledgement, so the callback only remembers the record id and queues the
  job.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.infrastructure.db import repositories
from app.infrastructure.db.models import Call, CallAudio
from app.infrastructure.storage import (
    StoragePort,
    audio_suffix,
    new_audio_key,
    retention_expiry,
)
from app.integrations.recording import CallRecordingPort
from app.services.jobs import AnalysisQueuePort

logger = logging.getLogger(__name__)

#: ``CallAudio.storage_url`` marker for "the provider holds the audio": the
#: record id follows the prefix until the worker downloads the object.
RECORD_PREFIX = "provider://exolve/"

#: Stored audio lives in object storage.
STORED_PREFIX = "s3://"


def record_uid(storage_url: str) -> str | None:
    """The Exolve record id from a ``CallAudio`` placeholder, if any."""
    if storage_url.startswith(RECORD_PREFIX):
        uid = storage_url[len(RECORD_PREFIX) :].strip()
        return uid or None
    return None


class ProviderRecordingService:
    """Bridge the provider's finished recording into storage and the ML queue."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        storage: StoragePort,
        analysis: AnalysisQueuePort | None = None,
        recordings: CallRecordingPort | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._storage = storage
        self._analysis = analysis
        self._recordings = recordings

    # -- webhook side ---------------------------------------------------------

    async def mark_ready(self, call: Call, *, uid: str) -> str:
        """A ``crr`` notification arrived: remember the record and queue the fetch.

        Returns an outcome code for the webhook acknowledgement: ``queued`` (the
        worker will fetch it), ``skipped`` (audio is already in storage) or
        ``rejected`` (the call was never recorded with consent).
        """
        if call.recording_started_at is None:
            # No ``answered`` + consent in our own flow: not our recording.
            await self._audit(call, "recording.rejected", {"uid": uid})
            return "rejected"

        audio = await self._get_or_create(call)
        if audio.storage_url.startswith(STORED_PREFIX):
            return "skipped"  # the client (or an earlier job) already stored it

        audio.storage_url = f"{RECORD_PREFIX}{uid}"
        audio.expires_at = retention_expiry(self._settings)
        await self._session.flush()
        if self._analysis is not None:
            self._analysis.enqueue_recording_download(str(call.id))
        await self._audit(call, "recording.ready", {"uid": uid})
        return "queued"

    # -- worker side ----------------------------------------------------------

    async def fetch_and_store(self, call: Call) -> bool:
        """Download the announced recording into storage; ``True`` when stored.

        Idempotent: a call whose audio is already in storage (client upload or a
        previous run) is left untouched, and an in-flight resumable client upload
        is never clobbered — the client's own upload wins.
        """
        if self._recordings is None:
            logger.info("no provider recorder configured; skipping call %s", call.id)
            return False
        if call.recording_started_at is None:
            logger.info("call %s was not recorded with consent; nothing to fetch", call.id)
            return False

        audio = await repositories.get_call_audio(self._session, call.id)
        if audio is None:
            logger.info("call %s has no audio row; nothing to fetch", call.id)
            return False
        if audio.storage_url.startswith(STORED_PREFIX) or audio.pending_uploads:
            return False
        uid = record_uid(audio.storage_url)
        if uid is None:
            logger.info("call %s has no provider record id; nothing to fetch", call.id)
            return False

        recording = await self._recordings.fetch_recording(uid)
        key = new_audio_key(str(call.id), audio_suffix(recording.content_type))
        url = await self._storage.put_bytes(key, recording.data, recording.content_type)
        audio.storage_url = url
        audio.content_type = recording.content_type
        audio.expires_at = retention_expiry(self._settings)
        await self._session.flush()
        await self._audit(
            call, "recording.downloaded", {"uid": uid, "bytes": len(recording.data)}
        )
        return True

    # -- helpers --------------------------------------------------------------

    async def _get_or_create(self, call: Call) -> CallAudio:
        audio = await repositories.get_call_audio(self._session, call.id)
        if audio is None:
            audio = CallAudio(
                call_id=call.id,
                storage_url=f"{RECORD_PREFIX}pending",
                expires_at=retention_expiry(self._settings),
            )
            self._session.add(audio)
            await self._session.flush()
        return audio

    async def _audit(self, call: Call, action: str, payload: dict[str, object]) -> None:
        await repositories.record_audit(
            self._session,
            entity_type="call",
            entity_id=call.id,
            action=action,
            actor_user_id=None,  # a provider callback, not a user action
            payload=payload,
        )
