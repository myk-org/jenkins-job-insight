"""Tests for user feedback endpoint and scrubbing logic."""

import json
import os
from unittest.mock import patch

import pytest
from ai_cli_runner import AIResult
from fastapi.testclient import TestClient

from jenkins_job_insight import storage
from jenkins_job_insight.config import get_settings
from jenkins_job_insight.feedback import (
    _FEEDBACK_REPO_URL,
    _build_fallback_feedback,
    create_feedback_issue,
    format_feedback_with_ai,
    scrub_sensitive_data,
)
from jenkins_job_insight.models import FeedbackRequest, FeedbackResponse


# ---------------------------------------------------------------------------
# scrub_sensitive_data tests
# ---------------------------------------------------------------------------


class TestScrubSensitiveData:
    def test_bearer_token(self):
        text = "Authorization: Bearer ghp_abc123XYZ"
        result = scrub_sensitive_data(text)
        assert "ghp_abc123XYZ" not in result
        assert "[REDACTED]" in result

    def test_basic_auth_header(self):
        text = "Authorization: Basic dXNlcjpwYXNz"
        result = scrub_sensitive_data(text)
        assert "dXNlcjpwYXNz" not in result
        assert "[REDACTED]" in result

    def test_api_key_param(self):
        text = "api_key=test-key-placeholder"  # pragma: allowlist secret
        result = scrub_sensitive_data(text)
        assert "test-key-placeholder" not in result
        assert "[REDACTED]" in result

    def test_token_param(self):
        text = "token=mySecretToken123"
        result = scrub_sensitive_data(text)
        assert "mySecretToken123" not in result
        assert "[REDACTED]" in result

    def test_password_param(self):
        text = "password=SuperS3cret!"
        result = scrub_sensitive_data(text)
        assert "SuperS3cret!" not in result
        assert "[REDACTED]" in result

    def test_jwt_token(self):
        jwt = "eyJhbGci.eyJzdWIi.dummy-test-sig"  # pragma: allowlist secret
        # JWT embedded in a sentence (not preceded by a key= pattern)
        text = f"The auth header contained {jwt} which expired"
        result = scrub_sensitive_data(text)
        assert jwt not in result
        assert "[REDACTED_JWT]" in result

    def test_jwt_token_after_key(self):
        jwt = "eyJhbGci.eyJzdWIi.dummy-test-sig"  # pragma: allowlist secret
        text = f"Token: {jwt}"
        result = scrub_sensitive_data(text)
        assert jwt not in result
        assert "[REDACTED]" in result

    def test_github_token_patterns(self):
        for prefix in ("ghp_", "gho_", "ghs_", "ghr_", "github_pat_"):
            text = f"token={prefix}abcdefghij1234567890"
            result = scrub_sensitive_data(text)
            assert f"{prefix}abcdefghij1234567890" not in result

    def test_preserves_normal_text(self):
        text = "Test test_login_flow failed with AssertionError at line 42"
        result = scrub_sensitive_data(text)
        assert result == text

    def test_preserves_urls(self):
        text = "Failed request to https://api.example.com/v1/users"
        result = scrub_sensitive_data(text)
        assert "https://api.example.com/v1/users" in result

    def test_preserves_test_names(self):
        text = "tests.auth.test_login.TestLogin.test_valid_credentials"
        result = scrub_sensitive_data(text)
        assert result == text

    def test_multiple_sensitive_patterns(self):
        text = "Bearer fake-token-abc password=fake-pass api_key=mykey"
        result = scrub_sensitive_data(text)
        assert "fake-token-abc" not in result
        assert "fake-pass" not in result
        assert "mykey" not in result

    def test_empty_string(self):
        assert scrub_sensitive_data("") == ""

    def test_authorization_header_json(self):
        text = """{"Authorization": "Bearer super-secret-token"}"""
        result = scrub_sensitive_data(text)
        assert "super-secret-token" not in result


# ---------------------------------------------------------------------------
# fallback formatting tests
# ---------------------------------------------------------------------------


