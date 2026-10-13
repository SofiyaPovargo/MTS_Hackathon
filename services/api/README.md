# Backend API (services/api)

FastAPI-бэкенд MTS_Hackathon: `audio -> ASR (T-one) -> диаризация (pyannote) -> транскрипт`.

Стек: Python 3.13, uv, FastAPI, Pydantic v2, async I/O.

## Стек локально

```bash
docker compose up -d          # БД (Postgres 16) + ASR (T-one streaming, порт 8080)
```

- `db` — общая Postgres, доступна команде по Tailscale (`sofiya-mac`).
- `asr` — T-one streaming ASR (русская телефония, 8 кГц), WebSocket `/api/ws`.

ASR можно звать напрямую с имени в tailnet (`ws://sofiya-mac:8080/api/ws`).

## Зависимости

```bash
uv sync               # основные (API, ASR-клиент)
uv sync --group ml    # + pyannote/torch для диаризации
```

## STT-пайплайн

Распознать звонок и сохранить транскрипт `data/transcripts/<id>.json`:

```bash
uv run python -m api.ml.stt <id> --audio-dir data/audio --out-dir data/transcripts
```

Флаги:
- `--ws-url` — адрес T-one (по умолчанию `ws://sofiya-mac:8080/api/ws`, из `ASR_WS_URL`).
- `--no-diarization` — пропустить pyannote, все спикеры = `unknown`.
- Без `--no-diarization` нужен `HF_TOKEN` в `.env` (read-only).

Структура ML-слоя (`src/api/ml/`):

```
asr/
  ports.py     # ASRPort, TextPhrase
  tone.py      # ToneASRClient (WebSocket /api/ws, 8кГц int16 PCM)
diarization/
  ports.py     # DiarizationPort, SpeakerSegment
  pyannote.py  # PyannoteDiarizer (gated speaker-diarization-3.1)
stt/
  schemas.py   # TranscriptSegment, Transcript
  pipeline.py  # загрузка аудио, слияние фраз со спикерами, роли operator/client
  __main__.py  # CLI python -m api.ml.stt <id>
```

## Настройки

`src/api/settings.py` (pydantic-settings, источник — env + `.env`):

| Vars | Описание |
|---|---|
| `ASR_WS_URL` | WebSocket T-one (по умолчанию `ws://sofiya-mac:8080/api/ws`) |
| `HF_TOKEN` | Read-only токен Hugging Face (диаризация) |
| `DATA_DIR` | Каталог данных (`data/audio`, `data/transcripts`) |

## Проверки

```bash
uv run ruff check .
uv run mypy src tests
uv run pytest
```

## Примечание по T-one

Модель уже внутри образа `tinkoffcreditsystems/t-one:0.1.0` (не качается отдельно),
работает на CPU. Сервер после финализации не закрывает соединение — клиент
`ToneASRClient` завершает работу по таймауту тишины (`FINALIZE_TIMEOUT`).