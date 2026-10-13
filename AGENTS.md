# Project: AI agent for capturing agreements in phone conversations

Cross-platform mobile application for users and their manager. The user takes
or makes calls through the app (VoIP/PSTN via a Voice Provider). After the
consent flow, the conversation is recorded and analyzed by AI: agreements,
deadlines, obligations, and next steps are extracted. The user confirms the
result, after which tasks, reminders, and calendar events are created. The
manager sees the team's tasks on a shared board, plus analytics.

Source of requirements: `plan.md`. If this file and `plan.md` disagree, stop and
ask; do not guess.

## Product rules

- The product captures agreements: obligations, deadlines, meetings, payments,
  promises, follow-ups, and open questions.
- Never create a task, reminder, calendar event, note, client message, or
  record in any external system without explicit user confirmation.
- Every extracted agreement must include:
  - type
  - title / object
  - owner: user, counterparty, or unknown
  - due date (and time, when applicable)
  - source quote from the transcript
  - audio start/end timestamps
  - confidence
  - status
- Agreement statuses: `detected`, `requires_review`, `needs_clarification`,
  `confirmed`, `rejected`. A task is created only from a `confirmed` agreement.
- If confidence is below the threshold (default 0.8), the status is
  `requires_review` and no task is created automatically. The threshold lives
  in configuration.
- If information is ambiguous (a deadline like "next week", a missing amount, an
  unclear owner), set `needs_clarification`. Do not invent dates, amounts,
  names, or obligations.
- Preserve the original quote and audio timestamps for auditability.
- The user must be able to edit or reject every proposed action.
- Automatically sending messages to the client is forbidden. Only produce a
  draft that the user sends themselves.
- Task statuses: `new`, `in_progress`, `done`, `overdue`, `canceled`.

## Roles and access

- Two roles: `user` and `manager`. An admin panel and a complex role model are
  out of MVP scope.
- A user sees only their own calls, agreements, tasks, and reminders.
- A manager sees the tasks of all users in their team (`team_id`) and the
  analytics. Tasks from other teams are never accessible.
- Permissions are enforced on the server, not only in the UI. Every manager
  endpoint checks both the role and team membership.
- A manager sees tasks and metadata but does not get access to subordinates'
  audio or transcripts unless that is decided separately and recorded in
  `plan.md`.

## Consent flow (critical)

- Recording starts only after the `answered` state and a successful consent
  flow. This rule must not be bypassed in code, tests, or demo mode.
- Call lifecycle:
  `incoming → ringing → answered → consent_notice → consent_result → recording →
  analyzing → in_progress → completed`, plus terminal `missed` and `failed`.
  Transitions are validated by a state machine in the domain layer; an invalid
  transition is an error.
- Backend logic on `call.answered`:
  1. check the app user's consent;
  2. no consent → ordinary call, recording is not enabled;
  3. play the audio notice to the other party;
  4. record the consent event;
  5. the other party refused → recording is not enabled;
  6. consent granted → start recording and the media stream;
  7. start ASR and AI analysis;
  8. send an `analysis_started` event to the app.
- Counterparty consent modes: notice + continuing the call, active consent
  (DTMF 1), refusal (DTMF 2), prior consent (SMS/app link).
- The `consents` table records the consent text version, date, method
  (`app_settings`, `audio_notice`, `dtmf`, `sms_link`), `call_id`, and status
  (`granted`, `denied`, `withdrawn`).
- The user can withdraw consent and request data deletion. Implement this as a
  real flow, not as "later".
- Without consent the app keeps working as an ordinary call and offers manual
  entry of agreements.

## Architecture rules

- Mobile client: Flutter/Dart under `apps/mobile` (stack from the plan: Flutter,
  one codebase for iOS and Android).
- Backend and ML pipeline: Python/FastAPI under `services/api`.
- Do not put business logic, ML inference, or external-system adapters into
  Flutter widgets.
- Clean layering:
  - UI: widgets and state
  - Application: use cases and state controllers
  - Domain: entities and business rules
  - Infrastructure: API clients, local database, native integrations
- Backend layers:
  - `api/`: HTTP routes, WebSocket, request/response schemas
  - `domain/`: entities, enums, state machines, validation rules
  - `services/`: Call Session, Consent, Agreement, Task, Notification,
    Manager Dashboard
  - `ml/`: VAD, diarization, ASR, LLM extraction
  - `integrations/`: Voice Provider, calendar, reminders, notifications
  - `workers/`: async jobs (ASR, AI, notifications)
- External systems are connected through a common port/interface:
  - `VoiceProviderPort` (answer, hangup, play_notice, start_recording,
    open_media_stream)
  - `CalendarPort.create_event()` / `.ics` generation
  - `RemindersPort.create_reminder()`
  - `MessagingPort.send_summary()` (only after confirmation)
