"""Deliver a due reminder through the push port.

The worker ``send_reminder`` calls this. Delivery is idempotent: a reminder that
is no longer ``scheduled`` (already ``sent``/``canceled``/``failed``) is left
untouched, so a redelivered job cannot notify the user twice. A failed provider
call marks the reminder ``failed`` and is re-raised so the queue can retry.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import ReminderStatus
from app.domain.errors import NotFound
from app.infrastructure.db import repositories
from app.infrastructure.db.models import Reminder
from app.integrations.notifications import PushPort


class ReminderDeliveryService:
    def __init__(self, session: AsyncSession, *, push: PushPort) -> None:
        self._session = session
        self._push = push

    async def deliver(self, reminder_id: uuid.UUID) -> Reminder:
        reminder = await repositories.get_reminder(self._session, reminder_id)
        if reminder is None:
            raise NotFound("reminder not found")
        if reminder.status is not ReminderStatus.scheduled:
            # Idempotent redelivery: the reminder was already handled.
            return reminder

        task = await repositories.get_task(self._session, reminder.task_id)
        if task is None:
            raise NotFound("task not found")
        user = await repositories.get_user(self._session, task.assignee_user_id)
        if user is None:
            raise NotFound("reminder assignee not found")

        data = {"task_id": str(task.id), "reminder_id": str(reminder.id)}
        try:
            external_id = await self._push.send(
                user=user, title="Напоминание", body=task.title, data=data
            )
        except Exception:
            reminder.status = ReminderStatus.failed
            await repositories.record_audit(
                self._session,
                entity_type="task",
                entity_id=task.id,
                action="task.reminder_failed",
                actor_user_id=None,
                payload={"reminder_id": str(reminder.id)},
            )
            await self._session.flush()
            raise

        reminder.status = ReminderStatus.sent
        reminder.sent_at = datetime.now(UTC)
        await repositories.record_audit(
            self._session,
            entity_type="task",
            entity_id=task.id,
            action="task.reminder_sent",
            actor_user_id=None,
            payload={"reminder_id": str(reminder.id), "external_id": external_id},
        )
        await self._session.flush()
        return reminder
