# apps/mobile — мобильное приложение (Flutter)

Приложение для пользователя и менеджера: звонки через voice-провайдера, consent,
запись и анализ разговора, карточки договорённостей, задачи, личная и
менеджерская доски. Одна кодовая база для Android и iOS (`plan.md`, `AGENTS.md`).

Текущий объём — **Этап 3 (мобильная основа)**: авторизация, контакты, личная
доска, локальный кэш SQLite, Repository и синхронизация. Звонки, consent и
live-карточка — следующие этапы (см. `TEAM_PLAN.md`).

## Слои (чистая архитектура)

```
lib/
  main.dart                 точка входа (ProviderScope)
  core/config.dart          конфиг; API base URL из --dart-define, не хардкод
  domain/                   сущности и правила, без Flutter/плагинов
    enums.dart              wire-enums (должны совпадать с backend)
    models.dart             UserProfile, AuthSession, TaskItem, Agreement, Call, ContactItem
    sync_models.dart        SyncChange/Pull/Operation/Result (контракт /sync)
    ports.dart              интерфейсы (AuthApi, SessionStore, BoardApi, SyncApi,
                            ContactsSource, LocalBoardStore, OutboxStore, SyncStateStore)
  application/              контроллеры Riverpod + провайдеры (wiring)
  infrastructure/           реализации портов
    api/                    dio-клиент (bearer, refresh-on-401), auth/board/sync API
    db/                     sqflite: схема, session, outbox, sync_state, доска
    repositories/           контакты устройства за портом
    sync/sync_engine.dart   цикл синхронизации
  ui/                       экраны и виджеты (никакой бизнес-логики)
```

Правило проекта: бизнес-логика, ML и внешние адаптеры — вне виджетов. Виджеты
зависят только от контроллеров из `application/`, контроллеры — от портов
`domain/ports.dart`, инфраструктура их реализует. Это позволяет подменять
бэкенд, БД и контакты фейками в тестах.

## Конфигурация backend URL

Адрес бэкенда берётся из build-конфигурации, в коде не хардкодится
(`AGENTS.md`). Значение по умолчанию зависит от платформы:

| Платформа | По умолчанию |
|---|---|
| Android-эмулятор | `http://10.0.2.2:8000/api` |
| iOS-симулятор | `http://localhost:8000/api` |
| Физическое устройство | задать явно |

Явно:

```bash
flutter run --dart-define=API_BASE_URL=https://your-host/api
flutter run --dart-define=API_BASE_URL=http://192.168.1.50:8000/api   # устройство в LAN
```

Полный стек поднимается из корня репозитория: `docker compose up -d`. Наружу
смотрит только nginx (TLS) — `https://localhost/api` (нужен `-k` для self-signed).
Для отладки без nginx доступен прямой `http://127.0.0.1:8000/api`.

## Вход

OTP-поток: `POST /auth/otp/request` → `POST /auth/login`. В dev-режиме OTP
фиксированный — `1234`. Демо-пользователи: Анна `+79000000002`,
Борис `+79000000003`, менеджер Ирина `+79000000001`. Сессия (access + rotating
refresh) сохраняется в SQLite и восстанавливается при запуске; истёкший access
токен обновляется прозрачно при 401.

## Локальная БД и синхронизация

Сервер — единственный источник истины; SQLite хранит только данные пользователя:
`tasks`, `agreements`, `session`, `outbox`, `sync_state`. Цикл (`plan.md` §9):

```
pull (GET /sync?since=) → apply в локальную БД → push outbox (POST /sync)
→ ack → обновить sync_token
```

- Повторный приход записи с версией `<=` известной пропускается (идемпотентно).
- Каждая операция outbox имеет `idempotency_key` (уникальный индекс) — ретраи не
  дублируют работу на сервере.
- Конфликт версий: сервер авторитетен — операция снимается с очереди, токен
  сбрасывается, следующий pull перезаписывает локальную запись серверной.
- Сетевые/5xx ошибки ретраятся с экспоненциальной задержкой; 401/403 всплывают
  наверх для повторной авторизации.
- Доска работает offline-first: при неудачном sync показывается локальный кэш.

## Команды

```bash
cd apps/mobile
flutter pub get
flutter analyze        # гейт: должен быть чист
flutter test           # гейт: юнит + виджет-тесты
flutter run            # нужен Android SDK / Xcode
```

## Ограничение платформы (важно)

На текущей dev-машине **нет Android SDK, Java и Xcode**, поэтому сборка и запуск
на устройстве/эмуляторе здесь недоступны. Проверка ограничена уровнем Dart:
`flutter analyze` и `flutter test` (то есть доменная логика, локальная БД,
sync-движок, контроллеры и виджеты). Команды `flutter build` / `flutter run`
надо выполнять на машине с установленными Android SDK и/или Xcode.

Платформенно-зависимый код (контакты через `flutter_contacts`; в следующих
этапах CallKit/PushKit, Telecom/ConnectionService, APNs/FCM) скрыт за портами и
внедряется через DI — в фичах Android/iOS-only API не используются.

## Контракт API

Dart-модели зеркалят Pydantic-схемы `services/api/src/app/api/schemas.py`.
При изменении OpenAPI контракта обновляйте модели и клиентов здесь; формат
WS-событий (`partial_transcript`, `agreement_detected`, `analysis_started`,
`call_ended`) ещё согласуется и будет добавлен на Этапе 7.
