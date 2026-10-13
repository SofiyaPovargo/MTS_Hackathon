# План реализации: ИИ‑агент для фиксации договоренностей в телефонных разговорах

## 1. Идея продукта

Мобильное кроссплатформенное приложение для пользователей и их менеджера.

Пользователь принимает или совершает звонки через приложение. После того как собеседник отвечает и согласие на запись получено, начинается запись и анализ разговора. ИИ распознает речь, выделяет договоренности, сроки, обязательства и следующие шаги. Пользователь подтверждает результат, после чего создаются задачи, напоминания и события календаря.

Менеджер видит задачи всех пользователей своей команды на общей доске, контролирует сроки и аналитику выполнения.

### Ключевой сценарий

1. Пользователь получает входящий VoIP‑звонок.
2. Нажимает «Ответить».
3. После установления соединения проигрывается аудио‑уведомление о записи и ИИ‑обработке.
4. Фиксируется согласие или отказ.
5. При согласии запускаются запись, media stream, ASR и ИИ‑анализ.
6. В приложении появляется live‑карточка договоренностей.
7. Пользователь подтверждает или исправляет результат.
8. После завершения звонка создаются задачи, напоминания и итог разговора.
9. Менеджер видит задачи пользователя на общей доске команды.

## 2. Роли пользователей

### Пользователь

- Принимает и совершает звонки через приложение.
- Видит свои договоренности, задачи и напоминания.
- Подтверждает или исправляет распознанные ИИ договоренности.
- Работает с личной доской задач.
- Может отключить запись и ИИ‑обработку.

### Менеджер

- Видит задачи всех пользователей своей команды.
- Работает с общей доской команды.
- Фильтрует задачи по сотруднику, статусу, сроку, приоритету и типу.
- Видит аналитику: выполнено вовремя, просрочено, в работе, среднее время закрытия.
- Не имеет доступа к задачам пользователей других команд.

## 3. Жизненный цикл звонка

```text
incoming
  → ringing
  → answered
  → consent_notice
  → consent_result
  → recording
  → analyzing
  → in_progress
  → completed
```

| Статус | Что происходит |
|---|---|
| `incoming` | Приложение получило входящий вызов |
| `ringing` | Показан экран входящего звонка |
| `answered` | Пользователь нажал «Ответить», соединение установлено |
| `consent_notice` | Собеседнику проигрывается аудио‑уведомление о записи и ИИ‑обработке |
| `consent_result` | Фиксируется согласие или отказ |
| `recording` | Запуск записи и media stream |
| `analyzing` | Аудио передается в ASR, начинается распознавание |
| `in_progress` | Активный разговор, live‑карточка обновляется |
| `completed` | Звонок завершен, сохранены транскрипт, итог и задачи |
| `missed` | Звонок не принят |
| `failed` | Ошибка соединения |

Критическое правило: запись начинается только после `answered` и успешного прохождения consent‑flow.

## 4. Архитектура

```text
Mobile App (iOS / Android)
├── Contacts
├── Incoming / Outgoing Call UI
├── Live Agreement Card
├── Personal Task Board
├── Local Cache (SQLite / Room)
└── Sync Engine

        │ REST: sync, tasks, calls
        │ WebSocket: live call events
        ▼
Backend API
├── Auth and Roles
├── Call Session Service
├── Consent Service
├── Agreement Service
├── Task Service
├── Notification Service
└── Manager Dashboard API

        │ SDK / API
        ▼
Voice Provider
├── VoIP calls
├── PSTN calls
├── Recording
└── Media Stream

        ▼
AI Pipeline
├── ASR
├── Speaker separation
├── LLM extraction
└── Agreement events

        ▼
PostgreSQL + Object Storage + Redis + Queue
```

### Важный принцип

Серверная PostgreSQL — единственный источник истины. Локальная база на телефоне — персональный кэш и очередь офлайн‑изменений. Мобильное приложение не является отдельной системой учета.

## 5. Кроссплатформенность

Мобильное приложение разрабатывается по принципу «одна кодовая база для iOS и Android».

### Рекомендуемый стек

