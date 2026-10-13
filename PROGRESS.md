# Прогресс проекта (для анализа готовой части)

Обновлять при каждом мёрже. Легенда: ✅ готово и зелёные гейты · 🔶 частично
(есть backend/исследование, ждёт интеграции) · ⬜ не начато.

Сводка на 2026-10-13: **Этапы 1–3 закрыты**, ML-исследование слито; всё остальное
— в работе по `TEAM_PLAN.md`. Разработка ведётся в ветках `track/mobile`
(Xivalor), `track/ml` (Sofiya), `track/backend-voice` (Mav); после зелёных гейтов
и ревью — мерж в `development`.

---

## По этапам (plan.md §17)

| Этап | Статус | Что готово | Что не готово |
|---|---|---|---|
| 1. Подготовка | ✅ | MVP-сценарий, роли, стек Flutter, репо, структура | **выбор voice-провайдера** (пункт Этапа 1!) — открыт, блокер Этапа 4 |
| 2. Серверная основа | ✅ | Postgres/Redis/MinIO, модели, auth+роли, CRUD, docker compose, миграции; 69 тестов | — |
| 3. Мобильная основа | ✅ | `apps/mobile` (Flutter): слои UI/App/Domain/Infra, OTP-auth + refresh, контакты за портом, личная доска, SQLite (tasks/agreements/outbox/sync_state/session), Repository + sync (pull→apply→push→ack→token), `--dart-define=API_BASE_URL`; analyze ✓, 33 теста | сборка/прогон на эмуляторе (нет Android SDK/Xcode в среде) — см. ограничение |
| 4. Звонки | 🔶 | `VoiceProviderPort` (mock) + webhook-маршруты в backend; state machine | реальный провайдер (блокер), VoIP SDK, экран звонка, исходящие |
| 5. Consent flow | 🔶 | backend-логика целиком: `consent.py`, `call_session.py`, state machine, тесты notice/DTMF/refusal/withdraw | аудио-уведомление собеседнику (play_notice), DTMF через провайдера, мобильные экраны |
| 6. Запись и анализ | 🔶 | research-слой `src/app/ml`: T-one ASR-клиент, pyannote-диаризация, STT-пайплайн (roles, resample); S3-хранилище; Celery-воркеры (заглушки) | VAD/чанкинг, worker-asr/ai задачи, LLM-извлечение, транскрипты в БД, WS-события |
| 7. Договорённости и задачи | 🔶 | backend: agreement-статусы, confirm→task, PATCH-guards, audit; тесты | live-карточка (UI), напоминания, привязка к звонку в UI |
| 8. Доски | 🔶 | backend: `/me/tasks`, `/manager/team/tasks|stats|members`, роли+team, тесты доступа | мобильные доски (личная и менеджерская), фильтры/сортировка, аналитика UI |
| 9. Итог и календарь | 🔶 | черновик клиенту (`integrations/outbound.py`), `icalendar` в депсах, история звонков в БД | `CalendarPort`/`.ics` генерация, `RemindersPort`, резюме разговора, UI |
| 10. Тестирование и демо | 🔶 | сквозное демо проверено: OTP → входящий → consent → задача → доска менеджера | тесты реальных звонков, 4G/обрыв WS, офлайн-синк, презентация |

---

## Backend — карта модулей (services/api/src/app)

### api/ — HTTP-слой (полный, из Этапа 2)
- `routes.py` — все эндпоинты: `/auth/*`, `/me*`, `/calls*`, `/agreements*`,
  `/tasks*`, `/manager/team/*`, `/sync` GET/POST, `/healthz`
- `schemas.py` — Pydantic v2: UserOut, AuthResponse, CallOut, AgreementOut,
  TaskOut, SyncChange/Pull/Push/Result, ErrorBody
- `dependencies.py` (auth/role deps), `errors.py` (единый формат ошибок)
- `/docs` (OpenAPI) доступен

### domain/ — бизнес-правила (без IO, тестируются отдельно)
- `state_machine.py` — жизненный цикл звонка (входящий→…→completed+missed/failed),
  невалидный переход = ошибка
