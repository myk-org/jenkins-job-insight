import os
import urllib.parse
import uuid
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from simple_logger.logger import get_logger

from jenkins_job_insight.analyzer import (
    AI_PROVIDER,
    CURSOR_MODEL,
    QODO_MODEL,
    analyze_job,
    call_ai_cli,
)
from jenkins_job_insight.config import Settings, get_settings
from jenkins_job_insight.models import AnalysisResult, AnalyzeRequest
from jenkins_job_insight.output import format_result_as_text, send_callback, send_slack
from jenkins_job_insight.storage import get_result, init_db, list_results, save_result

logger = get_logger(name=__name__, level=os.environ.get("LOG_LEVEL", "INFO"))


async def deliver_results(
    result: AnalysisResult,
    request: AnalyzeRequest,
    settings: Settings,
) -> None:
    """Deliver analysis results to callback and Slack webhooks.

    Uses request values if provided, otherwise falls back to settings.

    Args:
        result: The analysis result to deliver.
        request: The original analyze request containing optional callback/slack URLs.
        settings: Application settings with default callback/slack URLs.
    """
    callback_url = request.callback_url or settings.callback_url
    callback_headers = request.callback_headers or settings.callback_headers
    if callback_url:
        try:
            await send_callback(str(callback_url), result, callback_headers)
        except Exception:
            logger.exception("Failed to send callback to %s", callback_url)

    slack_url = request.slack_webhook_url or settings.slack_webhook_url
    if slack_url:
        try:
            await send_slack(str(slack_url), result)
        except Exception:
            logger.exception("Failed to send Slack notification to %s", slack_url)


def build_jenkins_url(base_url: str, job_name: str, build_number: int) -> str:
    """Construct full Jenkins build URL from job name and build number.

    Args:
        base_url: Base Jenkins URL from settings.
        job_name: Job name (can include folders like "folder/job-name").
        build_number: Build number.

    Returns:
        Full Jenkins build URL.
    """
    # Handle folder-style job names by URL-encoding each segment and joining with '/job/'
    segments = job_name.split("/")
    encoded_segments = [urllib.parse.quote(segment, safe="") for segment in segments]
    job_path = "/job/".join(encoded_segments)
    return f"{base_url.rstrip('/')}/job/{job_path}/{build_number}/"


async def validate_ai_provider() -> None:
    """Validate AI provider is configured and working.

    Sends a simple test prompt to verify the AI CLI is accessible.
    Raises RuntimeError if validation fails, which will crash the container.

    Set SKIP_AI_VALIDATION=1 to skip (for testing).
    """
    if os.getenv("SKIP_AI_VALIDATION", "").lower() in ("1", "true", "yes"):
        logger.info("Skipping AI provider validation (SKIP_AI_VALIDATION is set)")
        return

    provider = AI_PROVIDER
    model = ""
    if provider == "qodo":
        model = QODO_MODEL
    elif provider == "cursor":
        model = CURSOR_MODEL

    provider_info = f"{provider.upper()}" + (f" ({model})" if model else "")

    logger.info(f"Validating AI provider: {provider_info}")

    try:
        response = await call_ai_cli("Reply with only: OK")
        if not response or "error" in response.lower()[:50]:
            raise RuntimeError(f"AI provider validation failed: {response[:200]}")
        logger.info(f"AI provider validation successful: {provider_info}")
    except Exception as e:
        error_msg = f"AI provider {provider_info} is not working: {e}"
        logger.error(error_msg)
        raise RuntimeError(error_msg) from e


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await validate_ai_provider()
    yield


app = FastAPI(
    title="Jenkins Job Insight",
    description="Analyzes Jenkins job failures and classifies them as code or product issues",
    version="0.1.0",
    lifespan=lifespan,
)


async def process_analysis_with_id(
    job_id: str, request: AnalyzeRequest, settings: Settings
) -> None:
    """Background task to process analysis with a pre-generated job_id.

    Args:
        job_id: Pre-generated job ID for tracking.
        request: The analysis request.
        settings: Application settings.
    """
    jenkins_url = build_jenkins_url(
        settings.jenkins_url, request.job_name, request.build_number
    )
    logger.info(
        f"Analysis request received for {request.job_name} #{request.build_number} "
        f"(job_id: {job_id})"
    )
    try:
        result = await analyze_job(request, settings, job_id)

        # Save to storage
        await save_result(
            job_id, jenkins_url, "completed", result.model_dump(mode="json")
        )
        logger.info(
            f"Analysis completed for {request.job_name} #{request.build_number} "
            f"(job_id: {job_id})"
        )

        await deliver_results(result, request, settings)

    except Exception as e:
        logger.exception(f"Analysis failed for job {job_id}")
        await save_result(job_id, jenkins_url, "failed", {"error": str(e)})


@app.post("/analyze", status_code=202, response_model=None)
async def analyze(
    request: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    sync: bool = Query(False, description="If true, wait for result and return it"),
    output: str = Query("json", description="Output format: json or text"),
    settings: Settings = Depends(get_settings),
) -> dict | AnalysisResult | Response:
    """Submit a Jenkins job for analysis.

    By default (async mode), returns immediately with a job_id.
    With ?sync=true, blocks until analysis is complete and returns the full result.
    Use ?output=text for human-readable plain text format (only applies to sync mode).
    """
    if sync:
        logger.info(
            f"Sync analysis request received for {request.job_name} #{request.build_number}"
        )
        result = await analyze_job(request, settings)
        jenkins_url = build_jenkins_url(
            settings.jenkins_url, request.job_name, request.build_number
        )
        await save_result(
            result.job_id, jenkins_url, "completed", result.model_dump(mode="json")
        )
        logger.info(
            f"Sync analysis completed for {request.job_name} #{request.build_number} "
            f"(job_id: {result.job_id})"
        )

        await deliver_results(result, request, settings)

        if output == "text":
            return PlainTextResponse(format_result_as_text(result), status_code=200)
        return JSONResponse(content=result.model_dump(mode="json"), status_code=200)

    # Async mode - queue background task
    # Generate job_id here so we can return it to the client for polling
    job_id = str(uuid.uuid4())
    jenkins_url = build_jenkins_url(
        settings.jenkins_url, request.job_name, request.build_number
    )
    # Save initial pending state before queueing background task
    await save_result(job_id, jenkins_url, "pending", None)
    background_tasks.add_task(process_analysis_with_id, job_id, request, settings)
    return {
        "status": "queued",
        "message": "Analysis job queued. Results will be delivered to callback/slack.",
        "job_id": job_id,
    }


@app.get("/results/{job_id}")
async def get_job_result(job_id: str) -> dict:
    """Retrieve stored result by job_id."""
    result = await get_result(job_id)
    if not result:
        raise HTTPException(status_code=404, detail="Job not found")
    return result


@app.get("/results")
async def list_job_results(limit: int = Query(50, le=100)) -> list[dict]:
    """List recent analysis jobs."""
    return await list_results(limit)


@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint."""
    return {"status": "healthy"}


def run() -> None:
    """Entry point for the CLI."""
    import uvicorn

    reload = os.getenv("DEBUG", "").lower() == "true"
    uvicorn.run(
        "jenkins_job_insight.main:app", host="0.0.0.0", port=8000, reload=reload
    )