| Вариант | Когда выбирать |
|---|---|
| React Native + Expo | Быстрый MVP, большая экосистема, JS/TS |
| Flutter | Единый UI, хорошая производительность |
| Kotlin Multiplatform | Общая бизнес‑логика с нативными UI |
| Нативная разработка | Максимальный контроль, но больше ресурсов |

Рекомендация для MVP: React Native + Expo или Flutter.

### Что общее для платформ

- UI и дизайн‑система.
- Логика звонков.
- Локальная база.
- Синхронизация.
- Задачи и договоренности.
- Аналитика.

### Что платформенно‑специфично

- Входящие VoIP‑звонки: CallKit/PushKit на iOS, Telecom/ConnectionService на Android.
- Push‑уведомления: APNs и FCM.
- Разрешения на микрофон.
- Фоновая работа.
- Сборка и подпись приложений.

Мобильное приложение не контейнеризируется: оно собирается нативными инструментами для iOS и Android.

## 6. Docker и серверная инфраструктура

Docker используется для серверной части: API, PostgreSQL, Redis, воркеров ИИ и хранилища.

```text
docker-compose.yml
├── api                  — backend API
├── worker-asr           — распознавание речи
├── worker-ai            — LLM и извлечение договоренностей
├── worker-notifications — напоминания
├── postgres             — основная база данных
├── redis                — кэш, очереди, live‑состояние
├── minio / s3           — аудио и транскрипты
└── nginx                — HTTPS, прокси, WebSocket
```

### Пример docker-compose.yml

```yaml
services:
  api:
    build: ./backend
    env_file: .env
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_started

  worker-asr:
    build: ./backend
    command: celery -A app.worker worker -Q asr
    env_file: .env
    depends_on:
      - redis
      - postgres

  worker-ai:
    build: ./backend
    command: celery -A app.worker worker -Q ai
    env_file: .env
    depends_on:
      - redis
      - postgres

  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: app
      POSTGRES_PASSWORD: app
      POSTGRES_DB: agreements
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app"]
      interval: 5s
      retries: 5

  redis:
    image: redis:7
    volumes:
      - redis_data:/data

  minio:
    image: minio/minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minio
      MINIO_ROOT_PASSWORD: minio123
    volumes:
      - minio_data:/data

volumes:
  postgres_data:
  redis_data:
  minio_data:
```

## 7. База данных

### Серверная PostgreSQL

Основные таблицы:

- `teams`
- `users`
- `calls`
- `call_audio`
- `transcripts`
- `agreements`
- `tasks`
- `reminders`
- `consents`
- `audit_log`

### Связи

```text
teams 1 ────────< users
  │                  │
  │                  │ 1
  │                  │
  │                  └────────< calls
  │                                │ 1
  │                                │
  │                                └────────< agreements
  │                                                │ 1
  │                                                │
  │                                                └────────< tasks
  │                                                                │ 1
  │                                                                │
  │                                                                └────────< reminders
  │
  └──────────────────────────────< users (manager_id)
```

| Связь | Тип | Смысл |
|---|---|---|
| `teams.id` → `users.team_id` | 1:N | В команде много пользователей |
| `users.id` → `teams.manager_id` | 1:1 | Пользователь может быть менеджером команды |
| `users.id` → `calls.user_id` | 1:N | Пользователь совершает много звонков |
| `calls.id` → `agreements.call_id` | 1:N | Из звонка извлекается несколько договоренностей |
| `users.id` → `agreements.owner_user_id` | 1:N | У договоренности есть ответственный |
| `agreements.id` → `tasks.agreement_id` | 1:1 / 1:N | Договоренность превращается в задачу |
| `users.id` → `tasks.assignee_user_id` | 1:N | У пользователя много задач |
| `tasks.id` → `reminders.task_id` | 1:N | К задаче привязаны напоминания |
| `calls.id` → `transcripts.call_id` | 1:1 | У звонка одна расшифровка |
| `calls.id` → `call_audio.call_id` | 1:1 | У звонка одна аудиозапись |

### SQL‑схема

