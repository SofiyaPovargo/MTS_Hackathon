"""ML-пайплайн: аудио -> сегментированный транскрипт -> договорённости -> события.

Шаги (AGENTS.md, порядок пайплайна):

1. **worker-asr** — загрузить запись из объектного хранилища, транскрибировать с
   ролями (каналы для VoIP, диаризация для mono/PSTN), сохранить транскрипт в
   таблицу ``transcripts`` (1:1 со звонком).
2. **worker-ai** — прогнать LLM + rule-based валидацию, создать предложенные
   ``agreements`` (raw/validated/правки хранятся раздельно) и опубликовать
   событие ``agreement_detected``.

Оба шага идемпотентны по ``call_id``: повторная обработка переиспользует уже
сохранённый транскрипт / уже извлечённые договорённости (no-op). Источник истины
— Postgres; функции принимают сессию и порты, поэтому запускаются и без Celery
(тесты/локальный batch).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.domain.errors import NotFound
from app.infrastructure.db import repositories
from app.infrastructure.db.models import (
    Agreement,
    Call,
    User,
)
from app.infrastructure.db.models import (
    CallAudio as CallAudioRow,
)
from app.infrastructure.db.models import (
    Transcript as TranscriptRow,
)
from app.infrastructure.storage import StorageError, StoragePort, key_from_url
from app.ml.asr.ports import ASRPort
from app.ml.diarization.ports import DiarizationPort
from app.ml.extraction.context import ConversationContext
from app.ml.extraction.llm import PROMPT_VERSION
from app.ml.extraction.ports import ExtractionPort
from app.ml.extraction.service import ExtractionService
from app.ml.stt.pipeline import (
    CallAudio,
    TranscribePipeline,
    decode_phone_audio,
    decode_phone_pcm,
)
from app.ml.stt.schemas import TranscriptSegment
from app.ml.vad.ports import VadPort
from app.services.agreement import AgreementService
from app.services.events import CallEventMessage
from app.services.summary import generate_call_summary
from app.services.task import TaskService

logger = logging.getLogger(__name__)


class EventsPort(Protocol):
    async def emit(self, message: CallEventMessage) -> None: ...


def conversation_date(call: Call, user: User) -> date:
    """Дата разговора в часовом поясе пользователя (для резолва относительных дат)."""
    timestamp = call.answered_at or call.started_at or call.created_at
    if timestamp is None:
        return datetime.now(UTC).date()
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    try:
        zone = ZoneInfo(user.timezone)
    except Exception:  # an invalid timezone must not break the pipeline
        zone = ZoneInfo("UTC")
    return timestamp.astimezone(zone).date()


def _participants(user: User, call: Call) -> dict[str, str]:
    """Оператор — пользователь приложения, клиент — собеседник."""
    return {"operator": user.full_name, "client": call.contact_name or call.contact_phone}


def agreement_payload(agreement: Agreement) -> dict[str, object]:
    """Payload события ``agreement_detected`` (карточка для live-доски)."""
    return {
        "id": str(agreement.id),
        "call_id": str(agreement.call_id),
        "type": agreement.type,
        "title": agreement.title,
        "object": agreement.object,
        "owner": agreement.owner.value,
        "due_date": agreement.due_date.isoformat() if agreement.due_date else None,
        "due_time": agreement.due_time.isoformat() if agreement.due_time else None,
        "source_quote": agreement.source_quote,
        "audio_start": float(agreement.audio_start),
        "audio_end": float(agreement.audio_end),
        "confidence": float(agreement.confidence),
        "status": agreement.status.value,
    }


async def load_call_audio(audio: CallAudioRow, storage: StoragePort) -> CallAudio:
    """Собрать ``CallAudio`` из хранилища: ноги (VoIP) или смесь (PSTN)."""
    channels = audio.channel_urls or {}
    operator_url = channels.get("operator")
    client_url = channels.get("client")
    if operator_url and client_url:
        operator = await storage.get_bytes(key_from_url(operator_url))
        client = await storage.get_bytes(key_from_url(client_url))
        return CallAudio(
            operator=decode_phone_pcm(operator),
            client=decode_phone_pcm(client),
        )
    mixed = await storage.get_bytes(key_from_url(audio.storage_url))
    return decode_phone_audio(mixed)


async def transcribe_and_store(
    session: AsyncSession,
    *,
    call_id: uuid.UUID,
    storage: StoragePort,
    asr: ASRPort,
    diarizer: DiarizationPort | None,
    events: EventsPort,
    settings: Settings,
    vad: VadPort | None = None,
) -> TranscriptRow | None:
    """worker-asr: запись -> транскрипт с ролями, сохранённый в Postgres.

    Идемпотентно: если готовый транскрипт уже есть, он переиспользуется.
    """
    call = await repositories.get_call(session, call_id)
    if call is None:
        raise NotFound("call not found")

    existing = await repositories.get_transcript(session, call_id)
    if existing is not None and existing.status == "done":
        logger.info("transcript already exists for call %s; reusing", call_id)
        return existing

    audio_row = await repositories.get_call_audio(session, call_id)
    if audio_row is None:
        logger.warning("no audio for call %s; nothing to transcribe", call_id)
        return None

    try:
        audio = await load_call_audio(audio_row, storage)
    except StorageError as exc:
        logger.warning("audio unavailable for call %s: %s", call_id, exc)
        return None

    pipeline = TranscribePipeline(
        asr, diarizer, vad, vad_pad_sec=settings.vad_pad_sec
    )
    transcript = await pipeline.transcribe_audio(str(call_id), audio)

    segments = [segment.model_dump(mode="json") for segment in transcript.segments]
    full_text = " ".join(segment.text for segment in transcript.segments)
    row = await _persist_transcript(
        session,
        existing=existing,
        call_id=call_id,
        full_text=full_text,
        segments=segments,
        role_source=transcript.role_source.value,
    )
    await session.flush()

    for segment in transcript.segments:
        await events.emit(
            CallEventMessage(
                event="partial_transcript",
                call_id=call_id,
                payload={
                    "speaker": segment.speaker,
                    "text": segment.text,
                    "start": segment.start,
                    "end": segment.end,
                },
            )
        )
    logger.info(
        "transcribed call %s: %d segments (role_source=%s)",
        call_id,
        len(transcript.segments),
        transcript.role_source.value,
    )
    return row


async def _persist_transcript(
    session: AsyncSession,
    *,
    existing: TranscriptRow | None,
    call_id: uuid.UUID,
    full_text: str,
    segments: list[dict[str, object]],
    role_source: str,
) -> TranscriptRow:
    if existing is not None:
        existing.full_text = full_text
        existing.segments = segments
        existing.role_source = role_source
        existing.status = "done"
        return existing
    row = repositories.build_transcript(
        call_id=call_id,
        language="ru",
        full_text=full_text,
        segments=segments,
        role_source=role_source,
    )
    session.add(row)
    return row


async def extract_and_store(
    session: AsyncSession,
    *,
    call_id: uuid.UUID,
    extractor: ExtractionPort | None,
    events: EventsPort,
    settings: Settings,
) -> list[Agreement]:
    """worker-ai: транскрипт -> провалидированные agreements + ``agreement_detected``.

    Идемпотентно: если по звонку уже извлекали, повторно LLM не вызывается.
    """
    if extractor is None:
        logger.info("LLM extractor is disabled; skipping extraction for call %s", call_id)
        # Итог звонка не зависит от LLM: собираем его из того, что уже есть.
        await generate_call_summary(session, call_id)
        return []

    call = await repositories.get_call(session, call_id)
    if call is None:
        raise NotFound("call not found")
    user = await repositories.get_user(session, call.user_id)
    if user is None:
        raise NotFound("call owner not found")

    if await repositories.has_agreement_extractions(session, call_id):
        logger.info("agreements already extracted for call %s; reusing", call_id)
        await generate_call_summary(session, call_id)
        return list(await repositories.list_agreements_for_call(session, call_id))

    row = await repositories.get_transcript(session, call_id)
    if row is None or not row.segments:
        logger.warning("no transcript for call %s; nothing to extract", call_id)
        return []

    segments = [TranscriptSegment.model_validate(segment) for segment in row.segments]
    context = ConversationContext(
        conversation_id=str(call_id),
        conversation_date=conversation_date(call, user),
        user_timezone=user.timezone,
        participants=_participants(user, call),
        transcript=segments,
    )

    service = ExtractionService(extractor, confidence_threshold=settings.confidence_threshold)
    raw, validated = await service.extract_pair(context)

    agreements = AgreementService(session, settings, TaskService(session))
    # Сырой вывод LLM храним как есть (одна запись на звонок), валидированный —
    # отдельной копией внутри create_from_commitment; пользовательские правки —
    # в agreement_edits (AGENTS: raw / validated / edits раздельно).
    raw_output = {"commitments": [commitment.model_dump(mode="json") for commitment in raw]}

    created: list[Agreement] = []
    for commitment in validated:
        agreement = await agreements.create_from_commitment(
            user,
            call,
            commitment,
            model=settings.llm_model or "unknown",
            prompt_version=PROMPT_VERSION,
            raw_output=raw_output,
        )
        created.append(agreement)
        await events.emit(
            CallEventMessage(
                event="agreement_detected",
                call_id=call_id,
                payload=agreement_payload(agreement),
            )
        )
    await session.flush()
    # Итог звонка (§9): детерминированное резюме из валидированных договорённостей.
    await generate_call_summary(session, call_id)
    logger.info("extracted %d agreement(s) for call %s", len(created), call_id)
    return created


async def extract_incremental(
    session: AsyncSession,
    *,
    call_id: uuid.UUID,
    extractor: ExtractionPort | None,
    events: EventsPort,
    settings: Settings,
) -> list[Agreement]:
    """Инкрементальное извлечение: upsert по fingerprint, события только на изменения.

    Live-воркер вызывает это по ходу разговора (debounce) и финально в конце;
    повторный прогон без изменений ничего не эмитит и не дублирует agreements.
    """
    if extractor is None:
        logger.info("LLM extractor is disabled; skipping live extraction for %s", call_id)
        return []

    call = await repositories.get_call(session, call_id)
    if call is None:
        raise NotFound("call not found")
    user = await repositories.get_user(session, call.user_id)
    if user is None:
        raise NotFound("call owner not found")

    row = await repositories.get_transcript(session, call_id)
    if row is None or not row.segments:
        logger.warning("no transcript for call %s; nothing to extract", call_id)
        return []

    segments = [TranscriptSegment.model_validate(segment) for segment in row.segments]
    context = ConversationContext(
        conversation_id=str(call_id),
        conversation_date=conversation_date(call, user),
        user_timezone=user.timezone,
        participants=_participants(user, call),
        transcript=segments,
    )

    service = ExtractionService(extractor, confidence_threshold=settings.confidence_threshold)
    raw, validated = await service.extract_pair(context)
    raw_output = {"commitments": [commitment.model_dump(mode="json") for commitment in raw]}

    agreements = AgreementService(session, settings, TaskService(session))
    changed_agreements: list[Agreement] = []
    for commitment in validated:
        agreement, changed = await agreements.upsert_from_commitment(
            user,
            call,
            commitment,
            model=settings.llm_model or "unknown",
            prompt_version=PROMPT_VERSION,
            raw_output=raw_output,
        )
        if changed:
            changed_agreements.append(agreement)
            await events.emit(
                CallEventMessage(
                    event="agreement_detected",
                    call_id=call_id,
                    payload=agreement_payload(agreement),
                )
            )
    await session.flush()
    logger.info(
        "live extraction for call %s: %d changed agreement(s)",
        call_id,
        len(changed_agreements),
    )
    return changed_agreements


__all__ = [
    "agreement_payload",
    "conversation_date",
    "extract_and_store",
    "extract_incremental",
    "load_call_audio",
    "transcribe_and_store",
]
