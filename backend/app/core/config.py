from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "RepoPilot API"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    secret_key: str = "development-only-change-me"
    database_url: str = "sqlite:///./repopilot.db"
    redis_url: str = "redis://localhost:6379/0"
    groq_api_key: str | None = None
    groq_model: str = "openai/gpt-oss-120b"
    reranker_enabled: bool = False
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    github_token: str | None = None
    github_client_id: str | None = None
    github_client_secret: str | None = None
    github_webhook_secret: str | None = None
    sandbox_url: str = "http://sandbox:8090"
    sandbox_shared_secret: str = ""
    frontend_url: str = "http://localhost"
    public_api_url: str = "http://localhost"
    max_upload_mb: int = 100
    audit_retention_days: int = 365
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[3] / ".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False)

def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return "postgresql+psycopg://" + database_url.removeprefix("postgres://")
    if database_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + database_url.removeprefix("postgresql://")
    return database_url

@lru_cache
def get_settings() -> Settings:
    return Settings()
