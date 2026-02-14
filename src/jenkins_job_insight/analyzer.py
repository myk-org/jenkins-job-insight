import asyncio
import contextlib
import hashlib
import json
import os
import re
import subprocess
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable
from typing import NoReturn

import jenkins
from fastapi import HTTPException
from simple_logger.logger import get_logger

from jenkins_job_insight.config import Settings
from jenkins_job_insight.jenkins import JenkinsClient
from pydantic import HttpUrl

from jenkins_job_insight.models import (
    AnalysisDetail,
    AnalysisResult,
    AnalyzeRequest,
    ChildJobAnalysis,
    CodeFix,
    FailureAnalysis,
    ProductBugReport,
    TestFailure,
)
from jenkins_job_insight.repository import RepositoryManager

logger = get_logger(name=__name__, level=os.environ.get("LOG_LEVEL", "INFO"))


def _get_ai_cli_timeout() -> int:
    """Parse AI_CLI_TIMEOUT with fallback for invalid values."""
    raw = os.getenv("AI_CLI_TIMEOUT", "10")
    try:
        value = int(raw)
    except ValueError:
        logger.warning(f"Invalid AI_CLI_TIMEOUT={raw}; defaulting to 10")
        return 10
    if value <= 0:
        logger.warning(f"Non-positive AI_CLI_TIMEOUT={raw}; defaulting to 10")
        return 10
    return value


AI_CLI_TIMEOUT = _get_ai_cli_timeout()  # minutes

FALLBACK_TAIL_LINES = 200
MAX_CONCURRENT_AI_CALLS = 10

# Pre-compiled pattern for error detection with word boundaries
ERROR_PATTERN = re.compile(
    r"\b(error|fail(ed|ure)?|exception|traceback|assert(ion)?|warn(ing)?|critical|fatal)\b",
    re.IGNORECASE,
)

_JSON_RESPONSE_SCHEMA = """CRITICAL: Your response must be ONLY a valid JSON object. No text before or after. No markdown code blocks. No explanation.

If CODE ISSUE:
{
  "classification": "CODE ISSUE",
  "affected_tests": ["test_name_1", "test_name_2"],
  "details": "Your detailed analysis of what caused this failure",
  "code_fix": {
    "file": "exact/file/path.py",
    "line": "line number",
    "change": "specific code change that fixes all affected tests"
  }
}

If PRODUCT BUG:
{
  "classification": "PRODUCT BUG",
  "affected_tests": ["test_name_1", "test_name_2"],
  "details": "Your detailed analysis of what caused this failure",
  "product_bug_report": {
    "title": "concise bug title",
    "severity": "critical/high/medium/low",
    "component": "affected component",
    "description": "what product behavior is broken",
    "evidence": "relevant log snippets",
    "jira_search_keywords": ["specific error symptom", "component + behavior", "error type"]
  }
}

jira_search_keywords rules:
- Generate 3-5 SHORT specific keywords for finding matching bugs in Jira
- Focus on the specific error symptom and broken behavior, NOT test infrastructure
- Combine component name with the specific failure (e.g. "VM start failure migration", "API timeout authentication")
- AVOID generic/broad terms alone like "vSphere", "OpenShift", "timeout", "failure", "error"
- Each keyword should be specific enough to narrow Jira search results to relevant bugs
- Think: "what would someone title a Jira bug for this exact issue?\""""


@dataclass(frozen=True)
class ProviderConfig:
    """Configuration for an AI CLI provider."""

    binary: str
    build_cmd: Callable[[str, str, Path | None], list[str]]
    uses_own_cwd: bool = False


def _build_claude_cmd(binary: str, model: str, _cwd: Path | None) -> list[str]:
    return [binary, "--model", model, "--dangerously-skip-permissions", "-p"]


def _build_gemini_cmd(binary: str, model: str, _cwd: Path | None) -> list[str]:
    return [binary, "--model", model, "--yolo"]


def _build_cursor_cmd(binary: str, model: str, cwd: Path | None) -> list[str]:
    cmd = [binary, "--force", "--model", model, "--print"]
    if cwd:
        cmd.extend(["--workspace", str(cwd)])
    return cmd


PROVIDER_CONFIG: dict[str, ProviderConfig] = {
    "claude": ProviderConfig(binary="claude", build_cmd=_build_claude_cmd),
    "gemini": ProviderConfig(binary="gemini", build_cmd=_build_gemini_cmd),
    "cursor": ProviderConfig(
        binary="agent", uses_own_cwd=True, build_cmd=_build_cursor_cmd
    ),
}

VALID_AI_PROVIDERS = set(PROVIDER_CONFIG.keys())


def get_failure_signature(failure: TestFailure) -> str:
    """Create a signature for grouping identical failures.

    Uses error message and first few lines of stack trace to identify
    failures that are essentially the same issue.

    Args:
        failure: The test failure to create a signature for.

    Returns:
        SHA-256 hash string representing the failure signature.
    """
    # Use error message and first 5 lines of stack trace
    stack_lines = failure.stack_trace.split("\n")[:5]
    signature_text = f"{failure.error_message}|{'|'.join(stack_lines)}"
    return hashlib.sha256(signature_text.encode()).hexdigest()


