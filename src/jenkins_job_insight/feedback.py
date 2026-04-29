"""User feedback endpoint: AI-formatted GitHub issue creation.

Accepts user feedback (bug report or feature request), uses AI to
format it into a well-structured GitHub issue, scrubs sensitive data
from attached logs, and creates the issue in myk-org/jenkins-job-insight.
"""

import json
import os
import re

from simple_logger.logger import get_logger

from ai_cli_runner import call_ai_cli
from jenkins_job_insight.analyzer import PROVIDER_CLI_FLAGS
from jenkins_job_insight.bug_creation import create_github_issue
from jenkins_job_insight.config import Settings
from jenkins_job_insight.models import (
    FeedbackPreviewResponse,
    FeedbackRequest,
    FeedbackResponse,
)

logger = get_logger(name=__name__, level=os.environ.get("LOG_LEVEL", "INFO"))

_FEEDBACK_REPO_URL = "https://github.com/myk-org/jenkins-job-insight"

# Patterns for sensitive data scrubbing.
# Order matters: more specific patterns first to avoid partial matches.
_SENSITIVE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # JWT tokens (three dot-separated base64 segments)
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
        "[REDACTED_JWT]",
    ),
    # Basic auth headers (Base64-encoded credentials)
    (re.compile(r"(Basic\s+)[A-Za-z0-9+/=]{8,}", re.IGNORECASE), r"\1[REDACTED]"),
    # Bearer tokens
    (re.compile(r"(Bearer\s+)\S+", re.IGNORECASE), r"\1[REDACTED]"),
    # Authorization header values (generic)
    (
        re.compile(r"(Authorization[\"']?\s*[:=]\s*[\"']?)\S+", re.IGNORECASE),
        r"\1[REDACTED]",
    ),
    # API keys/tokens in query params or assignments
    (
        re.compile(
            r"((?:api_key|apikey|api_token|access_token|token|secret|auth_token)[\"']?\s*[:=]\s*[\"']?)\S+",
            re.IGNORECASE,
        ),
        r"\1[REDACTED]",
    ),
    # Passwords in query params or assignments
    (
        re.compile(
            r"((?:password|passwd|pwd)[\"']?\s*[:=]\s*[\"']?)\S+", re.IGNORECASE
        ),
        r"\1[REDACTED]",
    ),
    # GitHub tokens (ghp_, gho_, ghs_, ghr_, github_pat_)
    (
        re.compile(r"\b(?:ghp_|gho_|ghs_|ghr_|github_pat_)[A-Za-z0-9_]+\b"),
        "[REDACTED_GITHUB_TOKEN]",
    ),
    # Generic long hex/base64 secrets (40+ chars, likely tokens)
    (re.compile(r"\b[A-Fa-f0-9]{40,}\b"), "[REDACTED_HEX_TOKEN]"),
]


def scrub_sensitive_data(text: str) -> str:
    """Remove sensitive patterns from text.

    Scrubs API tokens/keys, passwords, JWT tokens, Basic/Bearer auth
    headers, and similar credential patterns. Preserves URLs, test
    names, and other non-sensitive content.
    """
    result = text
    for pattern, replacement in _SENSITIVE_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


