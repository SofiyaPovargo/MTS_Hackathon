# ML-пайплайн (соглашения в телефонных разговорах)

Документ описывает фактический ML-пайплайн проекта: целевую схему из
`plan.md` §12, реализованный research-слой (`src/app/ml/`, задел Этапа 6) и
границу между research и production. Обновлять при изменении ML-кода.

## 1. Целевая схема (plan.md §12)

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

Порядок и правила (`AGENTS.md`): обработка асинхронная (старт/upload отдаёт
`conversation_id` и статус, а не результат), звонок должен быть `answered` и с
согласием, транскрипт хранится в таблице `transcripts` (не дублируется в
`calls`), повторная обработка того же аудио идемпотентна, аудио/транскрипты
шифруются и имеют ограниченный срок хранения.

## 2. Что уже реализовано — research-слой `src/app/ml/`

Это рабочий STT-конвейер «аудио файл → транскрипт с ролями» на русском
телефонном аудио. Не запитан в воркеры, запускается CLI вручную.

| Шаг | Модуль | Что делает |
|---|---|---|
| Загрузка/ресемплинг | `stt/pipeline.py::read_phone_pcm` | wav → mono → 8 кГц через `soxr` → int16 PCM (вход T-one) |
| ASR (streaming) | `asr/tone.py::ToneASRClient` | WebSocket `/api/ws` к T-one, чанки 8 кГц int16, фразы с таймкодами |
| ASR-контракт | `asr/ports.py` | `ASRPort.transcribe(pcm)`, `TextPhrase(text, start_time, end_time)`; `SAMPLE_RATE=8000`, `CHUNK_SAMPLES=2400` (300 мс), `CHUNK_BYTES=4800` |
| Диаризация | `diarization/pyannote.py::PyannoteDiarizer` | `pyannote/speaker-diarization-3.1` (gated, нужен `HF_TOKEN`), CPU → `SpeakerSegment(speaker,start,end)` |
| Диаризация-контракт | `diarization/ports.py` | `DiarizationPort.diarize(path)` |
| Слияние + роли | `stt/pipeline.py` | фраза → спикер по максимальному пересечению (`assign_speaker`), `build_role_map`: первый заговоривший = `operator`, второй = `client`, остальные = `unknown` |
| Схемы транскрипта | `stt/schemas.py` | `TranscriptSegment(speaker ∈ operator\|client\|unknown, text, start, end)`, `Transcript(conversation_id, segments)` |
| Оркестрация | `stt/pipeline.py::TranscribePipeline` | audio → ASR → (опц.) диаризация → merge → `Transcript` |
| Сохранение | `stt/pipeline.py::save_transcript` | `data/transcripts/<id>.json` (UTF-8) |
| CLI | `stt/__main__.py` | `python -m app.ml.stt <id>` |

### Протокол T-one (`asr/tone.py`)

Сервер шлёт `{"event":"ready"}` → клиент отправляет чанк 8 кГц int16 PCM;
распознанная фраза приходит как `{"event":"transcript","phrase":{text,
start_time, end_time}}`. Финализация: клиент шлёт пустые байты, сервер
добивает буфер, но соединение держит открытым — поэтому клиент завершается
по таймауту тишины `FINALIZE_TIMEOUT = 30 с`, а не по закрытию сокета.

### Контракт извлечения (домен, ещё не подключён к ML)

- `domain/commitment.py::Commitment` — валидированная форма договорённости:
  `type`, `title`, `object`, `owner`, `owner_user_id`, `due_date`, `due_time`,
  `amount`/`currency`, `source_quote`, `audio_start`/`audio_end`, `confidence`,
  `ambiguity`, `status`. Плюс проверки: `audio_end ≥ audio_start`, `due_time`
  требует `due_date`, `amount` требует `currency`.
- `domain/rules.py` — `AmbiguityFlags` (vague_deadline, missing_due_date,
  missing_amount, unknown_owner, contradictory_quote), `resolve_agreement_status`
  (неоднозначность важнее уверенности), порог `DEFAULT_CONFIDENCE_THRESHOLD=0.8`,
  `can_create_task` (задача только из `confirmed`).
- `domain/dates.py` — детерминированный разбор относительных дат по-русски
  (`завтра`/`послезавтра`/`сегодня`, день недели, `до конца месяца`,
  `на следующей неделе`, `через N дней/недель`, ISO и числовые даты). Даты из
  LLM не доверяются как есть: флаг `ambiguous=True` уводит в
  `needs_clarification`, выдумывать сроки запрещено.

## 3. Research-данные и синтез звонков (`services/api/research/`)

Офлайн-этап для датасета и оценки качества (не в проде).

- `schemas.py` — research-схемы: `Commitment`, `ConversationContext`,
  `ExtractionResult`, `ExpectedCommitment`, `GoldCase`.