```sql
CREATE TABLE teams (
  id UUID PRIMARY KEY,
  name TEXT NOT NULL,
  manager_id UUID UNIQUE
);

CREATE TABLE users (
  id UUID PRIMARY KEY,
  team_id UUID REFERENCES teams(id),
  phone TEXT UNIQUE NOT NULL,
  full_name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('user', 'manager')),
  created_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE teams
  ADD CONSTRAINT fk_teams_manager
  FOREIGN KEY (manager_id) REFERENCES users(id);

CREATE TABLE calls (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id),
  contact_phone TEXT NOT NULL,
  direction TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),
  status TEXT NOT NULL,
  started_at TIMESTAMPTZ,
  ended_at TIMESTAMPTZ,
  transcript TEXT,
  summary TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE call_audio (
  id UUID PRIMARY KEY,
  call_id UUID UNIQUE NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
  storage_url TEXT NOT NULL,
  duration_sec INTEGER,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE transcripts (
  id UUID PRIMARY KEY,
  call_id UUID UNIQUE NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
  language TEXT DEFAULT 'ru',
  full_text TEXT,
  status TEXT NOT NULL DEFAULT 'processing',
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE agreements (
  id UUID PRIMARY KEY,
  call_id UUID NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
  owner_user_id UUID NOT NULL REFERENCES users(id),
  type TEXT NOT NULL,
  object TEXT,
  due_date DATE,
  confidence NUMERIC(3,2),
  source_quote TEXT,
  status TEXT NOT NULL DEFAULT 'detected',
  version INTEGER NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE tasks (
  id UUID PRIMARY KEY,
  agreement_id UUID REFERENCES agreements(id) ON DELETE SET NULL,
  assignee_user_id UUID NOT NULL REFERENCES users(id),
  title TEXT NOT NULL,
  description TEXT,
  due_date DATE,
  priority TEXT NOT NULL DEFAULT 'medium',
  status TEXT NOT NULL DEFAULT 'new',
  version INTEGER NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE reminders (
  id UUID PRIMARY KEY,
  task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  remind_at TIMESTAMPTZ NOT NULL,
  channel TEXT NOT NULL CHECK (channel IN ('push', 'local', 'sms')),
  status TEXT NOT NULL DEFAULT 'scheduled',
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE consents (
  id UUID PRIMARY KEY,
  user_id UUID REFERENCES users(id),
  subject_type TEXT NOT NULL CHECK (
    subject_type IN ('app_user', 'call_participant')
  ),
  call_id UUID REFERENCES calls(id),
  consent_type TEXT NOT NULL CHECK (
    consent_type IN (
      'recording',
      'ai_processing',
      'data_storage',
      'notification'
    )
  ),
  status TEXT NOT NULL CHECK (
    status IN ('granted', 'denied', 'withdrawn')
  ),
  method TEXT NOT NULL CHECK (
    method IN ('app_settings', 'audio_notice', 'dtmf', 'sms_link')
  ),
  granted_at TIMESTAMPTZ,
  withdrawn_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ,
  metadata JSONB
);

CREATE TABLE audit_log (
  id UUID PRIMARY KEY,
  entity_type TEXT NOT NULL,
  entity_id UUID NOT NULL,
  actor_user_id UUID REFERENCES users(id),
  action TEXT NOT NULL,
  payload JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);
```

## 8. Локальная база на телефоне

Локальная SQLite/Room хранит персональную реплику данных пользователя.

### Что хранить

- Профиль пользователя и роль.
- Его задачи и договоренности.
- Последние звонки.
- Офлайн‑черновики.
- Очередь несинхронизированных изменений.
- `sync_token` и версии записей.

### Чего не хранить

- Задачи других сотрудников.
- Данные всей команды.
- Ненужные аудиозаписи.
- Данные, к которым у пользователя нет доступа.

### Таблицы локальной базы

```sql
CREATE TABLE tasks (
  id TEXT PRIMARY KEY,
  server_id TEXT,
  title TEXT NOT NULL,
  due_date TEXT,
  priority TEXT,
  status TEXT,
  version INTEGER,
  sync_status TEXT DEFAULT 'synced',
  updated_at TEXT
);

CREATE TABLE agreements (
  id TEXT PRIMARY KEY,
  server_id TEXT,
  call_id TEXT,
  title TEXT,
  due_date TEXT,
  owner TEXT,
  confidence REAL,
  status TEXT,
  version INTEGER,
  sync_status TEXT DEFAULT 'synced'
);

CREATE TABLE outbox (
  id TEXT PRIMARY KEY,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  operation TEXT NOT NULL,
  payload TEXT NOT NULL,
  idempotency_key TEXT UNIQUE NOT NULL,
  created_at TEXT,
  retry_count INTEGER DEFAULT 0,
  status TEXT DEFAULT 'pending'
);

CREATE TABLE sync_state (
  key TEXT PRIMARY KEY,
  value TEXT
);
```

