# apps/mobile — мобильное приложение (Flutter)

Приложение для пользователя и менеджера: звонки через voice-провайдера, consent,
запись и анализ разговора, карточки договорённостей, задачи, личная и
менеджерская доски. Одна кодовая база для Android и iOS (`plan.md`, `AGENTS.md`).

Текущий объём — **Этапы 3–5, 7, 8**: мобильная основа (авторизация, контакты,
личная доска, SQLite-кэш, Repository и синхронизация), **звонки на Dart-уровне**
(порт `VoiceCallProvider` за DI, `CallController`, экран звонка, зеркало
стейт-машины, mock-провайдер), **consent-flow** (экран согласия на первом
входе, настройки записи/ИИ: toggle, отзыв, удаление данных, политика;
блокировка записи без согласия; отказ собеседника), **live-карточка
договорённостей по WebSocket** (транскрипт, карточки договорённостей,
confirm/reject/edit, ручной ввод без согласия, задача из `confirmed`) и
**доски** (личная с секциями и действиями по задачам через outbox; доска
менеджера с фильтрами, аналитикой и составом команды).
Нативный VoIP-адаптер, загрузка аудио на `MEDIA_INGEST_URL`, итог звонка и
календарь/удаление — следующие шаги (см. `TEAM_PLAN.md`).

## Слои (чистая архитектура)

```
lib/
  main.dart                 точка входа (ProviderScope)
  core/config.dart          конфиг; API base URL из --dart-define, не хардкод
  domain/                   сущности и правила, без Flutter/плагинов
    enums.dart              wire-enums (должны совпадать с backend)
    models.dart             UserProfile, AuthSession, TaskItem, Agreement, Call, ContactItem, ConsentRecord, TeamMember/TeamStats, TaskPatch
    board.dart              чистые правила досок (секции/сортировка/фильтры)
    call.dart               CallSignal/CallState + зеркало стейт-машины звонка
    consent.dart            AppConsent (решение пользователя; кэш + статус синка)
    ws_event.dart           конверт WS-событий (v1) + TranscriptSegment
    sync_models.dart        SyncChange/Pull/Operation/Result (контракт /sync)
    ports.dart              интерфейсы (AuthApi, SessionStore, BoardApi, ManagerApi,
                            SyncApi, CallApi, ConsentApi, ConsentStore,
                            VoiceCallProvider, CallEventsPort, AgreementApi,
                            ContactsSource, LocalBoardStore, OutboxStore,
                            SyncStateStore)
  application/              контроллеры Riverpod + провайдеры (wiring)
    call_controller.dart    сессия звонка (набор/ответ/отбой/mute, сигналы провайдера,
                            consent-статусы: notice/result, отказ собеседника),
                            live-лента WS (транскрипт/договорённости), действия
                            по договорённостям (confirm/reject/edit/ручной ввод)
    consent_controller.dart решение пользователя (local-first + write-through на сервер)
    board_controller.dart   личная доска + действия по задачам (outbox + sync)
    manager_controller.dart доска менеджера (задачи/аналитика/команда, фильтры)
  infrastructure/           реализации портов
    api/                    dio-клиент (bearer, refresh-on-401), auth/board/sync/call/consent/agreement/manager API
    db/                     sqflite: схема (v2), session, outbox, sync_state, доска, app_settings
    repositories/           контакты устройства за портом
    sync/sync_engine.dart   цикл синхронизации
    voice/                  mock voice-провайдер (реальный SDK — за тем же портом)
    ws/ws_call_events.dart  WS-клиент live-ленты (конверт v1 → CallEvent)
  ui/                       экраны и виджеты (никакой бизнес-логики)
    formats.dart                 пользовательские подписи (статусы/приоритет/владелец/уверенность)
    screens/call_screen.dart     экран звонка (оверлей) + таймер + live-карточка
    screens/agreement_edit_dialog.dart правка/ручной ввод договорённости
    screens/board_screen.dart    личная доска (секции) + вход на доску менеджера
    screens/task_actions_sheet.dart действия по задаче
    screens/manager_board_screen.dart доска менеджера (задачи/аналитика/сотрудники)
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
  (backend, Exolve `file_to_A`). Событие `analysis_started` по WS означает, что
  согласие получено → клиент доводит звонок до `analyzing`; отказ собеседника
  отдельным WS-событием **не сигнализируется** (контракт — 4 типа событий),
  поэтому `markConsentResult(granted: false)` переводит звонок в `in_progress`
  без записи и показывает «Собеседник отказался от записи».
- Тексту согласия соответствует версия `consentTextVersion = 'v1'` (на сервере —
  `CONSENT_VERSION`); при изменении текста приложение попросит согласие заново.

## Запись и офлайн-звонок (Этап 6)

Правило (зафиксировано 2026-10-14, `plan.md` §13): при наличии согласия запись
**сохраняется всегда**.

- **Локальный буфер** (`infrastructure/audio/file_audio_recording_store.dart`,
  таблица `audio_recordings`, схема v3): каждый чанк пишется в файл в приватном
  каталоге приложения; метаданные и offset загрузки — в SQLite. Это
  ограниченный кэш своих последних разговоров (`enforceRetention`, лимит N +
  `keep_until`), а не второй источник истины.
- **Онлайн**: те же байты уходят live по `WS /ws/calls/{id}/audio?leg=mixed`
  (`infrastructure/ws/ws_live_audio.dart`) для анализа в реальном времени.
- **Финал**: после завершения звонка запись загружается
  `POST /calls/{id}/audio` (`infrastructure/api/audio_ingest_api.dart`).
  Обрыв сети не теряет записанное: загрузка **докачиваемая**
  (`Content-Range: bytes start-end/total`, продолжение с серверного `offset`),
  при ошибке статус `pending` и повтор позже (`uploadPending`, в т.ч. на старте
  приложения через `recordingRetryProvider`).
- **Координатор** (`application/recording_service.dart`) стартует запись, когда
  звонок переходит в `recording` (после согласия), и завершает/грузит её на
  терминальном состоянии; ошибки аудио никогда не ломают звонок.
- **Ограничение**: полностью офлайн-звонок (сервер не видел `answered`) требует
  доработок backend (идемпотентное создание звонка и клиентская фиксация
  `recording_started_at`+согласия) — см. `plan.md` §13 и `TEAM_PLAN.md`.

## Договорённости и live-карточка (Этап 7)

После ответа и согласия звонок подключается к live-ленте backend по WebSocket —
`ws(s)://<host>/api/ws/calls/{call_id}` (`Authorization: Bearer <access_token>`,
пропущенные события доигрываются на подключении). Контракт — версионированный
конверт v1 (`domain/ws_event.dart`):

