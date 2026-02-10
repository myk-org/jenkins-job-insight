"""Output delivery for callbacks and Slack notifications."""

import os
from typing import Literal

import httpx
from simple_logger.logger import get_logger

from collections import defaultdict

from jenkins_job_insight.models import (
    AnalysisResult,
    ChildJobAnalysis,
    FailureAnalysis,
    ResultMessage,
)

logger = get_logger(name=__name__, level=os.environ.get("LOG_LEVEL", "INFO"))

MAX_MESSAGE_TEXT = 2900


def get_ai_provider_info(ai_provider: str = "", ai_model: str = "") -> str:
    """Get the AI provider and model info for display.

    Args:
        ai_provider: AI provider name.
        ai_model: AI model name.

    Returns:
        String like "Claude", "Gemini", or "Cursor (claude-3.5-sonnet)"
    """
    if not ai_provider:
        return "Unknown provider"
    if ai_model:
        return f"{ai_provider.capitalize()} ({ai_model})"
    return ai_provider.capitalize()


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


def _chunk_text(
    text: str,
    message_type: Literal["summary", "failure_detail", "child_job"],
    max_size: int = MAX_MESSAGE_TEXT,
) -> list[ResultMessage]:
    """Split text that exceeds max_size into multiple ResultMessage objects.

    Splits on line boundaries to preserve readability.

    Args:
        text: The text content to potentially split.
        message_type: The type to assign to each resulting ResultMessage.
        max_size: Maximum characters per message.

    Returns:
        List of ResultMessage objects, each under max_size.
    """
    if len(text) <= max_size:
        return [ResultMessage(type=message_type, text=text)]

    messages: list[ResultMessage] = []
    current_chunk = ""
    for line in text.split("\n"):
        # If adding this line would exceed the limit, flush the current chunk
        if current_chunk and len(current_chunk) + len(line) + 1 > max_size:
            messages.append(ResultMessage(type=message_type, text=current_chunk))
            current_chunk = line
        else:
            current_chunk = current_chunk + "\n" + line if current_chunk else line

    if current_chunk:
        messages.append(ResultMessage(type=message_type, text=current_chunk))

    return messages


def build_result_messages(
    result: AnalysisResult, ai_provider: str = "", ai_model: str = ""
) -> list[ResultMessage]:
    """Build hierarchical Slack messages from an analysis result.

    Creates separate messages for:
    1. Summary overview (always present)
    2. One per failure group (grouped by analysis text, same dedup as format_result_as_text)
    3. One per child job analysis

    Any individual message exceeding MAX_MESSAGE_TEXT is chunked further.

    Args:
        result: The analysis result to build messages from.
        ai_provider: AI provider name for display.
        ai_model: AI model name for display.

    Returns:
        List of ResultMessage objects ready for Slack delivery.
    """
    messages: list[ResultMessage] = []

    # 1. Summary message
    summary_lines = [
        f"Job URL: {result.jenkins_url}",
        f"Status: {result.status}",
        f"Job ID: {result.job_id}",
        "",
        f"Summary: {result.summary}",
    ]

    provider_info = get_ai_provider_info(ai_provider=ai_provider, ai_model=ai_model)
    summary_lines.append(f"Analyzed using {provider_info}")

    # Group failures by analysis text (reused for summary count and detail messages)
    analysis_groups: dict[str, list[FailureAnalysis]] = defaultdict(list)
    for f in result.failures:
        analysis_groups[f.analysis].append(f)

    # Add counts
    if analysis_groups:
        summary_lines.append(f"Failure groups: {len(analysis_groups)}")

    if result.child_job_analyses:
        summary_lines.append(f"Child jobs: {len(result.child_job_analyses)}")

    summary_text = "\n".join(summary_lines)
    messages.extend(_chunk_text(summary_text, "summary"))

    # 2. Failure detail messages - one per failure group
    if analysis_groups:
        for group_num, (analysis_text, failures_in_group) in enumerate(
            analysis_groups.items(), 1
        ):
            test_names = [f.test_name for f in failures_in_group]
            representative = failures_in_group[0]

            detail_lines = [
                f"[{group_num}] ({len(failures_in_group)} test(s) with same error)",
            ]

            if len(failures_in_group) > 1:
                detail_lines.append("Affected tests:")
                for name in test_names:
                    detail_lines.append(f"  - {name}")
            else:
                detail_lines.append(f"Test: {test_names[0]}")

            detail_lines.extend(
                [
                    f"Error: {representative.error}",
                    "",
                    "Analysis:",
                    analysis_text,
                ]
            )

            detail_text = "\n".join(detail_lines)
            messages.extend(_chunk_text(detail_text, "failure_detail"))

    # 3. Child job messages - one per child job
    if result.child_job_analyses:
        for child in result.child_job_analyses:
            child_lines = format_child_analysis_as_text(child)
            child_text = "\n".join(child_lines)
            messages.extend(_chunk_text(child_text, "child_job"))

    return messages


def format_slack_message(slack_message: ResultMessage) -> dict:
    """Format a single ResultMessage as a Slack Block Kit message.

    Args:
        slack_message: Pre-built ResultMessage to format.

    Returns:
        Slack Block Kit message payload.
    """
    # Choose header text based on message type
    header_text_map = {
        "summary": "Jenkins Analysis Summary",
        "failure_detail": "Failure Details",
        "child_job": "Child Job Analysis",
    }
    header_text = header_text_map.get(slack_message.type, "Jenkins Analysis")

    max_block_size = 2900  # Leave room for formatting

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": header_text},
        },
    ]

    # Split text into chunks for Slack blocks
    chunks: list[str] = []
    current_chunk = ""
    for line in slack_message.text.split("\n"):
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
    """Send analysis result to a Slack incoming webhook as multiple messages.

    Iterates over result.messages and POSTs each as a separate Slack message.

    Args:
        webhook_url: Slack webhook URL.
        result: Analysis result with pre-built slack_messages.
    """
    if not result.messages:
        logger.warning("No messages to send")
        return

    logger.info(f"Sending {len(result.messages)} Slack message(s)")
    async with httpx.AsyncClient() as client:
        for slack_msg in result.messages:
            message = format_slack_message(slack_msg)
            try:
                await client.post(webhook_url, json=message, timeout=30.0)
            except Exception:
                logger.exception(
                    "Failed to post Slack message (type=%s)", slack_msg.type
                )


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
    """Format analysis result as human-readable text from pre-built messages.

    Iterates over result.messages and joins them with section headers.

    Args:
        result: Analysis result with pre-built messages.

    Returns:
        Human-readable text representation.
    """
    if not result.messages:
        return f"Job URL: {result.jenkins_url}\nStatus: {result.status}\nSummary: {result.summary}"

    header_map = {
        "summary": "JENKINS JOB ANALYSIS",
        "failure_detail": "FAILURE DETAILS",
        "child_job": "CHILD JOB ANALYSIS",
    }

    sections: list[str] = []
    for msg in result.messages:
        header = header_map.get(msg.type, "DETAILS")
        section = f"{'=' * 60}\n{header}\n{'=' * 60}\n{msg.text}"
        sections.append(section)

    return "\n\n".join(sections)
