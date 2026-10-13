"""HTTP-клиент T-one streaming ASR (WebSocket /api/ws).

Протокол (см. tone/demo/website.py):
- сервер шлёт {"event": "ready"} -> клиент шлёт чанк 8кГц int16 PCM;
- когда распознана фраза: {"event": "transcript", "phrase": {...}};
- завершение: клиент шлёт пустые байты, сервер добивает буфер и закрывает WS.

Замечание: t-one держит соединение открытым после финализации, поэтому клиент
ждёт финальных фраз с таймаутом тишины, а не до закрытия соединения.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

from app.ml.asr.ports import CHUNK_BYTES, TextPhrase

# Сколько ждать финальную фразу после отправки маркера конца аудио. T-one
# добивает буфер сразу после пустых байт, поэтому 30 c — избыточно и тормозит
# каждый вызов; 5 c хватает как страховка.
FINALIZE_TIMEOUT = 5.0

# Как часто просыпаться, чтобы проверить завершение отправки (пока идёт стрим).
POLL_INTERVAL = 1.0

PhraseHandler = Callable[[TextPhrase], Awaitable[None]]


class ToneASRClient:
    """Асинхронный клиент T-one по WebSocket."""

    def __init__(self, ws_url: str) -> None:
        self._ws_url = ws_url

    @staticmethod
    def _parse_message(message: object) -> tuple[list[TextPhrase], bool]:
        """Разобрать сообщение сервера: (фразы, надо ли слать следующий чанк)."""
        if not isinstance(message, str):
            return [], False
        payload = json.loads(message)
        if payload.get("event") != "transcript":
            return [], payload.get("event") == "ready"
        phrase = payload["phrase"]
        return (
            [
                TextPhrase(
                    text=phrase["text"],
                    start_time=phrase["start_time"],
                    end_time=phrase["end_time"],
                )
            ],
            False,
        )

    async def transcribe(self, pcm_int16: bytes) -> list[TextPhrase]:
        """Прогнать 8кГц int16 PCM через T-one и собрать фразы."""
        phrases: list[TextPhrase] = []
        offset = 0
        finished = False

        async with websockets.connect(self._ws_url) as ws:
            while True:
                try:
                    if finished:
                        message = await asyncio.wait_for(
                            ws.recv(), timeout=FINALIZE_TIMEOUT
                        )
                    else:
                        message = await ws.recv()
                except (ConnectionClosed, TimeoutError):
                    break
                new_phrases, ready = self._parse_message(message)
                phrases.extend(new_phrases)
                if not ready:
                    continue
                if finished:
                    break
                chunk = pcm_int16[offset : offset + CHUNK_BYTES]
                if chunk:
                    await ws.send(chunk)
                    offset += CHUNK_BYTES
                else:
                    await ws.send(b"")
                    finished = True
        return phrases

    async def stream(
        self,
        chunks: AsyncIterator[bytes],
        on_phrase: PhraseHandler,
    ) -> None:
        """Стримить PCM-чанки в T-one и отдавать фразы колбэком по мере распознавания.

        Отправка и приём идут параллельно: чанки приходят из live-источника
        (Redis-стрим), а распознанные фразы обрабатываются сразу, не дожидаясь
        конца потока. Завершение: пустые байты; после этого приём ещё недолго
        ждёт финальные фразы (T-one держит соединение открытым).
        """
        finished = asyncio.Event()

        async def sender(ws: Any) -> None:
            try:
                async for chunk in chunks:
                    await ws.send(chunk)
                await ws.send(b"")
            finally:
                finished.set()

        async def receiver(ws: Any) -> None:
            idle_since_finished: float | None = None
            while True:
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=POLL_INTERVAL)
                except TimeoutError:
                    if finished.is_set():
                        if idle_since_finished is None:
                            idle_since_finished = time.monotonic()
                        elif time.monotonic() - idle_since_finished >= FINALIZE_TIMEOUT:
                            break
                    continue
                except ConnectionClosed:
                    break
                idle_since_finished = None
                phrases, _ = self._parse_message(message)
                for phrase in phrases:
                    await on_phrase(phrase)

        async with websockets.connect(self._ws_url) as ws:
            await asyncio.gather(sender(ws), receiver(ws))
