# Что осталось сделать — по людям

Статус на **2026-10-14**. Источники: `PROGRESS.md`, `TEAM_PLAN.md`, `plan.md`.
Гейты: mobile — `cd apps/mobile && flutter analyze && flutter test` (сейчас **167**);
backend — `cd services/api && uv run ruff check . && uv run mypy . && uv run pytest`.

Актуально: **PR #16** (Этап 6 + Этап 9 mobile) и **PR #17** (офлайн-звонок, трек C)
влиты в `development`; **PR #18** — остаток Этапа 9 (история звонков, `.ics`,
напоминания). Трек B (ML) закрыт.

---

## Xivalor — мобильное приложение (трек A)

Этапы 3–9 (UI) закрыты, критический путь демо работает на Dart-уровне. Осталось:

- [ ] **Полностью офлайн-звонок (клиент)** — backend **готов** (PR #17):
      `POST /calls` принимает клиентский `id`/`started_at`/`record_consent`
      идемпотентно, `POST /calls/{id}/recordings` фиксирует запись и согласие.
      Нужно: локальный UUID на звонок, очередь регистрации (буфер pending-звонков),
      flush при появлении сети, затем догрузка аудио. **Согласие участника — только
      из реального флоу** (`markConsentResult`), без авто-гранта (правило продукта).
- [ ] **Нативный VoIP** *(блокер: нет Android SDK/Java/Xcode в среде)*:
      CallKit/PushKit (iOS), Telecom/ConnectionService (Android), реальные входящие,
      реальная запись медиапотока за `VoiceCallProvider.openMediaStream()` и
      проигрывание notice. Сейчас — `MockVoiceCallProvider`.
- [ ] **«К звонку-источнику» на личной доске** — фича готова, но ждёт `call_id`
      в `TaskOut`/sync (трек C, Mav; у `ManagerTaskOut` уже есть).
- [ ] **Удаление события календаря** — UI готов, мягкий fallback 404/405 стоит;
      включится после `DELETE /tasks/{id}/calendar` (трек C, Mav).
- [ ] *(опц.)* Системный share sheet для `.ics`/черновика (`share_plus`) — сейчас
      копирование через `Clipboard` (без новых зависимостей).
- [ ] *(опц.)* FCM/APNs-клиент для напоминаний и `analysis_started`.
- [ ] Прогон на эмуляторе/устройстве (`flutter run`) — нужна машина с Android SDK/Xcode.

## Mav — backend и интеграции (трек C)

- [ ] **Удаление календарных договорённостей** (`plan.md` §12–14):
      `CalendarPort.delete_event()` + `DELETE /tasks/{id}/calendar`, хранить
      `event_id` (сейчас только в `audit_log`), писать `audit_log`; распознавание
      **отмены/переноса** в разговоре (LLM + сопоставление с существующей
      договорённостью) → предложение (внешняя запись — **только после подтверждения**).
- [ ] **`call_id` в `TaskOut`/sync** (личная доска) — разблокирует «К звонку-источнику»
      в мобильном приложении (у `ManagerTaskOut` уже есть).
- [ ] **Реальные адаптеры** `CalendarPort`/`RemindersPort` (OAuth Google/Microsoft)
      вместо `Null*`; постановка `send_reminder` в очередь + воркер
      `worker-notifications` (FCM/APNs).
- [ ] **Боевой voice-провайдер Exolve**: прод-режим (`EXOLVE_API_KEY`,
      `PUBLIC_BASE_URL`), DTMF-согласие, сквозная проверка
      notice → запись → ASR на стенде.
- [ ] *(опц.)* sync-сущность `call`/`recording` (сейчас клиент использует выделенные
      вызовы §13); подъём на VPS (`docker-compose.prod.yml`, `docs/deploy.md` готовы)
      — нужен стенд/DNS/TLS.

## Sofia — ML (трек B) — ✅ закрыт

- [x] LLM (Ollama `qwen2.5:7b`), live-ASR/VAD (T-one + Silero), детерминированные
      даты, приватность: удаление данных, retention-пурж, redaction.
- [ ] *(вне трека B, опц.)* напоминания-воркер `send_reminder`; резюме через LLM
      вместо детерминированного `summary.py`.

## Тестирование и демо (вся команда)

- [ ] Интеграционные тесты на контейнерах: `docker compose up -d && uv run pytest`
      *(в текущей среде Docker не запускался)*.
- [ ] Сценарии: Wi-Fi / 4G / обрыв WS / офлайн-синк; «нет записи без согласия».
- [ ] Сквозное демо: входящий → consent → задача на доске менеджера **< 3 мин**
      (нужен эмулятор/устройство).

---

## Блокеры среды

- Нет Android SDK/Java/Xcode → нативная сборка, VoIP и device-тесты невозможны;
  реализация на Dart-уровне + порты/моки.
- Сабагент `ml-reviewer` недоступен в этой среде — ревью ML/privacy/интеграций
  выполнено вручную.
