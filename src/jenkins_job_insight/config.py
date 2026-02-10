"""Configuration settings from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Claude Code CLI configuration (set by container environment)
    # These env vars are read by the claude CLI, not by this application:
    # - CLAUDE_CODE_USE_VERTEX=1
    # - CLOUD_ML_REGION=<region>
    # - ANTHROPIC_VERTEX_PROJECT_ID=<project>

    # Jenkins configuration
    jenkins_url: str
    jenkins_user: str
    jenkins_password: str
    jenkins_ssl_verify: bool = True

    # Custom prompt file path
    prompt_file: str = "/app/PROMPT.md"

    # Optional defaults (can be overridden per-request in webhook)
    tests_repo_url: str | None = None
    callback_url: str | None = None
    callback_headers: dict[str, str] | None = None


@lru_cache
def get_settings() -> Settings:
    """Get application settings instance."""
    return Settings()