- A new provider or integration is added as an adapter, without changing the ML
  pipeline or the mobile UI. The Voice Provider is chosen in stage 1; until then
  use the port and a mock.
- Server-side PostgreSQL is the single source of truth. The phone's local
  database is a cache and an offline change queue, not a separate system of
  record.

## Cross-platform rules

- Android and iOS from one Flutter codebase.
- Never use Android-only or iOS-only APIs directly in feature code.
- Hide platform-specific code (CallKit/PushKit on iOS, Telecom/ConnectionService
  on Android, APNs, FCM, background mode) behind an abstract interface and
  inject the implementation through dependency injection.
- Request permissions only when the relevant feature is used: microphone,
  notifications, calendar, contacts, background work.
- Provide a graceful fallback when a permission is denied: manual entry, share
  sheet, local draft.
- Do not assume calendar, reminders, or incoming VoIP calls behave identically
  on both platforms; test both paths.
- Use UTC in the backend and store the user's timezone separately.
- Format all user-facing dates using the device locale.
- The mobile app is not containerized. Docker is for the server side only.
- Out of MVP scope: recording ordinary cellular calls in the system Phone app.
  Do not attempt to implement it.

## Calls

- Incoming: Voice Provider → push → app → "Answer" → `Call.answer()` → consent →
  recording → media stream → ASR + LLM.
- Outgoing: app → VoIP → Voice Provider → PSTN → ordinary number. The other
  party does not need the app; AI capture works on the initiator's side.
- Handle events: incoming, ringing, answered, ended, dropped, missed.
- Network loss during a call must not lose what was already recorded. Cover this
  with tests (Wi-Fi, 4G, weak signal).

## ML and data rules

- Audio processing is asynchronous: starting or uploading returns a
  conversation/call ID and a processing status, not a blocking result.
- Pipeline order:
  media stream → decoder → VAD/chunking → diarization → ASR → transcript buffer →
  LLM extraction → validation → Agreement Service → WebSocket → user confirms →
  task/reminder/calendar event.
- Store raw LLM output, validated output, and user edits separately.
- Never trust an LLM-extracted date without validating it against the
  conversation date and the user's timezone ("by Friday" is resolved
  deterministically in code).
- The transcript is stored in the `transcripts` table. Do not duplicate it in
  `calls`.
- Reprocessing the same audio must be idempotent.
- Audio and transcripts contain personal and commercial data: encrypt them,
  restrict access, and set a limited retention period for audio.
- Log LLM prompts and responses only with redaction and user consent.

## API and WebSocket

- Every endpoint has request/response schemas (Pydantic v2) and error handling.
- Endpoints from the plan: `/auth/login`, `/calls`, `/sync`, `/me/tasks`,
  `/tasks/{id}` (PATCH), `/tasks/{id}/complete`, `/manager/team/tasks`,
  `/manager/team/stats`, `/manager/team/members`.
- WebSocket events: `partial_transcript`, `agreement_detected`,
  `analysis_started`, `call_ended`. The event schema is versioned; after any
  change, update OpenAPI and regenerate the API client.
- JWT access token with a short lifetime plus a refresh token.

## Local database and sync

- The local SQLite database stores only the user's own data: profile and role,
  their tasks and agreements, recent calls, offline drafts, outbox, `sync_token`,
  and record versions.
- Do not store: other employees' tasks, team data, unnecessary audio, or data
  the user has no access to.
- Flow: UI → Repository → Local DB → Outbox → Sync Engine → Server.
- Cycle: pull (`GET /sync?since=`) → apply to the local DB → push outbox → ack and
  delete successful operations → update `sync_token`.
- Every operation has an `idempotency_key`. Retry with backoff on error. On
  conflict the server returns the authoritative version (the `version` field).
- Sync deltas, not the whole database. The local cache can always be fully
  restored from the server.

## Code and data security

- Audit: `audit_log` records consent, recording start, and changes to agreements
  and tasks.
- Do not commit secrets, API keys, audio files, or real transcripts.
- The Postgres/MinIO values in `docker-compose.yml` (`app`, `minio123`) are for
  local development only. Real values come from `.env`; only `.env.example` is
  committed.

## Code quality

- Dart: strict analyzer settings, immutable models, Riverpod for state, no
  business logic inside widgets.
- Python: ruff, mypy, Pydantic v2, dependency injection, async I/O.
- Every external integration must be mockable in tests (including the Voice
  Provider and the LLM).
- Write tests before changing extraction, validation, scheduling, consent, sync,
  or integration logic.
- Required tests: call state transitions, recording blocked without consent,
  relative date resolution, confidence threshold, manager/user access rights,
  sync idempotency.

## Commands

