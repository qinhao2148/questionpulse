from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_TEACHER_PORTAL_SECRET = "questionpulse-local-teacher-portal"
DEFAULT_TEACHER_PASSWORD = "123456"
DEFAULT_PSEUDONYM_KEY = "questionpulse-development-pseudonym-key"
DEVELOPMENT_ENVIRONMENTS = {"development", "dev", "local", "test"}


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
    cors_origins: list[str] | str = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:15021",
        "http://127.0.0.1:15021",
    ]
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
    teacher_portal_ttl_hours: int = 24
    participant_pseudonym_key: str = DEFAULT_PSEUDONYM_KEY
    teacher_username: str = "0"
    teacher_password: str = DEFAULT_TEACHER_PASSWORD
    teacher_portal_secret: str = DEFAULT_TEACHER_PORTAL_SECRET

    # Knowledge base / RAG. Generation always uses the configured LLM API; the
    # embedding model runs in-process via fastembed (no model serving) and can
    # degrade to the deterministic hash embedder when it is unavailable.
    knowledge_storage_path: str = "../storage/knowledge"
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "questionpulse_knowledge_v1"
    qdrant_timeout_seconds: float = 10.0
    embedding_provider: str = "fastembed"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_dimensions: int = 512
    knowledge_max_file_mb: int = 50
    knowledge_worker_poll_seconds: float = 2.0
    # A cross-process in-memory vector store silently loses data (the worker
    # writes where the API can never read), so it is test-only by default.
    knowledge_allow_memory_vector_store: bool = False
    knowledge_job_lease_seconds: int = 300
    knowledge_job_max_attempts: int = 3
    rag_top_k: int = 20
    rag_context_limit: int = 6
    rag_min_score: float = 0.35
    rag_timeout_seconds: float = 30.0
    rag_max_output_tokens: int = 1500

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

    @field_validator("embedding_model", mode="before")
    @classmethod
    def default_embedding_model(cls, value: object) -> object:
        # .env ships an empty EMBEDDING_MODEL= line; treat it as unset so the
        # fastembed default still applies.
        return value or "BAAI/bge-small-zh-v1.5"

    @field_validator("qdrant_url", mode="before")
    @classmethod
    def default_qdrant_url(cls, value: object) -> object:
        return value or "http://127.0.0.1:6333"

    @field_validator("knowledge_storage_path", mode="before")
    @classmethod
    def default_knowledge_storage_path(cls, value: object) -> object:
        return value or "../storage/knowledge"

    @model_validator(mode="after")
    def reject_development_credentials_in_production(self) -> "Settings":
        """Refuse to boot outside development with shipped default credentials."""
        if self.app_env.strip().lower() in DEVELOPMENT_ENVIRONMENTS:
            return self
        weak: list[str] = []
        if self.teacher_password == DEFAULT_TEACHER_PASSWORD or len(self.teacher_password) < 12:
            weak.append("TEACHER_PASSWORD")
        if self.teacher_portal_secret == DEFAULT_TEACHER_PORTAL_SECRET:
            weak.append("TEACHER_PORTAL_SECRET")
        if self.participant_pseudonym_key == DEFAULT_PSEUDONYM_KEY:
            weak.append("PARTICIPANT_PSEUDONYM_KEY")
        if weak:
            raise ValueError(
                "development default credentials are not allowed when "
                f"APP_ENV={self.app_env}: {', '.join(weak)}"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
