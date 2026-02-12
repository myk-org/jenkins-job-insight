import os
import urllib.parse
import uuid
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from simple_logger.logger import get_logger

from jenkins_job_insight.analyzer import (
    VALID_AI_PROVIDERS,
    analyze_job,
)
from jenkins_job_insight.config import Settings, get_settings
from jenkins_job_insight.models import AnalysisResult, AnalyzeRequest
from jenkins_job_insight.html_report import format_result_as_html
from jenkins_job_insight.output import send_callback
from jenkins_job_insight.storage import (
    get_html_report,
    get_result,
    init_db,
    list_results,
    save_html_report,
    save_result,
)

logger = get_logger(name=__name__, level=os.environ.get("LOG_LEVEL", "INFO"))

AI_PROVIDER = os.getenv("AI_PROVIDER", "").lower()
AI_MODEL = os.getenv("AI_MODEL", "")
HTML_REPORT = os.getenv("HTML_REPORT", "true").lower() == "true"


async def deliver_results(
    result: AnalysisResult,
    body: AnalyzeRequest,
    settings: Settings,
) -> None:
    """Deliver analysis results to callback webhook.

    Uses request values if provided, otherwise falls back to settings.

    Args:
        result: The analysis result to deliver.
        body: The original analyze request containing optional callback URL.
        settings: Application settings with default callback URL.
    """
    callback_url = body.callback_url or settings.callback_url
    callback_headers = body.callback_headers or settings.callback_headers
    if callback_url:
        try:
            await send_callback(str(callback_url), result, callback_headers)
        except Exception:
            logger.exception("Failed to send callback to %s", callback_url)


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="Jenkins Job Insight",
    description="Analyzes Jenkins job failures and classifies them as code or product issues",
    version="0.1.0",
    lifespan=lifespan,
)


def _resolve_ai_config(body: AnalyzeRequest) -> tuple[str, str]:
    """Resolve AI provider and model from request or env var defaults.

    Args:
        body: The analysis request with optional ai_provider/ai_model overrides.

    Returns:
        Tuple of (ai_provider, ai_model).

    Raises:
        HTTPException: If provider or model is not configured.
    """
    ai_provider = body.ai_provider or AI_PROVIDER
    ai_model = body.ai_model or AI_MODEL
    if not ai_provider:
        raise HTTPException(
            status_code=400,
            detail=f"No AI provider configured. Set AI_PROVIDER env var or pass ai_provider in request body. Valid providers: {', '.join(sorted(VALID_AI_PROVIDERS))}",
        )
    if not ai_model:
        raise HTTPException(
            status_code=400,
            detail="No AI model configured. Set AI_MODEL env var or pass ai_model in request body.",
        )
    return ai_provider, ai_model


def _resolve_html_report(body: AnalyzeRequest) -> bool:
    """Resolve html_report flag from request or env var default."""
    if body.html_report is not None:
        return body.html_report
    return HTML_REPORT


async def _generate_html_report(result: AnalysisResult) -> None:
    """Generate and save HTML report to disk."""
    html_content = format_result_as_html(result)
    await save_html_report(result.job_id, html_content)
    logger.info(f"HTML report saved for job_id: {result.job_id}")


async def process_analysis_with_id(
    job_id: str, body: AnalyzeRequest, settings: Settings
) -> None:
    """Background task to process analysis with a pre-generated job_id.

    Args:
        job_id: Pre-generated job ID for tracking.
        body: The analysis request.
        settings: Application settings.
    """
    jenkins_url = build_jenkins_url(
        settings.jenkins_url, body.job_name, body.build_number
    )
    logger.info(
        f"Analysis request received for {body.job_name} #{body.build_number} "
        f"(job_id: {job_id})"
    )
    try:
        ai_provider, ai_model = _resolve_ai_config(body)

        result = await analyze_job(
            body, settings, ai_provider=ai_provider, ai_model=ai_model, job_id=job_id
        )

        result_data = result.model_dump(mode="json")

        # Generate HTML report if enabled
        if _resolve_html_report(body):
            await _generate_html_report(result)
            result_data["html_report_url"] = f"/results/{job_id}.html"

        # Save to storage
        await save_result(job_id, jenkins_url, "completed", result_data)
        logger.info(
            f"Analysis completed for {body.job_name} #{body.build_number} "
            f"(job_id: {job_id})"
        )

        await deliver_results(result, body, settings)

    except Exception as e:
        logger.exception(f"Analysis failed for job {job_id}")
        await save_result(job_id, jenkins_url, "failed", {"error": str(e)})


@app.post("/analyze", status_code=202, response_model=None)
async def analyze(
    body: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    sync: bool = Query(False, description="If true, wait for result and return it"),
    settings: Settings = Depends(get_settings),
) -> dict | JSONResponse:
    """Submit a Jenkins job for analysis.

    By default (async mode), returns immediately with a job_id.
    With ?sync=true, blocks until analysis is complete and returns the full result.
    """
    if sync:
        logger.info(
            f"Sync analysis request received for {body.job_name} #{body.build_number}"
        )

        ai_provider, ai_model = _resolve_ai_config(body)

        result = await analyze_job(
            body, settings, ai_provider=ai_provider, ai_model=ai_model
        )
        jenkins_url = build_jenkins_url(
            settings.jenkins_url, body.job_name, body.build_number
        )
        await save_result(
            result.job_id, jenkins_url, "completed", result.model_dump(mode="json")
        )
        logger.info(
            f"Sync analysis completed for {body.job_name} #{body.build_number} "
            f"(job_id: {result.job_id})"
        )

        await deliver_results(result, body, settings)

        content = result.model_dump(mode="json")

        if _resolve_html_report(body):
            await _generate_html_report(result)
            content["html_report_url"] = f"/results/{result.job_id}.html"

        return JSONResponse(content=content, status_code=200)

    # Async mode - queue background task
    # Generate job_id here so we can return it to the client for polling
    job_id = str(uuid.uuid4())
    jenkins_url = build_jenkins_url(
        settings.jenkins_url, body.job_name, body.build_number
    )
    # Save initial pending state before queueing background task
    await save_result(job_id, jenkins_url, "pending", None)
    background_tasks.add_task(process_analysis_with_id, job_id, body, settings)
    callback_url = body.callback_url or settings.callback_url
    message = "Analysis job queued."
    if callback_url:
        message += " Results will be delivered to callback."
    else:
        message += f" Poll /results/{job_id} for status."

    response: dict = {
        "status": "queued",
        "job_id": job_id,
        "message": message,
    }

    return response


@app.get("/results/{job_id}.html", response_class=HTMLResponse)
async def get_job_report(job_id: str) -> HTMLResponse:
    """Serve a saved HTML report."""
    html_content = await get_html_report(job_id)
    if not html_content:
        raise HTTPException(
            status_code=404,
            detail=f"HTML report not found for job '{job_id}'. The report may not have been generated.",
        )
    return HTMLResponse(html_content)


@app.get("/results/{job_id}", response_model=None)
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