async def run_parallel_with_limit(
    coroutines: list,
    max_concurrency: int = MAX_CONCURRENT_AI_CALLS,
) -> list:
    """Run coroutines in parallel with bounded concurrency.

    Args:
        coroutines: List of coroutines to execute.
        max_concurrency: Maximum concurrent executions.

    Returns:
        List of results (including exceptions if any failed).
    """
    semaphore = asyncio.Semaphore(max_concurrency)

    async def bounded(coro):
        async with semaphore:
            return await coro

    return await asyncio.gather(
        *[bounded(c) for c in coroutines],
        return_exceptions=True,
    )


def _parse_json_response(raw_text: str) -> AnalysisDetail:
    """Parse AI CLI JSON response into an AnalysisDetail.

    Attempts to extract a JSON object from the AI response text.
    The AI may wrap the JSON in markdown code blocks, add
    surrounding text, or embed code blocks inside JSON string values.

    Uses a multi-strategy approach:
    1. Try parsing the raw text directly as JSON
    2. Try extracting JSON from brace-matching ({...})
    3. Try extracting from markdown code blocks
    4. Fallback: store raw text in details, then attempt recovery

    Args:
        raw_text: The raw text output from the AI CLI.

    Returns:
        An AnalysisDetail instance parsed from the JSON, or a
        fallback instance with the raw text stored in details.
    """
    text = raw_text.strip()

    # Strategy 1: Try parsing the entire text as JSON directly
    if text.startswith("{"):
        try:
            data = json.loads(text)
            return AnalysisDetail(**data)
        except Exception:
            pass

    # Strategy 2: Find the outermost JSON object using brace matching
    result = _extract_json_by_braces(text)
    if result is not None:
        return result

    # Strategy 3: Try markdown code block extraction
    # Find ALL ```json or ``` blocks and try each one
    result = _extract_json_from_code_blocks(text)
    if result is not None:
        return result

    # Fallback: store raw text in details, then attempt recovery
    fallback = AnalysisDetail(details=raw_text)
    return _recover_from_details(fallback)


def _recover_from_details(result: AnalysisDetail) -> AnalysisDetail:
    """Attempt to recover structured fields from a fallback result.

    When the main parsing strategies fail and raw text is stored in
    the details field, this function checks if that text contains
    JSON field patterns and extracts them via regex.

    This handles cases where the AI returned JSON with formatting
    issues (unescaped newlines, embedded code blocks) that broke
    standard JSON parsing.

    Args:
        result: An AnalysisDetail with raw text in the details field.

    Returns:
        Either a recovered AnalysisDetail with populated fields,
        or the original fallback result unchanged.
    """
    if result.classification:
        return result

    details = result.details
    if not details or '"classification"' not in details:
        return result

    # Extract classification
    class_match = re.search(r'"classification"\s*:\s*"([^"]+)"', details)
    if not class_match:
        return result

    classification = class_match.group(1)

    # Extract affected_tests
    affected_tests: list[str] = []
    tests_match = re.search(r'"affected_tests"\s*:\s*\[([^\]]*)\]', details)
    if tests_match:
        affected_tests = re.findall(r'"([^"]+)"', tests_match.group(1))

    # Extract details text from within the JSON
    details_match = re.search(
        r'"details"\s*:\s*"((?:[^"\\]|\\.)*)"', details, re.DOTALL
    )
    analysis_text = (
        details_match.group(1).replace("\\n", "\n") if details_match else details
    )

    # Extract code_fix if present
    code_fix: CodeFix | bool | None = False
    file_match = re.search(r'"file"\s*:\s*"([^"]*)"', details)
    change_match = re.search(r'"change"\s*:\s*"((?:[^"\\]|\\.)*)"', details)
    if file_match and change_match:
        line_match = re.search(r'"line"\s*:\s*"([^"]*)"', details)
        code_fix = CodeFix(
            file=file_match.group(1),
            line=line_match.group(1) if line_match else "",
            change=change_match.group(1).replace("\\n", "\n"),
        )

    # Extract product_bug_report if present
    product_bug_report: ProductBugReport | bool | None = False
    title_match = re.search(r'"title"\s*:\s*"((?:[^"\\]|\\.)*)"', details)
    if title_match and "PRODUCT BUG" in classification.upper():
        severity_match = re.search(r'"severity"\s*:\s*"([^"]*)"', details)
        component_match = re.search(r'"component"\s*:\s*"([^"]*)"', details)
        desc_match = re.search(
            r'"description"\s*:\s*"((?:[^"\\]|\\.)*)"', details, re.DOTALL
        )
        evidence_match = re.search(
            r'"evidence"\s*:\s*"((?:[^"\\]|\\.)*)"', details, re.DOTALL
        )
        keywords_match = re.search(
            r'"jira_search_keywords"\s*:\s*\[([^\]]*)\]', details
        )
        jira_keywords = (
            re.findall(r'"([^"]+)"', keywords_match.group(1)) if keywords_match else []
        )

        product_bug_report = ProductBugReport(
            title=title_match.group(1),
            severity=severity_match.group(1) if severity_match else "",
            component=component_match.group(1) if component_match else "",
            description=(
                desc_match.group(1).replace("\\n", "\n") if desc_match else ""
            ),
            evidence=(
                evidence_match.group(1).replace("\\n", "\n") if evidence_match else ""
            ),
            jira_search_keywords=jira_keywords,
        )

    logger.warning(
        "Recovered classification '%s' from unparseable AI response via regex extraction",
        classification,
    )
    return AnalysisDetail(
        classification=classification,
        affected_tests=affected_tests,
        details=analysis_text,
        code_fix=code_fix,
        product_bug_report=product_bug_report,
    )


