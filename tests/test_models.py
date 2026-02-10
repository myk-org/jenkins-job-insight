"""Tests for Pydantic models."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from jenkins_job_insight.models import (
    AnalysisResult,
    AnalyzeRequest,
    FailureAnalysis,
    JobStatus,
    ResultMessage,
)


class TestAnalyzeRequest:
    """Tests for the AnalyzeRequest model."""

    def test_analyze_request_creation(self) -> None:
        """Test creating a valid AnalyzeRequest."""
        request = AnalyzeRequest(
            job_name="test",
            build_number=123,
            tests_repo_url="https://github.com/example/repo",
        )
        assert request.job_name == "test"
        assert request.build_number == 123
        assert str(request.tests_repo_url) == "https://github.com/example/repo"
        assert request.callback_url is None
        assert request.callback_headers is None
        assert request.slack_webhook_url is None

    def test_analyze_request_with_optional_fields(self) -> None:
        """Test creating AnalyzeRequest with all optional fields."""
        request = AnalyzeRequest(
            job_name="test",
            build_number=123,
            tests_repo_url="https://github.com/example/repo",
            callback_url="https://callback.example.com/webhook",
            callback_headers={"Authorization": "Bearer token"},
            slack_webhook_url="https://hooks.slack.com/services/xxx",
        )
        assert request.callback_url is not None
        assert request.callback_headers == {"Authorization": "Bearer token"}
        assert request.slack_webhook_url is not None

    def test_analyze_request_without_tests_repo_url(self) -> None:
        """Test creating AnalyzeRequest without tests_repo_url (now optional)."""
        request = AnalyzeRequest(
            job_name="test",
            build_number=123,
        )
        assert request.job_name == "test"
        assert request.build_number == 123
        assert request.tests_repo_url is None

    def test_analyze_request_invalid_tests_repo_url(self) -> None:
        """Test that invalid repo URL raises ValidationError."""
        with pytest.raises(ValidationError):
            AnalyzeRequest(
                job_name="test",
                build_number=123,
                tests_repo_url="not-a-valid-url",
            )


class TestFailureAnalysis:
    """Tests for the FailureAnalysis model."""

    def test_failure_analysis_creation(self) -> None:
        """Test creating a valid FailureAnalysis."""
        analysis = FailureAnalysis(
            test_name="test_example",
            error="AssertionError: Expected True, got False",
            analysis="=== CLASSIFICATION ===\nCODE ISSUE\n\n=== ANALYSIS ===\nThe test assertion is wrong",
        )
        assert analysis.test_name == "test_example"
        assert analysis.error == "AssertionError: Expected True, got False"
        assert "CLASSIFICATION" in analysis.analysis

    def test_failure_analysis_with_multiline_analysis(self) -> None:
        """Test FailureAnalysis with multiline analysis content."""
        analysis_text = """=== CLASSIFICATION ===
PRODUCT BUG

=== TEST ===
test_login

=== ANALYSIS ===
The authentication service is failing with a 500 error.

