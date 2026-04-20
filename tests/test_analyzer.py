"""Tests for analyzer module."""

from unittest.mock import AsyncMock, MagicMock, patch

import jenkins
import pytest
from fastapi import HTTPException

from jenkins_job_insight.analyzer import (
    _JSON_RESPONSE_SCHEMA,
    _build_resources_section,
    _call_ai_cli_with_retry,
    handle_jenkins_exception,
)
from jenkins_job_insight.config import Settings

_FAKE_JENKINS_PASSWORD = "test-pass"  # noqa: S105  # pragma: allowlist secret


class TestHandleJenkinsException:
    """Tests for the handle_jenkins_exception function."""

    def test_handle_not_found_exception(self) -> None:
        """Test that NotFoundException returns 404."""
        exc = jenkins.NotFoundException("Job not found")
        with pytest.raises(HTTPException) as exc_info:
            handle_jenkins_exception(exc, "my-job", 123)
        assert exc_info.value.status_code == 404
        assert "my-job" in exc_info.value.detail
        assert "123" in exc_info.value.detail

    def test_handle_jenkins_exception_with_not_found_message(self) -> None:
        """Test that JenkinsException with 'not found' message returns 404."""
        exc = jenkins.JenkinsException("Job does not exist")
        with pytest.raises(HTTPException) as exc_info:
            handle_jenkins_exception(exc, "my-job", 456)
        assert exc_info.value.status_code == 404

    def test_handle_jenkins_exception_with_404_message(self) -> None:
        """Test that JenkinsException with '404' in message returns 404."""
        exc = jenkins.JenkinsException("Error 404: Resource not available")
        with pytest.raises(HTTPException) as exc_info:
            handle_jenkins_exception(exc, "my-job", 789)
        assert exc_info.value.status_code == 404

    def test_handle_jenkins_exception_unauthorized(self) -> None:
        """Test that unauthorized error returns 502 with auth message."""
        exc = jenkins.JenkinsException("401 Unauthorized")
        with pytest.raises(HTTPException) as exc_info:
            handle_jenkins_exception(exc, "my-job", 123)
        assert exc_info.value.status_code == 502
        assert "authentication failed" in exc_info.value.detail.lower()

    def test_handle_jenkins_exception_forbidden(self) -> None:
        """Test that forbidden error returns 502 with permission message."""
        exc = jenkins.JenkinsException("403 Forbidden")
        with pytest.raises(HTTPException) as exc_info:
            handle_jenkins_exception(exc, "my-job", 123)
        assert exc_info.value.status_code == 502
        assert "access denied" in exc_info.value.detail.lower()
        assert "my-job" in exc_info.value.detail

    def test_handle_jenkins_exception_generic(self) -> None:
        """Test that generic JenkinsException returns 502 with error details."""
        exc = jenkins.JenkinsException("Connection timeout")
        with pytest.raises(HTTPException) as exc_info:
            handle_jenkins_exception(exc, "my-job", 123)
        assert exc_info.value.status_code == 502
        assert "Jenkins error" in exc_info.value.detail

    def test_handle_non_jenkins_exception(self) -> None:
        """Test that non-Jenkins exceptions return 502 with connection error."""
        exc = ValueError("Some other error")
        with pytest.raises(HTTPException) as exc_info:
            handle_jenkins_exception(exc, "my-job", 123)
        assert exc_info.value.status_code == 502
        assert "Failed to connect to Jenkins" in exc_info.value.detail

    def test_handle_timeout_exception(self) -> None:
        """Test that timeout returns 504 with generic message."""
        import requests

        exc = requests.exceptions.Timeout("Connection timed out")
        with pytest.raises(HTTPException) as exc_info:
            handle_jenkins_exception(exc, "my-job", 123)
        assert exc_info.value.status_code == 504
        assert (
            exc_info.value.detail
            == "Jenkins is unreachable or timed out. Check server connectivity."
        )
        # Raw exception message must not leak into the HTTP response
        assert "Connection timed out" not in exc_info.value.detail

    def test_handle_connection_error_exception(self) -> None:
        """Test that connection error returns 504 with generic message."""
        import requests

        exc = requests.exceptions.ConnectionError("Connection refused")
        with pytest.raises(HTTPException) as exc_info:
            handle_jenkins_exception(exc, "my-job", 123)
        assert exc_info.value.status_code == 504
        assert (
            exc_info.value.detail
            == "Jenkins is unreachable or timed out. Check server connectivity."
        )
        # Raw exception message must not leak into the HTTP response
        assert "Connection refused" not in exc_info.value.detail


