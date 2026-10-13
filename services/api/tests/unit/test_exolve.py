"""МТС Exolve adapter: event mapping, routing body, record API, provider port."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.domain.enums import CallEvent
from app.integrations.exolve import (
    ExolveCallRecordClient,
    ExolveVoiceProvider,
    build_routing_response,
    parse_call_event,
    parse_sip_routes,
)
from app.integrations.voice import MockVoiceProvider, voice_provider_factory


def _settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None).model_copy(update=overrides)


def _record_client(handler: Callable[[httpx.Request], httpx.Response]) -> ExolveCallRecordClient:
    return ExolveCallRecordClient(
        base_url="https://api.exolve.test",
        api_key="test-key",
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("b", CallEvent.incoming),
        ("o", CallEvent.ringing),
        ("s", CallEvent.answered),
        ("e", CallEvent.ended),
    ],
)
def test_parse_lifecycle_event(kind: str, expected: CallEvent) -> None:
    event = parse_call_event(
        {
            "type": kind,
            "call_sid": "cs-1",
            "from": "+79990000001",
            "to": "74990000000",
            "client_id": "abc",
            "record_call": True,
        }
    )
    assert event.event is expected
    assert event.known is True
    assert event.call_sid == "cs-1"
    assert event.from_number == "+79990000001"
    assert event.to_number == "74990000000"
    assert event.client_id == "abc"
    assert event.record_call is True


@pytest.mark.parametrize("kind", ["h", "crr", "z"])
def test_parse_non_lifecycle_keeps_raw(kind: str) -> None:
    payload = {"type": kind, "call_sid": "cs-2", "extra": "keep-me"}
    event = parse_call_event(payload)
    assert event.event is None
    assert event.raw == payload
    assert event.known is (kind != "z")


def test_parse_crr_exposes_the_record_id() -> None:
    event = parse_call_event(
        {
            "type": "crr",
            "call_sid": "cs-3",
            "client_id": "11111111-1111-1111-1111-111111111111",
            "uid": 7135909209505402880,
            "record_duration": 21,
            "path": "https://api.exolve.ru/statistics/download/7135909209505402880",
        }
    )
    assert event.known is True
    assert event.event is None
    assert event.record_uid == "7135909209505402880"


def test_parse_crr_without_uid_has_no_record_id() -> None:
    assert parse_call_event({"type": "crr", "call_sid": "cs-4"}).record_uid is None


def test_parse_sip_routes_handles_multiple_entries() -> None:
    routes = parse_sip_routes(
        "1001=+79000000002:sip:anna@pbx, 1002=+79000000003:sip:boris@pbx"
    )
    assert set(routes) == {"1001", "1002"}
    assert routes["1001"].phone == "+79000000002"
    assert routes["1001"].sip_uri == "sip:anna@pbx"


def test_parse_sip_routes_skips_malformed_entries() -> None:
    routes = parse_sip_routes("1001=+7900,sip_id_without_equals,:sip:x,=+7900:sip:y")
    assert routes == {}


def test_parse_sip_routes_empty_is_empty() -> None:
    assert parse_sip_routes("") == {}


def test_build_routing_response_shape() -> None:
    body = build_routing_response(
        sip_id="74990000000",
        redirect_sip_uri="user@sip.exolve.ru",
        event_url="https://api.example.com/api/voice/exolve/events",
        client_id="cid",
    )
    assert body["jsonrpc"] == "2.0"
    assert body["sip_id"] == "74990000000"
    result = body["result"]
    assert result["redirect_type"] == 1
    assert result["client_id"] == "cid"
    assert "file_to_A" not in result
    assert result["followme_struct"][0] == 1
    assert result["followme_struct"][1][0]["SIP_URI"] == "user@sip.exolve.ru"
    assert result["followme_struct"][1][0]["I_FOLLOW_ORDER"] == 1


async def test_set_call_record_state_sends_sip_resource() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, json={})

    client = _record_client(handler)
    try:
        await client.set_call_record_state(sip_resource_id=1111, call_record=True)
    finally:
        await client.aclose()

    assert seen["url"] == "https://api.exolve.test/sip/v1/SetCallRecordState"
    assert seen["auth"] == "Bearer test-key"
    assert seen["json"] == {"sip_resource_id": 1111, "call_record": True}


async def test_record_client_get_info_and_download() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/statistics/call-record/v1/GetInfo":
            return httpx.Response(200, json={"records": [{"uid": "42", "record_path": "http://x/42"}]})
        assert request.url.path == "/statistics/download/42"
        return httpx.Response(200, content=b"AUDIO", headers={"content-type": "audio/mpeg"})

    client = _record_client(handler)
    try:
        records = await client.get_info(["42"])
        recording = await client.fetch_recording("42")
    finally:
        await client.aclose()

    assert records[0]["uid"] == "42"
    assert recording.data == b"AUDIO"
    assert recording.content_type == "audio/mpeg"


async def test_fetch_recording_builds_the_url_from_the_configured_base() -> None:
    """The record id comes from the webhook, but the host never does (no SSRF)."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, content=b"AUDIO")

    client = ExolveCallRecordClient(
        base_url="https://api.exolve.test",
        api_key="test-key",
        transport=httpx.MockTransport(handler),
    )
    try:
        await client.fetch_recording("42")
    finally:
        await client.aclose()

    assert seen["url"] == "https://api.exolve.test/statistics/download/42"