def _extract_json_by_braces(text: str) -> AnalysisDetail | None:
    """Extract JSON by finding matching outermost braces.

    Handles cases where JSON values contain embedded code blocks
    or other special characters by tracking brace nesting depth
    and string boundaries.

    Args:
        text: Text potentially containing a JSON object.

    Returns:
        Parsed AnalysisDetail or None if extraction fails.
    """
    first_brace = text.find("{")
    if first_brace == -1:
        return None

    # Track brace depth to find the matching closing brace
    depth = 0
    in_string = False
    escape_next = False
    end_pos = -1

    for i in range(first_brace, len(text)):
        char = text[i]

        if escape_next:
            escape_next = False
            continue

        if char == "\\":
            if in_string:
                escape_next = True
            continue

        if char == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end_pos = i
                break

    if end_pos == -1:
        return None

    json_str = text[first_brace : end_pos + 1]
    try:
        data = json.loads(json_str)
        return AnalysisDetail(**data)
    except Exception:
        return None


def _extract_json_from_code_blocks(text: str) -> AnalysisDetail | None:
    """Extract JSON from markdown code blocks in the text.

    Finds code blocks (```json or ```) and attempts to parse
    each one as JSON. Uses brace matching within each block
    to handle embedded code blocks in JSON string values.

    Args:
        text: Text containing markdown code blocks.

    Returns:
        Parsed AnalysisDetail or None if no valid JSON found.
    """
    # Find all code block positions using a pattern that matches
    # opening ``` markers (with optional language tag)
    blocks = re.findall(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)

    for block_content in blocks:
        block_content = block_content.strip()
        if not block_content or "{" not in block_content:
            continue

        # Try parsing the block content directly
        try:
            data = json.loads(block_content)
            return AnalysisDetail(**data)
        except Exception:
            pass

        # Try brace matching within the block
        result = _extract_json_by_braces(block_content)
        if result is not None:
            return result

    return None


async def check_ai_cli_available(ai_provider: str, ai_model: str) -> tuple[bool, str]:
    """Run a lightweight sanity check to verify the AI CLI is reachable.

    Sends a trivial prompt ("Hi") to the configured provider and returns
    whether the CLI responded successfully.  This should be called once
    before spawning parallel analysis tasks so that a misconfigured
    provider is caught early without wasting API credits.

    Args:
        ai_provider: AI provider name (e.g. "claude", "gemini").
        ai_model: AI model identifier to pass to the provider.

    Returns:
        Tuple of (ok, error_message).  ok is True when the CLI works;
        on failure ok is False and error_message describes the problem.
    """
    config = PROVIDER_CONFIG.get(ai_provider)
    if not config:
        return (
            False,
            f"Unknown AI provider: '{ai_provider}'. Valid providers: {', '.join(sorted(VALID_AI_PROVIDERS))}",
        )

    if not ai_model:
        return (
            False,
            "No AI model configured. Set AI_MODEL env var or pass ai_model in request body.",
        )

    provider_info = f"{ai_provider.upper()} ({ai_model})"
    sanity_cmd = config.build_cmd(config.binary, ai_model, None)

    try:
        sanity_result = await asyncio.to_thread(
            subprocess.run,
            sanity_cmd,
            cwd=None,
            capture_output=True,
            text=True,
            timeout=60,
            input="Hi",
        )
        if sanity_result.returncode != 0:
            error_detail = (
                sanity_result.stderr
                or sanity_result.stdout
                or "unknown error (no output)"
            )
            return False, f"{provider_info} sanity check failed: {error_detail}"
    except subprocess.TimeoutExpired:
        return False, f"{provider_info} sanity check timed out"

    return True, ""


async def call_ai_cli(
    prompt: str, cwd: Path | None = None, ai_provider: str = "", ai_model: str = ""
) -> tuple[bool, str]:
    """Call AI CLI (Claude, Gemini, or Cursor) with given prompt.

    Args:
        prompt: The prompt to send to the AI CLI.
        cwd: Working directory for AI to explore (typically repo path).
        ai_provider: AI provider to use.
        ai_model: AI model to use.

    Returns:
        Tuple of (success, output). success is True with AI output, False with error message.
    """
    config = PROVIDER_CONFIG.get(ai_provider)
    if not config:
        return (
            False,
            f"Unknown AI provider: '{ai_provider}'. Valid providers: {', '.join(sorted(VALID_AI_PROVIDERS))}",
        )

    if not ai_model:
        return (
            False,
            "No AI model configured. Set AI_MODEL env var or pass ai_model in request body.",
        )

    provider_info = f"{ai_provider.upper()} ({ai_model})"
    cmd = config.build_cmd(config.binary, ai_model, cwd)

    subprocess_cwd = None if config.uses_own_cwd else cwd

    logger.info("Calling %s CLI", provider_info)

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            cwd=subprocess_cwd,
            capture_output=True,
            text=True,
            timeout=AI_CLI_TIMEOUT * 60,  # Convert minutes to seconds
            input=prompt,
        )
    except subprocess.TimeoutExpired:
        return (
            False,
            f"{provider_info} CLI error: Analysis timed out after {AI_CLI_TIMEOUT} minutes",
        )

    if result.returncode != 0:
        error_detail = result.stderr or result.stdout or "unknown error (no output)"
        return False, f"{provider_info} CLI error: {error_detail}"

    logger.debug(f"{provider_info} CLI response length: {len(result.stdout)} chars")
    return True, result.stdout