=== BUG REPORT ===
Title: Authentication fails with valid credentials
Severity: high
Component: auth
Description: Users cannot log in
Evidence: HTTP 500 response
"""
        analysis = FailureAnalysis(
            test_name="test_login",
            error="HTTP 500 Internal Server Error",
            analysis=analysis_text,
        )
        assert analysis.test_name == "test_login"
        assert "PRODUCT BUG" in analysis.analysis
        assert "BUG REPORT" in analysis.analysis

    def test_failure_analysis_required_fields(self) -> None:
        """Test that all required fields must be provided."""
        with pytest.raises(ValidationError):
            FailureAnalysis(
                test_name="test_example",
                # missing error and analysis
            )

        with pytest.raises(ValidationError):
            FailureAnalysis(
                test_name="test_example",
                error="Error message",
                # missing analysis
            )


class TestResultMessage:
    """Tests for the ResultMessage model."""

    def test_slack_message_creation(self) -> None:
        """Test creating a valid ResultMessage."""
        msg = ResultMessage(type="summary", text="Test content")
        assert msg.type == "summary"
        assert msg.text == "Test content"

    @pytest.mark.parametrize("msg_type", ["summary", "failure_detail", "child_job"])
    def test_slack_message_valid_types(self, msg_type: str) -> None:
        """Test that valid message types are accepted."""
        msg = ResultMessage(type=msg_type, text="content")
        assert msg.type == msg_type

    def test_slack_message_invalid_type(self) -> None:
        """Test that invalid message type raises ValidationError."""
        with pytest.raises(ValidationError):
            ResultMessage(type="invalid", text="content")

    def test_slack_message_required_fields(self) -> None:
        """Test that all required fields must be provided."""
        with pytest.raises(ValidationError):
            ResultMessage(type="summary")

        with pytest.raises(ValidationError):
            ResultMessage(text="content")


class TestAnalysisResult:
    """Tests for the AnalysisResult model."""

    def test_analysis_result_creation(self) -> None:
        """Test creating a valid AnalysisResult."""
        result = AnalysisResult(
            job_id="job-123",
            jenkins_url="https://jenkins.example.com/job/test/123/",
            status="completed",
            summary="Analysis complete",
            failures=[],
        )
        assert result.job_id == "job-123"
        assert result.status == "completed"
        assert result.failures == []

    def test_analysis_result_with_failures(
        self, sample_failure_analysis: FailureAnalysis
    ) -> None:
        """Test AnalysisResult with failure list."""
        result = AnalysisResult(
            job_id="job-123",
            jenkins_url="https://jenkins.example.com/job/test/123/",
            status="completed",
            summary="1 failure found",
            failures=[sample_failure_analysis],
        )
        assert len(result.failures) == 1
        assert result.failures[0].test_name == sample_failure_analysis.test_name

    @pytest.mark.parametrize("status", ["pending", "running", "completed", "failed"])
    def test_analysis_result_valid_statuses(self, status: str) -> None:
        """Test that valid status values are accepted."""
        result = AnalysisResult(
            job_id="job-123",
            jenkins_url="https://jenkins.example.com/job/test/123/",
            status=status,
            summary="Summary",
        )
        assert result.status == status

    def test_analysis_result_invalid_status(self) -> None:
        """Test that invalid status raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            AnalysisResult(
                job_id="job-123",
                jenkins_url="https://jenkins.example.com/job/test/123/",
                status="invalid",
                summary="Summary",
            )
        errors = exc_info.value.errors()
        assert any("status" in str(e) for e in errors)

    def test_analysis_result_default_failures(self) -> None:
        """Test that failures defaults to empty list."""
        result = AnalysisResult(
            job_id="job-123",
            jenkins_url="https://jenkins.example.com/job/test/123/",
            status="completed",
            summary="Summary",
        )
        assert result.failures == []

    def test_analysis_result_with_messages(self) -> None:
        """Test AnalysisResult with messages."""
        slack_msgs = [
            ResultMessage(type="summary", text="Summary text"),
            ResultMessage(type="failure_detail", text="Failure detail"),
        ]
        result = AnalysisResult(
            job_id="job-123",
            jenkins_url="https://jenkins.example.com/job/test/123/",
            status="completed",
            summary="Summary",
            messages=slack_msgs,
        )
        assert len(result.messages) == 2
        assert result.messages[0].type == "summary"
        assert result.messages[1].type == "failure_detail"

    def test_analysis_result_default_messages(self) -> None:
        """Test that messages defaults to empty list."""
        result = AnalysisResult(
            job_id="job-123",
            jenkins_url="https://jenkins.example.com/job/test/123/",
            status="completed",
            summary="Summary",
        )
        assert result.messages == []

    def test_analysis_result_messages_in_json(self) -> None:
        """Test that messages are included in JSON serialization."""
        slack_msgs = [ResultMessage(type="summary", text="Summary text")]
        result = AnalysisResult(
            job_id="job-123",
            jenkins_url="https://jenkins.example.com/job/test/123/",
            status="completed",
            summary="Summary",
            messages=slack_msgs,
        )
        data = result.model_dump(mode="json")
        assert "messages" in data
        assert len(data["messages"]) == 1
        assert data["messages"][0]["type"] == "summary"
        assert data["messages"][0]["text"] == "Summary text"


class TestJobStatus:
    """Tests for the JobStatus model."""

    def test_job_status_creation(self) -> None:
        """Test creating a valid JobStatus."""
        now = datetime.now()
        status = JobStatus(
            job_id="job-123",
            status="running",
            created_at=now,
        )
        assert status.job_id == "job-123"
        assert status.status == "running"
        assert status.created_at == now

    @pytest.mark.parametrize(
        "status_val", ["pending", "running", "completed", "failed"]
    )
    def test_job_status_valid_statuses(self, status_val: str) -> None:
        """Test that valid status values are accepted."""
        status = JobStatus(
            job_id="job-123",
            status=status_val,
            created_at=datetime.now(),
        )
        assert status.status == status_val

    def test_job_status_invalid_status(self) -> None:
        """Test that invalid status raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            JobStatus(
                job_id="job-123",
                status="invalid",
                created_at=datetime.now(),
            )
        errors = exc_info.value.errors()
        assert any("status" in str(e) for e in errors)
