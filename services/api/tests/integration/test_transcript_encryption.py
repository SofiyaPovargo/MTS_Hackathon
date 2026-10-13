"""Transcripts and LLM output are encrypted at rest (plan §16).

The transcript is the most sensitive row in the database: it is the full
conversation. This test reads the raw column, bypassing the ORM, to prove the
stored value is ciphertext, then reads it back through the ORM to prove readers
still see the plaintext.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.enums import CallDirection, CallStatus
from app.infrastructure.crypto import PREFIX
from app.infrastructure.db.models import AgreementExtraction, Call, Transcript

pytestmark = pytest.mark.integration


async def _make_call(session: AsyncSession, *, user_id: uuid.UUID) -> Call:
    call = Call(
        user_id=user_id,
        external_id=f"enc-{uuid.uuid4().hex[:8]}",
        contact_phone="+79995550000",
        direction=CallDirection.inbound,
        status=CallStatus.completed,
    )
    session.add(call)
    await session.flush()
    return call


async def test_full_text_and_segments_are_ciphertext_in_the_database(
    session_factory: async_sessionmaker[AsyncSession],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    secret = "Клиент: подтверждаю оплату 250000 рублей до пятницы"
    segments = [{"speaker": "client", "text": secret, "start": 1.0, "end": 3.0}]

    async with session_factory() as session:
        call = await _make_call(session, user_id=seeded_users["anna_id"])
        session.add(Transcript(call_id=call.id, full_text=secret, segments=segments, status="done"))
        await session.commit()
        call_id = call.id

    async with session_factory() as session:
        raw = (
            await session.execute(
                text("SELECT full_text, segments FROM transcripts WHERE call_id = :cid"),
                {"cid": call_id},
            )
        ).one()
        assert raw.full_text.startswith(PREFIX)
        assert secret not in raw.full_text
        assert raw.segments.startswith(PREFIX)
        assert secret not in raw.segments

        row = (await session.execute(select(Transcript).where(Transcript.call_id == call_id))).scalar_one()
        assert row.full_text == secret
        assert row.segments == segments


async def test_llm_output_is_ciphertext_in_the_database(
    session_factory: async_sessionmaker[AsyncSession],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    raw_output = {"commitments": [{"source_quote": "оплачу завтра", "confidence": 0.9}]}

    async with session_factory() as session:
        call = await _make_call(session, user_id=seeded_users["anna_id"])
        session.add(
            AgreementExtraction(
                call_id=call.id,
                model="qwen2.5:7b",
                prompt_version="v1",
                raw_output=raw_output,
                validated_output=raw_output,
            )
        )
        await session.commit()
        call_id = call.id

    async with session_factory() as session:
        stored = (
            await session.execute(
                text(
                    "SELECT raw_output, validated_output FROM agreement_extractions "
                    "WHERE call_id = :cid"
                ),
                {"cid": call_id},
            )
        ).one()
        assert stored.raw_output.startswith(PREFIX)
        assert "оплачу" not in stored.raw_output

        row = (
            await session.execute(
                select(AgreementExtraction).where(AgreementExtraction.call_id == call_id)
            )
        ).scalar_one()
        assert row.raw_output == raw_output
        assert row.validated_output == raw_output
