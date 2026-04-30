from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "KTC KTS API"
    app_env: str = "development"
    app_port: int = 8000
    app_secret_key: str = "change-me"
    jwt_secret: str = "change-me-too"
    jwt_access_token_expire_minutes: int = 120
    jwt_refresh_token_expire_days: int = 7
    database_url: str = "sqlite:///./storage/app.db"
    app_cors_origins: str = "http://localhost:3000,http://kts.blackbirdzzzz.art"
    redis_url: str = "redis://localhost:16379/0"
    gpu_service_url: str = "http://localhost:18001"
    openai_compat_base_url: str | None = None
    openai_compat_api_key: str | None = None
    openai_compat_model: str = "kts"
    llm_request_timeout_seconds: float = 15.0
    storage_dir: Path = Field(default=ROOT_DIR / "storage")
    public_base_url: str = "http://localhost:3000"
    feature_flag_viewer_3d: bool = True
    celery_task_always_eager: bool = False
    s3_endpoint_url: str | None = None
    s3_public_endpoint_url: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_bucket: str | None = None
    s3_region: str = "us-east-1"
    s3_secure: bool = False

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.app_cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()
