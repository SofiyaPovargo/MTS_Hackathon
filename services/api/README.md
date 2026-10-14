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
  api/            HTTP routes, WebSocket endpoint, schemas (Pydantic v2), dependencies
  domain/         entities, enums, state machine, date/commitment rules (no IO)
  services/       auth, call session, consent, agreement, task, schedule, sync, manager, data deletion, events
  infrastructure/ SQLAlchemy models/repositories, Redis cache, JWT, S3 storage
  integrations/   external ports: VoiceProviderPort (mock + Exolve adapter), calendar/reminders/messaging
  ml/             research layer: ASR (T-one client), diarization (pyannote), STT pipeline
  migrations/     Alembic migrations
  worker.py       Celery entrypoint (queues: asr, ai, asr-live, ai-live, notifications)
  cli.py          `python -m app.cli seed` — demo team + users
tests/
  unit/           date resolution, commitment rules, call state machine
  integration/    auth, access, consent flow, agreements/tasks (incl. edits), audio ingest/resume, schedule, sync, manager, WebSocket events, Exolve webhooks, provider recording, encryption, privacy
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

Production runs the base file plus `docker-compose.prod.yml` (real Let's
Encrypt certificates, restart policies, dev ports closed); see `docs/deploy.md`.
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
| `DATA_ENCRYPTION_KEY` | dev-only             | Fernet key for transcripts/LLM output at rest |
| `ACCESS_TOKEN_TTL_SEC`/`REFRESH_TOKEN_TTL_SEC` | 900 / 2592000 | short access + refresh   |
| `DEV_OTP`             | —                    | fixed OTP accepted only in local/dev      |
| `CONFIDENCE_THRESHOLD`| 0.8                  | below it an agreement is `requires_review`|
| `CONSENT_MODE`        | notice               | `notice` \| `dtmf` \| `sms_link`          |
| `VOICE_PROVIDER`      | mock                 | `mock` \| `exolve` (МТС Exolve adapter)   |
| `VOICE_WEBHOOK_SECRET`| dev-voice-secret     | header or `?secret=` checked on call webhooks |
| `EXOLVE_API_BASE_URL` | `https://api.exolve.ru` | Exolve API base                        |
| `EXOLVE_API_KEY`      | —                    | Exolve application API key (Bearer)       |
| `EXOLVE_SIP_RESOURCE_ID` | 0                 | SIP resource id used by `SetCallRecordState` |
| `EXOLVE_CONSENT_NOTICE_FILE_ID` | —          | audio notice played to the caller (`file_to_A`) |
| `EXOLVE_SIP_ROUTES`   | —                    | inbound routing `sip_id=phone:sip_uri`, comma-separated |
| `PUBLIC_BASE_URL`     | `http://localhost:8000` | base URL for provider callbacks (`event_URL`) |
| `MEDIA_INGEST_URL`    | `http://localhost:8000/api` | base for the client audio upload (`POST …/calls/{id}/audio`) |
| `MAX_AUDIO_UPLOAD_MB` | 64                   | cap for a single client audio upload      |
| `AUDIO_RETENTION_DAYS`| 30                   | object expiry for stored audio            |
| `CALENDAR_PROVIDER`   | ics                  | `ics` (in-app artifact)                   |
| `REMINDERS_PROVIDER`  | local                | `local`                                   |
| `MESSAGING_PROVIDER`  | draft                | `draft` (never sends)                     |
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
| POST   | `/calls/{id}/audio`   | client uploads the recorded audio (`audio/*` body; optional `?leg=operator|client`, `?duration_sec`, `?restart`). **Resumable**: with `Content-Range: bytes <start>-<end>/<total>` the body is one chunk, stored immediately, and the response `offset` says where to resume after a network drop (a retried chunk is idempotent; a gap → 409 with `expected_offset`). 202; queues ASR once complete. 409 if the call was not recorded, 413 oversized, 422 bad type/bad range, 403 foreign call |
| POST   | `/calls/{id}/analyze` | queue ASR + extraction for a recorded call (202, returns `{call_id,status}`) |
| GET    | `/calls/{id}/summary` | итог звонка (§9): deterministic summary of the call + agreement counts (owner-only) |

Voice provider webhooks (МТС Exolve, signed by `VOICE_WEBHOOK_SECRET` as an
`X-Voice-Webhook-Secret` header or a `?secret=` query param — Exolve cannot set
headers)

