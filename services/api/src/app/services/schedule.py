"""Calendar events, reminders and message drafts for confirmed agreements.

Every external write here is triggered by an explicit user action on a task
whose agreement is ``confirmed``. Nothing is created automatically, and a
message is only ever *drafted* — sending stays with the user (AGENTS.md,
"Product rules"). Reminder timestamps are validated against UTC; the user's
timezone is only used to interpret a date-only task.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import AgreementStatus, ReminderChannel, ReminderStatus, TaskStatus
from app.domain.errors import NotFound, ValidationFailed
from app.infrastructure.db import repositories
from app.infrastructure.db.models import Agreement, Call, Reminder, Task, User
from app.integrations.outbound import CalendarPort, MessagingPort, RemindersPort, make_ics_event
from app.services.jobs import AnalysisQueuePort

DEFAULT_EVENT_DURATION = timedelta(minutes=30)
DEFAULT_EVENT_TIME = time(9, 0)


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def task_window(
    task: Task, tz: ZoneInfo, *, duration: timedelta = DEFAULT_EVENT_DURATION
) -> tuple[datetime, datetime]:
    """Resolve a task's due date/time to a UTC-aware start/end window."""
    if task.due_date is None:
        raise ValidationFailed("task has no due date to schedule")
    start_local = datetime.combine(task.due_date, task.due_time or DEFAULT_EVENT_TIME, tzinfo=tz)
    start = start_local.astimezone(UTC)
    return start, start + duration


def _draft_text(task: Task, agreement: Agreement) -> str:
    due = ""
    if task.due_date is not None:
        due = f" Срок — {task.due_date.isoformat()}."
    return f"Здравствуйте! По итогам нашего разговора: {task.title}.{due}"


class ScheduleService:
    """User-confirmed side effects: calendar event, reminder, message draft."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        calendar: CalendarPort,
        reminders: RemindersPort,
        messaging: MessagingPort,
        jobs: AnalysisQueuePort | None = None,
    ) -> None:
        self._session = session
        self._calendar = calendar
        self._reminders = reminders
        self._messaging = messaging
        self._jobs = jobs

    # -- guards ---------------------------------------------------------------

    async def _require_confirmed(self, task: Task) -> Agreement:
        if task.status is TaskStatus.canceled:
            raise ValidationFailed("canceled tasks cannot be scheduled")
        if task.agreement_id is None:
            raise ValidationFailed("task is not linked to an agreement")
        agreement = await repositories.get_agreement(self._session, task.agreement_id)
        if agreement is None or agreement.status is not AgreementStatus.confirmed:
            raise ValidationFailed("only confirmed agreements can be scheduled")
        return agreement

    async def _call_for(self, agreement: Agreement) -> Call:
        call = await repositories.get_call(self._session, agreement.call_id)
        if call is None:
            raise NotFound("call not found")
        return call

    # -- calendar -------------------------------------------------------------

    async def calendar_event(self, user: User, task: Task) -> dict[str, object]:
        agreement = await self._require_confirmed(task)
        starts_at, ends_at = task_window(task, _zone(user.timezone))
        event_id = await self._calendar.create_event(
            title=task.title,
            starts_at=starts_at,
            ends_at=ends_at,
            notes=f"Из звонка: {agreement.source_quote}",
        )
        task.calendar_event_id = event_id
        await repositories.record_audit(
            self._session,
            entity_type="task",
            entity_id=task.id,
            action="task.calendar_created",
            actor_user_id=user.id,
            payload={"event_id": event_id},
        )
        await self._session.flush()
        return {
            "task_id": task.id,
            "event_id": event_id,
            "title": task.title,
            "starts_at": starts_at,
            "ends_at": ends_at,
        }

    async def delete_calendar_event(self, user: User, task: Task) -> str:
        """Remove a previously created calendar event (explicit user action).

        Only the event stored on the task is touched; nothing is deleted in an
        external system without this call, which the user triggers.
        """
        event_id = task.calendar_event_id
        if event_id is None:
            raise NotFound("task has no calendar event")
        await self._calendar.delete_event(event_id=event_id)
        task.calendar_event_id = None
        await repositories.record_audit(
            self._session,
            entity_type="task",
            entity_id=task.id,
            action="task.calendar_deleted",
            actor_user_id=user.id,
            payload={"event_id": event_id},
        )
        await self._session.flush()
        return event_id

    async def ics(self, user: User, task: Task) -> str:
        """Deterministic ``.ics`` the user can import without any integration."""
        await self._require_confirmed(task)
        starts_at, ends_at = task_window(task, _zone(user.timezone))
        return make_ics_event(
            title=task.title,
            starts_at=starts_at,
            ends_at=ends_at,
            notes=task.description,
        )

    # -- reminders ------------------------------------------------------------

    async def create_reminder(
        self,
        user: User,
        task: Task,
        *,
        remind_at: datetime,
        channel: ReminderChannel,
    ) -> Reminder:
        await self._require_confirmed(task)
        normalized = remind_at if remind_at.tzinfo is not None else remind_at.replace(tzinfo=UTC)
        if normalized <= datetime.now(UTC):
            raise ValidationFailed("remind_at must be in the future")
        reminder = Reminder(
            task_id=task.id,
            remind_at=normalized,
            channel=channel,
            status=ReminderStatus.scheduled,
        )
        self._session.add(reminder)
        await self._session.flush()
        external_id = await self._reminders.create_reminder(task=task, remind_at=normalized)
        if channel is ReminderChannel.push and self._jobs is not None:
            # Queue the push for ``remind_at``; the worker delivers it (FCM/APNs).
            self._jobs.enqueue_reminder(str(reminder.id), eta=normalized)
        await repositories.record_audit(
            self._session,
            entity_type="task",
            entity_id=task.id,
            action="task.reminder_created",
            actor_user_id=user.id,
            payload={"reminder_id": str(reminder.id), "external_id": external_id},
        )
        await self._session.flush()
        return reminder

    async def list_reminders(self, task: Task) -> list[Reminder]:
        return list(await repositories.list_reminders_for_task(self._session, task.id))

    async def cancel_reminder(self, user: User, task: Task, reminder: Reminder) -> Reminder:
        if reminder.status is ReminderStatus.canceled:
            return reminder
        reminder.status = ReminderStatus.canceled
        await repositories.record_audit(
            self._session,
            entity_type="task",
            entity_id=task.id,
            action="task.reminder_canceled",
            actor_user_id=user.id,
            payload={"reminder_id": str(reminder.id)},
        )
        await self._session.flush()
        return reminder

    # -- message draft --------------------------------------------------------

    async def draft_message(self, user: User, task: Task) -> dict[str, object]:
        """Produce a draft only. Sending is the user's action, never ours."""
        agreement = await self._require_confirmed(task)
        call = await self._call_for(agreement)
        text = _draft_text(task, agreement)
        draft_id = await self._messaging.draft_message(phone=call.contact_phone, text=text)
        await repositories.record_audit(
            self._session,
            entity_type="task",
            entity_id=task.id,
            action="task.message_drafted",
            actor_user_id=user.id,
            payload={"draft_id": draft_id, "phone": call.contact_phone},
        )
        await self._session.flush()
        return {
            "task_id": task.id,
            "draft_id": draft_id,
            "phone": call.contact_phone,
            "text": text,
            "sent": False,
        }