def extract_relevant_console_lines(console_output: str) -> str:
    """Extract only error, failure, and warning lines from console output.

    When no structured test report is available, we need to extract
    relevant information from the console without sending the entire log.

    Args:
        console_output: Full Jenkins console output.

    Returns:
        Extracted relevant lines (errors, failures, warnings, exceptions).
    """
    relevant_lines: list[str] = []
    lines = console_output.splitlines()

    # Track lines we've already added to avoid duplicates
    seen_indices: set[int] = set()
    in_traceback = False

    for i, line in enumerate(lines):
        # Check if line matches error pattern (word boundaries, case-insensitive)
        if ERROR_PATTERN.search(line):
            # Add some context: 2 lines before
            start = max(0, i - 2)
            for j in range(start, i):
                if j not in seen_indices:
                    relevant_lines.append(lines[j])
                    seen_indices.add(j)
            # Add the error line itself (with duplicate check)
            if i not in seen_indices:
                relevant_lines.append(line)
                seen_indices.add(i)
            in_traceback = True
        elif in_traceback:
            # Continue capturing indented lines (stack trace)
            if line.startswith((" ", "\t")) or line.strip() == "":
                if i not in seen_indices:
                    relevant_lines.append(line)
                    seen_indices.add(i)
            else:
                in_traceback = False

    if relevant_lines:
        return "\n".join(relevant_lines)

    # Fallback: if nothing found, return last N lines (likely has the failure info)
    return (
        "\n".join(lines[-FALLBACK_TAIL_LINES:])
        if len(lines) > FALLBACK_TAIL_LINES
        else console_output
    )


def handle_jenkins_exception(
    e: Exception, job_name: str, build_number: int
) -> NoReturn:
    """Convert Jenkins exceptions to appropriate HTTPExceptions.

    Args:
        e: The exception raised by the Jenkins client.
        job_name: Name of the Jenkins job being accessed.
        build_number: Build number being accessed.

    Raises:
        HTTPException: With appropriate status code and detail message.
    """
    if isinstance(e, jenkins.NotFoundException):
        raise HTTPException(
            status_code=404,
            detail=f"Job '{job_name}' build #{build_number} not found in Jenkins",
        )

    if isinstance(e, jenkins.JenkinsException):
        error_msg = str(e).lower()
        if (
            "does not exist" in error_msg
            or "not found" in error_msg
            or "404" in error_msg
        ):
            raise HTTPException(
                status_code=404,
                detail=f"Job '{job_name}' build #{build_number} not found in Jenkins",
            )
        elif "unauthorized" in error_msg or "401" in error_msg:
            raise HTTPException(
                status_code=502,
                detail="Jenkins authentication failed. Check JENKINS_USER and JENKINS_PASSWORD.",
            )
        elif "forbidden" in error_msg or "403" in error_msg:
            raise HTTPException(
                status_code=502,
                detail=f"Access denied to job '{job_name}'. Check Jenkins permissions.",
            )
        else:
            raise HTTPException(
                status_code=502,
                detail=f"Jenkins error: {e!s}",
            )

    # For any other exception type
    raise HTTPException(
        status_code=502,
        detail=f"Failed to connect to Jenkins: {e!s}",
    )


def extract_failed_child_jobs(build_info: dict) -> list[tuple[str, int]]:
    """Extract failed child job names and build numbers from pipeline build info.

    Looks for failed jobs in subBuilds (Pipeline plugin) and triggeredBuilds
    (older Jenkins plugins).

    Args:
        build_info: Jenkins build information dictionary.

    Returns:
        List of (job_name, build_number) tuples for failed child jobs.
    """
    failed_jobs: list[tuple[str, int]] = []

    # Check for subBuilds in pipeline (Blue Ocean / Pipeline plugin)
    sub_builds = build_info.get("subBuilds", [])
    for sub in sub_builds:
        if sub.get("result") in ("FAILURE", "UNSTABLE"):
            job_name = sub.get("jobName", "")
            build_num = sub.get("buildNumber", 0)
            if job_name and build_num:
                failed_jobs.append((job_name, build_num))

    # Also check actions for triggered builds (older Jenkins plugins)
    for action in build_info.get("actions", []):
        if action is None:
            continue
        action_class = action.get("_class", "")
        triggered_builds = action.get("triggeredBuilds", [])

        # Check for BuildAction or similar action types
        if triggered_builds or "BuildAction" in action_class:
            for triggered in triggered_builds:
                if triggered.get("result") in ("FAILURE", "UNSTABLE"):
                    # Try to get job name from different possible fields
                    job_name = triggered.get("jobName", "")
                    if not job_name:
                        # Try to parse from URL if available
                        url = triggered.get("url", "")
                        if url:
                            try:
                                job_name, _ = JenkinsClient.parse_jenkins_url(url)
                            except ValueError:
                                continue
                    build_num = triggered.get("number", triggered.get("buildNumber", 0))
                    if job_name and build_num:
                        failed_jobs.append((job_name, build_num))

    return failed_jobs