## 9. Синхронизация

### Принцип

```text
UI → Repository → Local DB
                ↘ Outbox
                ↘ Sync Engine → Server
```

### Цикл синхронизации

```text
1. pull: GET /sync?since=<sync_token>
2. применить серверные изменения к локальной базе
3. push: отправить outbox
4. ack: получить подтверждение и удалить успешные операции
5. обновить sync_token
```

### Правила

- Сервер — источник истины.
- Локальная копия — кэш и очередь изменений.
- Каждая операция имеет `idempotency_key`.
- При ошибке — retry с backoff.
- При конфликте сервер возвращает авторитетную версию.
- Синхронизируются только дельты, а не вся база.
- Локальный кэш можно полностью восстановить с сервера.

## 10. Consent flow

### Согласие пользователя приложения

При первом входе показывается экран:

> «Чтобы фиксировать договоренности из звонков, приложение может записывать и обрабатывать аудиоразговоры с помощью ИИ. Мы распознаем речь, выделяем задачи, сроки и обязательства. Запись хранится ограниченное время, доступ к ней ограничен. Вы можете отключить запись и удалить данные в любой момент».

Действия:

- «Согласен и включить запись».
- «Не включать запись».
- Ссылка на политику обработки данных.

### Согласие собеседника

После того как пользователь приложения ответил, но до начала записи, проигрывается аудио‑уведомление:

> «Внимание: разговор будет записан и обработан автоматической системой для фиксации договоренностей. Продолжая разговор, вы соглашаетесь с обработкой данных. Подробности — в политике конфиденциальности».

### Варианты согласия собеседника

| Режим | Как работает |
|---|---|
| Уведомление + продолжение | Дисклеймер проигрывается; если участник остается на линии — фиксируется согласие |
| Активное согласие | «Нажмите 1, чтобы продолжить записываемый разговор» |
| Отказ | «Нажмите 2, чтобы продолжить без записи» |
| Предварительное согласие | Ссылка в SMS/приложении до звонка |

### Логика backend

```text
on call.answered:
  1. проверить согласие пользователя приложения
  2. если согласия нет → обычный звонок, запись не включается
  3. проиграть аудио-уведомление собеседнику
  4. зафиксировать consent_event
  5. если участник отказался → не включать запись
  6. если согласие получено → запустить запись
  7. открыть media stream
  8. запустить ASR и ИИ-анализ
  9. отправить в приложение event analysis_started
```

## 11. Звонки через приложение

### Входящий звонок

```text
Звонящий → обычный номер / VoIP-номер
              │
              ▼
     Voice Provider
              │ push / IncomingCall
              ▼
Приложение пользователя
              │
   Пользователь нажимает «Ответить»
              │
              ▼
   Call.answer()
              │
              ▼
   Call connected
              │
              ├── consent notice
              ├── start recording
              ├── start media stream → backend
              └── ASR + LLM анализ
```

### Исходящий звонок

```text
Пользователь A (приложение)
      │ VoIP
      ▼
Voice Provider
      │ PSTN
      ▼
Обычный номер пользователя B
```

Собеседнику не обязательно устанавливать приложение: он получает обычный звонок. ИИ‑анализ доступен на стороне инициатора звонка.

### Сценарии

| Кто звонит | У кого есть приложение | Тип звонка | ИИ‑фиксация |
|---|---|---|---|
| Пользователь A | Только у A | App → PSTN → обычный номер B | Да, у A |
| Пользователь A | У обоих | App → PSTN → номер B | Да, у A |
| Пользователь A | У обоих, оба онлайн | App → App через интернет | Да, у обоих |
| Пользователь A | Только у B | PSTN → номер компании → App | Да, у B |
| Любой | Ни у кого | Обычный сотовый звонок | Нет |

### 11.1. Voice‑провайдер: МТС Exolve (решение Этапа 1)

