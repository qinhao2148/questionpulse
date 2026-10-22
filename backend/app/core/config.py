from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    app_env: str = "development"
    app_name: str = "QuestionPulse API"
    api_v1_prefix: str = "/api/v1"
    database_url: str = (
        "mysql+asyncmy://questionpulse:questionpulse_dev@127.0.0.1:3307/"
        "questionpulse?charset=utf8mb4"
    )
    cors_origins: list[str] | str = ["http://localhost:5173", "http://127.0.0.1:5173"]
    polyv_app_id: str = ""
    polyv_app_secret: str = ""
    polyv_channel_id: str = ""
    polyv_session_id: str = ""
    polyv_api_timeout_seconds: float = 10.0
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-flash"
    llm_timeout_seconds: float = 15.0
    llm_max_output_tokens: int = 1200
    access_token_ttl_hours: int = 72

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str) and not value.startswith("["):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("llm_base_url", mode="before")
    @classmethod
    def default_llm_base_url(cls, value: object) -> object:
        return value or "https://api.deepseek.com"

    @field_validator("llm_model", mode="before")
    @classmethod
    def default_llm_model(cls, value: object) -> object:
        return value or "deepseek-flash"


@lru_cache
def get_settings() -> Settings:
    return Settings()
