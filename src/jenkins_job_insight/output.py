"""Output delivery for callbacks and Slack notifications."""

import os

import httpx
from simple_logger.logger import get_logger

from collections import defaultdict

from jenkins_job_insight.models import AnalysisResult, ChildJobAnalysis, FailureAnalysis

logger = get_logger(name=__name__, level=os.environ.get("LOG_LEVEL", "INFO"))


def get_ai_provider_info() -> str:
    """Get the AI provider and model info for display.

    Returns:
        String like "Claude", "Gemini", "Cursor (claude-3.5-sonnet)", or "Qodo (gpt-5.2)"
    """
    provider = os.getenv("AI_PROVIDER", "claude").lower()

    # Get model info based on provider
    if provider == "qodo":
        model = os.getenv("QODO_MODEL", "")
        if model:
            return f"Qodo ({model})"
        return "Qodo"
    elif provider == "cursor":
        model = os.getenv("CURSOR_MODEL", "")
        if model:
            return f"Cursor ({model})"
        return "Cursor"
    elif provider == "gemini":
        return "Gemini"
    else:  # claude
        model = os.getenv("ANTHROPIC_MODEL", "")
        if model:
            return f"Claude ({model})"
        return "Claude"


async def send_callback(
    callback_url: str,
    result: AnalysisResult,
    headers: dict[str, str] | None = None,
) -> None:
    """Send analysis result to a callback webhook.

    Args:
        callback_url: URL to send the result to.
        result: Analysis result to deliver.
        headers: Optional headers to include in the request.
    """
    logger.info(f"Sending callback to {callback_url}")
    async with httpx.AsyncClient() as client:
        await client.post(
            callback_url,
            json=result.model_dump(mode="json"),
            headers=headers or {},
            timeout=30.0,
        )


def format_slack_message(result: AnalysisResult) -> dict:
    """Format analysis result as a Slack Block Kit message.

    Uses the same content as text output to ensure consistency.

    Args:
        result: Analysis result to format.

    Returns:
        Slack Block Kit message payload.
    """
    # Use the same text formatting as output=text
    text_content = format_result_as_text(result)

    # Split into chunks if needed (Slack has 3000 char limit per block)
    max_block_size = 2900  # Leave room for formatting

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Jenkins Analysis Complete"},
        },
    ]

    # Split text into chunks for Slack blocks
    chunks: list[str] = []
    current_chunk = ""
    for line in text_content.split("\n"):
        if len(current_chunk) + len(line) + 1 > max_block_size:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = line
        else:
            current_chunk = current_chunk + "\n" + line if current_chunk else line
    if current_chunk:
        chunks.append(current_chunk)

    # Add each chunk as a section block
    for chunk in chunks:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"```{chunk}```"},
            }
        )

    return {"blocks": blocks}


async def send_slack(webhook_url: str, result: AnalysisResult) -> None:
    """Send analysis result to a Slack incoming webhook.

    Args:
        webhook_url: Slack webhook URL.
        result: Analysis result to send.
    """
    logger.info("Sending Slack notification")
    message = format_slack_message(result)
    async with httpx.AsyncClient() as client:
        await client.post(webhook_url, json=message, timeout=30.0)


def format_child_analysis_as_text(
    child: ChildJobAnalysis, indent: int = 0
) -> list[str]:
    """Format child job analysis as text lines.

    Args:
        child: Child job analysis to format.
        indent: Indentation level for nested children.

    Returns:
        List of formatted text lines.
    """
    prefix = "  " * indent
    lines = [
        f"{prefix}Job: {child.job_name} #{child.build_number}",
    ]
    if child.jenkins_url:
        lines.append(f"{prefix}URL: {child.jenkins_url}")
    if child.note:
        lines.append(f"{prefix}Note: {child.note}")
    if child.summary:
        lines.append(f"{prefix}Summary: {child.summary}")

    # Group failures by analysis content to avoid duplicates
    if child.failures:
        analysis_groups: dict[str, list[FailureAnalysis]] = defaultdict(list)
        for f in child.failures:
            analysis_groups[f.analysis].append(f)

        for analysis_text, failures_in_group in analysis_groups.items():
            test_names = [f.test_name for f in failures_in_group]
            representative = failures_in_group[0]

            lines.append(
                f"{prefix}  ({len(failures_in_group)} test(s) with same error)"
            )

            # List affected tests
            if len(failures_in_group) > 1:
                lines.append(f"{prefix}  Affected tests:")
                for name in test_names:
                    lines.append(f"{prefix}    - {name}")
            else:
                lines.append(f"{prefix}  Test: {test_names[0]}")

            lines.append(f"{prefix}  Error: {representative.error}")
            lines.append(f"{prefix}  Analysis:")
            # Indent the analysis output
            for line in analysis_text.split("\n"):
                lines.append(f"{prefix}    {line}")
            lines.append("")

    for nested in child.failed_children:
        lines.extend(format_child_analysis_as_text(nested, indent + 1))
    return lines


def format_result_as_text(result: AnalysisResult) -> str:
    """Format analysis result as human-readable text.

    Args:
        result: Analysis result to format.

    Returns:
        Human-readable text representation.
    """
    lines = [
        "=" * 60,
        "JENKINS JOB ANALYSIS",
        "=" * 60,
        f"Job URL: {result.jenkins_url}",
        f"Status: {result.status}",
        f"Job ID: {result.job_id}",
        "",
        "SUMMARY:",
        result.summary,
        "",
    ]

    if result.failures:
        lines.append("=" * 60)
        lines.append("FAILURES:")
        lines.append("=" * 60)

        # Group failures by analysis content to avoid duplicates
        analysis_groups: dict[str, list[FailureAnalysis]] = defaultdict(list)
        for f in result.failures:
            analysis_groups[f.analysis].append(f)

        group_num = 0
        for analysis_text, failures_in_group in analysis_groups.items():
            group_num += 1
            test_names = [f.test_name for f in failures_in_group]
            representative = failures_in_group[0]

            lines.extend(
                [
                    "",
                    f"[{group_num}] ({len(failures_in_group)} test(s) with same error)",
                ]
            )

            # List affected tests
            if len(failures_in_group) > 1:
                lines.append("Affected tests:")
                for name in test_names:
                    lines.append(f"  - {name}")
            else:
                lines.append(f"Test: {test_names[0]}")

            lines.extend(
                [
                    f"Error: {representative.error}",
                    "",
                    "Analysis:",
                ]
            )
            # Add the full analysis output (already formatted by AI)
            lines.append(analysis_text)
            lines.append("-" * 40)

    if result.child_job_analyses:
        lines.append("")
        lines.append("=" * 60)
        lines.append("CHILD JOB ANALYSES:")
        lines.append("=" * 60)
        for child in result.child_job_analyses:
            lines.extend(format_child_analysis_as_text(child))

    # Add AI provider info at the end
    lines.append("")
    lines.append(f"Analyzed using {get_ai_provider_info()}")

    return "\n".join(lines)
