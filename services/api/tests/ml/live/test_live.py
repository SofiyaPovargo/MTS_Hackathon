"""Live-пайплайн: чтение Redis-стримов и маппинг ролей."""

from __future__ import annotations

import base64
from typing import Any

import pytest

from app.ml.live import leg_chunks, role_for_leg, role_source_for
from app.ml.stt.schemas import RoleSource


class FakeRedis:
    """Отдаёт заранее заданные батчи записей стрима, затем пустоту."""

    def __init__(self, batches: list[list[tuple[str, dict[str, str]]]]) -> None:
        self._batches = list(batches)

    async def xread(
        self, streams: dict[str, str], *, block: int = 0, count: int = 0
    ) -> list[Any]:
        if not self._batches:
            return []
        key = next(iter(streams))
        return [(key, self._batches.pop(0))]


def test_role_mapping() -> None:
    assert role_for_leg("operator") == "operator"
    assert role_for_leg("client") == "client"
    assert role_for_leg("mixed") == "unknown"
    assert role_source_for(["operator", "client"]) is RoleSource.channel
    assert role_source_for([]) is RoleSource.unknown


@pytest.mark.asyncio
async def test_leg_chunks_decodes_and_stops_at_eof() -> None:
    blob = b"\x01\x02\x03\x04"
    redis = FakeRedis(
        [
            [("1-0", {"data": base64.b64encode(blob).decode()})],
            [("2-0", {"eof": "1"})],
        ]
    )

    received: list[bytes] = []
    async for chunk in leg_chunks(redis, "call", "operator", max_sec=5):
        received.append(chunk)

    assert received == [blob]


@pytest.mark.asyncio
async def test_leg_chunks_returns_on_eof_alone() -> None:
    redis = FakeRedis([[("1-0", {"eof": "1"})]])
    received = [chunk async for chunk in leg_chunks(redis, "call", "client", max_sec=5)]
    assert received == []
