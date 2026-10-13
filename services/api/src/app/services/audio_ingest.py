"""Client audio ingest: the app uploads the recorded call audio.

МТС Exolve (plan.md §11.1) exposes no server-side media stream, so after the
call the mobile client uploads the SDK audio: the mixed stream (default) or the
two per-leg tracks. The bytes are written to object storage, the ``call_audio``
row created at ``recording.started`` is filled in, and ASR is queued once the
recording is complete.

Product rules enforced here:

- recording is impossible without ``answered`` + consent, so a call whose
  ``recording_started_at`` is unset is refused (the storage-side half of the
  consent gate);
- audio is capped in size and validated by content type;
- audio is personal data: every object carries a retention expiry, replaced or
  superseded objects are deleted so abandoned copies never linger, and only the
  call owner can upload.
"""

from __future__ import annotations

import logging
import mimetypes

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.domain.errors import Conflict, PayloadTooLarge, ValidationFailed
from app.infrastructure.db import repositories
from app.infrastructure.db.models import Call, CallAudio, User
from app.infrastructure.storage import (
    StorageError,
    StoragePort,
    key_from_url,
    new_audio_key,
    retention_expiry,
)
from app.services.jobs import AnalysisQueuePort

logger = logging.getLogger(__name__)

#: Per-leg uploads for channel-separated recordings (VoIP). Both are needed
#: before the pipeline can run without diarization.
LEGS = ("operator", "client")

#: Container extensions per content type. The ML decoder reads the object with
#: libsndfile, so wav/ogg/opus/flac are the practically supported containers;
#: anything else still lands in storage but as a generic ``.bin`` object.
_SUFFIXES = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/ogg": ".ogg",
    "audio/opus": ".ogg",
    "audio/flac": ".flac",
    "audio/x-flac": ".flac",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/webm": ".webm",
    "audio/aac": ".aac",
    "audio/3gpp": ".3gp",
}


def normalize_content_type(content_type: str | None) -> str:
    """Strip parameters and case from a ``Content-Type`` header value."""
    return (content_type or "application/octet-stream").split(";", 1)[0].strip().lower()


def _suffix(content_type: str) -> str:
    if content_type in _SUFFIXES:
        return _SUFFIXES[content_type]
    guessed = mimetypes.guess_extension(content_type)
    return guessed if guessed and guessed.startswith(".") else ".bin"


class AudioUpload:
    """One raw audio object as received from the client."""

    __slots__ = ("content_type", "data")

    def __init__(self, data: bytes, content_type: str | None) -> None:
        self.data = data
        self.content_type = normalize_content_type(content_type)


class AudioIngestService:
    """Store a call recording and hand it to the ML pipeline."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        storage: StoragePort,
        analysis: AnalysisQueuePort | None,
        settings: Settings,
    ) -> None:
        self._session = session
        self._storage = storage
        self._analysis = analysis
        self._settings = settings

    @property
    def _limit_bytes(self) -> int:
        return self._settings.max_audio_upload_mb * 1024 * 1024

    def check_declared_size(self, content_length: str | None) -> None:
        """Fail fast on an oversized upload before buffering its body."""
        if (
            content_length is not None
            and content_length.isdigit()
            and int(content_length) > self._limit_bytes
        ):
            raise PayloadTooLarge(self._limit_bytes)

    async def ingest(
        self,
        actor: User,
        call: Call,
        *,
        upload: AudioUpload,
        role: str | None = None,
        duration_sec: int | None = None,
    ) -> tuple[CallAudio, bool]:
        """Store one object (``role=None`` = mixed) and queue ASR when complete.

        Returns the updated ``call_audio`` row and whether ASR was enqueued.
        Re-uploading a role replaces the previous object (and deletes it), so
        reprocessing the same audio stays idempotent.
        """
        if call.recording_started_at is None:
            raise Conflict("call was not recorded")
        if role is not None and role not in LEGS:
            raise ValidationFailed(f"leg must be one of {LEGS}")
        if not upload.data:
            raise ValidationFailed("empty audio upload")
        if not self._accepts(upload.content_type):
            raise ValidationFailed(f"unsupported audio content type: {upload.content_type}")
        if len(upload.data) > self._limit_bytes:
            raise PayloadTooLarge(self._limit_bytes)

        audio = await self._get_or_create(call)
        superseded = {audio.storage_url, *(audio.channel_urls or {}).values()}

        key = new_audio_key(str(call.id), _suffix(upload.content_type))
        url = await self._storage.put_bytes(key, upload.data, upload.content_type)

        if role is None:
            audio.storage_url = url
            audio.channel_urls = None
        else:
            channels = dict(audio.channel_urls or {})
            channels[role] = url
            audio.channel_urls = channels
            # Keep a concrete primary object so a lone uploaded leg is still
            # readable; with both legs present the pipeline uses the legs.
            audio.storage_url = channels.get("operator") or channels.get("client") or url

        audio.content_type = upload.content_type
        if duration_sec is not None:
            audio.duration_sec = duration_sec
        audio.expires_at = retention_expiry(self._settings)
        await self._session.flush()

        current = {audio.storage_url, *(audio.channel_urls or {}).values()}
        for stale in superseded - current:
            await self._delete_object(stale)

        complete = self._is_complete(audio)
        if complete and self._analysis is not None:
            self._analysis.enqueue_asr(str(call.id))

        await repositories.record_audit(
            self._session,
            entity_type="call",
            entity_id=call.id,
            action="audio.uploaded",
            actor_user_id=actor.id,
            payload={
                "role": role or "mixed",
                "bytes": len(upload.data),
                "content_type": upload.content_type,
                "analysis_queued": complete,
            },
        )
        return audio, complete

    @staticmethod
    def _accepts(content_type: str) -> bool:
        return content_type == "application/octet-stream" or content_type.startswith("audio/")

    @staticmethod
    def _is_complete(audio: CallAudio) -> bool:
        channels = audio.channel_urls or {}
        if channels.get("operator") and channels.get("client"):
            return True
        # No legs: a single mixed object is a complete recording.
        return not channels and audio.storage_url.startswith("s3://")

    async def _get_or_create(self, call: Call) -> CallAudio:
        audio = await repositories.get_call_audio(self._session, call.id)
        if audio is None:
            # No provider-side placeholder row (manual/demo path): start one.
            audio = CallAudio(
                call_id=call.id,
                storage_url=f"provider://{call.external_id or call.id}",
                expires_at=retention_expiry(self._settings),
            )
            self._session.add(audio)
        return audio

    async def _delete_object(self, url: str) -> None:
        if not url.startswith("s3://"):
            return
        try:
            await self._storage.delete(key_from_url(url))
        except StorageError:  # pragma: no cover - storage is best-effort cleanup
            logger.warning("could not delete superseded audio object: %s", url)
