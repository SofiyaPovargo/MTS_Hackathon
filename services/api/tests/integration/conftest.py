"""Integration fixtures: isolated database, seeded team/users, API client.

These tests run against containers (``docker compose up -d postgres redis``).
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any, cast
from urllib.parse import quote

import asyncpg
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.domain.enums import Role
from app.infrastructure.db.base import Base
from app.infrastructure.db.models import Team, User

TEST_DB = "agreements_test"

# Derive the admin connection from DATABASE_URL instead of hardcoding app/app,
# so the tests run against whatever local Postgres a developer uses. The host is
# overridable (CI uses a service name); locally it is the published port.
_RAW_URL = make_url(os.environ["DATABASE_URL"])
_DB_HOST = os.environ.get("TEST_DB_HOST", "localhost")
_DB_PORT = _RAW_URL.port or 5432
_DB_USER = _RAW_URL.username or "postgres"
_DB_PASSWORD = _RAW_URL.password or ""


def _async_url(database: str) -> str:
    auth = quote(_DB_USER, safe="")
    if _DB_PASSWORD:
        auth += ":" + quote(_DB_PASSWORD, safe="")
    return f"postgresql+asyncpg://{auth}@{_DB_HOST}:{_DB_PORT}/{database}"


TEST_DATABASE_URL = _async_url(TEST_DB)
TEST_REDIS_URL = os.environ["REDIS_URL"]

# The app under test (create_app) reads DATABASE_URL from the environment; point
# it at the isolated test database so app + seeded fixtures share one database.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

USER_PHONES = {
    "manager": "+79000000001",
    "anna": "+79000000002",
    "boris": "+79000000003",
}


def _create_test_database_if_missing() -> None:
    async def _ensure() -> None:
        connection = await asyncpg.connect(
            host=_DB_HOST,
            port=_DB_PORT,
            user=_DB_USER,
            password=_DB_PASSWORD,
            database="postgres",
        )
        exists = await connection.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB)
        if not exists:
            await connection.execute(f'CREATE DATABASE "{TEST_DB}"')
        await connection.close()

    asyncio.run(_ensure())


def _migrate() -> None:
    env = {**os.environ, "DATABASE_URL": TEST_DATABASE_URL}
    subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],  # noqa: S607 - uv is on PATH by design
        check=True,
        env=env,
        capture_output=True,
    )


@pytest.fixture(scope="session")
def database() -> Iterator[None]:
    _create_test_database_if_missing()
    _migrate()
    yield


@pytest.fixture(scope="session")
def engine(database: None) -> Iterator[AsyncEngine]:
    # NullPool: each connection is created and closed on the calling test loop,
    # so pooled connections never outlive the per-function event loop.
    async_engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True, poolclass=NullPool)
    yield async_engine
    asyncio.run(async_engine.dispose())


@pytest.fixture
async def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def clean_db(engine: AsyncEngine) -> AsyncIterator[None]:
    async with engine.begin() as conn:
        tables = [t.name for t in Base.metadata.sorted_tables if t.name != "alembic_version"]
        await conn.execute(text(f'TRUNCATE {", ".join(f'"{t}"' for t in tables)} CASCADE'))
    yield


@pytest.fixture
async def seeded_users(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, uuid.UUID]:
    """Team + manager + two users, matching USER_PHONES."""
    async with session_factory() as session:
        team = Team(name="Альфа")
        session.add(team)
        await session.flush()
        manager = User(
            team_id=team.id, phone=USER_PHONES["manager"], full_name="Ирина",
            role=Role.manager, timezone="Europe/Moscow",
        )
        anna = User(
            team_id=team.id, phone=USER_PHONES["anna"], full_name="Анна",
            role=Role.user, timezone="Europe/Moscow",
        )
        boris = User(
            team_id=team.id, phone=USER_PHONES["boris"], full_name="Борис",
            role=Role.user, timezone="Europe/Moscow",
        )
        session.add_all([manager, anna, boris])
        await session.flush()
        team.manager_id = manager.id
        await session.commit()
        return {
            "team_id": team.id,
            "manager_id": manager.id,
            "anna_id": anna.id,
            "boris_id": boris.id,
        }


@pytest.fixture
async def app_and_client(engine: AsyncEngine) -> AsyncIterator[tuple[FastAPI, httpx.AsyncClient]]:
    from app.main import create_app

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        yield app, client


async def login(client: httpx.AsyncClient, phone: str) -> dict[str, Any]:
    response = await client.post("/api/auth/otp/request", json={"phone": phone})
    assert response.status_code == 204, response.text
    response = await client.post("/api/auth/login", json={"phone": phone, "otp": "1234"})
    assert response.status_code == 200, response.text
    return cast("dict[str, Any]", response.json())


async def create_call(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    phone: str = "+79991230001",
    external_id: str | None = None,
) -> dict[str, Any]:
    """Create an outbound call as the given user (initial status ``ringing``)."""
    payload: dict[str, object] = {"direction": "outbound", "callee_phone": phone}
    if external_id is not None:
        payload["external_id"] = external_id
    response = await client.post("/api/calls", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return cast("dict[str, Any]", response.json())


async def create_manual_agreement(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    call_id: str,
    *,
    title: str = "Отправить отчёт",
    owner: str = "user",
    due_date: str = "2026-10-20",
) -> dict[str, Any]:
    """Create a manual agreement on the call (the no-consent / correction path)."""
    response = await client.post(
        f"/api/calls/{call_id}/agreements",
        json={"type": "obligation", "title": title, "owner": owner, "due_date": due_date},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return cast("dict[str, Any]", response.json())


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


VOICE_HEADERS = {"X-Voice-Webhook-Secret": os.environ["VOICE_WEBHOOK_SECRET"]}