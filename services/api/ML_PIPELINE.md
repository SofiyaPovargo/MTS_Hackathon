# ML-пайплайн (соглашения в телефонных разговорах)

Документ описывает фактический ML-пайплайн проекта: целевую схему из
`plan.md` §12, production-конвейер (`src/app/ml/pipeline.py` + воркеры) и
research-слой. Обновлять при изменении ML-кода, схемы БД или событий.

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

Правила (`AGENTS.md`): обработка асинхронная (старт/upload отдаёт `call_id` и
статус, а не результат), запись возможна только после `answered` + согласия,
транскрипт хранится в таблице `transcripts` (не дублируется в `calls`), повторная
обработка того же аудио идемпотентна, аудио/транскрипты шифруются и имеют
ограниченный срок хранения.

## 2. Роли спикеров: каналы вместо диаризации

Запись VoIP приходит по каналам (по ноге на сторону). Роль известна из канала,
поэтому диаризация не нужна:

- **VoIP (каналы).** Каждая нога (`operator`, `client`) транскрибируется
  отдельно, фразы помечаются ролью канала и сортируются по времени.
  `Transcript.role_source = channel`.
- **mono/PSTN (смесь).** Один смешанный поток → ASR → pyannote → слияние
  «первый заговоривший = `operator`, второй = `client`».
  `Transcript.role_source = diarization`. Без диаризации — `unknown`.

`CallAudio` (`stt/pipeline.py`) — декодированные 8 кГц int16 PCM ноги/смесь;
`decode_phone_audio` сам решает: стерео → ноги, mono → смесь. `role_source`
хранится в `transcripts.role_source` как поле-аудит.

## 3. Production-конвейер

Оркестратор — `src/app/ml/pipeline.py`.

### worker-asr — `process_asr(call_id)`

1. Загрузить запись из MinIO/S3 (`call_audio.storage_url`, а при наличии
   `call_audio.channel_urls` — раздельные ноги).
2. `TranscribePipeline.transcribe_audio` → `Transcript` с ролями.
3. Сохранить транскрипт в `transcripts` (сегменты JSONB, `full_text`,
   `role_source`, `status=done`).
4. Опубликовать `partial_transcript` по каждому сегменту.
5. Передать задачу в `worker-ai` (очередь `ai`).

### worker-ai — `run_llm_extraction(call_id)`

1. Прочитать транскрипт из БД.
2. `ExtractionService.extract_pair` → `(raw, validated)`: сырой вывод LLM и его
   провалидированная копия (валидация не мутирует raw).
3. `AgreementService.create_from_commitment` → предложенные `agreements`; сырой и
   валидированный вывод — в `agreement_extractions`, правки пользователя — в
   `agreement_edits` (раздельно, по AGENTS).
4. Опубликовать `agreement_detected` по каждой договорённости.

### Идемпотентность

- ASR: если по `call_id` уже есть `transcripts.status == "done"` — no-op,
  транскрипт переиспользуется.
- Extraction: если по `call_id` уже есть `agreement_extractions` — no-op, LLM
  повторно не вызывается.

### Триггер

- `POST /calls/{call_id}/analyze` (owner-only) → очередь `asr`; отвечает
  `202 {call_id, status:"queued"}`.
- Дополнительно `CallSessionService` сам ставит задачу в очередь по событию
  `ended`, если запись уже загружена в S3 (`storage_url` начинается с `s3://`).

## 4. Извлечение и валидация

- `extraction/llm.py::InstructorLLMExtractor` — OpenAI-совместимый API +
  Instructor, структурный ответ `ExtractionResult` (список `Commitment`).
  Смена провайдера — смена `LLM_BASE_URL`. `PROMPT_VERSION` пишется в аудит.
- `extraction/validation.py` — rule-based проверки: `source_quote` встречается в
  транскрипте, таймкоды внутри длительности, срок обязателен для
  `deadline|payment|meeting`, `owner=unknown` → флаг. Правила статуса — в
  `domain/rules.py`: неоднозначность (`AmbiguityFlags`) важнее уверенности;
  ниже порога `CONFIDENCE_THRESHOLD` → `requires_review`; неоднозначно →
  `needs_clarification`. Относительные даты резолвит `domain/dates.py` по
  `conversation_date` и таймзоне пользователя.

## 5. Схемы и контракты

- `stt/schemas.py` — `TranscriptSegment(speaker ∈ operator|client|unknown,
  text, start, end)`, `Transcript(conversation_id, segments, role_source)`,
  `RoleSource(channel|diarization|unknown)`.
- `domain/commitment.py::Commitment` — валидированная форма: `type`, `title`,
  `object`, `owner`, `owner_user_id`, `due_date`, `due_time`, `amount`/`currency`,
  `source_quote`, `audio_start`/`audio_end`, `confidence`, `ambiguity`, `status`
  (канонические `AgreementStatus`: `detected|requires_review|
  needs_clarification|confirmed|rejected`).
