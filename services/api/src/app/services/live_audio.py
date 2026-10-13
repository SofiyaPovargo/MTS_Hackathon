"""Live audio ingest: клиент стримит PCM по WS, API релеит в Redis.

ML остаётся в воркерах: API не тянет ML-зависимости, поэтому только раскладывает
8 кГц int16 PCM по Redis-стриму на (звонок, ногу). `worker-asr-live` читает
стримы и гонит T-one в реальном времени.
"""

from __future__ import annotations

import base64

from app.infrastructure.cache import Cache

# Ключ Redis-стрима с чанками одной ноги/смеси звонка.
AUDIO_STREAM_KEY = "audio:call:{call_id}:{leg}"
# Флаг «live-ASR уже поставлен в очередь» (idempotent enqueue на звонок).
LIVE_STARTED_KEY = "live:started:{call_id}"

AUDIO_STREAM_TTL_SEC = 3600
AUDIO_STREAM_MAXLEN = 40_000  # кадров; защита от неограниченного роста

#: Допустимые потоки: две ноги VoIP или смешанный поток.
LEGS = ("operator", "client", "mixed")


class LiveAudioRelay:
    """Складывает live-чанки звонка в Redis-стримы для worker-asr-live."""

    def __init__(
        self,
        cache: Cache,
        *,
        ttl_sec: int = AUDIO_STREAM_TTL_SEC,
        maxlen: int = AUDIO_STREAM_MAXLEN,
    ) -> None:
        self._cache = cache
        self._ttl = ttl_sec
        self._maxlen = maxlen

    @staticmethod
    def _key(call_id: str, leg: str) -> str:
        return AUDIO_STREAM_KEY.format(call_id=call_id, leg=leg)

    async def push(self, call_id: str, leg: str, chunk: bytes) -> None:
        """Добавить кадр PCM в стрим ноги.

        Чанк кодируется в base64: Redis-клиент Cache работает с
        ``decode_responses=True`` и испортил бы произвольные бинарные байты.
        """
        key = self._key(call_id, leg)
        payload = base64.b64encode(chunk).decode("ascii")
        await self._cache.client.xadd(
            key, {"data": payload}, maxlen=self._maxlen, approximate=True
        )
        await self._cache.client.expire(key, self._ttl)

    async def end(self, call_id: str, leg: str) -> None:
        """Пометить конец потока ноги (клиент закрыл соединение)."""
        key = self._key(call_id, leg)
        await self._cache.client.xadd(
            key, {"eof": "1"}, maxlen=self._maxlen, approximate=True
        )
        await self._cache.client.expire(key, self._ttl)

    async def mark_started(self, call_id: str) -> bool:
        """True, если это первый потащивший ногу — тогда ставим ASR один раз."""
        started = await self._cache.client.set(
            LIVE_STARTED_KEY.format(call_id=call_id), "1", nx=True, ex=self._ttl
        )
        return bool(started)
