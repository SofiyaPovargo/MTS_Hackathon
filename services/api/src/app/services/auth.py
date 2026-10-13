"""Authentication: OTP login, JWT access/refresh tokens, revocation."""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.domain.errors import NotFound, ValidationFailed
from app.infrastructure.cache import Cache
from app.infrastructure.db import repositories
from app.infrastructure.db.models import User
from app.infrastructure.security import (
    REFRESH,
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
)

OTP_KEY = "otp:{phone}"
REFRESH_KEY = "refresh:{jti}"


@dataclass(slots=True)
class AuthResult:
    access_token: str
    refresh_token: str
    expires_in: int
    user: User
    token_type: str = "bearer"


class AuthService:
    def __init__(self, session: AsyncSession, cache: Cache, settings: Settings) -> None:
        self._session = session
        self._cache = cache
        self._settings = settings

    async def request_otp(self, phone: str) -> None:
        code = self._settings.dev_otp or f"{secrets.randbelow(1_000_000):06d}"
        await self._cache.set(OTP_KEY.format(phone=phone), code, ttl_sec=self._settings.otp_ttl_sec)

    async def _verify_otp(self, phone: str, otp: str) -> None:
        stored = await self._cache.get(OTP_KEY.format(phone=phone))
        if stored is None:
            raise ValidationFailed("OTP expired; request a new code")
        if stored != otp:
            raise ValidationFailed("invalid OTP")
        await self._cache.delete(OTP_KEY.format(phone=phone))

    async def _user_by_phone(self, phone: str) -> User:
        user = await repositories.get_user_by_phone(self._session, phone)
        if user is None or not user.is_active:
            raise NotFound("user not found")
        return user

    async def _issue_pair(self, user: User) -> AuthResult:
        access_token = create_access_token(user, settings=self._settings)
        refresh_token, jti = create_refresh_token(user, settings=self._settings)
        await self._cache.set(
            REFRESH_KEY.format(jti=jti),
            str(user.id),
            ttl_sec=self._settings.refresh_token_ttl_sec,
        )
        return AuthResult(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=self._settings.access_token_ttl_sec,
            user=user,
        )

    async def login(self, phone: str, otp: str) -> AuthResult:
        user = await self._user_by_phone(phone)
        await self._verify_otp(phone, otp)
        result = await self._issue_pair(user)
        await self._session.commit()
        return result

    async def refresh(self, refresh_token: str) -> AuthResult:
        payload = decode_token(refresh_token, settings=self._settings, expected_type=REFRESH)
        jti = str(payload["jti"])
        subject = str(payload["sub"])
        tracked = await self._cache.get(REFRESH_KEY.format(jti=jti))
        if tracked != subject:
            raise TokenError("refresh token revoked")
        user = await repositories.get_user(self._session, uuid.UUID(subject))
        if user is None or not user.is_active:
            raise NotFound("user not found")
        # Rotation: the old token is used once.
        await self._cache.delete(REFRESH_KEY.format(jti=jti))
        result = await self._issue_pair(user)
        await self._session.commit()
        return result

    async def logout(self, refresh_token: str) -> None:
        payload = decode_token(refresh_token, settings=self._settings, expected_type=REFRESH)
        await self._cache.delete(REFRESH_KEY.format(jti=str(payload["jti"])))

    async def reset_otp_for_demo(self, phone: str) -> str:
        """Demo helper: return the generated code so tests can log in."""
        code = self._settings.dev_otp or f"{secrets.randbelow(1_000_000):06d}"
        await self._cache.set(OTP_KEY.format(phone=phone), code, ttl_sec=self._settings.otp_ttl_sec)
        return code