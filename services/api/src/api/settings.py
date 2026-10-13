"""Backend application settings (pydantic-settings)."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _repo_root() -> Path:
    """Корень репозитория (там docker-compose.yml и общий .env)."""
    start = Path(__file__).resolve().parent
    for candidate in start.parents:
        if (candidate / "docker-compose.yml").is_file():
            return candidate
    return start


_REPO_ROOT = _repo_root()
_ENV_FILES = [Path.cwd() / ".env", _REPO_ROOT / ".env"]


class Settings(BaseSettings):
    """Environment-driven backend configuration.

    Настройки читаются из переменных окружения и .env (CWD + корень репозитория).
    """

    model_config = SettingsConfigDict(
        env_file=[str(p) for p in _ENV_FILES if p.exists()],
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "MTS_Hackathon API"

    # Адрес WebSocket-эндпоинта T-one (streaming ASR).
    # На Mac поднимается через docker-compose и шарится команде по Tailscale.
    asr_ws_url: str = "ws://sofiya-mac:8080/api/ws"

    # Read-only токен Hugging Face для gated-моделей pyannote (диаризация).
    hf_token: str | None = None

    data_dir: Path = Path("data")


settings = Settings()
