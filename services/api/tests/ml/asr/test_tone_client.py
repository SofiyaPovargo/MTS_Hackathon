"""Тесты ToneASRClient против fake WebSocket-сервера (протокол T-one)."""

from __future__ import annotations

import json

import pytest
from websockets.asyncio.server import ServerConnection, serve

from api.ml.asr.ports import CHUNK_BYTES
from api.ml.asr.tone import ToneASRClient


async def _fake_tone_handler(websocket: ServerConnection) -> None:
    """Повторяет tone/demo/website.py: ready -> bytes -> transcript -> empty-finalize."""
    await websocket.send(json.dumps({"event": "ready"}))
    while True:
        received = await websocket.recv()
        if isinstance(received, bytes) and len(received) > 0:
            await websocket.send(json.dumps({"event": "ready"}))
            continue
        await websocket.send(
            json.dumps(
                {
                    "event": "transcript",
                    "phrase": {"text": "привет", "start_time": 0.1, "end_time": 0.8},
                }
            ),
        )
        await websocket.send(
            json.dumps(
                {
                    "event": "transcript",
                    "phrase": {"text": "пока", "start_time": 1.0, "end_time": 1.5},
                }
            ),
        )
        return


@pytest.mark.asyncio
async def test_transcribe_returns_phrases_in_order() -> None:
    async with serve(_fake_tone_handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        client = ToneASRClient(f"ws://127.0.0.1:{port}/api/ws")
        phrases = await client.transcribe(bytes(2 * CHUNK_BYTES))

    assert [p.text for p in phrases] == ["привет", "пока"]
    first = phrases[0]
    assert first.start_time == 0.1
    assert first.end_time == 0.8
