"""WebSocket endpoint for live call events.

Schema version 1 (``EVENT_SCHEMA_VERSION``). Every frame is a JSON envelope:

    {"version": 1, "event": "partial_transcript", "call_id": "<uuid>", "payload": {…}}

Event types: ``partial_transcript``, ``agreement_detected``,
``analysis_started``, ``call_ended``. ``GET /ws/events/schema`` returns the
envelope JSON schema and the event list for the mobile client generator.

Authentication is a JWT access token, supplied either in the
``Authorization: Bearer <token>`` header (mobile) or as ``?token=<token>``
(browsers, which cannot set headers on the handshake). Only the call owner may
subscribe: managers never receive a subordinate's audio or transcript
(AGENTS.md, "Roles and access").
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.schemas import CallEventEnvelope
from app.infrastructure.db import repositories
from app.infrastructure.db.models import Call, User
from app.infrastructure.security import ACCESS, TokenError, decode_token
from app.services.events import EVENT_SCHEMA_VERSION, EVENT_TYPES, EventHub
from app.services.live_audio import LEGS, LiveAudioRelay

router = APIRouter()

# Mirror HTTP 401/403/404 semantics on the handshake (app-defined codes).
WS_UNAUTHORIZED = 4401
WS_FORBIDDEN = 4403
WS_NOT_FOUND = 4404
WS_BAD_REQUEST = 4400
# The call must be recorded (answered + consent) before its audio is accepted.
WS_NOT_RECORDING = 4409


@router.get("/ws/events/schema")
async def ws_events_schema() -> dict[str, object]:
    """Machine-readable contract for the live event stream (also in OpenAPI)."""
    return {
        "version": EVENT_SCHEMA_VERSION,
        "events": list(EVENT_TYPES),
        "envelope": CallEventEnvelope.model_json_schema(),
    }


@router.websocket("/ws/calls/{call_id}")
async def call_events(websocket: WebSocket, call_id: uuid.UUID) -> None:
    authorized = await _authenticate(websocket, call_id)
    if authorized is None:
        return
    _user, _call = authorized

    hub: EventHub = websocket.app.state.event_hub
    # Subscribe first: anything emitted while we replay is also delivered live and
    # de-duplicated below, so an event is never lost in the gap or sent twice.
    subscription = await hub.open_subscription(call_id)
    try:
        await websocket.accept()
        replayed = await hub.replay(call_id)
        pending_replay = set(replayed)
        for frame in replayed:
            await websocket.send_text(frame)
        async for frame in subscription.frames():
            if frame in pending_replay:
                pending_replay.discard(frame)
                continue
            await websocket.send_text(frame)
    except WebSocketDisconnect:
        return
    finally:
        await subscription.close()


@router.websocket("/ws/calls/{call_id}/audio")
async def call_audio(websocket: WebSocket, call_id: uuid.UUID) -> None:
    """Live audio ingest: the client streams per-leg 8 kHz int16 PCM.

    The API stays ML-free: each binary frame is appended to a Redis stream
    (``audio:call:{call_id}:{leg}``) that ``worker-asr-live`` consumes. Only the
    call owner may stream, and only after the recording gate (``answered`` +
    consent). ``?leg=operator|client|mixed`` selects the stream (default mixed).
    """
    leg = websocket.query_params.get("leg", "mixed")
    if leg not in LEGS:
        await websocket.close(code=WS_BAD_REQUEST)
        return

    authorized = await _authenticate(websocket, call_id)
    if authorized is None:
        return
    _user, call = authorized
    if call.recording_started_at is None:
        await websocket.close(code=WS_NOT_RECORDING)
        return

    relay = LiveAudioRelay(websocket.app.state.cache)
    if await relay.mark_started(str(call_id)):
        websocket.app.state.analysis_queue.enqueue_live_asr(str(call_id))

    await websocket.accept()
    try:
        while True:
            try:
                frame = await websocket.receive_bytes()
            except WebSocketDisconnect:
                break
            await relay.push(str(call_id), leg, frame)
    finally:
        await relay.end(str(call_id), leg)


async def _authenticate(
    websocket: WebSocket, call_id: uuid.UUID
) -> tuple[User, Call] | None:
    """JWT + owner check; close the handshake and return ``None`` on failure."""
    settings = websocket.app.state.settings
    token = _extract_token(websocket)
    if token is None:
        await websocket.close(code=WS_UNAUTHORIZED)
        return None
    try:
        payload = decode_token(token, settings=settings, expected_type=ACCESS)
    except TokenError:
        await websocket.close(code=WS_UNAUTHORIZED)
        return None

    factory = websocket.app.state.session_factory
    async with factory() as session:
        user = await repositories.get_user(session, uuid.UUID(str(payload["sub"])))
        call = await repositories.get_call(session, call_id)

    if user is None or not user.is_active:
        await websocket.close(code=WS_UNAUTHORIZED)
        return None
    if call is None:
        await websocket.close(code=WS_NOT_FOUND)
        return None
    if call.user_id != user.id:
        await websocket.close(code=WS_FORBIDDEN)
        return None
    return user, call


def _extract_token(websocket: WebSocket) -> str | None:
    header = websocket.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header.removeprefix("Bearer ").strip()
    token = websocket.query_params.get("token")
    return token or None
