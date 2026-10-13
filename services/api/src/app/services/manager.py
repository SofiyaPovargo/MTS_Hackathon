"""Manager dashboard: team tasks, members and analytics.

Every method re-checks role and team membership on the server. A manager sees
tasks and metadata only — never subordinates' audio or transcripts.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import TaskStatus
from app.domain.errors import NotFound
from app.domain.rules import resolve_task_status
from app.infrastructure.db import repositories
from app.infrastructure.db.models import Team, User
from app.services.access import AccessService


class ManagerDashboardService:
    def __init__(self, session: AsyncSession, access: AccessService) -> None:
        self._session = session
        self._access = access

    async def _team(self, actor: User) -> Team:
        self._access.require_manager(actor)
        if actor.team_id is None:
            from app.domain.errors import PermissionDenied

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
        status: str | None = None,
        due_before: date | None = None,
        today: date | None = None,
    ) -> list[dict[str, object]]:
        team = await self._team(actor)
        if user_id is not None and user_id != actor.id:
            # The manager may filter by any member of their own team.
            members = await repositories.list_team_members(self._session, team.id)
            if not any(member.id == user_id for member in members):
                from app.domain.errors import PermissionDenied

                raise PermissionDenied("user is not in the team")

        tasks = await repositories.list_tasks_for_team(
            self._session,
            team.id,
            user_id=user_id,
            status=status,
            due_before=due_before.isoformat() if due_before else None,
        )
        today = today or date.today()
        rows: list[dict[str, object]] = []
        for task in tasks:
            resolved = resolve_task_status(task.status, task.due_date, today=today)
            rows.append(
                {
                    "id": str(task.id),
                    "assignee_user_id": str(task.assignee_user_id),
                    "agreement_id": str(task.agreement_id) if task.agreement_id else None,
                    "title": task.title,
                    "description": task.description,
                    "due_date": task.due_date,
                    "due_time": task.due_time,
                    "priority": task.priority.value,
                    "status": resolved.value,
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
        tasks = await repositories.list_tasks_for_team(self._session, team.id)

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
                and task.created_at is not None
            ):
                done_on_time += 1
                close_hours.append((task.completed_at - task.created_at).total_seconds() / 3600)
            if resolved is TaskStatus.overdue:
                overdue += 1
            if task.agreement_id is not None:
                from_agreement += 1

        total_tasks = len(tasks)
        done_tasks = statuses[TaskStatus.done.value]
        on_time_percent = round(done_on_time / done_tasks * 100, 1) if done_tasks else 0.0
        avg_close_hours = round(sum(close_hours) / len(close_hours), 1) if close_hours else None
        from_call_percent = round(from_agreement / total_tasks * 100, 1) if total_tasks else 0.0

        return {
            "members_count": len(members),
            "tasks_total": total_tasks,
            "tasks_by_status": statuses,
            "overdue": overdue,
            "done_on_time": done_on_time,
            "done_on_time_percent": on_time_percent,
            "avg_close_hours": avg_close_hours,
            "tasks_from_calls_percent": from_call_percent,
        }