- `commitment.py` — типы договорённостей (обязательство/дедлайн/встреча/платёж/
  обещание/follow-up/открытый вопрос)
- `dates.py` — относительные даты («на следующей неделе» → детерминированно,
  `ambiguous` флаг), TZ пользователя
- `rules.py` — confidence threshold (0.8, из конфига)
- `enums.py` — agreement/task/call-статусы, SyncEntity, consent-методы

### services/ — use cases
- `auth.py` — OTP в Redis, JWT access + rotating refresh (jti в Redis), logout-ревокация
- `call_session.py` — запись только после `answered` + согласия; `analysis_started`
- `consent.py` — режимы notice/dtmf/sms_link; запись в `consents`
- `agreement.py` — статусы, confirm→task, PATCH-guards (confirmed/rejected final)
- `task.py` — статусы задач, complete
- `sync.py` — delta pull (since-token), идемпотентный push (idempotency_key hash),
  конфликт → server version
- `manager.py` — доска команды: роли+team_id проверяются на сервере
- `access.py` — права user/manager
- `events.py` — event hub в Redis (`events:call:{id}`), replayed для late joiners;
  типы: `partial_transcript | agreement_detected | analysis_started | call_ended`

### infrastructure/
- `db/` — SQLAlchemy async: models, repositories, session; `migrations/` (Alembic,
  initial `ee8b295d7610`)
- `storage.py` — S3/MinIO (аудио, retention), `cache.py` — Redis
- `security.py` — JWT HS256

### integrations/ — внешние порты
- `voice.py` — **VoiceProviderPort (mock)**; webhook-signature `VOICE_WEBHOOK_SECRET`
- `outbound.py` — черновик сообщения клиенту (не отправляется автоматически — правило!)

### ml/ — research-слой (Этап 6 groundwork, уже в проде-структуре)
- `asr/` — `ASRPort`, `ToneASRClient` (WS /api/ws, 8 кГц int16, chunking)
- `diarization/` — `DiarizationPort`, `PyannoteDiarizer` (speaker-diarization-3.1, HF_TOKEN)
- `stt/` — `Transcript`, `pipeline.py` (load→resample→merge→roles), CLI
  `python -m app.ml.stt <id>`
- ⚠️ НЕ запитан: воркеры — заглушки (`worker.py`), события не эмитятся, транскрипты не сохраняются

### worker.py / workers/
- Celery, очереди `asr|ai|notifications`; задачи-заглушки (явные плейсхолдеры)

### cli.py
- `python -m app.cli seed` — демо-данные: менеджер Ирина +79000000001, Анна
  +79000000002, Борис +79000000003, задачи, звонки

---

## ML (research vs production)

| Часть | research | production |
|---|---|---|
| Синтез звонков | ✅ `research/` (TTS, wav) | — |
| Streaming ASR (T-one) | ✅ `ml/asr/tone.py` + тест протокола | 🔶 не в воркере |
| Диаризация (pyannote) | ✅ `ml/diarization/` | 🔶 не в воркере |
| STT-пайплайн | ✅ `ml/stt/` + тесты | 🔶 не в воркере |
| VAD/чанкинг | ⬜ | ⬜ |
| LLM-извлечение | ⬜ (формат готов: `domain/commitment.py`) | ⬜ |
| События/WebSocket | — | ⬜ (hub готов) |
| Транскрипты в БД | — | ⬜ |

---

## Мобильное приложение (`apps/mobile`, Этап 3 ✅)

Flutter 3.47.7 / Dart 3.13.5 (SDK вне репо). Слои: `core/`, `domain/` (enums,
models, sync_models, ports), `application/` (Riverpod-контроллеры + providers),
`infrastructure/` (api/dio, db/sqflite, repositories, sync), `ui/` (экраны).
Подробности — `apps/mobile/README.md`.

- **Auth**: OTP (`/auth/otp/request`, `/auth/login`), rotating refresh; сессия в
  SQLite, авто-refresh на 401 в dio-интерцепторе.
- **Доска**: личные задачи из кэша, pull-to-refresh запускает sync; offline-first.
- **Локальная БД** (sqflite, `_schemaVersion = 1`): `tasks`, `agreements`,
  `session`, `outbox` (уникальный `idempotency_key`), `sync_state`.