| method | path                    | notes                                |
| ------ | ----------------------- | ------------------------------------ |
| POST   | `/voice/exolve/control` | inbound call control: route the call to the app user (`EXOLVE_SIP_ROUTES`), play the consent notice (`file_to_A`), point events at our `event_URL`. JSON-RPC body; unknown `sip_id` → `error`; idempotent per `call_sid` |
| POST   | `/voice/exolve/events`  | progress notification `b/o/s/e/h/crr`: `b/o/s/e` drive the call lifecycle, `crr` remembers the record id and queues the download, the rest are acknowledged. Call resolved by `client_id` or `call_sid` |

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
| GET    | `/me/tasks`             | personal board (§14): `view=today\|overdue\|upcoming\|done\|all`, plus `status`/`priority`/`due_before`/`due_after` |
| PATCH  | `/tasks/{id}`           | edit (status transitions validated) |
| POST   | `/tasks/{id}/complete`  | mark done                           |
| POST   | `/tasks/{id}/calendar`  | write the task into the calendar (explicit action) |
| GET    | `/tasks/{id}/calendar.ics` | portable `.ics` download         |
| POST   | `/tasks/{id}/reminders` | schedule a reminder (`remind_at` in the future) |
| GET    | `/tasks/{id}/reminders` | list reminders for the task         |
| POST   | `/reminders/{id}/cancel` | cancel a reminder                  |
| POST   | `/tasks/{id}/message-draft` | draft a client message — never sent |

Manager board (role + team membership enforced server-side)

| method | path                    | notes                               |
| ------ | ----------------------- | ----------------------------------- |
| GET    | `/manager/team/tasks`   | filters: `user_id`, `status`, `priority`, `task_type`, `due_before`, `due_after`; `sort=overdue\|due_date\|priority\|created` (default overdue-first) |
| GET    | `/manager/team/stats`   | team metrics + per-member breakdown (incl. `agreements_total`) |
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
| GET    | `/ws/events/schema` | WebSocket envelope schema + event list |
| GET    | `/docs`        | OpenAPI (FastAPI)      |
| WS     | `/ws/calls/{id}` | live call events (JWT, owner-only; see below) |

## Data model

`teams`, `users` (role `user|manager`, `timezone`), `calls`, `call_audio`
(retention-bounded), `transcripts` (encrypted; the transcript lives here, never
duplicated in `calls`), `agreements` (owner, quote, audio timestamps,
confidence, status), `agreement_extractions` (raw + validated LLM output,
encrypted), `agreement_edits`, `tasks`, `reminders`, `consents`, `audit_log`,
`idempotency_keys`.

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
  ports exist behind confirmation; nothing is sent automatically. Each is a
  user-triggered action on a task whose agreement is `confirmed`
  (`services/schedule.py`); the message endpoint only produces a draft
  (`sent: false`), and the `.ics` download touches no external system.
- **Personal data at rest.** Audio objects use SSE-AES256 and a retention
  expiry (`AUDIO_RETENTION_DAYS`); transcript text/segments and raw LLM output
  are encrypted column-by-column with Fernet under `DATA_ENCRYPTION_KEY`
  (`infrastructure/crypto.py`, transparent ORM types). Logs never carry raw
  transcripts or prompts — the one LLM preview is passed through
  `infrastructure/redaction.py` (masks phones, e-mails, long numbers). A daily
  `beat` job (`purge_expired_audio`) and the on-request `delete_user_data`
  (`services/data_deletion.py`) remove audio objects — including the legs of a
  split call and the chunks of an unfinished resumable upload.

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

**МТС Exolve adapter** (`integrations/exolve.py`, `VOICE_PROVIDER=exolve`). The
inbound API has no DTMF collection and exposes no server-side media stream, so
for Exolve consent is `notice` (played to the caller via `file_to_A` in the
call-control response) and the ML audio comes from the mobile client, which
uploads the SDK audio to `POST {MEDIA_INGEST_URL}/calls/{call_id}/audio`
(`open_media_stream()` returns the `MEDIA_INGEST_URL` base). The adapter maps
Exolve progress notifications (`b/o/s/e`) to `CallEvent` and wraps the Call
Record API (`SetCallRecordState`, `GetInfo`, `Download`). Decisions recorded in
`plan.md` §11.1.

**Exolve webhooks** (`services/voice_webhooks.py`). `POST /voice/exolve/control`
answers the inbound routing request: the `sip_id` is resolved to the app user and
their SIP URI through `EXOLVE_SIP_ROUTES` (`sip_id=phone:sip_uri`), the call is
recorded as a `Call` (`external_id = call_sid`, direction `inbound`) and the
JSON-RPC body forwards the call, plays the notice (`file_to_A`) and points
Exolve at `POST /voice/exolve/events`. The body echoes our call id as
`client_id`, which — together with `Call.external_id` — correlates every later
notification back to the call. `POST /voice/exolve/events` maps `b/o/s/e` to the
*same* `CallSessionService` the mock provider uses, so the
`answered`+consent recording gate applies unchanged; `h` and unknown types are
acknowledged without a transition. Both endpoints are signed with
`VOICE_WEBHOOK_SECRET`; the callback base is `PUBLIC_BASE_URL`.