class TestBuildFallbackFeedback:
    def test_bug_fallback(self):
        req = FeedbackRequest(
            feedback_type="bug",
            description="Button does not work",
            console_errors=["TypeError: undefined is not a function"],
            failed_api_calls=[
                {
                    "status": 500,
                    "endpoint": "/api/analyze",
                    "error": "Internal Server Error",
                }
            ],
            page_state={"url": "/report/123"},
            user_agent="Mozilla/5.0",
        )
        title, body = _build_fallback_feedback(req)
        assert "Bug report:" in title
        assert "## Bug Report" in body
        assert "Button does not work" in body
        assert "TypeError" in body
        assert "/api/analyze" in body
        assert "Mozilla/5.0" in body

    def test_feature_fallback(self):
        req = FeedbackRequest(
            feedback_type="feature",
            description="Add dark mode support",
        )
        title, body = _build_fallback_feedback(req)
        assert "Feature request:" in title
        assert "## Feature Request" in body
        assert "Add dark mode support" in body

    def test_bug_fallback_scrubs_console_errors(self):
        req = FeedbackRequest(
            feedback_type="bug",
            description="Auth error",
            console_errors=["Bearer my-secret-token leaked"],
        )
        _, body = _build_fallback_feedback(req)
        assert "my-secret-token" not in body
        assert "[REDACTED]" in body


# ---------------------------------------------------------------------------
# format_feedback_with_ai tests
# ---------------------------------------------------------------------------


class TestFormatFeedbackWithAi:
    @pytest.fixture
    def settings(self):
        env = {
            "JENKINS_URL": "https://jenkins.example.com",
            "JENKINS_USER": "user",
            "JENKINS_PASSWORD": "pass",  # pragma: allowlist secret
        }
        with patch.dict(os.environ, env, clear=True):
            get_settings.cache_clear()
            s = get_settings()
            get_settings.cache_clear()
            return s

    async def test_ai_success(self, settings):
        req = FeedbackRequest(
            feedback_type="bug",
            description="The analyze button is broken",
        )
        ai_response = json.dumps(
            {
                "title": "Analyze button not responding",
                "body": "## Description\n\nThe analyze button fails to trigger analysis.",
            }
        )
        with patch("jenkins_job_insight.feedback.call_ai_cli") as mock_ai:
            mock_ai.return_value = AIResult(success=True, text=ai_response)
            title, body = await format_feedback_with_ai(req, settings)
        assert title == "Analyze button not responding"
        assert "## Description" in body

    async def test_ai_failure_uses_fallback(self, settings):
        req = FeedbackRequest(
            feedback_type="feature",
            description="Add export to CSV",
        )
        with patch("jenkins_job_insight.feedback.call_ai_cli") as mock_ai:
            mock_ai.return_value = AIResult(success=False, text="CLI error")
            title, body = await format_feedback_with_ai(req, settings)
        assert "Feature request:" in title
        assert "Add export to CSV" in body

    async def test_ai_returns_invalid_json_uses_fallback(self, settings):
        req = FeedbackRequest(
            feedback_type="bug",
            description="Something broke",
        )
        with patch("jenkins_job_insight.feedback.call_ai_cli") as mock_ai:
            mock_ai.return_value = AIResult(success=True, text="not json at all")
            title, body = await format_feedback_with_ai(req, settings)
        assert "Bug report:" in title

    async def test_ai_response_with_markdown_fences(self, settings):
        req = FeedbackRequest(
            feedback_type="bug",
            description="Error on page load",
        )
        ai_response = (
            "```json\n"
            + json.dumps(
                {
                    "title": "Page load error",
                    "body": "## Bug\n\nPage fails to load.",
                }
            )
            + "\n```"
        )
        with patch("jenkins_job_insight.feedback.call_ai_cli") as mock_ai:
            mock_ai.return_value = AIResult(success=True, text=ai_response)
            title, body = await format_feedback_with_ai(req, settings)
        assert title == "Page load error"

    async def test_scrubs_sensitive_data_in_context(self, settings):
        req = FeedbackRequest(
            feedback_type="bug",
            description="Auth failed",
            console_errors=["Bearer my-secret-token-123"],
            failed_api_calls=[{"error": "password=hunter2"}],
        )
        captured_prompt = None

        async def capture_call(prompt, **kwargs):
            nonlocal captured_prompt
            captured_prompt = prompt
            return AIResult(success=False, text="fail")

        with patch(
            "jenkins_job_insight.feedback.call_ai_cli", side_effect=capture_call
        ):
            await format_feedback_with_ai(req, settings)

        # Verify sensitive data was scrubbed in the prompt sent to AI
        assert "my-secret-token-123" not in captured_prompt
        assert "hunter2" not in captured_prompt


