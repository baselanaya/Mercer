from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql+asyncpg://mercer:mercer@localhost:5432/mercer_dev"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # SGLang inference server
    sglang_url: str = "http://localhost:30000"

    # LLM API keys
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # Model names (overridable per environment)
    anthropic_model: str = "claude-sonnet-4-6"
    openai_model: str = "gpt-4o"

    # Inference backend
    inference_backend: Literal["sglang", "anthropic", "openai"] = "anthropic"

    # API
    mercer_api_key: str = ""          # Optional; if set, X-API-Key header required
    audit_path: str = "logs/audit.duckdb"

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


settings = Settings()
