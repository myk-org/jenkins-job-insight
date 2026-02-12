"""Pydantic request and response models."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class AnalyzeRequest(BaseModel):
    """Request payload for analysis endpoint."""

    job_name: str = Field(
        description="Jenkins job name (can include folders like 'folder/job-name')"
    )
    build_number: int = Field(description="Build number to analyze")
    tests_repo_url: HttpUrl | None = Field(
        default=None,
        description="URL of the tests repository (overrides env var default)",
    )
    callback_url: HttpUrl | None = Field(
        default=None,
        description="Optional callback URL for async results (overrides env var default)",
    )
    callback_headers: dict[str, str] | None = Field(
        default=None,
        description="Optional headers to include in callback request (overrides env var default)",
    )
    ai_provider: Literal["claude", "gemini", "cursor"] | None = Field(
        default=None,
        description="AI provider to use: claude, gemini, or cursor (overrides env var default)",
    )
    ai_model: str | None = Field(
        default=None,
        description="AI model to use (overrides env var default)",
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


class FailureAnalysis(BaseModel):
    """Analysis result for a single test failure."""

    test_name: str = Field(description="Name of the failed test")
    error: str = Field(description="Error message or exception")
    analysis: str = Field(
        description="Full Claude CLI analysis output (human readable)"
    )


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
    jenkins_url: HttpUrl = Field(description="URL of the analyzed Jenkins job")
    status: Literal["pending", "running", "completed", "failed"] = Field(
        description="Current status of the analysis"
    )
    summary: str = Field(description="Summary of the analysis findings")
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