def extract_failed_child_jobs_from_console(
    console_output: str,
) -> list[tuple[str, int]]:
    """Extract failed child jobs from console output using regex.

    Looks for patterns like:
    - Build folder » job-name #123 completed: FAILURE
    - Build job-name #123 completed: FAILURE

    Args:
        console_output: The Jenkins console output text.

    Returns:
        List of (job_name, build_number) tuples for failed child jobs.
    """
    failed_jobs: list[tuple[str, int]] = []

    # Pattern: Build [job path] #[number] completed: FAILURE/UNSTABLE
    pattern = r"Build\s+(.+?)\s+#(\d+)\s+completed:\s*(FAILURE|UNSTABLE)"
    matches = re.findall(pattern, console_output)

    for match in matches:
        job_path = match[0].strip()
        build_num = int(match[1])
        # Convert "folder » job" to "folder/job" format for Jenkins API
        # Example: "mtv-base » mtv-deploy-dynamic" -> "mtv-base/mtv-deploy-dynamic"
        # The URL construction will handle adding /job/ segments for display
        job_name = job_path.replace(" » ", "/")
        failed_jobs.append((job_name, build_num))

    return failed_jobs


def extract_failures_from_test_report(test_report: dict) -> list[TestFailure]:
    """Extract failed test cases from Jenkins test report.

    Parses the structured test report from Jenkins /testReport/api/json endpoint
    and extracts all failed and regression tests.

    Args:
        test_report: Jenkins test report dictionary from the API.

    Returns:
        List of TestFailure objects containing test details.
    """
    failures: list[TestFailure] = []

    # Handle both top-level suites and nested childReports structure
    suites = test_report.get("suites", [])

    # Some Jenkins configurations use childReports instead of suites at top level
    child_reports = test_report.get("childReports", [])
    for child_report in child_reports:
        result = child_report.get("result", {})
        suites.extend(result.get("suites", []))

    for suite in suites:
        for case in suite.get("cases", []):
            status = case.get("status", "")
            if status in ("FAILED", "REGRESSION"):
                class_name = case.get("className", "")
                test_name = case.get("name", "")
                full_name = f"{class_name}.{test_name}" if class_name else test_name

                failures.append(
                    TestFailure(
                        test_name=full_name,
                        error_message=case.get("errorDetails", "") or "",
                        stack_trace=case.get("errorStackTrace", "") or "",
                        duration=case.get("duration", 0.0) or 0.0,
                        status=status,
                    )
                )

    return failures


async def analyze_failure_group(
    failures: list[TestFailure],
    console_context: str,
    repo_path: Path | None,
    ai_provider: str = "",
    ai_model: str = "",
) -> list[FailureAnalysis]:
    """Analyze a group of failures with the same error signature.

    Only calls Claude CLI once for the group, then applies the analysis
    to all failures in the group.

    Args:
        failures: List of test failures with the same error signature.
        console_context: Relevant console lines for context.
        repo_path: Path to cloned test repo (optional).

    Returns:
        List of FailureAnalysis objects, one per failure in the group.
    """
    # Use the first failure as representative
    representative = failures[0]
    test_names = [f.test_name for f in failures]

    prompt = f"""Analyze this test failure from a Jenkins CI job.

AFFECTED TESTS ({len(failures)} tests with same error):
{chr(10).join(f"- {name}" for name in test_names)}

ERROR: {representative.error_message}
STACK TRACE:
{representative.stack_trace}

CONSOLE CONTEXT:
{console_context}

You have access to the test repository. Explore the code to understand the failure.

Note: Multiple tests failed with the same error. Provide ONE analysis that applies to all of them.

{_JSON_RESPONSE_SCHEMA}
"""

    logger.info(
        f"Calling {ai_provider.upper()} CLI for failure group ({len(failures)} tests with same error)"
    )
    success, analysis_output = await call_ai_cli(
        prompt, cwd=repo_path, ai_provider=ai_provider, ai_model=ai_model
    )

    # Parse the AI response into structured data
    if success:
        parsed = _parse_json_response(analysis_output)
    else:
        parsed = AnalysisDetail(details=analysis_output)

    # Apply the same analysis to all failures in the group
    return [
        FailureAnalysis(
            test_name=f.test_name,
            error=f.error_message,
            analysis=parsed,
        )
        for f in failures
    ]


