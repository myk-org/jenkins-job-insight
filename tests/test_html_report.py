"""Tests for HTML report generation."""

import pytest

from jenkins_job_insight.html_report import (
    _classification_css_class,
    format_result_as_html,
)
from jenkins_job_insight.models import (
    AnalysisDetail,
    AnalysisResult,
    ChildJobAnalysis,
    CodeFix,
    FailureAnalysis,
    ProductBugReport,
)


# ---------------------------------------------------------------------------
# Local fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def code_issue_failure() -> FailureAnalysis:
    """A failure classified as CODE ISSUE with a code fix."""
    return FailureAnalysis(
        test_name="test_config_load",
        error="ImportError: missing module",
        analysis=AnalysisDetail(
            classification="CODE ISSUE",
            affected_tests=["test_config_load"],
            details="The test failed due to a missing import.",
            code_fix=CodeFix(
                file="src/config.py",
                line="10",
                change="Add 'import os' at the top",
            ),
        ),
    )


@pytest.fixture
def product_bug_failure() -> FailureAnalysis:
    """A failure classified as PRODUCT BUG with a bug report."""
    return FailureAnalysis(
        test_name="tests.network.test_timeout",
        error="TimeoutError: request exceeded 30s",
        analysis=AnalysisDetail(
            classification="PRODUCT BUG",
            affected_tests=["tests.network.test_timeout"],
            details="The API is timing out under load.",
            product_bug_report=ProductBugReport(
                title="API timeout under load",
                severity="medium",
                component="networking",
                description="API requests time out when server is under load",
                evidence="TimeoutError after 30s",
            ),
        ),
    )


@pytest.fixture
def result_with_children(
    sample_failure_analysis: FailureAnalysis,
) -> AnalysisResult:
    """An AnalysisResult with child and nested child job analyses."""
    nested_child = ChildJobAnalysis(
        job_name="nested-child",
        build_number=3,
        jenkins_url="https://jenkins.example.com/job/nested/3/",
        failures=[
            FailureAnalysis(
                test_name="tests.deep.test_nested",
                error="AssertionError: nested failure",
                analysis=AnalysisDetail(classification="CODE ISSUE"),
            ),
        ],
    )
    child = ChildJobAnalysis(
        job_name="child-job",
        build_number=2,
        jenkins_url="https://jenkins.example.com/job/child/2/",
        summary="Child job had failures",
        note="Depth limit reached",
        failures=[
            FailureAnalysis(
                test_name="tests.child.test_child_fail",
                error="ValueError: child error",
                analysis=AnalysisDetail(
                    classification="PRODUCT BUG",
                    product_bug_report=ProductBugReport(
                        title="Child validation error",
                        severity="high",
                        component="validation",
                    ),
                ),
            ),
        ],
        failed_children=[nested_child],
    )
    return AnalysisResult(
        job_id="parent-job-456",
        job_name="parent",
        build_number=456,
        jenkins_url="https://jenkins.example.com/job/parent/456/",
        status="completed",
        summary="Multiple failures across parent and children",
        ai_provider="claude",
        ai_model="test-model",
        failures=[sample_failure_analysis],
        child_job_analyses=[child],
    )


@pytest.fixture
def empty_result() -> AnalysisResult:
    """An AnalysisResult with no failures at all."""
    return AnalysisResult(
        job_id="empty-job-789",
        job_name="empty",
        build_number=789,
        jenkins_url="https://jenkins.example.com/job/empty/789/",
        status="completed",
        summary="No failures found",
        ai_provider="claude",
        ai_model="test-model",
        failures=[],
    )


# ===========================================================================
# TestClassificationCssClass
# ===========================================================================


class TestClassificationCssClass:
    """Tests for the _classification_css_class helper."""

    def test_product_bug(self) -> None:
        assert _classification_css_class("PRODUCT BUG") == "product-bug"

    def test_code_issue(self) -> None:
        assert _classification_css_class("CODE ISSUE") == "code-issue"

    def test_unknown(self) -> None:
        assert _classification_css_class("SOMETHING ELSE") == "unknown"

    def test_empty(self) -> None:
        assert _classification_css_class("") == "unknown"


# ===========================================================================
# TestFormatResultAsHtml
# ===========================================================================


