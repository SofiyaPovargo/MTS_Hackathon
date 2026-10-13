"""Call-event hub: versioned envelopes, replay and live pub/sub.

Every event is (a) appended to a Redis list so a subscriber that connects
mid-call can replay what it missed, and (b) published on a Redis channel so
already-connected subscribers receive it live. ``api/ws.py`` is the consumer.

Event contract (schema version 1), the same shape on replay and live:

    {"version": 1, "event": "partial_transcript",
     "call_id": "<uuid>", "payload": {…}}

Event types: ``partial_transcript``, ``agreement_detected``,
``analysis_started``, ``call_ended`` (see ``plan.md`` §13).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from typing import Any, cast

from redis.asyncio.client import PubSub

from app.infrastructure.cache import Cache

CALL_EVENT_KEY = "events:call:{call_id}"
CALL_EVENT_TTL_SEC = 3600

# Bump only on a breaking change to the frame shape; consumers pin to this.
EVENT_SCHEMA_VERSION = 1
EVENT_TYPES = (
    "partial_transcript",
    "agreement_detected",
    "analysis_started",
    "call_ended",
)


@dataclass(slots=True)
class CallEventMessage:
    event: str
    call_id: uuid.UUID
    payload: dict[str, object] = field(default_factory=dict)
    version: int = EVENT_SCHEMA_VERSION

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)


class CallEventSubscription:
    """An open Redis pub/sub subscription for a single call."""

    def __init__(self, pubsub: PubSub, channel: str) -> None:
        self._pubsub = pubsub
        self._channel = channel
        self._closed = False

    async def frames(self) -> AsyncIterator[str]:
        async for raw in cast("AsyncIterator[dict[str, Any]]", self._pubsub.listen()):
            if raw.get("type") != "message":
                continue
            data = raw.get("data")
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            if isinstance(data, str):
                yield data

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._pubsub.unsubscribe(self._channel)
        await self._pubsub.aclose()  # type: ignore[no-untyped-call]


class EventHub:
    def __init__(self, cache: Cache) -> None:
        self._cache = cache

    @staticmethod
    def _key(call_id: uuid.UUID | str) -> str:
        return CALL_EVENT_KEY.format(call_id=call_id)

    async def emit(self, message: CallEventMessage) -> None:
        key = self._key(message.call_id)
        frame = message.to_json()
        # rpush (via Cache.lpush) keeps the replay list in chronological order.
        await self._cache.lpush(key, frame)
        await self._cache.client.expire(key, CALL_EVENT_TTL_SEC)
        await cast("Any", self._cache.client.publish(key, frame))

    async def replay(self, call_id: uuid.UUID | str) -> list[str]:
        rows = await cast("Any", self._cache.client.lrange(self._key(call_id), 0, -1))
        return [str(row) for row in rows]

    async def open_subscription(self, call_id: uuid.UUID | str) -> CallEventSubscription:
        """Subscribe *before* replaying so no event falls in the gap between them."""
        channel = self._key(call_id)
        pubsub = self._cache.client.pubsub()
        await pubsub.subscribe(channel)
        return CallEventSubscription(pubsub, channel)
