"""Environment for the whole test run.

Env vars must be set before ``app.config`` is imported (it caches settings).
Integration tests require PostgreSQL and Redis on localhost (docker compose).
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://app:app@localhost:5432/agreements_test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("DEV_OTP", "1234")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("VOICE_WEBHOOK_SECRET", "test-voice-secret")
os.environ.setdefault("CONSENT_MODE", "notice")
os.environ.setdefault("DATA_ENCRYPTION_KEY", "test-encryption-key")