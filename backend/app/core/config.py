from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    demo_password: str = Field(min_length=12)
    cookie_secure: bool = False
    session_ttl_seconds: int = Field(default=28800, ge=60, le=604800)
    session_cookie_name: str = "credit_session"


settings = Settings()
