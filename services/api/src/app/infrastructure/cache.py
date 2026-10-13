"""Redis client: cache, live call state, OTP codes, refresh-token revocation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, cast

from redis.asyncio import Redis

from app.config import Settings


class Cache:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    @classmethod
    def from_settings(cls, settings: Settings) -> Cache:
        return cls(Redis.from_url(settings.redis_url, decode_responses=True))

    async def close(self) -> None:
        await self._redis.aclose()

    @property
    def client(self) -> Redis:
        return self._redis

    async def set(self, key: str, value: str, *, ttl_sec: int) -> None:
        await self._redis.set(key, value, ex=ttl_sec)

    async def get(self, key: str) -> str | None:
        return cast("str | None", await self._redis.get(key))

    async def delete(self, *keys: str) -> None:
        if keys:
            await self._redis.delete(*keys)

    async def lpush(self, key: str, value: str) -> None:
        await cast("Awaitable[Any]", self._redis.rpush(key, value))

    async def get_or_set(
        self,
        key: str,
        *,
        ttl_sec: int,
        factory: Callable[[], Any],
    ) -> Any:
        cached = await self.get(key)
        if cached is not None:
            return cached
        value = factory()
        await self.set(key, str(value), ttl_sec=ttl_sec)
        return value