- `generate_data.py` — 14 gold-кейсов `data/gold/<id>.json` + `manifest.json`.
  Категории: `explicit_deadline`, `meeting_with_time`, `payment_with_date`,
  `ambiguous`, `contradictory_dates`, `no_commitment`, `follow_up`,
  `payment_amount`, `multiple_commitments`, `open_question`,
  `proposal_not_confirmed`. Ожидаются и негативные кейсы (нет договорённости),
  и спорные (`needs_clarification`: «сделаем быстро», противоречивые даты,
  предложение без подтверждения, сумма без срока).
- `synth_tts.py` — синтез Silero TTS v4_ru (`operator`=xenia, `client`=aidar,
  48 кГц).
- `synthesize_calls.py` — склейка реплик с паузами → `*_orig.wav`, имитация
  телефонного канала через ffmpeg (band-limit 100–3400 Гц, 8 кГц mono,
  G.711 mu-law) → `<id>.wav`; после синтеза таймкоды диалога и договорённостей
  пересчитываются по реальным длительностям.
- `01_data_synth.ipynb`, `02_asr_tone.ipynb` — эксперименты синтеза и прогона
  T-one.

## 4. Чего не хватает до продакшена (Этап 6)

Направление — от файла к живому потоку и к извлечению в БД.

- **VAD / chunking** из media stream (сейчас чанкинг фиксированный 300 мс при
  отправке готового файла).
- **Audio Decoder** из media stream и загрузка аудио в S3/MinIO.
- **Воркеры**: `worker.py` сейчас заглушки (`process_asr`, `process_ai`,
  `process_*` возвращают `implemented=False`); очереди `asr|ai|notifications`
  подняты, но ML-код в них не вызван.
- **LLM extraction**: промпт и парсинг ответа, хранение сырого и
  валидированного вывода в `agreement_extractions` (сырой LLM-вывод, валидный
  вывод и правки пользователя — раздельно). Формат вывода уже задан
  `domain/commitment.py`.
- **Транскрипты в БД**: сейчас JSON на диске (`data/transcripts/`), нужна
  запись в таблицу `transcripts`.
- **События / WebSocket**: хаб `services/events.py` готов (Redis
  `events:call:{id}`, replay для late joiners), но эмиссия `partial_transcript`,
  `agreement_detected`, `analysis_started`, `call_ended` не подключена.
- **Идемпотентность** повторной обработки одного и того же аудио.
- **Open decision**: выбор LLM (предпочтителен самохостинг ради приватности) —
  блокирует LLM-часть.

## 5. Конфигурация

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `ASR_WS_URL` | `ws://localhost:8080/api/ws` | адрес T-one WebSocket |
| `HF_TOKEN` | — | read-only токен Hugging Face (gated pyannote) |
| `DATA_DIR` | `data` | `data/audio`, `data/transcripts` для STT CLI |
| `CONFIDENCE_THRESHOLD` | `0.8` | ниже порога договорённость → `requires_review` |

T-one идёт в отдельном образе: `tinkoffcreditsystems/t-one:0.1.0`, профиль
`ml`, порт 8080 (`docker compose --profile ml up -d asr`). Тяжёлые ML-зависимости
(`numpy`, `soundfile`, `soxr`, `pyannote-audio`, `torch`) — в optional-группе
`ml` (`uv sync --extra ml`), чтобы образ API оставался лёгким. Внутри
контейнеров адрес берётся по имени сервиса, не `localhost`.

## 6. Запуск и проверка

```bash
cd services/api
uv sync --extra ml                              # ML-зависимости и тесты
docker compose --profile ml up -d asr           # T-one ASR (из корня репо)

# распознать звонок: data/audio/<id>.wav → data/transcripts/<id>.json
uv run python -m app.ml.stt <id> --audio-dir data/audio --out-dir data/transcripts

uv run pytest tests/ml                          # тесты протокола и слияния
```

Флаги CLI: `--ws-url` (адрес T-one), `--no-diarization` (без pyannote, все
спикеры `unknown`; иначе нужен `HF_TOKEN`), `--audio-dir`, `--out-dir`.

### Тесты (`tests/ml/`)

- `asr/test_tone_client.py` — протокол T-one против fake WS-сервера
  (`ready → bytes → transcript → finalize`), порядок и таймкоды фраз.
- `stt/test_pipeline.py` — привязка спикера по максимальному пересечению, карта
  ролей (`operator`=первый, `client`=второй, остальные `unknown`), `unknown`
  без диаризации, ресемплинг в 8 кГц.

## 7. Безопасность и приватность

- Аудио и транскрипты — персональные и коммерческие данные: шифровать,
  ограничивать доступ, ограничивать срок хранения аудио.
- Промпты и ответы LLM логировать только с редактированием PII и с согласия
  пользователя.
- Не коммитить секреты, `HF_TOKEN`, аудиофайлы и реальные транскрипты
  (research-аудио в `.gitignore`).
- Запись возможна только после `answered` + согласия; правило не обходится в
  тестах и демо.
