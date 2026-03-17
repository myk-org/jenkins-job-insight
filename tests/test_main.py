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
            assert data["base_url"] == "http://testserver"
            assert data["result_url"].startswith("http://testserver/results/")
            assert data["html_report_url"].startswith("http://testserver/results/")
            assert data["html_report_url"].endswith(".html")

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
            with patch(
                "jenkins_job_insight.main.save_result", new_callable=AsyncMock
            ) as mock_save:
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
                assert (
                    data["html_report_url"] == "http://testserver/results/test-123.html"
                )
                assert data["base_url"] == "http://testserver"
                assert data["result_url"] == "http://testserver/results/test-123"

                # Verify result was persisted
                mock_save.assert_called_once()

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

    def test_analyze_async_always_includes_html_report_url(self, test_client) -> None:
        """Test that async analyze always includes html_report_url for lazy generation."""
        with patch("jenkins_job_insight.main.process_analysis_with_id"):
            response = test_client.post(
                "/analyze",
                json={
                    "job_name": "test",
                    "build_number": 123,
                },
            )
            assert response.status_code == 202
            data = response.json()
            assert data["html_report_url"].startswith("http://testserver/results/")
            assert data["html_report_url"].endswith(".html")
            assert data["base_url"] == "http://testserver"
            assert data["result_url"].startswith("http://testserver/results/")


