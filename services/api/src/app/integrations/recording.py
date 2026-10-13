"""Port for fetching a finished call recording from the voice provider.

МТС Exolve records at the SIP-resource level and announces the finished record
through the ``crr`` progress notification; the audio itself is then pulled with
the Call Record API (plan.md §11.1). That provider-specific step stays behind
this interface so the services and the ML pipeline never talk to a concrete
provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProviderRecording:
    """One finished recording fetched from the voice provider."""

    data: bytes
    content_type: str


class CallRecordingPort(Protocol):
    """Fetch a finished recording by the provider's own record id."""

    async def fetch_recording(self, uid: str) -> ProviderRecording: ...