Выбран **МТС Exolve**. Соответствие `VoiceProviderPort` и API (сверено с
docs.exolve.ru):

| Возможность | API Exolve |
|---|---|
| Входящие, сценарий по URL (call control) | переадресация входящих на URL: Exolve POST‑ит `{sip_id, numberA, call_sid}`, мы отвечаем JSON‑RPC с маршрутом на SIP ID пользователя |
| Исходящие на обычные номера | Voice API / Callback API |
| Запись разговора | Call Record API: `POST /sip/v1/SetCallRecordState`, `POST /statistics/call-record/v1/GetInfo`, `GET /statistics/download/{uid}` |
| События звонка (webhook) | Statistics API: Inbound Call Events — `type` `b` (Begin/A), `o` (Originate/B), `s` (Start/B ответил), `h`, `e` (End), `crr` (запись готова) |
| Уведомление собеседнику (согласие) | `file_to_A` в ответе call control — проигрывается вызывающему |
| Мобильный клиент | Mobile SDK (Android, iOS, Flutter) |
| Транскрибация (альтернатива своему ASR) | Call Transcribation / Speech Analytics |

**Два решения по итогам сверки API (трек C):**

1. **Аудио в ML‑пайплайн идёт от мобильного клиента.** У Exolve нет серверного
   медиапотока (WebSocket/RTP нам не отдаётся), поэтому `open_media_stream()`
   возвращает базу ingest‑URL (`MEDIA_INGEST_URL`), а приложение загружает
   смикшированный SDK‑поток на `POST {MEDIA_INGEST_URL}/calls/{call_id}/audio`
   (§13). Пайплайн §12 не меняется — меняется только источник `Media Stream`.
2. **Согласие собеседника — `notice` + продолжение разговора.** Сбора DTMF в
   inbound‑API Exolve нет, поэтому для Exolve `CONSENT_MODE=notice`: текст
   уведомления проигрывается через `file_to_A`, факт согласия пишется в
   `consents`. Режим `dtmf` остаётся для провайдеров, которые его поддерживают.

**Webhooks Exolve (трек C).** Оба колбэка обслуживает `services/voice_webhooks.py`
(адаптер остаётся `integrations/exolve.py`):

- `POST /api/voice/exolve/control` — call control. По `sip_id` находим
  принимающего пользователя и его SIP‑URI (`EXOLVE_SIP_ROUTES`,
  `sip_id=phone:sip_uri`), заводим/переиспользуем `Call` (`external_id =
  call_sid`, direction `inbound`) и отвечаем JSON‑RPC‑телом: маршрут на SIP ID
  пользователя, `event_URL` на наш event‑эндпоинт и `file_to_A` — уведомление о
  записи. Неизвестный `sip_id` → JSON‑RPC `error` (звонок не маршрутизируется).
  Повторный колбэк с тем же `call_sid` идемпотентен.
- `POST /api/voice/exolve/events` — прогресс `b/o/s/h/e/crr`. Звонок находится
  по `client_id` (наш id, эхо из routing‑тела) или по `call_sid`; события
  `b/o/s/e` прогоняются через тот же `CallSessionService`, что и mock, поэтому
  правило «запись только после `answered` + согласия» соблюдается автоматически.
  `h`/`crr` и неизвестные типы подтверждаются без перехода жизненного цикла.
- Оба эндпоинта подписываются общим секретом (`VOICE_WEBHOOK_SECRET`), который
  Exolve присылает как `?secret=` (заголовки Exolve не ставит). `event_URL`
  собирается из `PUBLIC_BASE_URL` + базового пути API.

Интеграция — адаптер за `VoiceProviderPort` (`integrations/exolve.py`); ML‑пайплайн
и мобильный UI не меняются. Ключи/номера — только из `.env` (`EXOLVE_*`, `PUBLIC_BASE_URL`),
в репозиторий не коммитятся.

## 12. ИИ‑пайплайн

```text
Media Stream
  → Audio Decoder
  → VAD / chunking
  → ASR
  → Transcript buffer
  → LLM extraction
  → Agreement Service
  → WebSocket → App
```

### Что извлекает ИИ

- Обязательство: кто и что должен сделать.
- Срок: дата или относительный срок.
- Ответственного.
- Объект: КП, счет, договор, услуга.
- Сумму, если она важна.
- Следующий шаг.
- Confidence — уверенность распознавания.

