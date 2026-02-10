"""Tests for HTML report generation."""

import pytest

from jenkins_job_insight.html_report import (
    _collect_all_failures,
    _compute_stats,
    _extract_field,
    _extract_section,
    _group_failures_by_root_cause,
    _parse_failure_analysis,
    format_result_as_html,
)
from jenkins_job_insight.models import (
    AnalysisResult,
    ChildJobAnalysis,
    FailureAnalysis,
)


# ---------------------------------------------------------------------------
# Local fixtures for test data not covered by conftest
# ---------------------------------------------------------------------------


@pytest.fixture
def unstructured_failure() -> FailureAnalysis:
    """A failure with plain-text analysis lacking === markers."""
    return FailureAnalysis(
        test_name="test_plain_text",
        error="RuntimeError: connection refused",
        analysis="The database was unreachable during the test run.",
    )


@pytest.fixture
def setup_failure() -> FailureAnalysis:
    """A failure whose error text contains the word 'setup'."""
    return FailureAnalysis(
        test_name="test_db_init",
        error="SetupError: setup fixture failed to initialize",
        analysis="""=== CLASSIFICATION ===
CODE ISSUE

=== BUG REPORT ===
Title: Database setup fixture broken
Severity: critical
Component: database
""",
    )


@pytest.fixture
def second_failure() -> FailureAnalysis:
    """A failure with a different analysis for grouping tests."""
    return FailureAnalysis(
        test_name="tests.network.test_timeout",
        error="TimeoutError: request exceeded 30s",
        analysis="""=== CLASSIFICATION ===
PRODUCT BUG

=== BUG REPORT ===
Title: API timeout under load
Severity: medium
Component: networking
""",
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
                analysis="=== CLASSIFICATION ===\nCODE ISSUE\n",
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
                analysis="""=== CLASSIFICATION ===
PRODUCT BUG

=== BUG REPORT ===
Title: Child validation error
Severity: high
Component: validation
""",
            ),
        ],
        failed_children=[nested_child],
    )
    return AnalysisResult(
        job_id="parent-job-456",
        jenkins_url="https://jenkins.example.com/job/parent/456/",
        status="completed",
        summary="Multiple failures across parent and children",
        failures=[sample_failure_analysis],
        child_job_analyses=[child],
    )


@pytest.fixture
def empty_result() -> AnalysisResult:
    """An AnalysisResult with no failures at all."""
    return AnalysisResult(
        job_id="empty-job-789",
        jenkins_url="https://jenkins.example.com/job/empty/789/",
        status="completed",
        summary="No failures found",
        failures=[],
    )


# ===========================================================================
# TestExtractSection
# ===========================================================================


class TestExtractSection:
    """Tests for the _extract_section helper."""

    def test_extracts_classification_section(self) -> None:
        """Parse '=== CLASSIFICATION ===' followed by another marker."""
        text = "=== CLASSIFICATION ===\nPRODUCT BUG\n\n=== TEST ==="
        result = _extract_section(text, "CLASSIFICATION")
        assert result == "PRODUCT BUG"

    def test_extracts_analysis_section(self) -> None:
        """Multiline content between two markers is returned intact."""
        text = "=== ANALYSIS ===\nLine one.\nLine two.\n\n=== BUG REPORT ==="
        result = _extract_section(text, "ANALYSIS")
        assert "Line one." in result
        assert "Line two." in result

    def test_returns_empty_for_missing_section(self) -> None:
        """An absent section yields an empty string."""
        text = "=== CLASSIFICATION ===\nPRODUCT BUG\n"
        result = _extract_section(text, "NONEXISTENT")
        assert result == ""

    def test_case_insensitive_matching(self) -> None:
        """Section lookup is case-insensitive."""
        text = "=== classification ===\nPRODUCT BUG\n\n=== test ==="
        result = _extract_section(text, "CLASSIFICATION")
        assert result == "PRODUCT BUG"

    def test_extracts_last_section(self) -> None:
        """Section at end of text with no following === marker."""
        text = (
            "=== CLASSIFICATION ===\nPRODUCT BUG\n\n"
            "=== ANALYSIS ===\nThis is the final section."
        )
        result = _extract_section(text, "ANALYSIS")
        assert result == "This is the final section."


# ===========================================================================
# TestExtractField
# ===========================================================================


class TestExtractField:
    """Tests for the _extract_field helper."""

    def test_extracts_title_field(self) -> None:
        """Simple 'Title: value' extraction."""
        text = "Title: Login fails\nSeverity: high"
        result = _extract_field(text, "Title")
        assert result == "Login fails"

    def test_extracts_severity_field(self) -> None:
        """Severity field is extracted correctly."""
        text = "Title: Something\nSeverity: high\nComponent: auth"
        result = _extract_field(text, "Severity")
        assert result == "high"

    def test_returns_empty_for_missing_field(self) -> None:
        """Missing field yields an empty string."""
        text = "Title: Login fails"
        result = _extract_field(text, "Component")
        assert result == ""

    def test_handles_colon_in_value(self) -> None:
        """Colons within the value are preserved."""
        text = "Error: HTTP 500: Internal Server Error"
        result = _extract_field(text, "Error")
        assert result == "HTTP 500: Internal Server Error"