class TestCallAiCliWithRetry:
    """Tests for the _call_ai_cli_with_retry function."""

    @pytest.mark.asyncio
    async def test_success_no_retry(self) -> None:
        """Test that a successful first call does not retry."""
        with patch(
            "jenkins_job_insight.analyzer.call_ai_cli", new_callable=AsyncMock
        ) as mock:
            mock.return_value = (True, "result")
            success, output = await _call_ai_cli_with_retry(
                "prompt", ai_provider="test"
            )
            assert success is True
            assert output == "result"
            assert mock.call_count == 1

    @pytest.mark.asyncio
    async def test_retryable_error_retries(self) -> None:
        """Test that a retryable error triggers a retry and succeeds."""
        with (
            patch(
                "jenkins_job_insight.analyzer.call_ai_cli", new_callable=AsyncMock
            ) as mock,
            patch("jenkins_job_insight.analyzer.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock.side_effect = [
                (False, "ENOENT: no such file or directory, rename config"),
                (True, "success after retry"),
            ]
            success, output = await _call_ai_cli_with_retry(
                "prompt", ai_provider="test", max_retries=1
            )
            assert success is True
            assert output == "success after retry"
            assert mock.call_count == 2

    @pytest.mark.asyncio
    async def test_non_retryable_error_no_retry(self) -> None:
        """Test that a non-retryable error does not trigger a retry."""
        with patch(
            "jenkins_job_insight.analyzer.call_ai_cli", new_callable=AsyncMock
        ) as mock:
            mock.return_value = (False, "some other error")
            success, output = await _call_ai_cli_with_retry(
                "prompt", ai_provider="test", max_retries=3
            )
            assert success is False
            assert "some other error" in output
            assert mock.call_count == 1

    @pytest.mark.asyncio
    async def test_max_retries_exhausted(self) -> None:
        """Test that retries stop after max_retries is exhausted."""
        with (
            patch(
                "jenkins_job_insight.analyzer.call_ai_cli", new_callable=AsyncMock
            ) as mock,
            patch("jenkins_job_insight.analyzer.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock.return_value = (False, "ENOENT: no such file or directory")
            success, _ = await _call_ai_cli_with_retry(
                "prompt", ai_provider="test", max_retries=2
            )
            assert success is False
            assert mock.call_count == 3  # initial + 2 retries


class TestRunSingleAiAnalysis:
    """Tests for the _run_single_ai_analysis shared helper."""

    @pytest.mark.asyncio
    async def test_returns_parsed_analysis_and_signature(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Successful AI call returns parsed AnalysisDetail and error signature."""
        from jenkins_job_insight.analyzer import _run_single_ai_analysis
        from jenkins_job_insight.models import TestFailure
        import json

        ai_response = json.dumps(
            {
                "classification": "CODE ISSUE",
                "affected_tests": ["test_foo"],
                "details": "broken assertion",
            }
        )
        mock_cli = AsyncMock(return_value=(True, ai_response))
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer._call_ai_cli_with_retry", mock_cli
        )

        failure = TestFailure(
            test_name="test_foo", error_message="AssertionError", stack_trace="line 42"
        )
        parsed, sig = await _run_single_ai_analysis(
            failures=[failure],
            console_context="console lines",
            repo_path=None,
            ai_provider="claude",
            ai_model="opus",
            ai_cli_timeout=None,
            custom_prompt="",
            artifacts_context="",
            server_url="",
            job_id="",
        )
        assert parsed.classification == "CODE ISSUE"
        assert parsed.details == "broken assertion"
        assert isinstance(sig, str) and len(sig) == 64  # SHA-256 hex

    @pytest.mark.asyncio
    async def test_failed_ai_call_returns_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Failed AI call returns AnalysisDetail with raw output in details."""
        from jenkins_job_insight.analyzer import _run_single_ai_analysis
        from jenkins_job_insight.models import TestFailure

        mock_cli = AsyncMock(return_value=(False, "CLI timeout"))
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer._call_ai_cli_with_retry", mock_cli
        )

        failure = TestFailure(
            test_name="test_bar", error_message="err", stack_trace="st"
        )
        parsed, sig = await _run_single_ai_analysis(
            failures=[failure],
            console_context="",
            repo_path=None,
            ai_provider="claude",
            ai_model="opus",
            ai_cli_timeout=None,
            custom_prompt="",
            artifacts_context="",
            server_url="",
            job_id="",
        )
        assert parsed.details == "CLI timeout"
        assert parsed.classification == ""
        assert isinstance(sig, str) and len(sig) == 64

    @pytest.mark.asyncio
    async def test_peer_analysis_uses_shared_helper(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Peer analysis module calls _run_single_ai_analysis for the orchestrator's initial analysis."""
        from jenkins_job_insight.peer_analysis import analyze_failure_group_with_peers
        from jenkins_job_insight.models import (
            AiConfigEntry,
            AnalysisDetail,
            TestFailure,
        )

        # Mock _run_single_ai_analysis to track that it was called
        mock_run = AsyncMock(
            return_value=(
                AnalysisDetail(classification="CODE ISSUE", details="test"),
                "abc123sig",
            )
        )
        monkeypatch.setattr(
            "jenkins_job_insight.peer_analysis._run_single_ai_analysis", mock_run
        )

        # Mock peer calls to agree immediately
        import json

        peer_response = json.dumps(
            {
                "agrees": True,
                "classification": "CODE ISSUE",
                "reasoning": "agree",
                "suggested_changes": "",
            }
        )
        mock_cli = AsyncMock(return_value=(True, peer_response))
        monkeypatch.setattr(
            "jenkins_job_insight.peer_analysis._call_ai_cli_with_retry", mock_cli
        )

        failure = TestFailure(
            test_name="test_foo", error_message="err", stack_trace="st"
        )
        peers = [AiConfigEntry(ai_provider="gemini", ai_model="pro")]

        await analyze_failure_group_with_peers(
            failures=[failure],
            console_context="console",
            repo_path=None,
            main_ai_provider="claude",
            main_ai_model="opus",
            peer_ai_configs=peers,
            max_rounds=1,
        )

        # _run_single_ai_analysis must have been called for the orchestrator
        assert mock_run.called
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["ai_provider"] == "claude"
        assert call_kwargs["ai_model"] == "opus"


class TestAnalyzeFailureGroupPeerDelegation:
    """Tests for peer analysis delegation in analyze_failure_group."""

    @pytest.mark.asyncio
    async def test_delegates_to_peer_analysis_when_peers_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When peer_ai_configs is provided, delegates to peer analysis module."""
        from jenkins_job_insight.analyzer import TestFailure, analyze_failure_group
        from jenkins_job_insight.models import (
            AiConfigEntry,
            AnalysisDetail,
            FailureAnalysis,
        )

        expected_result = [
            FailureAnalysis(
                test_name="test_foo",
                error="err",
                analysis=AnalysisDetail(details="d", classification="CODE ISSUE"),
                error_signature="sig",
            )
        ]
        mock_peer = AsyncMock(return_value=expected_result)

        # Patch the function at the module level where it will be imported
        monkeypatch.setattr(
            "jenkins_job_insight.peer_analysis.analyze_failure_group_with_peers",
            mock_peer,
        )

        failure = TestFailure(
            test_name="test_foo", error_message="err", stack_trace="st"
        )
        peers = [
            AiConfigEntry(ai_provider="cursor", ai_model="gpt"),
            AiConfigEntry(ai_provider="gemini", ai_model="pro"),
        ]

        result = await analyze_failure_group(
            [failure],
            "",
            None,
            ai_provider="claude",
            ai_model="opus",
            peer_ai_configs=peers,
        )
        assert mock_peer.called
        assert result == expected_result
        # Verify correct arguments were passed
        call_kwargs = mock_peer.call_args
        assert call_kwargs.kwargs["main_ai_provider"] == "claude"
        assert call_kwargs.kwargs["main_ai_model"] == "opus"
        assert call_kwargs.kwargs["peer_ai_configs"] == peers
        assert call_kwargs.kwargs["max_rounds"] == 3  # default

    @pytest.mark.asyncio
    async def test_custom_max_rounds_passed_to_peers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """peer_analysis_max_rounds is forwarded as max_rounds."""
        from jenkins_job_insight.analyzer import TestFailure, analyze_failure_group
        from jenkins_job_insight.models import (
            AiConfigEntry,
            AnalysisDetail,
            FailureAnalysis,
        )

        mock_peer = AsyncMock(
            return_value=[
                FailureAnalysis(
                    test_name="t",
                    error="e",
                    analysis=AnalysisDetail(details="d"),
                    error_signature="s",
                )
            ]
        )
        monkeypatch.setattr(
            "jenkins_job_insight.peer_analysis.analyze_failure_group_with_peers",
            mock_peer,
        )

        failure = TestFailure(
            test_name="test_bar", error_message="err", stack_trace="st"
        )
        peers = [AiConfigEntry(ai_provider="gemini", ai_model="pro")]

        await analyze_failure_group(
            [failure],
            "",
            None,
            ai_provider="claude",
            ai_model="opus",
            peer_ai_configs=peers,
            peer_analysis_max_rounds=5,
        )
        assert mock_peer.call_args.kwargs["max_rounds"] == 5

    @pytest.mark.asyncio
    async def test_no_delegation_without_peers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When no peer_ai_configs, uses single-AI path."""
        from jenkins_job_insight.analyzer import TestFailure, analyze_failure_group

        mock_cli = AsyncMock(
            return_value=(
                True,
                '{"classification":"CODE ISSUE","affected_tests":["t"],"details":"d"}',
            )
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer._call_ai_cli_with_retry", mock_cli
        )

        failure = TestFailure(
            test_name="test_foo", error_message="err", stack_trace="st"
        )

        result = await analyze_failure_group(
            [failure], "", None, ai_provider="claude", ai_model="opus"
        )
        assert mock_cli.called  # Used single-AI path
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_dict_peer_configs_converted_to_models(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Dict-form peer configs are converted to AiConfigEntry objects."""
        from jenkins_job_insight.analyzer import TestFailure, analyze_failure_group
        from jenkins_job_insight.models import (
            AiConfigEntry,
            AnalysisDetail,
            FailureAnalysis,
        )

        mock_peer = AsyncMock(
            return_value=[
                FailureAnalysis(
                    test_name="t",
                    error="e",
                    analysis=AnalysisDetail(details="d"),
                    error_signature="s",
                )
            ]
        )
        monkeypatch.setattr(
            "jenkins_job_insight.peer_analysis.analyze_failure_group_with_peers",
            mock_peer,
        )

        failure = TestFailure(
            test_name="test_baz", error_message="err", stack_trace="st"
        )
        # Pass dicts instead of AiConfigEntry objects
        peers = [{"ai_provider": "cursor", "ai_model": "gpt"}]

        await analyze_failure_group(
            [failure],
            "",
            None,
            ai_provider="claude",
            ai_model="opus",
            peer_ai_configs=peers,
        )
        assert mock_peer.called
        passed_configs = mock_peer.call_args.kwargs["peer_ai_configs"]
        assert all(isinstance(c, AiConfigEntry) for c in passed_configs)

    @pytest.mark.asyncio
    async def test_group_label_forwarded_to_peer_analysis(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """group_label is forwarded from analyze_failure_group to analyze_failure_group_with_peers."""
        from jenkins_job_insight.analyzer import TestFailure, analyze_failure_group
        from jenkins_job_insight.models import (
            AiConfigEntry,
            AnalysisDetail,
            FailureAnalysis,
        )

        mock_peer = AsyncMock(
            return_value=[
                FailureAnalysis(
                    test_name="t",
                    error="e",
                    analysis=AnalysisDetail(details="d"),
                    error_signature="s",
                )
            ]
        )
        monkeypatch.setattr(
            "jenkins_job_insight.peer_analysis.analyze_failure_group_with_peers",
            mock_peer,
        )

        failure = TestFailure(
            test_name="test_foo", error_message="err", stack_trace="st"
        )
        peers = [AiConfigEntry(ai_provider="gemini", ai_model="pro")]

        await analyze_failure_group(
            [failure],
            "",
            None,
            ai_provider="claude",
            ai_model="opus",
            peer_ai_configs=peers,
            group_label="2/5",
        )
        assert mock_peer.call_args.kwargs["group_label"] == "2/5"

    @pytest.mark.asyncio
    async def test_group_label_defaults_to_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """group_label defaults to empty string when not provided."""
        from jenkins_job_insight.analyzer import TestFailure, analyze_failure_group
        from jenkins_job_insight.models import (
            AiConfigEntry,
            AnalysisDetail,
            FailureAnalysis,
        )

        mock_peer = AsyncMock(
            return_value=[
                FailureAnalysis(
                    test_name="t",
                    error="e",
                    analysis=AnalysisDetail(details="d"),
                    error_signature="s",
                )
            ]
        )
        monkeypatch.setattr(
            "jenkins_job_insight.peer_analysis.analyze_failure_group_with_peers",
            mock_peer,
        )

        failure = TestFailure(
            test_name="test_foo", error_message="err", stack_trace="st"
        )
        peers = [AiConfigEntry(ai_provider="gemini", ai_model="pro")]

        await analyze_failure_group(
            [failure],
            "",
            None,
            ai_provider="claude",
            ai_model="opus",
            peer_ai_configs=peers,
        )
        assert mock_peer.call_args.kwargs["group_label"] == ""


class TestConsoleOnlyPeerWarning:
    """Tests that console-only fallback branches warn when peer analysis is configured."""

    @pytest.mark.asyncio
    async def test_child_job_console_only_warns_when_peers_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """analyze_child_job console-only path logs warning when peer_ai_configs set."""
        from jenkins_job_insight.analyzer import analyze_child_job
        from jenkins_job_insight.models import AiConfigEntry

        mock_client = MagicMock()
        mock_client.get_build_info_safe.return_value = {
            "result": "FAILURE",
            "building": False,
        }
        mock_client.get_build_console.return_value = "Build failed with error"
        mock_client.get_test_report.return_value = None

        async def fake_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.asyncio.to_thread",
            fake_to_thread,
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer._call_ai_cli_with_retry",
            AsyncMock(
                return_value=(True, '{"classification": "CODE ISSUE", "details": "d"}')
            ),
        )

        peers = [AiConfigEntry(ai_provider="gemini", ai_model="pro")]

        with patch("jenkins_job_insight.analyzer.logger") as mock_logger:
            await analyze_child_job(
                job_name="child-job",
                build_number=1,
                jenkins_client=mock_client,
                jenkins_base_url="https://jenkins.example.com",
                peer_ai_configs=peers,
            )

            mock_logger.warning.assert_any_call(
                "Peer analysis not supported for console-only failures (no test report)"
            )

    @pytest.mark.asyncio
    async def test_child_job_console_only_no_warning_without_peers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """analyze_child_job console-only path does NOT warn when no peers."""
        from jenkins_job_insight.analyzer import analyze_child_job

        mock_client = MagicMock()
        mock_client.get_build_info_safe.return_value = {
            "result": "FAILURE",
            "building": False,
        }
        mock_client.get_build_console.return_value = "Build failed with error"
        mock_client.get_test_report.return_value = None

        async def fake_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.asyncio.to_thread",
            fake_to_thread,
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer._call_ai_cli_with_retry",
            AsyncMock(
                return_value=(True, '{"classification": "CODE ISSUE", "details": "d"}')
            ),
        )

        with patch("jenkins_job_insight.analyzer.logger") as mock_logger:
            await analyze_child_job(
                job_name="child-job",
                build_number=1,
                jenkins_client=mock_client,
                jenkins_base_url="https://jenkins.example.com",
                peer_ai_configs=None,
            )

            # Ensure no warning about peer analysis was logged
            for call in mock_logger.warning.call_args_list:
                assert "Peer analysis not supported" not in str(call)

    @pytest.mark.asyncio
    async def test_analyze_job_console_only_warns_when_peers_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """analyze_job console-only path logs warning when peer_ai_configs set."""
        from jenkins_job_insight.analyzer import analyze_job
        from jenkins_job_insight.models import AiConfigEntry, AnalyzeRequest

        body = AnalyzeRequest(
            job_name="my-job",
            build_number=123,
        )
        settings = Settings()
        settings_data = settings.model_dump(mode="python")
        settings_data["jenkins_url"] = "https://jenkins.example.com"
        settings_data["jenkins_user"] = "user"
        settings_data["jenkins_password"] = _FAKE_JENKINS_PASSWORD
        merged = Settings.model_validate(settings_data)

        mock_client = MagicMock()
        mock_client.get_build_info_safe.return_value = {
            "result": "FAILURE",
            "building": False,
        }
        mock_client.get_build_console.return_value = "Build failed with error"
        mock_client.get_test_report.return_value = None
        mock_client.session = MagicMock()

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.JenkinsClient",
            lambda **kwargs: mock_client,
        )

        async def fake_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.asyncio.to_thread",
            fake_to_thread,
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.check_ai_cli_available",
            AsyncMock(return_value=(True, "")),
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer._call_ai_cli_with_retry",
            AsyncMock(
                return_value=(True, '{"classification": "CODE ISSUE", "details": "d"}')
            ),
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.update_progress_phase",
            AsyncMock(),
        )

        peers = [AiConfigEntry(ai_provider="gemini", ai_model="pro")]

        with patch("jenkins_job_insight.analyzer.logger") as mock_logger:
            await analyze_job(
                body,
                merged,
                ai_provider="claude",
                ai_model="test-model",
                job_id="test-job-id",
                peer_ai_configs=peers,
            )

            mock_logger.warning.assert_any_call(
                "Peer analysis not supported for console-only failures (no test report)"
            )


class TestAnalyzeJobProgressPhases:
    """Tests for progress phase updates in analyze_job."""

    @pytest.mark.asyncio
    async def test_analyze_job_emits_analyzing_child_jobs_phase(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When there are failed child jobs, emits analyzing_child_jobs phase."""
        from jenkins_job_insight.analyzer import analyze_job
        from jenkins_job_insight.models import AnalyzeRequest, ChildJobAnalysis

        body = AnalyzeRequest(
            job_name="pipeline-job",
            build_number=42,
        )
        settings = Settings()
        settings_data = settings.model_dump(mode="python")
        settings_data["jenkins_url"] = "https://jenkins.example.com"
        settings_data["jenkins_user"] = "user"
        settings_data["jenkins_password"] = _FAKE_JENKINS_PASSWORD
        merged = Settings.model_validate(settings_data)

        phases: list[str] = []

        async def capture_phase(job_id, phase):
            phases.append(phase)

        mock_client = MagicMock()
        mock_client.get_build_info_safe.return_value = {
            "result": "FAILURE",
            "building": False,
            "subBuilds": [
                {"jobName": "child-job", "buildNumber": 1, "result": "FAILURE"}
            ],
        }
        mock_client.get_build_console.return_value = "Build failed"
        mock_client.get_test_report.return_value = None

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.JenkinsClient",
            lambda **kwargs: mock_client,
        )

        async def fake_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.asyncio.to_thread",
            fake_to_thread,
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.check_ai_cli_available",
            AsyncMock(return_value=(True, "")),
        )

        # Mock child job analysis
        child_result = ChildJobAnalysis(
            job_name="child-job",
            build_number=1,
            jenkins_url="https://jenkins.example.com/job/child-job/1/",
            summary="1 failure analyzed",
            failures=[],
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.analyze_child_job",
            AsyncMock(return_value=child_result),
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.run_parallel_with_limit",
            AsyncMock(return_value=[child_result]),
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.update_progress_phase",
            AsyncMock(side_effect=capture_phase),
        )

        await analyze_job(
            body,
            merged,
            ai_provider="claude",
            ai_model="test-model",
            job_id="test-job-id",
        )

        assert "analyzing_child_jobs" in phases

    @pytest.mark.asyncio
    async def test_analyze_job_emits_analyzing_failures_phase(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When there are test failures, emits analyzing_failures phase."""
        from jenkins_job_insight.analyzer import analyze_job
        from jenkins_job_insight.models import (
            AnalysisDetail,
            AnalyzeRequest,
            FailureAnalysis,
        )

        body = AnalyzeRequest(
            job_name="my-job",
            build_number=123,
        )
        settings = Settings()
        settings_data = settings.model_dump(mode="python")
        settings_data["jenkins_url"] = "https://jenkins.example.com"
        settings_data["jenkins_user"] = "user"
        settings_data["jenkins_password"] = _FAKE_JENKINS_PASSWORD
        merged = Settings.model_validate(settings_data)

        phases: list[str] = []

        async def capture_phase(job_id, phase):
            phases.append(phase)

        mock_client = MagicMock()
        mock_client.get_build_info_safe.return_value = {
            "result": "FAILURE",
            "building": False,
        }
        mock_client.get_build_console.return_value = (
            "Test failed: test_foo\nBuild finished"
        )
        mock_client.get_test_report.return_value = {
            "suites": [
                {
                    "cases": [
                        {
                            "className": "com.example",
                            "name": "test_foo",
                            "status": "FAILED",
                            "errorDetails": "AssertionError",
                            "errorStackTrace": "at line 42",
                        }
                    ]
                }
            ]
        }
        mock_client.session = MagicMock()

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.JenkinsClient",
            lambda **kwargs: mock_client,
        )

        async def fake_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.asyncio.to_thread",
            fake_to_thread,
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.check_ai_cli_available",
            AsyncMock(return_value=(True, "")),
        )

        mock_failure = FailureAnalysis(
            test_name="com.example.test_foo",
            error="AssertionError",
            analysis=AnalysisDetail(
                classification="CODE ISSUE", details="broken assertion"
            ),
            error_signature="sig123",
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.analyze_failure_group",
            AsyncMock(return_value=[mock_failure]),
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.run_parallel_with_limit",
            AsyncMock(return_value=[[mock_failure]]),
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.update_progress_phase",
            AsyncMock(side_effect=capture_phase),
        )

        await analyze_job(
            body,
            merged,
            ai_provider="claude",
            ai_model="test-model",
            job_id="test-job-id",
        )

        assert "analyzing_failures" in phases

    @pytest.mark.asyncio
    async def test_no_progress_phase_when_job_id_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When job_id is None, update_progress_phase should not be called."""
        from jenkins_job_insight.analyzer import analyze_job
        from jenkins_job_insight.models import AnalyzeRequest

        body = AnalyzeRequest(
            job_name="my-job",
            build_number=123,
        )
        settings = Settings()
        settings_data = settings.model_dump(mode="python")
        settings_data["jenkins_url"] = "https://jenkins.example.com"
        settings_data["jenkins_user"] = "user"
        settings_data["jenkins_password"] = _FAKE_JENKINS_PASSWORD
        merged = Settings.model_validate(settings_data)

        mock_client = MagicMock()
        mock_client.get_build_info_safe.return_value = {
            "result": "SUCCESS",
            "building": False,
        }

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.JenkinsClient",
            lambda **kwargs: mock_client,
        )

        async def fake_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.asyncio.to_thread",
            fake_to_thread,
        )

        mock_update = AsyncMock()
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.update_progress_phase",
            mock_update,
        )

        # job_id=None should not trigger any phase updates
        await analyze_job(
            body,
            merged,
            ai_provider="claude",
            ai_model="test-model",
            job_id=None,
        )

        mock_update.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_progress_phase_when_job_id_none_with_failures(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When job_id is None and build has test failures, update_progress_phase should not be called.

        This covers the case where a synthetic UUID is generated internally
        but progress writes are skipped because no persisted job exists.
        """
        from jenkins_job_insight.analyzer import analyze_job
        from jenkins_job_insight.models import (
            AnalysisDetail,
            AnalyzeRequest,
            FailureAnalysis,
        )

        body = AnalyzeRequest(
            job_name="my-job",
            build_number=123,
        )
        settings = Settings()
        settings_data = settings.model_dump(mode="python")
        settings_data["jenkins_url"] = "https://jenkins.example.com"
        settings_data["jenkins_user"] = "user"
        settings_data["jenkins_password"] = _FAKE_JENKINS_PASSWORD
        merged = Settings.model_validate(settings_data)

        mock_client = MagicMock()
        mock_client.get_build_info_safe.return_value = {
            "result": "FAILURE",
            "building": False,
        }
        mock_client.get_build_console.return_value = (
            "Test failed: test_foo\nBuild finished"
        )
        mock_client.get_test_report.return_value = {
            "suites": [
                {
                    "cases": [
                        {
                            "className": "com.example",
                            "name": "test_foo",
                            "status": "FAILED",
                            "errorDetails": "AssertionError",
                            "errorStackTrace": "at line 42",
                        }
                    ]
                }
            ]
        }
        mock_client.session = MagicMock()

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.JenkinsClient",
            lambda **kwargs: mock_client,
        )

        async def fake_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.asyncio.to_thread",
            fake_to_thread,
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.check_ai_cli_available",
            AsyncMock(return_value=(True, "")),
        )

        mock_failure = FailureAnalysis(
            test_name="com.example.test_foo",
            error="AssertionError",
            analysis=AnalysisDetail(
                classification="CODE ISSUE", details="broken assertion"
            ),
            error_signature="sig123",
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.analyze_failure_group",
            AsyncMock(return_value=[mock_failure]),
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.run_parallel_with_limit",
            AsyncMock(return_value=[[mock_failure]]),
        )

        mock_update = AsyncMock()
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.update_progress_phase",
            mock_update,
        )

        # job_id=None with actual failures should still not trigger phase updates
        await analyze_job(
            body,
            merged,
            ai_provider="claude",
            ai_model="test-model",
            job_id=None,
        )

        mock_update.assert_not_called()


class TestResolveAdditionalRepos:
    """Tests for resolve_additional_repos."""

    def test_request_value_takes_priority(self) -> None:
        """Request additional_repos overrides settings."""
        from jenkins_job_insight.models import AdditionalRepo, AnalyzeRequest
        from jenkins_job_insight.analyzer import resolve_additional_repos

        request = AnalyzeRequest(
            job_name="test",
            build_number=1,
            additional_repos=[
                AdditionalRepo.model_validate(
                    {"name": "infra", "url": "https://github.com/org/infra"}
                ),
            ],
        )
        settings = MagicMock()
        settings.additional_repos = "other:https://github.com/org/other"
        result = resolve_additional_repos(request, settings)
        assert len(result) == 1
        assert result[0].name == "infra"

    def test_falls_back_to_settings(self) -> None:
        """Falls back to settings when request is None."""
        from jenkins_job_insight.models import AnalyzeRequest
        from jenkins_job_insight.analyzer import resolve_additional_repos

        request = AnalyzeRequest(job_name="test", build_number=1)
        settings = MagicMock()
        settings.additional_repos = "infra:https://github.com/org/infra"
        result = resolve_additional_repos(request, settings)
        assert len(result) == 1
        assert result[0].name == "infra"

    def test_empty_settings_returns_empty(self) -> None:
        """Returns empty list when both request and settings are empty."""
        from jenkins_job_insight.models import AnalyzeRequest
        from jenkins_job_insight.analyzer import resolve_additional_repos

        request = AnalyzeRequest(job_name="test", build_number=1)
        settings = MagicMock()
        settings.additional_repos = ""
        result = resolve_additional_repos(request, settings)
        assert result == []

    def test_explicit_empty_list_overrides_settings(self) -> None:
        """Explicit [] in request disables additional repos."""
        from jenkins_job_insight.models import AnalyzeRequest
        from jenkins_job_insight.analyzer import resolve_additional_repos

        request = AnalyzeRequest(job_name="test", build_number=1, additional_repos=[])
        settings = MagicMock()
        settings.additional_repos = "infra:https://github.com/org/infra"
        result = resolve_additional_repos(request, settings)
        assert result == []


class TestCloneAdditionalRepos:
    """Tests for clone_additional_repos helper."""

    @pytest.mark.asyncio
    async def test_clones_into_subdirs_when_repo_path_exists(self, tmp_path) -> None:
        """Additional repos are cloned as subdirectories of repo_path."""
        from jenkins_job_insight.analyzer import clone_additional_repos
        from jenkins_job_insight.models import AdditionalRepo
        from jenkins_job_insight.repository import RepositoryManager

        repo_path = tmp_path / "main-repo"
        repo_path.mkdir()

        repos = [
            AdditionalRepo.model_validate(
                {"name": "infra", "url": "https://github.com/org/infra"}
            ),
            AdditionalRepo.model_validate(
                {"name": "product", "url": "https://github.com/org/product"}
            ),
        ]

        manager = MagicMock(spec=RepositoryManager)

        def fake_clone_into(url, target, depth=1, branch=""):
            target.mkdir(parents=True, exist_ok=True)
            return target

        manager.clone_into = MagicMock(side_effect=fake_clone_into)

        async def fake_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with patch(
            "jenkins_job_insight.analyzer.asyncio.to_thread",
            side_effect=fake_to_thread,
        ):
            cloned, result_path = await clone_additional_repos(
                manager, repos, repo_path
            )

        assert result_path == repo_path
        assert len(cloned) == 2
        assert "infra" in cloned
        assert "product" in cloned
        assert cloned["infra"] == repo_path / "infra"
        assert cloned["product"] == repo_path / "product"

    @pytest.mark.asyncio
    async def test_clones_into_caller_provided_workspace(self, tmp_path) -> None:
        """Caller always provides workspace; repos are cloned as subdirectories."""
        from jenkins_job_insight.analyzer import clone_additional_repos
        from jenkins_job_insight.models import AdditionalRepo
        from jenkins_job_insight.repository import RepositoryManager

        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()

        repos = [
            AdditionalRepo.model_validate(
                {"name": "main-code", "url": "https://github.com/org/main"}
            ),
        ]

        manager = MagicMock(spec=RepositoryManager)

        def fake_clone_into(url, target, depth=1, branch=""):
            target.mkdir(parents=True, exist_ok=True)
            return target

        manager.clone_into = MagicMock(side_effect=fake_clone_into)

        async def fake_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with patch(
            "jenkins_job_insight.analyzer.asyncio.to_thread",
            side_effect=fake_to_thread,
        ):
            cloned, result_path = await clone_additional_repos(
                manager, repos, workspace_dir
            )

        assert result_path == workspace_dir
        assert "main-code" in cloned
        assert cloned["main-code"] == workspace_dir / "main-code"

    @pytest.mark.asyncio
    async def test_all_repos_are_subdirs_of_workspace(self, tmp_path) -> None:
        """ALL repos are cloned as subdirectories of the provided workspace."""
        from jenkins_job_insight.analyzer import clone_additional_repos
        from jenkins_job_insight.models import AdditionalRepo
        from jenkins_job_insight.repository import RepositoryManager

        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()

        repos = [
            AdditionalRepo.model_validate(
                {"name": "first", "url": "https://github.com/org/first"}
            ),
            AdditionalRepo.model_validate(
                {"name": "second", "url": "https://github.com/org/second"}
            ),
        ]

        manager = MagicMock(spec=RepositoryManager)

        def fake_clone_into(url, target, depth=1, branch=""):
            target.mkdir(parents=True, exist_ok=True)
            return target

        manager.clone_into = MagicMock(side_effect=fake_clone_into)

        async def fake_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with patch(
            "jenkins_job_insight.analyzer.asyncio.to_thread",
            side_effect=fake_to_thread,
        ):
            cloned, result_path = await clone_additional_repos(
                manager, repos, workspace_dir
            )

        assert result_path == workspace_dir
        assert "first" in cloned
        assert "second" in cloned
        assert cloned["first"] == workspace_dir / "first"
        assert cloned["second"] == workspace_dir / "second"
        # All repos cloned via clone_into, no manager.clone call
        assert manager.clone_into.call_count == 2

    @pytest.mark.asyncio
    async def test_clone_failure_is_graceful(self, tmp_path) -> None:
        """Failed clones are logged but don't crash the process."""
        from jenkins_job_insight.analyzer import clone_additional_repos
        from jenkins_job_insight.models import AdditionalRepo
        from jenkins_job_insight.repository import RepositoryManager

        repo_path = tmp_path / "main"
        repo_path.mkdir()

        repos = [
            AdditionalRepo.model_validate(
                {"name": "good", "url": "https://github.com/org/good"}
            ),
            AdditionalRepo.model_validate(
                {"name": "bad", "url": "https://github.com/org/bad"}
            ),
        ]

        def fake_clone_into(url, target, depth=1, branch=""):
            if "bad" in str(url):
                raise RuntimeError("Clone failed")
            target.mkdir(parents=True, exist_ok=True)
            return target

        manager = MagicMock(spec=RepositoryManager)
        manager.clone_into = MagicMock(side_effect=fake_clone_into)

        async def fake_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with patch(
            "jenkins_job_insight.analyzer.asyncio.to_thread",
            side_effect=fake_to_thread,
        ):
            cloned, result_path = await clone_additional_repos(
                manager, repos, repo_path
            )

        assert "good" in cloned
        assert "bad" not in cloned
        assert result_path == repo_path

    @pytest.mark.asyncio
    async def test_cloning_uses_asyncio_gather(self, tmp_path) -> None:
        """Verify that parallel cloning uses asyncio.gather, not sequential loops."""
        from jenkins_job_insight.analyzer import clone_additional_repos
        from jenkins_job_insight.models import AdditionalRepo
        from jenkins_job_insight.repository import RepositoryManager

        repo_path = tmp_path / "main-repo"
        repo_path.mkdir()

        repos = [
            AdditionalRepo.model_validate(
                {"name": "a", "url": "https://github.com/org/a"}
            ),
            AdditionalRepo.model_validate(
                {"name": "b", "url": "https://github.com/org/b"}
            ),
            AdditionalRepo.model_validate(
                {"name": "c", "url": "https://github.com/org/c"}
            ),
        ]

        manager = MagicMock(spec=RepositoryManager)

        def fake_clone_into(url, target, depth=1, branch=""):
            target.mkdir(parents=True, exist_ok=True)
            return target

        manager.clone_into = MagicMock(side_effect=fake_clone_into)

        async def fake_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with (
            patch(
                "jenkins_job_insight.analyzer.asyncio.to_thread",
                side_effect=fake_to_thread,
            ),
            patch(
                "jenkins_job_insight.analyzer.asyncio.gather",
                wraps=__import__("asyncio").gather,
            ) as mock_gather,
        ):
            cloned, _ = await clone_additional_repos(manager, repos, repo_path)

        # asyncio.gather must have been called (parallel, not sequential)
        assert mock_gather.called
        assert len(cloned) == 3

    @pytest.mark.asyncio
    async def test_all_repos_use_asyncio_gather_with_workspace(self, tmp_path) -> None:
        """ALL repos are cloned in parallel via asyncio.gather in the provided workspace."""
        from jenkins_job_insight.analyzer import clone_additional_repos
        from jenkins_job_insight.models import AdditionalRepo
        from jenkins_job_insight.repository import RepositoryManager

        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()

        repos = [
            AdditionalRepo.model_validate(
                {"name": "first", "url": "https://github.com/org/first"}
            ),
            AdditionalRepo.model_validate(
                {"name": "second", "url": "https://github.com/org/second"}
            ),
            AdditionalRepo.model_validate(
                {"name": "third", "url": "https://github.com/org/third"}
            ),
        ]

        manager = MagicMock(spec=RepositoryManager)

        def fake_clone_into(url, target, depth=1, branch=""):
            target.mkdir(parents=True, exist_ok=True)
            return target

        manager.clone_into = MagicMock(side_effect=fake_clone_into)

        async def fake_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with (
            patch(
                "jenkins_job_insight.analyzer.asyncio.to_thread",
                side_effect=fake_to_thread,
            ),
            patch(
                "jenkins_job_insight.analyzer.asyncio.gather",
                wraps=__import__("asyncio").gather,
            ) as mock_gather,
        ):
            cloned, result_path = await clone_additional_repos(
                manager, repos, workspace_dir
            )

        assert mock_gather.called
        assert result_path == workspace_dir
        assert len(cloned) == 3
        assert "first" in cloned
        assert "second" in cloned
        assert "third" in cloned
        # All repos via clone_into, no manager.clone
        assert manager.clone_into.call_count == 3


class TestBuildResourcesSectionAdditionalRepos:
    """Tests for _build_resources_section with additional_repos."""

    def test_additional_repos_git_repos(self, tmp_path) -> None:
        """Test that additional git repos are advertised in resources section."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        additional = {
            "infra": tmp_path / "infra",
            "product": tmp_path / "product",
        }
        for _name, path in additional.items():
            path.mkdir()
            (path / ".git").mkdir()

        result = _build_resources_section(workspace, additional_repos=additional)
        assert "infra" in result
        assert "product" in result
        assert "Repository" in result

    def test_additional_repos_non_git(self, tmp_path) -> None:
        """Test that additional non-git dirs are advertised as directories."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        additional = {"data": tmp_path / "data"}
        additional["data"].mkdir()

        result = _build_resources_section(workspace, additional_repos=additional)
        assert "data" in result
        assert "Directory" in result

    def test_no_additional_repos(self, tmp_path) -> None:
        """Test that section works without additional repos."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = _build_resources_section(workspace, additional_repos=None)
        assert "Repository" not in result
        assert "Directory" not in result

    def test_empty_additional_repos(self, tmp_path) -> None:
        """Test that empty dict produces no repo entries."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = _build_resources_section(workspace, additional_repos={})
        assert "Repository" not in result

    def test_job_insight_prompt_in_repo(self, tmp_path) -> None:
        """Test that JOB_INSIGHT_PROMPT.md in a cloned repo is advertised."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        repo_path = tmp_path / "my-repo"
        repo_path.mkdir()
        (repo_path / ".git").mkdir()
        (repo_path / "JOB_INSIGHT_PROMPT.md").write_text("custom instructions")

        additional = {"my-repo": repo_path}
        result = _build_resources_section(workspace, additional_repos=additional)
        assert "JOB_INSIGHT_PROMPT.md" in result
        assert "Project-specific analysis instructions" in result

    def test_history_prompt_in_repo(self, tmp_path) -> None:
        """Test that history prompt in a cloned repo is advertised when history enabled."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        repo_path = tmp_path / "my-repo"
        repo_path.mkdir()
        (repo_path / ".git").mkdir()
        (repo_path / "JOB_INSIGHT_FAILURE_HISTORY_ANALYSIS_PROMPT.md").write_text(
            "history instructions"
        )

        additional = {"my-repo": repo_path}
        result = _build_resources_section(
            workspace, additional_repos=additional, history_enabled=True
        )
        assert "history analysis instructions" in result

    def test_history_prompt_not_shown_when_disabled(self, tmp_path) -> None:
        """Test that history prompt is not shown when history is disabled."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        repo_path = tmp_path / "my-repo"
        repo_path.mkdir()
        (repo_path / ".git").mkdir()
        (repo_path / "JOB_INSIGHT_FAILURE_HISTORY_ANALYSIS_PROMPT.md").write_text(
            "history instructions"
        )

        additional = {"my-repo": repo_path}
        result = _build_resources_section(
            workspace, additional_repos=additional, history_enabled=False
        )
        assert "history analysis instructions" not in result


class TestAnalyzeJobWorkspacePattern:
    """Tests that analyze_job creates a workspace and clones test repo as subdirectory."""

    @pytest.mark.asyncio
    async def test_test_repo_cloned_into_workspace_subdirectory(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """When tests_repo_url is set, test repo is cloned as subdirectory of workspace."""
        from jenkins_job_insight.analyzer import analyze_job
        from jenkins_job_insight.models import AnalyzeRequest

        body = AnalyzeRequest.model_validate(
            {
                "job_name": "my-job",
                "build_number": 123,
                "tests_repo_url": "https://github.com/RedHatQE/mtv-api-tests",
            }
        )
        settings = Settings()
        settings_data = settings.model_dump(mode="python")
        settings_data["jenkins_url"] = "https://jenkins.example.com"
        settings_data["jenkins_user"] = "user"
        settings_data["jenkins_password"] = _FAKE_JENKINS_PASSWORD
        merged = Settings.model_validate(settings_data)

        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()

        mock_client = MagicMock()
        mock_client.get_build_info_safe.return_value = {
            "result": "FAILURE",
            "building": False,
        }
        mock_client.get_build_console.return_value = "Build failed"
        mock_client.get_test_report.return_value = None
        mock_client.session = MagicMock()

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.JenkinsClient",
            lambda **kwargs: mock_client,
        )

        async def fake_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.asyncio.to_thread",
            fake_to_thread,
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.check_ai_cli_available",
            AsyncMock(return_value=(True, "")),
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer._call_ai_cli_with_retry",
            AsyncMock(
                return_value=(True, '{"classification": "CODE ISSUE", "details": "d"}')
            ),
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.update_progress_phase",
            AsyncMock(),
        )

        # Track RepositoryManager calls
        clone_into_calls = []

        mock_repo_manager = MagicMock()
        mock_repo_manager.create_workspace.return_value = workspace_dir

        def fake_clone_into(url, target, depth=1, branch=""):
            clone_into_calls.append({"url": url, "target": target, "depth": depth})
            target.mkdir(parents=True, exist_ok=True)
            # Create .git to simulate a real clone
            (target / ".git").mkdir(exist_ok=True)
            return target

        mock_repo_manager.clone_into = MagicMock(side_effect=fake_clone_into)

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.RepositoryManager",
            lambda: mock_repo_manager,
        )

        await analyze_job(
            body,
            merged,
            ai_provider="claude",
            ai_model="test-model",
            job_id="test-job-id",
        )

        # Verify workspace was created
        mock_repo_manager.create_workspace.assert_called_once()

        # Verify test repo was cloned INTO workspace as subdirectory
        assert len(clone_into_calls) == 1
        call = clone_into_calls[0]
        assert call["url"] == "https://github.com/RedHatQE/mtv-api-tests"
        assert call["target"] == workspace_dir / "mtv-api-tests"
        assert call["depth"] == 50  # Test repo uses depth=50 for git history

    @pytest.mark.asyncio
    async def test_test_repo_name_derived_from_url(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """Repo name is extracted from URL, stripping .git suffix and trailing slashes."""
        from jenkins_job_insight.analyzer import analyze_job
        from jenkins_job_insight.models import AnalyzeRequest

        body = AnalyzeRequest.model_validate(
            {
                "job_name": "my-job",
                "build_number": 123,
                "tests_repo_url": "https://github.com/org/my-tests.git",
            }
        )
        settings = Settings()
        settings_data = settings.model_dump(mode="python")
        settings_data["jenkins_url"] = "https://jenkins.example.com"
        settings_data["jenkins_user"] = "user"
        settings_data["jenkins_password"] = _FAKE_JENKINS_PASSWORD
        merged = Settings.model_validate(settings_data)

        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()

        mock_client = MagicMock()
        mock_client.get_build_info_safe.return_value = {
            "result": "FAILURE",
            "building": False,
        }
        mock_client.get_build_console.return_value = "Build failed"
        mock_client.get_test_report.return_value = None
        mock_client.session = MagicMock()

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.JenkinsClient",
            lambda **kwargs: mock_client,
        )

        async def fake_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.asyncio.to_thread",
            fake_to_thread,
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.check_ai_cli_available",
            AsyncMock(return_value=(True, "")),
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer._call_ai_cli_with_retry",
            AsyncMock(
                return_value=(True, '{"classification": "CODE ISSUE", "details": "d"}')
            ),
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.update_progress_phase",
            AsyncMock(),
        )

        clone_into_calls = []
        mock_repo_manager = MagicMock()
        mock_repo_manager.create_workspace.return_value = workspace_dir

        def fake_clone_into(url, target, depth=1, branch=""):
            clone_into_calls.append({"url": url, "target": target, "depth": depth})
            target.mkdir(parents=True, exist_ok=True)
            (target / ".git").mkdir(exist_ok=True)
            return target

        mock_repo_manager.clone_into = MagicMock(side_effect=fake_clone_into)

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.RepositoryManager",
            lambda: mock_repo_manager,
        )

        await analyze_job(
            body,
            merged,
            ai_provider="claude",
            ai_model="test-model",
            job_id="test-job-id",
        )

        # Verify .git suffix is stripped from repo name
        assert clone_into_calls[0]["target"] == workspace_dir / "my-tests"

    @pytest.mark.asyncio
    async def test_workspace_created_for_additional_repos_only(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """When no test repo but additional repos exist, workspace is still created."""
        from jenkins_job_insight.analyzer import analyze_job
        from jenkins_job_insight.models import AnalyzeRequest

        body = AnalyzeRequest.model_validate(
            {
                "job_name": "my-job",
                "build_number": 123,
                "additional_repos": [
                    {"name": "infra", "url": "https://github.com/org/infra"},
                ],
            }
        )
        settings = Settings()
        settings_data = settings.model_dump(mode="python")
        settings_data["jenkins_url"] = "https://jenkins.example.com"
        settings_data["jenkins_user"] = "user"
        settings_data["jenkins_password"] = _FAKE_JENKINS_PASSWORD
        merged = Settings.model_validate(settings_data)

        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()

        mock_client = MagicMock()
        mock_client.get_build_info_safe.return_value = {
            "result": "FAILURE",
            "building": False,
        }
        mock_client.get_build_console.return_value = "Build failed"
        mock_client.get_test_report.return_value = None
        mock_client.session = MagicMock()

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.JenkinsClient",
            lambda **kwargs: mock_client,
        )

        async def fake_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.asyncio.to_thread",
            fake_to_thread,
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.check_ai_cli_available",
            AsyncMock(return_value=(True, "")),
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer._call_ai_cli_with_retry",
            AsyncMock(
                return_value=(True, '{"classification": "CODE ISSUE", "details": "d"}')
            ),
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.update_progress_phase",
            AsyncMock(),
        )

        mock_repo_manager = MagicMock()
        mock_repo_manager.create_workspace.return_value = workspace_dir

        def fake_clone_into(url, target, depth=1, branch=""):
            target.mkdir(parents=True, exist_ok=True)
            (target / ".git").mkdir(exist_ok=True)
            return target

        mock_repo_manager.clone_into = MagicMock(side_effect=fake_clone_into)

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.RepositoryManager",
            lambda: mock_repo_manager,
        )

        # Mock clone_additional_repos to track calls
        clone_additional_calls = []

        async def mock_clone_additional(manager, repos, path):
            clone_additional_calls.append({"manager": manager, "path": path})
            return {"infra": workspace_dir / "infra"}, path or workspace_dir

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.clone_additional_repos",
            mock_clone_additional,
        )

        await analyze_job(
            body,
            merged,
            ai_provider="claude",
            ai_model="test-model",
            job_id="test-job-id",
        )

        # Verify additional repos got a workspace path (not None)
        assert len(clone_additional_calls) == 1

    @pytest.mark.asyncio
    async def test_test_repo_and_additional_repos_share_workspace(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """Test repo and additional repos are both in the same workspace."""
        from jenkins_job_insight.analyzer import analyze_job
        from jenkins_job_insight.models import AnalyzeRequest

        body = AnalyzeRequest.model_validate(
            {
                "job_name": "my-job",
                "build_number": 123,
                "tests_repo_url": "https://github.com/org/test-repo",
                "additional_repos": [
                    {"name": "infra", "url": "https://github.com/org/infra"},
                ],
            }
        )
        settings = Settings()
        settings_data = settings.model_dump(mode="python")
        settings_data["jenkins_url"] = "https://jenkins.example.com"
        settings_data["jenkins_user"] = "user"
        settings_data["jenkins_password"] = _FAKE_JENKINS_PASSWORD
        merged = Settings.model_validate(settings_data)

        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()

        mock_client = MagicMock()
        mock_client.get_build_info_safe.return_value = {
            "result": "FAILURE",
            "building": False,
        }
        mock_client.get_build_console.return_value = "Build failed"
        mock_client.get_test_report.return_value = None
        mock_client.session = MagicMock()

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.JenkinsClient",
            lambda **kwargs: mock_client,
        )

        async def fake_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.asyncio.to_thread",
            fake_to_thread,
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.check_ai_cli_available",
            AsyncMock(return_value=(True, "")),
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer._call_ai_cli_with_retry",
            AsyncMock(
                return_value=(True, '{"classification": "CODE ISSUE", "details": "d"}')
            ),
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.update_progress_phase",
            AsyncMock(),
        )

        clone_into_calls = []
        mock_repo_manager = MagicMock()
        mock_repo_manager.create_workspace.return_value = workspace_dir

        def fake_clone_into(url, target, depth=1, branch=""):
            clone_into_calls.append({"url": url, "target": target, "depth": depth})
            target.mkdir(parents=True, exist_ok=True)
            (target / ".git").mkdir(exist_ok=True)
            return target

        mock_repo_manager.clone_into = MagicMock(side_effect=fake_clone_into)

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.RepositoryManager",
            lambda: mock_repo_manager,
        )

        # Track what clone_additional_repos receives as repo_path
        clone_additional_repo_paths = []

        async def mock_clone_additional(manager, repos, path):
            clone_additional_repo_paths.append(path)
            return {"infra": workspace_dir / "infra"}, path

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.clone_additional_repos",
            mock_clone_additional,
        )

        await analyze_job(
            body,
            merged,
            ai_provider="claude",
            ai_model="test-model",
            job_id="test-job-id",
        )

        # Test repo cloned into workspace
        assert len(clone_into_calls) == 1
        assert clone_into_calls[0]["target"] == workspace_dir / "test-repo"

        # Additional repos received the same workspace path
        assert len(clone_additional_repo_paths) == 1
        assert clone_additional_repo_paths[0] == workspace_dir

    @pytest.mark.asyncio
    async def test_test_repo_included_in_cloned_repos_dict(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """Test repo is added to the cloned_repos dict passed to analysis functions."""
        from jenkins_job_insight.analyzer import analyze_job
        from jenkins_job_insight.models import (
            AnalysisDetail,
            AnalyzeRequest,
            FailureAnalysis,
        )

        body = AnalyzeRequest.model_validate(
            {
                "job_name": "my-job",
                "build_number": 123,
                "tests_repo_url": "https://github.com/org/test-repo",
            }
        )
        settings = Settings()
        settings_data = settings.model_dump(mode="python")
        settings_data["jenkins_url"] = "https://jenkins.example.com"
        settings_data["jenkins_user"] = "user"
        settings_data["jenkins_password"] = _FAKE_JENKINS_PASSWORD
        merged = Settings.model_validate(settings_data)

        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()

        mock_client = MagicMock()
        mock_client.get_build_info_safe.return_value = {
            "result": "FAILURE",
            "building": False,
        }
        mock_client.get_build_console.return_value = "Build failed"
        mock_client.get_test_report.return_value = {
            "suites": [
                {
                    "cases": [
                        {
                            "className": "com.example",
                            "name": "test_foo",
                            "status": "FAILED",
                            "errorDetails": "AssertionError",
                            "errorStackTrace": "at line 42",
                        }
                    ]
                }
            ]
        }
        mock_client.session = MagicMock()

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.JenkinsClient",
            lambda **kwargs: mock_client,
        )

        async def fake_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.asyncio.to_thread",
            fake_to_thread,
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.check_ai_cli_available",
            AsyncMock(return_value=(True, "")),
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.update_progress_phase",
            AsyncMock(),
        )

        mock_repo_manager = MagicMock()
        mock_repo_manager.create_workspace.return_value = workspace_dir

        def fake_clone_into(url, target, depth=1, branch=""):
            target.mkdir(parents=True, exist_ok=True)
            (target / ".git").mkdir(exist_ok=True)
            return target

        mock_repo_manager.clone_into = MagicMock(side_effect=fake_clone_into)

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.RepositoryManager",
            lambda: mock_repo_manager,
        )

        # Track additional_repos passed to analyze_failure_group
        captured_additional_repos = []

        mock_failure = FailureAnalysis(
            test_name="com.example.test_foo",
            error="AssertionError",
            analysis=AnalysisDetail(
                classification="CODE ISSUE", details="broken assertion"
            ),
            error_signature="sig123",
        )

        async def mock_analyze_group(*args, **kwargs):
            captured_additional_repos.append(kwargs.get("additional_repos"))
            return [mock_failure]

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.analyze_failure_group",
            mock_analyze_group,
        )

        async def run_coroutines(coroutines, **kwargs):
            return [await coro for coro in coroutines]

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.run_parallel_with_limit",
            AsyncMock(side_effect=run_coroutines),
        )

        await analyze_job(
            body,
            merged,
            ai_provider="claude",
            ai_model="test-model",
            job_id="test-job-id",
        )

        # The test repo should be included in additional_repos dict
        assert len(captured_additional_repos) == 1
        repos = captured_additional_repos[0]
        assert repos is not None
        assert "test-repo" in repos
        assert repos["test-repo"] == workspace_dir / "test-repo"


class TestAnalyzeFailuresWorkspacePattern:
    """Tests that analyze_failures endpoint creates a workspace and clones test repo as subdirectory."""

    @pytest.mark.asyncio
    async def test_analyze_failures_workspace_via_http(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """POST /analyze-failures with tests_repo_url creates workspace pattern."""
        from jenkins_job_insight.models import (
            AnalysisDetail,
            FailureAnalysis,
        )
        from starlette.testclient import TestClient
        from jenkins_job_insight.main import app

        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()

        clone_into_calls = []
        mock_repo_manager = MagicMock()
        mock_repo_manager.create_workspace.return_value = workspace_dir
        mock_repo_manager.cleanup.return_value = None

        def fake_clone_into(url, target, depth=1, branch=""):
            clone_into_calls.append({"url": url, "target": target, "depth": depth})
            target.mkdir(parents=True, exist_ok=True)
            (target / ".git").mkdir(exist_ok=True)
            return target

        mock_repo_manager.clone_into = MagicMock(side_effect=fake_clone_into)

        monkeypatch.setattr(
            "jenkins_job_insight.main.RepositoryManager",
            lambda: mock_repo_manager,
        )

        mock_failure = FailureAnalysis(
            test_name="test_foo",
            error="assert False",
            analysis=AnalysisDetail(classification="CODE ISSUE", details="d"),
            error_signature="sig",
        )

        monkeypatch.setattr(
            "jenkins_job_insight.main.analyze_failure_group",
            AsyncMock(return_value=[mock_failure]),
        )

        async def run_coroutines(coroutines, **kwargs):
            return [await coro for coro in coroutines]

        monkeypatch.setattr(
            "jenkins_job_insight.main.run_parallel_with_limit",
            AsyncMock(side_effect=run_coroutines),
        )
        monkeypatch.setattr(
            "jenkins_job_insight.main.save_result",
            AsyncMock(),
        )
        monkeypatch.setattr(
            "jenkins_job_insight.main.update_status",
            AsyncMock(),
        )
        monkeypatch.setattr(
            "jenkins_job_insight.main.populate_failure_history",
            AsyncMock(),
        )
        monkeypatch.setattr(
            "jenkins_job_insight.main.storage.make_classifications_visible",
            AsyncMock(),
        )
        monkeypatch.setattr(
            "jenkins_job_insight.main._preserve_request_params",
            AsyncMock(),
        )

        async def fake_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr(
            "jenkins_job_insight.main.asyncio.to_thread",
            fake_to_thread,
        )

        test_client = TestClient(app)
        response = test_client.post(
            "/analyze-failures",
            json={
                "failures": [
                    {
                        "test_name": "test_foo",
                        "error_message": "assert False",
                        "stack_trace": "line 10",
                    }
                ],
                "ai_provider": "claude",
                "ai_model": "test-model",
                "tests_repo_url": "https://github.com/org/my-tests",
            },
        )
        assert response.status_code == 200

        # Verify workspace was created
        mock_repo_manager.create_workspace.assert_called_once()

        # Verify test repo was cloned INTO workspace as subdirectory
        assert len(clone_into_calls) == 1
        call = clone_into_calls[0]
        assert call["url"] == "https://github.com/org/my-tests"
        assert call["target"] == workspace_dir / "my-tests"
        assert call["depth"] == 50  # Test repo uses depth=50


class TestWorkspaceAlwaysCreated:
    """Workspace is always created, even when no repos are configured."""

    @pytest.mark.asyncio
    async def test_analyze_job_creates_workspace_without_repos(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """analyze_job creates a workspace even when no test repo or additional repos."""
        from jenkins_job_insight.analyzer import analyze_job
        from jenkins_job_insight.models import AnalyzeRequest

        body = AnalyzeRequest(
            job_name="my-job",
            build_number=123,
        )
        settings = Settings()
        settings_data = settings.model_dump(mode="python")
        settings_data["jenkins_url"] = "https://jenkins.example.com"
        settings_data["jenkins_user"] = "user"
        settings_data["jenkins_password"] = _FAKE_JENKINS_PASSWORD
        settings_data["tests_repo_url"] = None
        settings_data["additional_repos"] = ""
        merged = Settings.model_validate(settings_data)

        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()

        mock_client = MagicMock()
        mock_client.get_build_info_safe.return_value = {
            "result": "FAILURE",
            "building": False,
        }
        mock_client.get_build_console.return_value = "Build failed"
        mock_client.get_test_report.return_value = None
        mock_client.session = MagicMock()

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.JenkinsClient",
            lambda **kwargs: mock_client,
        )

        async def fake_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.asyncio.to_thread",
            fake_to_thread,
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.check_ai_cli_available",
            AsyncMock(return_value=(True, "")),
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer._call_ai_cli_with_retry",
            AsyncMock(
                return_value=(True, '{"classification": "CODE ISSUE", "details": "d"}')
            ),
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.update_progress_phase",
            AsyncMock(),
        )

        mock_repo_manager = MagicMock()
        mock_repo_manager.create_workspace.return_value = workspace_dir

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.RepositoryManager",
            lambda: mock_repo_manager,
        )

        await analyze_job(
            body,
            merged,
            ai_provider="claude",
            ai_model="test-model",
            job_id="test-job-id",
        )

        # Workspace must be created even without any repos
        mock_repo_manager.create_workspace.assert_called_once()

    @pytest.mark.asyncio
    async def test_analyze_failures_creates_workspace_without_repos(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """POST /analyze-failures creates workspace even without tests_repo_url."""
        from jenkins_job_insight.models import (
            AnalysisDetail,
            FailureAnalysis,
        )
        from starlette.testclient import TestClient
        from jenkins_job_insight.main import app
        from jenkins_job_insight.config import get_settings

        # Override settings to ensure no repos are configured
        no_repo_settings = Settings()
        settings_data = no_repo_settings.model_dump(mode="python")
        settings_data["tests_repo_url"] = None
        settings_data["additional_repos"] = ""
        no_repo_settings = Settings.model_validate(settings_data)
        app.dependency_overrides[get_settings] = lambda: no_repo_settings

        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()

        mock_repo_manager = MagicMock()
        mock_repo_manager.create_workspace.return_value = workspace_dir
        mock_repo_manager.cleanup.return_value = None

        monkeypatch.setattr(
            "jenkins_job_insight.main.RepositoryManager",
            lambda: mock_repo_manager,
        )

        mock_failure = FailureAnalysis(
            test_name="test_foo",
            error="assert False",
            analysis=AnalysisDetail(classification="CODE ISSUE", details="d"),
            error_signature="sig",
        )

        monkeypatch.setattr(
            "jenkins_job_insight.main.analyze_failure_group",
            AsyncMock(return_value=[mock_failure]),
        )

        async def run_coroutines(coroutines, **kwargs):
            return [await coro for coro in coroutines]

        monkeypatch.setattr(
            "jenkins_job_insight.main.run_parallel_with_limit",
            AsyncMock(side_effect=run_coroutines),
        )
        monkeypatch.setattr(
            "jenkins_job_insight.main.save_result",
            AsyncMock(),
        )
        monkeypatch.setattr(
            "jenkins_job_insight.main.update_status",
            AsyncMock(),
        )
        monkeypatch.setattr(
            "jenkins_job_insight.main.populate_failure_history",
            AsyncMock(),
        )
        monkeypatch.setattr(
            "jenkins_job_insight.main.storage.make_classifications_visible",
            AsyncMock(),
        )
        monkeypatch.setattr(
            "jenkins_job_insight.main._preserve_request_params",
            AsyncMock(),
        )

        async def fake_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr(
            "jenkins_job_insight.main.asyncio.to_thread",
            fake_to_thread,
        )

        test_client = TestClient(app)
        response = test_client.post(
            "/analyze-failures",
            json={
                "failures": [
                    {
                        "test_name": "test_foo",
                        "error_message": "assert False",
                        "stack_trace": "line 10",
                    }
                ],
                "ai_provider": "claude",
                "ai_model": "test-model",
            },
        )
        assert response.status_code == 200

        # Workspace must be created even without any repos
        mock_repo_manager.create_workspace.assert_called_once()

        # Clean up dependency override
        app.dependency_overrides.pop(get_settings, None)

    @pytest.mark.asyncio
    async def test_clone_additional_repos_requires_path(self, tmp_path) -> None:
        """clone_additional_repos always receives a Path, never None."""
        from jenkins_job_insight.analyzer import clone_additional_repos
        import inspect

        sig = inspect.signature(clone_additional_repos)
        repo_path_param = sig.parameters["repo_path"]
        # The annotation should be Path, not Path | None
        assert repo_path_param.annotation is not inspect.Parameter.empty
        assert "None" not in str(repo_path_param.annotation)


class TestCloneAdditionalReposPassesRef:
    """Tests that clone_additional_repos passes ar.ref as branch to clone_into."""

    @pytest.mark.asyncio
    async def test_ref_passed_as_branch(self, tmp_path) -> None:
        """AdditionalRepo.ref is forwarded as branch parameter to clone_into."""
        from jenkins_job_insight.analyzer import clone_additional_repos
        from jenkins_job_insight.models import AdditionalRepo
        from jenkins_job_insight.repository import RepositoryManager

        repo_path = tmp_path / "workspace"
        repo_path.mkdir()

        repos = [
            AdditionalRepo.model_validate(
                {
                    "name": "infra",
                    "url": "https://github.com/org/infra",
                    "ref": "develop",
                }
            ),
            AdditionalRepo.model_validate(
                {"name": "product", "url": "https://github.com/org/product", "ref": ""}
            ),
        ]

        manager = MagicMock(spec=RepositoryManager)

        def fake_clone_into(url, target, depth=1, branch=""):
            target.mkdir(parents=True, exist_ok=True)
            return target

        manager.clone_into = MagicMock(side_effect=fake_clone_into)

        async def fake_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with patch(
            "jenkins_job_insight.analyzer.asyncio.to_thread",
            side_effect=fake_to_thread,
        ):
            cloned, _ = await clone_additional_repos(manager, repos, repo_path)

        assert len(cloned) == 2
        # Check calls: infra should have branch="develop", product should have branch=""
        calls = manager.clone_into.call_args_list
        assert len(calls) == 2

        # Find the call for each repo (order may vary due to asyncio.gather)
        call_args_by_url = {}
        for call in calls:
            url = call[0][0] if call[0] else call[1].get("url", "")
            call_args_by_url[url] = call

        infra_call = call_args_by_url.get("https://github.com/org/infra")
        assert infra_call is not None
        # branch should be "develop"
        assert infra_call[1].get("branch") == "develop" or (
            len(infra_call[0]) > 3 and infra_call[0][3] == "develop"
        )

        product_call = call_args_by_url.get("https://github.com/org/product")
        assert product_call is not None
        # branch should be "" (empty)
        assert product_call[1].get("branch", "") == ""


class TestAnalyzeJobParsesRepoRef:
    """Tests that analyze_job parses ref from tests_repo_url before cloning."""

    @pytest.mark.asyncio
    async def test_tests_repo_url_with_ref_passes_branch_to_clone(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """When tests_repo_url has ':ref', parse it and pass branch to clone_into."""
        from jenkins_job_insight.analyzer import analyze_job
        from jenkins_job_insight.models import AnalyzeRequest

        body = AnalyzeRequest.model_validate(
            {
                "job_name": "my-job",
                "build_number": 123,
                "tests_repo_url": "https://github.com/org/my-tests:develop",
            }
        )
        settings = Settings()
        settings_data = settings.model_dump(mode="python")
        settings_data["jenkins_url"] = "https://jenkins.example.com"
        settings_data["jenkins_user"] = "user"
        settings_data["jenkins_password"] = _FAKE_JENKINS_PASSWORD
        merged = Settings.model_validate(settings_data)

        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()

        mock_client = MagicMock()
        mock_client.get_build_info_safe.return_value = {
            "result": "FAILURE",
            "building": False,
        }
        mock_client.get_build_console.return_value = "Build failed"
        mock_client.get_test_report.return_value = None
        mock_client.session = MagicMock()

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.JenkinsClient",
            lambda **kwargs: mock_client,
        )

        async def fake_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.asyncio.to_thread",
            fake_to_thread,
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.check_ai_cli_available",
            AsyncMock(return_value=(True, "")),
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer._call_ai_cli_with_retry",
            AsyncMock(
                return_value=(True, '{"classification": "CODE ISSUE", "details": "d"}')
            ),
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.update_progress_phase",
            AsyncMock(),
        )

        clone_into_calls = []
        mock_repo_manager = MagicMock()
        mock_repo_manager.create_workspace.return_value = workspace_dir

        def fake_clone_into(url, target, depth=1, branch=""):
            clone_into_calls.append(
                {"url": url, "target": target, "depth": depth, "branch": branch}
            )
            target.mkdir(parents=True, exist_ok=True)
            (target / ".git").mkdir(exist_ok=True)
            return target

        mock_repo_manager.clone_into = MagicMock(side_effect=fake_clone_into)

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.RepositoryManager",
            lambda: mock_repo_manager,
        )

        await analyze_job(
            body,
            merged,
            ai_provider="claude",
            ai_model="test-model",
            job_id="test-job-id",
        )

        assert len(clone_into_calls) == 1
        call = clone_into_calls[0]
        # URL should be clean (no :develop suffix)
        assert call["url"] == "https://github.com/org/my-tests"
        # Branch should be "develop"
        assert call["branch"] == "develop"
        # Target should use the clean repo name
        assert call["target"] == workspace_dir / "my-tests"

    @pytest.mark.asyncio
    async def test_tests_repo_url_without_ref_no_branch(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """When tests_repo_url has no ':ref', branch is empty string."""
        from jenkins_job_insight.analyzer import analyze_job
        from jenkins_job_insight.models import AnalyzeRequest

        body = AnalyzeRequest.model_validate(
            {
                "job_name": "my-job",
                "build_number": 123,
                "tests_repo_url": "https://github.com/org/my-tests",
            }
        )
        settings = Settings()
        settings_data = settings.model_dump(mode="python")
        settings_data["jenkins_url"] = "https://jenkins.example.com"
        settings_data["jenkins_user"] = "user"
        settings_data["jenkins_password"] = _FAKE_JENKINS_PASSWORD
        merged = Settings.model_validate(settings_data)

        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()

        mock_client = MagicMock()
        mock_client.get_build_info_safe.return_value = {
            "result": "FAILURE",
            "building": False,
        }
        mock_client.get_build_console.return_value = "Build failed"
        mock_client.get_test_report.return_value = None
        mock_client.session = MagicMock()

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.JenkinsClient",
            lambda **kwargs: mock_client,
        )

        async def fake_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.asyncio.to_thread",
            fake_to_thread,
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.check_ai_cli_available",
            AsyncMock(return_value=(True, "")),
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer._call_ai_cli_with_retry",
            AsyncMock(
                return_value=(True, '{"classification": "CODE ISSUE", "details": "d"}')
            ),
        )
        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.update_progress_phase",
            AsyncMock(),
        )

        clone_into_calls = []
        mock_repo_manager = MagicMock()
        mock_repo_manager.create_workspace.return_value = workspace_dir

        def fake_clone_into(url, target, depth=1, branch=""):
            clone_into_calls.append(
                {"url": url, "target": target, "depth": depth, "branch": branch}
            )
            target.mkdir(parents=True, exist_ok=True)
            (target / ".git").mkdir(exist_ok=True)
            return target

        mock_repo_manager.clone_into = MagicMock(side_effect=fake_clone_into)

        monkeypatch.setattr(
            "jenkins_job_insight.analyzer.RepositoryManager",
            lambda: mock_repo_manager,
        )

        await analyze_job(
            body,
            merged,
            ai_provider="claude",
            ai_model="test-model",
            job_id="test-job-id",
        )

        assert len(clone_into_calls) == 1
        call = clone_into_calls[0]
        assert call["url"] == "https://github.com/org/my-tests"
        assert call["branch"] == ""


class TestJsonResponseSchemaParagraphBreaks:
    """Tests that _JSON_RESPONSE_SCHEMA instructs the AI to use paragraph breaks."""

    def test_code_issue_details_has_paragraph_break_instruction(self) -> None:
        """CODE ISSUE details field instructs AI to use paragraph breaks."""
        assert "paragraph breaks" in _JSON_RESPONSE_SCHEMA
        assert "root cause identification" in _JSON_RESPONSE_SCHEMA
        assert "Do NOT write one continuous paragraph" in _JSON_RESPONSE_SCHEMA

    def test_product_bug_details_has_paragraph_break_instruction(self) -> None:
        """PRODUCT BUG details field instructs AI to use paragraph breaks."""
        assert "If PRODUCT BUG:" in _JSON_RESPONSE_SCHEMA
        assert "Do NOT write one continuous paragraph" in _JSON_RESPONSE_SCHEMA

    def test_code_issue_artifacts_evidence_has_paragraph_break_instruction(
        self,
    ) -> None:
        """CODE ISSUE artifacts_evidence field instructs AI to separate entries with paragraph breaks."""
        assert "artifacts_evidence" in _JSON_RESPONSE_SCHEMA
        assert (
            "Separate distinct artifact entries with paragraph breaks"
            in _JSON_RESPONSE_SCHEMA
        )

    def test_product_bug_artifacts_evidence_has_paragraph_break_instruction(
        self,
    ) -> None:
        """PRODUCT BUG artifacts_evidence field instructs AI to separate entries with paragraph breaks."""
        assert "artifacts_evidence" in _JSON_RESPONSE_SCHEMA
        assert (
            "Separate distinct artifact entries with paragraph breaks"
            in _JSON_RESPONSE_SCHEMA
        )

    def test_product_bug_report_description_has_paragraph_break_instruction(
        self,
    ) -> None:
        """product_bug_report description field instructs AI to use paragraph breaks."""
        assert "paragraph breaks between sections" in _JSON_RESPONSE_SCHEMA
