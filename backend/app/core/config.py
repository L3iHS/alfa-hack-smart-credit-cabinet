from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    demo_password: str = Field(min_length=12)
    processing_worker_enabled: bool = True
    cookie_secure: bool = False
    session_ttl_seconds: int = Field(default=28800, ge=60, le=604800)
    session_cookie_name: str = "credit_session"
    llm_provider: Literal['disabled', 'openai', 'ollama'] = 'disabled'
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_api_key: SecretStr | None = None
    llm_timeout_seconds: int = Field(default=30, ge=5, le=120)
    llm_max_tokens: int = Field(default=1200, ge=128, le=4096)
    llm_json_mode: Literal['json_object', 'json_schema'] = 'json_object'
    llm_reasoning_enabled: bool | None = None

    @field_validator('llm_reasoning_enabled', mode='before')
    @classmethod
    def blank_reasoning_is_unset(cls, value):
        return None if value == '' else value

    document_storage_path: Path = Path("/tmp/credit-documents")


settings = Settings()
