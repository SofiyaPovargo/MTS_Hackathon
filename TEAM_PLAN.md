# План командной работы (распараллеливание)

Статус на 2026-10-13: Этапы 1–2 из `plan.md` **готовы и зелёные**, **Этап 3 и
Этап 4 (mobile) реализованы** — основа в `track/mobile`, звонки (Dart-уровень)
в `track/mobile-calls`: `flutter analyze` ✓, `flutter test` **53 passed**.
**Этап 6, backend-часть ML-пайплайна, слит в
`development`** (PR #5): роли из каналов VoIP, воркеры `process_asr`/
`run_llm_extraction`, триггер `POST /calls/{id}/analyze`; гейты ruff ✓, mypy ✓,
pytest 135 passed. **Трек C (Mav) закрыт**: приём и докачка аудио от клиента,
вебхуки Exolve + авто-скачивание записи `crr`, правка подтверждённых
договорённостей, шифрование данных и подготовка деплоя (**233 passed**).
Команда: **Sofiya** (ML), **Mav** (backend), **Xivalor** (mobile). Актуальное
состояние по каждому этапу — в `PROGRESS.md`.

**Обновление 2026-10-13:** команда работает **локально** — у каждого свой стек и
своя БД (общая/удалённая БД не используем). **Sofia делает свою часть (трек B)
сама**; работа распараллелена между **Xivalor** (мобильное) и **Mav**
(backend/интеграции) — см. «Перераспределение» ниже. Локальная БД поднимается
скриптом `./scripts/local-db.sh`.

Главный принцип (AGENTS.md, «Working order»): этапы идут по порядку, но это
касается **зависимостей**, а не людских ресурсов. Ниже — три независимых трека,
каждый со своей последовательностью задач, которые можно делать сейчас.
Трек A (мобильный) — критический путь демо; треки B и C его не блокируют.

---

## Перераспределение на 2026-10-13

**Как работаем:** каждый — **локально**: свой `docker compose up -d` и своя БД
(`./scripts/local-db.sh`). Общая/удалённая БД не используется.

**Роли сейчас:**
- **Xivalor** — мобильное приложение (трек A, Этапы 4→9) — критический путь демо.
- **Mav** — backend и интеграции (трек C): приём аудио, Exolve, consent, приватность.
- **Sofia** — трек B (ML) **делает сама**; её пункты не перераспределяем.

### Xivalor — мобильное приложение (Этапы 4→9)
- [x] **Этап 4** (Dart-уровень): порт `VoiceCallProvider` за DI + `CallApi`, зеркало стейт-машины, `CallController`, экран звонка (оверлей) + дозвон; mock-провайдер; нативный адаптер — на машине с Android SDK/Xcode
- [x] **Этап 5**: экран согласия (гейт первого входа) + настройки записи/ИИ (toggle, отзыв, удаление данных, политика); кэш решения `app_settings` (схема v2) + write-through `PUT /me/consent`/`withdraw`/`/me/data/delete`; запись без согласия заблокирована; отказ собеседника → обычный звонок; UI-статусы `consent_notice/consent_result` (события от WS — Этап 7)
- [ ] **Этап 7**: live-карточка по WS (`partial_transcript`, `agreement_detected`, `analysis_started`, `call_ended`); edit/confirm; задача из `confirmed`
- [ ] **Этап 8**: личная и менеджерская доски (фильтры, сортировка, аналитика)
- [ ] **Этап 9**: резюме разговора, черновик клиенту, календарь/`.ics`

### Mav — backend и интеграции (Трек C)
- [x] **Приём аудио от клиента** (критический путь): `POST /calls/{id}/audio` → MinIO → `call_audio` → очередь `process_asr` (202; отказ 409 без записи/согласия, mixed или per-leg `?leg=`)
- [x] **Докачка записи при обрыве сети** (критический путь): докачиваемая загрузка по `Content-Range` (чанки сразу в MinIO, durable `offset`), идемпотентный повтор чанка, рассинхрон → 409 `expected_offset`; сборка чанков в объект `call_audio` и удаление чанков; тесты обрыва (Wi-Fi/4G/слабый сигнал); клиентская буферизация+ретрай — трек A
- [x] **Exolve `crr`** → скачать запись (Call Record API по `uid`, не по URL из вебхука — SSRF) → MinIO → авто-постановка ASR (`download_recording` на очереди `asr`; гейт по `recording_started_at`, идемпотентно, без ключа — пропуск)
- [x] **Exolve webhooks** (call-control + statistics `b/o/s/h/e/crr`) end-to-end: `POST /api/voice/exolve/control` (маршрут по `EXOLVE_SIP_ROUTES`, `Call`, `file_to_A`, `event_URL`) + `POST /api/voice/exolve/events` (`b/o/s/e` → `CallSessionService`; `crr` → скачивание записи)
- [x] **Consent-уведомление** в бою (`file_to_A`, режим `notice`) + запись в `consents`: notice в ответе call-control, ветка согласия — по событию `s`
- [x] **Правка подтверждённых договорённостей** (`plan.md` §12–14): `PATCH /agreements/{id}` работает в любом статусе (в т.ч. `confirmed`) и переносится на связанную задачу (название, срок, ответственный) + сдвиг напоминаний; `POST /reject` подтверждённой отменяет задачу; каждое изменение → `version` + `audit_log`; повторное извлечение не создаёт дублей
- [x] **Приватность**: шифрование полей `transcripts`/`agreement_extractions` (Fernet, `DATA_ENCRYPTION_KEY`; аудио — SSE-AES256), redaction логов LLM (`redact`/`redact_preview`); retention/удаление — `services/data_deletion.py` (`beat`, чистит и незавершённые чанки докачки)
- [ ] (опц.) реальные адаптеры календаря/напоминаний (OAuth/FCM); (опц.) подъём на VPS — подготовка готова (`docker-compose.prod.yml`, `docs/deploy.md`)

### Sofia — трек B (ML, делает сама) — ✅ закрыт
- [x] Решение по LLM (самохостинг: Ollama `qwen2.5:7b`) и включение извлечения в prod (`LLM_BASE_URL`/`LLM_MODEL`)
- [x] live-стриминговый ASR (WS-аудио → Redis → T-one), отдельный VAD (Silero), тюнинг извлечения (детерминированные даты)
- [x] Privacy: удаление данных, retention-пурж (beat), redaction PII
- [x] Проверено end-to-end на реальных моделях; `ruff`/`mypy`/pytest зелёные
- **Вне ML (осталось, но не трек B)**: notifications-воркер (`send_reminder`), авто-триггер Exolve `crr`, шифрование транскриптов в БД (бэклог), мобильный live-клиент (трек A)

### Локальная БД (у каждого своя)
```bash
./scripts/local-db.sh          # postgres + БД + миграции (+ agreements_test)
./scripts/local-db.sh --seed   # ещё демо-данные: Ирина/Анна/Борис
```

---

## Три трека

| Трек | Человек | Этапы | Суть | Зависит от |
|---|---|---|---|---|
| **A. Мобильное приложение** | Xivalor | 3 → 4 → 5 → 7 → 8 → 9 (UI) | Flutter: основа, звонки, consent, live-карточка, доски | Flutter SDK, бэкенд-эндпоинты (есть), WS-эндпоинт (трек C) |
| **B. ML и анализ** | Sofiya (сама) | 6 (backend) | прод-пайплайн влит (PR #5); осталось: LLM-решение, live/VAD, приватность | research-слой (есть), LLM-решение |
| **C. Voice и интеграции** | Mav | 4–5, 9 (backend) + деплой | Voice-провайдер, адаптеры, consent-уведомление, WS-эндпоинт, календарь/.ics, деплой | решение по voice-провайдеру |

Трек A работает по **Этапам по порядку** (нельзя начинать экран звонка до основы
приложения). Треки B и C — отдельные backend-треки, они не требуют мобильного
кода и стартуют сразу; проверяются на синтетических данных и моках, боевая
интеграция — после Этапов 4–5.

---

## Трек A. Мобильное приложение — Xivalor

Критический путь демо: «входящий звонок → задача на доске менеджера < 3 минут».

**Этап 3. Мобильная основа** — ✅ **сделано** (ветка `track/mobile`;
Flutter SDK 3.47.7 / Dart 3.13.5, в репозиторий не коммитится):

- [x] `apps/mobile`: `flutter create --platforms=android,ios --org ru.mts`
- [x] Слои: UI / Application (Riverpod) / Domain / Infrastructure
- [x] Авторизация: OTP → `/auth/otp/request` + `/auth/login`, refresh-ротация
- [x] Контакты: порт над `flutter_contacts`; при запрете перимишена — ручной ввод
- [x] Личная доска задач (нетворк + локальный кэш)
- [x] SQLite (sqflite): только свои данные (tasks, agreements, outbox, sync_state);
      session хранится там же
- [x] Repository + sync: pull → apply → push → ack → `sync_token`, идемпотентность
- [x] API base URL через `--dart-define=API_BASE_URL`, не хардкодом
- [x] Гейты: `flutter analyze` ✓ + `flutter test` ✓ (33 теста на момент этапа;
      суммарно с Этапом 4 — 53)
- ⚠️ **Ограничение среды**: на dev-машине нет Android SDK/Java/Xcode, поэтому
  сборка/запуск на эмуляторе здесь не проверялись — только Dart-уровень
  (analyze + test). См. `apps/mobile/README.md`.
- **Осталось для полного «готово»**: прогон на эмуляторе против живого бэкенда
  на машине с Android SDK/Xcode.


**Этап 4. Звонки** — 🔶 **Dart-уровень сделан** (ветка `track/mobile-calls`):
- [x] Порты: `VoiceCallProvider` (за DI) + `CallApi`; клиентское зеркало
      стейт-машины звонка (`domain/call.dart`, совпадает с backend)
- [x] `CallController`: исходящий набор (`POST /calls` + `dial`), входящий
      (answer/decline), mute, hangup; события incoming/ringing/answered/
      ended/dropped/missed
- [x] Экран звонка — оверлей поверх приложения (таймер, mute, hangup,
      входящий: ответить/отклонить); дозвон из контактов и с доски (FAB)
- [x] `MockVoiceCallProvider` для запуска без SDK (авто-ответ, dev-входящий)
- [x] Гейты: `flutter analyze` ✓, `flutter test` ✓ (53 теста)
- [ ] **Осталось** (нужна машина с Android SDK/Xcode): нативный адаптер
      (CallKit / Telecom / MTS Exolve SDK) и реальные входящие VoIP

**Этап 5. Consent flow (UI)** (после 3–4):
- [ ] Экран согласия пользователя + настройки записи/ИИ
- [ ] Экран «собеседник отказался в DTMF 2»
- [ ] Слушает решения трека C по формату аудио-уведомления

**Этап 7. Договорённости и задачи (UI)** (после 3): live-карточка, edit/confirm,
создание задачи из confirmed. Съедает WS-события: `partial_transcript`,
`agreement_detected`, `analysis_started`, `call_ended` (эндпоинт — трек C,
эмиссия — трек B).

**Этап 8. Доски (UI)**: личная + менеджерская (фильтры, аналитика), доступ
по ролям с сервера.

**Этап 9. Итог и календарь (UI)**: резюме, черновик клиенту, `.ics`.

---

## Трек B. ML и анализ — Sofiya

Продолжение research-линии: перевод `src/app/ml` из исследования в
продакшн-пайплайн — **backend-часть сделана** (PR #5). Работает на синтетических
wav (research уже умеет их синтезировать) — мобильный код не нужен.

- [x] **Роли из каналов (VoIP)**: каналы-ноги → роли без диаризации; pyannote —
  fallback для mono/PSTN; `role_source` фиксирует путь
- [x] **worker-asr**: celery-задача читает аудио из MinIO/S3, гонит ASR; идемпотентно по `call_id`
- [x] **worker-ai**: транскрипт → LLM-извлечение (Instructor) + валидация;
  без LLM-ключа извлечение выключено
- [x] **Транскрипт**: сохраняется в `transcripts` (JSONB-сегменты), не дублируется в `calls`
- [x] **События**: эмиссия `partial_transcript`, `agreement_detected` через
  `services/events.py` (Redis) — контракт v1
- [x] **Валидация дат** из LLM: `domain/dates.py` + `conversation_date` (по времени разговора + TZ юзера)
- [x] **Триггер**: `POST /calls/{id}/analyze` (owner-only, 202, только для записанного звонка)
- [x] Тесты: роли каналов, `extract_pair`, сквозной пайплайн (идемпотентность)
- [x] **Конфиденциальность**: удаление данных по запросу (`delete_user_data`), retention-пурж аудио (Celery-beat, батчами; чистит и незавершённые чанки докачки), redaction PII в логах, аудио SSE-AES256, **шифрование `transcripts`/`agreement_extractions` (Fernet, `DATA_ENCRYPTION_KEY`)**
- [x] **Приём аудио**: `POST /calls/{id}/audio` (raw `audio/*`, `?leg=`, размер, приватность) → MinIO → `call_audio` → авто-постановка `process_asr`; отказ без записи/согласия
- [x] Авто-триггер по Exolve `crr` (скачать запись Call Record API в MinIO) — трек C
- [x] **Live-стриминг**: WS-аудио (`/ws/calls/{id}/audio?leg=`) → Redis → `worker-asr-live` (T-one стримингом, `partial_transcript` сразу) → `worker-ai-live` (инкрементальный extraction, upsert по fingerprint); VAD (Silero); LLM self-host (Ollama)
- **Готово, когда**: `docker compose up -d` + аудио звонка → в БД транскрипт, в Redis
  события для WebSocket, на доске — договорённость.
- **Замечание**: отдельного шага VAD раньше не было — теперь Silero VAD (обрезка
  краёв) опционален (`VAD_ENABLED`); чанкинг по 300 мс делает T-one.

**Открытое решение (до старта LLM-части)**: какой LLM — самохостинг предпочтителен
(приватность, было обсуждение); согласовать с Xivalor/Mav, зафиксировать в plan.md.

---

## Трек C. Voice и интеграции — Mav

Бэкенд-интеграции и инфраструктура. Четыре независимых пакета, делать в любом
порядке.

1. **Voice-провайдер** (блокирует Этап 4 целиком — и backend, и мобильный):
   - [x] Сравнить кандидатов (Exolve, Mango Office, Voximplant, Zadarma/Novofon)
   - [x] Выбор зафиксирован в `plan.md` §11.1: **МТС Exolve**
   - [x] Реальный адаптер `VoiceProviderPort` (Exolve) + мок для тестов/демо:
     `integrations/exolve.py` — события (`b/o/s/e/h/crr`→`CallEvent`), тело
     call-control (маршрут на SIP ID + `file_to_A`), Call Record API
     (`SetCallRecordState`/`GetInfo`/`Download`); мок остаётся для тестов/демо
   - [x] Webhook-маршруты Exolve (call-control + события) и end-to-end связка:
     `POST /api/voice/exolve/control` (маршрут по `EXOLVE_SIP_ROUTES`, создание
     `Call`, `file_to_A`, `event_URL`) и `POST /api/voice/exolve/events`
     (`b/o/s/e` → тот же `CallSessionService`; корреляция по `client_id`/
     `call_sid`); общий секрет `?secret=`, `PUBLIC_BASE_URL`
2. **Consent-уведомление** (нужно Этапу 5): `play_notice` через провайдера,
   DTMF 1/2, запись события в `consents`
   - [x] Адаптер Exolve: notice через `file_to_A` в ответе call-control
   - [x] Подключить к consent-flow; у Exolve нет сбора DTMF → режим `notice`
     (`plan.md` §11.1), `dtmf` — за другими провайдерами. Уведомление
     проигрывается в ответе call-control (`file_to_A`), а ветка согласия
     запускается событием `s` через общий `CallSessionService` (`notice` →
     granted/`audio_notice`)
3. **WebSocket-эндпоинт** (нужен и мобильному, и ML):
   - [x] `/api/ws/calls/{id}` с JWT-аутентификацией (header или `?token=`),
     владелец звонка; версия в схеме событий (`version: 1`) + `GET /api/ws/events/schema`
   - [x] `partial_transcript | agreement_detected | analysis_started | call_ended` —
     replay из Redis + live pub/sub, дедуп на стыке
   - [ ] Регенерация API-клиента после изменения контракта (клиента ещё нет, Этап 3)
4. **Календарь/напоминания** (Этап 9, backend): `CalendarPort.create_event()` +
   `.ics` (dependency `icalendar` уже есть), `RemindersPort.create_reminder()`,
   только после подтверждения пользователя (правило продукта!)
   - [x] `services/schedule.py`: календарь (`POST /tasks/{id}/calendar`),
     `.ics` (`GET /tasks/{id}/calendar.ics`), напоминания
     (`POST/GET /tasks/{id}/reminders`, `POST /reminders/{id}/cancel`),
     черновик сообщения (`POST /tasks/{id}/message-draft`, `sent: false`)
   - [x] Только для задач из `confirmed`-договорённости; `remind_at` — в будущем
   - [ ] Реальные адаптеры календаря/напоминаний (за теми же портами)
5. **Деплой** (не блокирует демо): VPS + тот же compose + Let's Encrypt;
   секреты из `.env`, не из коммитов.
   - [x] Подготовка: `docker-compose.prod.yml` (реальные сертификаты, restart,
     dev-порты закрыты) + гайд `docs/deploy.md` (certbot, секреты, проверка)
   - [ ] Поднять на VPS (нужен сервер и DNS — за командой)

- **Готово, когда**: все интеграции за моками в тестах; реальный провайдер
  добавлен адаптером без изменения ML-пайплайна и мобильного UI.

---

## Старт работы — по шагам (для каждого)

Общие ветки созданы и запушены в origin (от `development`, коммит `39ac850`):
`track/mobile` (Xivalor), `track/ml` (Sofiya), `track/backend-voice` (Mav).

### Клонировать и взять свою ветку

```bash
git clone git@github.com:SofiyaPovargo/MTS_Hackathon.git
cd MTS_Hackathon
git checkout track/<твоя>        # см. свою ветку ниже
git pull origin track/<твоя>
```

### Xivalor — track/mobile (мобильное приложение)

1. Flutter: нужен SDK 3.47.7 / Dart 3.13.5. На dev-машине уже стоит
   (`/home/dd/flutter`); на своей: `flutter_linux_3.47.7-stable.tar.xz` от
   storage.googleapis.com (stable channel, 3.47.7).
2. Первый шаг: `cd apps # (создать, если нет)` → `flutter create --platforms=android,ios --org ru.mts mobile`
   → реализовать Этап 3 (чек-лист выше). Бэкенд для проверки: `docker compose up -d`
   (в корне репо), API уже живой.
3. Гейты: `cd apps/mobile && flutter analyze && flutter test`.
4. PR: ветка `track/mobile` → `development`, ревьюер **Mav** (контракты API/WS).

### Sofiya — track/ml (ML и анализ)

1. `cd services/api && uv sync` (появится всё из `uv.lock`; numpy/soundfile/soxr —
   dev-группа уже входит).
2. Первый шаг: VAD/чанкинг + задача `worker-asr` на существующем research-слое
   `src/app/ml`; тестовые wav — `research/` (генератор уже есть).
3. Гейты: `uv run ruff check . && uv run mypy . && uv run pytest`
   (интеграционные требуют `docker compose up -d postgres redis`).
4. PR: `track/ml` → `development`, ревьюер **Mav** (места пересечения:
   events/worker), **Xivalor** — если трогаешь формат WS-событий.

### Mav — track/backend-voice (backend, voice и интеграции)

1. Первым делом (блокер!): выбор voice-провайдера — сравнение 2–3 кандидатов,
   решение зафиксировать в `plan.md` (пункт Этапа 1).
2. Потом: реальный адаптер `VoiceProviderPort` (за моком), WebSocket-эндпоинт
   `/ws` (JWT, схема событий в OpenAPI), consent-уведомление, календарь/.ics.
3. Гейты: те же, что у Sofiya.
4. PR: `track/backend-voice` → `development`, ревьюер **Sofiya** (ML-сторона
   событий) / **Xivalor** (клиент после регенерации из OpenAPI).

### Как поддерживать ветку в актуальном состоянии

```bash
git fetch origin
git merge origin/development     # часто, пока «свежо» — меньше конфликтов
# прогнать гейты, закоммитить, запушить
git push origin track/<твоя>
```

### Флоу на каждый PR

1. Коммиты в свою track-ветку (по задачам — можно подветками, но проще прямо в трек).
2. `git merge origin/development` → гейты зелёные.
3. PR → `development` с описанием: что сделано / как проверить / что трогает у других.
4. Минимум 1 ревью от назначенного человека (см. выше), конфликты разруливает автор.
5. Мерж → отметить галочки в `PROGRESS.md` (это тоже PR или расскоммитить сразу в development).

### Где пересекаются track/ml и track/backend-voice

`services/events.py`, `worker.py`, `app/api/routes.py`, `docker-compose.yml`,
`pyproject.toml`. Правило: **сначала договориться о схеме WS-событий** (записать в
plan.md), потом писать код. Общие файлы менять только после `git merge origin/development`,
иначе будет больно.

---

## Открытые решения (блокеры)

| Решение | Кто | Срок | Блокирует |
|---|---|---|---|
| ~~Выбор voice-провайдера~~ **МТС Exolve** | Mav | ✅ решено | снят |
| **Аудио в ML — от мобильного клиента** (`MEDIA_INGEST_URL`; у Exolve нет серверного медиапотока) | согласовано Mav/A/B | ✅ решено 2026-10-13 | Этап 6: ingest-эндпоинт (C) + загрузка SDK-потока (A) |
| Consent для Exolve — только `notice` (нет сбора DTMF) | Mav | ✅ решено 2026-10-13 (`plan.md` §11.1) | Этап 5 у Exolve — notice |
| Выбор LLM (самохостинг?) | Sofiya + согласование | до включения извлечения в prod (`LLM_BASE_URL`/`LLM_MODEL`) | B |
| Деплой-таргет (VPS) | Mav | ближе к демо | — (не блокер) |
| ~~Формат WS-событий (схема)~~ версия 1 + `GET /api/ws/events/schema` | C (Mav) | ✅ решено | снят |

---

## Правила работы

- **Ветки**: каждая задача — своя ветка от `development`, после зелёных гейтов и
  PR-ревью (минимум 1) мёржим в `development`. В `master` — только готовые демо-точки.
- **Гейты перед PR**: backend — `cd services/api && uv run ruff check . && uv run mypy . && uv run pytest`; mobile — `cd apps/mobile && flutter analyze && flutter test`.
- **Этапы не перепрыгивать**: у каждого трека свой порядок; перед началом этапа —
  «предыдущий готов и тесты зелёные».
- **Никаких внешних записей без подтверждения пользователя** — напоминания,
  календарь, клиентские сообщения только после confirm (правило продукта).
- **Глобально в одной кодовой базе**: никаких Android/iOS-only API в фичах;
  платформенное — за интерфейсами и DI.
- **Контракты**: любые изменения API/WS → обновить OpenAPI и регенерировать
  клиент (мобильный), чтобы A не разъезжался с B/C.
- **Документация**: изменения схемы/флоу — в README + plan.md.

## Ориентир по времени (если по 1 человеку на трек)

- Неделя 1: Этап 3 (Xivalor) ║ VAD+worker-asr (Sofiya) ║ провайдер + WS (Mav)
- Неделя 2: Этап 4 (Xivalor, ждёт провайдера) ║ worker-ai+LLM (Sofiya) ║
  consent-уведомление + календарь (Mav)
- Неделя 3: Этапы 5, 7 (Xivalor) ║ сквозной прогон ML (Sofiya) ║ деплой (Mav)
- Неделя 4: Этапы 8–9 + Этап 10 (демо) — все вместе

## Критерий готовности MVP (из plan.md §19)

Демо «входящий звонок → задача менеджера» < 3 минут; запись только после
`answered` + согласия; всё внешнее — только после подтверждения пользователя.
