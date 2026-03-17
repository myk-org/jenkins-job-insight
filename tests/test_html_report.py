"""Tests for HTML report generation."""

import pytest

from jenkins_job_insight.html_report import (
    _classification_css_class,
    format_result_as_html,
    format_status_page,
    generate_dashboard_html,
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
        # The XSS payload must be escaped (not rendered as raw HTML)
        assert "&lt;script&gt;alert(" in html_output
        assert "<script>alert(" not in html_output
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

    def test_report_contains_favicon_link(
        self, sample_analysis_result: AnalysisResult
    ) -> None:
        """Report HTML contains a favicon link tag."""
        html_output = format_result_as_html(sample_analysis_result)
        assert '<link rel="icon"' in html_output

    def test_report_header_counts_child_job_failures(self) -> None:
        """Header shows total failure count including child job failures."""
        top_level_failure = FailureAnalysis(
            test_name="tests.parent.test_top_level",
            error="AssertionError: top-level failure",
            analysis=AnalysisDetail(classification="CODE ISSUE"),
        )
        child = ChildJobAnalysis(
            job_name="child-job",
            build_number=10,
            jenkins_url="https://jenkins.example.com/job/child/10/",
            failures=[
                FailureAnalysis(
                    test_name="tests.child.test_first",
                    error="ValueError: child error one",
                    analysis=AnalysisDetail(classification="PRODUCT BUG"),
                ),
                FailureAnalysis(
                    test_name="tests.child.test_second",
                    error="RuntimeError: child error two",
                    analysis=AnalysisDetail(classification="CODE ISSUE"),
                ),
            ],
        )
        result = AnalysisResult(
            job_id="header-count-test",
            job_name="header-count",
            build_number=1,
            jenkins_url="https://jenkins.example.com/job/header-count/1/",
            status="completed",
            summary="Failures across parent and child",
            failures=[top_level_failure],
            child_job_analyses=[child],
        )
        html_output = format_result_as_html(result)
        assert "3 failures" in html_output


# ===========================================================================
# TestStatusPageFavicon
# ===========================================================================


class TestStatusPageFavicon:
    """Tests for favicon in the status page."""

    def test_status_page_contains_favicon_link(self) -> None:
        """Status page HTML contains a favicon link tag."""
        html_output = format_status_page(
            job_id="status-test-123",
            status="running",
            result={
                "jenkins_url": "https://jenkins.example.com/job/test/1/",
                "created_at": "2026-01-01T00:00:00",
            },
        )
        assert '<link rel="icon"' in html_output


# ===========================================================================
# TestGenerateDashboardHtml
# ===========================================================================


class TestGenerateDashboardHtml:
    """Tests for the generate_dashboard_html function."""

    def test_dashboard_html_generation(self) -> None:
        """Dashboard HTML is generated correctly with job data."""
        jobs = [
            {
                "job_id": "job-aaa",
                "jenkins_url": "https://jenkins.example.com/job/test/1/",
                "status": "completed",
                "created_at": "2026-01-15T10:00:00",
                "job_name": "my-pipeline",
                "build_number": 42,
                "failure_count": 3,
            },
            {
                "job_id": "job-bbb",
                "jenkins_url": "",
                "status": "failed",
                "created_at": "2026-01-14T09:00:00",
            },
        ]
        html_output = generate_dashboard_html(jobs, base_url="https://example.com")
        assert "<!DOCTYPE html>" in html_output
        assert "Jenkins Job Insight" in html_output
        assert "my-pipeline" in html_output
        assert "job-aaa" in html_output
        assert "job-bbb" in html_output
        assert "https://example.com/results/job-aaa.html" in html_output
        # The badge is rendered with the total, then JS updates it
        assert "2 jobs" in html_output

    def test_dashboard_html_empty_state(self) -> None:
        """Empty dashboard shows the 'No analysis results yet' message."""
        html_output = generate_dashboard_html([], base_url="https://example.com")
        assert "No analysis results yet" in html_output
        assert "0 jobs" in html_output

    def test_dashboard_html_escapes_content(self) -> None:
        """Special characters in job names are HTML-escaped to prevent XSS."""
        jobs = [
            {
                "job_id": "xss-job",
                "jenkins_url": "",
                "status": "completed",
                "created_at": "2026-01-01T00:00:00",
                "job_name": "<script>alert('xss')</script>",
                "build_number": 1,
            },
        ]
        html_output = generate_dashboard_html(jobs, base_url="https://example.com")
        assert "<script>alert" not in html_output
        assert "&lt;script&gt;" in html_output

    def test_dashboard_card_has_correct_href(self) -> None:
        """Dashboard card links point to the correct /results/{job_id}.html path."""
        jobs = [
            {
                "job_id": "href-test-id",
                "jenkins_url": "",
                "status": "completed",
                "created_at": "2026-01-01T00:00:00",
                "job_name": "href-test",
            },
        ]
        html_output = generate_dashboard_html(
            jobs, base_url="https://myserver.example.com"
        )
        assert "https://myserver.example.com/results/href-test-id.html" in html_output

    def test_dashboard_contains_favicon_link(self) -> None:
        """Dashboard HTML contains a favicon link tag."""
        html_output = generate_dashboard_html([], base_url="https://example.com")
        assert '<link rel="icon"' in html_output

    def test_dashboard_contains_search_input(self) -> None:
        """Dashboard with jobs contains a search input field."""
        jobs = [
            {
                "job_id": "search-job",
                "jenkins_url": "",
                "status": "completed",
                "created_at": "2026-01-01T00:00:00",
                "job_name": "search-test",
            },
        ]
        html_output = generate_dashboard_html(jobs, base_url="https://example.com")
        assert 'id="search-input"' in html_output
        assert 'placeholder="Search jobs' in html_output

    def test_dashboard_contains_pagination_controls(self) -> None:
        """Dashboard with jobs contains pagination Previous/Next buttons and page info."""
        jobs = [
            {
                "job_id": "page-job",
                "jenkins_url": "",
                "status": "completed",
                "created_at": "2026-01-01T00:00:00",
                "job_name": "page-test",
            },
        ]
        html_output = generate_dashboard_html(jobs, base_url="https://example.com")
        assert 'id="prev-btn"' in html_output
        assert 'id="next-btn"' in html_output
        assert 'id="page-info"' in html_output
        assert "Previous" in html_output
        assert "Next" in html_output

    def test_dashboard_contains_per_page_dropdown(self) -> None:
        """Dashboard with jobs contains a per-page dropdown with 10, 50, 100 options."""
        jobs = [
            {
                "job_id": "pp-job",
                "jenkins_url": "",
                "status": "completed",
                "created_at": "2026-01-01T00:00:00",
                "job_name": "pp-test",
            },
        ]
        html_output = generate_dashboard_html(jobs, base_url="https://example.com")
        assert 'id="per-page-select"' in html_output
        assert 'value="10"' in html_output
        assert 'value="50"' in html_output
        assert 'value="100"' in html_output

    def test_dashboard_contains_javascript(self) -> None:
        """Dashboard with jobs contains inline JavaScript for pagination and search."""
        jobs = [
            {
                "job_id": "js-job",
                "jenkins_url": "",
                "status": "completed",
                "created_at": "2026-01-01T00:00:00",
                "job_name": "js-test",
            },
        ]
        html_output = generate_dashboard_html(jobs, base_url="https://example.com")
        assert "<script>" in html_output
        assert "currentPage" in html_output
        assert "applyFilter" in html_output

    def test_dashboard_empty_has_no_search_or_pagination(self) -> None:
        """Empty dashboard does not render search, pagination, or per-page controls,
        but still renders the limit control."""
        html_output = generate_dashboard_html([], base_url="https://example.com")
        assert 'id="search-input"' not in html_output
        assert 'id="prev-btn"' not in html_output
        assert 'id="per-page-select"' not in html_output
        assert "<script>" not in html_output
        # Limit control is always present
        assert 'id="limit-input"' in html_output

    def test_dashboard_job_cards_container(self) -> None:
        """Dashboard wraps job cards in a container with id='job-cards'."""
        jobs = [
            {
                "job_id": "container-job",
                "jenkins_url": "",
                "status": "completed",
                "created_at": "2026-01-01T00:00:00",
                "job_name": "container-test",
            },
        ]
        html_output = generate_dashboard_html(jobs, base_url="https://example.com")
        assert 'id="job-cards"' in html_output

    def test_dashboard_contains_limit_control(self) -> None:
        """Dashboard with jobs contains the 'Load last' limit control."""
        jobs = [
            {
                "job_id": "limit-job",
                "jenkins_url": "",
                "status": "completed",
                "created_at": "2026-01-01T00:00:00",
                "job_name": "limit-test",
            },
        ]
        html_output = generate_dashboard_html(
            jobs, base_url="https://example.com", limit=100
        )
        assert 'id="limit-input"' in html_output
        assert 'id="limit-btn"' in html_output
        assert "Load last" in html_output
        assert 'value="100"' in html_output

    def test_dashboard_limit_value_reflected_in_input(self) -> None:
        """The limit value is reflected in the number input's value attribute."""
        jobs = [
            {
                "job_id": "val-job",
                "jenkins_url": "",
                "status": "completed",
                "created_at": "2026-01-01T00:00:00",
                "job_name": "val-test",
            },
        ]
        for limit_val in (50, 200, 1000):
            html_output = generate_dashboard_html(
                jobs, base_url="https://example.com", limit=limit_val
            )
            assert (
                f'id="limit-input" class="limit-input" min="1" value="{limit_val}"'
                in html_output
            )

    def test_dashboard_empty_still_has_limit_control(self) -> None:
        """Even with 0 jobs the limit control is present."""
        html_output = generate_dashboard_html(
            [], base_url="https://example.com", limit=500
        )
        assert 'id="limit-input"' in html_output
        assert 'id="limit-btn"' in html_output
        assert "Load last" in html_output

    def test_dashboard_limit_default_value(self) -> None:
        """Default limit value of 500 is used when not specified."""
        jobs = [
            {
                "job_id": "default-job",
                "jenkins_url": "",
                "status": "completed",
                "created_at": "2026-01-01T00:00:00",
                "job_name": "default-test",
            },
        ]
        html_output = generate_dashboard_html(jobs, base_url="https://example.com")
        assert 'value="500"' in html_output

    def test_dashboard_load_button_uses_base_url(self) -> None:
        """Load buttons in both empty and populated states use base_url, not hardcoded /dashboard."""
        base = "https://myproxy.example.com/prefix"
        # Populated state
        jobs = [
            {
                "job_id": "btn-job",
                "jenkins_url": "",
                "status": "completed",
                "created_at": "2026-01-01T00:00:00",
                "job_name": "btn-test",
            },
        ]
        html_output = generate_dashboard_html(jobs, base_url=base)
        assert f"{base}/dashboard?limit=" in html_output
        assert "'/dashboard?limit=" not in html_output

        # Empty state
        html_empty = generate_dashboard_html([], base_url=base)
        assert f"{base}/dashboard?limit=" in html_empty
        assert "'/dashboard?limit=" not in html_empty

    def test_dashboard_common_css_shared(self) -> None:
        """Both report and dashboard HTML contain the shared CSS custom properties."""
        from jenkins_job_insight.html_report import _common_css

        css = _common_css()
        # Verify it contains key shared rules
        assert "--bg-primary" in css
        assert "--accent-blue" in css
        assert ".sticky-header" in css
        assert ".report-footer" in css
        assert ".container" in css
