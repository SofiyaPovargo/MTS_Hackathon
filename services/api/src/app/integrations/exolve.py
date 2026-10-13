"""МТС Exolve voice adapter.

Two Exolve features are used (docs.exolve.ru):

1. *Динамическая переадресация входящих вызовов по API (на URL)* — on an
   inbound call Exolve POSTs ``{sip_id, numberA, call_sid}`` to our control URL.
   We answer with a JSON-RPC 2.0 body that routes the call to the app user's
   SIP ID and plays the notice to the calling party through ``file_to_A``.
   Progress notifications (``b``/``o``/``s``/``h``/``e``/``crr``) are POSTed to
   ``event_URL``.
2. *Call Record API* — ``SetCallRecordState`` toggles recording for a SIP
   resource, ``GetInfo``/``Download`` fetch the finished recording.

Two provider properties shape the design (recorded in ``plan.md`` §11.1):

- Exolve exposes **no server-side media stream**, so the audio that reaches the
  ML pipeline is uploaded by the mobile client (the SDK's mixed stream).
  ``open_media_stream`` therefore returns the client ingest URL; it does not
  open a provider-side stream.
- Exolve's inbound API has **no DTMF collection**, so consent is
  ``notice`` + continuing the call (``CONSENT_MODE=notice``) and
  ``collect_dtmf`` returns ``None``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import Settings
from app.domain.enums import CallEvent

# Exolve progress-notification type -> domain call event. ``h`` (bridge status)
# and ``crr`` (record ready) carry no domain transition yet; they are surfaced
# through ``ExolveCallEvent.raw`` instead of being guessed into an event.
EXOLVE_LIFECYCLE_EVENTS: dict[str, CallEvent] = {
    "b": CallEvent.incoming,  # Begin: connected to the calling party (A)
    "o": CallEvent.ringing,  # Originate: dialing the forwarding target (B)
    "s": CallEvent.answered,  # Start: B answered
    "e": CallEvent.ended,  # End: the conversation finished
}
EXOLVE_EVENT_TYPES: frozenset[str] = frozenset({"b", "o", "s", "h", "e", "crr"})


@dataclass(frozen=True)
class ExolveCallEvent:
    """Normalized view of one Exolve progress notification."""

    exolve_type: str
    call_sid: str
    from_number: str | None
    to_number: str | None
    client_id: str | None
    record_call: bool
    event: CallEvent | None = None
    known: bool = True
    raw: dict[str, Any] = field(default_factory=dict)


def parse_call_event(payload: dict[str, Any]) -> ExolveCallEvent:
    """Map a raw Exolve webhook payload onto the domain vocabulary.

    Unknown types never raise: ``known`` is ``False`` and ``raw`` is kept so the
    caller can log or handle it later without losing information.
    """
    kind = str(payload.get("type", ""))
    return ExolveCallEvent(
        exolve_type=kind,
        call_sid=str(payload.get("call_sid", "")),
        from_number=payload.get("from"),
        to_number=payload.get("to"),
        client_id=payload.get("client_id"),
        record_call=bool(payload.get("record_call", False)),
        event=EXOLVE_LIFECYCLE_EVENTS.get(kind),
        known=kind in EXOLVE_EVENT_TYPES,
        raw=dict(payload),
    )


def build_routing_response(
    *,
    sip_id: str,
    redirect_sip_uri: str,
    event_url: str,
    client_id: str,
    notice_file_id: str | None = None,
    timeout: int = 30,
    masking: bool = True,
) -> dict[str, Any]:
    """JSON-RPC 2.0 body that routes an inbound call to the app user.

    ``file_to_A`` plays the notice (the consent prompt) to the calling party;
    ``event_URL`` receives the progress notifications; ``client_id`` is echoed
    back so we can correlate our own call record.
    """
    result: dict[str, Any] = {
        "redirect_type": 1,  # 1 = single target
        "event_URL": event_url,
        "event_extended": True,
        "client_id": client_id,
        "masking": masking,
        "followme_struct": [
            1,  # number of targets
            [
                {
                    "I_FOLLOW_ORDER": 1,
                    "ACTIVE": True,
                    "NAME": "app-user",
                    "SIP_URI": redirect_sip_uri,
                    "PERIOD": "always",
                    "PERIOD_DESCRIPTION": "always",
                    "TIMEOUT": timeout,
                }
            ],
        ],
    }
    if notice_file_id:
        result["file_to_A"] = notice_file_id
    return {"id": 1, "jsonrpc": "2.0", "sip_id": sip_id, "result": result}


class ExolveCallRecordClient:
    """Thin client for the Call Record API.

    Endpoints verified against docs.exolve.ru:

    - ``POST /sip/v1/SetCallRecordState`` — ``{sip_resource_id, call_record}``
    - ``POST /statistics/call-record/v1/GetInfo`` — ``{uids: [...]}``
    - ``GET  /statistics/download/{uid}`` — audio bytes

    Authentication is the application API key as ``Authorization: Bearer …``.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(
            base_url=base_url, timeout=timeout, headers=headers, transport=transport
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def set_call_record_state(self, *, sip_resource_id: int, call_record: bool) -> None:
        response = await self._client.post(
            "/sip/v1/SetCallRecordState",
            json={"sip_resource_id": sip_resource_id, "call_record": call_record},
        )
        response.raise_for_status()

    async def get_info(self, uids: Sequence[str]) -> list[dict[str, Any]]:
        response = await self._client.post(
            "/statistics/call-record/v1/GetInfo", json={"uids": list(uids)}
        )
        response.raise_for_status()
        return list(response.json().get("records", []))

    async def download_record(self, uid: str) -> bytes:
        response = await self._client.get(f"/statistics/download/{uid}")
        response.raise_for_status()
        return response.content


class ExolveVoiceProvider:
    """``VoiceProviderPort`` implementation on top of Exolve.

    Recording is toggled at the SIP-resource level, so ``start_recording`` is
    idempotent and safe to call per call. The consent notice is collected here
    and rendered into the control webhook response (``control_response``); it is
    not a standalone mid-call call, which the inbound API does not offer.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._records = ExolveCallRecordClient(
            base_url=settings.exolve_api_base_url,
            api_key=settings.exolve_api_key,
            transport=transport,
        )
        self._notices: dict[str, str] = {}

    async def aclose(self) -> None:
        await self._records.aclose()

    async def answer(self, call_external_id: str) -> None:
        # The app answers through the Exolve Mobile SDK; on the server the
        # "answer" is the routing body returned to the control webhook.
        return None

    async def hangup(self, call_external_id: str) -> None:
        # This Exolve API surface has no per-call hangup; the app ends its leg.
        return None

    async def play_notice(self, call_external_id: str, notice_id: str) -> None:
        # Rendered as ``file_to_A`` in the control response.
        self._notices[call_external_id] = notice_id

    async def play_consent_prompt(self, call_external_id: str) -> None:
        await self.play_notice(call_external_id, self._settings.exolve_consent_notice_file_id)

    async def collect_dtmf(self, call_external_id: str) -> str | None:
        # Not supported by the inbound API; consent is CONSENT_MODE=notice.
        return None

    async def start_recording(self, call_external_id: str) -> str:
        await self._records.set_call_record_state(
            sip_resource_id=self._settings.exolve_sip_resource_id, call_record=True
        )
        return f"exolve-rec:{call_external_id}"

    async def open_media_stream(self, call_external_id: str) -> str:
        # No server-side media stream: the mobile client uploads the SDK's mixed
        # stream to this ingest URL.
        return f"{self._settings.media_ingest_url}?call_external_id={call_external_id}"

    def control_response(
        self,
        call_external_id: str,
        *,
        sip_id: str,
        redirect_sip_uri: str,
        event_url: str,
        client_id: str,
    ) -> dict[str, Any]:
        """Build the routing body, applying any notice set for this call."""
        notice = self._notices.pop(call_external_id, None)
        if not notice:
            notice = self._settings.exolve_consent_notice_file_id or None
        return build_routing_response(
            sip_id=sip_id,
            redirect_sip_uri=redirect_sip_uri,
            event_url=event_url,
            client_id=client_id,
            notice_file_id=notice,
        )
