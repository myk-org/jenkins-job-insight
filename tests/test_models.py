"""Tests for Pydantic models."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from jenkins_job_insight.models import (
    AnalysisDetail,
    AnalysisResult,
    AnalyzeRequest,
    CodeFix,
    FailureAnalysis,
    JobStatus,
    ProductBugReport,
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

    def test_analyze_request_with_optional_fields(self) -> None:
        """Test creating AnalyzeRequest with all optional fields."""
        request = AnalyzeRequest(
            job_name="test",
            build_number=123,
            tests_repo_url="https://github.com/example/repo",
            callback_url="https://callback.example.com/webhook",
            callback_headers={"Authorization": "Bearer token"},
        )
        assert request.callback_url is not None
        assert request.callback_headers == {"Authorization": "Bearer token"}

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


class TestProductBugReport:
    """Tests for the ProductBugReport model."""

    def test_creation_with_defaults(self) -> None:
        """Test creating with all defaults."""
        report = ProductBugReport()
        assert report.title == ""
        assert report.severity == ""
        assert report.component == ""

    def test_creation_with_values(self) -> None:
        """Test creating with all fields."""
        report = ProductBugReport(
            title="Bug title",
            severity="high",
            component="auth",
            description="Something is broken",
            evidence="Stack trace here",
        )
        assert report.title == "Bug title"
        assert report.severity == "high"


class TestCodeFix:
    """Tests for the CodeFix model."""

    def test_creation_with_defaults(self) -> None:
        """Test creating with all defaults."""
        fix = CodeFix()
        assert fix.file == ""
        assert fix.line == ""
        assert fix.change == ""

    def test_creation_with_values(self) -> None:
        """Test creating with all fields."""
        fix = CodeFix(file="src/main.py", line="42", change="Fix the bug")
        assert fix.file == "src/main.py"
        assert fix.line == "42"


class TestAnalysisDetail:
    """Tests for the AnalysisDetail model."""

    def test_creation_with_defaults(self) -> None:
        """Test creating with all defaults."""
        detail = AnalysisDetail()
        assert detail.classification == ""
        assert detail.affected_tests == []
        assert detail.details == ""
        assert detail.code_fix is False
        assert detail.product_bug_report is False

    def test_creation_with_code_fix(self) -> None:
        """Test creating with a code fix."""
        detail = AnalysisDetail(
            classification="CODE ISSUE",
            details="Missing import",
            code_fix=CodeFix(file="test.py", line="1", change="Add import"),
        )
        assert detail.code_fix
        assert detail.code_fix.file == "test.py"
        assert not detail.product_bug_report

    def test_creation_with_bug_report(self) -> None:
        """Test creating with a product bug report."""
        detail = AnalysisDetail(
            classification="PRODUCT BUG",
            details="API broken",
            product_bug_report=ProductBugReport(title="API bug", severity="high"),
        )
        assert detail.product_bug_report
        assert detail.product_bug_report.title == "API bug"
        assert not detail.code_fix


class TestFailureAnalysis:
    """Tests for the FailureAnalysis model."""

    def test_failure_analysis_creation(self) -> None:
        """Test creating a valid FailureAnalysis."""
        analysis = FailureAnalysis(
            test_name="test_example",
            error="AssertionError: Expected True, got False",
            analysis=AnalysisDetail(
                classification="CODE ISSUE",
                details="The test assertion is wrong",
            ),
        )
        assert analysis.test_name == "test_example"
        assert analysis.error == "AssertionError: Expected True, got False"
        assert analysis.analysis.classification == "CODE ISSUE"

    def test_failure_analysis_with_full_detail(self) -> None:
        """Test FailureAnalysis with full AnalysisDetail content."""
        analysis = FailureAnalysis(
            test_name="test_login",
            error="HTTP 500 Internal Server Error",
            analysis=AnalysisDetail(
                classification="PRODUCT BUG",
                affected_tests=["test_login"],
                details="The authentication service is failing with a 500 error.",
                product_bug_report=ProductBugReport(
                    title="Authentication fails with valid credentials",
                    severity="high",
                    component="auth",
                    description="Users cannot log in",
                    evidence="HTTP 500 response",
                ),
            ),
        )
        assert analysis.test_name == "test_login"
        assert analysis.analysis.classification == "PRODUCT BUG"
        assert analysis.analysis.product_bug_report
        assert (
            analysis.analysis.product_bug_report.title
            == "Authentication fails with valid credentials"
        )

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