### Пример результата

```json
{
  "event": "agreement_detected",
  "call_id": "CALL-882",
  "agreement": {
    "id": "AGR-901",
    "type": "send_document",
    "object": "счет",
    "owner": "caller",
    "due_date": "2026-10-16",
    "confidence": 0.92,
    "quote": "Мы пришлем счет до пятницы",
    "status": "requires_review"
  }
}
```

Если confidence ниже порога, например 0.8, договоренность помечается как `requires_review` и не превращается в задачу автоматически.

### Изменение уже зафиксированных договорённостей

- Подтверждённая («закреплённая») договорённость и созданная из неё задача
  остаются **изменяемыми**: пользователь может поправить тип, объект,
  ответственного, срок и сумму и отклонить её, если она больше не актуальна.
  Подтверждение не «замораживает» карточку — правило продукта «пользователь
  должен уметь исправить или отклонить результат» действует и после
  подтверждения.
- Изменение договорённости переносится на связанную задачу (название, срок,
  ответственный, приоритет), а также на напоминания/календарь: доска и
  уведомления показывают актуальное значение. Каждое изменение увеличивает
  `version` и пишется в `audit_log` (§16: «изменения задач и договорённостей»).
- Чтобы **изменить**, а не продублировать, система должна по звонку понимать,
  была ли уже такая договорённость. Каждая договорённость хранит источник
  (`call_id`, `source_quote`, аудио‑таймстемпы, `owner`), и при повторном
  извлечении или повторной обработке звонка ИИ сопоставляет результат с уже
  существующими договорённостями того же звонка: совпадение **обновляет**
  существующую запись, а не создаёт новую. Повторная обработка одного и того же
  аудио идемпотентна (§12, §13).

## 13. API

### Авторизация

```http
POST /auth/login
{
  "phone": "+7XXXXXXXXXX",
  "otp": "1234"
}
```

### Создание звонка

```http
POST /calls
{
  "callee_phone": "+7XXXXXXXXXX",
  "contact_id": "CNT-12",
  "record_consent": true
}
```

### Приём аудио звонка (клиент → сервер)

Voice‑провайдер (МТС Exolve) не отдаёт серверный медиапоток, поэтому запись
загружает мобильный клиент (§11.1). Загрузка возможна только после `answered` и
согласия: без `recording_started_at` запрос отклоняется (409), чужой звонок —
403. Тело — сырое аудио (`Content-Type: audio/*`), лимит
`MAX_AUDIO_UPLOAD_MB` (413), срок хранения — `AUDIO_RETENTION_DAYS`. После
загрузки аудио кладётся в MinIO, заполняется `call_audio` и ставится ASR.

```http
POST /calls/{call_id}/audio                  # смешанный поток (по умолчанию)
POST /calls/{call_id}/audio?leg=operator     # одна нога VoIP (?leg=client — вторая)
     &duration_sec=123
```

### Вебхуки Voice‑провайдера (МТС Exolve, §11.1)

```http
POST /voice/exolve/control?secret={VOICE_WEBHOOK_SECRET}
{ "sip_id": "1001", "numberA": "+7XXXXXXXXXX", "call_sid": "..." }
→ JSON‑RPC 2.0: followme на SIP ID пользователя, event_URL, file_to_A (уведомление)

POST /voice/exolve/events?secret={VOICE_WEBHOOK_SECRET}
{ "type": "s" | "b" | "o" | "e" | "h" | "crr", "call_sid": "...", "client_id": "..." }
→ { "status": "handled" | "ignored", "call_id": "...", "event": "s" }
```

Маршрутизация входящих — `EXOLVE_SIP_ROUTES` (`sip_id=phone:sip_uri`),
внешний адрес колбэков — `PUBLIC_BASE_URL`.

### Синхронизация

```http
GET /sync?since=2026-10-13T09:00:00Z
POST /sync
```

### Задачи пользователя

```http
GET /me/tasks?status=active
PATCH /tasks/{task_id}
POST /tasks/{task_id}/complete
```

### Календарь, напоминания, черновик (только после подтверждения)

Действия пользователя по задаче из `confirmed`-договорённости. Ничего не
создаётся автоматически, сообщение только черновик.

