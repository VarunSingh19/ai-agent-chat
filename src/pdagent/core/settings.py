"""Application settings loaded exclusively via pydantic-settings (Rules.md §4 & §7)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated runtime configuration for pdagent.

    All environment variables use the PDAGENT_ prefix (Rules.md §4).
    Startup fails fast with a clear message if required URLs are missing or blank.
    """

    model_config = SettingsConfigDict(
        env_prefix="PDAGENT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    database_url: str
    migrator_database_url: str = ""
    redis_url: str
    jwks_url: str = ""
    token_issuer: str = Field(default="https://auth.propertydek.example.com")
    token_audience: str = Field(default="pdagent")
    pdapi_base_url: str = "https://api.propertydek.example.com"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    sms_webhook_secret: str = Field(default="test-sms-webhook-secret-do-not-use-in-prod")
    otel_exporter_otlp_endpoint: str = ""
    service_name: str = "pdagent"
    environment: Literal["development", "test", "staging", "production"] = "production"
    db_pool_size: int = 10
    db_max_overflow: int = 10
    readiness_timeout_s: float = 2.0
    global_daily_cap_usd: float = 250.0
    user_daily_cap_usd: float = 2.50

    @field_validator("database_url", "redis_url")
    @classmethod
    def _require_non_blank(cls, value: str, info: object) -> str:
        cleaned = value.strip()
        if not cleaned:
            msg = f"Required setting {getattr(info, 'field_name', 'setting')} must not be empty"
            raise ValueError(msg)
        return cleaned

    @field_validator("migrator_database_url", mode="after")
    @classmethod
    def _default_migrator_url(cls, value: str) -> str:
        return value.strip()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached singleton Settings instance."""
    return Settings()
