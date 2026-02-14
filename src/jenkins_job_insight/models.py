"""Pydantic request and response models."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_serializer, model_validator


class BaseAnalysisRequest(BaseModel):
    """Shared fields for all analysis request types."""

    tests_repo_url: HttpUrl | None = Field(
        default=None,
        description="URL of the tests repository (overrides env var default)",
    )
    ai_provider: Literal["claude", "gemini", "cursor"] | None = Field(
        default=None,
        description="AI provider to use: claude, gemini, or cursor (overrides env var default)",
    )
    ai_model: str | None = Field(
        default=None,
        description="AI model to use (overrides env var default)",
    )
    enable_jira: bool | None = Field(
        default=None,
        description="Enable Jira bug search (default: true when Jira is configured, set false to skip)",
    )


class AnalyzeRequest(BaseAnalysisRequest):
    """Request payload for analysis endpoint."""

    job_name: str = Field(
        description="Jenkins job name (can include folders like 'folder/job-name')"
    )
    build_number: int = Field(description="Build number to analyze")
    callback_url: HttpUrl | None = Field(
        default=None,
        description="Optional callback URL for async results (overrides env var default)",
    )
    callback_headers: dict[str, str] | None = Field(
        default=None,
        description="Optional headers to include in callback request (overrides env var default)",
    )
    html_report: bool | None = Field(
        default=None,
        description="Generate HTML report (default: true, overrides HTML_REPORT env var)",
    )


class TestFailure(BaseModel):
    """A single test failure extracted from Jenkins test report."""

    test_name: str = Field(
        description="Fully qualified test name (className.methodName)"
    )
    error_message: str = Field(default="", description="Error details/message")
    stack_trace: str = Field(default="", description="Full stack trace if available")
    duration: float = Field(default=0.0, description="Test duration in seconds")
    status: str = Field(
        default="FAILED", description="Test status (FAILED, REGRESSION, etc.)"
    )


class JiraMatch(BaseModel):
    """A Jira issue that potentially matches a product bug."""

    key: str = Field(description="Jira issue key (e.g., PROJ-123)")
    summary: str = Field(description="Issue summary/title")
    status: str = Field(
        default="", description="Issue status (e.g., Open, In Progress)"
    )
    priority: str = Field(default="", description="Issue priority (e.g., High, Medium)")
    url: str = Field(default="", description="Full URL to the Jira issue")
    score: float = Field(default=0.0, description="Relevance score (0.0-1.0)")


class ProductBugReport(BaseModel):
    """Structured product bug report from AI analysis."""

    title: str = Field(default="", description="Concise bug title")
    severity: str = Field(
        default="", description="Bug severity: critical/high/medium/low"
    )
    component: str = Field(default="", description="Affected component")
    description: str = Field(default="", description="What product behavior is broken")
    evidence: str = Field(default="", description="Relevant log snippets")
    jira_search_keywords: list[str] = Field(
        default_factory=list, description="AI-suggested keywords for Jira search"
    )
    jira_matches: list[JiraMatch] = Field(
        default_factory=list,
        description="Matched Jira issues (populated in post-processing)",
    )


class CodeFix(BaseModel):
    """Structured code fix suggestion from AI analysis."""

    file: str = Field(default="", description="File path to fix")
    line: str = Field(default="", description="Line number")
    change: str = Field(default="", description="Specific code change")


class AnalysisDetail(BaseModel):
    """Structured AI analysis broken into sections."""

    classification: str = Field(default="", description="CODE ISSUE or PRODUCT BUG")
    affected_tests: list[str] = Field(
        default_factory=list, description="List of affected test names"
    )
    details: str = Field(default="", description="Detailed analysis text")
    code_fix: CodeFix | bool | None = Field(
        default=False, description="Code fix (if CODE ISSUE)"
    )
    product_bug_report: ProductBugReport | bool | None = Field(
        default=False, description="Bug report (if PRODUCT BUG)"
    )

    @model_validator(mode="after")
    def check_mutual_exclusivity(self) -> "AnalysisDetail":
        if self.code_fix and self.product_bug_report:
            raise ValueError("code_fix and product_bug_report are mutually exclusive")
        return self

    @model_serializer(mode="wrap")
    def _exclude_falsy_optionals(self, handler):
        d = handler(self)
        if not d.get("code_fix"):
            d.pop("code_fix", None)
        if not d.get("product_bug_report"):
            d.pop("product_bug_report", None)
        return d


class FailureAnalysis(BaseModel):
    """Analysis result for a single test failure."""

    test_name: str = Field(description="Name of the failed test")
    error: str = Field(description="Error message or exception")
    analysis: AnalysisDetail = Field(description="Structured AI analysis output")


class ChildJobAnalysis(BaseModel):
    """Analysis result for a failed child job in a pipeline."""

    job_name: str = Field(description="Name of the child job")
    build_number: int = Field(description="Build number of the child job")
    jenkins_url: str | None = Field(
        default=None, description="URL of the child job build"
    )
    summary: str | None = Field(
        default=None, description="Summary of the child job failure analysis"
    )
    failures: list["FailureAnalysis"] = Field(
        default_factory=list, description="List of analyzed failures in child job"
    )
    failed_children: list["ChildJobAnalysis"] = Field(
        default_factory=list, description="Nested failed child jobs"
    )
    note: str | None = Field(
        default=None, description="Additional notes (e.g., max depth reached)"
    )


class AnalysisResult(BaseModel):
    """Complete analysis result for a Jenkins job."""

    job_id: str = Field(description="Unique identifier for the analysis job")
    job_name: str = Field(default="", description="Jenkins job name")
    build_number: int = Field(default=0, description="Jenkins build number")
    jenkins_url: HttpUrl = Field(description="URL of the analyzed Jenkins job")
    status: Literal["pending", "running", "completed", "failed"] = Field(
        description="Current status of the analysis"
    )
    summary: str = Field(description="Summary of the analysis findings")
    ai_provider: str = Field(default="", description="AI provider used for analysis")
    ai_model: str = Field(default="", description="AI model used for analysis")
    failures: list[FailureAnalysis] = Field(
        default_factory=list, description="List of analyzed failures"
    )
    child_job_analyses: list[ChildJobAnalysis] = Field(
        default_factory=list,
        description="Analyses of failed child jobs in pipeline",
    )


class JobStatus(BaseModel):
    """Status information for a queued analysis job."""

    job_id: str = Field(description="Unique identifier for the analysis job")
    status: Literal["pending", "running", "completed", "failed"] = Field(
        description="Current status of the analysis"
    )
    created_at: datetime = Field(description="Timestamp when the job was created")


class AnalyzeFailuresRequest(BaseAnalysisRequest):
    """Request payload for direct failure analysis (no Jenkins)."""

    failures: list[TestFailure] = Field(description="Raw test failures to analyze")


class FailureAnalysisResult(BaseModel):
    """Analysis result for direct failure analysis (no Jenkins context)."""

    job_id: str = Field(description="Unique identifier for the analysis job")
    status: Literal["completed", "failed"] = Field(description="Analysis status")
    summary: str = Field(description="Summary of the analysis findings")
    ai_provider: str = Field(default="", description="AI provider used")
    ai_model: str = Field(default="", description="AI model used")
    failures: list[FailureAnalysis] = Field(
        default_factory=list, description="Analyzed failures"
    )