```http
POST /tasks/{task_id}/calendar        # записать в календарь (порт)
GET  /tasks/{task_id}/calendar.ics    # переносимый .ics
POST /tasks/{task_id}/reminders       # {remind_at, channel}
GET  /tasks/{task_id}/reminders
POST /reminders/{reminder_id}/cancel
POST /tasks/{task_id}/message-draft   # черновик клиенту, sent: false
```

### Доска менеджера

```http
GET /manager/team/tasks?user_id=&status=&due_before=
GET /manager/team/stats
GET /manager/team/members
```

### WebSocket‑события

Транспорт: `GET /api/ws/calls/{call_id}` (WebSocket). Аутентификация — JWT
access‑токен в заголовке `Authorization: Bearer <token>` (мобильный) или в query
`?token=<token>` (браузер). Подписаться может только владелец звонка; менеджер
транскрипт и аудио не получает. Коды закрытия рукопожатия: `4401`
(не авторизован), `4403` (чужой звонок), `4404` (звонок не найден).

Схема событий версионирована: каждый кадр — конверт `version: 1`, при
несовместимом изменении версия увеличивается. Клиент сверяется с
`GET /api/ws/events/schema`. При подключении сначала отдаются сохранённые
события (replay), затем живые; на стыке дубликаты не отправляются.

| event | payload |
|---|---|
| `partial_transcript` | `speaker` (`user` \| `client`), `text` |
| `agreement_detected` | `agreement` (объект как в §12) |
| `analysis_started` | `{}` |
| `call_ended` | `duration_sec`, `summary` |

```json
{
  "version": 1,
  "event": "partial_transcript",
  "call_id": "CALL-771",
  "payload": {
    "speaker": "client",
    "text": "Хорошо, пришлите КП до пятницы"
  }
}
```

```json
{
  "version": 1,
  "event": "agreement_detected",
  "call_id": "CALL-771",
  "payload": {
    "agreement": {
      "id": "AGR-331",
      "type": "send_document",
      "object": "КП",
      "owner": "user",
      "due_date": "2026-10-16",
      "confidence": 0.93,
      "quote": "пришлите КП до пятницы",
      "status": "requires_review"
    }
  }
}
```

```json
{
  "version": 1,
  "event": "call_ended",
  "call_id": "CALL-771",
  "payload": {
    "duration_sec": 214,
    "summary": "Клиент ждет КП до 16.10. Встреча не назначена."
  }
}
```

## 14. Личная доска пользователя

### Экран

- Ближайшие задачи.
- Просроченные задачи.
- Задачи на сегодня.
- Выполненные задачи.
- Связь задачи со звонком и договоренностью.

### Статусы задач

- `new` — новая.
- `in_progress` — в работе.
- `done` — выполнена.
- `overdue` — просрочена.
- `canceled` — отменена.

### Действия

- Начать задачу.
- Отметить выполненной.
- Перенести срок.
- Изменить приоритет.
- Отменить.
- Перейти к звонку‑источнику.
- **Изменить договорённость** (в том числе уже подтверждённую) и связанную с
  ней задачу; изменение фиксируется в `audit_log` и в `version`. Если из
  договорённости уже создана задача, правка карточки обновляет задачу.

## 15. Общая доска менеджера

### Экран

- Задачи всех пользователей команды.
- Фильтры: сотрудник, статус, срок, приоритет, тип задачи.
- Сортировка: сначала просрочки, затем ближайшие дедлайны.
- Карточка задачи: исполнитель, клиент, звонок‑источник, дедлайн, статус.
- Аналитика по сотрудникам и команде.

### Аналитика

- Количество созданных договоренностей.
- Количество задач.
- Выполнено вовремя.
- Просрочено.
- Среднее время закрытия задачи.
- Доля задач, созданных из звонков.
- Общий процент выполнения в срок.

## 16. Безопасность

- Явное согласие пользователя на запись и ИИ‑обработку.
- Автоматическое аудио‑уведомление собеседнику перед началом записи.
- Фиксация версии текста согласия, даты, метода и идентификатора звонка.
- Возможность отозвать согласие и запросить удаление данных.
- Шифрование аудио, транскриптов и персональных данных.
- Ограниченный срок хранения аудио.
- Разграничение доступа по ролям и командам.
- Audit log: факт согласия, старт записи, изменения задач и договоренностей.
- JWT access token с коротким сроком жизни и refresh token.
- Проверка прав на сервере, а не только в UI.

