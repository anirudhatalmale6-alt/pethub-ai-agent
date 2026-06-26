from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    app_name: str = "PetHub AI Agent"
    environment: str = "development"
    debug: bool = False

    database_url: str = "postgresql+asyncpg://pethub:pethub@db:5432/pethub_agent"
    redis_url: str = "redis://redis:6379/0"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    cors_origins: list[str] = ["http://localhost:3000"]

    wp_url: str = ""
    wp_user: str = ""
    wp_password: str = ""

    max_tool_iterations: int = 10
    require_approval_for: list[str] = [
        "bulk_edit",
        "plugin_install",
        "site_wide_change",
        "delete_content",
    ]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
