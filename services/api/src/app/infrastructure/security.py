"""JWT access/refresh tokens. Short-lived access + refresh with Redis revocation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.config import Settings
from app.infrastructure.db.models import User

ACCESS = "access"
REFRESH = "refresh"


class TokenError(Exception):
    pass


def _issue(
    *,
    settings: Settings,
    token_type: str,
    subject: str,
    role: str,
    team_id: str | None,
    ttl_sec: int,
    jti: str | None = None,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "role": role,
        "team_id": team_id,
        "type": token_type,
        "jti": jti or str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(seconds=ttl_sec),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user: User, *, settings: Settings) -> str:
    return _issue(
        settings=settings,
        token_type=ACCESS,
        subject=str(user.id),
        role=user.role.value,
        team_id=str(user.team_id) if user.team_id else None,
        ttl_sec=settings.access_token_ttl_sec,
    )


def create_refresh_token(user: User, *, settings: Settings) -> tuple[str, str]:
    """Return (token, jti). The jti is embedded in the token and stored in Redis."""
    jti = str(uuid.uuid4())
    token = _issue(
        settings=settings,
        token_type=REFRESH,
        subject=str(user.id),
        role=user.role.value,
        team_id=str(user.team_id) if user.team_id else None,
        ttl_sec=settings.refresh_token_ttl_sec,
        jti=jti,
    )
    return token, jti


def decode_token(token: str, *, settings: Settings, expected_type: str) -> dict[str, object]:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise TokenError("invalid token") from exc
    if payload.get("type") != expected_type:
        raise TokenError("wrong token type")
    return payload