- `asr/ports.py` — `ASRPort.transcribe(pcm)`, `TextPhrase`; `SAMPLE_RATE=8000`,
  `CHUNK_SAMPLES=2400` (300 мс), `CHUNK_BYTES=4800`.
- `diarization/ports.py` — `DiarizationPort.diarize(path)`.

### Протокол T-one (`asr/tone.py`)

Сервер шлёт `{"event":"ready"}` → клиент отправляет чанк 8 кГц int16 PCM;
распознанная фраза приходит как `{"event":"transcript","phrase":{text,
start_time, end_time}}`. Финализация: клиент шлёт пустые байты, сервер добивает
буфер, но соединение держит открытым — поэтому клиент завершается по таймауту
тишины `FINALIZE_TIMEOUT = 30 с`, а не по закрытию сокета.

## 6. Research-слой и данные (`services/api/research/`)

Офлайн-этап для датасета и оценки качества (не в проде). `research/` — отдельный
uv-проект, исключён из ruff/mypy.

- `schemas.py` — research-схемы (зеркало домена; `CommitmentStatus` приведён к
  каноническим статусам AGENTS).
- `generate_data.py` — 14 gold-кейсов `data/gold/<id>.json` + `manifest.json`.
- `synth_tts.py`, `synthesize_calls.py` — Silero TTS v4_ru + имитация
  телефонного канала (band-limit 100–3400 Гц, 8 кГц mono, G.711 mu-law).
- `01_data_synth.ipynb`, `02_asr_tone.ipynb`, `03_extraction_eval.ipynb` —
  синтез, прогон T-one, оценка извлечения (Recall/Precision).

## 7. Конфигурация

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `ASR_WS_URL` | `ws://localhost:8080/api/ws` | адрес T-one WebSocket |
| `HF_TOKEN` | — | read-only токен Hugging Face (gated pyannote) |
| `DATA_DIR` | `data` | `data/audio`, `data/transcripts` для STT CLI |
| `CONFIDENCE_THRESHOLD` | `0.8` | ниже порога договорённость → `requires_review` |
| `LLM_BASE_URL` | — | OpenAI-совместимый endpoint (Ollama/self-host) |
| `LLM_MODEL` | — | модель; без обоих параметров extraction выключен |
| `LLM_API_KEY` | — | ключ (для локального Ollama не нужен) |

T-one идёт в отдельном образе: `tinkoffcreditsystems/t-one:0.1.0`, профиль
`ml`, порт 8080 (`docker compose --profile ml up -d asr`). Тяжёлые ML-зависимости
(`numpy`, `soundfile`, `soxr`, `pyannote-audio`, `torch`, `instructor`, `openai`) —
в optional-группе `ml` (`uv sync --extra ml`); образ API остаётся лёгким.
Внутри контейнеров адрес берётся по имени сервиса, не `localhost`.

## 8. Запуск и проверка

```bash
cd services/api
uv sync --extra ml                              # ML-зависимости и тесты
docker compose --profile ml up -d asr           # T-one ASR (из корня репо)

# распознать звонок: data/audio/<id>.wav → data/transcripts/<id>.json
uv run python -m app.ml.stt <id> --audio-dir data/audio --out-dir data/transcripts

uv run pytest tests/ml                          # ASR, роли, валидация
uv run pytest tests/integration/test_ml_pipeline.py   # конвейер в БД (нужны postgres+redis)
```

Флаги CLI: `--ws-url`, `--no-diarization`, `--audio-dir`, `--out-dir`.

### Тесты

- `tests/ml/asr/test_tone_client.py` — протокол T-one против fake WS-сервера.
- `tests/ml/stt/test_pipeline.py` — слияние с диаризацией, карта ролей, ресемплинг.
- `tests/ml/stt/test_channels.py` — роли по каналам, фоллбек на диаризацию,
  `unknown` без диаризации, стерео/mono декодирование, `role_source`.
- `tests/ml/extraction/test_extraction.py` — валидатор, сервис и `extract_pair`.
- `tests/integration/test_ml_pipeline.py` — каналы → транскрипт в БД → agreements
  → события, идемпотентность, `POST /calls/{id}/analyze`.

## 9. Безопасность и приватность

- Аудио и транскрипты — персональные и коммерческие данные: шифровать,
  ограничивать доступ, ограничивать срок хранения аудио
  (`AUDIO_RETENTION_DAYS`).
- Промпты и ответы LLM логировать только с редактированием PII и с согласия
  пользователя.
- Не коммитить секреты, `HF_TOKEN`, аудиофайлы и реальные транскрипты
  (research-аудио в `.gitignore`).
- Запись возможна только после `answered` + согласия; правило не обходится в
  тестах и демо.