async def analyze_child_job(
    job_name: str,
    build_number: int,
    jenkins_client: JenkinsClient,
    jenkins_base_url: str,
    depth: int = 0,
    max_depth: int = 3,
    repo_path: Path | None = None,
    ai_provider: str = "",
    ai_model: str = "",
) -> ChildJobAnalysis:
    """Analyze a single child job, recursively analyzing its failed children.

    Each child job gets its own Claude CLI call to manage context size.

    Args:
        job_name: Name of the Jenkins job to analyze.
        build_number: Build number to analyze.
        jenkins_client: Jenkins API client.
        jenkins_base_url: Base URL of Jenkins server.
        depth: Current recursion depth (0 = direct child of main job).
        max_depth: Maximum recursion depth to prevent infinite loops.
        repo_path: Path to cloned test repository for source code lookup.

    Returns:
        ChildJobAnalysis with analysis results or nested child analyses.
    """
    # Construct Jenkins URL for this child job
    job_path = "/job/".join(job_name.split("/"))
    jenkins_url = f"{jenkins_base_url.rstrip('/')}/job/{job_path}/{build_number}/"

    if depth >= max_depth:
        return ChildJobAnalysis(
            job_name=job_name,
            build_number=build_number,
            jenkins_url=jenkins_url,
            note="Max depth reached - analysis stopped to prevent infinite recursion",
        )

    # Get build info for this child
    try:
        build_info = await asyncio.to_thread(
            jenkins_client.get_build_info_safe, job_name, build_number
        )
    except Exception as e:
        return ChildJobAnalysis(
            job_name=job_name,
            build_number=build_number,
            jenkins_url=jenkins_url,
            note=f"Failed to get build info: {e}",
        )

    # Fetch console output first (needed for fallback child detection and analysis)
    try:
        console_output = await asyncio.to_thread(
            jenkins_client.get_build_console, job_name, build_number
        )
    except Exception as e:
        return ChildJobAnalysis(
            job_name=job_name,
            build_number=build_number,
            jenkins_url=jenkins_url,
            note=f"Failed to get console output: {e}",
        )

    # Check if this child also has failed children
    # Try to extract from build_info first
    failed_children = extract_failed_child_jobs(build_info)

    # Fallback to console parsing if none found from build_info
    if not failed_children:
        failed_children = extract_failed_child_jobs_from_console(console_output)

    if failed_children:
        # Recursively analyze failed children IN PARALLEL with bounded concurrency
        child_tasks = [
            analyze_child_job(
                child_name,
                child_num,
                jenkins_client,
                jenkins_base_url,
                depth + 1,
                max_depth,
                repo_path,
                ai_provider,
                ai_model,
            )
            for child_name, child_num in failed_children
        ]
        child_results = await run_parallel_with_limit(child_tasks)

        # Handle exceptions in results
        child_analyses = []
        for i, result in enumerate(child_results):
            if isinstance(result, Exception):
                child_name, child_num = failed_children[i]
                child_analyses.append(
                    ChildJobAnalysis(
                        job_name=child_name,
                        build_number=child_num,
                        jenkins_url="",
                        note=f"Analysis failed: {result}",
                    )
                )
            else:
                child_analyses.append(result)

        # This job failed because children failed - skip Claude CLI analysis
        # Count failures from child analyses
        total_failures = sum(len(child.failures) for child in child_analyses)
        summary = f"Pipeline failed due to {len(child_analyses)} child job(s)."
        if total_failures > 0:
            summary += f" Total: {total_failures} failure(s) analyzed. See child analyses below."

        return ChildJobAnalysis(
            job_name=job_name,
            build_number=build_number,
            jenkins_url=jenkins_url,
            summary=summary,
            failures=[],  # Pipeline has no direct failures
            failed_children=child_analyses,
        )

    # No failed children - this is a leaf failure, analyze it directly

    # Try to get structured test report first (much cleaner than parsing console output)
    test_report = await asyncio.to_thread(
        jenkins_client.get_test_report, job_name, build_number
    )

    test_failures = (
        extract_failures_from_test_report(test_report) if test_report else []
    )

    # Extract relevant console lines for context
    console_context = extract_relevant_console_lines(console_output)

    # If we have test failures, group by signature and analyze unique groups
    if test_failures:
        # Group failures by signature to avoid analyzing identical errors multiple times
        failure_groups: dict[str, list[TestFailure]] = defaultdict(list)
        for tf in test_failures:
            sig = get_failure_signature(tf)
            failure_groups[sig].append(tf)

        logger.info(
            f"Grouped {len(test_failures)} failures into {len(failure_groups)} unique error types"
        )

        # Analyze each unique failure group in parallel
        tasks = [
            analyze_failure_group(
                failures=group,
                console_context=console_context,
                repo_path=repo_path,
                ai_provider=ai_provider,
                ai_model=ai_model,
            )
            for group in failure_groups.values()
        ]
        group_results = await run_parallel_with_limit(tasks)

        # Flatten results and handle exceptions
        failures = []
        group_list = list(failure_groups.values())
        for i, result in enumerate(group_results):
            if isinstance(result, Exception):
                # Create error entries for all failures in this group
                for tf in group_list[i]:
                    failures.append(
                        FailureAnalysis(
                            test_name=tf.test_name,
                            error=tf.error_message,
                            analysis=AnalysisDetail(
                                details=f"Analysis failed: {result}"
                            ),
                        )
                    )
            else:
                failures.extend(result)

        # Generate summary from parallel results
        total_failures = len(failures)
        unique_errors = len(failure_groups)

        # Include deduplication info in summary if applicable
        if unique_errors < total_failures:
            summary = (
                f"{total_failures} failure(s) analyzed "
                f"({unique_errors} unique error type(s))"
            )
        else:
            summary = f"{total_failures} failure(s) analyzed"

        return ChildJobAnalysis(
            job_name=job_name,
            build_number=build_number,
            jenkins_url=jenkins_url,
            summary=summary,
            failures=failures,
        )

    # No structured test failures - fall back to single Claude CLI analysis of console output
    prompt = f"""Analyze this failed Jenkins job:

Job: {job_name} #{build_number}

CONSOLE OUTPUT (errors/failures/warnings extracted):
{console_context}

You have access to the repository if one was cloned. Explore to understand the failure.

{_JSON_RESPONSE_SCHEMA}
"""
    success, analysis_output = await call_ai_cli(
        prompt, cwd=repo_path, ai_provider=ai_provider, ai_model=ai_model
    )

    if success:
        parsed_analysis = _parse_json_response(analysis_output)
    else:
        parsed_analysis = AnalysisDetail(details=analysis_output)

    return ChildJobAnalysis(
        job_name=job_name,
        build_number=build_number,
        jenkins_url=jenkins_url,
        summary="Analysis complete",
        failures=[
            FailureAnalysis(
                test_name=f"{job_name}#{build_number}",
                error="Console-only analysis",
                analysis=parsed_analysis,
            )
        ],
    )


