"""Agreement lifecycle: detection, user edits, confirmation, rejection.

Raw LLM output, validated output and user edits are stored separately
(``agreement_extractions``, ``agreement_edits``) so every step is auditable.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, time
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.domain.commitment import Commitment
from app.domain.enums import AgreementStatus, Owner
from app.domain.errors import NotFound, PermissionDenied, ValidationFailed
from app.domain.rules import AmbiguityFlags, resolve_agreement_status
from app.infrastructure.db import repositories
from app.infrastructure.db.models import Agreement, Call, User
from app.services.task import TaskService

# Fields the user may edit. Quote and audio timestamps stay immutable for audit.
EDITABLE_FIELDS = frozenset(
    {
        "type",
        "title",
        "object",
        "owner",
        "owner_user_id",
        "due_date",
        "due_time",
        "amount",
        "currency",
    }
)

_COMPACT = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]")


def _normalize_quote(text: str) -> str:
    """Стабильная нормализация цитаты для fingerprint (регистр/пунктуация/ё)."""
    cleaned = _PUNCT.sub(" ", (text or "").lower().replace("ё", "е"))
    return _COMPACT.sub(" ", cleaned).strip()


def _fingerprint(type: str, owner: Owner, source_quote: str) -> str:
    return f"{type}|{owner.value}|{_normalize_quote(source_quote)}"


def _json_safe(value: object) -> object:
    """JSONB cannot encode dates, times, decimals or UUIDs; keep them as strings."""
    if isinstance(value, (date, time, Decimal, uuid.UUID)):
        return str(value)
    return value


def _coerce_change(field: str, value: Any) -> Any:
    """Sync/LLM payloads arrive as raw JSON; coerce them to domain types.

    The HTTP routes already coerce through Pydantic, but the sync push and the
    extraction pipeline hand us plain values — the same rules must hold there.
    """
    if value is None:
        return None
    if field == "due_date" and isinstance(value, str):
        return date.fromisoformat(value)
    if field == "due_time" and isinstance(value, str):
        return time.fromisoformat(value)
    if field == "amount" and isinstance(value, (str, int, float)):
        return Decimal(str(value))
    if field == "owner" and isinstance(value, str):
        return Owner(value)
    if field == "owner_user_id" and isinstance(value, str):
        return uuid.UUID(value)
    return value


class AgreementService:
    def __init__(self, session: AsyncSession, settings: Settings, tasks: TaskService) -> None:
        self._session = session
        self._settings = settings
        self._tasks = tasks

    # -- queries --------------------------------------------------------------

    async def get_owned(self, user: User, agreement_id: uuid.UUID) -> Agreement:
        agreement = await repositories.get_agreement(self._session, agreement_id)
        if agreement is None:
            raise NotFound("agreement not found")
        await self._require_owner(user, agreement)
        return agreement

    async def list_for_user(self, user: User) -> list[Agreement]:
        return list(await repositories.list_agreements_for_user(self._session, user.id))

    async def _require_owner(self, user: User, agreement: Agreement) -> None:
        call = await repositories.get_call(self._session, agreement.call_id)
        if call is None:
            raise NotFound("call not found")
        if call.user_id != user.id:
            raise PermissionDenied("agreement belongs to another user")

    # -- creation ------------------------------------------------------------

    async def create_from_commitment(
        self,
        user: User,
        call: Call,
        commitment: Commitment,
        *,
        model: str,
        prompt_version: str,
        raw_output: dict[str, Any],
        extra_ambiguity: AmbiguityFlags | None = None,
    ) -> Agreement:
        """Validated LLM output becomes an agreement; the raw output is kept apart."""
        status = commitment.status_for(self._settings.confidence_threshold)
        if extra_ambiguity is not None and extra_ambiguity.is_ambiguous:
            status = AgreementStatus.needs_clarification

        owner_user_id = None
        if commitment.owner is Owner.user and commitment.owner_user_id is not None:
            owner_user_id = uuid.UUID(commitment.owner_user_id)

        agreement = Agreement(
            call_id=call.id,
            owner=commitment.owner,
            owner_user_id=owner_user_id,
            type=commitment.type,
            title=commitment.title,
            object=commitment.object,
            due_date=commitment.due_date,
            due_time=commitment.due_time,
            amount=commitment.amount,
            currency=commitment.currency,
            source_quote=commitment.source_quote,
            audio_start=float(commitment.audio_start),
            audio_end=float(commitment.audio_end),
            confidence=Decimal(str(commitment.confidence)),
            status=status,
        )
        self._session.add(agreement)
        await self._session.flush()

        from app.infrastructure.db.models import AgreementExtraction

        self._session.add(
            AgreementExtraction(
                call_id=call.id,
                agreement_id=agreement.id,
                model=model,
                prompt_version=prompt_version,
                raw_output=raw_output,
                validated_output=commitment.model_dump(mode="json"),
            )
        )
        await repositories.record_audit(
            self._session,
            entity_type="agreement",
            entity_id=agreement.id,
            action="agreement.detected",
            actor_user_id=user.id,
            payload={"status": status.value, "confidence": float(commitment.confidence)},
        )
        await self._session.flush()
        return agreement

    async def upsert_from_commitment(
        self,
        user: User,
        call: Call,
        commitment: Commitment,
        *,
        model: str,
        prompt_version: str,
        raw_output: dict[str, Any],
    ) -> tuple[Agreement, bool]:
        """Создать или обновить системную договорённость (идемпотентно по fingerprint).

        Live-извлечение перезапускается по мере роста транскрипта, поэтому одна и
        та же договорённость приходит многократно. Идентичность держит fingerprint
        (type + owner + цитата): новые создаём, изменённые обновляем (bump
        ``version``), а подтверждённые/отклонённые пользователем не трогаем.
        Возвращает ``(agreement, changed)``.
        """
        fingerprint = _fingerprint(commitment.type, commitment.owner, commitment.source_quote)
        existing = await repositories.list_agreements_for_call(self._session, call.id)
        match = next(
            (a for a in existing if _fingerprint(a.type, a.owner, a.source_quote) == fingerprint),
            None,
        )
        if match is None:
            agreement = await self.create_from_commitment(
                user, call, commitment, model=model, prompt_version=prompt_version, raw_output=raw_output
            )
            return agreement, True
        if match.status in (AgreementStatus.confirmed, AgreementStatus.rejected):
            return match, False

        status = commitment.status_for(self._settings.confidence_threshold)
        updates: dict[str, Any] = {
            "title": commitment.title,
            "object": commitment.object,
            "due_date": commitment.due_date,
            "due_time": commitment.due_time,
            "amount": commitment.amount,
            "currency": commitment.currency,
            "confidence": Decimal(str(commitment.confidence)),
            "status": status,
            "audio_start": float(commitment.audio_start),
            "audio_end": float(commitment.audio_end),
        }
        changed = False
        for field, value in updates.items():
            if getattr(match, field) != value:
                setattr(match, field, value)
                changed = True
        if not changed:
            return match, False
        match.version += 1
        await repositories.record_audit(
            self._session,
            entity_type="agreement",
            entity_id=match.id,
            action="agreement.updated",
            actor_user_id=user.id,
            payload={"status": status.value},
        )
        await self._session.flush()
        return match, True

    async def create_manual(
        self,
        user: User,
        call: Call,
        *,
        type: str,
        title: str,
        object: str | None,
        owner: Owner,
        owner_user_id: uuid.UUID | None,
        due_date: date | None,
        due_time: time | None,
        amount: Decimal | None,
        currency: str | None,
    ) -> Agreement:
        """Manual entry (no-consent path): the quote is the user's own words."""
        agreement = Agreement(
            call_id=call.id,
            owner=owner,
            owner_user_id=owner_user_id,
            type=type,
            title=title,
            object=object,
            due_date=due_date,
            due_time=due_time,
            amount=amount,
            currency=currency,
            source_quote="manual entry",
            audio_start=0,
            audio_end=0,
            confidence=Decimal("1.00"),
            status=AgreementStatus.detected,
        )
        self._session.add(agreement)
        await self._session.flush()
        await repositories.record_audit(
            self._session,
            entity_type="agreement",
            entity_id=agreement.id,
            action="agreement.manual_created",
            actor_user_id=user.id,
        )
        await self._session.flush()
        return agreement

    # -- user actions ----------------------------------------------------------

    async def patch(self, user: User, agreement: Agreement, changes: dict[str, Any]) -> Agreement:
        provided = set(changes)
        forbidden = provided - EDITABLE_FIELDS
        if forbidden:
            raise ValidationFailed(f"fields are not editable: {', '.join(sorted(forbidden))}")

        changed: dict[str, Any] = {}
        for field in EDITABLE_FIELDS & provided:
            new_value = _coerce_change(field, changes[field])
            if new_value is not None and new_value != getattr(agreement, field):
                changed[field] = _json_safe(new_value)
                setattr(agreement, field, new_value)

        if changed:
            await repositories.record_agreement_edit(
                self._session,
                agreement_id=agreement.id,
                actor_user_id=user.id,
                changes=changed,
            )
            agreement.version += 1
            if agreement.status is AgreementStatus.needs_clarification:
                agreement.status = self._solve_status(agreement)
            await repositories.record_audit(
                self._session,
                entity_type="agreement",
                entity_id=agreement.id,
                action="agreement.edited",
                actor_user_id=user.id,
                payload={"fields": sorted(changed)},
            )
        await self._session.flush()
        return agreement

    async def confirm(self, user: User, agreement: Agreement) -> Agreement:
        if agreement.status not in (
            AgreementStatus.detected,
            AgreementStatus.requires_review,
            AgreementStatus.needs_clarification,
        ):
            raise ValidationFailed(f"agreement is {agreement.status.value}, cannot confirm")
        agreement.status = AgreementStatus.confirmed
        agreement.version += 1
        task = await self._tasks.create_from_agreement(agreement, actor=user)
        await repositories.record_audit(
            self._session,
            entity_type="agreement",
            entity_id=agreement.id,
            action="agreement.confirmed",
            actor_user_id=user.id,
            payload={"task_id": str(task.id)},
        )
        await self._session.flush()
        return agreement

    async def reject(self, user: User, agreement: Agreement) -> Agreement:
        if agreement.status is AgreementStatus.confirmed:
            raise ValidationFailed("confirmed agreements cannot be rejected; cancel the task")
        if agreement.status is AgreementStatus.rejected:
            return agreement
        agreement.status = AgreementStatus.rejected
        agreement.version += 1
        await repositories.record_audit(
            self._session,
            entity_type="agreement",
            entity_id=agreement.id,
            action="agreement.rejected",
            actor_user_id=user.id,
        )
        await self._session.flush()
        return agreement

    def _solve_status(self, agreement: Agreement) -> AgreementStatus:
        """Re-derive the status after the user resolved an ambiguous agreement."""
        flags = AmbiguityFlags(
            missing_due_date=agreement.due_date is None,
            missing_amount=agreement.amount is None,
            unknown_owner=agreement.owner is Owner.unknown,
        )
        return resolve_agreement_status(
            float(agreement.confidence),
            threshold=self._settings.confidence_threshold,
            ambiguity=flags,
        )