async def format_feedback_with_ai(
    request: FeedbackRequest, settings: Settings
) -> tuple[str, str]:
    """Format user feedback into a GitHub issue title and body using AI.

    Returns:
        Tuple of (title, body) for the GitHub issue.
    """
    ai_provider = os.getenv("AI_PROVIDER", "").lower()
    ai_model = os.getenv("AI_MODEL", "")
    ai_cli_timeout = settings.ai_cli_timeout

    context_parts: list[str] = []
    if request.feedback_type == "bug":
        context_parts.append("Feedback type: Bug Report")
        context_parts.append(
            f"Description: {scrub_sensitive_data(request.description)}"
        )
        if request.console_errors:
            scrubbed_errors = [scrub_sensitive_data(e) for e in request.console_errors]
            context_parts.append(
                "Console errors:\n" + "\n".join(f"- {e}" for e in scrubbed_errors)
            )
        if request.failed_api_calls:
            scrubbed_calls = [
                {
                    "status": call.status,
                    "endpoint": scrub_sensitive_data(call.endpoint),
                    "error": scrub_sensitive_data(call.error),
                }
                for call in request.failed_api_calls
            ]
            context_parts.append(
                f"Failed API calls:\n{json.dumps(scrubbed_calls, indent=2)}"
            )
        if (
            request.page_state.url
            or request.page_state.active_filters
            or request.page_state.report_id
        ):
            scrubbed_state = {
                "url": scrub_sensitive_data(request.page_state.url),
                "active_filters": scrub_sensitive_data(
                    request.page_state.active_filters
                ),
                "report_id": scrub_sensitive_data(request.page_state.report_id),
            }
            context_parts.append(f"Page state:\n{json.dumps(scrubbed_state, indent=2)}")
        if request.user_agent:
            context_parts.append(f"User agent: {request.user_agent}")
    else:
        context_parts.append("Feedback type: Feature Request")
        context_parts.append(
            f"Description: {scrub_sensitive_data(request.description)}"
        )

    context = "\n\n".join(context_parts)

    if request.feedback_type == "bug":
        prompt = f"""You are formatting a user-submitted bug report into a well-structured GitHub issue
for the jenkins-job-insight project (https://github.com/myk-org/jenkins-job-insight).

User's feedback:
{context}

Create a GitHub issue with:
1. A concise, descriptive title (max 120 chars)
2. A well-formatted markdown body with appropriate sections

Respond ONLY with valid JSON (no markdown fences) in this exact format:
{{"title": "...", "body": "..."}}

The body should include:
- **Description**: Clear summary of the bug
- **Steps to Reproduce**: Inferred from the context
- **Console Errors**: If any were provided (already scrubbed of sensitive data)
- **Failed API Calls**: If any were provided
- **Environment**: Browser/user agent info if available
- **Page State**: Current page context if available

Do NOT include any sensitive data (tokens, passwords, etc.) in the output."""
    else:
        prompt = f"""You are formatting a user-submitted feature request into a well-structured GitHub issue
for the jenkins-job-insight project (https://github.com/myk-org/jenkins-job-insight).

User's feedback:
{context}

Create a GitHub issue with:
1. A concise, descriptive title (max 120 chars)
2. A well-formatted markdown body

Respond ONLY with valid JSON (no markdown fences) in this exact format:
{{"title": "...", "body": "..."}}

The body should include:
- **Description**: Clear summary of the feature request
- **Use Case**: Why this feature would be useful
- **Proposed Solution**: If the user suggested one

Do NOT include any sensitive data in the output."""

    result = await call_ai_cli(
        prompt,
        ai_provider=ai_provider,
        ai_model=ai_model,
        ai_cli_timeout=ai_cli_timeout,
        cli_flags=PROVIDER_CLI_FLAGS.get(ai_provider, []),
        output_format="json",
    )

    if result.success:
        parsed = _parse_json_response(result.text)
        if parsed:
            return parsed["title"], parsed["body"]
        logger.debug(
            "AI response JSON parsing failed, using fallback. Output: %s", result.text
        )
    else:
        logger.debug("AI CLI call failed for feedback formatting: %s", result.text)

    logger.warning("AI formatting failed for feedback, using fallback template")
    return _build_fallback_feedback(request)