async def analyze_job(
    request: AnalyzeRequest,
    settings: Settings,
    ai_provider: str,
    ai_model: str,
    job_id: str | None = None,
) -> AnalysisResult:
    """Analyze a Jenkins job failure."""
    if job_id is None:
        job_id = str(uuid.uuid4())

    job_name = request.job_name
    build_number = request.build_number
    logger.info(f"Starting analysis for job {job_name} #{build_number}")
    # Get Jenkins data
    jenkins_client = JenkinsClient(
        url=settings.jenkins_url,
        username=settings.jenkins_user,
        password=settings.jenkins_password,
        ssl_verify=settings.jenkins_ssl_verify,
    )

    # Construct full Jenkins URL for the result
    # Handle folder-style job names by replacing '/' with '/job/'
    job_path = "/job/".join(job_name.split("/"))
    jenkins_build_url = (
        f"{settings.jenkins_url.rstrip('/')}/job/{job_path}/{build_number}/"
    )

    # First get build_info (quick call) to check if build passed
    build_info: dict = {}
    try:
        build_info = await asyncio.to_thread(
            jenkins_client.get_build_info_safe, job_name, build_number
        )
    except Exception as e:
        handle_jenkins_exception(e, job_name, build_number)

    # Check if build passed - return early if yes
    build_result = build_info.get("result")
    if build_result == "SUCCESS":
        return AnalysisResult(
            job_id=job_id,
            job_name=request.job_name,
            build_number=request.build_number,
            jenkins_url=HttpUrl(jenkins_build_url),
            status="completed",
            summary="Build passed successfully. No failures to analyze.",
            ai_provider=ai_provider,
            ai_model=ai_model,
            failures=[],
        )

    # Only fetch console output if build failed
    console_output: str = ""
    try:
        console_output = await asyncio.to_thread(
            jenkins_client.get_build_console, job_name, build_number
        )
    except Exception as e:
        handle_jenkins_exception(e, job_name, build_number)

    # Check for failed child jobs in pipeline
    # Try to extract from build_info first
    failed_child_jobs = extract_failed_child_jobs(build_info)

    # Fallback to console parsing if none found from build_info
    if not failed_child_jobs:
        failed_child_jobs = extract_failed_child_jobs_from_console(console_output)

    logger.debug(f"Extracted {len(failed_child_jobs)} failed child jobs")
    child_job_analyses: list[ChildJobAnalysis] = []

    # Clone repo for context BEFORE child job analysis so it's available for all jobs
    # Use request value if provided, otherwise fall back to settings
    tests_repo_url = request.tests_repo_url or settings.tests_repo_url
    repo_context = ""
    repo_path: Path | None = None

    # Use RepositoryManager context for entire analysis (child jobs and main job)
    async with contextlib.AsyncExitStack() as stack:
        if tests_repo_url:
            repo_manager = RepositoryManager()
            stack.enter_context(repo_manager)
            try:
                logger.info(f"Cloning repository: {tests_repo_url}")
                repo_path = await asyncio.to_thread(
                    repo_manager.clone, str(tests_repo_url)
                )
                repo_context = f"\nRepository cloned from: {tests_repo_url}"
            except Exception as e:
                logger.warning(f"Failed to clone repository: {e}")
                repo_context = f"\nFailed to clone repo: {e}"

        # Pre-flight: verify AI CLI is reachable before spawning parallel tasks
        ok, err = await check_ai_cli_available(ai_provider, ai_model)
        if not ok:
            return AnalysisResult(
                job_id=job_id,
                job_name=request.job_name,
                build_number=request.build_number,
                jenkins_url=HttpUrl(jenkins_build_url),
                status="failed",
                summary=err,
                ai_provider=ai_provider,
                ai_model=ai_model,
                failures=[],
            )

        # Analyze failed child jobs IN PARALLEL with bounded concurrency
        if failed_child_jobs:
            child_tasks = [
                analyze_child_job(
                    job_name=child_name,
                    build_number=child_num,
                    jenkins_client=jenkins_client,
                    jenkins_base_url=settings.jenkins_url,
                    depth=0,
                    max_depth=3,
                    repo_path=repo_path,
                    ai_provider=ai_provider,
                    ai_model=ai_model,
                )
                for child_name, child_num in failed_child_jobs
            ]
            child_results = await run_parallel_with_limit(child_tasks)

            # Handle exceptions in results
            for i, result in enumerate(child_results):
                if isinstance(result, Exception):
                    child_name, child_num = failed_child_jobs[i]
                    child_job_analyses.append(
                        ChildJobAnalysis(
                            job_name=child_name,
                            build_number=child_num,
                            jenkins_url="",
                            note=f"Analysis failed: {result}",
                        )
                    )
                else:
                    child_job_analyses.append(result)

        # Try to get structured test report first (much cleaner than parsing console output)
        test_report = await asyncio.to_thread(
            jenkins_client.get_test_report, job_name, build_number
        )

        test_failures = (
            extract_failures_from_test_report(test_report) if test_report else []
        )
        logger.info(f"Found {len(test_failures)} test failures to analyze")

        # If this job has failed children AND no test failures, it's a pipeline/orchestrator
        # Skip Claude CLI analysis - just return the child analyses
        if child_job_analyses and not test_failures:
            total_failures = sum(len(child.failures) for child in child_job_analyses)
            summary = f"Pipeline failed due to {len(child_job_analyses)} child job(s)."
            if total_failures > 0:
                summary += f" Total: {total_failures} failure(s) analyzed. See child analyses below."

            return AnalysisResult(
                job_id=job_id,
                job_name=request.job_name,
                build_number=request.build_number,
                jenkins_url=HttpUrl(jenkins_build_url),
                status="completed",
                summary=summary,
                ai_provider=ai_provider,
                ai_model=ai_model,
                failures=[],  # Pipeline has no direct failures
                child_job_analyses=child_job_analyses,
            )

        # Extract relevant console lines for context
        console_context = extract_relevant_console_lines(console_output)

        # Analyze main job test failures, grouping by signature to deduplicate
        unique_errors = 0
        if test_failures:
            # Group failures by signature to avoid analyzing identical errors multiple times
            failure_groups: dict[str, list[TestFailure]] = defaultdict(list)
            for tf in test_failures:
                sig = get_failure_signature(tf)
                failure_groups[sig].append(tf)

            unique_errors = len(failure_groups)
            logger.info(
                f"Grouped {len(test_failures)} failures into {unique_errors} unique error types"
            )

            # Analyze each unique failure group in parallel
            failure_tasks = [
                analyze_failure_group(
                    failures=group,
                    console_context=console_context,
                    repo_path=repo_path,
                    ai_provider=ai_provider,
                    ai_model=ai_model,
                )
                for group in failure_groups.values()
            ]
            group_results = await run_parallel_with_limit(failure_tasks)

            # Flatten results and handle exceptions
            failures = []
            group_list = list(failure_groups.values())
            for i, result in enumerate(group_results):
                if isinstance(result, Exception):
                    # Create error entries for all failures in this group
                    for tf in group_list[i]:
                        failures.append(
                            FailureAnalysis(
                                test_name=tf.test_name,
                                error=tf.error_message,
                                analysis=AnalysisDetail(
                                    details=f"Analysis failed: {result}"
                                ),
                            )
                        )
                else:
                    failures.extend(result)
        else:
            # No structured test failures - fall back to single Claude CLI analysis
            prompt = f"""Analyze this failed Jenkins job:

Job: {job_name} #{build_number}

CONSOLE OUTPUT (errors/failures/warnings extracted):
{console_context}
{repo_context}

You have access to the repository if one was cloned. Explore to understand the failure.

{_JSON_RESPONSE_SCHEMA}
"""
            success, analysis_output = await call_ai_cli(
                prompt, cwd=repo_path, ai_provider=ai_provider, ai_model=ai_model
            )

            if not success:
                return AnalysisResult(
                    job_id=job_id,
                    job_name=request.job_name,
                    build_number=request.build_number,
                    jenkins_url=HttpUrl(jenkins_build_url),
                    status="failed",
                    summary=analysis_output,
                    ai_provider=ai_provider,
                    ai_model=ai_model,
                    failures=[],
                    child_job_analyses=child_job_analyses,
                )

            failures = [
                FailureAnalysis(
                    test_name=f"{job_name}#{build_number}",
                    error="Console-only analysis",
                    analysis=_parse_json_response(analysis_output),
                )
            ]

        # Build summary from parallel results
        total_failures = len(failures)
        # Include deduplication info in summary if applicable
        if unique_errors > 0 and unique_errors < total_failures:
            summary = (
                f"{total_failures} failure(s) analyzed "
                f"({unique_errors} unique error type(s))"
            )
        else:
            summary = f"{total_failures} failure(s) analyzed"

        if child_job_analyses:
            summary = (
                f"{summary}. Additionally, {len(child_job_analyses)} failed child "
                f"job(s) were analyzed recursively."
            )

        logger.info(f"Analysis complete: {len(failures)} failures analyzed")
        return AnalysisResult(
            job_id=job_id,
            job_name=request.job_name,
            build_number=request.build_number,
            jenkins_url=HttpUrl(jenkins_build_url),
            status="completed",
            summary=summary,
            ai_provider=ai_provider,
            ai_model=ai_model,
            failures=failures,
            child_job_analyses=child_job_analyses,
        )
