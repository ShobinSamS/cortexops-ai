from functools import lru_cache
import os
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(os.environ.get("CORTEXOPS_ROOT", Path(__file__).resolve().parents[3]))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ROOT / ".env"), extra="ignore", hide_input_in_errors=True)
    app_env: str = "development"
    postgres_password: str = Field(default="", repr=False)
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    postgres_db: str = "cortexops"
    postgres_user: str = "cortexops"
    database_url: str = Field(default="", repr=False)
    analytics_database_url: str = Field(default="", repr=False)
    jwt_secret: str = Field(default="", repr=False)
    access_token_minutes: int = 10
    refresh_token_days: int = 7
    cookie_secure: bool = False
    redis_url: str = "redis://127.0.0.1:6379/0"
    celery_queue: str = "cortexops"
    qdrant_url: str = "http://127.0.0.1:6333"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:1.7b"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L6-v2"
    llm_timeout: int = 420
    investigation_timeout: int = 1200
    max_llm_calls: int = 6
    max_tool_calls: int = 24
    upload_dir: Path = ROOT / ".data/uploads"
    max_upload_bytes: int = 20 * 1024 * 1024
    chunk_size: int = Field(default=1500, ge=300, le=6000)
    chunk_overlap: int = Field(default=200, ge=0, le=1000)
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000,http://localhost:8080,http://127.0.0.1:8080"
    mcp_base_url: str = "http://127.0.0.1"
    mcp_bind_host: str = "127.0.0.1"
    mcp_port_offset: int = 0
    mcp_container_network: bool = False
    github_token: str = Field(default="", repr=False)
    github_repository: str = ""
    github_workspace_id: str = ""
    analytics_password: str = Field(default="", repr=False)
    neo4j_uri: str = ""
    neo4j_password: str = Field(default="", repr=False)
    otel_exporter_otlp_endpoint: str = ""
    enable_demo: bool = True

    @model_validator(mode="after")
    def validate_configuration(self):
        if not self.database_url:
            self.database_url = f"postgresql+psycopg://{self.postgres_user}:{quote_plus(self.postgres_password)}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        if len(self.jwt_secret) < 32:
            raise ValueError("JWT_SECRET must contain at least 32 characters. Run setup/configure-app.py.")
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")
        if self.app_env == "production" and (not self.cookie_secure or self.enable_demo):
            raise ValueError("Production requires COOKIE_SECURE=true and ENABLE_DEMO=false")
        return self

    @property
    def psycopg_url(self):
        return self.database_url.replace("postgresql+psycopg://", "postgresql://")


@lru_cache
def get_settings() -> Settings:
    return Settings()
