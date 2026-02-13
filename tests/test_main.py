"""Tests for FastAPI main application."""

import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from jenkins_job_insight import storage
from jenkins_job_insight.models import (
    AnalysisDetail,
    AnalysisResult,
    FailureAnalysis,
)


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
                with patch(
                    "jenkins_job_insight.main.save_html_report", new_callable=AsyncMock
                ):
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
                    assert response.status_code == 200
                    data = response.json()
                    assert data["status"] == "completed"
                    assert data["job_id"] == "test-123"
                    # html_report defaults to True via env
                    assert data["html_report_url"] == "/results/test-123.html"

    def test_analyze_sync_no_html_report(self, test_client) -> None:
        """Test that html_report=false omits html_report_url from response."""
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
                        "ai_provider": "claude",
                        "ai_model": "test-model",
                        "html_report": False,
                    },
                )
                assert response.status_code == 200
                data = response.json()
                assert "html_report_url" not in data

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
        """Test analyze with optional callback fields."""
        with patch("jenkins_job_insight.main.process_analysis_with_id"):
            response = test_client.post(
                "/analyze",
                json={
                    "job_name": "test",
                    "build_number": 123,
                    "tests_repo_url": "https://github.com/example/repo",
                    "callback_url": "https://callback.example.com/webhook",
                    "callback_headers": {"Authorization": "Bearer token"},
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
                    "jenkins_job_insight.main.save_html_report", new_callable=AsyncMock
                ):
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


class TestAnalyzeFailuresEndpoint:
    """Tests for the POST /analyze-failures endpoint."""

    def test_analyze_failures_success(self, test_client) -> None:
        """Test that valid failures return 200 with correct structure."""
        mock_analysis = FailureAnalysis(
            test_name="test_foo",
            error="assert False",
            analysis=AnalysisDetail(
                classification="CODE ISSUE",
                details="Test assertion failed",
            ),
        )

        with patch("jenkins_job_insight.main.RepositoryManager") as mock_repo_cls:
            mock_repo_instance = mock_repo_cls.return_value
            mock_repo_instance.clone.return_value = None
            mock_repo_instance.cleanup.return_value = None

            with patch(
                "jenkins_job_insight.main.analyze_failure_group",
                new_callable=AsyncMock,
            ) as mock_analyze_group:
                mock_analyze_group.return_value = [mock_analysis]

                with patch(
                    "jenkins_job_insight.main.run_parallel_with_limit",
                    new_callable=AsyncMock,
                ) as mock_parallel:
                    mock_parallel.return_value = [[mock_analysis]]

                    response = test_client.post(
                        "/analyze-failures",
                        json={
                            "failures": [
                                {
                                    "test_name": "test_foo",
                                    "error_message": "assert False",
                                    "stack_trace": "File test.py, line 10",
                                }
                            ],
                            "ai_provider": "claude",
                            "ai_model": "test-model",
                        },
                    )
                    assert response.status_code == 200
                    data = response.json()
                    assert data["status"] == "completed"
                    assert data["ai_provider"] == "claude"
                    assert data["ai_model"] == "test-model"
                    assert "job_id" in data
                    assert len(data["failures"]) == 1
                    assert data["failures"][0]["test_name"] == "test_foo"

    def test_analyze_failures_empty_failures(self, test_client) -> None:
        """Test that empty failures list returns 400."""
        response = test_client.post(
            "/analyze-failures",
            json={
                "failures": [],
                "ai_provider": "claude",
                "ai_model": "test-model",
            },
        )
        assert response.status_code == 400
        assert "No failures provided" in response.json()["detail"]

    def test_analyze_failures_missing_ai_provider(self, test_client) -> None:
        """Test that missing AI provider (no env var, no body param) returns 400."""
        response = test_client.post(
            "/analyze-failures",
            json={
                "failures": [
                    {
                        "test_name": "test_foo",
                        "error_message": "assert False",
                    }
                ],
                "ai_model": "test-model",
            },
        )
        assert response.status_code == 400
        assert "AI provider" in response.json()["detail"]

    def test_analyze_failures_missing_ai_model(self, test_client) -> None:
        """Test that missing AI model returns 400."""
        response = test_client.post(
            "/analyze-failures",
            json={
                "failures": [
                    {
                        "test_name": "test_foo",
                        "error_message": "assert False",
                    }
                ],
                "ai_provider": "claude",
            },
        )
        assert response.status_code == 400
        assert "AI model" in response.json()["detail"]

    def test_analyze_failures_handles_analysis_exception(self, test_client) -> None:
        """Test that when analyze_failure_group raises, endpoint returns status 'failed'."""
        with patch("jenkins_job_insight.main.RepositoryManager") as mock_repo_cls:
            mock_repo_instance = mock_repo_cls.return_value
            mock_repo_instance.clone.return_value = None
            mock_repo_instance.cleanup.return_value = None

            with patch(
                "jenkins_job_insight.main.get_failure_signature",
                return_value="sig-a",
            ):
                with patch(
                    "jenkins_job_insight.main.run_parallel_with_limit",
                    new_callable=AsyncMock,
                    side_effect=RuntimeError("AI CLI crashed"),
                ):
                    response = test_client.post(
                        "/analyze-failures",
                        json={
                            "failures": [
                                {
                                    "test_name": "test_foo",
                                    "error_message": "assert False",
                                }
                            ],
                            "ai_provider": "claude",
                            "ai_model": "test-model",
                        },
                    )
                    assert response.status_code == 200
                    data = response.json()
                    assert data["status"] == "failed"
                    assert "AI CLI crashed" in data["summary"]

    def test_analyze_failures_partial_failure(self, test_client) -> None:
        """Test that when some failure groups succeed and others raise, the endpoint returns partial results.

        Posts 2 failures with different signatures. run_parallel_with_limit returns
        one successful analysis list and one RuntimeError exception. Verifies the
        endpoint returns status 'completed' with only the successful analysis and
        the summary reflects the correct counts.
        """
        mock_analysis = FailureAnalysis(
            test_name="test_a",
            error="err",
            analysis=AnalysisDetail(
                classification="CODE ISSUE",
                details="analysis",
            ),
        )

        with patch("jenkins_job_insight.main.RepositoryManager") as mock_repo_cls:
            mock_repo_instance = mock_repo_cls.return_value
            mock_repo_instance.clone.return_value = None
            mock_repo_instance.cleanup.return_value = None

            with patch(
                "jenkins_job_insight.main.get_failure_signature",
                side_effect=["sig-a", "sig-b"],
            ):
                with patch(
                    "jenkins_job_insight.main.run_parallel_with_limit",
                    new_callable=AsyncMock,
                ) as mock_parallel:
                    mock_parallel.return_value = [
                        [mock_analysis],
                        RuntimeError("AI CLI crashed"),
                    ]

                    with patch(
                        "jenkins_job_insight.main.save_result",
                        new_callable=AsyncMock,
                    ):
                        with patch(
                            "jenkins_job_insight.main.update_status",
                            new_callable=AsyncMock,
                        ):
                            response = test_client.post(
                                "/analyze-failures",
                                json={
                                    "failures": [
                                        {
                                            "test_name": "test_a",
                                            "error_message": "err",
                                            "stack_trace": "File a.py, line 1",
                                        },
                                        {
                                            "test_name": "test_b",
                                            "error_message": "different err",
                                            "stack_trace": "File b.py, line 2",
                                        },
                                    ],
                                    "ai_provider": "claude",
                                    "ai_model": "test-model",
                                },
                            )
                            assert response.status_code == 200
                            data = response.json()
                            assert data["status"] == "completed"
                            assert len(data["failures"]) == 1
                            assert data["failures"][0]["test_name"] == "test_a"
                            assert "2 test failures" in data["summary"]
                            assert "2 unique errors" in data["summary"]
                            assert "1 analyzed successfully" in data["summary"]

    def test_analyze_failures_deduplication(self, test_client) -> None:
        """Test that failures sharing the same signature are deduplicated.

        Three failures are submitted where two share a signature. Verify
        analyze_failure_group is called twice (once per unique signature),
        not three times.
        """
        mock_analysis_a = FailureAnalysis(
            test_name="test_foo",
            error="assert False",
            analysis=AnalysisDetail(
                classification="CODE ISSUE",
                details="assertion failure",
            ),
        )
        mock_analysis_b = FailureAnalysis(
            test_name="test_bar",
            error="KeyError: x",
            analysis=AnalysisDetail(
                classification="CODE ISSUE",
                details="missing key",
            ),
        )

        with patch("jenkins_job_insight.main.RepositoryManager") as mock_repo_cls:
            mock_repo_instance = mock_repo_cls.return_value
            mock_repo_instance.clone.return_value = None
            mock_repo_instance.cleanup.return_value = None

            # Return same signature for first two failures, different for third
            signatures = iter(["sig-a", "sig-a", "sig-b"])
            with patch(
                "jenkins_job_insight.main.get_failure_signature",
                side_effect=lambda f: next(signatures),
            ):
                with patch(
                    "jenkins_job_insight.main.analyze_failure_group",
                    new_callable=AsyncMock,
                ) as mock_analyze_group:
                    mock_analyze_group.side_effect = [
                        [mock_analysis_a, mock_analysis_a],
                        [mock_analysis_b],
                    ]

                    with patch(
                        "jenkins_job_insight.main.run_parallel_with_limit",
                        new_callable=AsyncMock,
                    ) as mock_parallel:
                        # Simulate run_parallel_with_limit calling the coroutines
                        async def run_coroutines(coroutines, **kwargs):
                            results = []
                            for coro in coroutines:
                                results.append(await coro)
                            return results

                        mock_parallel.side_effect = run_coroutines

                        response = test_client.post(
                            "/analyze-failures",
                            json={
                                "failures": [
                                    {
                                        "test_name": "test_foo",
                                        "error_message": "assert False",
                                        "stack_trace": "File test.py, line 10",
                                    },
                                    {
                                        "test_name": "test_baz",
                                        "error_message": "assert False",
                                        "stack_trace": "File test.py, line 10",
                                    },
                                    {
                                        "test_name": "test_bar",
                                        "error_message": "KeyError: x",
                                        "stack_trace": "File test.py, line 20",
                                    },
                                ],
                                "ai_provider": "claude",
                                "ai_model": "test-model",
                            },
                        )
                        assert response.status_code == 200
                        data = response.json()
                        assert data["status"] == "completed"
                        # analyze_failure_group called twice: once for sig-a group, once for sig-b
                        assert mock_analyze_group.call_count == 2


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

    def test_get_report_html(self, test_client) -> None:
        """Test retrieving a saved HTML report."""
        with patch(
            "jenkins_job_insight.main.get_html_report", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = "<!DOCTYPE html><html><body>Report</body></html>"
            response = test_client.get("/results/html-job-123.html")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "<!DOCTYPE html>" in response.text

    def test_get_report_not_found(self, test_client) -> None:
        """Test that missing HTML report returns 404."""
        with patch(
            "jenkins_job_insight.main.get_html_report", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = None
            response = test_client.get("/results/non-existent.html")
        assert response.status_code == 404

    async def test_get_result_json_format_default(
        self, test_client, temp_db_path: Path
    ) -> None:
        """Test that default format returns JSON."""
        with patch.object(storage, "DB_PATH", temp_db_path):
            await storage.init_db()
            await storage.save_result(
                job_id="json-job-456",
                jenkins_url="https://jenkins.example.com/job/test/2/",
                status="completed",
                result={"summary": "Done"},
            )
            response = test_client.get("/results/json-job-456")
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == "json-job-456"


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