# ---------------------------------------------------------------------------
# create_feedback_issue tests
# ---------------------------------------------------------------------------


class TestCreateFeedbackIssue:
    @pytest.fixture
    def settings(self):
        env = {
            "JENKINS_URL": "https://jenkins.example.com",
            "JENKINS_USER": "user",
            "JENKINS_PASSWORD": "pass",  # pragma: allowlist secret
            "GITHUB_TOKEN": "test-token-placeholder",  # pragma: allowlist secret
        }
        with patch.dict(os.environ, env, clear=True):
            get_settings.cache_clear()
            s = get_settings()
            get_settings.cache_clear()
            return s

    async def test_creates_bug_issue(self, settings):
        req = FeedbackRequest(
            feedback_type="bug",
            description="Dashboard crashes",
        )
        with (
            patch(
                "jenkins_job_insight.feedback.format_feedback_with_ai"
            ) as mock_format,
            patch("jenkins_job_insight.feedback.create_github_issue") as mock_create,
        ):
            mock_format.return_value = (
                "Dashboard crash on load",
                "## Bug\n\nDetails...",
            )
            mock_create.return_value = {
                "url": "https://github.com/myk-org/jenkins-job-insight/issues/42",
                "number": 42,
                "title": "Dashboard crash on load",
            }
            result = await create_feedback_issue(req, settings)

        assert isinstance(result, FeedbackResponse)
        assert result.issue_number == 42
        assert result.title == "Dashboard crash on load"
        assert "issues/42" in result.issue_url

        # Verify correct label
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args
        assert call_kwargs.kwargs.get("labels") == ["bug"] or call_kwargs[1].get(
            "labels"
        ) == ["bug"]

    async def test_creates_feature_issue_with_enhancement_label(self, settings):
        req = FeedbackRequest(
            feedback_type="feature",
            description="Add dark mode",
        )
        with (
            patch(
                "jenkins_job_insight.feedback.format_feedback_with_ai"
            ) as mock_format,
            patch("jenkins_job_insight.feedback.create_github_issue") as mock_create,
        ):
            mock_format.return_value = (
                "Add dark mode support",
                "## Feature\n\nDark mode...",
            )
            mock_create.return_value = {
                "url": "https://github.com/myk-org/jenkins-job-insight/issues/99",
                "number": 99,
                "title": "Add dark mode support",
            }
            result = await create_feedback_issue(req, settings)

        assert result.issue_number == 99
        call_kwargs = mock_create.call_args
        assert call_kwargs.kwargs.get("labels") == ["enhancement"] or call_kwargs[
            1
        ].get("labels") == ["enhancement"]

    async def test_uses_correct_repo_url(self, settings):
        req = FeedbackRequest(
            feedback_type="bug",
            description="test",
        )
        with (
            patch(
                "jenkins_job_insight.feedback.format_feedback_with_ai"
            ) as mock_format,
            patch("jenkins_job_insight.feedback.create_github_issue") as mock_create,
        ):
            mock_format.return_value = ("Title", "Body")
            mock_create.return_value = {
                "url": "https://github.com/x/y/issues/1",
                "number": 1,
                "title": "Title",
            }
            await create_feedback_issue(req, settings)

        call_kwargs = mock_create.call_args
        assert (
            call_kwargs.kwargs.get("repo_url") == _FEEDBACK_REPO_URL
            or call_kwargs[1].get("repo_url") == _FEEDBACK_REPO_URL
        )


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


