"""Manager dashboard: team tasks, members and analytics.

Every method re-checks role and team membership on the server. A manager sees
tasks and metadata only — never subordinates' audio or transcripts.

The board (``plan.md`` §15) is assembled here: column filters run in SQL, the
derived ``overdue`` status and the board ordering are resolved against "today",
and each card is enriched with the client and call-source metadata.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import TaskPriority, TaskSort, TaskStatus
from app.domain.errors import NotFound, PermissionDenied
from app.domain.rules import resolve_task_status
from app.infrastructure.db import repositories
from app.infrastructure.db.models import Task, Team, User
from app.services.access import AccessService

_PRIORITY_ORDER: dict[TaskPriority, int] = {
    TaskPriority.high: 0,
    TaskPriority.medium: 1,
    TaskPriority.low: 2,
}


def _board_sort_key(task: Task, resolved: TaskStatus, *, sort: TaskSort) -> tuple[int, date, float]:
    """Board ordering. Default is overdue first, then the nearest deadline."""
    created_rank = -task.created_at.timestamp()
    due = task.due_date or date.max
    if sort is TaskSort.priority:
        return (_PRIORITY_ORDER[task.priority], due, created_rank)
    if sort is TaskSort.created:
        return (0, date.max, created_rank)
    if sort is TaskSort.overdue:
        return (0 if resolved is TaskStatus.overdue else 1, due, created_rank)
    return (0, due, created_rank)


def _summarize(tasks: Sequence[Task], *, today: date) -> dict[str, object]:
    """Aggregate metrics shared by the team and per-member analytics (§15)."""
    statuses: dict[str, int] = {status.value: 0 for status in TaskStatus}
    done_on_time = 0
    overdue = 0
    close_hours: list[float] = []
    from_agreement = 0
    for task in tasks:
        resolved = resolve_task_status(task.status, task.due_date, today=today)
        statuses[resolved.value] += 1
        if (
            resolved is TaskStatus.done
            and task.completed_at is not None
            and task.due_date is not None
            and task.completed_at.date() <= task.due_date
        ):
            done_on_time += 1
            close_hours.append((task.completed_at - task.created_at).total_seconds() / 3600)
        if resolved is TaskStatus.overdue:
            overdue += 1
        if task.agreement_id is not None:
            from_agreement += 1

    total = len(tasks)
    done = statuses[TaskStatus.done.value]
    return {
        "tasks_total": total,
        "tasks_by_status": statuses,
        "overdue": overdue,
        "done_on_time": done_on_time,
        "done_on_time_percent": round(done_on_time / done * 100, 1) if done else 0.0,
        "avg_close_hours": round(sum(close_hours) / len(close_hours), 1) if close_hours else None,
        "tasks_from_calls_percent": round(from_agreement / total * 100, 1) if total else 0.0,
    }


class ManagerDashboardService:
    def __init__(self, session: AsyncSession, access: AccessService) -> None:
        self._session = session
        self._access = access

    async def _team(self, actor: User) -> Team:
        self._access.require_manager(actor)
        if actor.team_id is None:
            raise PermissionDenied("manager has no team")
        team = await repositories.get_team(self._session, actor.team_id)
        if team is None:
            raise NotFound("team not found")
        return team

    async def team_tasks(
        self,
        actor: User,
        *,
        user_id: uuid.UUID | None = None,
        status: TaskStatus | None = None,
        priority: TaskPriority | None = None,
        task_type: str | None = None,
        due_before: date | None = None,
        due_after: date | None = None,
        sort: TaskSort = TaskSort.overdue,
        today: date | None = None,
    ) -> list[dict[str, object]]:
        team = await self._team(actor)
        members = await repositories.list_team_members(self._session, team.id)
        if user_id is not None and not any(member.id == user_id for member in members):
            # The manager may filter by any member of their own team, and by nobody else.
            raise PermissionDenied("user is not in the team")

        tasks = list(
            await repositories.list_tasks_for_team(
                self._session,
                team.id,
                user_id=user_id,
                priority=priority,
                due_before=due_before,
                due_after=due_after,
                agreement_type=task_type,
            )
        )
        today = today or date.today()

        resolved: dict[uuid.UUID, TaskStatus] = {}
        board: list[Task] = []
        for task in tasks:
            value = resolve_task_status(task.status, task.due_date, today=today)
            if status is not None and value is not status:
                continue
            resolved[task.id] = value
            board.append(task)
        board.sort(key=lambda task: _board_sort_key(task, resolved[task.id], sort=sort))

        names = {member.id: member.full_name for member in members}
        agreements = {
            agreement.id: agreement
            for agreement in await repositories.list_agreements_by_ids(
                self._session,
                {task.agreement_id for task in board if task.agreement_id is not None},
            )
        }
        calls = {
            call.id: call
            for call in await repositories.list_calls_by_ids(
                self._session, {agreement.call_id for agreement in agreements.values()}
            )
        }

        rows: list[dict[str, object]] = []
        for task in board:
            agreement = agreements.get(task.agreement_id) if task.agreement_id else None
            call = calls.get(agreement.call_id) if agreement is not None else None
            rows.append(
                {
                    "id": str(task.id),
                    "assignee_user_id": str(task.assignee_user_id),
                    "assignee_name": names.get(task.assignee_user_id),
                    "agreement_id": str(task.agreement_id) if task.agreement_id else None,
                    "agreement_type": agreement.type if agreement else None,
                    "call_id": str(call.id) if call else None,
                    "contact_name": call.contact_name if call else None,
                    "contact_phone": call.contact_phone if call else None,
                    "title": task.title,
                    "description": task.description,
                    "due_date": task.due_date,
                    "due_time": task.due_time,
                    "priority": task.priority.value,
                    "status": resolved[task.id].value,
                    "version": task.version,
                    "created_at": task.created_at,
                    "updated_at": task.updated_at,
                }
            )
        return rows

    async def team_members(self, actor: User) -> list[dict[str, object]]:
        team = await self._team(actor)
        members = await repositories.list_team_members(self._session, team.id)
        return [
            {
                "id": str(member.id),
                "phone": member.phone,
                "full_name": member.full_name,
                "role": member.role.value,
            }
            for member in members
        ]

    async def team_stats(self, actor: User, *, today: date | None = None) -> dict[str, object]:
        team = await self._team(actor)
        today = today or date.today()
        members = await repositories.list_team_members(self._session, team.id)
        tasks = list(await repositories.list_tasks_for_team(self._session, team.id))
        agreements_by_member = await repositories.count_agreements_by_member(self._session, team.id)

        per_member: list[dict[str, object]] = []
        for member in members:
            member_tasks = [task for task in tasks if task.assignee_user_id == member.id]
            per_member.append(
                {
                    "user_id": str(member.id),
                    "full_name": member.full_name,
                    "agreements_total": agreements_by_member.get(member.id, 0),
                    **_summarize(member_tasks, today=today),
                }
            )

        return {
            "members_count": len(members),
            # "Количество созданных договоренностей" for the team (§15).
            "agreements_total": sum(agreements_by_member.values()),
            **_summarize(tasks, today=today),
            "members": per_member,
        }
