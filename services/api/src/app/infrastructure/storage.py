"""Object storage (MinIO / S3) for audio.

Audio carries personal data: objects are stored in a private bucket with a
retention expiry and short-lived pre-signed URLs. Nothing is written to the
container filesystem.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from app.config import Settings


class StorageError(RuntimeError):
    pass


class StoragePort(Protocol):
    async def put_bytes(self, key: str, data: bytes, content_type: str) -> str: ...
    async def delete(self, key: str) -> None: ...
    async def presigned_get(self, key: str, *, expires_sec: int = 3600) -> str: ...
    async def create_bucket(self) -> None: ...


class MinioStorage:
    """S3-compatible storage used in production and in the dev stack."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            config=BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        self._bucket = settings.s3_bucket

    async def _guarded(self, op: Callable[[], object]) -> object:
        try:
            return await asyncio.to_thread(op)
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(str(exc)) from exc

    async def create_bucket(self) -> None:
        def _do() -> None:
            try:
                self._client.head_bucket(Bucket=self._bucket)
            except ClientError:
                self._client.create_bucket(Bucket=self._bucket)

        await self._guarded(_do)

    async def put_bytes(self, key: str, data: bytes, content_type: str) -> str:
        await self._guarded(
            lambda: self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                ServerSideEncryption="AES256",
            )
        )
        return f"s3://{self._bucket}/{key}"

    async def delete(self, key: str) -> None:
        await self._guarded(lambda: self._client.delete_object(Bucket=self._bucket, Key=key))

    async def presigned_get(self, key: str, *, expires_sec: int = 3600) -> str:
        return str(
            await self._guarded(
                lambda: self._client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self._bucket, "Key": key},
                    ExpiresIn=expires_sec,
                )
            )
        )


class InMemoryStorage(StoragePort):
    """Test double: keeps data in memory, no network access."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    async def put_bytes(self, key: str, data: bytes, content_type: str) -> str:
        self._objects[key] = data
        return f"s3://memory/{key}"

    async def delete(self, key: str) -> None:
        self._objects.pop(key, None)

    async def presigned_get(self, key: str, *, expires_sec: int = 3600) -> str:
        if key not in self._objects:
            raise StorageError(f"object not found: {key}")
        return f"memory://{key}?expires={expires_sec}"

    async def create_bucket(self) -> None:
        return None


def new_audio_key(call_id: str) -> str:
    return f"calls/{call_id}/audio/{uuid.uuid4().hex}.ogg"


def retention_expiry(settings: Settings) -> datetime:
    return datetime.now(UTC) + timedelta(days=settings.audio_retention_days)