- **Sync engine**: pull `GET /sync?since=` → apply (пропуск `version <= known`),
  push outbox `POST /sync` → accepted снимает операцию, conflict сбрасывает токен
  (полный re-pull), rejected снимает операцию; ретраи с backoff на network/5xx.
- **Контакты**: порт `ContactsSource` над `flutter_contacts`; при отказе в
  доступе — ручной ввод номера (graceful fallback).
- ⚠️ **Ограничение среды**: нет Android SDK/Java/Xcode → проверка только на
  уровне Dart (`flutter analyze` + `flutter test`); сборка/запуск — на машине с
  SDK. Платформенное скрыто за портами/DI.

---

## Инфраструктура и контейнеры

- `docker-compose.yml` — postgres, redis, minio, migrate (one-off, Alembic),
  api, worker-asr/ai/notifications, nginx (TLS+WS), **asr** (T-one, профиль `ml`)
- `docker-compose.override.yml` — dev-порты
- `services/nginx` — TLS-терминация, WS-проксирование (Upgrade/Connection,
  dynamic upstream через resolver)
- Dockerfile: base/api/worker targets; UV_NO_SYNC; worker тянет `--extra ml`
- Правила соблюдены: healthchecks + `service_healthy`, только nginx наружу,
  секреты из .env, никаких `down -v` без спроса

---

## Тесты

| Группа | Файлы | Что покрывают |
|---|---|---|
| unit (3) | test_dates, test_rules, test_state_machine | относительные даты, пороги, переходы звонка |
| integration (6) | test_auth, test_access, test_call_consent, test_agreements_tasks, test_sync, test_manager | OTP/refresh, права ролей+команды, запись без consent, confirm→task, sync-идемпотентность |
| ml (2) | test_tone_client, test_pipeline | протокол T-one, слияние ролей/ресамплинг |
| mobile (7) | domain/models, infrastructure/local_stores, infrastructure/sync_engine, application/auth_controller, application/board_controller, application/contacts_controller, widget/app | парсинг моделей, SQLite-хранилища, цикл sync + идемпотентность/конфликт/ретраи, контроллеры, экраны |

Backend: **74 passed** (unit 38 + integration 31 + ml 5); интеграционные требуют
`docker compose up -d postgres redis` (отдельная БД `agreements_test`).
Mobile: **33 passed** (`flutter test`, без Docker); локальные хранилища тестируются
через `sqflite_common_ffi`.

---

## Как проверить текущее состояние

```bash
cd services/api
uv run ruff check .        # lint
uv run mypy .              # types
uv run pytest              # 74 теста
docker compose up -d       # поднять стек
uv run python -m app.cli seed   # демо-данные (если БД пуста)
curl -k https://localhost/api/healthz   # живо (nginx TLS)

cd apps/mobile
flutter analyze            # lint мобильного (чисто)
flutter test               # 33 теста (Dart-уровень, без Docker)
```

Демо-флоу (проверен): OTP-логин (dev OTP 1234) → `/calls` POST + вебхук
`X-Voice-Webhook-Secret: dev-voice-secret` → answered → consent `audio_notice`
→ `recording_started_at` + `analysis_started` → agreement confirm → задача →
`/manager/team/tasks`.

---

## Блокеры и открытые решения

| Блокер | Влияние |
|---|---|
| Выбор voice-провайдера (Этап 1, остался открытым) | Этап 4 целиком + реальная запись |
| Выбор LLM (самохостинг предпочтителен) | Этап 6, LLM-часть |
| Формат WS-событий | мобильная live-карточка (Этап 7) и эмиссия ML |

## История (для контекста)

- `3ddd35a…e6c15a0` — подготовка: план, AGENTS, research-эксперименты (agreement type — free string)
- `992d46e` — research: тип договорённости строкой вместо enum
- `c4fd7cd` — add: diarization pipeline (ASR+диаризация+STT)
- `361a76b` — **Этап 2** + интеграция ML в `src/app/ml/` (resolved merge)