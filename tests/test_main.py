"""Tests for FastAPI main application."""

import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from jenkins_job_insight import storage
from jenkins_job_insight.models import AnalysisResult


@pytest.fixture
def mock_settings():
    """Mock settings for tests."""
    env = {
        "JENKINS_URL": "https://jenkins.example.com",
        "JENKINS_USER": "testuser",
        "JENKINS_PASSWORD": "testpassword",  # pragma: allowlist secret
        "GEMINI_API_KEY": "test-key",  # pragma: allowlist secret
    }
    with patch.dict(os.environ, env, clear=True):
        # Clear the lru_cache to use fresh settings
        from jenkins_job_insight.config import get_settings

        get_settings.cache_clear()
        yield


@pytest.fixture
def test_client(mock_settings, temp_db_path: Path):
    """Create a test client with mocked dependencies."""
    with patch.object(storage, "DB_PATH", temp_db_path):
        from starlette.testclient import TestClient
        from jenkins_job_insight.main import app

        with TestClient(app) as client:
            yield client


class TestHealthEndpoint:
    """Tests for the /health endpoint."""

    def test_health_check_returns_healthy(self, test_client) -> None:
        """Test that health check returns healthy status."""
        response = test_client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}

    def test_health_check_method_not_allowed(self, test_client) -> None:
        """Test that POST to health returns 405."""
        response = test_client.post("/health")
        assert response.status_code == 405


class TestAnalyzeEndpoint:
    """Tests for the /analyze endpoint."""

    def test_analyze_async_returns_queued(self, test_client) -> None:
        """Test that async analyze returns queued status."""
        with patch("jenkins_job_insight.main.process_analysis_with_id"):
            response = test_client.post(
                "/analyze",
                json={
                    "job_name": "test",
                    "build_number": 123,
                    "tests_repo_url": "https://github.com/example/repo",
                },
            )
            assert response.status_code == 202
            data = response.json()
            assert data["status"] == "queued"

    def test_analyze_sync_accepts_sync_param(self, test_client) -> None:
        """Test that sync parameter is accepted (validation test only).

        Note: Full sync test requires extensive mocking of analyze_job,
        Jenkins client, and AI client. This test verifies the endpoint
        accepts the sync parameter without validation errors.
        """
        # Mock the analyze_job at the module level before the request
        with patch(
            "jenkins_job_insight.main.analyze_job", new_callable=AsyncMock
        ) as mock_analyze:
            with patch("jenkins_job_insight.main.save_result", new_callable=AsyncMock):
                mock_result = AnalysisResult(
                    job_id="test-123",
                    jenkins_url="https://jenkins.example.com/job/test/123/",
                    status="completed",
                    summary="Analysis complete",
                    failures=[],
                )
                mock_analyze.return_value = mock_result

                response = test_client.post(
                    "/analyze?sync=true",
                    json={
                        "job_name": "test",
                        "build_number": 123,
                        "tests_repo_url": "https://github.com/example/repo",
                        "ai_provider": "claude",
                        "ai_model": "test-model",
                    },
                )
                # Sync mode returns 200 (completed), not 202 (accepted)
                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "completed"
                assert data["job_id"] == "test-123"

    def test_analyze_sync_missing_ai_provider_returns_400(self, test_client) -> None:
        """Test that sync analyze without AI provider returns 400."""
        response = test_client.post(
            "/analyze?sync=true",
            json={
                "job_name": "test",
                "build_number": 123,
                "tests_repo_url": "https://github.com/example/repo",
                "ai_model": "test-model",
            },
        )
        assert response.status_code == 400
        assert "AI provider" in response.json()["detail"]

    def test_analyze_sync_missing_ai_model_returns_400(self, test_client) -> None:
        """Test that sync analyze without AI model returns 400."""
        response = test_client.post(
            "/analyze?sync=true",
            json={
                "job_name": "test",
                "build_number": 123,
                "tests_repo_url": "https://github.com/example/repo",
                "ai_provider": "claude",
            },
        )
        assert response.status_code == 400
        assert "AI model" in response.json()["detail"]

    def test_analyze_invalid_build_number(self, test_client) -> None:
        """Test that invalid build number returns 422."""
        response = test_client.post(
            "/analyze",
            json={
                "job_name": "test",
                "build_number": "not-a-number",
                "tests_repo_url": "https://github.com/example/repo",
            },
        )
        assert response.status_code == 422

    def test_analyze_invalid_tests_repo_url(self, test_client) -> None:
        """Test that invalid repo URL returns 422."""
        response = test_client.post(
            "/analyze",
            json={
                "job_name": "test",
                "build_number": 123,
                "tests_repo_url": "not-a-valid-url",
            },
        )
        assert response.status_code == 422

    def test_analyze_missing_required_field(self, test_client) -> None:
        """Test that missing required field returns 422."""
        response = test_client.post(
            "/analyze",
            json={
                "job_name": "test",
            },
        )
        assert response.status_code == 422

    def test_analyze_with_optional_fields(self, test_client) -> None:
        """Test analyze with optional callback and Slack fields."""
        with patch("jenkins_job_insight.main.process_analysis_with_id"):
            response = test_client.post(
                "/analyze",
                json={
                    "job_name": "test",
                    "build_number": 123,
                    "tests_repo_url": "https://github.com/example/repo",
                    "callback_url": "https://callback.example.com/webhook",
                    "callback_headers": {"Authorization": "Bearer token"},
                    "slack_webhook_url": "https://hooks.slack.com/services/xxx",
                },
            )
            assert response.status_code == 202

    def test_analyze_sync_sends_callback(self, test_client) -> None:
        """Test that sync analyze sends callback when URL provided."""
        mock_result = AnalysisResult(
            job_id="test-123",
            jenkins_url="https://jenkins.example.com/job/test/123/",
            status="completed",
            summary="Analysis complete",
            failures=[],
        )

        with patch(
            "jenkins_job_insight.main.analyze_job", new_callable=AsyncMock
        ) as mock_analyze:
            with patch("jenkins_job_insight.main.save_result", new_callable=AsyncMock):
                with patch(
                    "jenkins_job_insight.main.send_callback", new_callable=AsyncMock
                ) as mock_callback:
                    mock_analyze.return_value = mock_result

                    response = test_client.post(
                        "/analyze?sync=true",
                        json={
                            "job_name": "test",
                            "build_number": 123,
                            "tests_repo_url": "https://github.com/example/repo",
                            "callback_url": "https://callback.example.com/webhook",
                            "ai_provider": "claude",
                            "ai_model": "test-model",
                        },
                    )
                    assert response.status_code == 200
                    mock_callback.assert_called_once()

    def test_analyze_sync_sends_slack(self, test_client) -> None:
        """Test that sync analyze sends Slack notification when URL provided."""
        mock_result = AnalysisResult(
            job_id="test-123",
            jenkins_url="https://jenkins.example.com/job/test/123/",
            status="completed",
            summary="Analysis complete",
            failures=[],
        )

        with patch(
            "jenkins_job_insight.main.analyze_job", new_callable=AsyncMock
        ) as mock_analyze:
            with patch("jenkins_job_insight.main.save_result", new_callable=AsyncMock):
                with patch(
                    "jenkins_job_insight.main.send_slack", new_callable=AsyncMock
                ) as mock_slack:
                    mock_analyze.return_value = mock_result

                    response = test_client.post(
                        "/analyze?sync=true",
                        json={
                            "job_name": "test",
                            "build_number": 123,
                            "tests_repo_url": "https://github.com/example/repo",
                            "slack_webhook_url": "https://hooks.slack.com/services/xxx",
                            "ai_provider": "claude",
                            "ai_model": "test-model",
                        },
                    )
                    assert response.status_code == 200
                    mock_slack.assert_called_once()


