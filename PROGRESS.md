# Прогресс проекта (для анализа готовой части)

Обновлять при каждом мёрже. Легенда: ✅ готово и зелёные гейты · 🔶 частично
(есть backend/исследование, ждёт интеграции) · ⬜ не начато.

Сводка на 2026-10-14: **Этапы 1–3 закрыты, Этапы 4–5 (mobile, Dart) закрыты**,
**Этап 7 (mobile, Dart) — live-карточка по WS** реализована,
ML-исследование слито. **ML-пайплайн
переведён в прод** (PR #5): запись → роли из каналов VoIP → сегментированный
транскрипт → LLM-извлечение → валидация → `agreement_detected`; реальные воркеры
и триггер `POST /calls/{id}/analyze`. **Приём аудио от клиента** `POST /calls/{id}/audio`
слит (PR #8, трек C). **ML-трек B закрыт** (ветка `track/ml-live`, влита в
`development`): live-стриминг ASR (WS→Redis→T-one), инкрементальный extraction,
VAD (Silero), LLM self-host (Ollama `qwen2.5:7b`), детерминированные даты,
**Privacy** (удаление данных, retention-пурж, redaction); проверено end-to-end на
реальных моделях; тесты зелёные. **Трек C (Mav) закрыт**: приватность (шифрование
транскриптов/LLM-вывода Fernet + redaction логов), авто-скачивание записи Exolve
`crr`, докачиваемая загрузка аудио, правка подтверждённых договорённостей,
подготовка деплоя. **Вне ML и трека C (осталось)**: notifications-воркер
(`send_reminder`), подъём на VPS (нужен сервер/DNS), мобильный live-клиент (трек A).
Разработка ведётся в ветках `track/mobile-consent` (Xivalor), `track/ml-live`
(Sofiya), `track/backend-voice` (Mav); после зелёных гейтов и ревью — мерж в
`development`.

---

## По этапам (plan.md §17)

| Этап | Статус | Что готово | Что не готово |
|---|---|---|---|
| 1. Подготовка | ✅ | MVP-сценарий, роли, стек Flutter, репо, структура; **voice-провайдер выбран: МТС Exolve** (§11.1) | — |
| 2. Серверная основа | ✅ | Postgres/Redis/MinIO, модели, auth+роли, CRUD, docker compose, миграции; 69 тестов | — |
| 3. Мобильная основа | ✅ | `apps/mobile` (Flutter): слои UI/App/Domain/Infra, OTP-auth + refresh, контакты за портом, личная доска, SQLite (tasks/agreements/outbox/sync_state/session), Repository + sync (pull→apply→push→ack→token), `--dart-define=API_BASE_URL`; analyze ✓ | сборка/прогон на эмуляторе (нет Android SDK/Xcode в среде) — см. ограничение |
| 4. Звонки | 🔶 | backend: `VoiceProviderPort` (mock) + webhook-маршруты + state machine; **mobile (Dart)**: `VoiceCallProvider` за DI + `CallApi`, `CallController` (набор/ответ/отбой/mute), экран звонка (оверлей: таймер, mute, входящий), дозвон из контактов/доски, `MockVoiceCallProvider`, зеркало стейт-машины; analyze ✓, **53 теста** | нативный адаптер (CallKit/Telecom/Exolve SDK) и реальные входящие VoIP — нужна машина с Android SDK/Xcode; реальный провайдер (блокер) |
| 5. Consent flow | ✅ | backend-логика целиком: `consent.py`, `call_session.py`, state machine, тесты notice/DTMF/refusal/withdraw; **mobile (Dart)**: гейт согласия на первом входе, настройки записи/ИИ (toggle, отзыв, удаление данных, политика), локальный кэш решения (`app_settings`, схема v2) + write-through `PUT /me/consent`/`withdraw`/`/me/data/delete`, блокировка записи без согласия в `CallController` (нет согласия → обычный звонок), отказ собеседника → звонок без записи, `consent_notice/consent_result` в зеркале стейт-машины; analyze ✓, тесты | аудио-уведомление собеседнику (play_notice) проигрывает провайдер (бэкенд, Exolve `file_to_A`); UI-статусы согласия в звонке получат данные от WS (Этап 7) |
| 6. Запись и анализ | ✅ | **прод-пайплайн** (`ml/pipeline.py`): декодер + роли из каналов VoIP / диаризация для mono-PSTN (`ml/stt`), транскрипт в `transcripts` (JSONB-сегменты, `role_source`), LLM+Instructor + валидация (`ml/extraction`, детерминированные даты), реальные воркеры `process_asr`/`run_llm_extraction`, эмиссия `partial_transcript`/`agreement_detected`, **приём аудио от клиента** `POST /calls/{id}/audio` (raw `audio/*`, mixed или `?leg=`, MinIO + `call_audio`, авто-постановка ASR, только после записи/согласия, **докачиваемая загрузка** `Content-Range` + `offset` — обрыв сети не теряет записанное), триггер `POST /calls/{id}/analyze`, идемпотентность по `call_id`; **live-стриминг**: WS `/ws/calls/{id}/audio?leg=` → Redis → `worker-asr-live` (T-one стримингом, `partial_transcript` сразу) → `worker-ai-live` (инкрементальный extraction, upsert по fingerprint); **VAD** (Silero) в `ml/vad`; **LLM self-host** (Ollama `qwen2.5:7b` в compose), **авто-скачивание записи Exolve `crr`** (`download_recording` → MinIO → ASR; гейт согласия), **шифрование** `transcripts`/`agreement_extractions` (Fernet, `DATA_ENCRYPTION_KEY`) + redaction логов LLM, retention/удаление данных (`services/data_deletion.py`, Celery-beat) | — |
| 7. Договорённости и задачи | 🔶 | backend: agreement-статусы, confirm→task, PATCH-guards, audit; тесты; **mobile (Dart)**: live-карточка по WS (`/api/ws/calls/{id}`, события v1) — транскрипт, карточки договорённостей, confirm/reject/edit, ручной ввод без согласия, задача из `confirmed`; `AgreementApi`/`CallEventsPort` за DI, `WebSocketCallEvents`; analyze ✓, 106 тестов | напоминания, привязка к звонку в UI |
| 8. Доски | 🔶 | backend: `/me/tasks` (срезы `view=today|overdue|upcoming|done` + фильтры), `/manager/team/tasks\|stats\|members` с фильтрами (сотрудник, статус, приоритет, тип, срок) и сортировкой (просрочки → ближайшие дедлайны), типизированные схемы (`ManagerTaskOut`/`TeamStatsOut`), карточка (исполнитель, клиент, звонок‑источник), аналитика по сотрудникам и команде (`agreements_total`, вовремя/просрочено, среднее время закрытия, доля из звонков), роли+team, тесты доступа | мобильные доски (личная и менеджерская UI), аналитика UI |
| 9. Итог и календарь | 🔶 | backend: `schedule.py` — календарное событие/`.ics`/напоминания/черновик клиенту, только для confirmed-задач; **итог звонка** — `services/summary.py`, детерминированное резюме из договорённостей (без LLM, без выдуманных фактов), кэш в `calls.summary`, `GET /calls/{id}/summary` (владелец), обновляется в пайплайне и пересобирается на чтение, тесты | UI итога/календаря/напоминаний, реальные адаптеры (OAuth/FCM) |
| 10. Тестирование и демо | 🔶 | сквозное демо проверено: OTP → входящий → consent → задача → доска менеджера | тесты реальных звонков, 4G/обрыв WS, офлайн-синк, презентация |

---

## Backend — карта модулей (services/api/src/app)

### api/ — HTTP-слой (полный, из Этапа 2)
- `routes.py` — все эндпоинты: `/auth/*`, `/me*`, `/calls*` (+ `POST /calls/{id}/audio`
  — загрузка записи клиентом, 202; + `POST /calls/{id}/analyze`
  — постановка ASR/LLM в очередь, 202), `/agreements*`, `/tasks*`,
  `/manager/team/*`, `/sync` GET/POST, `/voice/exolve/control` и
  `/voice/exolve/events` (вебхуки провайдера, подпись `VOICE_WEBHOOK_SECRET`),
  `/healthz`
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
- `agreement.py` — статусы, confirm→task, правка/отклонение **подтверждённой**
  договорённости → задача (название/срок/ответственный) + сдвиг напоминаний
  (`version`+`audit`); `rejected` финальна
- `task.py` — статусы задач, complete; личная доска (§14): срезы `view` + фильтры
- `schedule.py` — календарь/`.ics`, напоминания, черновик сообщения; только для
  задач из `confirmed`-договорённости (порты за `Integrations`)
- `summary.py` — итог звонка (§9): детерминированное резюме из договорённостей,
  кэш в `calls.summary`; обновляется пайплайном и на чтение `GET /calls/{id}/summary`
- `sync.py` — delta pull (since-token), идемпотентный push (idempotency_key hash),
  конфликт → server version
- `manager.py` — доска команды: роли+team_id на сервере, фильтры (сотрудник/
  статус/приоритет/тип/срок), сортировка (просрочки → дедлайны), карточка
  (исполнитель/клиент/звонок), аналитика по команде и сотрудникам (§15)
- `data_deletion.py` — retention-пурж аудио и удаление данных пользователя:
  объекты (смесь/ноги/незавершённые чанки) → звонки-каскад → задачи
- `access.py` — права user/manager
- `events.py` — event hub в Redis (`events:call:{id}`): replay-список + pub/sub,
  версия схемы 1, дедуп на стыке; типы: `partial_transcript | agreement_detected | analysis_started | call_ended`
- `jobs.py` — `AnalysisQueuePort` + `CeleryAnalysisQueue` / `NullAnalysisQueue`;
  постановка ASR в очередь (триггер анализа)
- `audio_ingest.py` — приём записи от клиента: валидация типа/размера (413/422),
  MinIO (SSE + retention), заполнение `call_audio` (mixed или ноги), удаление
  вытесненных объектов, авто-постановка ASR; отказ без `recording_started_at`;
  **докачка при обрыве сети**: `Content-Range`-чанки пишутся сразу (durable
  `offset`), повтор чанка идемпотентен, рассинхрон → 409 `expected_offset`,
  чанки собираются в объект и удаляются
- `voice_webhooks.py` — вебхуки Exolve: call-control (маршрут по
  `EXOLVE_SIP_ROUTES` → `Call` с `external_id=call_sid`, `file_to_A`,
  `event_URL`, `client_id`; неизвестный `sip_id` → JSON-RPC `error`, повтор
  идемпотентен) и прогресс-события (`b/o/s/e` → общий `CallSessionService` по
  `client_id`/`call_sid`; `h`/`crr`/неизвестные — без перехода)

### infrastructure/
- `db/` — SQLAlchemy async: models, repositories, session; `migrations/` (Alembic,
  initial `ee8b295d7610`)
- `storage.py` — S3/MinIO (аудио, retention), `cache.py` — Redis
- `crypto.py` — Fernet-шифрование полей (`EncryptedText`/`EncryptedJSON`,
  `DATA_ENCRYPTION_KEY`, префикс `enc:v1:`); `redaction.py` — маскирование PII
  в логах (`redact`/`redact_preview`)
- `security.py` — JWT HS256

### integrations/ — внешние порты
- `voice.py` — `VoiceProviderPort`, `MockVoiceProvider`, `voice_provider_factory` (`mock`/`exolve`); webhook-signature `VOICE_WEBHOOK_SECRET`
- `exolve.py` — адаптер МТС Exolve: парсинг событий (`b/o/s/e/h/crr` → `CallEvent`), тело call-control (маршрут на SIP ID + `file_to_A`), Call Record API (`SetCallRecordState`/`GetInfo`/`Download`), парсинг маршрутов входящих (`EXOLVE_SIP_ROUTES`, `sip_id` → телефон + SIP-URI); `open_media_stream` → `MEDIA_INGEST_URL` (аудио льёт клиент), `collect_dtmf` → `None` (`CONSENT_MODE=notice`) — см. plan.md §11.1
- `outbound.py` — календарь/напоминания/черновик клиенту (не отправляется автоматически — правило!); фабрики портов

### ml/ — прод-пайплайн (Этап 6)
- `pipeline.py` — оркестратор: `load_call_audio` (ноги VoIP / смесь),
  `transcribe_and_store` (аудио → транскрипт в Postgres + `partial_transcript`),
  `extract_and_store` (транскрипт → agreements + `agreement_detected`),
  `extract_incremental` (upsert по fingerprint, события только на изменения);
  идемпотентно по `call_id`
- `live.py` — live-путь: Redis-стримы аудио → `ToneASRClient.stream` → сегменты в
  `transcripts` + `partial_transcript`; роли из каналов; финализация по `eof`
- `stt/` — `CallAudio`, декодер (soundfile/soxr → 8 кГц int16), роли из каналов
  VoIP / диаризация для mono/PSTN, `role_source` (`channel|diarization|unknown`); `Transcript`
- `extraction/` — `ExtractionPort`, `InstructorLLMExtractor`, `ExtractionService.extract_pair`
  (raw + validated раздельно), `validation` (детерминированные даты/порог confidence), `PROMPT_VERSION`
- `asr/` — `ASRPort` + `StreamingASRPort` (`transcribe` и `stream`), `ToneASRClient`
  (WS, 8 кГц int16, chunking; finalize 5 с)
- `diarization/` — `DiarizationPort`, `PyannoteDiarizer` (только mono/PSTN, HF_TOKEN)
- `vad/` — `VadPort`, `SileroVad`, `trim_to_speech` (обрезка краёв, timeline-safe)
- CLI `python -m app.ml.stt <id>`

### worker.py / workers/
- Celery, очереди `asr|ai|asr-live|ai-live|notifications`
- `process_asr` (worker-asr) → читает аудио из MinIO, транскрибирует, сохраняет,
  шлёт `partial_transcript`, затем передаёт в `run_llm_extraction` (worker-ai)
- `run_llm_extraction` (worker-ai) → agreements + `agreement_detected`; оба идемпотентны по `call_id`
- `stream_asr` (worker-asr-live) → live-стримы → транскрипт; `stream_extract`
  (worker-ai-live) → инкрементальный extraction (debounce)
- `download_recording` (worker-asr) → запись Exolve `crr` из Call Record API в
  MinIO → `process_asr`; гейт по `recording_started_at`, идемпотентно,
  клиентская загрузка не перетирается
- `request_data_deletion` → реальное удаление данных пользователя
  (`services/data_deletion.delete_user_data`): объекты аудио (смесь, ноги,
  незавершённые чанки докачки) + звонки/транскрипты/agreements/tasks;
  `purge_expired_audio` (Celery-beat, батчами) → retention-пурж аудио
- `send_reminder` — заглушка (`implemented: False`)

### cli.py
- `python -m app.cli seed` — демо-данные: менеджер Ирина +79000000001, Анна
  +79000000002, Борис +79000000003, задачи, звонки

---

## ML (research vs production)

| Часть | research | production |
|---|---|---|
| Синтез звонков | ✅ `research/` (TTS, wav) | — |
| Streaming ASR (T-one) | ✅ `ml/asr/tone.py` + тест протокола | ✅ `ToneASRClient` (`transcribe` + `stream`); batch и live |
| Диаризация (pyannote) | ✅ `ml/diarization/` | ✅ fallback для mono/PSTN (при `HF_TOKEN`) |
| STT-пайплайн | ✅ `ml/stt/` + тесты | ✅ роли из каналов VoIP / диаризация; `role_source` |
| VAD/чанкинг | ✅ `ml/vad` (Silero) | ✅ `VAD_ENABLED` (обрезка краёв) + чанкинг T-one |
| Live-стриминг | ✅ `ml/live.py` | ✅ WS-аудио → Redis → `worker-asr-live`/`worker-ai-live` |
| LLM-извлечение | ✅ | ✅ Instructor + валидация; self-host Ollama `qwen2.5:7b` |
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
- **Локальная БД** (sqflite, схема v2: v1 + `app_settings`): `tasks`, `agreements`,
  `session`, `outbox` (уникальный `idempotency_key`), `sync_state`, `app_settings`
  (кэш согласия).
- **Согласие (Этап 5)**: гейт на первом входе (`ConsentScreen`), настройки записи/ИИ
  (`SettingsScreen`: toggle, отзыв согласия с подтверждением, удаление данных,
  политика); решение кэшируется локально и пишется на сервер (`PUT /me/consent`,
  `POST /me/consent/withdraw`, `POST /me/data/delete`); без сети — pending-состояние
  с ретраем; запись невозможна без согласия (гарантируется логикой `CallController`).
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
| unit (8) | test_dates, test_rules, test_state_machine, test_exolve, test_audio_ingest, test_crypto, test_redaction, test_summary | относительные даты, пороги, переходы звонка, Exolve (события, тело маршрута, Call Record API, порт, разбор `EXOLVE_SIP_ROUTES`), `Content-Range`-парсер, шифрование полей, redaction PII, детерминированный итог звонка |
| ml (6) | test_tone_client, test_pipeline, test_channels, test_extraction, test_trim, test_live | протокол T-one (`transcribe`+`stream`), слияние ролей/ресамплинг, роли из каналов VoIP, извлечение+валидация (детерминированные даты), VAD-обрезка, чтение Redis-стримов |
| integration (18) | test_auth, test_access, test_call_consent, test_agreements_tasks, test_agreement_edits, test_audio_ingest, test_audio_resume, test_schedule, test_sync, test_manager, test_boards, test_call_summary, test_ws_events, test_ml_pipeline, test_exolve_webhooks, test_provider_recording, test_transcript_encryption, test_privacy | OTP/refresh, права ролей+команды, запись без consent, confirm→task, правка/отклонение **подтверждённой** договорённости → задача/напоминания (`version`+`audit`), приём аудио (mixed/`?leg=`/докачка `Content-Range`, 409), календарь/напоминания/черновик (только confirmed), sync-идемпотентность, доски: срезы личной доски (§14) и фильтры/сортировка/аналитика по сотрудникам доски менеджера (§15), итог звонка (§9: резюме из договорённостей, счётчики, владелец), WS auth/ownership/replay/live, сквозной ML-пайплайн (batch + live) + `POST /calls/{id}/analyze`, вебхуки Exolve (control/events), авто-скачивание записи (`crr` → MinIO, гейт согласия, идемпотентность), шифрование транскрипта/LLM-вывода в БД, retention/удаление данных |
| mobile (16) | domain/models, domain/call, domain/consent, domain/ws_event, infrastructure/local_stores, infrastructure/sync_engine, infrastructure/ws_call_events, application/auth_controller, application/board_controller, application/contacts_controller, application/call_controller, application/consent_controller, widget/app, widget/call_screen, widget/live_card, widget/consent_screen, widget/settings_screen | парсинг моделей, стейт-машина звонка, согласие (AppConsent/статусы, кэш + write-through + retry), WS-контракт v1 (конверт/сегменты/событие), SQLite-хранилища (включая миграцию v1→v2), цикл sync + идемпотентность/конфликт/ретраи, контроллеры (live-события, правка/подтверждение договорённостей, реконнект-fallback), экраны (доска, контакты, звонок + live-карточка, согласие, настройки) |

Backend: **244 passed** (unit+ml+domain 133, integration 111); интеграционные требуют
`docker compose up -d postgres redis` (отдельная БД `agreements_test`; креды берутся
из `DATABASE_URL`). ML проверен end-to-end на реальных моделях (T-one, Ollama
`qwen2.5:7b`, Silero VAD, pyannote).
Mobile: **106 passed** (`flutter test`, без Docker); локальные хранилища тестируются
через `sqflite_common_ffi`.

---

## Как проверить текущее состояние

```bash
cd services/api
uv run ruff check .        # lint
uv run mypy .              # types
uv run pytest tests/unit tests/ml tests/domain   # 129 (без Docker)
uv run pytest tests/integration                  # 104 (postgres+redis)
docker compose up -d       # поднять стек
uv run python -m app.cli seed   # демо-данные (если БД пуста)
curl -k https://localhost/api/healthz   # живо (nginx TLS)

cd apps/mobile
flutter analyze            # lint мобильного (чисто)
flutter test               # 106 тестов (Dart-уровень, без Docker)
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
| **Аудио в ML — от мобильного клиента** (`MEDIA_INGEST_URL`): у Exolve нет серверного медиапотока (решено 2026-10-13, §11.1) | Этап 6: ingest-эндпоинт **готов** (PR #8) и **live WS `/ws/calls/{id}/audio`** готов (track/ml-live); осталась отправка аудио клиентом (трек A) |
| ~~Авто-триггер анализа по Exolve `crr`~~ **реализован** (трек C): `crr` → `call_audio.provider://exolve/<uid>` → job `download_recording` → MinIO → ASR (гейт согласия, идемпотентно, клиентская загрузка не перетирается) | снят; в бою нужен `EXOLVE_API_KEY` |
| У Exolve нет сбора DTMF → `CONSENT_MODE=notice` (§11.1) | Этап 5: для Exolve только notice; `dtmf` — за другими провайдерами |
| Вебхуки Exolve подписаны общим секретом в URL (`?secret=`) — заголовки Exolve не ставит | Деплой: URL колбэка — секрет; `PUBLIC_BASE_URL` обязателен в бою |
| ~~Шифрование персональных данных~~ **сделано** (трек C): аудио — SSE-AES256 в MinIO, `transcripts`/`agreement_extractions` — Fernet (`DATA_ENCRYPTION_KEY`), LLM-логи — с редакцией (`redact`/`redact_preview`); retention/удаление — `services/data_deletion.py` (`beat`, батчами; чистит и незавершённые чанки докачки) | снят; `DATA_ENCRYPTION_KEY` не менять без перешифровки |
| **Деплой на VPS** (нужен сервер + DNS) | Подготовка готова: `docker-compose.prod.yml` + `docs/deploy.md` (Let's Encrypt, секреты, колбэки Exolve); подъём — за командой со стендом |
| ~~Выбор LLM (самохостинг)~~ **Ollama `qwen2.5:7b` в compose** (решено) | снят; извлечение включено |

## История (для контекста)

- `3ddd35a…e6c15a0` — подготовка: план, AGENTS, research-эксперименты (agreement type — free string)
- `992d46e` — research: тип договорённости строкой вместо enum
- `c4fd7cd` — add: diarization pipeline (ASR+диаризация+STT)
- `361a76b` — **Этап 2** + интеграция ML в `src/app/ml/` (resolved merge)
- `12c400c` — **Этап 3**: мобильная основа (auth, контакты, доска, SQLite, sync) — PR #2
- `7268635`/`156b6b5` — LLM-extractor (research) — PR #3
- `071948d`/`eb0d40d` — Этап 4/5 (backend): Exolve-адаптер, consent-flow, WS-события — PR #4
- `64b3fda`/`79bffed` — **Этап 6 (backend)**: канальные роли VoIP, прод-пайплайн ML, воркеры, `POST /calls/{id}/analyze` — PR #5
- `3b3119c`/`d1948d5` — docs/team: статус ML-пайплайна, сплит Xivalor/Mav, `scripts/local-db.sh` — PR #6
- `b7f2ccb` — **Этап 4 (mobile, Dart)**: порт `VoiceCallProvider` за DI + `CallApi`, `CallController`, зеркало стейт-машины, экран звонка (оверлей) + дозвон, mock-провайдер; analyze ✓, 53 теста — PR #7 (нативный SDK-адаптер — на машине с Android SDK/Xcode)
- `c216b0f` — **Трек C**: приём аудио от клиента `POST /calls/{id}/audio` (MinIO + `call_audio`, 409 без записи/согласия, mixed/`?leg=`) — PR #8
- `#9` — **Этап 5 (mobile, Dart)**: consent-гейт + настройки записи/ИИ (`app_settings` v2), кэш решения + write-through, блокировка записи без согласия, отказ собеседника → обычный звонок; analyze ✓, 82 теста
- `309bf34`/`c217b00`/`37fcc3a`/`252807b` — **ML-трек B (`track/ml-live`)**: LLM self-host (Ollama) + детерминированные даты, Silero VAD, live-стриминг ASR (WS→Redis→T-one) + инкрементальный extraction, документация; влито в `development`
- `12f596c` — **ML-фиксы**: live-debounce, finalize T-one 30→5 с, интеграционный conftest по `DATABASE_URL`; end-to-end проверка на реальных моделях
- `693beaa`/`36a2e31` — **ML-трек B (Sofiya)**: docs (live/VAD/LLM закрыты) + реализация приватности: удаление данных и retention-пурж (`services/data_deletion.py`), redaction логов, `beat` — влито в `development`
- `#10` — **Трек C (Mav)**: вебхуки Exolve call-control + прогресс-события end-to-end (маршрут по `EXOLVE_SIP_ROUTES`, `file_to_A`, `client_id`; `b/o/s/e` → общий `CallSessionService`)
- **Трек C (Mav)**: докачиваемая загрузка аудио (`Content-Range`/`offset`, идемпотентный повтор, 409 при рассинхроне, миграция `call_audio.pending_uploads`); правка/отклонение **подтверждённой** договорённости → задача + сдвиг напоминаний (`version`+`audit`)
- **Трек C (Mav)**: авто-скачивание записи Exolve `crr` (`download_recording` → MinIO → ASR); шифрование `transcripts`/`agreement_extractions` (Fernet, миграция `a1c9f4e27b30`) + redaction логов LLM; retention-пурж чистит и незавершённые чанки; деплой-оверлей `docker-compose.prod.yml` + `docs/deploy.md`
- `#11` — **Этап 7 (mobile, Dart)**: live-карточка по WS (`WebSocketCallEvents`, `AgreementApi`, контракт v1), транскрипт + карточки договорённостей, confirm/reject/edit, ручной ввод без согласия, задача из `confirmed`; analyze ✓, 106 тестов
