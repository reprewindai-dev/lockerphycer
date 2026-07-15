"""Runtime settings with secure production defaults."""

from functools import lru_cache
from pydantic import Field
try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:  # pragma: no cover - pydantic v1 fallback
    from pydantic import BaseSettings
    SettingsConfigDict = dict


class Settings(BaseSettings):
    APP_NAME: str = "Locker Phycer"
    VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    FRONTEND_URL: str = "http://localhost:8000"
    API_URL: str = "http://localhost:8000"
    ADMIN_EMAIL: str = "admin@lockerphycer.local"

    SECRET_KEY: str = Field(default="change-me-only-for-local-dev-32-bytes-minimum", min_length=32)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    PASSWORD_MIN_LENGTH: int = 8
    MAX_FAILED_LOGIN_ATTEMPTS: int = 10
    ACCOUNT_LOCKOUT_DURATION_MINUTES: int = 30

    DATABASE_URL: str = "sqlite+aiosqlite:///./lockerphycer.db"
    REDIS_URL: str = "redis://localhost:6379/0"

    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    OPENAI_API_KEY: str = ""
    HUGGINGFACE_API_KEY: str = ""

    SENTRY_DSN: str = ""
    SENTRY_ENVIRONMENT: str = "production"
    OTEL_SERVICE_NAME: str = "lockerphycer-api"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