class TestResultsEndpoints:
    """Tests for the /results endpoints."""

    async def test_get_result_existing(self, test_client, temp_db_path: Path) -> None:
        """Test retrieving an existing result."""
        with patch.object(storage, "DB_PATH", temp_db_path):
            await storage.init_db()
            await storage.save_result(
                job_id="job-123",
                jenkins_url="https://jenkins.example.com/job/test/1/",
                status="completed",
                result={"summary": "Done"},
            )

            response = test_client.get("/results/job-123")
            assert response.status_code == 200
            data = response.json()
            assert data["job_id"] == "job-123"

    def test_get_result_not_found(self, test_client) -> None:
        """Test retrieving non-existent result returns 404."""
        response = test_client.get("/results/non-existent")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    async def test_list_results(self, test_client, temp_db_path: Path) -> None:
        """Test listing results."""
        with patch.object(storage, "DB_PATH", temp_db_path):
            await storage.init_db()
            for i in range(3):
                await storage.save_result(
                    job_id=f"job-{i}",
                    jenkins_url=f"https://jenkins.example.com/job/test/{i}/",
                    status="completed",
                )

            response = test_client.get("/results")
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 3

    async def test_list_results_with_limit(
        self, test_client, temp_db_path: Path
    ) -> None:
        """Test listing results with limit parameter."""
        with patch.object(storage, "DB_PATH", temp_db_path):
            await storage.init_db()
            for i in range(10):
                await storage.save_result(
                    job_id=f"job-limit-{i}",
                    jenkins_url=f"https://jenkins.example.com/job/test/{i}/",
                    status="completed",
                )

            response = test_client.get("/results?limit=5")
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 5

    def test_list_results_limit_max(self, test_client) -> None:
        """Test that limit is capped at 100."""
        response = test_client.get("/results?limit=200")
        assert response.status_code == 422  # Validation error

    def test_list_results_empty(self, test_client) -> None:
        """Test listing results when empty."""
        response = test_client.get("/results")
        assert response.status_code == 200
        assert response.json() == []


class TestAppLifespan:
    """Tests for application lifespan events."""

    def test_app_initializes_db_on_startup(
        self, mock_settings, temp_db_path: Path
    ) -> None:
        """Test that database is initialized on app startup."""
        with patch.object(storage, "DB_PATH", temp_db_path):
            from starlette.testclient import TestClient
            from jenkins_job_insight.main import app

            with TestClient(app):
                # After startup, DB should exist with results table
                assert temp_db_path.exists()


class TestOpenAPISchema:
    """Tests for OpenAPI schema."""

    def test_openapi_schema_available(self, test_client) -> None:
        """Test that OpenAPI schema is available."""
        response = test_client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        assert schema["info"]["title"] == "Jenkins Job Insight"
        assert schema["info"]["version"] == "0.1.0"

    def test_docs_available(self, test_client) -> None:
        """Test that docs endpoint is available."""
        response = test_client.get("/docs")
        assert response.status_code == 200
