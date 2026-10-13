"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_exception_handlers
from app.api.routes import router as api_router
from app.api.ws import router as ws_router
from app.config import Settings, get_settings
from app.infrastructure.cache import Cache
from app.infrastructure.db.session import create_engine_and_factory
from app.integrations.outbound import (
    calendar_factory,
    messaging_factory,
    reminders_factory,
)
from app.integrations.voice import voice_provider_factory
from app.services.events import EventHub
from app.services.jobs import CeleryAnalysisQueue, NullAnalysisQueue

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    engine, factory = create_engine_and_factory(settings.database_url)
    cache = Cache.from_settings(settings)

    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = factory
    app.state.cache = cache
    app.state.voice_provider = voice_provider_factory(settings.voice_provider, settings)
    app.state.event_hub = EventHub(cache)
    app.state.calendar = calendar_factory(settings.calendar_provider)
    app.state.reminders = reminders_factory(settings.reminders_provider)
    app.state.messaging = messaging_factory(settings.messaging_provider)
    app.state.analysis_queue = (
        NullAnalysisQueue() if settings.env == "test" else CeleryAnalysisQueue(settings)
    )

    from app.infrastructure.storage import InMemoryStorage, MinioStorage

    if settings.env == "test":
        app.state.storage = InMemoryStorage()
    else:
        app.state.storage = MinioStorage(settings)
        try:
            await app.state.storage.create_bucket()
        except Exception as exc:  # pragma: no cover - infra can be down in dev
            logger.warning("object storage bucket unavailable: %s", exc)

    yield

    aclose = getattr(app.state.voice_provider, "aclose", None)
    if aclose is not None:
        await aclose()
    await cache.close()
    await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    app = FastAPI(
        title="Agreement Capture API",
        description="Server for the agreement-capture mobile app: calls, consent, "
        "agreements, tasks, sync and the manager board.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.cors_origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)
    app.include_router(api_router, prefix=resolved.api_base_path)
    app.include_router(ws_router, prefix=resolved.api_base_path)
    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, log_level="info")