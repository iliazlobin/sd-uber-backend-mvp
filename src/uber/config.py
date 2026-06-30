"""Application settings, loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Typed configuration for the Uber MVP backend."""

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/uber"
    redis_url: str = "redis://localhost:6379/0"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"

    model_config = {"extra": "ignore"}


settings = Settings()
