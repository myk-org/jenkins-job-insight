"""Tests for the /api/analyze-comment-intent endpoint."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from ai_cli_runner import AIResult

from jenkins_job_insight import storage
from tests.conftest import build_test_env


@pytest.fixture
def _mock_settings(temp_db_path: Path):
    """Mock settings with AI provider configured."""
    env = build_test_env(
        AI_PROVIDER="gemini",
        AI_MODEL="gemini-2.5-flash",
        DB_PATH=str(temp_db_path),
        GEMINI_API_KEY="test-key",  # pragma: allowlist secret
    )
    with patch.dict(os.environ, env, clear=True):
        from jenkins_job_insight.config import get_settings

        get_settings.cache_clear()
        try:
            yield
        finally:
            get_settings.cache_clear()


@pytest.fixture
def client(_mock_settings, temp_db_path: Path):
    """Create a test client with mocked dependencies."""
    with patch.object(storage, "DB_PATH", temp_db_path):
        from starlette.testclient import TestClient

        from jenkins_job_insight.main import app

        with TestClient(app) as c:
            yield c


class TestAnalyzeCommentIntent:
    """Tests for /api/analyze-comment-intent endpoint."""

    def test_comment_suggests_reviewed(self, client) -> None:
        """Comment with a bug link implies reviewed."""
        ai_response = AIResult(
            success=True,
            text='{"suggests_reviewed": true, "reason": "Bug filed with Jira link"}',
        )
        with patch("ai_cli_runner.call_ai_cli", return_value=ai_response) as mock_ai:
            response = client.post(
                "/api/analyze-comment-intent",
                json={"comment": "Filed JIRA-123 for this failure"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["suggests_reviewed"] is True
        assert data["reason"] == "Bug filed with Jira link"
        mock_ai.assert_called_once()

    def test_comment_does_not_suggest_reviewed(self, client) -> None:
        """Comment sharing a URL for context does not imply reviewed."""
        ai_response = AIResult(
            success=True,
            text='{"suggests_reviewed": false, "reason": "Sharing a URL for context, no resolution indicated"}',
        )
        with patch("ai_cli_runner.call_ai_cli", return_value=ai_response):
            response = client.post(
                "/api/analyze-comment-intent",
                json={
                    "comment": "Here's the docs link: https://docs.example.com/troubleshooting"
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["suggests_reviewed"] is False

    def test_ai_failure_returns_false(self, client) -> None:
        """AI call failure returns safe default (suggests_reviewed=False)."""
        ai_response = AIResult(
            success=False,
            text="AI service unavailable",
        )
        with patch("ai_cli_runner.call_ai_cli", return_value=ai_response):
            response = client.post(
                "/api/analyze-comment-intent",
                json={"comment": "Fixed in commit abc123"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["suggests_reviewed"] is False
        assert data["reason"] == ""

    def test_ai_returns_invalid_json(self, client) -> None:
        """Unparseable AI response returns safe default."""
        ai_response = AIResult(
            success=True,
            text="This is not valid JSON at all",
        )
        with patch("ai_cli_runner.call_ai_cli", return_value=ai_response):
            response = client.post(
                "/api/analyze-comment-intent",
                json={"comment": "some comment"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["suggests_reviewed"] is False

    def test_records_ai_usage(self, client) -> None:
        """Token usage is recorded for comment intent calls."""
        ai_response = AIResult(
            success=True,
            text='{"suggests_reviewed": false, "reason": "test"}',
        )
        with (
            patch("ai_cli_runner.call_ai_cli", return_value=ai_response),
            patch("jenkins_job_insight.token_tracking.record_ai_usage") as mock_record,
        ):
            response = client.post(
                "/api/analyze-comment-intent",
                json={"comment": "test comment"},
            )

        assert response.status_code == 200
        mock_record.assert_called_once()
        call_kwargs = mock_record.call_args
        assert call_kwargs.kwargs["job_id"] == "comment-intent"
        assert call_kwargs.kwargs["call_type"] == "comment_intent"

    def test_missing_comment_field(self, client) -> None:
        """Missing comment field returns 422."""
        response = client.post(
            "/api/analyze-comment-intent",
            json={},
        )
        assert response.status_code == 422

    def test_accepts_ai_provider_and_model(self, client) -> None:
        """Request body can include optional ai_provider and ai_model."""
        ai_response = AIResult(
            success=True,
            text='{"suggests_reviewed": true, "reason": "Bug filed"}',
        )
        with patch("ai_cli_runner.call_ai_cli", return_value=ai_response) as mock_ai:
            response = client.post(
                "/api/analyze-comment-intent",
                json={
                    "comment": "Filed JIRA-123",
                    "ai_provider": "claude",
                    "ai_model": "claude-sonnet-4-20250514",
                },
            )

        assert response.status_code == 200
        assert response.json()["suggests_reviewed"] is True
        call_kwargs = mock_ai.call_args
        assert call_kwargs.kwargs["ai_provider"] == "claude"
        assert call_kwargs.kwargs["ai_model"] == "claude-sonnet-4-20250514"