# ===========================================================================
# TestParseFailureAnalysis
# ===========================================================================


class TestParseFailureAnalysis:
    """Tests for the _parse_failure_analysis helper."""

    def test_parses_structured_analysis(
        self, sample_failure_analysis: FailureAnalysis
    ) -> None:
        """All fields are extracted from a well-structured analysis."""
        parsed = _parse_failure_analysis(sample_failure_analysis)
        assert parsed["classification"] == "PRODUCT BUG"
        assert parsed["severity"] == "high"
        assert parsed["component"] == "auth"
        assert parsed["bug_title"] == "Login fails with valid credentials"
        assert parsed["stage"] == "execution"

    def test_parses_unstructured_analysis(
        self, unstructured_failure: FailureAnalysis
    ) -> None:
        """Plain text without === markers falls back to defaults."""
        parsed = _parse_failure_analysis(unstructured_failure)
        assert parsed["classification"] == "Unknown"
        assert parsed["severity"] == "unknown"
        assert parsed["component"] == "unknown"
        # bug_title should fall back to error text
        assert parsed["bug_title"] == unstructured_failure.error

    def test_detects_setup_stage(self, setup_failure: FailureAnalysis) -> None:
        """Failure with 'setup' in error text is classified as setup stage."""
        parsed = _parse_failure_analysis(setup_failure)
        assert parsed["stage"] == "setup"

    def test_detects_execution_stage_default(
        self, sample_failure_analysis: FailureAnalysis
    ) -> None:
        """Failure without 'setup' keyword defaults to execution stage."""
        parsed = _parse_failure_analysis(sample_failure_analysis)
        assert parsed["stage"] == "execution"


# ===========================================================================
# TestGroupFailuresByRootCause
# ===========================================================================


class TestGroupFailuresByRootCause:
    """Tests for the _group_failures_by_root_cause helper."""

    def test_groups_identical_analyses(self) -> None:
        """Three failures with the same analysis text produce one group."""
        shared_analysis = "=== CLASSIFICATION ===\nPRODUCT BUG\n"
        failures = [
            FailureAnalysis(
                test_name=f"test_{i}",
                error=f"Error {i}",
                analysis=shared_analysis,
            )
            for i in range(3)
        ]
        groups = _group_failures_by_root_cause(failures)
        assert len(groups) == 1
        assert len(groups[0]["failures"]) == 3

    def test_separates_different_analyses(
        self,
        sample_failure_analysis: FailureAnalysis,
        second_failure: FailureAnalysis,
    ) -> None:
        """Two failures with different analyses produce two groups."""
        groups = _group_failures_by_root_cause(
            [sample_failure_analysis, second_failure]
        )
        assert len(groups) == 2

    def test_assigns_bug_ids(
        self,
        sample_failure_analysis: FailureAnalysis,
        second_failure: FailureAnalysis,
    ) -> None:
        """Groups are assigned sequential BUG-N identifiers."""
        groups = _group_failures_by_root_cause(
            [sample_failure_analysis, second_failure]
        )
        bug_ids = [g["bug_id"] for g in groups]
        assert bug_ids == ["BUG-1", "BUG-2"]

    def test_empty_list_returns_empty(self) -> None:
        """An empty failure list produces an empty group list."""
        groups = _group_failures_by_root_cause([])
        assert groups == []


# ===========================================================================
# TestComputeStats
# ===========================================================================


