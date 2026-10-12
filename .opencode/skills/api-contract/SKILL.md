---
name: api-contract
description: Design or change FastAPI endpoints and shared contracts for the agreement-capture backend.
---

# API contract workflow

Use this skill for new endpoints, request/response models, error handling,
OpenAPI changes, and mobile-backend synchronization.

## Required steps

1. Define the business outcome before adding a route.
2. Create Pydantic v2 request and response schemas.
3. Use explicit status codes:
   - 201 for created resources
   - 202 for accepted async processing
   - 409 for conflicts or duplicates
   - 422 for validation errors
   - 503 when an external integration is unavailable
4. Use idempotency keys for repeated submission of the same action.
5. Return conversation/job status for asynchronous processing.
6. Update OpenAPI schema and regenerate or update the Flutter API client.
7. Add API tests with `httpx.AsyncClient`.
8. Run:
   - `cd services/api && pytest`
   - `cd services/api && ruff check .`
   - `cd services/api && mypy .`

## Endpoint conventions

- `POST /conversations` — create conversation and start processing
- `GET /conversations/{id}` — status and metadata
- `GET /conversations/{id}/transcript` — transcript segments
- `GET /conversations/{id}/commitments` — extracted draft commitments
- `PATCH /commitments/{id}` — user edits or confirmation
- `POST /commitments/{id}/dispatch` — send to selected external apps
- `GET /integrations` — available user integrations
- `POST /integrations/{id}/test` — check access without writing data