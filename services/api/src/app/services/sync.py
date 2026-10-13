"""Delta sync between the phone's local cache and the server.

The server is the single source of truth. The phone pulls deltas since a sync
token and pushes its outbox with idempotency keys; on conflict the server
returns the authoritative version.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import SyncEntity
from app.domain.errors import ValidationFailed
from app.infrastructure.db import repositories
from app.infrastructure.db.models import Agreement, Call, Task, User
from app.services.agreement import AgreementService
from app.services.task import TaskService

PUSH_SCOPE = "sync"


@dataclass(slots=True)
class SyncResult:
    entity_type: str
    entity_id: str
    status: str  # accepted | conflict | rejected
    version: int | None
    server_version: int | None = None
    message: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "status": self.status,
            "version": self.version,
            "server_version": self.server_version,
            "message": self.message,
        }


@dataclass(slots=True)
class SyncItem:
    entity_type: str
    id: str
    version: int
    updated_at: datetime
    data: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "entity_type": self.entity_type,
            "id": self.id,
            "version": self.version,
            "updated_at": self.updated_at,
            "data": self.data,
        }


class SyncService:
    def __init__(self, session: AsyncSession, tasks: TaskService, agreements: AgreementService) -> None:
        self._session = session
        self._tasks = tasks
        self._agreements = agreements

    # -- pull ------------------------------------------------------------------

    async def pull(self, user: User, since: datetime | None, *, limit: int = 100) -> dict[str, object]:
        changes: list[SyncItem] = []

        for call in await repositories.list_calls(self._session, user.id, limit=limit):
            changes.append(_call_item(call))
        for agreement in await repositories.list_agreements_for_user(self._session, user.id, limit=limit):
            changes.append(_agreement_item(agreement))
        for task in await repositories.list_tasks_for_user(self._session, user.id, limit=limit):
            changes.append(_task_item(task))

        if since is not None:
            changes = [change for change in changes if change.updated_at > since]

        changes.sort(key=lambda change: change.updated_at)
        # 'Z' instead of '+00:00' keeps the token safe inside URL query strings
        # ('+' would be decoded as a space by the client).
        token = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        return {
            "changes": [change.as_dict() for change in changes[:limit]],
            "sync_token": token,
            "has_more": len(changes) > limit,
        }

    # -- push ------------------------------------------------------------------

    async def push(self, user: User, operations: list[dict[str, object]]) -> dict[str, object]:
        results: list[SyncResult] = []
        for op in operations:
            results.append(await self._push_one(user, op))
        return {"results": [result.as_dict() for result in results]}

    async def _push_one(self, user: User, op: dict[str, object]) -> SyncResult:
        entity_type = str(op["entity_type"])
        entity_id = uuid.UUID(str(op["entity_id"]))
        operation = str(op["operation"])
        key = str(op["idempotency_key"])
        request_hash = hashlib.sha256(json.dumps(op, sort_keys=True, default=str).encode()).hexdigest()

        stored = await repositories.get_idempotent_response(
            self._session, user_id=user.id, scope=PUSH_SCOPE, key=key
        )
        if stored is not None:
            return _from_stored(stored.response_body, str(entity_id))

        if entity_type == SyncEntity.task.value:
            result = await self._push_task(user, entity_id, operation, op, key, request_hash)
        elif entity_type == SyncEntity.agreement.value:
            result = await self._push_agreement(user, entity_id, operation, op, key, request_hash)
        else:
            result = SyncResult(
                entity_type=entity_type,
                entity_id=str(entity_id),
                status="rejected",
                version=None,
                message=f"unsupported entity for push: {entity_type}",
            )
        await self._session.flush()
        return result

    async def _push_task(
        self,
        user: User,
        entity_id: uuid.UUID,
        operation: str,
        op: dict[str, object],
        key: str,
        request_hash: str,
    ) -> SyncResult:
        task = await repositories.get_task(self._session, entity_id)
        if task is None or task.assignee_user_id != user.id:
            return SyncResult("task", str(entity_id), "rejected", None, message="not found")

        incoming_version = op.get("version")
        if incoming_version is not None and incoming_version != task.version:
            return SyncResult(
                "task", str(entity_id), "conflict", None, task.version, message="version conflict"
            )

        payload = cast("dict[str, object]", op.get("payload", {}))
        try:
            if operation == "update":
                await self._tasks.patch(user, task, payload)
            elif operation == "delete":
                await self._tasks.patch(user, task, {"status": "canceled"})
            else:
                return SyncResult(
                    "task", str(entity_id), "rejected", None, task.version,
                    message=f"unsupported operation: {operation}",
                )
        except ValidationFailed as exc:
            return SyncResult(
                "task", str(entity_id), "rejected", task.version, task.version, message=str(exc)
            )

        await self._store(user, key, request_hash, op, "task", str(entity_id), task.version)
        return SyncResult("task", str(entity_id), "accepted", task.version)

    async def _push_agreement(
        self,
        user: User,
        entity_id: uuid.UUID,
        operation: str,
        op: dict[str, object],
        key: str,
        request_hash: str,
    ) -> SyncResult:
        agreement = await repositories.get_agreement(self._session, entity_id)
        if agreement is None:
            return SyncResult("agreement", str(entity_id), "rejected", None, message="not found")
        call = await repositories.get_call(self._session, agreement.call_id)
        if call is None or call.user_id != user.id:
            return SyncResult("agreement", str(entity_id), "rejected", None, message="not found")

        incoming_version = op.get("version")
        if incoming_version is not None and incoming_version != agreement.version:
            return SyncResult(
                "agreement", str(entity_id), "conflict", None, agreement.version,
                message="version conflict",
            )

        payload = cast("dict[str, object]", op.get("payload", {}))
        try:
            if operation == "update":
                await self._agreements.patch(user, agreement, payload)
            elif operation == "delete":
                await self._agreements.reject(user, agreement)
            else:
                return SyncResult(
                    "agreement", str(entity_id), "rejected", None, agreement.version,
                    message=f"unsupported operation: {operation}",
                )
        except ValidationFailed as exc:
            return SyncResult(
                "agreement", str(entity_id), "rejected", agreement.version, agreement.version,
                message=str(exc),
            )

        await self._store(user, key, request_hash, op, "agreement", str(entity_id), agreement.version)
        return SyncResult("agreement", str(entity_id), "accepted", agreement.version)

    async def _store(
        self,
        user: User,
        key: str,
        request_hash: str,
        op: dict[str, object],
        entity_type: str,
        entity_id: str,
        version: int,
    ) -> None:
        body: dict[str, object] = {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "status": "accepted",
            "version": version,
        }
        await repositories.store_idempotent_response(
            self._session,
            user_id=user.id,
            scope=PUSH_SCOPE,
            key=key,
            request_hash=request_hash,
            response_status=200,
            response_body=body,
        )


def _from_stored(body: dict[str, object], entity_id: str) -> SyncResult:
    version = body.get("version")
    return SyncResult(
        entity_type=str(body["entity_type"]),
        entity_id=str(body.get("entity_id") or entity_id),
        status=str(body["status"]),
        version=int(version) if isinstance(version, int) else None,
    )


def _call_item(call: Call) -> SyncItem:
    return SyncItem(
        entity_type="call",
        id=str(call.id),
        version=call.version,
        updated_at=call.updated_at,
        data={
            "id": str(call.id),
            "direction": call.direction.value,
            "contact_phone": call.contact_phone,
            "contact_name": call.contact_name,
            "status": call.status.value,
            "started_at": call.started_at,
            "answered_at": call.answered_at,
            "ended_at": call.ended_at,
            "recording_started_at": call.recording_started_at,
            "summary": call.summary,
        },
    )


def _agreement_item(agreement: Agreement) -> SyncItem:
    return SyncItem(
        entity_type="agreement",
        id=str(agreement.id),
        version=agreement.version,
        updated_at=agreement.updated_at,
        data={
            "id": str(agreement.id),
            "call_id": str(agreement.call_id),
            "owner": agreement.owner.value,
            "owner_user_id": str(agreement.owner_user_id) if agreement.owner_user_id else None,
            "type": agreement.type,
            "title": agreement.title,
            "object": agreement.object,
            "due_date": agreement.due_date,
            "due_time": agreement.due_time,
            "amount": float(agreement.amount) if agreement.amount is not None else None,
            "currency": agreement.currency,
            "source_quote": agreement.source_quote,
            "audio_start": float(agreement.audio_start),
            "audio_end": float(agreement.audio_end),
            "confidence": float(agreement.confidence),
            "status": agreement.status.value,
        },
    )


def _task_item(task: Task) -> SyncItem:
    return SyncItem(
        entity_type="task",
        id=str(task.id),
        version=task.version,
        updated_at=task.updated_at,
        data={
            "id": str(task.id),
            "agreement_id": str(task.agreement_id) if task.agreement_id else None,
            "assignee_user_id": str(task.assignee_user_id),
            "title": task.title,
            "description": task.description,
            "due_date": task.due_date,
            "due_time": task.due_time,
            "priority": task.priority.value,
            "status": task.status.value,
        },
    )