class TestComputeStats:
    """Tests for the _compute_stats helper."""

    def test_computes_total_and_unique(
        self,
        sample_failure_analysis: FailureAnalysis,
        second_failure: FailureAnalysis,
    ) -> None:
        """Total count and unique error count are accurate."""
        failures = [sample_failure_analysis, second_failure]
        groups = _group_failures_by_root_cause(failures)
        stats = _compute_stats(failures, groups)
        assert stats["total"] == 2
        assert stats["unique_errors"] == 2

    def test_computes_setup_exec_counts(
        self,
        sample_failure_analysis: FailureAnalysis,
        setup_failure: FailureAnalysis,
    ) -> None:
        """Setup and execution counts reflect failure stage detection."""
        failures = [sample_failure_analysis, setup_failure]
        groups = _group_failures_by_root_cause(failures)
        stats = _compute_stats(failures, groups)
        assert stats["setup_count"] == 1
        assert stats["exec_count"] == 1

    def test_computes_dominant_classification(
        self, sample_failure_analysis: FailureAnalysis
    ) -> None:
        """Dominant classification is the most frequent one."""
        # Create 3 identical failures to ensure PRODUCT BUG dominates
        failures = [sample_failure_analysis] * 3
        groups = _group_failures_by_root_cause(failures)
        stats = _compute_stats(failures, groups)
        assert stats["dominant_classification"] == "PRODUCT BUG"

    def test_computes_module_distribution(
        self, second_failure: FailureAnalysis
    ) -> None:
        """Module distribution extracts first two dot-segments."""
        # second_failure has test_name "tests.network.test_timeout"
        failures = [second_failure]
        groups = _group_failures_by_root_cause(failures)
        stats = _compute_stats(failures, groups)
        assert "tests.network" in stats["modules"]
        assert stats["modules"]["tests.network"] == 1

    def test_handles_empty_failures(self) -> None:
        """Empty failure list produces zero counts."""
        stats = _compute_stats([], [])
        assert stats["total"] == 0
        assert stats["unique_errors"] == 0
        assert stats["setup_count"] == 0
        assert stats["exec_count"] == 0
        assert stats["dominant_classification"] == "Unknown"
        assert stats["dominant_severity"] == "unknown"


# ===========================================================================
# TestCollectAllFailures
# ===========================================================================


class TestCollectAllFailures:
    """Tests for the _collect_all_failures helper."""

    def test_collects_from_result_failures(
        self, sample_analysis_result: AnalysisResult
    ) -> None:
        """Direct failures on the result are collected."""
        all_failures = _collect_all_failures(sample_analysis_result)
        assert len(all_failures) == 1
        assert all_failures[0].test_name == "test_login_success"

    def test_collects_from_child_jobs(
        self, result_with_children: AnalysisResult
    ) -> None:
        """Failures from child_job_analyses are included."""
        all_failures = _collect_all_failures(result_with_children)
        child_test_names = [f.test_name for f in all_failures]
        assert "tests.child.test_child_fail" in child_test_names

    def test_collects_from_nested_children(
        self, result_with_children: AnalysisResult
    ) -> None:
        """Failures from recursively nested failed_children are included."""
        all_failures = _collect_all_failures(result_with_children)
        nested_test_names = [f.test_name for f in all_failures]
        assert "tests.deep.test_nested" in nested_test_names
        # 1 parent + 1 child + 1 nested = 3 total
        assert len(all_failures) == 3

    def test_empty_result(self, empty_result: AnalysisResult) -> None:
        """Result with no failures anywhere returns empty list."""
        all_failures = _collect_all_failures(empty_result)
        assert all_failures == []


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
        # The report may link back to Jenkins, but must not load
        # external CSS or JavaScript resources.
        assert '<link rel="stylesheet"' not in html_output
        assert '<script src="http' not in html_output
        assert 'src="http' not in html_output

    def test_html_escapes_user_content(self) -> None:
        """Special characters in user content are HTML-escaped."""
        xss_failure = FailureAnalysis(
            test_name="<script>alert('xss')</script>",
            error="<img onerror='hack'>",
            analysis="=== CLASSIFICATION ===\nUNKNOWN\n",
        )
        result = AnalysisResult(
            job_id="xss-test",
            jenkins_url="https://jenkins.example.com/job/xss/1/",
            status="completed",
            summary="XSS test",
            failures=[xss_failure],
        )
        html_output = format_result_as_html(result)
        # Raw tags must not appear; escaped forms must
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
        """When ai_provider is provided, it appears in the output."""
        html_output = format_result_as_html(
            sample_analysis_result, ai_provider="claude", ai_model="opus-4"
        )
        assert "Claude" in html_output
        assert "opus-4" in html_output

    def test_includes_child_job_analysis(
        self, result_with_children: AnalysisResult
    ) -> None:
        """Child job information is rendered in the output."""
        html_output = format_result_as_html(result_with_children)
        assert "child-job" in html_output
        assert "Child Job Analyses" in html_output
        assert "child error" in html_output

    def test_contains_donut_chart(self, sample_analysis_result: AnalysisResult) -> None:
        """Output contains SVG donut chart elements."""
        html_output = format_result_as_html(sample_analysis_result)
        assert "<svg" in html_output
        assert "circle" in html_output
        assert "donut" in html_output.lower()

    def test_contains_bug_cards(self, sample_analysis_result: AnalysisResult) -> None:
        """Output contains <details> elements for expandable bug cards."""
        html_output = format_result_as_html(sample_analysis_result)
        assert "<details" in html_output
        assert "bug-card" in html_output

    def test_contains_detail_table(
        self, sample_analysis_result: AnalysisResult
    ) -> None:
        """Output contains a <table> with test names."""
        html_output = format_result_as_html(sample_analysis_result)
        assert "<table>" in html_output
        assert "test_login_success" in html_output
        assert "Test Name" in html_output