```json
{ "version": 1, "event": "partial_transcript", "call_id": "…", "payload": { … } }
```

| Событие | Что делает клиент |
|---|---|
| `analysis_started` | `markConsentResult(granted: true)` → `markAnalysisStarted()` (статус `analyzing`) |
| `partial_transcript` | добавляет сегмент (`speaker`, `text`, `start`, `end`) в транскрипт |
| `agreement_detected` | upsert карточки договорённости (повторный приход по `id` заменяет, не дублирует) |
| `call_ended` | переводит звонок в `completed`, отключает ленту |

- **Слои**: `WebSocketCallEvents` (`infrastructure/ws/`, за портом `CallEventsPort`)
  и `HttpAgreementApi` (`infrastructure/api/agreement_api.dart`, за портом
  `AgreementApi`) внедряются через DI (`callEventsProvider`, `agreementApiProvider`).
  Виджеты обращаются только к `CallController`.
- **Карточка** (`ui/screens/call_screen.dart`): последние строки транскрипта и
  карточки договорённостей с уверенностью, владельцем, сроком и цитатой;
  действия «Подтвердить» / «Отклонить» / «Изменить». Подтверждение создаёт задачу
  **только** на сервере (клиент ничего не создаёт сам). Правка — через
  `AgreementEditDialog` → `PATCH /agreements/{id}`.
- **Подтверждённая карточка не «замораживается»** (§12–14): у `confirmed`
  скрывается только «Подтвердить» (уже подтверждено), а «Отклонить» и «Изменить»
  остаются — серверный `PATCH` работает в любом статусе и переносит правку на
  задачу; `rejected` финальна, действий нет.
- **Без согласия** запись выключена, лента не подключается, и карточка предлагает
  «Добавить договорённость вручную» (`POST /calls/{id}/agreements`).
- **Устойчивость**: лента — best-effort; обрыв/неудача handshake не ломает звонок.
  Отключается на терминальном статусе, `clear()` и `dispose`.
- Live-лента подключается только когда есть `call_id` и `recordingEnabled`.

## Доски: личная и менеджера (Этап 8)

Правила группировки/сортировки/фильтрации — чистые функции в `domain/board.dart`
(без Flutter), поэтому виджеты тонкие, а логика покрыта юнит-тестами.

### Личная доска (`ui/screens/board_screen.dart`)

- **Секции** (`plan.md` §14): «Просроченные», «Сегодня», «Предстоящие»,
  «Без срока», «Выполненные», «Отменённые». Порядок — просрочки сверху, затем
  ближайшие дедлайны, затем приоритет; done/canceled в конце.
- **Действия** (тап по задаче → `ui/screens/task_actions_sheet.dart`): «Взять в
  работу», «Отметить выполненной», «Перенести срок», «Изменить приоритет»,
  «Отменить». В карточке показывается источник (`task.description` — цитата из
  звонка).
- **Offline-first**: действие применяется оптимистично к локальному кэшу и
  кладётся в `outbox` (`SyncOperation`, entity `task`, op `update`), затем
  запускается sync (`plan.md` §9). Без сети правка остаётся в очереди; при
  конфликте сервер авторитетен и перезапишет локальную запись. Правки одной
  задачи коалесцируются (`removeByEntity`), в операции идёт известная версия.
- **Связь со звонком/договорённостью**: показывается цитата источника; в
  действиях по задаче есть «К звонку-источнику» (`TaskItem.callId`) — открывает
  экран звонка со сводкой (Этап 9, история звонков).