**Provider recording download** (`services/provider_recording.py`). Exolve
records at the SIP-resource level and announces the finished file with `crr`
(`uid` = the Call Record id). The webhook only parks that id on the
`call_audio` row (`provider://exolve/<uid>`) and queues `download_recording`;
the worker then pulls `GET /statistics/download/{uid}` and stores the object in
MinIO before handing off to ASR. Two rules hold:

- the download happens only for a call our own flow recorded
  (`recording_started_at`, i.e. `answered` + consent) — a `crr` for a
  non-consented call is audited as `recording.rejected` and its audio is never
  fetched or stored;
- it is idempotent: audio already in storage is left alone, so a client upload
  wins over the provider copy and a re-delivered `crr` does not re-download.

The download URL is built from `EXOLVE_API_BASE_URL` + the record id, never from
the notification's `path` field, so a forged callback cannot redirect the fetch.
Without `EXOLVE_API_KEY` the worker logs and skips the job.

**Client audio ingest** (`services/audio_ingest.py`). The app POSTs the raw
recording (`Content-Type: audio/*`) to `POST /calls/{id}/audio`; the body is the
mixed stream, or one per-leg track with `?leg=operator` / `?leg=client`. The
service writes to MinIO (SSE-AES256, retention expiry), fills the `call_audio`
row and queues ASR once the recording is complete (mixed, or both legs).
Re-uploading a role replaces the object and deletes the superseded one. The
endpoint refuses any call without `recording_started_at` — the storage-side half
of the `answered`+consent gate — and is owner-only.

The upload is **resumable**, because a dropped connection must not lose what was
already recorded: with `Content-Range: bytes <start>-<end>/<total>` the body is
one chunk and is written to storage immediately, so the `offset` returned is
durable. A client that reconnects (Wi-Fi hand-off, 4G dead spot, weak signal)
resumes from that offset; re-sending an already-stored chunk is idempotent
(accepted, not stored twice); a gap or partial overlap is `409` with
`expected_offset`. Chunks are assembled into the final object once the last one
arrives and then deleted; `?restart=true` abandons an in-flight upload. Without
`Content-Range` the upload is a single whole-object request (replacement).

## ML pipeline (research, Stage 6 groundwork)

Full description: [`ML_PIPELINE.md`](ML_PIPELINE.md) (target pipeline, what is
implemented, gaps, config, how to run, privacy).

Streaming ASR (T-one, Russian telephony 8 kHz) + speaker roles + LLM
extraction, wired into the workers and the database.

The audio stream arrives from the mobile client (`POST /calls/{id}/audio`), not
from the voice provider — see §11.1 of `plan.md`.

```
src/app/ml/
  pipeline.py   # orchestrator: audio -> transcript -> agreements + events
  asr/
    ports.py     # ASRPort, TextPhrase
    tone.py      # ToneASRClient (WebSocket /api/ws, 8 kHz int16 PCM)
  diarization/
    ports.py     # DiarizationPort, SpeakerSegment
    pyannote.py  # PyannoteDiarizer (gated speaker-diarization-3.1)
  extraction/
    llm.py       # InstructorLLMExtractor (OpenAI-compatible, Instructor)
    service.py   # ExtractionService: LLM -> validate (raw + validated)
    validation.py# rule-based checks vs the transcript
    context.py   # ConversationContext
  stt/
    schemas.py   # TranscriptSegment, Transcript(+role_source)
    pipeline.py  # channels->roles (VoIP); pyannote fallback (mono/PSTN)
    __main__.py  # CLI: python -m app.ml.stt <conversation_id>
```

**Speaker roles.** For VoIP the recording is channel-separated (one leg per
party): each leg is transcribed on its own and the role is known from the
channel — no diarization. Only mono/PSTN audio (a single mixed stream) goes
through pyannote; the first speaker becomes `operator`, the second `client`.
`Transcript.role_source` records which path was used (`channel` | `diarization` |
`unknown`) for audit.

**Production pipeline** (`pipeline.py`, run by the workers):

1. `worker-asr` (`download_recording`) — when Exolve announces a finished
   recording (`crr`), fetch it through the Call Record API and store it in
   MinIO, then enqueue `process_asr`. Skipped when the audio is already in
   storage or the call was not recorded with consent.
2. `worker-asr` (`process_asr`) — load the recording from MinIO/S3, transcribe,
   persist the segmented transcript into `transcripts` (1:1 with the call),
   publish `partial_transcript` events, then enqueue `worker-ai`.
3. `worker-ai` (`run_llm_extraction`) — LLM extraction + rule-based validation,
   create proposed `agreements` (raw/validated output kept apart in
   `agreement_extractions`), publish `agreement_detected`.

