"""External-system adapters behind common ports.

A new provider is added as an adapter; the ML pipeline, the mobile UI and the
business rules do not change. In stage 1 the Voice Provider is a mock.
"""

from __future__ import annotations

from typing import Protocol

from app.config import Settings
from app.integrations.exolve import ExolveVoiceProvider


class VoiceProviderPort(Protocol):
    """Interface of the Voice Provider (Twilio-like adapter in production)."""

    async def answer(self, call_external_id: str) -> None: ...
    async def hangup(self, call_external_id: str) -> None: ...
    async def play_notice(self, call_external_id: str, notice_id: str) -> None: ...
    async def play_consent_prompt(self, call_external_id: str) -> None: ...
    async def collect_dtmf(self, call_external_id: str) -> str | None: ...
    async def start_recording(self, call_external_id: str) -> str: ...
    async def open_media_stream(self, call_external_id: str) -> str: ...


class VoiceProviderFactory(Protocol):
    def __call__(self, name: str) -> VoiceProviderPort: ...


class MockVoiceProvider:
    """Deterministic double used in tests and demo mode.

    Every call is recorded into ``history`` so tests can assert that, for
    example, ``start_recording`` was never invoked without consent.
    """

    def __init__(self) -> None:
        self.history: list[tuple[str, str]] = []
        self.dtmf_response: str | None = None

    def _log(self, op: str, call_external_id: str) -> None:
        self.history.append((op, call_external_id))

    async def answer(self, call_external_id: str) -> None:
        self._log("answer", call_external_id)

    async def hangup(self, call_external_id: str) -> None:
        self._log("hangup", call_external_id)

    async def play_notice(self, call_external_id: str, notice_id: str) -> None:
        self._log(f"play_notice:{notice_id}", call_external_id)

    async def play_consent_prompt(self, call_external_id: str) -> None:
        self._log("play_consent_prompt", call_external_id)

    async def collect_dtmf(self, call_external_id: str) -> str | None:
        self._log("collect_dtmf", call_external_id)
        return self.dtmf_response

    async def start_recording(self, call_external_id: str) -> str:
        self._log("start_recording", call_external_id)
        return f"rec-{call_external_id}"

    async def open_media_stream(self, call_external_id: str) -> str:
        self._log("open_media_stream", call_external_id)
        return f"stream-{call_external_id}"


def voice_provider_factory(name: str, settings: Settings) -> VoiceProviderPort:
    if name == "mock":
        return MockVoiceProvider()
    if name == "exolve":
        return ExolveVoiceProvider(settings)
    raise ValueError(f"unknown voice provider: {name}")