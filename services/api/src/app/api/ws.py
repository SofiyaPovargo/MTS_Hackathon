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
from app.infrastructure.security import ACCESS, TokenError, decode_token
from app.services.events import EVENT_SCHEMA_VERSION, EVENT_TYPES, EventHub

router = APIRouter()

# Mirror HTTP 401/403/404 semantics on the handshake (app-defined codes).
WS_UNAUTHORIZED = 4401
WS_FORBIDDEN = 4403
WS_NOT_FOUND = 4404


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
    settings = websocket.app.state.settings
    token = _extract_token(websocket)
    if token is None:
        await websocket.close(code=WS_UNAUTHORIZED)
        return
    try:
        payload = decode_token(token, settings=settings, expected_type=ACCESS)
    except TokenError:
        await websocket.close(code=WS_UNAUTHORIZED)
        return

    factory = websocket.app.state.session_factory
    async with factory() as session:
        user = await repositories.get_user(session, uuid.UUID(str(payload["sub"])))
        call = await repositories.get_call(session, call_id)

    if user is None or not user.is_active:
        await websocket.close(code=WS_UNAUTHORIZED)
        return
    if call is None:
        await websocket.close(code=WS_NOT_FOUND)
        return
    if call.user_id != user.id:
        await websocket.close(code=WS_FORBIDDEN)
        return

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


def _extract_token(websocket: WebSocket) -> str | None:
    header = websocket.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header.removeprefix("Bearer ").strip()
    token = websocket.query_params.get("token")
    return token or None
