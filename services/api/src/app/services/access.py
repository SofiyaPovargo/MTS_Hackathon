"""Server-side access control. Never trust the UI with permissions."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import Role
from app.domain.errors import PermissionDenied
from app.infrastructure.db import repositories
from app.infrastructure.db.models import Task, User


class AccessService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def require_manager(self, actor: User) -> None:
        if actor.role is not Role.manager:
            raise PermissionDenied("manager role required")

    def require_team_manager(self, actor: User, team_id: object) -> None:
        if actor.role is not Role.manager or actor.team_id is None or str(actor.team_id) != str(
            team_id
        ):
            raise PermissionDenied("manager of the team required")

    async def require_accessible_task(self, actor: User, task: Task | None) -> Task:
        if task is None:
            raise PermissionDenied("task not found")
        if actor.role is Role.manager:
            await self._require_task_in_team(actor, task)
            return task
        if task.assignee_user_id != actor.id:
            raise PermissionDenied("task belongs to another user")
        return task

    async def _require_task_in_team(self, actor: User, task: Task) -> None:
        task_user = await repositories.get_user(self._session, task.assignee_user_id)
        if (
            task_user is None
            or actor.team_id is None
            or task_user.team_id is None
            or task_user.team_id != actor.team_id
        ):
            raise PermissionDenied("task belongs to another team")

    async def require_manager_of_actor_team(self, actor: User) -> None:
        if actor.role is not Role.manager or actor.team_id is None:
            raise PermissionDenied("manager of a team required")
        team = await repositories.get_team(self._session, actor.team_id)
        if team is None or team.manager_id != actor.id:
            raise PermissionDenied("not the manager of the team")