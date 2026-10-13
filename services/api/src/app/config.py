"""Application configuration.

Every host and credential comes from the environment. The same variables point to
service names inside docker compose (``postgres``, ``redis``, ``minio``) and to
``localhost`` when the code runs on the host (tests, debugging).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = Field(default="local", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    api_base_path: str = Field(default="/api", alias="API_BASE_PATH")
    cors_origins: list[str] = Field(default_factory=list, alias="API_CORS_ORIGINS")

    database_url: str = Field(
        default="postgresql+asyncpg://app:app@localhost:5432/agreements", alias="DATABASE_URL"
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    s3_endpoint: str = Field(default="http://localhost:9000", alias="S3_ENDPOINT")
    s3_access_key: str = Field(default="minio", alias="S3_ACCESS_KEY")
    s3_secret_key: str = Field(default="minio123", alias="S3_SECRET_KEY")
    s3_bucket: str = Field(default="audio", alias="S3_BUCKET")
    audio_retention_days: int = Field(default=30, alias="AUDIO_RETENTION_DAYS")
    # Client audio upload cap; the mobile client uploads a recorded call file.
    max_audio_upload_mb: int = Field(default=64, alias="MAX_AUDIO_UPLOAD_MB")

    jwt_secret: str = Field(default="dev-only-change-me", alias="JWT_SECRET")
    jwt_algorithm: str = "HS256"
    access_token_ttl_sec: int = Field(default=900, alias="ACCESS_TOKEN_TTL_SEC")
    refresh_token_ttl_sec: int = Field(default=2_592_000, alias="REFRESH_TOKEN_TTL_SEC")

    otp_ttl_sec: int = Field(default=300, alias="OTP_TTL_SEC")
    dev_otp: str | None = Field(default=None, alias="DEV_OTP")

    # Product rules that must be configurable, never hardcoded in business logic.
    confidence_threshold: float = Field(default=0.8, alias="CONFIDENCE_THRESHOLD")

    voice_provider: str = Field(default="mock", alias="VOICE_PROVIDER")
    voice_webhook_secret: str = Field(default="dev-voice-secret", alias="VOICE_WEBHOOK_SECRET")
    consent_mode: str = Field(
        default="notice",
        alias="CONSENT_MODE",
        description="notice | dtmf | sms_link — how the counterparty consents",
    )

    # Outbound integrations. ``ics``/``local``/``draft`` are the in-app
    # artifacts; real adapters (calendar, reminders, messaging) are add-ons.
    calendar_provider: str = Field(default="ics", alias="CALENDAR_PROVIDER")
    reminders_provider: str = Field(default="local", alias="REMINDERS_PROVIDER")
    messaging_provider: str = Field(default="draft", alias="MESSAGING_PROVIDER")

    # МТС Exolve (plan.md §11.1). Empty credentials keep the mock path usable.
    exolve_api_base_url: str = Field(default="https://api.exolve.ru", alias="EXOLVE_API_BASE_URL")
    exolve_api_key: str = Field(default="", alias="EXOLVE_API_KEY")
    exolve_sip_resource_id: int = Field(default=0, alias="EXOLVE_SIP_RESOURCE_ID")
    exolve_consent_notice_file_id: str = Field(default="", alias="EXOLVE_CONSENT_NOTICE_FILE_ID")
    # Inbound routing: which app user receives a call that arrived on a given SIP
    # resource, and the SIP URI the app leg registers on. Entries
    # ``sip_id=phone:sip_uri`` separated by commas (multi-user).
    exolve_sip_routes: str = Field(default="", alias="EXOLVE_SIP_ROUTES")
    # Public base URL used for provider callbacks (``event_URL``): it must be
    # reachable by Exolve, so it is configuration, not derived from the request.
    public_base_url: str = Field(default="http://localhost:8000", alias="PUBLIC_BASE_URL")
    # Exolve has no server-side media stream: the mobile client uploads the SDK's
    # mixed call audio to the ingest endpoint for the ML pipeline. The client
    # posts the raw audio to ``POST {MEDIA_INGEST_URL}/calls/{call_id}/audio``.
    media_ingest_url: str = Field(default="http://localhost:8000/api", alias="MEDIA_INGEST_URL")

    # --- ML pipeline (optional, Stage 6 research) ---
    # T-one streaming ASR server (WebSocket). The compose `asr` service
    # (profile `ml`) serves it on http://localhost:8080; on the research Mac
    # it is shared via Tailscale (set ASR_WS_URL accordingly).
    asr_ws_url: str = Field(default="ws://localhost:8080/api/ws", alias="ASR_WS_URL")
    # Read-only Hugging Face token for gated pyannote diarization models.
    hf_token: str | None = Field(default=None, alias="HF_TOKEN")
    # Data directory for the STT CLI (data/audio, data/transcripts).
    data_dir: Path = Field(default=Path("data"), alias="DATA_DIR")

    # --- LLM extraction (optional) ---
    # OpenAI-compatible API for commitment extraction. Local default: Ollama.
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_base_url: str = Field(default="", alias="LLM_BASE_URL")
    llm_model: str = Field(default="", alias="LLM_MODEL")

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_base_url and self.llm_model)


@lru_cache
def get_settings() -> Settings:
    return Settings()
