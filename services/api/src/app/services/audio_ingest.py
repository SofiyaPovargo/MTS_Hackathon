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

Network loss is expected (AGENTS «Calls»: a dropped connection must not lose
what was already recorded). The endpoint therefore accepts **resumable chunked
uploads**: the client sends ``Content-Range: bytes <start>-<end>/<total>`` and
each chunk is written to storage *immediately*, so the offset acknowledged in
the response is durable. A retry of an already-stored chunk is idempotent, and a
client that reconnects (Wi-Fi / 4G / weak signal) resumes from the offset the
server reports instead of re-sending earlier audio. The chunks are assembled
into one object once the last one arrives, then deleted.
"""

from __future__ import annotations

import logging
import uuid
from typing import TypedDict, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.domain.errors import (
    Conflict,
    PayloadTooLarge,
    UploadOffsetMismatch,
    ValidationFailed,
)
from app.infrastructure.db import repositories
from app.infrastructure.db.models import Call, CallAudio, User
from app.infrastructure.storage import (
    StorageError,
    StoragePort,
    audio_suffix,
    chunk_key,
    key_from_url,
    new_audio_key,
    retention_expiry,
)
from app.services.jobs import AnalysisQueuePort

logger = logging.getLogger(__name__)

#: Per-leg uploads for channel-separated recordings (VoIP). Both are needed
#: before the pipeline can run without diarization.
LEGS = ("operator", "client")

#: Upload slot for the mixed stream (``role`` is ``None`` on the wire).
MIXED = "mixed"


class UploadPart(TypedDict):
    """One durably stored chunk of an in-flight upload."""

    key: str
    size: int


class UploadSession(TypedDict):
    """In-flight chunked upload state for one role (persisted as JSONB)."""

    upload_id: str
    offset: int
    total: int
    content_type: str
    parts: list[UploadPart]


def normalize_content_type(content_type: str | None) -> str:
    """Strip parameters and case from a ``Content-Type`` header value."""
    return (content_type or "application/octet-stream").split(";", 1)[0].strip().lower()


def parse_content_range(value: str) -> tuple[int, int, int]:
    """Parse ``bytes <start>-<end>/<total>`` into ``(start, end, total)``.

    Only the closed-range form the resumable client sends is accepted; anything
    malformed is a client error (422), never a silent whole-object upload.
    """
    prefix, _, spec = value.partition(" ")
    if prefix.strip().lower() != "bytes":
        raise ValidationFailed(f"unsupported Content-Range unit: {value!r}")
    range_part, sep, total_part = spec.partition("/")
    start_part, dash, end_part = range_part.partition("-")
    if sep != "/" or dash != "-" or not (start_part.isdigit() and end_part.isdigit()):
        raise ValidationFailed(f"malformed Content-Range: {value!r}")
    if not total_part.isdigit():
        raise ValidationFailed(f"malformed Content-Range total: {value!r}")
    start, end, total = int(start_part), int(end_part), int(total_part)
    if total <= 0 or start > end or end >= total:
        raise ValidationFailed(f"invalid Content-Range bounds: {value!r}")
    return start, end, total


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
        self._check_recording(call)
        self._check_role(role)
        self._check_upload(upload)

        audio = await self._get_or_create(call)
        # A whole-object upload supersedes any half-finished chunked upload.
        dropped = self._drop_session(audio, role)
        superseded = self._current_urls(audio)

        key = new_audio_key(str(call.id), audio_suffix(upload.content_type))
        url = await self._storage.put_bytes(key, upload.data, upload.content_type)
        self._apply_object(
            audio, role=role, url=url, content_type=upload.content_type, duration_sec=duration_sec
        )
        await self._session.flush()
        await self._delete_urls(superseded - self._current_urls(audio))
        await self._delete_keys(dropped)

        return await self._finish_upload(
            actor, call, audio, role=role, size=len(upload.data)
        )

    async def ingest_chunk(
        self,
        actor: User,
        call: Call,
        *,
        upload: AudioUpload,
        role: str | None,
        start: int,
        total: int,
        duration_sec: int | None = None,
        restart: bool = False,
    ) -> tuple[CallAudio, bool, int]:
        """Append one chunk of a resumable upload; returns ``(audio, queued, offset)``.

        ``offset`` is the durable byte count for this role after the request: a
        client that loses its connection resumes from there. Re-sending an
        already-stored chunk is accepted without storing it twice.
        """
        self._check_recording(call)
        self._check_role(role)
        self._check_upload(upload)
        if total > self._limit_bytes:
            raise PayloadTooLarge(self._limit_bytes)
        end = start + len(upload.data) - 1
        if end >= total:
            raise ValidationFailed(
                f"chunk of {len(upload.data)} bytes overruns the declared total {total}"
            )

        audio = await self._get_or_create(call)
        slot = role or MIXED
        sessions = self._load_sessions(audio)
        session: UploadSession | None = None if restart else sessions.get(slot)
        stale_keys: list[str] = []
        if restart:
            # The client re-records from scratch: drop the abandoned chunks.
            abandoned = sessions.get(slot)
            if abandoned is not None:
                stale_keys = [part["key"] for part in abandoned["parts"]]
        if session is not None and (
            session["total"] != total or session["content_type"] != upload.content_type
        ):
            # A different recording for the same role: only a fresh start is legal.
            if start != 0:
                raise UploadOffsetMismatch(session["offset"], session["total"])
            stale_keys = [part["key"] for part in session["parts"]]
            session = None

        if session is None:
            if start != 0:
                raise UploadOffsetMismatch(0, total)
            session = {
                "upload_id": uuid.uuid4().hex,
                "offset": 0,
                "total": total,
                "content_type": upload.content_type,
                "parts": [],
            }

        offset = session["offset"]
        if end < offset:
            return audio, False, offset  # a retried chunk: already durable
        if start != offset:
            raise UploadOffsetMismatch(offset, session["total"])

        key = chunk_key(str(call.id), session["upload_id"], len(session["parts"]))
        await self._storage.put_bytes(key, upload.data, upload.content_type)
        session["offset"] = end + 1
        session["parts"] = [*session["parts"], {"key": key, "size": len(upload.data)}]
        sessions[slot] = session
        self._store_sessions(audio, sessions)
        await self._session.flush()
        await self._delete_keys(stale_keys)
        await self._audit(actor, call, role=role, size=len(upload.data), queued=False)

        if session["offset"] < session["total"]:
            return audio, False, session["offset"]

        queued = await self._finalize(actor, call, audio, session=session, role=role,
                                      duration_sec=duration_sec)
        return audio, queued, session["total"]

    async def _finalize(
        self,
        actor: User,
        call: Call,
        audio: CallAudio,
        *,
        session: UploadSession,
        role: str | None,
        duration_sec: int | None,
    ) -> bool:
        """Assemble the stored chunks into the final object and queue ASR."""
        parts = session["parts"]
        content_type = session["content_type"]
        data = b"".join([await self._storage.get_bytes(part["key"]) for part in parts])

        superseded = self._current_urls(audio)
        key = new_audio_key(str(call.id), audio_suffix(content_type))
        url = await self._storage.put_bytes(key, data, content_type)
        self._apply_object(
            audio, role=role, url=url, content_type=content_type, duration_sec=duration_sec
        )
        sessions = self._load_sessions(audio)
        sessions.pop(role or MIXED, None)
        self._store_sessions(audio, sessions)
        await self._session.flush()

        await self._delete_urls(superseded - self._current_urls(audio))
        await self._delete_keys([part["key"] for part in parts])

        _, queued = await self._finish_upload(actor, call, audio, role=role, size=len(data))
        return queued

    # -- validation -----------------------------------------------------------

    @staticmethod
    def _check_recording(call: Call) -> None:
        if call.recording_started_at is None:
            raise Conflict("call was not recorded")

    @staticmethod
    def _check_role(role: str | None) -> None:
        if role is not None and role not in LEGS:
            raise ValidationFailed(f"leg must be one of {LEGS}")

    def _check_upload(self, upload: AudioUpload) -> None:
        if not upload.data:
            raise ValidationFailed("empty audio upload")
        if not self._accepts(upload.content_type):
            raise ValidationFailed(f"unsupported audio content type: {upload.content_type}")
        if len(upload.data) > self._limit_bytes:
            raise PayloadTooLarge(self._limit_bytes)

    # -- helpers --------------------------------------------------------------

    async def _finish_upload(
        self, actor: User, call: Call, audio: CallAudio, *, role: str | None, size: int
    ) -> tuple[CallAudio, bool]:
        complete = self._is_complete(audio)
        if complete and self._analysis is not None:
            self._analysis.enqueue_asr(str(call.id))
        await self._audit(actor, call, role=role, size=size, queued=complete)
        return audio, complete

    def _apply_object(
        self,
        audio: CallAudio,
        *,
        role: str | None,
        url: str,
        content_type: str,
        duration_sec: int | None,
    ) -> None:
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

        audio.content_type = content_type
        if duration_sec is not None:
            audio.duration_sec = duration_sec
        audio.expires_at = retention_expiry(self._settings)

    @staticmethod
    def _load_sessions(audio: CallAudio) -> dict[str, UploadSession]:
        return cast("dict[str, UploadSession]", dict(audio.pending_uploads or {}))

    @staticmethod
    def _store_sessions(audio: CallAudio, sessions: dict[str, UploadSession]) -> None:
        audio.pending_uploads = cast("dict[str, object] | None", dict(sessions) or None)

    def _drop_session(self, audio: CallAudio, role: str | None) -> list[str]:
        """Discard an in-flight chunked upload for the role; return its part keys."""
        sessions = self._load_sessions(audio)
        session = sessions.pop(role or MIXED, None)
        if session is None:
            return []
        self._store_sessions(audio, sessions)
        return [part["key"] for part in session["parts"]]

    @staticmethod
    def _current_urls(audio: CallAudio) -> set[str]:
        return {audio.storage_url, *(audio.channel_urls or {}).values()}

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

    async def _delete_urls(self, urls: set[str]) -> None:
        for url in urls:
            if not url.startswith("s3://"):
                continue
            try:
                await self._storage.delete(key_from_url(url))
            except StorageError:  # pragma: no cover - cleanup is best-effort
                logger.warning("could not delete superseded audio object: %s", url)

    async def _delete_keys(self, keys: list[str]) -> None:
        for key in keys:
            try:
                await self._storage.delete(key)
            except StorageError:  # pragma: no cover - cleanup is best-effort
                logger.warning("could not delete stored audio chunk: %s", key)

    async def _audit(
        self, actor: User, call: Call, *, role: str | None, size: int, queued: bool
    ) -> None:
        await repositories.record_audit(
            self._session,
            entity_type="call",
            entity_id=call.id,
            action="audio.uploaded",
            actor_user_id=actor.id,
            payload={"role": role or MIXED, "bytes": size, "analysis_queued": queued},
        )
