"""Exolve webhook handling: inbound call control and progress notifications.

Exolve POSTs to our control URL for every inbound call; we answer with the
routing body that forwards the call to the app user's SIP account and plays the
consent notice (``file_to_A``). Progress notifications (``b``/``o``/``s``/``h``/
``e``/``crr``) then arrive at the event URL and drive the same
``CallSessionService`` the mock provider uses — so the ML/consent pipeline is
unchanged. ``crr`` (the finished recording) is handed to
``ProviderRecordingService``, which queues the download for a worker.

Exolve's control payload carries only ``{sip_id, numberA, call_sid}``: it does
not identify our user. The app user is resolved from the SIP resource that
received the call (``EXOLVE_SIP_ROUTES``), and the correlation back to our
``Call`` row is the ``client_id`` echoed in the routing body (and the
``call_sid`` stored as ``Call.external_id``).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.domain.enums import CallDirection
from app.domain.errors import NotFound
from app.infrastructure.db import repositories
from app.infrastructure.db.models import Call, User
from app.integrations.exolve import build_routing_response, parse_call_event, parse_sip_routes
from app.services.call_session import CallSessionService
from app.services.provider_recording import ProviderRecordingService

logger = logging.getLogger(__name__)


class ExolveWebhookService:
    """Turn Exolve callbacks into ``Call`` records and lifecycle transitions."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        calls: CallSessionService,
        recordings: ProviderRecordingService,
    ) -> None:
        self._session = session
        self._settings = settings
        self._calls = calls
        self._recordings = recordings

    # -- call control ---------------------------------------------------------

    async def handle_control(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Answer the routing request: forward to the app user or refuse.

        Returns a JSON-RPC 2.0 body ready to be sent back to Exolve.
        """
        sip_id = str(payload.get("sip_id", ""))
        route = parse_sip_routes(self._settings.exolve_sip_routes).get(sip_id)
        if route is None:
            logger.warning("exolve: no route for sip_id=%s", sip_id)
            return self._routing_error(sip_id, "unknown SIP resource")
        user = await repositories.get_user_by_phone(self._session, route.phone)
        if user is None or not user.is_active:
            logger.warning("exolve: no active user for phone=%s (sip_id=%s)", route.phone, sip_id)
            return self._routing_error(sip_id, "app user is not available")

        call_sid = str(payload.get("call_sid", ""))
        call = await self._find_or_create_call(
            user, call_sid=call_sid, from_number=str(payload.get("numberA", ""))
        )
        return build_routing_response(
            sip_id=sip_id,
            redirect_sip_uri=route.sip_uri,
            event_url=self._event_url(),
            client_id=str(call.id),
            notice_file_id=self._settings.exolve_consent_notice_file_id or None,
        )

    async def _find_or_create_call(self, user: User, *, call_sid: str, from_number: str) -> Call:
        call = await repositories.get_call_by_external_id(self._session, call_sid)
        if call is not None:
            return call  # Exolve retried the control webhook: keep one Call row.
        return await self._calls.create_call(
            user,
            direction=CallDirection.inbound,
            contact_phone=from_number,
            contact_name=None,
            external_id=call_sid,
        )

    # -- progress notifications ----------------------------------------------

    async def handle_event(self, payload: dict[str, Any]) -> tuple[Call, str]:
        """Apply one progress notification; returns the call and an outcome code."""
        parsed = parse_call_event(payload)
        call = await self._resolve_call(parsed.client_id, parsed.call_sid)
        if not parsed.known:
            logger.info("exolve: ignoring unknown event type=%s", parsed.exolve_type)
            return call, "ignored"
        if parsed.exolve_type == "crr":
            # The finished recording: remember the record id and let a worker
            # download it (the webhook must answer Exolve quickly).
            if not parsed.record_uid:
                logger.info("exolve: crr without a record id for call %s", call.id)
                return call, "ignored"
            return call, await self._recordings.mark_ready(call, uid=parsed.record_uid)
        if parsed.event is None:
            # ``h`` (bridge status) carries no lifecycle transition.
            return call, "ignored"
        owner = await repositories.get_user(self._session, call.user_id)
        if owner is None:
            raise NotFound("call owner not found")
        await self._calls.handle_provider_event(owner, call, parsed.event)
        return call, "handled"

    async def _resolve_call(self, client_id: str | None, call_sid: str) -> Call:
        if client_id:
            try:
                call = await repositories.get_call(self._session, uuid.UUID(client_id))
            except ValueError:
                call = None
            if call is not None:
                return call
        if call_sid:
            call = await repositories.get_call_by_external_id(self._session, call_sid)
            if call is not None:
                return call
        raise NotFound("unknown call for Exolve event")

    # -- helpers --------------------------------------------------------------

    def _event_url(self) -> str:
        base = self._settings.public_base_url.rstrip("/")
        path = self._settings.api_base_path.strip("/")
        return f"{base}/{path}/voice/exolve/events?secret={self._settings.voice_webhook_secret}"

    @staticmethod
    def _routing_error(sip_id: str, message: str) -> dict[str, Any]:
        return {
            "id": 1,
            "jsonrpc": "2.0",
            "sip_id": sip_id,
            "error": {"code": -32000, "message": message},
        }
