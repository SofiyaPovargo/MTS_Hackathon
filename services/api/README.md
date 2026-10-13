# API — agreement-capture backend

FastAPI (async) + PostgreSQL + Redis + MinIO. This is Stage 2 of the plan:
the server foundation — models, auth and roles, CRUD, consent-gated call
lifecycle, sync, and Docker Compose. The mobile client (`apps/mobile`, Stage 3)
is not implemented yet. The ML pipeline (ASR / diarization / transcript, Stage 6)
already has a working research layer under `src/app/ml/`.

## Layout

Layered per `AGENTS.md`:

```
src/app/
  api/            HTTP routes, request/response schemas (Pydantic v2), dependencies
  domain/         entities, enums, state machine, date/commitment rules (no IO)
  services/       auth, call session, consent, agreement, task, sync, manager, events
  infrastructure/ SQLAlchemy models/repositories, Redis cache, JWT, S3 storage
  integrations/   external ports: VoiceProviderPort (mock), outbound drafts
  ml/             research layer: ASR (T-one client), diarization (pyannote), STT pipeline
  migrations/     Alembic migrations
  worker.py       Celery entrypoint (queues: asr, ai, notifications)
  cli.py          `python -m app.cli seed` — demo team + users
tests/
  unit/           date resolution, commitment rules, call state machine
  integration/    auth, access, consent flow, agreements/tasks, sync, manager
  ml/             T-one ASR client protocol, STT pipeline (roles, resample)
```

## Quick start (host, for development)

```bash
cd services/api
uv sync                       # install deps from uv.lock
docker compose up -d postgres redis   # infra only (from repo root)
uv run alembic upgrade head   # create schema (also done by the migrate service)
uv run python -m app.cli seed # demo team: manager + 2 users
uv run uvicorn app.main:app --reload
```

Demo users (OTP is any; the dev OTP `1234` is accepted in `.env`):

| phone          | name            | role    |
| -------------- | --------------- | ------- |
| +79000000001   | Ирина Менеджер  | manager |
| +79000000002   | Анна Пользователь | user  |
| +79000000003   | Борис Пользователь | user  |

## Docker Compose

`docker compose up -d` starts the full stack: `postgres`, `redis`, `minio`,
one-off `migrate` (runs Alembic after Postgres is healthy), `api`, three
workers (`worker-asr`, `worker-ai`, `worker-notifications`), and `nginx`
(the only service published to the outside; TLS + WebSocket proxying).

Rules enforced by the compose file (see `AGENTS.md`):

- Containers reach each other by service name, never `localhost`.
- Hosts/credentials come only from environment variables.
- `postgres`, `redis`, `minio` have healthchecks; dependents use
  `condition: service_healthy`.
- `migrate` runs once, before `api`/workers; migrations never run on API startup.
- Data lives only in named volumes (`postgres_data`, `redis_data`, `minio_data`).
- Dev-only published ports (`8000`, `5432`, `6379`, `9000`, `9001`) live in
  `docker-compose.override.yml`, not in the production compose file.
- `api` and workers share one image with different start commands; the ML-heavy
  extras go in the optional `ml` dependency group so the API image stays light.
- The research `asr` service (T-one streaming ASR) is optional and starts only
  with `docker compose --profile ml up -d asr`.

## Configuration

All settings come from the environment (`.env`, see `.env.example`). Key ones:

| variable              | default              | meaning                                   |
| --------------------- | -------------------- | ----------------------------------------- |
| `DATABASE_URL`        | `postgresql+asyncpg://…` | PostgreSQL (service name inside compose) |
| `REDIS_URL`           | `redis://localhost:6379/0` | Redis (queues, cache, event hub)    |
| `S3_ENDPOINT` etc.    | MinIO dev defaults   | audio storage (used from Stage 6)         |
| `JWT_SECRET`          | dev-only             | HS256 signing key                         |
| `ACCESS_TOKEN_TTL_SEC`/`REFRESH_TOKEN_TTL_SEC` | 900 / 2592000 | short access + refresh   |
| `DEV_OTP`             | —                    | fixed OTP accepted only in local/dev      |
| `CONFIDENCE_THRESHOLD`| 0.8                  | below it an agreement is `requires_review`|
| `CONSENT_MODE`        | notice               | `notice` \| `dtmf` \| `sms_link`          |
| `VOICE_WEBHOOK_SECRET`| dev-voice-secret     | header checked on call webhooks           |
| `ASR_WS_URL`          | `ws://localhost:8080/api/ws` | T-one streaming ASR WebSocket  |
| `HF_TOKEN`            | —                    | read-only Hugging Face token (pyannote)   |
| `DATA_DIR`            | `data`               | `data/audio`, `data/transcripts` for STT CLI |

