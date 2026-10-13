"""Live ML pipeline: Redis-стримы аудио -> T-one streaming -> транскрипт + события.

Поток (plan.md §12): клиент стримит PCM по WS -> API кладёт кадры в Redis-стрим
-> `worker-asr-live` (эта функция) читает стримы, гонит T-one в реальном времени,
дописывает сегменты в `transcripts` и публикует `partial_transcript` сразу.
Инкрементальное извлечение (`stream_extract`, worker-ai-live) запускается по
debounce и финально в конце — договорённости обновляются по ходу разговора.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.infrastructure.db import repositories
from app.infrastructure.db.models import Transcript as TranscriptRow
from app.ml.asr.ports import StreamingASRPort, TextPhrase
from app.ml.stt.schemas import (
    ROLE_CLIENT,
    ROLE_OPERATOR,
    ROLE_UNKNOWN,
    RoleSource,
    TranscriptSegment,
)
from app.services.events import CallEventMessage
from app.services.live_audio import AUDIO_STREAM_KEY

logger = logging.getLogger(__name__)

LEG_ROLES: dict[str, str] = {"operator": ROLE_OPERATOR, "client": ROLE_CLIENT}


class EventsPort(Protocol):
    async def emit(self, message: CallEventMessage) -> None: ...


class RedisStreamPort(Protocol):
    """Минимум Redis, нужный live-пайплайну (структурно; fake в тестах)."""

    async def xread(
        self, streams: dict[str, str], *, block: int = 0, count: int = 0
    ) -> Any: ...


def role_for_leg(leg: str) -> str:
    return LEG_ROLES.get(leg, ROLE_UNKNOWN)


def role_source_for(legs: list[str]) -> RoleSource:
    """Канальные роли, если пришли ноги; иначе роли неизвестны."""
    return RoleSource.channel if legs else RoleSource.unknown


async def leg_chunks(
    redis: RedisStreamPort,
    call_id: str,
    leg: str,
    *,
    max_sec: float,
    block_ms: int = 2000,
) -> AsyncIterator[bytes]:
    """Асинхронно выдавать PCM-чанки ноги из Redis-стрима до ``eof``/таймаута."""
    key = AUDIO_STREAM_KEY.format(call_id=call_id, leg=leg)
    last_id = "0"
    deadline = time.monotonic() + max_sec
    while time.monotonic() < deadline:
        response = await redis.xread({key: last_id}, block=block_ms, count=64)
        if not response:
            continue
        for _name, entries in response:
            for entry_id, fields in entries:
                last_id = entry_id
                if fields.get("eof") == "1":
                    return
                data = fields.get("data")
                if data:
                    yield base64.b64decode(data)


async def stream_transcribe_and_store(
    session: AsyncSession,
    *,
    call_id: uuid.UUID,
    legs: list[str],
    redis: RedisStreamPort,
    asr: StreamingASRPort,
    events: EventsPort,
    settings: Settings,
    enqueue_extract: Callable[[], None],
) -> TranscriptRow | None:
    """Прочитать live-стримы, распознать и сохранить транскрипт.

    Одна asyncio-очередь сериализует запись в БД (AsyncSession не конкурентна):
    ноги стримят параллельно, а сегменты и события обрабатывает один consumer.
    Идемпотентно: если транскрипт уже ``done`` — no-op.
    """
    existing = await repositories.get_transcript(session, call_id)
    if existing is not None and existing.status == "done":
        logger.info("transcript already done for call %s; skipping live", call_id)
        return existing
    row = existing

    segments: list[TranscriptSegment] = []
    queue: asyncio.Queue[tuple[str, TextPhrase | None]] = asyncio.Queue()
    last_extract_at = 0.0
    call_str = str(call_id)

    async def producer(leg: str) -> None:
        async def on_phrase(phrase: TextPhrase) -> None:
            await queue.put((leg, phrase))

        chunks = leg_chunks(redis, call_str, leg, max_sec=settings.live_max_sec)
        await asr.stream(chunks, on_phrase)
        await queue.put((leg, None))  # sentinel: нога закончилась

    producers = [asyncio.create_task(producer(leg)) for leg in legs]
    remaining = len(producers)

    try:
        while remaining > 0:
            leg, phrase = await queue.get()
            if phrase is None:
                remaining -= 1
                continue
            segment = TranscriptSegment(
                speaker=role_for_leg(leg), text=phrase.text, start=phrase.start_time, end=phrase.end_time
            )
            segments.append(segment)
            row = await _persist_segments(session, row=row, call_id=call_id, segments=segments, legs=legs)
            await events.emit(
                CallEventMessage(
                    event="partial_transcript",
                    call_id=call_id,
                    payload={
                        "speaker": segment.speaker,
                        "text": segment.text,
                        "start": segment.start,
                        "end": segment.end,
                    },
                )
            )
            now = time.monotonic()
            if now - last_extract_at >= settings.live_debounce_sec:
                last_extract_at = now
                enqueue_extract()
    finally:
        for task in producers:
            task.cancel()
        await asyncio.gather(*producers, return_exceptions=True)

    row = await _persist_segments(
        session, row=row, call_id=call_id, segments=segments, legs=legs, status="done"
    )
    logger.info("live transcript for call %s: %d segments", call_id, len(segments))
    enqueue_extract()
    return row


async def _persist_segments(
    session: AsyncSession,
    *,
    row: TranscriptRow | None,
    call_id: uuid.UUID,
    segments: list[TranscriptSegment],
    legs: list[str],
    status: str = "processing",
) -> TranscriptRow:
    serialized = [segment.model_dump(mode="json") for segment in segments]
    full_text = " ".join(segment.text for segment in segments)
    role_source = role_source_for(legs).value
    if row is not None:
        row.segments = serialized
        row.full_text = full_text
        row.role_source = role_source
        row.status = status
        return row
    created = repositories.build_transcript(
        call_id=call_id,
        language="ru",
        full_text=full_text,
        segments=serialized,
        role_source=role_source,
    )
    created.status = status
    session.add(created)
    return created