def _parse_json_response(text: str) -> dict | None:
    """Parse JSON from AI response, handling markdown code fences."""
    text = text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n", 1)
        if len(lines) > 1:
            text = lines[1]
        end = text.rfind("```")
        if end > 0:
            text = text[:end]
        text = text.strip()

    try:
        data = json.loads(text)
        if isinstance(data, dict) and "title" in data and "body" in data:
            return data
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def _build_fallback_feedback(request: FeedbackRequest) -> tuple[str, str]:
    """Build fallback title and body when AI formatting fails."""
    _FALLBACK_TITLE_MAX = 500  # matches FeedbackCreateRequest.title max_length
    if request.feedback_type == "bug":
        scrubbed_desc = scrub_sensitive_data(request.description)
        title = f"Bug report: {scrubbed_desc}"[:_FALLBACK_TITLE_MAX]
        parts = [
            "## Bug Report",
            "",
            f"**Description:** {scrubbed_desc}",
        ]
        if request.console_errors:
            parts.extend(["", "## Console Errors", "```"])
            parts.extend(scrub_sensitive_data(e) for e in request.console_errors)
            parts.append("```")
        if request.failed_api_calls:
            scrubbed_calls = [
                {
                    "status": call.status,
                    "endpoint": scrub_sensitive_data(call.endpoint),
                    "error": scrub_sensitive_data(call.error),
                }
                for call in request.failed_api_calls
            ]
            parts.extend(
                [
                    "",
                    "## Failed API Calls",
                    f"```json\n{json.dumps(scrubbed_calls, indent=2)}\n```",
                ]
            )
        if (
            request.page_state.url
            or request.page_state.active_filters
            or request.page_state.report_id
        ):
            scrubbed_state = {
                "url": scrub_sensitive_data(request.page_state.url),
                "active_filters": scrub_sensitive_data(
                    request.page_state.active_filters
                ),
                "report_id": scrub_sensitive_data(request.page_state.report_id),
            }
            parts.extend(
                [
                    "",
                    "## Page State",
                    f"```json\n{json.dumps(scrubbed_state, indent=2)}\n```",
                ]
            )
        if request.user_agent:
            parts.extend(["", f"**User Agent:** {request.user_agent}"])
        body = "\n".join(parts)
    else:
        scrubbed_desc = scrub_sensitive_data(request.description)
        title = f"Feature request: {scrubbed_desc}"[:_FALLBACK_TITLE_MAX]
        body = f"## Feature Request\n\n**Description:** {scrubbed_desc}"
    return title, body


async def generate_feedback_preview(
    request: FeedbackRequest, settings: Settings
) -> FeedbackPreviewResponse:
    """Generate an AI-formatted preview of a feedback GitHub issue.

    Calls AI to generate a well-structured title and body, scrubs
    sensitive data from attached logs, and returns the preview
    without creating the issue.

    Args:
        request: User feedback submission.
        settings: Application settings.

    Returns:
        FeedbackPreviewResponse with generated title, body, and labels.
    """
    title, body = await format_feedback_with_ai(request, settings)
    labels = ["bug"] if request.feedback_type == "bug" else ["enhancement"]
    return FeedbackPreviewResponse(title=title, body=body, labels=labels)


_ALLOWED_LABELS: set[str] = {"bug", "enhancement"}


async def create_feedback_from_preview(
    title: str, body: str, labels: list[str], settings: Settings
) -> FeedbackResponse:
    """Create a GitHub issue from a previously previewed feedback.

    Args:
        title: Issue title (from preview).
        body: Issue body (from preview).
        labels: Issue labels (from preview).
        settings: Application settings (must have github_token configured).

    Returns:
        FeedbackResponse with the created issue details.
    """
    title = scrub_sensitive_data(title)
    body = scrub_sensitive_data(body)
    labels = [lbl for lbl in labels if lbl in _ALLOWED_LABELS]

    github_token = (
        settings.github_token.get_secret_value() if settings.github_token else ""
    )

    result = await create_github_issue(
        title=title,
        body=body,
        repo_url=_FEEDBACK_REPO_URL,
        github_token=github_token,
        labels=labels,
    )

    return FeedbackResponse(
        issue_url=result["url"],
        issue_number=result["number"],
        title=result["title"],
    )


async def create_feedback_issue(
    request: FeedbackRequest, settings: Settings
) -> FeedbackResponse:
    """Orchestrate feedback submission: scrub, format with AI, create GitHub issue.

    .. deprecated::
        Use :func:`generate_feedback_preview` + :func:`create_feedback_from_preview`
        for the two-step preview/create flow.

    Args:
        request: User feedback submission.
        settings: Application settings (must have github_token configured).

    Returns:
        FeedbackResponse with the created issue details.
    """
    preview = await generate_feedback_preview(request, settings)
    return await create_feedback_from_preview(
        title=preview.title,
        body=preview.body,
        labels=preview.labels,
        settings=settings,
    )
