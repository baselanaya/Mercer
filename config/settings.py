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

    # llama.cpp inference server (llama-server or llama-cpp-python)
    llamacpp_url: str = "http://localhost:8080"
    # Path to the GGUF model file used by the llama.cpp server.
    # Read by scripts/serve_llamacpp_turboquant.sh as the MODEL_PATH default
    # and by docs to point users at the recommended SOTA SQL-tuned model.
    # See docs/custom-models.md for the model selection rationale.
    local_model_path: str = "models/Arctic-Text2SQL-R1-7B-IQ4_XS.gguf"

    # LLM API keys (used when inference_backend is "anthropic" or "openai")
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # Model names (overridable per environment)
    anthropic_model: str = "claude-opus-4-7"
    openai_model: str = "gpt-4.1"

    # Inference backend
    inference_backend: Literal["llamacpp", "anthropic", "openai"] = "llamacpp"

    # API
    mercer_api_key: str = ""          # Optional; if set, X-API-Key header required
    audit_path: str = "logs/audit.duckdb"

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


settings = Settings()
