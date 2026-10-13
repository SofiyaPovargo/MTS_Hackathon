"""Task lifecycle. A task is created only from a confirmed agreement."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import Owner, ReminderStatus, TaskPriority, TaskStatus
from app.domain.errors import NotFound, ValidationFailed
from app.domain.rules import can_create_task, resolve_task_status
from app.infrastructure.db import repositories
from app.infrastructure.db.models import Agreement, Task, User

TASK_STATUS_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.new: frozenset({TaskStatus.in_progress, TaskStatus.done, TaskStatus.canceled}),
    TaskStatus.in_progress: frozenset({TaskStatus.done, TaskStatus.canceled}),
    TaskStatus.done: frozenset(),
    TaskStatus.canceled: frozenset(),
    TaskStatus.overdue: frozenset({TaskStatus.in_progress, TaskStatus.done, TaskStatus.canceled}),
}

EDITABLE_TASK_FIELDS = frozenset({"title", "description", "due_date", "due_time", "priority"})


def _coerce_change(field: str, value: Any) -> Any:
    """Sync pushes arrive as raw JSON; coerce to domain types like Pydantic does."""
    if value is None:
        return None
    if field == "due_date" and isinstance(value, str):
        return date.fromisoformat(value)
    if field == "due_time" and isinstance(value, str):
        return time.fromisoformat(value)
    if field in ("priority", "status") and isinstance(value, str):
        return TaskPriority(value) if field == "priority" else TaskStatus(value)
    return value


def _seconds_of(value: time | None) -> int:
    """Seconds since midnight; a date-only due date counts as 00:00."""
    if value is None:
        return 0
    return value.hour * 3600 + value.minute * 60 + value.second


class TaskService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_from_agreement(self, agreement: Agreement, *, actor: User) -> Task:
        if not can_create_task(
            agreement.status, confidence=float(agreement.confidence)
        ):
            raise ValidationFailed(
                f"task requires a confirmed agreement, got {agreement.status.value}"
            )
        call = await repositories.get_call(self._session, agreement.call_id)
        if call is None:
            raise NotFound("call not found")

        assignee_id = call.user_id
        if agreement.owner is Owner.user and agreement.owner_user_id is not None:
            assignee_id = agreement.owner_user_id
        assignee = await repositories.get_user(self._session, assignee_id)
        if assignee is None:
            raise ValueError("agreement owner is not a user")

        task = Task(
            agreement_id=agreement.id,
            assignee_user_id=assignee.id,
            title=agreement.title,
            description=f"Из звонка: {agreement.source_quote}",
            due_date=agreement.due_date,
            due_time=agreement.due_time,
            priority=TaskPriority.medium,
            status=TaskStatus.new,
        )
        self._session.add(task)
        await self._session.flush()
        await repositories.record_audit(
            self._session,
            entity_type="task",
            entity_id=task.id,
            action="task.created_from_agreement",
            actor_user_id=actor.id,
            payload={"agreement_id": str(agreement.id)},
        )
        await self._session.flush()
        return task

    async def get_for_user(self, user: User, task_id: uuid.UUID) -> Task:
        task = await repositories.get_task(self._session, task_id)
        if task is None or task.assignee_user_id != user.id:
            raise NotFound("task not found")
        return task

    # -- agreement -> task propagation ----------------------------------------

    async def sync_from_agreement(
        self,
        agreement: Agreement,
        *,
        actor: User,
        previous_due: tuple[date | None, time | None],
    ) -> Task | None:
        """Перенести правку (в т.ч. подтверждённой) договорённости на задачу.

        Доска и уведомления должны показывать актуальное значение, поэтому
        название, срок и ответственный задачи следуют за договорённостью.
        Напоминания, привязанные к старому сроку, сдвигаются на ту же дельту.
        Задача может отсутствовать (договорённость ещё не подтверждена).
        """
        task = await repositories.get_task_for_agreement(self._session, agreement.id)
        if task is None:
            return None

        changed: list[str] = []
        if task.title != agreement.title:
            task.title = agreement.title
            changed.append("title")
        if (task.due_date, task.due_time) != (agreement.due_date, agreement.due_time):
            task.due_date = agreement.due_date
            task.due_time = agreement.due_time
            changed.append("due_date")
        assignee_id = await self._assignee_for(agreement)
        if assignee_id != task.assignee_user_id:
            task.assignee_user_id = assignee_id
            changed.append("assignee_user_id")
        if not changed:
            return task

        task.version += 1
        await repositories.record_audit(
            self._session,
            entity_type="task",
            entity_id=task.id,
            action="task.updated_from_agreement",
            actor_user_id=actor.id,
            payload={"agreement_id": str(agreement.id), "fields": sorted(changed)},
        )
        await self._reschedule_reminders(task, previous_due=previous_due, actor=actor)
        await self._session.flush()
        return task

    async def cancel_for_agreement(self, agreement: Agreement, *, actor: User) -> Task | None:
        """Отклонили подтверждённую договорённость — отменяем её задачу.

        ``done``/``canceled`` не трогаем: завершённую работу не «разворачиваем».
        """
        task = await repositories.get_task_for_agreement(self._session, agreement.id)
        if task is None or task.status in (TaskStatus.done, TaskStatus.canceled):
            return task
        return await self.patch(actor, task, {"status": TaskStatus.canceled.value})

    async def _assignee_for(self, agreement: Agreement) -> uuid.UUID:
        if agreement.owner is Owner.user and agreement.owner_user_id is not None:
            return agreement.owner_user_id
        call = await repositories.get_call(self._session, agreement.call_id)
        if call is None:
            raise NotFound("call not found")
        return call.user_id

    async def _reschedule_reminders(
        self,
        task: Task,
        *,
        previous_due: tuple[date | None, time | None],
        actor: User,
    ) -> None:
        """Сдвинуть напоминания вместе с новым сроком (прошлые — отменить)."""
        old_date, old_time = previous_due
        new_date, new_time = task.due_date, task.due_time
        if old_date is None or new_date is None or (old_date, old_time) == (new_date, new_time):
            return
        delta = timedelta(
            days=(new_date - old_date).days,
            seconds=_seconds_of(new_time) - _seconds_of(old_time),
        )
        if delta == timedelta(0):
            return

        now = datetime.now(UTC)
        for reminder in await repositories.list_reminders_for_task(self._session, task.id):
            if reminder.status is not ReminderStatus.scheduled:
                continue
            shifted = reminder.remind_at + delta
            if shifted <= now:
                reminder.status = ReminderStatus.canceled
                action = "task.reminder_canceled"
            else:
                reminder.remind_at = shifted
                action = "task.reminder_rescheduled"
            await repositories.record_audit(
                self._session,
                entity_type="task",
                entity_id=task.id,
                action=action,
                actor_user_id=actor.id,
                payload={"reminder_id": str(reminder.id), "remind_at": str(reminder.remind_at)},
            )

    async def list_for_user(self, user: User, *, today: date | None = None) -> list[Task]:
        tasks = list(await repositories.list_tasks_for_user(self._session, user.id))
        today = today or date.today()
        for task in tasks:
            task.status = resolve_task_status(task.status, task.due_date, today=today)
        return tasks

    async def patch(self, user: User, task: Task, changes: dict[str, Any]) -> Task:
        provided = set(changes)
        forbidden = provided - EDITABLE_TASK_FIELDS - {"status"}
        if forbidden:
            raise ValidationFailed(f"fields are not editable: {', '.join(sorted(forbidden))}")

        if "status" in changes and changes["status"] is not None:
            target = TaskStatus(_coerce_change("status", changes["status"]))
            allowed = TASK_STATUS_TRANSITIONS[task.status]
            if target not in allowed:
                raise ValidationFailed(
                    f"cannot move task from {task.status.value} to {target.value}"
                )
            task.status = target

        for field in EDITABLE_TASK_FIELDS:
            if field in changes and changes[field] is not None:
                setattr(task, field, _coerce_change(field, changes[field]))

        if task.status is TaskStatus.done:
            task.completed_at = datetime.now(UTC)
        task.version += 1
        await repositories.record_audit(
            self._session,
            entity_type="task",
            entity_id=task.id,
            action="task.updated",
            actor_user_id=user.id,
            payload={"changes": sorted(changes)},
        )
        await self._session.flush()
        return task

    async def complete(self, user: User, task: Task) -> Task:
        return await self.patch(user, task, {"status": TaskStatus.done.value})