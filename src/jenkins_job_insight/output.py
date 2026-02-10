"""Output delivery for callback webhooks."""

import os

import httpx
from simple_logger.logger import get_logger

from jenkins_job_insight.models import AnalysisResult

logger = get_logger(name=__name__, level=os.environ.get("LOG_LEVEL", "INFO"))


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
