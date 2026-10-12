# Project: Documentation of MTS telephone agreements

Cross-platform mobile assistant that turns conversations into confirmed
commitments and delivers them to user-selected external apps.

## Product rules

- The product captures agreements: deadlines, meetings, payments, promises,
  follow-ups, and open questions.
- Never create a calendar event, reminder, note, message, CRM record, or email
  without explicit user confirmation.
- Every extracted commitment must include:
  - type
  - title
  - owner: user, counterparty, or unknown
  - due date/time when applicable
  - source quote from the transcript
  - audio start/end timestamps
  - confidence
  - status
- If information is ambiguous, mark the commitment as
  `needs_clarification`; do not invent dates, amounts, names, or obligations.
- Preserve the original quote and audio timestamps for auditability.
- The user must be able to edit or reject every proposed action.

## Architecture rules

- Mobile client: Flutter/Dart under `apps/mobile`.
- Backend and ML pipeline: Python/FastAPI under `services/api`.
- Do not put business logic, ML inference, or external-app adapters directly
  into Flutter widgets.
- Use clean layering:
  - UI layer: widgets and state
  - Application layer: use cases and state controllers
  - Domain layer: entities and business rules
  - Infrastructure layer: API clients, database, native integrations
- Backend layers:
  - `api/`: HTTP routes and request/response schemas
  - `domain/`: entities, enums, validation rules
  - `ml/`: ASR, VAD, diarization, LLM extraction
  - `integrations/`: calendar, reminders, notes, messaging, CRM adapters
  - `workers/`: async jobs for audio processing and delivery
- External integrations must implement a common port/interface, for example:
  - `CalendarPort.create_event()`
  - `RemindersPort.create_reminder()`
  - `NotesPort.create_note()`
  - `MessagingPort.send_summary()`
- A new integration must be added as an adapter, not by changing the ML
  pipeline or mobile UI.

## Cross-platform rules

- Target Android and iOS with one Flutter codebase.
- Never use Android-only or iOS-only APIs directly in feature code.
- Wrap platform-specific code behind an abstract interface and inject the
  implementation through dependency injection.
- Request permissions only when the relevant feature is used:
  microphone, notifications, calendar, contacts, background audio.
- Provide a graceful fallback when a permission is denied:
  manual entry, share sheet, or local draft.
- Do not assume calendar, reminders, or notes APIs behave identically on both
  platforms; test both paths.
- Use UTC in the backend and store the user timezone separately.
- Format all user-facing dates using the device locale.

## ML and data rules

- Audio processing is asynchronous: upload returns a conversation ID and
  processing status, not a blocking result.
- Pipeline order:
  audio -> VAD -> diarization -> ASR -> transcript -> LLM extraction ->
  validation -> user confirmation -> external action.
- Store raw LLM output, validated output, and user edits separately.
- Never trust an LLM-extracted date without validation against the
  conversation date and user timezone.
- Redact or restrict access to audio and transcripts; they contain personal
  and commercial information.
- Log model prompts and responses only with explicit redaction and user
  consent.

## Code quality

- Dart: use strict analyzer settings, immutable models where practical,
  Riverpod for state, and no business logic inside widgets.
- Python: use ruff, mypy, Pydantic v2, dependency injection, and async I/O.
- Every API endpoint must have request/response schemas and error handling.
- Every external integration must be mockable in tests.
- Write tests before changing extraction, validation, scheduling, or
  integration logic.
- Do not commit secrets, API keys, audio files, or real transcripts.

## Commands

- Mobile analyze: `cd apps/mobile && flutter analyze`
- Mobile tests: `cd apps/mobile && flutter test`
- Backend lint: `cd services/api && ruff check .`
- Backend types: `cd services/api && mypy .`
- Backend tests: `cd services/api && pytest`
- Local stack: `docker compose up -d`
- Generate API client after OpenAPI changes.

## Definition of done

- Feature works on Android and iOS or has an explicit platform limitation.
- User confirmation is required before any external write.
- Tests cover domain rules, API contract, and integration adapter.
- No secrets or personal data are committed.
- Documentation is updated if the API, data model, or user flow changed.

## Python dependency management

- Use `uv` for all Python code under `services/`.
- Never create or edit `requirements.txt` for the backend.
- Never manually edit `uv.lock`.
- Add runtime dependencies with `uv add <package>`.
- Add development dependencies with `uv add --dev <package>`.
- Run Python tools through `uv run`, for example:
  - `uv run pytest`
  - `uv run ruff check .`
  - `uv run mypy .`
- Commit both `pyproject.toml` and `uv.lock`.
- Do not commit `.venv/`.
- If dependencies change, run `uv sync` and ensure tests pass.
- Keep ML-heavy dependencies in an optional dependency group when they are
  not required to run the API locally.