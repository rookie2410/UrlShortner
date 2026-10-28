from functools import lru_cache
from pathlib import Path
from typing import Annotated
from pydantic import Field, field_validator
from urllib.parse import urlsplit
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPOSITORY_ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "ShortLink API"
    environment: str = "development"
    database_url: str = "postgresql+psycopg://shortlink:change-me@localhost:5432/shortlink"
    redis_url: str = "redis://localhost:6379/0"
    public_base_url: str = "http://localhost:8000"
    admin_api_token: str | None = None
    frontend_api_base_url: str = "http://localhost:8000/api/v1"
    allowed_frontend_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:5173"])
    redirect_cache_ttl_seconds: int = Field(default=300, ge=1, le=86400)
    max_url_length: int = Field(default=2048, ge=128, le=8192)
    create_rate_limit_count: int = Field(default=20, ge=1, le=10000)
    create_rate_limit_window_seconds: int = Field(default=60, ge=1, le=86400)
    redis_socket_timeout_seconds: float = Field(default=0.5, gt=0, le=10)
    click_stream_name: str = "shortlink:click-events"
    click_consumer_group: str = "shortlink-workers"
    click_dead_letter_stream: str = "shortlink:click-events:dead-letter"
    worker_consumer_name: str = "worker-1"
    worker_batch_size: int = Field(default=25, ge=1, le=500)
    worker_block_ms: int = Field(default=1000, ge=0, le=30000)
    worker_pending_idle_ms: int = Field(default=30000, ge=1000, le=3600000)
    worker_max_deliveries: int = Field(default=5, ge=1, le=100)
    worker_max_backoff_seconds: int = Field(default=300, ge=1, le=3600)
    log_level: str = "INFO"

    @field_validator("public_base_url", "frontend_api_base_url")
    @classmethod
    def validate_base_urls(cls, value: str) -> str:
        value = value.rstrip("/")
        try:
            parsed = urlsplit(value)
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("Base URL must be a valid absolute HTTP(S) URL.") from exc
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
            raise ValueError("Base URL must be a valid absolute HTTP(S) URL without credentials, query, or fragment.")
        return value

    @field_validator("allowed_frontend_origins", mode="before")
    @classmethod
    def parse_origins(cls, value):
        if isinstance(value, str):
            return [origin.strip().rstrip("/") for origin in value.split(",") if origin.strip()]
        return [str(origin).rstrip("/") for origin in value]


@lru_cache
def get_settings() -> Settings:
    return Settings()
