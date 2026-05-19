"""
Application Settings and Configuration
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List, Optional
import os
from datetime import datetime


class Settings(BaseSettings):
    """Application settings"""
    
    # Application
    APP_NAME: str = Field(default="Veklom Sovereign AI Hub", env="APP_NAME")
    VERSION: str = Field(default="1.0.0", env="VERSION")
    ENVIRONMENT: str = Field(default="development", env="ENVIRONMENT")
    DEBUG: bool = Field(default=True, env="DEBUG")
    
    # Security
    SECRET_KEY: str = Field(default="veklom-dev-secret-key-change-in-production", env="SECRET_KEY")
    AI_CITIZENSHIP_SECRET: str = Field(default="veklom-ai-citizenship-dev", env="AI_CITIZENSHIP_SECRET")
    ENCRYPTION_KEY: str = Field(default="veklom-encryption-dev-key-32chars!", env="ENCRYPTION_KEY")
    ADMIN_EMAIL: str = Field(default="reprewindai@gmail.com", env="ADMIN_EMAIL")
    
    # Database
    DATABASE_URL: str = Field(default="sqlite+aiosqlite:///./veklom.db", env="DATABASE_URL")
    
    # Redis
    REDIS_URL: str = Field(default="redis://localhost:6379/0", env="REDIS_URL")
    CELERY_BROKER_URL: str = Field(default="", env="CELERY_BROKER_URL")
    CELERY_RESULT_BACKEND: str = Field(default="", env="CELERY_RESULT_BACKEND")
    
    # URLs
    FRONTEND_URL: str = Field(default="http://localhost:3000", env="FRONTEND_URL")
    API_URL: str = Field(default="http://localhost:8000", env="API_URL")
    
    # AI Services
    OPENAI_API_KEY: Optional[str] = Field(default=None, env="OPENAI_API_KEY")
    HUGGINGFACE_API_KEY: Optional[str] = Field(default=None, env="HUGGINGFACE_API_KEY")
    
    # Monitoring
    GRAFANA_PASSWORD: Optional[str] = Field(default=None, env="GRAFANA_PASSWORD")
    SENTRY_DSN: Optional[str] = Field(default=None, env="SENTRY_DSN")

    # OpenTelemetry / Grafana Cloud
    OTEL_SERVICE_NAME: str = Field(default="veklom-sovereign-ai-hub", env="OTEL_SERVICE_NAME")
    OTEL_EXPORTER_OTLP_ENDPOINT: Optional[str] = Field(default=None, env="OTEL_EXPORTER_OTLP_ENDPOINT")
    OTEL_EXPORTER_OTLP_HEADERS: Optional[str] = Field(default=None, env="OTEL_EXPORTER_OTLP_HEADERS")
    
    # Security Settings
    ENABLE_MFA: bool = Field(default=True, env="ENABLE_MFA")
    PASSWORD_MIN_LENGTH: int = Field(default=8, env="PASSWORD_MIN_LENGTH")
    MAX_FAILED_LOGIN_ATTEMPTS: int = Field(default=10, env="MAX_FAILED_LOGIN_ATTEMPTS")
    ACCOUNT_LOCKOUT_DURATION_MINUTES: int = Field(default=30, env="ACCOUNT_LOCKOUT_DURATION_MINUTES")
    SESSION_TIMEOUT_MINUTES: int = Field(default=120, env="SESSION_TIMEOUT_MINUTES")
    
    # Performance
    MAX_CONCURRENT_REQUESTS: int = Field(default=100, env="MAX_CONCURRENT_REQUESTS")
    REQUEST_TIMEOUT_SECONDS: int = Field(default=30, env="REQUEST_TIMEOUT_SECONDS")
    CACHE_TTL_SECONDS: int = Field(default=3600, env="CACHE_TTL_SECONDS")
    
    # AI/ML Configuration
    MODEL_CACHE_DIR: str = Field(default="/app/models", env="MODEL_CACHE_DIR")
    MAX_CONCURRENT_AI_REQUESTS: int = Field(default=10, env="MAX_CONCURRENT_AI_REQUESTS")
    AI_REQUEST_TIMEOUT_SECONDS: int = Field(default=60, env="AI_REQUEST_TIMEOUT_SECONDS")
    
    # Logging
    LOG_LEVEL: str = Field(default="INFO", env="LOG_LEVEL")
    LOG_FORMAT: str = Field(default="json", env="LOG_FORMAT")
    LOG_FILE_PATH: str = Field(default="./logs/veklom.log", env="LOG_FILE_PATH")
    
    # Build info
    BUILD_DATE: str = Field(default=datetime.utcnow().isoformat(), env="BUILD_DATE")
    VCS_REF: str = Field(default="unknown", env="VCS_REF")
    
    @property
    def ALLOWED_HOSTS(self) -> List[str]:
        """Get allowed hosts based on environment"""
        if self.ENVIRONMENT == "production":
            return [self.FRONTEND_URL.replace("https://", "").replace("http://", "")]
        return ["*"]
    
    @property
    def IS_PRODUCTION(self) -> bool:
        """Check if running in production"""
        return self.ENVIRONMENT.lower() == "production"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# Create settings instance
settings = Settings()