- Mobile analyze: `cd apps/mobile && flutter analyze`
- Mobile tests: `cd apps/mobile && flutter test`
- Backend lint: `cd services/api && uv run ruff check .`
- Backend types: `cd services/api && uv run mypy .`
- Backend tests: `cd services/api && uv run pytest`
- Local stack: `docker compose up -d`
- Regenerate the API client after OpenAPI changes.

## Docker and containers (server side only)

- Every component runs in its own container: `api`, `worker-asr`, `worker-ai`,
  `worker-notifications`, `postgres`, `redis`, `minio`, `nginx`. They all share
  one docker compose network. The MVP server side starts with
  `docker compose up -d`.
- Containers reach each other by service name (`postgres`, `redis`, `minio`),
  never via `localhost` or `127.0.0.1`. Inside a container, `localhost` is the
  container itself.
- Addresses and credentials come only from environment variables
  (`DATABASE_URL`, `REDIS_URL`, `S3_ENDPOINT`, etc.). Never hardcode hosts. When
  running on the host (tests, debugging), the same variables point to
  `localhost` and the published ports.
- Only `nginx` is published to the outside. `postgres`, `redis`, and `minio` do
  not publish ports in production. In dev, `docker-compose.override.yml` opens
  them.
- `postgres`, `redis`, and `minio` have healthchecks. Services that depend on
  them use `depends_on` with `condition: service_healthy`, not just start order.
- Migrations (Alembic) run in a separate one-off `migrate` service: it starts
  after `postgres` and before `api` and the workers. Do not run migrations on API
  startup, and never from several containers at once.
- Containers are stateless. Data lives only in named volumes (`postgres_data`,
  `redis_data`, `minio_data`) and in S3 storage. Audio and transcripts are never
  written to the container filesystem.
- Do not run `docker compose down -v` or delete volumes without the user's
  explicit permission: it destroys data.
- `api` and the workers share code and one image with different start commands.
  Workers talk to the API only through the queue and the database, not over
  HTTP. Put ML-heavy dependencies in a separate build target for the workers so
  the API image stays light.
- Integration tests run against containers. Unit tests do not require Docker.
- The mobile app is not containerized. The backend URL comes from build
  configuration, not a hardcoded value: Android emulator → `10.0.2.2`, iOS
  simulator → `localhost`, physical device → the host's LAN IP or an HTTPS
  domain.
- `nginx` terminates TLS and proxies WebSocket (`Upgrade` and `Connection`
  headers, longer timeouts).

## Working order

Follow the stages from `plan.md` and do not skip ahead:

1. Preparation: MVP scenario, roles, stack, Voice Provider, repository
   structure.
2. Server foundation: Postgres, Redis, storage, models, auth and roles, CRUD,
   Docker Compose.
3. Mobile foundation: authentication, contacts, personal board, local database,
   Repository and sync.
4. Calls: Voice SDK, incoming VoIP, outgoing calls to ordinary numbers, call
   screen.
5. Consent flow: consent screen, notice to the other party, recording the
   result, blocking recording without consent.
6. Recording and analysis: media stream, streaming ASR, LLM, WebSocket events.
7. Agreements and tasks: live card, edit and confirm, tasks, reminders.
8. Boards: personal and manager boards, filters, sorting, analytics, access
   restriction.
9. Call summary and calendar: summary, draft client message, calendar event or
   `.ics`, call history.
10. Testing and demo.

Before starting a stage, briefly verify that the previous one is done and its
tests are green. Work in small steps: schema and tests first, then
implementation, then documentation.

## Out of MVP scope

- Recording ordinary cellular calls in the system Phone app.
- Corporate CRM integration.
- Multilingual ASR (the MVP language is `ru`).
- A complex role model and an admin panel.
- Automatically sending messages to the client without confirmation.
- Billing, pricing plans, and corporate SSO.

## Definition of done

- The feature works on Android and iOS, or has an explicitly documented platform
  limitation.
- Recording is impossible without `answered` and consent. Any external write
  requires user confirmation.
- Tests cover domain rules, the API contract, and the integration adapter.
- Access rights are verified on the server for both roles.
- No secrets or personal data are committed.
- Documentation is updated if the API, data model, or user flow changed.
- MVP criterion: the demo runs from an incoming call to a task on the manager's
  board in under 3 minutes.

## Python dependency management

- Use `uv` for all Python code under `services/`.
- Never create or edit `requirements.txt` for the backend.
- Never manually edit `uv.lock`.
- Add runtime dependencies with `uv add <package>`.
- Add development dependencies with `uv add --dev <package>`.
- Run Python tools through `uv run` (`uv run pytest`, `uv run ruff check .`,
  `uv run mypy .`).
- Commit both `pyproject.toml` and `uv.lock`; do not commit `.venv/`.
- After dependencies change, run `uv sync` and make sure tests pass.
- Keep ML-heavy dependencies in an optional dependency group when they are not
  required to run the API locally.