class TestBaseUrlDetection:
    """Tests for base URL detection from request headers."""

    def test_base_url_from_forwarded_headers(self, test_client) -> None:
        """Test base URL detection from X-Forwarded-Proto and X-Forwarded-Host."""
        with patch("jenkins_job_insight.main.process_analysis_with_id"):
            response = test_client.post(
                "/analyze",
                json={"job_name": "test", "build_number": 1},
                headers={
                    "X-Forwarded-Proto": "https",
                    "X-Forwarded-Host": "myapp.example.com",
                },
            )
            assert response.status_code == 202
            data = response.json()
            assert data["base_url"] == "https://myapp.example.com"
            assert data["result_url"].startswith("https://myapp.example.com/results/")

    def test_base_url_from_forwarded_headers_with_port(self, test_client) -> None:
        """Test base URL detection with forwarded host including port."""
        with patch("jenkins_job_insight.main.process_analysis_with_id"):
            response = test_client.post(
                "/analyze",
                json={"job_name": "test", "build_number": 1},
                headers={
                    "X-Forwarded-Proto": "https",
                    "X-Forwarded-Host": "myapp.example.com:8443",
                },
            )
            assert response.status_code == 202
            data = response.json()
            assert data["base_url"] == "https://myapp.example.com:8443"

    def test_base_url_comma_separated_forwarded_headers(self, test_client) -> None:
        """Test that only the first value is used from comma-separated forwarded headers."""
        with patch("jenkins_job_insight.main.process_analysis_with_id"):
            response = test_client.post(
                "/analyze",
                json={"job_name": "test", "build_number": 1},
                headers={
                    "X-Forwarded-Proto": "https, http",
                    "X-Forwarded-Host": "external.example.com, internal.proxy",
                },
            )
            assert response.status_code == 202
            data = response.json()
            assert data["base_url"] == "https://external.example.com"

    def test_base_url_invalid_proto_defaults_to_https(self, test_client) -> None:
        """Test that invalid X-Forwarded-Proto defaults to https."""
        with patch("jenkins_job_insight.main.process_analysis_with_id"):
            response = test_client.post(
                "/analyze",
                json={"job_name": "test", "build_number": 1},
                headers={
                    "X-Forwarded-Proto": "ftp",
                    "X-Forwarded-Host": "myapp.example.com",
                },
            )
            assert response.status_code == 202
            data = response.json()
            assert data["base_url"] == "https://myapp.example.com"

    def test_base_url_invalid_forwarded_host_falls_back(self, test_client) -> None:
        """Test that invalid X-Forwarded-Host (with special chars) falls back to Host header."""
        with patch("jenkins_job_insight.main.process_analysis_with_id"):
            response = test_client.post(
                "/analyze",
                json={"job_name": "test", "build_number": 1},
                headers={
                    "X-Forwarded-Proto": "https",
                    "X-Forwarded-Host": "evil.com/<script>alert(1)</script>",
                },
            )
            assert response.status_code == 202
            data = response.json()
            # Should NOT contain the malicious host
            assert "evil.com/<script>" not in data["base_url"]
            # Should fall back to testserver
            assert data["base_url"] == "http://testserver"

    def test_base_url_leading_dot_hostname_rejected(self, test_client) -> None:
        """Test that leading dot in hostname is rejected by RFC-1123 validation."""
        with patch("jenkins_job_insight.main.process_analysis_with_id"):
            response = test_client.post(
                "/analyze",
                json={"job_name": "test", "build_number": 1},
                headers={
                    "X-Forwarded-Proto": "https",
                    "X-Forwarded-Host": ".evil.com",
                },
            )
            assert response.status_code == 202
            data = response.json()
            assert data["base_url"] == "http://testserver"

    def test_base_url_default_from_host_header(self, test_client) -> None:
        """Test base URL from Host header when no forwarded headers present."""
        with patch("jenkins_job_insight.main.process_analysis_with_id"):
            # TestClient always sends Host: testserver
            response = test_client.post(
                "/analyze",
                json={"job_name": "test", "build_number": 1},
            )
            assert response.status_code == 202
            data = response.json()
            assert data["base_url"] == "http://testserver"


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

                    async def run_coroutines(coroutines, **kwargs):
                        return [await coro for coro in coroutines]

                    mock_parallel.side_effect = run_coroutines

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
                    assert data["base_url"] == "http://testserver"
                    assert data["result_url"].startswith("http://testserver/results/")
                    assert data["html_report_url"].startswith(
                        "http://testserver/results/"
                    )
                    assert data["html_report_url"].endswith(".html")

    def test_analyze_failures_passes_resolved_custom_prompt(self, test_client) -> None:
        """Test that resolved custom prompt is forwarded to group analysis."""
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
            mock_repo_instance.clone.return_value = Path("/tmp/test-repo")
            mock_repo_instance.cleanup.return_value = None

            with patch(
                "jenkins_job_insight.main._resolve_custom_prompt",
                return_value="Custom instructions",
            ) as mock_resolve_prompt:
                with patch(
                    "jenkins_job_insight.main.analyze_failure_group",
                    new_callable=AsyncMock,
                ) as mock_analyze_group:
                    mock_analyze_group.return_value = [mock_analysis]

                    with patch(
                        "jenkins_job_insight.main.run_parallel_with_limit",
                        new_callable=AsyncMock,
                    ) as mock_parallel:

                        async def run_coroutines(coroutines, **kwargs):
                            return [await coro for coro in coroutines]

                        mock_parallel.side_effect = run_coroutines

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
                                "tests_repo_url": "https://github.com/example/repo",
                                "raw_prompt": "Request prompt",
                                "ai_provider": "claude",
                                "ai_model": "test-model",
                            },
                        )

                    assert response.status_code == 200
                    mock_resolve_prompt.assert_called_once_with(
                        "Request prompt", Path("/tmp/test-repo")
                    )
                    assert (
                        mock_analyze_group.call_args.kwargs["custom_prompt"]
                        == "Custom instructions"
                    )

    def test_analyze_failures_empty_failures(self, test_client) -> None:
        """Test that empty failures list returns 422 (validator rejects empty list without raw_xml)."""
        response = test_client.post(
            "/analyze-failures",
            json={
                "failures": [],
                "ai_provider": "claude",
                "ai_model": "test-model",
            },
        )
        assert response.status_code == 422

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
                ) as mock_parallel:

                    async def raise_after_closing(coroutines, **kwargs):
                        for coro in coroutines:
                            coro.close()
                        raise RuntimeError("AI CLI crashed")

                    mock_parallel.side_effect = raise_after_closing

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

                    async def run_partial_failure(coroutines, **kwargs):
                        for coro in coroutines:
                            coro.close()
                        return [
                            [mock_analysis],
                            RuntimeError("AI CLI crashed"),
                        ]

                    mock_parallel.side_effect = run_partial_failure

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


class TestAnalyzeFailuresRawXml:
    """Tests for the POST /analyze-failures endpoint with raw_xml input."""

    SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="TestSuite" tests="2" failures="1" errors="0">
    <testcase classname="tests.test_auth" name="test_login" time="0.5">
        <failure message="assert False" type="AssertionError">
            at tests/test_auth.py:42
        </failure>
    </testcase>
    <testcase classname="tests.test_auth" name="test_logout" time="0.1"/>
</testsuite>"""

    SAMPLE_XML_NO_FAILURES = """<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="TestSuite" tests="1" failures="0" errors="0">
    <testcase classname="tests.test_auth" name="test_ok" time="0.1"/>
