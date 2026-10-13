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

import websockets
from websockets.exceptions import ConnectionClosed

from api.ml.asr.ports import CHUNK_BYTES, TextPhrase

# Сколько ждать финальную фразу после отправки маркера конца аудио.
FINALIZE_TIMEOUT = 30.0


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