class TestFeedbackEndpoint:
    @pytest.fixture
    def _init_db(self, temp_db_path):
        """Initialize an empty database for endpoint tests."""
        import asyncio

        with patch.object(storage, "DB_PATH", temp_db_path):
            asyncio.run(storage.init_db())
            yield

    def _make_client(
        self,
        temp_db_path,
        github_token: str = "",
        enable_github_issues: str = "",
    ):
        """Create a TestClient with optional GITHUB_TOKEN."""
        env = {
            k: v
            for k, v in os.environ.items()
            if k
            not in {
                "GITHUB_TOKEN",
                "ADMIN_KEY",
                "JJI_ENCRYPTION_KEY",
                "ALLOWED_USERS",
                "ENABLE_GITHUB_ISSUES",
            }
        }
        env["SECURE_COOKIES"] = "false"
        env["DB_PATH"] = str(temp_db_path)
        if github_token:
            env["GITHUB_TOKEN"] = github_token
        if enable_github_issues:
            env["ENABLE_GITHUB_ISSUES"] = enable_github_issues
        with patch.dict(os.environ, env, clear=True):
            get_settings.cache_clear()
            with patch.object(storage, "DB_PATH", temp_db_path):
                from jenkins_job_insight.main import app

                with TestClient(app) as c:
                    yield c
            get_settings.cache_clear()

    def test_missing_github_token_returns_503(self, _init_db, temp_db_path):
        for client in self._make_client(temp_db_path, github_token=""):
            resp = client.post(
                "/api/feedback",
                json={
                    "feedback_type": "bug",
                    "description": "Something broke",
                },
            )
            assert resp.status_code == 503
            assert "disabled" in resp.json()["detail"]

    def test_successful_feedback_submission(self, _init_db, temp_db_path):
        for client in self._make_client(
            temp_db_path, github_token="ghp_test"
        ):  # pragma: allowlist secret
            with (
                patch(
                    "jenkins_job_insight.feedback.format_feedback_with_ai"
                ) as mock_format,
                patch(
                    "jenkins_job_insight.feedback.create_github_issue"
                ) as mock_create,
            ):
                mock_format.return_value = ("Test title", "Test body")
                mock_create.return_value = {
                    "url": "https://github.com/myk-org/jenkins-job-insight/issues/10",
                    "number": 10,
                    "title": "Test title",
                }
                resp = client.post(
                    "/api/feedback",
                    json={
                        "feedback_type": "bug",
                        "description": "The button is broken",
                        "console_errors": ["TypeError: x is not a function"],
                    },
                )
            assert resp.status_code == 201
            data = resp.json()
            assert data["issue_number"] == 10
            assert data["title"] == "Test title"
            assert "issues/10" in data["issue_url"]

    def test_invalid_feedback_type_returns_422(self, _init_db, temp_db_path):
        for client in self._make_client(
            temp_db_path, github_token="ghp_test"
        ):  # pragma: allowlist secret
            resp = client.post(
                "/api/feedback",
                json={
                    "feedback_type": "invalid",
                    "description": "Something",
                },
            )
            assert resp.status_code == 422

    def test_capabilities_includes_feedback_enabled(self, _init_db, temp_db_path):
        for client in self._make_client(
            temp_db_path, github_token="ghp_test"
        ):  # pragma: allowlist secret
            resp = client.get("/api/capabilities")
            assert resp.status_code == 200
            data = resp.json()
            assert "feedback_enabled" in data
            assert data["feedback_enabled"] is True

    def test_capabilities_feedback_disabled_without_token(self, _init_db, temp_db_path):
        for client in self._make_client(temp_db_path, github_token=""):
            resp = client.get("/api/capabilities")
            assert resp.status_code == 200
            data = resp.json()
            assert data["feedback_enabled"] is False

    def test_feedback_disabled_when_enable_github_issues_false(
        self, _init_db, temp_db_path
    ):
        for client in self._make_client(
            temp_db_path,
            github_token="ghp_test",  # pragma: allowlist secret
            enable_github_issues="false",
        ):
            resp = client.post(
                "/api/feedback",
                json={
                    "feedback_type": "bug",
                    "description": "Something broke",
                },
            )
            assert resp.status_code == 503
            assert "disabled" in resp.json()["detail"]

    def test_capabilities_feedback_disabled_when_github_issues_false(
        self, _init_db, temp_db_path
    ):
        for client in self._make_client(
            temp_db_path,
            github_token="ghp_test",  # pragma: allowlist secret
            enable_github_issues="false",
        ):
            resp = client.get("/api/capabilities")
            assert resp.status_code == 200
            assert resp.json()["feedback_enabled"] is False
