"""Configuration settings from environment variables."""

import os
from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from simple_logger.logger import get_logger

logger = get_logger(name=__name__, level=os.environ.get("LOG_LEVEL", "INFO"))


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

    # Optional defaults (can be overridden per-request in webhook)
    tests_repo_url: str | None = None
    callback_url: str | None = None
    callback_headers: dict[str, str] | None = None

    # Jira integration (optional)
    jira_url: str | None = None
    jira_email: str | None = None
    jira_api_token: SecretStr | None = None
    jira_pat: SecretStr | None = None
    jira_project_key: str | None = None
    jira_ssl_verify: bool = True
    jira_max_results: int = Field(default=5, gt=0)

    # Explicit Jira toggle (optional)
    enable_jira: bool | None = None

    # AI CLI timeout in minutes
    ai_cli_timeout: int = Field(default=10, gt=0)

    # Jenkins artifacts configuration
    jenkins_artifacts_max_size_mb: int = Field(default=500, gt=0)
    jenkins_artifacts_context_lines: int = Field(default=200, gt=0)

    # Artifact download toggle
    get_job_artifacts: bool = True

    # GitHub (optional) -- for comment enrichment (PR status)
    github_token: SecretStr | None = None

    @property
    def jira_enabled(self) -> bool:
        """Check if Jira integration is enabled and configured with valid credentials."""
        if self.enable_jira is False:
            return False
        if not self.jira_url:
            if self.enable_jira is True:
                logger.warning("enable_jira is True but JIRA_URL is not configured")
            return False
        # Token: prefer jira_api_token (backward compat), fall back to jira_pat
        has_token = bool(self.jira_api_token or self.jira_pat)
        if not has_token:
            if self.enable_jira is True:
                logger.warning(
                    "enable_jira is True but no Jira credentials are configured"
                )
            return False
        return True


@lru_cache
def get_settings() -> Settings:
    """Get application settings instance."""
    return Settings()
