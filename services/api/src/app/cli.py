"""CLI helpers: ``python -m app.cli seed`` creates the demo team and users.

Demo credentials:
- manager: +79000000001
- user Anna: +79000000002
- user Boris: +79000000003
OTP: any value configured in DEV_OTP (default in dev: 1234 via .env).

Only local/demo data is created here; nothing is ever sent outside.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import select

from app.config import get_settings
from app.domain.enums import (
    CallDirection,
    CallStatus,
    ConsentMethod,
    ConsentStatus,
    ConsentSubjectType,
    ConsentType,
    Role,
)
from app.infrastructure.db.models import Call, Consent, Team, User
from app.infrastructure.db.session import create_engine_and_factory


async def seed() -> None:
    settings = get_settings()
    engine, factory = create_engine_and_factory(settings.database_url)
    async with factory() as session:
        existing = (await session.execute(select(User.phone))).scalars().all()
        if existing:
            print(f"users already present ({len(existing)}); seed skipped")
            return

        team = Team(name="Альфа")
        session.add(team)
        await session.flush()

        manager = User(
            team_id=team.id,
            phone="+79000000001",
            full_name="Ирина Менеджер",
            role=Role.manager,
            timezone="Europe/Moscow",
        )
        anna = User(
            team_id=team.id,
            phone="+79000000002",
            full_name="Анна Пользователь",
            role=Role.user,
            timezone="Europe/Moscow",
        )
        boris = User(
            team_id=team.id,
            phone="+79000000003",
            full_name="Борис Пользователь",
            role=Role.user,
            timezone="Europe/Moscow",
        )
        session.add_all([manager, anna, boris])
        await session.flush()
        team.manager_id = manager.id

        session.add(
            Consent(
                user_id=anna.id,
                subject_type=ConsentSubjectType.app_user,
                consent_type=ConsentType.recording,
                status=ConsentStatus.granted,
                method=ConsentMethod.app_settings,
                text_version="v1",
                granted_at=datetime.now(UTC),
            )
        )

        session.add(
            Call(
                user_id=anna.id,
                direction=CallDirection.outbound,
                contact_phone="+79000000010",
                contact_name="Клиент «Стройка»",
                status=CallStatus.in_progress,
                started_at=datetime.now(UTC),
            )
        )
        await session.commit()
        print(f"seeded: team={team.id} manager={manager.id} anna={anna.id} boris={boris.id}")
    await engine.dispose()


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()