Both ASR and extraction are idempotent by `call_id`: re-processing reuses the
stored transcript / agreements instead of recomputing. The client upload
(`POST /calls/{id}/audio`) queues `worker-asr` automatically once the recording
is complete; `POST /calls/{id}/analyze` re-queues explicitly. The LLM part is off
unless `LLM_BASE_URL`/`LLM_MODEL` are set (`llm_enabled`).

**Live streaming.** In addition to the one-shot upload, the client can stream
per-leg audio during the call to `WS /calls/{id}/audio?leg=operator|client|mixed`
(JWT, owner-only, gated by `recording_started_at`). The API (ML-free) fans the
8 kHz int16 PCM frames out to a Redis stream per leg; `worker-asr-live` runs
T-one incrementally and publishes `partial_transcript` as phrases arrive, and
`worker-ai-live` re-runs extraction (debounced by `LIVE_DEBOUNCE_SEC`) so the
live card updates during the call. `agreement_detected` is reused for created
*and* updated agreements (stable `agreement.id`, growing `version`) — the client
upserts by id. The final recording upload stays the path for retention/audit and
as the batch fallback; live and batch are idempotent by `call_id`.

**Self-hosted LLM.** `ollama` runs as a compose service (model `qwen2.5:7b`,
host cache mounted); the workers reach it at `http://ollama:11434/v1`.

Run the T-one ASR server locally (optional; also reachable on the research
Mac via Tailscale):

```bash
docker compose --profile ml up -d asr
```

Install the ML extras for the pipeline and its tests:

```bash
uv sync --extra ml        # adds numpy, soundfile, soxr, pyannote-audio, torch, instructor, openai
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

## LLM extraction

Извлечение договорённостей (`src/app/ml/extraction/`) работает с любым
OpenAI-совместимым API и отдаёт `app.domain.commitment.Commitment` — тот же
контракт, что принимает Agreement Service.

```bash
# локально (Ollama)
brew install ollama && ollama pull qwen2.5:7b
# .env:
#   LLM_API_KEY=ollama
#   LLM_BASE_URL=http://localhost:11434/v1
#   LLM_MODEL=qwen2.5:7b
uv sync --extra ml   # instructor + openai (входит в ml extra)
```

Извлечение из транскрипта (rule-пас в `validation.py` сверяет `source_quote` с
транскриптом, таймкоды — с длительностью звонка; расхождения -> `AmbiguityFlags`
-> `needs_clarification`):

```python
from app.config import get_settings
from app.ml.extraction.llm import InstructorLLMExtractor
from app.ml.extraction.service import ExtractionService

settings = get_settings()
service = ExtractionService(
    InstructorLLMExtractor(settings.llm_api_key, settings.llm_base_url, settings.llm_model)
)
commitments = await service.extract(context)  # list[Commitment]
```

Eval по gold: `services/api/research/03_extraction_eval.ipynb` (Recall/Precision
по категориям).

## WebSocket events

`/api/ws/calls/{call_id}` streams live call events; `services/events.py` is the
hub (`CallEventMessage` persisted to Redis under `events:call:{id}` for replay,
published on the same key for live delivery). Every frame is a versioned
envelope (schema version 1):

```json
{"version": 1, "event": "agreement_detected", "call_id": "…", "payload": { … }}
```

| property        | value |
| --------------- | ----- |
| auth            | `Authorization: Bearer <access token>` **or** `?token=<access token>` (browsers) |
| access          | call owner only — managers never receive audio/transcript |
| handshake close | `4401` unauthorized · `4403` forbidden · `4404` unknown call |
| replay          | persisted events are sent on connect, then live events follow |
| event types     | `partial_transcript`, `agreement_detected`, `analysis_started`, `call_ended` |
| contract        | `GET /ws/events/schema` (envelope JSON schema + event list, also in OpenAPI) |

Event types are emitted by the ML workers (Stage 6, Track B), except
`analysis_started` / `call_ended`, which the call session emits today.

## Workers

Celery, one image, separate queues (`worker-asr`, `worker-ai`, `worker-asr-live`,
`worker-ai-live`, `worker-notifications`). `beat` schedules the daily audio
retention purge (`purge_expired_audio`); `POST /me/data/delete` enqueues
`request_data_deletion`. Both run against `services/data_deletion.py`.

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
T-one ASR client protocol, the STT speaker/role merge, the WebSocket event
stream (auth, ownership, replay, live delivery), the confirmed-only
calendar/reminder/draft side effects (future-only reminders, draft never sent),
and the МТС Exolve adapter (event mapping, routing body, Call Record API,
notice/DTMF behaviour).

## Roadmap

Stage order follows `plan.md`: this is Stage 2 (plus research ML groundwork and
the Track C voice/integration increments). Staged placeholders: wiring the ML
pipeline into the workers (Stage 6), real third-party calendar/reminder
adapters, the Exolve call-control/event webhook routes and end-to-end call
wiring (`plan.md` §11.1), and the mobile app (Stage 3+).