</testsuite>"""

    def test_raw_xml_success(self, test_client) -> None:
        """Test that raw_xml with failures returns enriched XML."""
        mock_analysis = FailureAnalysis(
            test_name="tests.test_auth.test_login",
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
                "jenkins_job_insight.main.run_parallel_with_limit",
                new_callable=AsyncMock,
            ) as mock_parallel:

                async def return_mock_results(coroutines, **kwargs):
                    for coro in coroutines:
                        coro.close()
                    return [[mock_analysis]]

                mock_parallel.side_effect = return_mock_results

                response = test_client.post(
                    "/analyze-failures",
                    json={
                        "raw_xml": self.SAMPLE_XML,
                        "ai_provider": "claude",
                        "ai_model": "test-model",
                    },
                )
                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "completed"
                assert data["enriched_xml"] is not None
                assert "<?xml" in data["enriched_xml"]
                assert len(data["failures"]) == 1

    def test_raw_xml_no_failures(self, test_client) -> None:
        """Test that raw_xml with no failures returns the original XML."""
        response = test_client.post(
            "/analyze-failures",
            json={
                "raw_xml": self.SAMPLE_XML_NO_FAILURES,
                "ai_provider": "claude",
                "ai_model": "test-model",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert "No test failures" in data["summary"]
        assert data["enriched_xml"] is not None

    def test_raw_xml_invalid_xml(self, test_client) -> None:
        """Test that invalid XML returns 400."""
        response = test_client.post(
            "/analyze-failures",
            json={
                "raw_xml": "this is not valid xml <<<<",
                "ai_provider": "claude",
                "ai_model": "test-model",
            },
        )
        assert response.status_code == 400
        assert "Invalid XML" in response.json()["detail"]

    def test_raw_xml_and_failures_mutual_exclusion(self, test_client) -> None:
        """Test that providing both raw_xml and failures returns 422."""
        response = test_client.post(
            "/analyze-failures",
            json={
                "raw_xml": self.SAMPLE_XML,
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
        assert response.status_code == 422

    def test_neither_raw_xml_nor_failures_returns_422(self, test_client) -> None:
        """Test that providing neither raw_xml nor failures returns 422."""
        response = test_client.post(
            "/analyze-failures",
            json={
                "ai_provider": "claude",
                "ai_model": "test-model",
            },
        )
        assert response.status_code == 422

    def test_failures_mode_still_works(self, test_client) -> None:
        """Test that existing failures mode is backwards compatible."""
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
                "jenkins_job_insight.main.run_parallel_with_limit",
                new_callable=AsyncMock,
            ) as mock_parallel:

                async def return_mock_results(coroutines, **kwargs):
                    for coro in coroutines:
                        coro.close()
                    return [[mock_analysis]]

                mock_parallel.side_effect = return_mock_results

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
                assert data["enriched_xml"] is None  # No enriched_xml in failures mode

    def test_raw_xml_enriched_xml_contains_analysis(self, test_client) -> None:
        """Test that enriched_xml contains ai_classification properties."""
        mock_analysis = FailureAnalysis(
            test_name="tests.test_auth.test_login",
            error="assert False",
            analysis=AnalysisDetail(
                classification="PRODUCT BUG",
                details="Auth service down",
            ),
        )

        with patch("jenkins_job_insight.main.RepositoryManager") as mock_repo_cls:
            mock_repo_instance = mock_repo_cls.return_value
            mock_repo_instance.clone.return_value = None
            mock_repo_instance.cleanup.return_value = None

            with patch(
                "jenkins_job_insight.main.run_parallel_with_limit",
                new_callable=AsyncMock,
            ) as mock_parallel:

                async def return_mock_results(coroutines, **kwargs):
                    for coro in coroutines:
                        coro.close()
                    return [[mock_analysis]]

                mock_parallel.side_effect = return_mock_results

                response = test_client.post(
                    "/analyze-failures",
                    json={
                        "raw_xml": self.SAMPLE_XML,
                        "ai_provider": "claude",
                        "ai_model": "test-model",
                    },
                )
                data = response.json()
                assert data["enriched_xml"] is not None
                assert "ai_classification" in data["enriched_xml"]
                assert "PRODUCT BUG" in data["enriched_xml"]


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
            assert data["base_url"] == "http://testserver"
            assert data["result_url"] == "http://testserver/results/job-123"

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

    def test_get_report_on_demand_generation(self, test_client) -> None:
        """Test on-demand HTML generation when cache misses but completed result exists."""
        stored_result = {
            "job_id": "on-demand-job",
            "status": "completed",
            "result": {
                "job_id": "on-demand-job",
                "status": "completed",
                "summary": "Analyzed 3 failures",
                "ai_provider": "claude",
                "ai_model": "test-model",
                "failures": [
                    {
                        "test_name": "test_example",
                        "error": "assert False",
                        "analysis": {
                            "classification": "CODE ISSUE",
                            "details": "Test assertion failed",
                        },
                    }
                ],
            },
            "created_at": "2026-01-01T00:00:00",
        }

        with patch(
            "jenkins_job_insight.main.get_html_report", new_callable=AsyncMock
        ) as mock_get_html:
            mock_get_html.return_value = None

            with patch(
                "jenkins_job_insight.main.get_result", new_callable=AsyncMock
            ) as mock_get_result:
                mock_get_result.return_value = stored_result

                with patch(
                    "jenkins_job_insight.main.format_result_as_html"
                ) as mock_format:
                    mock_format.return_value = (
                        "<html><body>Generated Report</body></html>"
                    )

                    with patch(
                        "jenkins_job_insight.main.save_html_report",
                        new_callable=AsyncMock,
                    ) as mock_save:
                        response = test_client.get("/results/on-demand-job.html")

                        assert response.status_code == 200
                        assert response.headers["content-type"].startswith("text/html")
                        assert "Generated Report" in response.text

                        # Verify format_result_as_html was called with correct AnalysisResult
                        mock_format.assert_called_once()
                        analysis_arg = mock_format.call_args[0][0]
                        assert analysis_arg.jenkins_url is None
                        assert analysis_arg.job_name == "Direct Failure Analysis"
                        assert analysis_arg.job_id == "on-demand-job"

                        # Verify disk caching was attempted
                        mock_save.assert_called_once_with(
                            "on-demand-job",
                            "<html><body>Generated Report</body></html>",
                        )

    def test_get_report_on_demand_generation_cache_failure(self, test_client) -> None:
        """Test that disk cache failure does not prevent serving the generated report."""
        stored_result = {
            "job_id": "cache-fail-job",
            "status": "completed",
            "result": {
                "job_id": "cache-fail-job",
                "status": "completed",
                "summary": "Analyzed 1 failure",
                "ai_provider": "claude",
                "ai_model": "test-model",
                "failures": [
                    {
                        "test_name": "test_example",
                        "error": "assert False",
                        "analysis": {
                            "classification": "CODE ISSUE",
                            "details": "Test assertion failed",
                        },
                    }
                ],
            },
            "created_at": "2026-01-01T00:00:00",
        }

        with patch(
            "jenkins_job_insight.main.get_html_report", new_callable=AsyncMock
        ) as mock_get_html:
            mock_get_html.return_value = None

            with patch(
                "jenkins_job_insight.main.get_result", new_callable=AsyncMock
            ) as mock_get_result:
                mock_get_result.return_value = stored_result

                with patch(
                    "jenkins_job_insight.main.format_result_as_html"
                ) as mock_format:
                    mock_format.return_value = "<html><body>Report</body></html>"

                    with patch(
                        "jenkins_job_insight.main.save_html_report",
                        new_callable=AsyncMock,
                        side_effect=OSError("Disk full"),
                    ):
                        response = test_client.get("/results/cache-fail-job.html")

                        assert response.status_code == 200
                        assert response.headers["content-type"].startswith("text/html")
                        assert "Report" in response.text

    def test_get_report_on_demand_generation_jenkins_path(self, test_client) -> None:
        """Test on-demand HTML generation for Jenkins analysis results (with jenkins_url)."""
        stored_result = {
            "job_id": "jenkins-job",
            "status": "completed",
            "result": {
                "job_id": "jenkins-job",
                "job_name": "my-pipeline",
                "build_number": 42,
                "jenkins_url": "https://jenkins.example.com/job/my-pipeline/42/",
                "status": "completed",
                "summary": "Analyzed 2 failures",
                "ai_provider": "claude",
                "ai_model": "test-model",
                "failures": [
                    {
                        "test_name": "test_example",
                        "error": "assert False",
                        "analysis": {
                            "classification": "CODE ISSUE",
                            "details": "Test assertion failed",
                        },
                    }
                ],
            },
            "created_at": "2026-01-01T00:00:00",
        }

        with patch(
            "jenkins_job_insight.main.get_html_report", new_callable=AsyncMock
        ) as mock_get_html:
            mock_get_html.return_value = None

            with patch(
                "jenkins_job_insight.main.get_result", new_callable=AsyncMock
            ) as mock_get_result:
                mock_get_result.return_value = stored_result

                with patch(
                    "jenkins_job_insight.main.format_result_as_html"
                ) as mock_format:
                    mock_format.return_value = (
                        "<html><body>Jenkins Report</body></html>"
                    )

                    with patch(
                        "jenkins_job_insight.main.save_html_report",
                        new_callable=AsyncMock,
                    ) as mock_save:
                        response = test_client.get("/results/jenkins-job.html")

                        assert response.status_code == 200
                        assert response.headers["content-type"].startswith("text/html")
                        assert "Jenkins Report" in response.text

                        # Verify format_result_as_html was called with AnalysisResult from model_validate path
                        mock_format.assert_called_once()
                        analysis_arg = mock_format.call_args[0][0]
                        assert analysis_arg.jenkins_url is not None
                        assert (
                            str(analysis_arg.jenkins_url)
                            == "https://jenkins.example.com/job/my-pipeline/42/"
                        )
                        assert analysis_arg.job_name == "my-pipeline"
                        assert analysis_arg.build_number == 42

                        # Verify disk caching was attempted
                        mock_save.assert_called_once()

    def test_get_report_refresh_forces_regeneration(self, test_client) -> None:
        """Test that ?refresh=1 skips cache and regenerates the HTML report."""
        stored_result = {
            "job_id": "refresh-job",
            "status": "completed",
            "result": {
                "job_id": "refresh-job",
                "status": "completed",
                "summary": "Analyzed 1 failure",
                "ai_provider": "claude",
                "ai_model": "test-model",
                "failures": [
                    {
                        "test_name": "test_refresh",
                        "error": "assert False",
                        "analysis": {
                            "classification": "CODE ISSUE",
                            "details": "Assertion failed",
                        },
                    }
                ],
            },
            "created_at": "2026-01-01T00:00:00",
        }

        cached_html = "<html><body>Cached Report v1</body></html>"
        regenerated_html = "<html><body>Regenerated Report v2</body></html>"

        # First request without refresh: serves the cached version
        with patch(
            "jenkins_job_insight.main.get_html_report", new_callable=AsyncMock
        ) as mock_get_html:
            mock_get_html.return_value = cached_html
            response = test_client.get("/results/refresh-job.html")
            assert response.status_code == 200
            assert "Cached Report v1" in response.text
            mock_get_html.assert_called_once()

        # Second request with ?refresh=1: bypasses cache and regenerates
        with patch(
            "jenkins_job_insight.main.get_html_report", new_callable=AsyncMock
        ) as mock_get_html:
            mock_get_html.return_value = cached_html

            with patch(
                "jenkins_job_insight.main.get_result", new_callable=AsyncMock
            ) as mock_get_result:
                mock_get_result.return_value = stored_result

                with patch(
                    "jenkins_job_insight.main.format_result_as_html"
                ) as mock_format:
                    mock_format.return_value = regenerated_html

                    with patch(
                        "jenkins_job_insight.main.save_html_report",
                        new_callable=AsyncMock,
                    ) as mock_save:
                        response = test_client.get(
                            "/results/refresh-job.html?refresh=1"
                        )

                        assert response.status_code == 200
                        assert response.headers["content-type"].startswith("text/html")
                        assert "Regenerated Report v2" in response.text

                        # get_html_report should NOT have been called (cache skipped)
                        mock_get_html.assert_not_called()

                        # format_result_as_html should have been called to regenerate
                        mock_format.assert_called_once()

                        # The regenerated report should be saved to cache
                        mock_save.assert_called_once_with(
                            "refresh-job", regenerated_html
                        )

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

    async def test_get_result_upgrades_legacy_relative_html_report_url(
        self, test_client, temp_db_path: Path
    ) -> None:
        """Test that legacy relative html_report_url is upgraded to absolute."""
        with patch.object(storage, "DB_PATH", temp_db_path):
            await storage.init_db()
            await storage.save_result(
                job_id="legacy-job",
                jenkins_url="https://jenkins.example.com/job/test/1/",
                status="completed",
                result={
                    "summary": "Done",
                    "html_report_url": "/results/legacy-job.html",
                },
            )

            response = test_client.get("/results/legacy-job")
            assert response.status_code == 200
            data = response.json()
            result_data = data.get("result", {})
            assert (
                result_data["html_report_url"]
                == "http://testserver/results/legacy-job.html"
            )


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


class TestDashboardEndpoint:
    """Tests for the GET /dashboard endpoint."""

    def test_dashboard_returns_html(self, test_client) -> None:
        """Test that GET /dashboard returns 200 with text/html content type."""
        response = test_client.get("/dashboard")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")

    def test_dashboard_contains_title(self, test_client) -> None:
        """Test that the dashboard HTML contains the application title."""
        response = test_client.get("/dashboard")
        assert response.status_code == 200
        assert "Jenkins Job Insight" in response.text

    def test_dashboard_empty_shows_message(self, test_client) -> None:
        """Test that an empty dashboard shows the 'No analysis results yet' message."""
        response = test_client.get("/dashboard")
        assert response.status_code == 200
        assert "No analysis results yet" in response.text

    async def test_dashboard_shows_jobs(self, test_client, temp_db_path: Path) -> None:
        """Test that stored jobs appear on the dashboard with links to HTML reports."""
        with patch.object(storage, "DB_PATH", temp_db_path):
            await storage.init_db()
            for i in range(3):
                await storage.save_result(
                    job_id=f"dash-job-{i}",
                    jenkins_url=f"https://jenkins.example.com/job/test/{i}/",
                    status="completed",
                    result={
                        "job_name": f"test-job-{i}",
                        "build_number": i + 1,
                        "failures": [{"test_name": "t"}] if i == 0 else [],
                    },
                )

        response = test_client.get("/dashboard")
        assert response.status_code == 200
        html = response.text
        for i in range(3):
            assert f"dash-job-{i}" in html
            assert f"/results/dash-job-{i}.html" in html

    async def test_dashboard_links_open_new_tab(
        self, test_client, temp_db_path: Path
    ) -> None:
        """Test that dashboard cards have target='_blank' for opening in new tabs."""
        with patch.object(storage, "DB_PATH", temp_db_path):
            await storage.init_db()
            await storage.save_result(
                job_id="tab-test-job",
                jenkins_url="https://jenkins.example.com/job/test/1/",
                status="completed",
                result={"job_name": "tab-test", "failures": []},
            )

            response = test_client.get("/dashboard")
            assert response.status_code == 200
            assert 'target="_blank"' in response.text

    async def test_dashboard_default_limit(
        self, test_client, temp_db_path: Path
    ) -> None:
        """Test that the dashboard default limit returns up to 500 jobs."""
        with patch.object(storage, "DB_PATH", temp_db_path):
            await storage.init_db()
            for i in range(10):
                await storage.save_result(
                    job_id=f"all-job-{i}",
                    jenkins_url=f"https://jenkins.example.com/job/test/{i}/",
                    status="completed",
                    result={"job_name": f"all-test-{i}", "failures": []},
                )

            response = test_client.get("/dashboard")
            assert response.status_code == 200
            html = response.text
            # All 10 cards should be present (fewer than default limit of 500)
            card_count = html.count('class="dashboard-card')
            assert card_count == 10

    async def test_dashboard_limit_parameter(
        self, test_client, temp_db_path: Path
    ) -> None:
        """Test that ?limit=3 caps the number of job cards returned."""
        with patch.object(storage, "DB_PATH", temp_db_path):
            await storage.init_db()
            for i in range(5):
                await storage.save_result(
                    job_id=f"lim-job-{i}",
                    jenkins_url=f"https://jenkins.example.com/job/test/{i}/",
                    status="completed",
                    result={"job_name": f"lim-test-{i}", "failures": []},
                )

            response = test_client.get("/dashboard?limit=3")
            assert response.status_code == 200
            html = response.text
            card_count = html.count('class="dashboard-card')
            assert card_count == 3

    def test_dashboard_limit_invalid_zero(self, test_client) -> None:
        """Test that limit=0 returns a validation error."""
        response = test_client.get("/dashboard?limit=0")
        assert response.status_code == 422

    def test_dashboard_limit_exceeds_max(self, test_client) -> None:
        """Test that limit above the maximum returns a validation error."""
        response = test_client.get("/dashboard?limit=99999")
        assert response.status_code == 422

    async def test_dashboard_completed_job_shows_passed_indicator(
        self, test_client, temp_db_path: Path
    ) -> None:
        """Test that completed jobs with no failures show a passed indicator."""
        with patch.object(storage, "DB_PATH", temp_db_path):
            await storage.init_db()
            await storage.save_result(
                job_id="passed-job",
                jenkins_url="https://jenkins.example.com/job/test/1/",
                status="completed",
                result={"job_name": "passing-job", "build_number": 1, "failures": []},
            )

        response = test_client.get("/dashboard")
        assert response.status_code == 200
        html = response.text
        assert "result-passed" in html
        assert "passed-badge" in html
        assert "passed</span>" in html

    async def test_dashboard_completed_job_shows_failure_indicator(
        self, test_client, temp_db_path: Path
    ) -> None:
        """Test that completed jobs with failures show a failure indicator."""
        with patch.object(storage, "DB_PATH", temp_db_path):
            await storage.init_db()
            await storage.save_result(
                job_id="failed-job",
                jenkins_url="https://jenkins.example.com/job/test/1/",
                status="completed",
                result={
                    "job_name": "failing-job",
                    "build_number": 1,
                    "failures": [{"test_name": "test_one"}, {"test_name": "test_two"}],
                },
            )

        response = test_client.get("/dashboard")
        assert response.status_code == 200
        html = response.text
        assert "result-failures" in html
        assert "has-failures" in html
        assert "2 failures" in html

    async def test_dashboard_counts_child_job_failures(
        self, test_client, temp_db_path: Path
    ) -> None:
        """Test that failures from child job analyses are included in the total count."""
        with patch.object(storage, "DB_PATH", temp_db_path):
            await storage.init_db()
            await storage.save_result(
                job_id="child-fail-job",
                jenkins_url="https://jenkins.example.com/job/test/1/",
                status="completed",
                result={
                    "job_name": "pipeline-job",
                    "build_number": 1,
                    "failures": [{"test_name": "top_level_fail"}],
                    "child_job_analyses": [
                        {
                            "job_name": "child-1",
                            "build_number": 1,
                            "failures": [
                                {"test_name": "child_fail_1"},
                                {"test_name": "child_fail_2"},
                            ],
                            "failed_children": [],
                        }
                    ],
                },
            )

        response = test_client.get("/dashboard")
        assert response.status_code == 200
        html = response.text
        assert "3 failures" in html
        assert "result-failures" in html

    async def test_dashboard_running_job_no_result_indicator(
        self, test_client, temp_db_path: Path
    ) -> None:
        """Test that running jobs do not show pass/fail result indicators."""
        with patch.object(storage, "DB_PATH", temp_db_path):
            await storage.init_db()
            await storage.save_result(
                job_id="running-job",
                jenkins_url="https://jenkins.example.com/job/test/1/",
                status="running",
            )

            response = test_client.get("/dashboard")
            assert response.status_code == 200
            html = response.text
            assert "dashboard-card result-passed" not in html
            assert "dashboard-card result-failures" not in html
            assert "card-result-icon passed" not in html
            assert "card-result-icon has-failures" not in html

    async def test_dashboard_shows_child_job_count(
        self, test_client, temp_db_path: Path
    ) -> None:
        """Test that dashboard cards show the number of child jobs when present."""
        with patch.object(storage, "DB_PATH", temp_db_path):
            await storage.init_db()
            await storage.save_result(
                job_id="pipeline-job",
                jenkins_url="https://jenkins.example.com/job/test/1/",
                status="completed",
                result={
                    "job_name": "pipeline-job",
                    "build_number": 1,
                    "failures": [],
                    "child_job_analyses": [
                        {
                            "job_name": "child-1",
                            "build_number": 1,
                            "failures": [],
                            "failed_children": [],
                        },
                        {
                            "job_name": "child-2",
                            "build_number": 2,
                            "failures": [],
                            "failed_children": [],
                        },
                        {
                            "job_name": "child-3",
                            "build_number": 3,
                            "failures": [],
                            "failed_children": [],
                        },
                    ],
                },
            )

            response = test_client.get("/dashboard")
            assert response.status_code == 200
            html = response.text
            assert "child-jobs-badge" in html
            assert "3 child jobs" in html


class TestFaviconEndpoint:
    """Tests for the GET /favicon.ico endpoint."""

    def test_favicon_returns_svg(self, test_client) -> None:
        """Test that GET /favicon.ico returns 200 with image/svg+xml content type."""
        response = test_client.get("/favicon.ico")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/svg+xml"

    def test_favicon_contains_svg_content(self, test_client) -> None:
        """Test that the favicon response body contains a valid SVG tag."""
        response = test_client.get("/favicon.ico")
        assert response.status_code == 200
        assert "<svg" in response.text

    def test_favicon_has_cache_control(self, test_client) -> None:
        """Test that the favicon response has a Cache-Control header with max-age."""
        response = test_client.get("/favicon.ico")
        assert response.status_code == 200
        cache_control = response.headers.get("cache-control", "")
        assert "max-age" in cache_control


class TestCommentEndpoints:
    @pytest.mark.asyncio
    async def test_add_comment(self, test_client):
        from jenkins_job_insight import storage

        result_data = {
            "status": "completed",
            "summary": "",
            "failures": [
                {
                    "test_name": "test_foo",
                    "error": "some error",
                    "analysis": {"classification": "CODE ISSUE"},
                }
            ],
        }
        await storage.save_result(
            "job-test-1", "http://jenkins", "completed", result_data
        )
        response = test_client.post(
            "/results/job-test-1/comments",
            json={"test_name": "test_foo", "comment": "opened bug"},
        )
        assert response.status_code == 201
        assert "id" in response.json()

    @pytest.mark.asyncio
    async def test_get_comments(self, test_client):
        from jenkins_job_insight import storage

        result_data = {
            "status": "completed",
            "summary": "",
            "failures": [
                {
                    "test_name": "test_foo",
                    "error": "err",
                    "analysis": {"classification": "CODE ISSUE"},
                }
            ],
        }
        await storage.save_result(
            "job-test-2", "http://jenkins", "completed", result_data
        )
        await storage.add_comment("job-test-2", "test_foo", "comment 1")
        response = test_client.get("/results/job-test-2/comments")
        assert response.status_code == 200
        data = response.json()
        assert "comments" in data
        assert "reviews" in data
        assert len(data["comments"]) == 1

    @pytest.mark.asyncio
    async def test_add_comment_nonexistent_job(self, test_client):
        response = test_client.post(
            "/results/nonexistent/comments",
            json={"test_name": "test_foo", "comment": "test"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_add_comment_invalid_test_name(self, test_client):
        from jenkins_job_insight import storage

        result_data = {
            "status": "completed",
            "summary": "",
            "failures": [
                {
                    "test_name": "test_foo",
                    "error": "err",
                    "analysis": {"classification": "CODE ISSUE"},
                }
            ],
        }
        await storage.save_result(
            "job-test-3", "http://jenkins", "completed", result_data
        )
        response = test_client.post(
            "/results/job-test-3/comments",
            json={"test_name": "nonexistent_test", "comment": "test"},
        )
        assert response.status_code == 400


class TestReviewedEndpoint:
    @pytest.mark.asyncio
    async def test_set_reviewed(self, test_client):
        from jenkins_job_insight import storage

        result_data = {
            "status": "completed",
            "summary": "",
            "failures": [
                {
                    "test_name": "test_foo",
                    "error": "err",
                    "analysis": {"classification": "CODE ISSUE"},
                }
            ],
        }
        await storage.save_result(
            "job-rev-1", "http://jenkins", "completed", result_data
        )
        response = test_client.put(
            "/results/job-rev-1/reviewed",
            json={"test_name": "test_foo", "reviewed": True},
        )
        assert response.status_code == 200
        response = test_client.get("/results/job-rev-1/comments")
        data = response.json()
        assert "test_foo" in data["reviews"]
        assert data["reviews"]["test_foo"]["reviewed"] is True

    @pytest.mark.asyncio
    async def test_set_reviewed_nonexistent_job(self, test_client):
        response = test_client.put(
            "/results/nonexistent/reviewed",
            json={"test_name": "test_foo", "reviewed": True},
        )
        assert response.status_code == 404


class TestReviewStatusEndpoint:
    @pytest.mark.asyncio
    async def test_get_review_status(self, test_client):
        from jenkins_job_insight import storage

        result_data = {
            "status": "completed",
            "summary": "",
            "failures": [
                {
                    "test_name": "test_a",
                    "error": "err",
                    "analysis": {"classification": "CODE ISSUE"},
                },
                {
                    "test_name": "test_b",
                    "error": "err",
                    "analysis": {"classification": "PRODUCT BUG"},
                },
            ],
        }
        await storage.save_result(
            "job-rs-1", "http://jenkins", "completed", result_data
        )
        await storage.set_reviewed("job-rs-1", "test_a", reviewed=True)
        await storage.add_comment("job-rs-1", "test_a", "bug opened")
        response = test_client.get("/results/job-rs-1/review-status")
        assert response.status_code == 200
        data = response.json()
        assert data["total_failures"] == 2
        assert data["reviewed_count"] == 1
        assert data["comment_count"] == 1


class TestChildScopeValidation:
    @pytest.mark.asyncio
    async def test_comment_child_job_without_build_number_rejected(self, test_client):
        """child_job_name without child_build_number should be rejected (422)."""
        result_data = {
            "status": "completed",
            "summary": "",
            "failures": [
                {
                    "test_name": "test_foo",
                    "error": "err",
                    "analysis": {"classification": "CODE ISSUE"},
                }
            ],
        }
        await storage.save_result(
            "job-val-1", "http://jenkins", "completed", result_data
        )
        response = test_client.post(
            "/results/job-val-1/comments",
            json={
                "test_name": "test_foo",
                "child_job_name": "child-1",
                "comment": "test",
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_comment_build_number_without_child_job_rejected(self, test_client):
        """child_build_number without child_job_name should be rejected (422)."""
        result_data = {
            "status": "completed",
            "summary": "",
            "failures": [
                {
                    "test_name": "test_foo",
                    "error": "err",
                    "analysis": {"classification": "CODE ISSUE"},
                }
            ],
        }
        await storage.save_result(
            "job-val-2", "http://jenkins", "completed", result_data
        )
        response = test_client.post(
            "/results/job-val-2/comments",
            json={
                "test_name": "test_foo",
                "child_build_number": 42,
                "comment": "test",
            },
        )
        assert response.status_code == 422