## 17. План работ

### Этап 1. Подготовка

- Зафиксировать MVP‑сценарий.
- Определить роли пользователя и менеджера.
- Выбрать мобильный стек: React Native/Expo или Flutter.
- Выбрать Voice‑провайдера — **МТС Exolve** (см. §11.1).
- Создать репозиторий и структуру проекта.

### Этап 2. Серверная основа

- Поднять PostgreSQL, Redis, Object Storage.
- Реализовать модели: users, teams, calls, agreements, tasks, reminders, consents, audit_log.
- Сделать авторизацию и роли.
- Реализовать CRUD задач и договоренностей.
- Настроить Docker Compose.

### Этап 3. Мобильная основа

- Создать кроссплатформенное приложение.
- Реализовать авторизацию.
- Сделать список контактов.
- Сделать личную доску задач.
- Подключить локальную SQLite/Room.
- Реализовать Repository и базовый sync.

### Этап 4. Звонки

- Интегрировать Voice SDK.
- Реализовать входящие VoIP‑звонки.
- Реализовать исходящие звонки на обычные номера.
- Сделать экран активного звонка.
- Обработать события: входящий, гудки, ответ, завершение, обрыв.

### Этап 5. Consent flow

- Сделать экран согласия пользователя.
- Добавить настройки записи и ИИ‑обработки.
- Реализовать аудио‑уведомление собеседнику.
- Фиксировать согласие или отказ.
- Блокировать запись при отсутствии согласия.

### Этап 6. Запись и анализ

- После `answered` и согласия запускать запись.
- Настроить media stream на backend.
- Подключить streaming ASR.
- Реализовать частичную и финальную транскрипцию.
- Подключить LLM для извлечения договоренностей.
- Отправлять события в приложение по WebSocket.

### Этап 7. Договоренности и задачи

- Сделать live‑карточку договоренностей.
- Дать возможность редактировать и подтверждать результат.
- Создавать задачи из подтвержденных договоренностей.
- Добавить статусы задач.
- Реализовать напоминания.
- Связать задачу со звонком и договоренностью.

### Этап 8. Доски

- Реализовать личную доску пользователя.
- Реализовать общую доску менеджера.
- Добавить фильтры и сортировку.
- Сделать аналитику по сотрудникам и команде.
- Ограничить доступ по ролям и командам.

### Этап 9. Итог звонка и календарь

- Формировать резюме разговора.
- Собирать подтвержденные договоренности.
- Генерировать черновик сообщения клиенту.
- Добавлять события в календарь или генерировать `.ics`.
- Сохранять историю звонков.

### Этап 10. Тестирование и демо

- Протестировать входящие и исходящие звонки.
- Проверить consent flow.
- Проверить работу при Wi‑Fi, 4G и слабом сигнале.
- Проверить обрыв WebSocket и восстановление.
- Проверить офлайн‑режим и синхронизацию.
- Проверить права доступа.
- Подготовить демо‑сценарий и резервный режим.
- Подготовить презентацию.

## 18. Что не входит в MVP

- Прослушивание или запись обычных сотовых звонков в системной «Телефон».
- Полноценная интеграция с корпоративной CRM.
- Многоязычный ASR.
- Сложная ролевая модель и админ‑панель.
- Автоматическая отправка сообщений клиенту без подтверждения.
- Биллинг и тарифы.
- Полноценный корпоративный SSO.

## 19. Критерии готовности MVP

- Пользователь может принять входящий VoIP‑звонок в приложении.
- После ответа и согласия запускаются запись и анализ.
- ИИ распознает разговор и выделяет договоренности.
- Пользователь видит live‑карточку и может исправить результат.
- Подтвержденная договоренность превращается в задачу.
- Создается напоминание.
- После звонка формируется итог.
- Менеджер видит задачи команды на общей доске.
- Серверная часть запускается через Docker Compose.
- Приложение работает на iOS и Android из одной кодовой базы.
- Демо проходит от начала до конца менее чем за 3 минуты.