## Endpoints

`/auth`

| method | path                  | notes                              |
| ------ | --------------------- | ---------------------------------- |
| POST   | `/auth/otp/request`   | asks for an OTP (204; dev OTP `1234`) |
| POST   | `/auth/login`         | phone+OTP → access + refresh tokens |
| POST   | `/auth/refresh`       | rotates refresh token (jti in Redis) |
| POST   | `/auth/logout`        | revokes the refresh token (204)    |

`/me` and consent

| method | path                  | notes                              |
| ------ | --------------------- | ---------------------------------- |
| GET    | `/me`                 | current user profile               |
| PUT    | `/me/consent`         | app-user consent setting           |
| POST   | `/me/consent/withdraw`| withdraw consent (real flow)       |
| POST   | `/me/data/delete`     | 202: withdraw + audit + enqueue deletion job |

Calls (voice provider integration lives behind `VoiceProviderPort`)

| method | path                  | notes                              |
| ------ | --------------------- | ---------------------------------- |
| POST   | `/calls`              | create a call (outbound demo)      |
| GET    | `/calls`              | my calls                           |
| GET    | `/calls/{id}`         | call detail (owner-only)           |
| POST   | `/calls/{id}/events`  | provider webhook, signed by `VOICE_WEBHOOK_SECRET` |

Agreements

| method | path                    | notes                               |
| ------ | ----------------------- | ----------------------------------- |
| GET    | `/calls/{id}/agreements`| agreements of my call               |
| POST   | `/calls/{id}/agreements`| manual entry (no-consent path)      |
| GET    | `/me/agreements`        | all my agreements                   |
| PATCH  | `/agreements/{id}`      | edit (guards: confirmed/rejected are final) |
| POST   | `/agreements/{id}/confirm` | confirmed → creates a task        |
| POST   | `/agreements/{id}/reject`  | rejected, no task                 |

Tasks

| method | path                    | notes                               |
| ------ | ----------------------- | ----------------------------------- |
| GET    | `/me/tasks`             | tasks created from confirmed agreements |
| PATCH  | `/tasks/{id}`           | edit (status transitions validated) |
| POST   | `/tasks/{id}/complete`  | mark done                           |

Manager board (role + team membership enforced server-side)

| method | path                    | notes                               |
| ------ | ----------------------- | ----------------------------------- |
| GET    | `/manager/team/tasks`   | filters: `user_id`, `status`, `due_before` |
| GET    | `/manager/team/stats`   | team metrics                        |
| GET    | `/manager/team/members` | team roster                         |

Sync (deltas, idempotent push)

| method | path        | notes                                             |
| ------ | ----------- | ------------------------------------------------- |
| GET    | `/sync`     | pull since `since` token → changed rows + new token |
| POST   | `/sync`     | push operations with `idempotency_key`; conflicts return server version |

Misc

| method | path           | notes                  |
| ------ | -------------- | ---------------------- |
| GET    | `/healthz`     | DB-backed liveness     |
| GET    | `/docs`        | OpenAPI (FastAPI)      |

## Data model

`teams`, `users` (role `user|manager`, `timezone`), `calls`, `call_audio`
(retention-bounded), `transcripts` (transcript lives here, never duplicated in
`calls`), `agreements` (owner, quote, audio timestamps, confidence, status),
`agreement_extractions` (raw + validated LLM output), `agreement_edits`,
`tasks`, `reminders`, `consents`, `audit_log`, `idempotency_keys`.

Agreement statuses: `detected`, `requires_review`, `needs_clarification`,
`confirmed`, `rejected`. Task statuses: `new`, `in_progress`, `done`,
`overdue`, `canceled`. Enums are stored as checked VARCHAR.

## Product rules implemented here

- **Recording requires `answered` + consent.** The call lifecycle is a state
  machine in `domain/state_machine.py`; invalid transitions raise an error.
  `services/call_session.py` checks app-user consent and the counterparty
  consent result before recording ever starts (`recording_started_at` is only
  set on the granted path).
- **Tasks only from confirmed agreements.** `agreements/{id}/confirm` is the
  single point that creates a task; `reject` and status guards are enforced in
  `services/agreement.py`.
- **Confidence threshold (0.8, configurable).** Below it an agreement is
  `requires_review` and no task is created.
- **Ambiguity → `needs_clarification`.** Relative dates are resolved
  deterministically in `domain/dates.py` against the conversation date in the
  user's timezone (`next week`, `month end` are resolved but flagged
  `ambiguous=True`). Never invented dates.
