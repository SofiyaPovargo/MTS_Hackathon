"""Privacy: real data deletion and audio retention enforcement.

- ``delete_user_data`` — the "user requested deletion" flow (AGENTS.md: consent
  withdrawal + data deletion is a real flow, not "later"): removes the user's
  audio objects from object storage and their calls (which cascade to
  transcripts, agreements, extractions and edits) and tasks.
- ``purge_expired_audio`` — enforces the audio retention period: objects whose
  ``expires_at`` has passed are deleted from storage and their rows removed. The
  transcript is kept (only audio has a limited retention per AGENTS.md).

Both flows delete *every* object behind a recording: the mixed stream, the legs
of a split call, and the chunks of a resumable upload the client never finished
(``call_audio.pending_uploads``). A dropped connection must not leave personal
data in storage forever.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db import repositories
from app.infrastructure.db.models import Call, CallAudio, Task
from app.infrastructure.storage import StorageError, StoragePort, key_from_url

logger = logging.getLogger(__name__)

#: How many expired rows one retention pass handles; ``beat`` repeats.
PURGE_BATCH = 500


def _audio_keys(audio: CallAudio) -> set[str]:
    """Every stored object behind a recording: mixed stream, legs, chunks."""
    keys: set[str] = set()
    if audio.storage_url.startswith("s3://"):
        keys.add(key_from_url(audio.storage_url))
    for url in (audio.channel_urls or {}).values():
        if url.startswith("s3://"):
            keys.add(key_from_url(url))
    # A resumable upload stores each chunk as its own object until the last one
    # arrives; an upload abandoned mid-way must not leave those chunks behind.
    for session_state in (audio.pending_uploads or {}).values():
        if not isinstance(session_state, dict):
            continue
        parts = session_state.get("parts", [])
        if not isinstance(parts, list):
            continue
        for part in parts:
            if isinstance(part, dict) and "key" in part:
                keys.add(str(part["key"]))
    return keys


async def _delete_objects(storage: StoragePort, keys: set[str]) -> int:
    deleted = 0
    for key in keys:
        try:
            await storage.delete(key)
            deleted += 1
        except StorageError:  # best-effort: DB rows still get removed
            logger.warning("could not delete audio object: %s", key)
    return deleted


async def delete_user_data(
    session: AsyncSession, *, user_id: uuid.UUID, storage: StoragePort
) -> dict[str, int]:
    """Purge a user's personal data. Returns counts for logging/audit."""
    audio_rows = (
        (
            await session.execute(
                select(CallAudio)
                .join(Call, Call.id == CallAudio.call_id)
                .where(Call.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    keys: set[str] = set()
    for audio in audio_rows:
        keys |= _audio_keys(audio)
    objects = await _delete_objects(storage, keys)

    # Tasks are the user's own; reminders cascade from them (ON DELETE CASCADE).
    tasks = cast(
        "CursorResult[Any]",
        await session.execute(delete(Task).where(Task.assignee_user_id == user_id)),
    )
    # Calls cascade (DB-level) to call_audio, transcripts, agreements,
    # agreement_extractions and agreement_edits.
    calls = cast(
        "CursorResult[Any]", await session.execute(delete(Call).where(Call.user_id == user_id))
    )

    await repositories.record_audit(
        session,
        entity_type="user",
        entity_id=user_id,
        action="data.deleted",
        actor_user_id=user_id,
        payload={"calls": calls.rowcount or 0, "tasks": tasks.rowcount or 0, "objects": objects},
    )
    logger.info(
        "deleted user data: calls=%s tasks=%s objects=%s",
        calls.rowcount,
        tasks.rowcount,
        objects,
    )
    return {
        "calls": calls.rowcount or 0,
        "tasks": tasks.rowcount or 0,
        "objects": objects,
    }


async def purge_expired_audio(
    session: AsyncSession,
    *,
    storage: StoragePort,
    now: datetime | None = None,
    limit: int = PURGE_BATCH,
) -> dict[str, int]:
    """Delete audio objects past their retention expiry; keep transcripts."""
    moment = now or datetime.now(UTC)
    expired = (
        (
            await session.execute(
                select(CallAudio)
                .where(CallAudio.expires_at.is_not(None), CallAudio.expires_at < moment)
                .order_by(CallAudio.expires_at)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    keys: set[str] = set()
    for audio in expired:
        keys |= _audio_keys(audio)
    objects = await _delete_objects(storage, keys)

    ids = [audio.id for audio in expired]
    if ids:
        await session.execute(delete(CallAudio).where(CallAudio.id.in_(ids)))
    logger.info("purged %d expired audio recording(s), %d object(s)", len(ids), objects)
    return {"audio": len(ids), "objects": objects}
