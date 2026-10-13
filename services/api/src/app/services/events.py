"""In-process event hub for call events.

Stage 6 wires these events to the WebSocket endpoint; the hub already
persists the last events per call in Redis so late subscribers can replay.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field

from app.infrastructure.cache import Cache

CALL_EVENT_KEY = "events:call:{call_id}"


@dataclass(slots=True)
class CallEventMessage:
    event: str
    call_id: uuid.UUID
    payload: dict[str, object] = field(default_factory=dict)


class EventHub:
    def __init__(self, cache: Cache) -> None:
        self._cache = cache

    async def emit(self, message: CallEventMessage) -> None:
        key = CALL_EVENT_KEY.format(call_id=message.call_id)
        await self._cache.lpush(key, json.dumps(asdict(message), default=str))
        await self._cache.client.expire(key, 3600)