### Доска менеджера (`ui/screens/manager_board_screen.dart`)

- Доступна только роли `manager` (иконка «Доска команды» в app bar личной
  доски); сервер повторно проверяет роль и принадлежность команде.
- **Данные не кэшируются локально** (AGENTS: телефон хранит только свои данные) —
  `ManagerController` держит их в памяти и перезапрашивает при обновлении.
  Клиенты — `/manager/team/tasks`, `/manager/team/stats`, `/manager/team/members`.
- **Вкладки**: «Задачи» (фильтры сотрудник/статус/приоритет/тип, сортировка —
  просрочки, затем ближайшие дедлайны), «Аналитика» (сводка из stats + разбивка
  по сотрудникам, когда сервер её отдаёт), «Сотрудники» (состав команды).
- Карточка задачи использует расширенный `ManagerTaskOut`: имя исполнителя,
  клиент/контакт и привязку к звонку, если сервер их вернул (поля
  необязательные — старый backend продолжает работать).
- Фильтры сотрудник/статус/приоритет/тип/срок уходят на сервер (`user_id`,
  `status`, `priority`, `task_type`, `due_before`); приоритет дополнительно
  сужается на клиенте, чтобы доска работала и со старым backend без фильтра по
  приоритету. Тип выбирается из значений, встречающихся в загруженных задачах
  (в API нет списка типов).

## Итог звонка, история, календарь и напоминания (Этап 9)

Контракт описан в `domain/schedule.dart`, порт — `ScheduleApi` в
`domain/ports.dart`, адаптер — `infrastructure/api/schedule_api.dart`, DI —
`providers.dart` (`scheduleApiProvider`, `taskActionsControllerProvider`).
Все записи во внешние системы — только после явного подтверждения; черновик
клиенту **не отправляется автоматически** (правило продукта).

- **Итог звонка** (`GET /calls/{id}/summary`, владелец): `CallController.loadSummary()`
  кладёт `CallSummary` в `CallState`; вызывается автоматически на терминальном
  статусе и по кнопке в live-карточке (`ui/screens/call_screen.dart`, блок
  «Сводка»: текст + счётчики договорённостей). Ошибка/офлайн — тихо, без потери UI.
- **Действия по задаче** (`ui/screens/task_actions_sheet.dart`), каждое через
  диалог подтверждения (`application/task_actions_controller.dart`):
  - «Добавить в календарь» → `POST /tasks/{id}/calendar`, показывается время события;
  - «Удалить из календаря» → `DELETE /tasks/{id}/calendar`; эндпоинта пока нет на
    backend (трек C) — 404/405 обрабатывается мягко («пока недоступно»), без падения;
  - «Черновик клиенту» → `POST /tasks/{id}/message-draft`, текст показывается в
    диалоге с кнопкой «Копировать» и пометкой «не отправляется автоматически»
    (Flutter `Clipboard`, без новых зависимостей);
  - «Скачать .ics» → `GET /tasks/{id}/calendar.ics`; исходный `text/calendar`
    показывается в диалоге и копируется через `Clipboard` (без новых зависимостей);
  - «Напоминания» → `ui/screens/reminders_sheet.dart`: список
    (`GET /tasks/{id}/reminders`) с отменой (`POST /reminders/{id}/cancel`) и
    добавлением пресетами (`POST /tasks/{id}/reminders`);
  - «К звонку-источнику» → экран звонка со сводкой, если у задачи есть `TaskItem.callId`.
    **Зависимость backend:** личная доска `TaskOut` (и sync) пока не отдают `call_id`,
    поэтому пункт появится после добавления `call_id` в `TaskOut`/схему задач (трек C);
    у `ManagerTaskOut` поле уже есть.
- **Порт `CallApi`** расширен: `calls()` (`GET /calls`) — история звонков владельца.
- **История звонков**: `ui/screens/call_history_screen.dart` (`callHistoryProvider`)
  — список звонков пользователя (контакт, направление, время, статус),
  тяга-обновление; тап открывает `ui/screens/call_detail_screen.dart`
  (`GET /calls/{id}` + `/calls/{id}/summary`). Открывается из app bar личной доски
  и из действия «К звонку-источнику».
- **Формат даты/времени**: `formatDateTime` в `ui/formats.dart` (локаль устройства).
- **Ещё не сделано** (не трек A): удаление события календаря (ждёт
  `DELETE /tasks/{id}/calendar` + `CalendarPort.delete_event()` — трек C, Mav);
  мобильный путь полностью офлайн-звонка (backend готов, PR #17: `POST /calls`
  с клиентским `id` и `POST /calls/{id}/recordings` — интеграция отложена).

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
При изменении OpenAPI контракта обновляйте модели и клиентов здесь. Формат
WS-событий (конверт v1: `partial_transcript`, `agreement_detected`,
`analysis_started`, `call_ended`) реализован в `domain/ws_event.dart` +
`infrastructure/ws/ws_call_events.dart`; соглашения/задачи — в
`infrastructure/api/agreement_api.dart`.