class TestFormatResultAsHtml:
    """Tests for the format_result_as_html public function."""

    def test_returns_valid_html(self, sample_analysis_result: AnalysisResult) -> None:
        """Output starts with DOCTYPE and ends with </html>."""
        html_output = format_result_as_html(sample_analysis_result)
        assert html_output.strip().startswith("<!DOCTYPE html>")
        assert html_output.strip().endswith("</html>")

    def test_contains_job_info(self, sample_analysis_result: AnalysisResult) -> None:
        """Job name and build number appear in the rendered output."""
        html_output = format_result_as_html(sample_analysis_result)
        assert "my-job" in html_output
        assert "123" in html_output

    def test_contains_failure_info(
        self, sample_analysis_result: AnalysisResult
    ) -> None:
        """Test name and error text appear in the rendered output."""
        html_output = format_result_as_html(sample_analysis_result)
        assert "test_login_success" in html_output
        assert "AssertionError" in html_output

    def test_contains_inline_css(self, sample_analysis_result: AnalysisResult) -> None:
        """Output contains a <style> tag with CSS custom properties."""
        html_output = format_result_as_html(sample_analysis_result)
        assert "<style>" in html_output
        assert "--bg-primary" in html_output

    def test_self_contained(self, sample_analysis_result: AnalysisResult) -> None:
        """No external stylesheets or scripts are loaded."""
        html_output = format_result_as_html(sample_analysis_result)
        assert '<link rel="stylesheet"' not in html_output
        assert '<script src="http' not in html_output

    def test_html_escapes_user_content(self) -> None:
        """Special characters in user content are HTML-escaped."""
        xss_failure = FailureAnalysis(
            test_name="<script>alert('xss')</script>",
            error="<img onerror='hack'>",
            analysis=AnalysisDetail(classification="UNKNOWN"),
        )
        result = AnalysisResult(
            job_id="xss-test",
            job_name="xss",
            build_number=1,
            jenkins_url="https://jenkins.example.com/job/xss/1/",
            status="completed",
            summary="XSS test",
            failures=[xss_failure],
        )
        html_output = format_result_as_html(result)
        assert "<script>" not in html_output
        assert "&lt;script&gt;" in html_output
        assert "<img onerror" not in html_output
        assert "&lt;img onerror" in html_output

    def test_empty_failures_shows_message(self, empty_result: AnalysisResult) -> None:
        """Result with no failures shows an appropriate message."""
        html_output = format_result_as_html(empty_result)
        assert "No failures detected" in html_output

    def test_includes_provider_info(
        self, sample_analysis_result: AnalysisResult
    ) -> None:
        """AI provider appears in the output (from result fields)."""
        html_output = format_result_as_html(sample_analysis_result)
        assert "Claude" in html_output
        assert "test-model" in html_output

    def test_includes_child_job_analysis(
        self, result_with_children: AnalysisResult
    ) -> None:
        """Child job information is rendered in the output."""
        html_output = format_result_as_html(result_with_children)
        assert "child-job" in html_output
        assert "Child Job Analyses" in html_output
        assert "child error" in html_output

    def test_contains_failure_cards(
        self, sample_analysis_result: AnalysisResult
    ) -> None:
        """Output contains <details> elements for expandable failure cards."""
        html_output = format_result_as_html(sample_analysis_result)
        assert "<details" in html_output
        assert "failure-card" in html_output

    def test_contains_detail_table(
        self, sample_analysis_result: AnalysisResult
    ) -> None:
        """Output contains a <table> with test names."""
        html_output = format_result_as_html(sample_analysis_result)
        assert "<table>" in html_output
        assert "test_login_success" in html_output
        assert "Test Name" in html_output

    def test_contains_classification_in_table(
        self, sample_analysis_result: AnalysisResult
    ) -> None:
        """Classification column appears in the failures table."""
        html_output = format_result_as_html(sample_analysis_result)
        assert "Classification" in html_output
        assert "PRODUCT BUG" in html_output

    def test_renders_code_fix_details(
        self, code_issue_failure: FailureAnalysis
    ) -> None:
        """Code fix details are rendered in the failure card."""
        result = AnalysisResult(
            job_id="fix-test",
            job_name="test",
            build_number=1,
            jenkins_url="https://jenkins.example.com/job/test/1/",
            status="completed",
            summary="Code issue found",
            failures=[code_issue_failure],
        )
        html_output = format_result_as_html(result)
        assert "Code Fix" in html_output
        assert "src/config.py" in html_output
        assert (
            "Add &#x27;import os&#x27; at the top" in html_output
            or "import os" in html_output
        )

    def test_renders_product_bug_report(
        self, product_bug_failure: FailureAnalysis
    ) -> None:
        """Product bug report details are rendered in the failure card."""
        result = AnalysisResult(
            job_id="bug-test",
            job_name="test",
            build_number=1,
            jenkins_url="https://jenkins.example.com/job/test/1/",
            status="completed",
            summary="Product bug found",
            failures=[product_bug_failure],
        )
        html_output = format_result_as_html(result)
        assert "Product Bug Report" in html_output
        assert "API timeout under load" in html_output
        assert "networking" in html_output
