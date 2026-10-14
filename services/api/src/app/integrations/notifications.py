"""Push delivery for reminders.

The worker ``send_reminder`` delivers a due reminder through this port. Real
providers (FCM for Android, APNs for iOS) are adapters added behind the port;
without credentials the ``Null`` adapter logs the notification and reports
success, so the queue/worker plumbing is fully testable and the demo keeps
working offline (AGENTS.md: every external integration must be mockable).
"""

from __future__ import annotations

import logging
from typing import Protocol

from app.infrastructure.db.models import User

logger = logging.getLogger(__name__)


class PushPort(Protocol):
    async def send(
        self, *, user: User, title: str, body: str, data: dict[str, str]
    ) -> str | None: ...


class NullPush:
    """Log-only adapter: no device tokens, no network. Returns no message id."""

    async def send(
        self, *, user: User, title: str, body: str, data: dict[str, str]
    ) -> str | None:
        logger.info("push (null adapter) to user %s: %s — %s %s", user.id, title, body, data)
        return None


def push_factory(name: str) -> PushPort:
    """Real providers (``fcm``/``apns``) are added later; ``null`` is the default."""
    if name in {"", "null", "local"}:
        return NullPush()
    raise ValueError(f"unknown push provider: {name}")