async def test_fetch_recording_falls_back_to_mp3_without_a_content_type() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"AUDIO")

    client = _record_client(handler)
    try:
        recording = await client.fetch_recording("42")
    finally:
        await client.aclose()

    assert recording.content_type == "audio/mpeg"


async def test_record_client_raises_on_provider_error() -> None:
    client = _record_client(lambda _request: httpx.Response(409, json={"error": "disabled"}))
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await client.set_call_record_state(sip_resource_id=1, call_record=True)
    finally:
        await client.aclose()


async def test_start_recording_toggles_sip_resource() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, json={})

    provider = ExolveVoiceProvider(
        _settings(exolve_api_key="k", exolve_sip_resource_id=77),
        transport=httpx.MockTransport(handler),
    )
    try:
        handle = await provider.start_recording("call-1")
    finally:
        await provider.aclose()

    assert seen["json"] == {"sip_resource_id": 77, "call_record": True}
    assert handle == "exolve-rec:call-1"


async def test_collect_dtmf_is_unsupported() -> None:
    provider = ExolveVoiceProvider(_settings())
    try:
        assert await provider.collect_dtmf("call-1") is None
    finally:
        await provider.aclose()


async def test_open_media_stream_returns_client_ingest_url() -> None:
    provider = ExolveVoiceProvider(_settings(media_ingest_url="http://ingest.local/api"))
    try:
        url = await provider.open_media_stream("call-9")
    finally:
        await provider.aclose()

    assert url == "http://ingest.local/api"


async def test_control_response_applies_notice_then_falls_back() -> None:
    provider = ExolveVoiceProvider(_settings(exolve_consent_notice_file_id="default-notice"))
    try:
        await provider.play_notice("call-1", "notice-777")
        applied = provider.control_response(
            "call-1",
            sip_id="74990000000",
            redirect_sip_uri="user@sip.exolve.ru",
            event_url="https://api.example.com/api/voice/exolve/events",
            client_id="11111111-1111-1111-1111-111111111111",
        )
        # The pending notice is consumed once.
        reused = provider.control_response(
            "call-1",
            sip_id="74990000000",
            redirect_sip_uri="user@sip.exolve.ru",
            event_url="https://api.example.com/api/voice/exolve/events",
            client_id="11111111-1111-1111-1111-111111111111",
        )
    finally:
        await provider.aclose()

    assert applied["result"]["file_to_A"] == "notice-777"
    assert applied["result"]["event_URL"].endswith("/api/voice/exolve/events")
    assert reused["result"]["file_to_A"] == "default-notice"


async def test_voice_provider_factory() -> None:
    settings = _settings()
    assert isinstance(voice_provider_factory("mock", settings), MockVoiceProvider)

    provider = voice_provider_factory("exolve", settings)
    assert isinstance(provider, ExolveVoiceProvider)
    await provider.aclose()

    with pytest.raises(ValueError):
        voice_provider_factory("nope", settings)
