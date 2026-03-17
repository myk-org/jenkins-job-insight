"""Pydantic request and response models."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    Field,
    HttpUrl,
    field_validator,
    model_serializer,
    model_validator,
)


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
    ai_cli_timeout: Annotated[int, Field(gt=0)] | None = Field(
        default=None,
        description="AI CLI timeout in minutes (overrides AI_CLI_TIMEOUT env var)",
    )
    jira_url: str | None = Field(
        default=None,
        description="Jira instance URL (overrides JIRA_URL env var)",
    )
    jira_email: str | None = Field(
        default=None,
        description="Jira Cloud email (overrides JIRA_EMAIL env var)",
    )
    jira_api_token: str | None = Field(
        default=None,
        description="Jira Cloud API token (overrides JIRA_API_TOKEN env var)",
        json_schema_extra={"format": "password"},
    )
    jira_pat: str | None = Field(
        default=None,
        description="Jira Server/DC personal access token (overrides JIRA_PAT env var)",
        json_schema_extra={"format": "password"},
    )
    jira_project_key: str | None = Field(
        default=None,
        description="Jira project key to scope searches (overrides JIRA_PROJECT_KEY env var)",
    )
    jira_ssl_verify: bool | None = Field(
        default=None,
        description="Jira SSL verification (overrides JIRA_SSL_VERIFY env var)",
    )
    jira_max_results: Annotated[int, Field(gt=0)] | None = Field(
        default=None,
        description="Max Jira search results (overrides JIRA_MAX_RESULTS env var)",
    )
    raw_prompt: str | None = Field(
        default=None,
        description="Raw prompt to append as additional AI instructions (overrides repo-level JOB_INSIGHT_PROMPT.md)",
    )
    github_token: str | None = Field(
        default=None,
        description="GitHub API token for private repo PR status in comments (overrides GITHUB_TOKEN env var)",
        json_schema_extra={"format": "password"},
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
    jenkins_url: str | None = Field(
        default=None,
        description="Jenkins server URL (overrides JENKINS_URL env var)",
    )
    jenkins_user: str | None = Field(
        default=None,
        description="Jenkins username (overrides JENKINS_USER env var)",
    )
    jenkins_password: str | None = Field(
        default=None,
        description="Jenkins password or API token (overrides JENKINS_PASSWORD env var)",
        json_schema_extra={"format": "password"},
    )
    jenkins_ssl_verify: bool | None = Field(
        default=None,
        description="Jenkins SSL verification (overrides JENKINS_SSL_VERIFY env var)",
    )
    jenkins_artifacts_max_size_mb: Annotated[int, Field(gt=0)] | None = Field(
        default=None,
        description="Maximum Jenkins artifacts size in MB (overrides JENKINS_ARTIFACTS_MAX_SIZE_MB env var)",
    )
    jenkins_artifacts_context_lines: Annotated[int, Field(gt=0)] | None = Field(
        default=None,
        description="Maximum Jenkins artifacts context lines for AI prompt (overrides JENKINS_ARTIFACTS_CONTEXT_LINES env var)",
    )
    get_job_artifacts: bool | None = Field(
        default=None,
        description="Download all build artifacts for AI context (default: true, overrides GET_JOB_ARTIFACTS env var)",
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
    artifacts_evidence: str = Field(
        default="",
        description="Verbatim log lines from build artifacts supporting the analysis (not a summary)",
    )
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
    error_signature: str = Field(
        default="",
        description="SHA-256 hash of error + stack trace for deduplication",
    )

    @field_validator("analysis", mode="before")
    @classmethod
    def _coerce_legacy_analysis(cls, v: object) -> object:
        """Accept legacy string format for backward compatibility.

        Data stored before the AnalysisDetail model was introduced has the
        analysis field as a plain string.  Wrap it in a dict so Pydantic can
        construct an AnalysisDetail with the text in the ``details`` field.
        """
        if isinstance(v, str):
            return {"details": v}
        return v


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
    jenkins_url: HttpUrl | None = Field(
        default=None,
        description="URL of the analyzed Jenkins job (None for non-Jenkins analysis)",
    )
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

    failures: list[TestFailure] | None = Field(
        default=None, description="Raw test failures to analyze"
    )
    raw_xml: Annotated[str, Field(max_length=50_000_000)] | None = Field(
        default=None,
        description="Raw JUnit XML content to extract failures from and enrich with analysis results",
    )

    @model_validator(mode="after")
    def check_input_source(self) -> "AnalyzeFailuresRequest":
        if self.failures and self.raw_xml:
            raise ValueError("Provide either 'failures' or 'raw_xml', not both")
        if not self.failures and not self.raw_xml:
            raise ValueError("Either 'failures' or 'raw_xml' must be provided")
        return self


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
    enriched_xml: str | None = Field(
        default=None,
        description="Enriched JUnit XML with analysis results (only when raw_xml was provided in request)",
    )


class _ChildJobFieldsValidator(BaseModel):
    """Mixin providing child_job_name + child_build_number cross-validation."""

    child_job_name: str = ""
    child_build_number: int = 0

    @model_validator(mode="after")
    def validate_child_fields(self):
        if self.child_job_name and self.child_build_number <= 0:
            raise ValueError(
                "child_build_number must be positive when child_job_name is set"
            )
        if not self.child_job_name and self.child_build_number > 0:
            raise ValueError(
                "child_job_name is required when child_build_number is set"
            )
        return self


class AddCommentRequest(_ChildJobFieldsValidator):
    """Request body for adding a comment to a test failure."""

    test_name: str
    comment: str
    # NOTE: error_signature is NOT sent by the browser.
    # It is read server-side from the pre-computed FailureAnalysis.error_signature
    # stored in the result data (computed during analysis when stack traces are available).


class SetReviewedRequest(_ChildJobFieldsValidator):
    """Request body for toggling the reviewed state of a test failure."""

    test_name: str
    reviewed: bool


class CommentResponse(BaseModel):
    """A single comment entry."""

    id: int
    job_id: str
    test_name: str
    child_job_name: str = ""
    child_build_number: int = 0
    comment: str
    username: str = ""
    created_at: str


class ReviewState(BaseModel):
    """Reviewed state for a single failure."""

    reviewed: bool
    updated_at: str


class CommentsAndReviewsResponse(BaseModel):
    """Combined response for all comments and review states for a job."""

    comments: list[CommentResponse]
    reviews: dict[str, ReviewState]


class ReviewStatusResponse(BaseModel):
    """Lightweight review summary for dashboard cards."""

    total_failures: int
    reviewed_count: int
    comment_count: int
