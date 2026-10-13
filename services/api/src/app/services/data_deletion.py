"""Privacy: real data deletion and audio retention enforcement.

- ``delete_user_data`` — the "user requested deletion" flow (AGENTS.md: consent
  withdrawal + data deletion is a real flow, not "later"): removes the user's
  audio objects from object storage and their calls (which cascade to
  transcripts, agreements, extractions and edits) and tasks.
- ``purge_expired_audio`` — enforces the audio retention period: objects whose
  ``expires_at`` has passed are deleted from storage and their rows removed. The
  transcript is kept (only audio has a limited retention per AGENTS.md).
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


def _audio_urls(audio: CallAudio) -> set[str]:
    urls = {audio.storage_url}
    urls.update((audio.channel_urls or {}).values())
    return {url for url in urls if url}


async def _delete_objects(storage: StoragePort, urls: set[str]) -> int:
    deleted = 0
    for url in urls:
        if not url.startswith("s3://"):
            continue
        try:
            await storage.delete(key_from_url(url))
            deleted += 1
        except StorageError:  # best-effort: DB rows still get removed
            logger.warning("could not delete audio object: %s", url)
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
    urls: set[str] = set()
    for audio in audio_rows:
        urls |= _audio_urls(audio)
    objects = await _delete_objects(storage, urls)

    # Tasks are the user's own; reminders cascade from them (ON DELETE CASCADE).
    tasks = cast(
        "CursorResult[Any]", await session.execute(delete(Task).where(Task.assignee_user_id == user_id))
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
) -> dict[str, int]:
    """Delete audio objects past their retention expiry; keep transcripts."""
    moment = now or datetime.now(UTC)
    expired = (
        (
            await session.execute(
                select(CallAudio).where(
                    CallAudio.expires_at.is_not(None), CallAudio.expires_at < moment
                )
            )
        )
        .scalars()
        .all()
    )
    urls: set[str] = set()
    for audio in expired:
        urls |= _audio_urls(audio)
    objects = await _delete_objects(storage, urls)

    ids = [audio.id for audio in expired]
    if ids:
        await session.execute(delete(CallAudio).where(CallAudio.id.in_(ids)))
    logger.info("purged %d expired audio recording(s), %d object(s)", len(ids), objects)
    return {"audio": len(ids), "objects": objects}
