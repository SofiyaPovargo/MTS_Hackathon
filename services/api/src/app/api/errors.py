"""Exception-to-HTTP mapping. Business rules never leak as 500s.

Handlers are registered per exception class but typed broadly (``Exception``)
so strict mypy stays happy; the cast is only to read exception attributes.
"""

from __future__ import annotations

import logging
from typing import cast

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.domain.errors import (
    Conflict,
    ConsentRequired,
    DomainError,
    InvalidStateTransition,
    NotFound,
    PayloadTooLarge,
    PermissionDenied,
    UploadOffsetMismatch,
    ValidationFailed,
)
from app.infrastructure.security import TokenError
from app.infrastructure.storage import StorageError

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(TokenError, _handle_token)
    app.add_exception_handler(PermissionDenied, _handle_permission)
    app.add_exception_handler(ConsentRequired, _handle_consent)
    app.add_exception_handler(InvalidStateTransition, _handle_conflict)
    app.add_exception_handler(Conflict, _handle_conflict)
    app.add_exception_handler(UploadOffsetMismatch, _handle_offset_mismatch)
    app.add_exception_handler(NotFound, _handle_not_found)
    app.add_exception_handler(ValidationFailed, _handle_unprocessable)
    app.add_exception_handler(PayloadTooLarge, _handle_payload_too_large)
    app.add_exception_handler(StorageError, _handle_service_unavailable)


async def _handle_token(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=401, content={"detail": str(exc)})


async def _handle_permission(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=403, content={"detail": str(exc)})


async def _handle_consent(request: Request, exc: Exception) -> JSONResponse:
    # Recording without consent is a hard business error, not a client mistake.
    reason = getattr(cast(ConsentRequired, exc), "reason", str(exc))
    return JSONResponse(status_code=403, content={"detail": f"consent required: {reason}"})


async def _handle_conflict(request: Request, exc: Exception) -> JSONResponse:
    domain = cast(DomainError, exc)
    return JSONResponse(
        status_code=409,
        content={
            "detail": str(domain),
            "current": getattr(domain, "current", None),
            "target": getattr(domain, "target", None),
        },
    )


async def _handle_offset_mismatch(request: Request, exc: Exception) -> JSONResponse:
    # Resumable upload: tell the client exactly where to continue from.
    mismatch = cast(UploadOffsetMismatch, exc)
    return JSONResponse(
        status_code=409,
        content={
            "detail": str(mismatch),
            "expected_offset": mismatch.expected_offset,
            "total": mismatch.total,
        },
    )


async def _handle_not_found(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


async def _handle_unprocessable(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


async def _handle_payload_too_large(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=413, content={"detail": str(exc)})


async def _handle_service_unavailable(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "external storage is unavailable"})