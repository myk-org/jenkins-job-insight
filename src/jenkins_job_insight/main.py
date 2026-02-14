import asyncio
import os
import urllib.parse
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from simple_logger.logger import get_logger

from jenkins_job_insight.analyzer import (
    VALID_AI_PROVIDERS,
    analyze_failure_group,
    analyze_job,
    get_failure_signature,
    run_parallel_with_limit,
)
from jenkins_job_insight.config import Settings, get_settings
from jenkins_job_insight.jira import enrich_with_jira_matches
from jenkins_job_insight.models import (
    AnalysisResult,
    AnalyzeFailuresRequest,
    AnalyzeRequest,
    BaseAnalysisRequest,
    ChildJobAnalysis,
    FailureAnalysis,
    FailureAnalysisResult,
)
from jenkins_job_insight.html_report import format_result_as_html, format_status_page
from jenkins_job_insight.output import send_callback
from jenkins_job_insight.repository import RepositoryManager
from jenkins_job_insight.storage import (
    get_html_report,
    get_result,
    init_db,
    list_results,
    save_html_report,
    save_result,
    update_status,
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


def _resolve_ai_config_values(
    ai_provider: str | None, ai_model: str | None
) -> tuple[str, str]:
    """Resolve and validate AI provider and model from given values or env defaults.

    Args:
        ai_provider: Provider from request body (or None).
        ai_model: Model from request body (or None).

    Returns:
        Tuple of (ai_provider, ai_model).

    Raises:
        HTTPException: If provider or model is not configured.
    """
    provider = ai_provider or AI_PROVIDER
    model = ai_model or AI_MODEL
    if not provider:
        raise HTTPException(
            status_code=400,
            detail=f"No AI provider configured. Set AI_PROVIDER env var or pass ai_provider in request body. Valid providers: {', '.join(sorted(VALID_AI_PROVIDERS))}",
        )
    if not model:
        raise HTTPException(
            status_code=400,
            detail="No AI model configured. Set AI_MODEL env var or pass ai_model in request body.",
        )
    return provider, model


def _resolve_ai_config(body: AnalyzeRequest) -> tuple[str, str]:
    """Resolve AI config from an AnalyzeRequest."""
    return _resolve_ai_config_values(body.ai_provider, body.ai_model)


def _resolve_html_report(body: AnalyzeRequest) -> bool:
    """Resolve html_report flag from request or env var default."""
    if body.html_report is not None:
        return body.html_report
    return HTML_REPORT


def _resolve_enable_jira(body: BaseAnalysisRequest, settings: Settings) -> bool:
    """Resolve enable_jira flag from request or config default.

    Args:
        body: The analysis request (AnalyzeRequest or AnalyzeFailuresRequest).
        settings: Application settings with Jira configuration.

    Returns:
        True if Jira enrichment should run, False otherwise.
    """
    if body.enable_jira is not None:
        return body.enable_jira
    return settings.jira_enabled


async def _generate_html_report(result: AnalysisResult) -> None:
    """Generate and save HTML report to disk."""
    html_content = format_result_as_html(result)
    await save_html_report(result.job_id, html_content)
    logger.info(f"HTML report saved for job_id: {result.job_id}")


async def _enrich_result_with_jira(
    failures: list[FailureAnalysis | ChildJobAnalysis],
    settings: Settings,
    ai_provider: str = "",
    ai_model: str = "",
) -> None:
    """Enrich PRODUCT BUG failures with Jira matches.

    Collects all FailureAnalysis objects from the provided list,
    recursing into ChildJobAnalysis objects, then searches Jira
    for matching issues. Results are attached in-place.

    Args:
        failures: Mixed list of FailureAnalysis and ChildJobAnalysis objects.
        settings: Application settings with Jira configuration.
        ai_provider: AI provider for Jira relevance filtering.
        ai_model: AI model for Jira relevance filtering.
    """
    if not settings.jira_enabled:
        return

    all_failures: list[FailureAnalysis] = []

    def _collect(items: list) -> None:
        for item in items:
            if isinstance(item, FailureAnalysis):
                all_failures.append(item)
            elif isinstance(item, ChildJobAnalysis):
                _collect(item.failures)
                _collect(item.failed_children)

    _collect(failures)

    await enrich_with_jira_matches(all_failures, settings, ai_provider, ai_model)


async def process_analysis_with_id(
    job_id: str, body: AnalyzeRequest, settings: Settings
) -> None:
    """Background task to process analysis with a pre-generated job_id.

    Args:
        job_id: Pre-generated job ID for tracking.
        body: The analysis request.
        settings: Application settings.
    """
    logger.info(
        f"Analysis request received for {body.job_name} #{body.build_number} "
        f"(job_id: {job_id})"
    )
    try:
        await update_status(job_id, "running")

        ai_provider, ai_model = _resolve_ai_config(body)

        result = await analyze_job(
            body, settings, ai_provider=ai_provider, ai_model=ai_model, job_id=job_id
        )

        # Enrich PRODUCT BUG failures with Jira matches
        if _resolve_enable_jira(body, settings):
            await _enrich_result_with_jira(
                result.failures + list(result.child_job_analyses),
                settings,
                ai_provider,
                ai_model,
            )

        result_data = result.model_dump(mode="json")

        # Generate HTML report if enabled
        if _resolve_html_report(body):
            await _generate_html_report(result)
            result_data["html_report_url"] = f"/results/{job_id}.html"

        # Save to storage
        await update_status(job_id, "completed", result_data)
        logger.info(
            f"Analysis completed for {body.job_name} #{body.build_number} "
            f"(job_id: {job_id})"
        )

        await deliver_results(result, body, settings)

    except Exception as e:
        logger.exception(f"Analysis failed for job {job_id}")
        await update_status(job_id, "failed", {"error": str(e)})


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

        # Enrich PRODUCT BUG failures with Jira matches
        if _resolve_enable_jira(body, settings):
            await _enrich_result_with_jira(
                result.failures + list(result.child_job_analyses),
                settings,
                ai_provider,
                ai_model,
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


@app.post("/analyze-failures", response_model=FailureAnalysisResult)
async def analyze_failures(
    body: AnalyzeFailuresRequest,
    settings: Settings = Depends(get_settings),
) -> FailureAnalysisResult:
    """Analyze raw test failures directly without Jenkins.

    Accepts test failure data and returns AI analysis. Sync only.
    Reuses the same deduplication and analysis logic as Jenkins-based analysis.
    """
    if not body.failures:
        raise HTTPException(status_code=400, detail="No failures provided")

    ai_provider, ai_model = _resolve_ai_config_values(body.ai_provider, body.ai_model)

    job_id = str(uuid.uuid4())
    logger.info(
        f"Direct failure analysis request received with {len(body.failures)} failures (job_id: {job_id})"
    )

    # Save initial pending state so GET /results/{job_id} works immediately
    await save_result(job_id, "", "pending", None)

    # Group failures by error signature for deduplication
    groups: dict[str, list] = defaultdict(list)
    for failure in body.failures:
        sig = get_failure_signature(failure)
        groups[sig].append(failure)

    logger.info(
        f"Grouped {len(body.failures)} failures into {len(groups)} unique error signatures"
    )

    # Optionally clone repo for AI code context
    repo_manager = RepositoryManager()
    repo_path = None
    tests_repo_url = body.tests_repo_url or os.getenv("TESTS_REPO_URL")
    try:
        await update_status(job_id, "running")

        if tests_repo_url:
            repo_path = await asyncio.to_thread(repo_manager.clone, str(tests_repo_url))

        # Analyze each unique failure group in parallel
        coroutines = [
            analyze_failure_group(
                failures=group_failures,
                console_context="",
                repo_path=repo_path,
                ai_provider=ai_provider,
                ai_model=ai_model,
            )
            for group_failures in groups.values()
        ]

        results = await run_parallel_with_limit(coroutines)

        # Flatten results and filter out exceptions
        all_analyses = []
        for result in results:
            if isinstance(result, Exception):
                logger.error(
                    f"Failed to analyze failure group: {result}", exc_info=result
                )
            else:
                all_analyses.extend(result)

        unique_errors = len(groups)
        summary = f"Analyzed {len(body.failures)} test failures ({unique_errors} unique errors). {len(all_analyses)} analyzed successfully."

        # Enrich PRODUCT BUG failures with Jira matches
        if _resolve_enable_jira(body, settings):
            await enrich_with_jira_matches(
                all_analyses, settings, ai_provider, ai_model
            )

        analysis_result = FailureAnalysisResult(
            job_id=job_id,
            status="completed",
            summary=summary,
            ai_provider=ai_provider,
            ai_model=ai_model,
            failures=all_analyses,
        )
        await update_status(
            job_id, "completed", analysis_result.model_dump(mode="json")
        )
        return analysis_result

    except Exception as e:
        logger.exception(f"Direct failure analysis failed for job {job_id}")
        analysis_result = FailureAnalysisResult(
            job_id=job_id,
            status="failed",
            summary=f"Analysis failed: {e}",
            ai_provider=ai_provider,
            ai_model=ai_model,
        )
        await update_status(job_id, "failed", analysis_result.model_dump(mode="json"))
        return analysis_result

    finally:
        repo_manager.cleanup()


@app.get("/results/{job_id}.html", response_class=HTMLResponse)
async def get_job_report(job_id: str) -> HTMLResponse:
    """Serve a saved HTML report or a status page if still processing."""
    html_content = await get_html_report(job_id)
    if html_content:
        return HTMLResponse(html_content)

    # Check if the job exists and show a status page
    result = await get_result(job_id)
    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"Job '{job_id}' not found.",
        )

    status = result.get("status", "unknown")
    if status in ("pending", "running"):
        return HTMLResponse(
            format_status_page(job_id, status, result),
            headers={"Refresh": "10"},
        )

    # Job completed/failed but no HTML report was generated
    raise HTTPException(
        status_code=404,
        detail=f"HTML report not found for job '{job_id}'. The report may not have been generated.",
    )


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
