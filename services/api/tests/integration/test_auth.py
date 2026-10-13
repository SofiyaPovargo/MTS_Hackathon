"""End-to-end auth: OTP login, token refresh rotation, logout revocation."""

from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI

from tests.integration.conftest import USER_PHONES, auth_headers, login

pytestmark = pytest.mark.integration


async def test_otp_login_and_me(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    auth = await login(client, USER_PHONES["anna"])
    assert set(auth) >= {"access_token", "refresh_token"}
    assert auth["user"]["role"] == "user"

    response = await client.get("/api/me", headers=auth_headers(str(auth["access_token"])))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["phone"] == USER_PHONES["anna"]
    assert body["full_name"] == "Анна"


async def test_login_wrong_otp_rejected(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    response = await client.post("/api/auth/otp/request", json={"phone": USER_PHONES["anna"]})
    assert response.status_code == 204
    response = await client.post(
        "/api/auth/login", json={"phone": USER_PHONES["anna"], "otp": "9999"}
    )
    assert response.status_code == 422


async def test_login_unknown_phone_is_404(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    await client.post("/api/auth/otp/request", json={"phone": "+79990000000"})
    response = await client.post(
        "/api/auth/login", json={"phone": "+79990000000", "otp": "1234"}
    )
    assert response.status_code == 404


async def test_refresh_rotates_token(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    auth = await login(client, USER_PHONES["anna"])
    old_refresh = str(auth["refresh_token"])

    response = await client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
    assert response.status_code == 200, response.text
    rotated = response.json()
    assert rotated["refresh_token"] != old_refresh

    # The old token is one-time: reusing it after rotation must fail.
    response = await client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
    assert response.status_code == 401


async def test_logout_revokes_refresh_token(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    auth = await login(client, USER_PHONES["anna"])

    response = await client.post(
        "/api/auth/logout", json={"refresh_token": auth["refresh_token"]}
    )
    assert response.status_code == 204

    response = await client.post(
        "/api/auth/refresh", json={"refresh_token": auth["refresh_token"]}
    )
    assert response.status_code == 401


async def test_me_requires_bearer_token(
    app_and_client: tuple[FastAPI, httpx.AsyncClient],
    seeded_users: dict[str, uuid.UUID],
) -> None:
    _, client = app_and_client
    response = await client.get("/api/me")
    assert response.status_code == 401