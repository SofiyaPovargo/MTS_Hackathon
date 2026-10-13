# apps/mobile — мобильное приложение (Flutter)

Приложение для пользователя и менеджера: звонки через voice-провайдера, consent,
запись и анализ разговора, карточки договорённостей, задачи, личная и
менеджерская доски. Одна кодовая база для Android и iOS (`plan.md`, `AGENTS.md`).

Текущий объём — **Этапы 3–5**: мобильная основа (авторизация, контакты, личная
доска, SQLite-кэш, Repository и синхронизация), **звонки на Dart-уровне** (порт
`VoiceCallProvider` за DI, `CallController`, экран звонка, зеркало
стейт-машины, mock-провайдер) и **consent-flow** (экран согласия на первом
входе, настройки записи/ИИ: toggle, отзыв, удаление данных, политика;
блокировка записи без согласия; отказ собеседника). Live-карточка (WS) —
следующий этап (см. `TEAM_PLAN.md`).

## Слои (чистая архитектура)

```
lib/
  main.dart                 точка входа (ProviderScope)
  core/config.dart          конфиг; API base URL из --dart-define, не хардкод
  domain/                   сущности и правила, без Flutter/плагинов
    enums.dart              wire-enums (должны совпадать с backend)
    models.dart             UserProfile, AuthSession, TaskItem, Agreement, Call, ContactItem, ConsentRecord
    call.dart               CallSignal/CallState + зеркало стейт-машины звонка
    consent.dart            AppConsent (решение пользователя; кэш + статус синка)
    sync_models.dart        SyncChange/Pull/Operation/Result (контракт /sync)
    ports.dart              интерфейсы (AuthApi, SessionStore, BoardApi, SyncApi,
                            CallApi, ConsentApi, ConsentStore, VoiceCallProvider,
                            ContactsSource, LocalBoardStore, OutboxStore, SyncStateStore)
  application/              контроллеры Riverpod + провайдеры (wiring)
    call_controller.dart    сессия звонка (набор/ответ/отбой/mute, сигналы провайдера,
                            consent-статусы: notice/result, отказ собеседника)
    consent_controller.dart решение пользователя (local-first + write-through на сервер)
  infrastructure/           реализации портов
    api/                    dio-клиент (bearer, refresh-on-401), auth/board/sync/call/consent API
    db/                     sqflite: схема (v2), session, outbox, sync_state, доска, app_settings
    repositories/           контакты устройства за портом
    sync/sync_engine.dart   цикл синхронизации
    voice/                  mock voice-провайдер (реальный SDK — за тем же портом)
  ui/                       экраны и виджеты (никакой бизнес-логики)
    screens/call_screen.dart     экран звонка (оверлей) + таймер
    screens/dialer_screen.dart   набор номера
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

## Звонки (Этап 4)

Звонки абстрагированы портом `VoiceCallProvider` (`domain/ports.dart`):
`ensureMicrophonePermission`, `signals` (incoming/ringing/answered/ended/dropped/
missed), `dial`, `answer`, `decline`, `hangup`, `setMuted`. Платформенный адаптер
(CallKit/PushKit, Telecom/ConnectionService, MTS Exolve SDK) внедряется через DI
— в фичах платформенных API нет.

- `application/call_controller.dart` — `CallController` (Riverpod): исходящий
  набор (`POST /calls` + `dial`), входящий (answer/decline), mute, hangup. Каждое
  событие провайдера проходит через клиентское зеркало стейт-машины
  (`domain/call.dart`, совпадает с backend `state_machine.py`).
- Микрофон запрашивается контекстно при старте/ответе; при отказе звонок не
  начинается и показывается сообщение (ручной ввод контакта остаётся).
- Экран звонка — оверлей поверх всего приложения (`CallOverlay`), поэтому
  входящий виден на любом экране: таймер, mute, завершение.
- Начать звонок: иконка на контакте или FAB «Новый звонок» на доске.
- `infrastructure/voice/mock_voice_provider.dart` — mock-провайдер: исходящий
  соединяется автоматически через 2 c, входящий можно смоделировать dev-кнопкой
  на доске (debug-сборка). Реального VoIP SDK здесь нет — он подключается на
  машине с Android SDK/Xcode.

События совпадают с backend `CallEvent` (`incoming`, `ringing`, `answered`,
`ended`, `dropped`, `missed`); статусы — с backend `CallStatus`.

## Согласие (Этап 5)

Запись и ИИ-обработка включаются только после явного согласия пользователя
приложения (`plan.md` §10):

- **Гейт первого входа** (`ui/screens/consent_screen.dart`): пока решение не
  принято, вместо доски показывается экран согласия («Согласен и включить
  запись» / «Не включать запись», ссылка на политику).
- **Настройки** (`ui/screens/settings_screen.dart`, с доски — иконка ⚙):
  переключатель записи/ИИ, отзыв согласия (с подтверждением), удаление данных
  (реальный серверный флоу `POST /me/data/delete`), политика.
- **Хранение**: решение кэшируется в SQLite (`app_settings`, схема v2) и
  пишется на сервер (`PUT /me/consent`, `POST /me/consent/withdraw`); без сети —
  pending-состояние с кнопкой «Повторить» (`ConsentController.retrySync`).
  Кэш — единственный источник для гейта, т.к. GET-эндпоинта для consent нет.
- **Блокировка записи**: `CallController` берёт `recordingEnabled` из согласия
  при старте/ответе звонка; без согласия звонок остаётся обычным (без записи)
  и предлагается ручной ввод договорённостей.
- **Собеседник**: уведомление (`consent_notice`) проигрывает провайдер
  (backend, Exolve `file_to_A`), результат (`consent_result`) придёт в звонок
  событиями WS на Этапе 7; `markConsentResult(granted: false)` переводит звонок
  в `in_progress` без записи и показывает «Собеседник отказался от записи».
- Тексту согласия соответствует версия `consentTextVersion = 'v1'` (на сервере —
  `CONSENT_VERSION`); при изменении текста приложение попросит согласие заново.

## Вход

OTP-поток: `POST /auth/otp/request` → `POST /auth/login`. В dev-режиме OTP
фиксированный — `1234`. Демо-пользователи: Анна `+79000000002`,
Борис `+79000000003`, менеджер Ирина `+79000000001`. Сессия (access + rotating
refresh) сохраняется в SQLite и восстанавливается при запуске; истёкший access
токен обновляется прозрачно при 401.

## Локальная БД и синхронизация

Сервер — единственный источник истины; SQLite хранит только данные пользователя:
`tasks`, `agreements`, `session`, `outbox`, `sync_state`, `app_settings` (кэш
согласия). Цикл (`plan.md` §9):

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

Платформенно-зависимый код (контакты через `flutter_contacts`; voice-провайдер —
CallKit/PushKit, Telecom/ConnectionService, MTS Exolve SDK; далее APNs/FCM) скрыт
за портами и внедряется через DI — в фичах Android/iOS-only API не используются.
Звонки на Этапе 4 реализованы на Dart-уровне: порт + контроллер + экран + mock;
нативный адаптер подключается на машине с установленными Android SDK/Xcode.

## Контракт API

Dart-модели зеркалят Pydantic-схемы `services/api/src/app/api/schemas.py`.
При изменении OpenAPI контракта обновляйте модели и клиентов здесь; формат
WS-событий (`partial_transcript`, `agreement_detected`, `analysis_started`,
`call_ended`) ещё согласуется и будет добавлен на Этапе 7.