- **Auditability.** Original quote and audio timestamps are preserved; raw LLM
  output, validated output and user edits are stored separately; `audit_log`
  records consent, recording start, and agreement/task changes.
- **Manager access.** Manager endpoints verify both role and team membership;
  cross-team and cross-user data return 403/404. Users see only their own data.
- **No external writes without confirmation.** Calendar/reminder/messaging
  ports exist behind confirmation; nothing is sent automatically.

## Consent flow on `call.answered`

1. app-user consent checked; none → ordinary call, recording disabled;
2. audio notice played to the other party;
3. consent event recorded;
4. refusal (DTMF 2) → recording disabled;
5. grant (notice-continue / DTMF 1 / prior consent) → recording + media stream
   start (`recording_started_at`), `analysis_started` event emitted;
6. `consents` row carries text version, method, call id and status.

Modes are switched via `CONSENT_MODE`; the integration tests exercise
notice, DTMF refusal and withdrawal.

## ML pipeline (research, Stage 6 groundwork)

Streaming ASR (T-one, Russian telephony 8 kHz) + speaker diarization
(pyannote) + transcript with `operator`/`client` roles.

```
src/app/ml/
  asr/
    ports.py     # ASRPort, TextPhrase
    tone.py      # ToneASRClient (WebSocket /api/ws, 8 kHz int16 PCM)
  diarization/
    ports.py     # DiarizationPort, SpeakerSegment
    pyannote.py  # PyannoteDiarizer (gated speaker-diarization-3.1)
  stt/
    schemas.py   # TranscriptSegment, Transcript
    pipeline.py  # audio loading, speaker merge, operator/client roles
    __main__.py  # CLI: python -m app.ml.stt <conversation_id>
```

Run the T-one ASR server locally (optional; also reachable on the research
Mac via Tailscale):

```bash
docker compose --profile ml up -d asr
```

Install the ML extras for the pipeline and its tests:

```bash
uv sync --extra ml        # adds numpy, soundfile, soxr, pyannote-audio, torch
```

Transcribe a call and save `data/transcripts/<id>.json`:

```bash
uv run python -m app.ml.stt <id> --audio-dir data/audio --out-dir data/transcripts
```

Flags:
- `--ws-url` — T-one address (default `ws://localhost:8080/api/ws`, from `ASR_WS_URL`).
- `--no-diarization` — skip pyannote, all speakers become `unknown`.
- Without `--no-diarization` you need `HF_TOKEN` in `.env` (read-only).

T-one note: the model ships inside `tinkoffcreditsystems/t-one:0.1.0` (no extra
download) and runs on CPU. The server keeps the connection open after
finalization, so `ToneASRClient` finishes on a silence timeout
(`FINALIZE_TIMEOUT`) instead of waiting for the socket to close. `tone.py`,
`pipeline.py` and the tests are protocol-level: no audio is stored, nothing is
sent to the model unless the CLI is run explicitly.

## WebSocket events

`services/events.py` provides the event hub (`CallEventMessage` persisted to
Redis under `events:call:{id}` for late replay). Stage 6 wires it to the
WebSocket endpoint. Known event types: `partial_transcript`,
`agreement_detected`, `analysis_started`, `call_ended`.

## Workers

Celery, one image, separate queues (`worker-asr`, `worker-ai`,
`worker-notifications`). The tasks are explicit placeholders that keep the
queues healthy; the ML pipeline wiring is Stage 6. `data-deletion` jobs are
enqueued from `POST /me/data/delete`.

## Tests

```bash
uv run ruff check .        # lint
uv run mypy .              # strict types
uv run pytest              # unit + integration + ML (asr/stt) tests
```

Integration tests need `docker compose up -d postgres redis`; they use a
separate `agreements_test` database (created and migrated automatically) and
Redis DB 1. They do not share data with development. Test OTP is `1234`, the
voice webhook header is `X-Voice-Webhook-Secret: test-voice-secret`.

Covered rules: call state transitions, recording blocked without consent,
relative date resolution, confidence threshold, manager/user access rights,
sync idempotency, OTP login + refresh rotation + logout, consent notice/DTMF
/withdrawal, agreement confirm→task, PATCH guards, cross-team 403s, the
T-one ASR client protocol and the STT speaker/role merge.

## Roadmap

Stage order follows `plan.md`: this is Stage 2 (plus research ML groundwork).
Staged placeholders: wiring the ML pipeline into the workers and the WebSocket
endpoint (Stage 6), tasks/reminders creation beyond the confirm flow,
calendar/`.ics` (Stage 9), and the mobile app (Stage 3+).