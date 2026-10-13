# Прогресс проекта (для анализа готовой части)

Обновлять при каждом мёрже. Легенда: ✅ готово и зелёные гейты · 🔶 частично
(есть backend/исследование, ждёт интеграции) · ⬜ не начато.

Сводка на 2026-10-13: **Этапы 1–3 закрыты**, ML-исследование слито. **ML-пайплайн
переведён в прод** (PR #5): запись → роли из каналов VoIP → сегментированный
транскрипт → LLM-извлечение → валидация → `agreement_detected`; реальные воркеры
и триггер `POST /calls/{id}/analyze`. Разработка ведётся в ветках `track/mobile`
(Xivalor), `track/ml` (Sofiya), `track/backend-voice` (Mav); после зелёных гейтов
и ревью — мерж в `development`.

---

## По этапам (plan.md §17)

| Этап | Статус | Что готово | Что не готово |
|---|---|---|---|
| 1. Подготовка | ✅ | MVP-сценарий, роли, стек Flutter, репо, структура; **voice-провайдер выбран: МТС Exolve** (§11.1) | — |
| 2. Серверная основа | ✅ | Postgres/Redis/MinIO, модели, auth+роли, CRUD, docker compose, миграции; 69 тестов | — |
| 3. Мобильная основа | ✅ | `apps/mobile` (Flutter): слои UI/App/Domain/Infra, OTP-auth + refresh, контакты за портом, личная доска, SQLite (tasks/agreements/outbox/sync_state/session), Repository + sync (pull→apply→push→ack→token), `--dart-define=API_BASE_URL`; analyze ✓, 33 теста | сборка/прогон на эмуляторе (нет Android SDK/Xcode в среде) — см. ограничение |
| 4. Звонки | 🔶 | `VoiceProviderPort` (mock) + webhook-маршруты в backend; state machine | реальный провайдер (блокер), VoIP SDK, экран звонка, исходящие |
| 5. Consent flow | 🔶 | backend-логика целиком: `consent.py`, `call_session.py`, state machine, тесты notice/DTMF/refusal/withdraw | аудио-уведомление собеседнику (play_notice), DTMF через провайдера, мобильные экраны |
| 6. Запись и анализ | 🔶 | **прод-пайплайн** (`ml/pipeline.py`): декодер + роли из каналов VoIP / диаризация для mono-PSTN (`ml/stt`), транскрипт в `transcripts` (JSONB-сегменты, `role_source`), LLM+Instructor + валидация (`ml/extraction`), реальные воркеры `process_asr`/`run_llm_extraction`, эмиссия `partial_transcript`/`agreement_detected`, триггер `POST /calls/{id}/analyze`, идемпотентность по `call_id` | приём аудио от клиента (`MEDIA_INGEST_URL` — эндпоинта нет), авто-триггер по Exolve `crr` (скачивание записи в MinIO), live-стриминг (сейчас batch по файлу), шифрование/redaction |
| 7. Договорённости и задачи | 🔶 | backend: agreement-статусы, confirm→task, PATCH-guards, audit; тесты | live-карточка (UI), напоминания, привязка к звонку в UI |
| 8. Доски | 🔶 | backend: `/me/tasks`, `/manager/team/tasks|stats|members`, роли+team, тесты доступа | мобильные доски (личная и менеджерская), фильтры/сортировка, аналитика UI |
| 9. Итог и календарь | 🔶 | backend: `schedule.py` — календарное событие/`.ics`/напоминания/черновик клиенту, только для confirmed-задач, тесты | резюме разговора, UI календаря/напоминаний, реальные адаптеры |
| 10. Тестирование и демо | 🔶 | сквозное демо проверено: OTP → входящий → consent → задача → доска менеджера | тесты реальных звонков, 4G/обрыв WS, офлайн-синк, презентация |

---

## Backend — карта модулей (services/api/src/app)

### api/ — HTTP-слой (полный, из Этапа 2)
- `routes.py` — все эндпоинты: `/auth/*`, `/me*`, `/calls*` (+ `POST /calls/{id}/analyze`
  — постановка ASR/LLM в очередь, 202), `/agreements*`, `/tasks*`,
  `/manager/team/*`, `/sync` GET/POST, `/healthz`
- `ws.py` — WebSocket `/ws/calls/{id}` (JWT, owner-only, replay+live, схема v1)
  + `GET /ws/events/schema`
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
- `schedule.py` — календарь/`.ics`, напоминания, черновик сообщения; только для
  задач из `confirmed`-договорённости (порты за `Integrations`)
- `sync.py` — delta pull (since-token), идемпотентный push (idempotency_key hash),
  конфликт → server version
- `manager.py` — доска команды: роли+team_id проверяются на сервере
- `access.py` — права user/manager
- `events.py` — event hub в Redis (`events:call:{id}`): replay-список + pub/sub,
  версия схемы 1, дедуп на стыке; типы: `partial_transcript | agreement_detected | analysis_started | call_ended`
- `jobs.py` — `AnalysisQueuePort` + `CeleryAnalysisQueue` / `NullAnalysisQueue`;
  постановка ASR в очередь (триггер анализа)

### infrastructure/
- `db/` — SQLAlchemy async: models, repositories, session; `migrations/` (Alembic,
  initial `ee8b295d7610`)
- `storage.py` — S3/MinIO (аудио, retention), `cache.py` — Redis
- `security.py` — JWT HS256

### integrations/ — внешние порты
- `voice.py` — `VoiceProviderPort`, `MockVoiceProvider`, `voice_provider_factory` (`mock`/`exolve`); webhook-signature `VOICE_WEBHOOK_SECRET`
- `exolve.py` — адаптер МТС Exolve: парсинг событий (`b/o/s/e/h/crr` → `CallEvent`), тело call-control (маршрут на SIP ID + `file_to_A`), Call Record API (`SetCallRecordState`/`GetInfo`/`Download`); `open_media_stream` → `MEDIA_INGEST_URL` (аудио льёт клиент), `collect_dtmf` → `None` (`CONSENT_MODE=notice`) — см. plan.md §11.1
- `outbound.py` — календарь/напоминания/черновик клиенту (не отправляется автоматически — правило!); фабрики портов

### ml/ — прод-пайплайн (Этап 6)
- `pipeline.py` — оркестратор: `load_call_audio` (ноги VoIP / смесь),
  `transcribe_and_store` (аудио → транскрипт в Postgres + `partial_transcript`),
  `extract_and_store` (транскрипт → agreements + `agreement_detected`); идемпотентно по `call_id`
- `stt/` — `CallAudio`, декодер (soundfile/soxr → 8 кГц int16), роли из каналов
  VoIP / диаризация для mono/PSTN, `role_source` (`channels|diarization|mono`); `Transcript`
- `extraction/` — `ExtractionPort`, `InstructorLLMExtractor`, `ExtractionService.extract_pair`
  (raw + validated раздельно), `validation` (даты/порог confidence), `PROMPT_VERSION`
- `asr/` — `ASRPort`, `ToneASRClient` (WS, 8 кГц int16, chunking)
- `diarization/` — `DiarizationPort`, `PyannoteDiarizer` (только mono/PSTN, HF_TOKEN)
- CLI `python -m app.ml.stt <id>`

### worker.py / workers/
- Celery, очереди `asr|ai|notifications`
- `process_asr` (worker-asr) → читает аудио из MinIO, транскрибирует, сохраняет,
  шлёт `partial_transcript`, затем передаёт в `run_llm_extraction` (worker-ai)
- `run_llm_extraction` (worker-ai) → agreements + `agreement_detected`; оба идемпотентны по `call_id`
- `send_reminder`, `request_data_deletion` — заглушки (`implemented: False`)

### cli.py
- `python -m app.cli seed` — демо-данные: менеджер Ирина +79000000001, Анна
  +79000000002, Борис +79000000003, задачи, звонки

---

## ML (research vs production)

| Часть | research | production |
|---|---|---|
| Синтез звонков | ✅ `research/` (TTS, wav) | — |
| Streaming ASR (T-one) | ✅ `ml/asr/tone.py` + тест протокола | ✅ `ToneASRClient` в `worker.py` (batch по файлу) |
| Диаризация (pyannote) | ✅ `ml/diarization/` | ✅ fallback для mono/PSTN (при `HF_TOKEN`) |
| STT-пайплайн | ✅ `ml/stt/` + тесты | ✅ роли из каналов VoIP / диаризация; `role_source` |
| VAD/чанкинг | ⬜ (отдельного VAD нет) | 🔶 чанкинг внутри T-one-клиента |
| LLM-извлечение | ⬜ | ✅ Instructor + валидация (при `LLM_BASE_URL`/`LLM_MODEL`) |
| События/WebSocket | — | ✅ `partial_transcript`, `agreement_detected` из воркеров |
| Транскрипты в БД | — | ✅ `transcripts` (JSONB-сегменты, 1:1 со звонком) |

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
| domain (1) | test_commitment | типы договорённостей |
| unit (4) | test_dates, test_rules, test_state_machine, test_exolve | относительные даты, пороги, переходы звонка, Exolve (события, тело маршрута, Call Record API, порт) |
| ml (4) | test_tone_client, test_pipeline, test_channels, test_extraction | протокол T-one, слияние ролей/ресамплинг, роли из каналов VoIP, извлечение+валидация (`extract_pair`) |
| integration (9) | test_auth, test_access, test_call_consent, test_agreements_tasks, test_schedule, test_sync, test_manager, test_ws_events, test_ml_pipeline | OTP/refresh, права ролей+команды, запись без consent, confirm→task, календарь/напоминания/черновик (только confirmed), sync-идемпотентность, WS auth/ownership/replay/live, сквозной ML-пайплайн + `POST /calls/{id}/analyze` |
| mobile (7) | domain/models, infrastructure/local_stores, infrastructure/sync_engine, application/auth_controller, application/board_controller, application/contacts_controller, widget/app | парсинг моделей, SQLite-хранилища, цикл sync + идемпотентность/конфликт/ретраи, контроллеры, экраны |

Backend: **135 passed** (domain 6 + unit 54 + ml 27 + integration 48);
интеграционные требуют `docker compose up -d postgres redis` (отдельная БД
`agreements_test`).
Mobile: **33 passed** (`flutter test`, без Docker); локальные хранилища тестируются
через `sqflite_common_ffi`.

---

## Как проверить текущее состояние

```bash
cd services/api
uv run ruff check .        # lint
uv run mypy .              # types
uv run pytest              # 135 тестов
docker compose up -d       # поднять стек
uv run python -m app.cli seed   # демо-данные (если БД пуста)
curl -k https://localhost/api/healthz   # живо (nginx TLS)

cd apps/mobile
flutter analyze            # lint мобильного (чисто)
flutter test               # 33 теста (Dart-уровень, без Docker)
```

Демо-флоу (проверен): OTP-логин (dev OTP 1234) → `/calls` POST + вебхук
`X-Voice-Webhook-Secret: dev-voice-secret` → answered → consent `audio_notice`
→ `recording_started_at` + `analysis_started` → `POST /calls/{id}/analyze`
(запись уже в MinIO) → транскрипт + `agreement_detected` → agreement confirm →
задача → `/manager/team/tasks`.

---

## Блокеры и открытые решения

| Блокер | Влияние |
|---|---|
| ~~Выбор voice-провайдера~~ **МТС Exolve** (решено 2026-10-13, `plan.md` §11.1) | снят; Этап 4 — за webhook-маршрутами и VoIP SDK |
| ~~Формат WS-событий~~ версия 1 + `GET /api/ws/events/schema` (трек C) | снят; мобильные/ML эмитят по контракту |
| **Аудио в ML — от мобильного клиента** (`MEDIA_INGEST_URL`): у Exolve нет серверного медиапотока (решено 2026-10-13, §11.1) | Этап 6: нужен ingest-эндпоинт (backend) + загрузка SDK-потока (трек A) |
| **Авто-триггер анализа по Exolve `crr`** (скачать запись → MinIO → очередь) не реализован | Этап 6/демо: сейчас триггер ручной — `POST /calls/{id}/analyze` |
| У Exolve нет сбора DTMF → `CONSENT_MODE=notice` (§11.1) | Этап 5: для Exolve только notice; `dtmf` — за другими провайдерами |
| Шифрование аудио/транскриптов и redaction логов LLM не сделаны (AGENTS, «Code and data security») | Этап 6: приватность |
| Выбор LLM (самохостинг предпочтителен) | Этап 6: извлечение реализовано, но включится только при `LLM_BASE_URL`/`LLM_MODEL` |

## История (для контекста)

- `3ddd35a…e6c15a0` — подготовка: план, AGENTS, research-эксперименты (agreement type — free string)
- `992d46e` — research: тип договорённости строкой вместо enum
- `c4fd7cd` — add: diarization pipeline (ASR+диаризация+STT)
- `361a76b` — **Этап 2** + интеграция ML в `src/app/ml/` (resolved merge)
- `12c400c` — **Этап 3**: мобильная основа (auth, контакты, доска, SQLite, sync) — PR #2
- `7268635`/`156b6b5` — LLM-extractor (research) — PR #3
- `071948d`/`eb0d40d` — Этап 4/5 (backend): Exolve-адаптер, consent-flow, WS-события — PR #4
- `64b3fda`/`79bffed` — **Этап 6 (backend)**: канальные роли VoIP, прод-пайплайн ML, воркеры, `POST /calls/{id}/analyze` — PR #5
