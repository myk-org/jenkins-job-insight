import asyncio
import os
import re
import urllib.parse
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from xml.etree.ElementTree import ParseError

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import SecretStr
from simple_logger.logger import get_logger

from ai_cli_runner import VALID_AI_PROVIDERS, run_parallel_with_limit
from jenkins_job_insight.analyzer import (
    _resolve_custom_prompt,
    analyze_failure_group,
    analyze_job,
    get_failure_signature,
)
from jenkins_job_insight.config import Settings, get_settings
from jenkins_job_insight.jira import enrich_with_jira_matches
from jenkins_job_insight.models import (
    AddCommentRequest,
    AnalysisResult,
    AnalyzeFailuresRequest,
    AnalyzeRequest,
    BaseAnalysisRequest,
    ChildJobAnalysis,
    FailureAnalysis,
    FailureAnalysisResult,
    SetReviewedRequest,
)
from jenkins_job_insight.xml_enrichment import (
    build_enriched_xml,
    extract_test_failures,
)
from jenkins_job_insight.html_report import (
    FAVICON_SVG,
    format_result_as_html,
    format_status_page,
    generate_dashboard_html,
    generate_register_html,
)
from jenkins_job_insight.output import send_callback
from jenkins_job_insight.repository import RepositoryManager
from jenkins_job_insight import storage
from jenkins_job_insight.storage import (
    get_html_report,
    get_result,
    init_db,
    list_results,
    list_results_for_dashboard,
    save_html_report,
    save_result,
    update_status,
)

logger = get_logger(name=__name__, level=os.environ.get("LOG_LEVEL", "INFO"))

_HOST_RE = re.compile(
    r"^([A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)"  # first label
    r"(\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*"  # additional labels
    r"(:\d+)?$"  # optional port
)

AI_PROVIDER = os.getenv("AI_PROVIDER", "").lower()
AI_MODEL = os.getenv("AI_MODEL", "")


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


def _extract_base_url(request: Request) -> str:
    """Extract the external base URL from incoming request headers.

    Priority:
        1. X-Forwarded-Proto + X-Forwarded-Host (reverse proxy scenario)
        2. Host header + request scheme (direct access)
        3. Fallback to request.url components

    Args:
        request: The incoming FastAPI/Starlette request.

    Returns:
        Base URL without trailing slash (e.g. "https://example.com").
    """
    forwarded_proto = request.headers.get("x-forwarded-proto")
    forwarded_host = request.headers.get("x-forwarded-host")

    if forwarded_proto and forwarded_host:
        # Take first value from comma-separated list (multi-hop proxies)
        proto = forwarded_proto.split(",")[0].strip().lower()
        host = forwarded_host.split(",")[0].strip()
        scheme = proto if proto in ("http", "https") else "https"
        if _HOST_RE.match(host):
            base_url = f"{scheme}://{host}".rstrip("/")
            logger.debug("Base URL from X-Forwarded headers: %s", base_url)
            return base_url

    host = request.headers.get("host")
    if host and _HOST_RE.match(host):
        base_url = f"{request.url.scheme}://{host}".rstrip("/")
        logger.debug("Base URL from Host header: %s", base_url)
        return base_url

    base_url = f"{request.url.scheme}://{request.url.netloc}".rstrip("/")
    logger.debug("Base URL from request URL fallback: %s", base_url)
    return base_url


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


class UsernameMiddleware(BaseHTTPMiddleware):
    """Middleware that checks for jji_username cookie and redirects to /register if missing."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in ("/register", "/health", "/favicon.ico") or path.startswith(
            "/register"
        ):
            return await call_next(request)

        username = request.cookies.get("jji_username", "")
        if not username:
            # Only redirect browser requests, not API calls
            accept = request.headers.get("accept", "")
            if "text/html" in accept:
                return RedirectResponse(url="/register", status_code=303)

        request.state.username = username
        return await call_next(request)


app.add_middleware(UsernameMiddleware)


@app.get("/register", response_class=HTMLResponse)
async def register_page() -> str:
    """Show registration page for new users."""
    return generate_register_html()


@app.post("/register")
async def register(request: Request) -> RedirectResponse:
    """Set username cookie and redirect to dashboard."""
    form = await request.form()
    username = str(form.get("username", "")).strip()
    if not username:
        return RedirectResponse(url="/register", status_code=303)
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie(
        key="jji_username",
        value=username,
        max_age=365 * 24 * 60 * 60,  # 1 year
        samesite="lax",
    )
    return response


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


def _resolve_enable_jira(body: BaseAnalysisRequest, settings: Settings) -> bool:
    """Resolve enable_jira flag from request, env var, or auto-detection.

    Priority order:
    1. Request body field (highest)
    2. ENABLE_JIRA env var (via settings)
    3. Auto-detect from Jira credentials (lowest)

    Args:
        body: The analysis request (AnalyzeRequest or AnalyzeFailuresRequest).
        settings: Application settings (should be merged settings).

    Returns:
        True if Jira enrichment should run, False otherwise.
    """
    if body.enable_jira is not None:
        return body.enable_jira
    return settings.jira_enabled


def _merge_settings(body: BaseAnalysisRequest, settings: Settings) -> Settings:
    """Create a copy of settings with per-request overrides applied.

    Request values take precedence over environment variable defaults.
    Only non-None request values are applied as overrides.

    Args:
        body: The analysis request with optional override fields.
        settings: Base application settings from environment.

    Returns:
        Settings instance with overrides applied (or original if no overrides).
    """
    overrides: dict = {}

    # Direct field mappings (request field name == settings field name).
    # Keep in sync with BaseAnalysisRequest and Settings when adding new overrides.
    # Fields intentionally NOT listed here are handled by their own resolvers:
    #   tests_repo_url   - HttpUrl vs str type mismatch; resolved in endpoint code
    #   ai_provider      - resolved + validated by _resolve_ai_config()
    #   ai_model         - resolved + validated by _resolve_ai_config()
    #   callback_url     - resolved in deliver_results()
    #   callback_headers - resolved in deliver_results()
    direct_fields = [
        "jira_url",
        "jira_email",
        "jira_project_key",
        "jira_ssl_verify",
        "jira_max_results",
        "ai_cli_timeout",
        "enable_jira",
        "jenkins_artifacts_max_size_mb",
        "jenkins_artifacts_context_lines",
        "get_job_artifacts",
    ]
    for field in direct_fields:
        value = getattr(body, field, None)
        if value is not None:
            overrides[field] = value

    # SecretStr fields need wrapping
    if body.jira_api_token is not None:
        overrides["jira_api_token"] = SecretStr(body.jira_api_token)
    if body.jira_pat is not None:
        overrides["jira_pat"] = SecretStr(body.jira_pat)
    if body.github_token is not None:
        overrides["github_token"] = SecretStr(body.github_token)

    # AnalyzeRequest-specific fields (Jenkins overrides)
    if isinstance(body, AnalyzeRequest):
        jenkins_fields = [
            "jenkins_url",
            "jenkins_user",
            "jenkins_password",
            "jenkins_ssl_verify",
        ]
        for field in jenkins_fields:
            value = getattr(body, field, None)
            if value is not None:
                overrides[field] = value

    if overrides:
        merged_data = settings.model_dump(mode="python") | overrides
        return Settings.model_validate(merged_data)
    return settings


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
    job_id: str, body: AnalyzeRequest, settings: Settings, base_url: str = ""
) -> None:
    """Background task to process analysis with a pre-generated job_id.

    Args:
        job_id: Pre-generated job ID for tracking.
        body: The analysis request.
        settings: Application settings.
        base_url: External base URL for constructing absolute result URLs.
    """
    logger.info(
        f"Analysis request received for {body.job_name} #{body.build_number} "
        f"(job_id: {job_id})"
    )
    try:
        await update_status(job_id, "running")

        ai_provider, ai_model = _resolve_ai_config(body)

        result = await analyze_job(
            body,
            settings,
            ai_provider=ai_provider,
            ai_model=ai_model,
            job_id=job_id,
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
        result_data["base_url"] = base_url
        result_data["result_url"] = f"{base_url}/results/{job_id}"
        result_data["html_report_url"] = f"{base_url}/results/{job_id}.html"

        # Save to storage
        await update_status(job_id, result.status, result_data)
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
    request: Request,
    body: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    *,
    sync: bool = Query(
        default=False, description="If true, wait for result and return it"
    ),
    settings: Settings = Depends(get_settings),
) -> dict | JSONResponse:
    """Submit a Jenkins job for analysis.

    By default (async mode), returns immediately with a job_id.
    With ?sync=true, blocks until analysis is complete and returns the full result.
    """
    base_url = _extract_base_url(request)

    if sync:
        logger.info(
            f"Sync analysis request received for {body.job_name} #{body.build_number}"
        )

        merged = _merge_settings(body, settings)
        ai_provider, ai_model = _resolve_ai_config(body)

        result = await analyze_job(
            body,
            merged,
            ai_provider=ai_provider,
            ai_model=ai_model,
        )

        # Enrich PRODUCT BUG failures with Jira matches
        if _resolve_enable_jira(body, merged):
            await _enrich_result_with_jira(
                result.failures + list(result.child_job_analyses),
                merged,
                ai_provider,
                ai_model,
            )

        jenkins_url = build_jenkins_url(
            merged.jenkins_url, body.job_name, body.build_number
        )
        await save_result(
            result.job_id, jenkins_url, result.status, result.model_dump(mode="json")
        )
        logger.info(
            f"Sync analysis completed for {body.job_name} #{body.build_number} "
            f"(job_id: {result.job_id})"
        )

        await deliver_results(result, body, merged)

        content = result.model_dump(mode="json")
        content["base_url"] = base_url
        content["result_url"] = f"{base_url}/results/{result.job_id}"
        content["html_report_url"] = f"{base_url}/results/{result.job_id}.html"

        return JSONResponse(content=content, status_code=200)

    # Async mode - queue background task
    # Generate job_id here so we can return it to the client for polling
    job_id = str(uuid.uuid4())
    merged = _merge_settings(body, settings)
    jenkins_url = build_jenkins_url(
        merged.jenkins_url, body.job_name, body.build_number
    )
    # Save initial pending state before queueing background task
    await save_result(job_id, jenkins_url, "pending", None)
    background_tasks.add_task(process_analysis_with_id, job_id, body, merged, base_url)
    callback_url = body.callback_url or merged.callback_url
    message = "Analysis job queued."
    if callback_url:
        message += " Results will be delivered to callback."
    else:
        message += f" Poll /results/{job_id} for status."

    response: dict = {
        "status": "queued",
        "job_id": job_id,
        "message": message,
        "base_url": base_url,
        "result_url": f"{base_url}/results/{job_id}",
        "html_report_url": f"{base_url}/results/{job_id}.html",
    }

    return response


@app.post("/analyze-failures", response_model=None)
async def analyze_failures(
    request: Request,
    body: AnalyzeFailuresRequest,
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Analyze raw test failures directly without Jenkins.

    Accepts test failure data (or raw JUnit XML) and returns AI analysis.
    Sync only. Reuses the same deduplication and analysis logic as Jenkins-based analysis.

    When raw_xml is provided, failures are extracted from the XML and the enriched
    XML with analysis results is included in the response.
    """
    base_url = _extract_base_url(request)

    if raw_xml := body.raw_xml:
        try:
            test_failures = extract_test_failures(raw_xml)
        except ParseError as e:
            raise HTTPException(status_code=400, detail=f"Invalid XML: {e}")

        if not test_failures:
            job_id = str(uuid.uuid4())
            analysis_result = FailureAnalysisResult(
                job_id=job_id,
                status="completed",
                summary="No test failures found in the provided XML.",
                enriched_xml=raw_xml,
            )
            result_data = analysis_result.model_dump(mode="json")
            result_data["base_url"] = base_url
            result_data["result_url"] = f"{base_url}/results/{job_id}"
            result_data["html_report_url"] = f"{base_url}/results/{job_id}.html"
            return JSONResponse(content=result_data)
    else:
        if not body.failures:
            raise HTTPException(status_code=400, detail="No failures provided")
        test_failures = body.failures

    merged = _merge_settings(body, settings)
    ai_provider, ai_model = _resolve_ai_config_values(body.ai_provider, body.ai_model)

    job_id = str(uuid.uuid4())
    logger.info(
        f"Direct failure analysis request received with {len(test_failures)} failures (job_id: {job_id})"
    )

    # Save initial pending state so GET /results/{job_id} works immediately
    await save_result(job_id, "", "pending", None)

    # Group failures by error signature for deduplication
    groups: dict[str, list] = defaultdict(list)
    for failure in test_failures:
        sig = get_failure_signature(failure)
        groups[sig].append(failure)

    logger.info(
        f"Grouped {len(test_failures)} failures into {len(groups)} unique error signatures"
    )

    # Optionally clone repo for AI code context
    repo_manager = RepositoryManager()
    repo_path = None
    custom_prompt = ""
    tests_repo_url = body.tests_repo_url or merged.tests_repo_url
    try:
        await update_status(job_id, "running")

        if tests_repo_url:
            repo_path = await asyncio.to_thread(repo_manager.clone, str(tests_repo_url))

        custom_prompt = _resolve_custom_prompt(body.raw_prompt, repo_path)

        # Analyze each unique failure group in parallel
        coroutines = [
            analyze_failure_group(
                failures=group_failures,
                console_context="",
                repo_path=repo_path,
                ai_provider=ai_provider,
                ai_model=ai_model,
                ai_cli_timeout=merged.ai_cli_timeout,
                custom_prompt=custom_prompt,
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
        summary = f"Analyzed {len(test_failures)} test failures ({unique_errors} unique errors). {len(all_analyses)} analyzed successfully."

        # Enrich PRODUCT BUG failures with Jira matches
        if _resolve_enable_jira(body, merged):
            await enrich_with_jira_matches(all_analyses, merged, ai_provider, ai_model)

        # If raw_xml was provided, produce enriched XML
        enriched_xml = None
        if raw_xml is not None:
            enriched_xml = build_enriched_xml(
                raw_xml, all_analyses, f"{base_url}/results/{job_id}.html"
            )

        analysis_result = FailureAnalysisResult(
            job_id=job_id,
            status="completed",
            summary=summary,
            ai_provider=ai_provider,
            ai_model=ai_model,
            failures=all_analyses,
            enriched_xml=enriched_xml,
        )

        result_data = analysis_result.model_dump(mode="json")
        result_data["base_url"] = base_url
        result_data["result_url"] = f"{base_url}/results/{job_id}"
        result_data["html_report_url"] = f"{base_url}/results/{job_id}.html"

        await update_status(job_id, "completed", result_data)
        return JSONResponse(content=result_data)

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
        content = analysis_result.model_dump(mode="json")
        content["base_url"] = base_url
        content["result_url"] = f"{base_url}/results/{job_id}"
        return JSONResponse(content=content)

    finally:
        repo_manager.cleanup()


def _build_analysis_result(job_id: str, result_data: dict) -> AnalysisResult:
    """Reconstruct an AnalysisResult from stored result JSON.

    Handles both Jenkins analysis results (which have jenkins_url) and
    direct failure analysis results (which don't).

    Args:
        job_id: The job identifier.
        result_data: The stored result JSON dict.

    Returns:
        AnalysisResult suitable for HTML report generation.
    """
    if result_data.get("jenkins_url"):
        return AnalysisResult.model_validate(result_data)

    # Direct failure analysis — wrap in AnalysisResult
    return AnalysisResult(
        job_id=job_id,
        job_name=result_data.get("job_name", "Direct Failure Analysis"),
        build_number=result_data.get("build_number", 0),
        jenkins_url=None,
        status="completed",
        summary=result_data.get("summary", ""),
        ai_provider=result_data.get("ai_provider", ""),
        ai_model=result_data.get("ai_model", ""),
        failures=[
            FailureAnalysis.model_validate(f) for f in result_data.get("failures", [])
        ],
    )


@app.get("/results/{job_id}.html", response_class=HTMLResponse)
async def get_job_report(
    job_id: str,
    *,
    refresh: bool = Query(
        default=False, description="Force regeneration of the HTML report"
    ),
) -> HTMLResponse:
    """Serve an HTML report, generating it on-demand if needed.

    Reports are generated lazily from stored results and cached to disk.
    Pass ``?refresh=1`` to force regeneration (e.g. after a code update).
    """
    # Try disk cache first (skip when refresh requested)
    if not refresh:
        html_content = await get_html_report(job_id)
        if html_content:
            return HTMLResponse(html_content)

    # Check if the job exists
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

    # Generate HTML on-demand from stored result data
    result_data = result.get("result")
    if result_data and status == "completed":
        analysis_result = _build_analysis_result(job_id, result_data)
        html_content = format_result_as_html(
            analysis_result, completed_at=result.get("created_at", "")
        )
        try:
            await save_html_report(job_id, html_content)
        except OSError:
            logger.warning(
                "Failed to cache HTML report for job_id: %s", job_id, exc_info=True
            )
        logger.info(f"HTML report generated on-demand for job_id: {job_id}")
        return HTMLResponse(html_content)

    raise HTTPException(
        status_code=404,
        detail=f"No report available for job '{job_id}'.",
    )


@app.get("/results/{job_id}", response_model=None)
async def get_job_result(request: Request, job_id: str) -> dict:
    """Retrieve stored result by job_id."""
    result = await get_result(job_id)
    if not result:
        raise HTTPException(status_code=404, detail="Job not found")
    base_url = _extract_base_url(request)
    result["base_url"] = base_url
    result["result_url"] = f"{base_url}/results/{job_id}"
    result_data = result.get("result")
    if isinstance(result_data, dict) and "html_report_url" in result_data:
        # Ensure it's a full URL (update legacy relative paths)
        if result_data["html_report_url"].startswith("/"):
            result_data["html_report_url"] = (
                f"{base_url}{result_data['html_report_url']}"
            )
    return result


def _find_test_in_children(
    children: list[dict],
    test_name: str,
    child_job_name: str,
    child_build_number: int = 0,
) -> bool:
    """Recursively search child job analyses for a test."""
    for child in children:
        if child.get("job_name") == child_job_name and (
            child_build_number == 0 or child.get("build_number") == child_build_number
        ):
            for f in child.get("failures", []):
                if f.get("test_name") == test_name:
                    return True
        if _find_test_in_children(
            child.get("failed_children", []),
            test_name,
            child_job_name,
            child_build_number,
        ):
            return True
    return False


async def _validate_test_name_in_result(
    job_id: str, test_name: str, child_job_name: str = "", child_build_number: int = 0
) -> None:
    """Validate that a test_name exists in the stored result."""
    stored = await storage.get_result(job_id)
    if not stored:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    result_data = stored.get("result") or {}

    if child_job_name:
        if _find_test_in_children(
            result_data.get("child_job_analyses", []),
            test_name,
            child_job_name,
            child_build_number,
        ):
            return
        raise HTTPException(
            status_code=400,
            detail=f"Test '{test_name}' not found in child job '{child_job_name}' of job {job_id}",
        )
    else:
        for f in result_data.get("failures", []):
            if f.get("test_name") == test_name:
                return
        raise HTTPException(
            status_code=400, detail=f"Test '{test_name}' not found in job {job_id}"
        )


def _find_error_signature_in_children(
    children: list[dict],
    test_name: str,
    child_job_name: str,
    child_build_number: int = 0,
) -> str:
    """Recursively find error_signature for a test in child job analyses."""
    for child in children:
        if child.get("job_name") == child_job_name and (
            child_build_number == 0 or child.get("build_number") == child_build_number
        ):
            for f in child.get("failures", []):
                if f.get("test_name") == test_name:
                    return f.get("error_signature", "")
        result = _find_error_signature_in_children(
            child.get("failed_children", []),
            test_name,
            child_job_name,
            child_build_number,
        )
        if result:
            return result
    return ""


async def _invalidate_cached_html(job_id: str) -> None:
    """Delete cached HTML report so next request regenerates it."""
    try:
        report_path = storage.REPORTS_DIR / f"{job_id}.html"
        await asyncio.to_thread(lambda: report_path.unlink(missing_ok=True))
    except OSError:
        pass  # Cache cleanup is best-effort


@app.get("/results/{job_id}/comments")
async def get_comments(job_id: str) -> dict:
    """Get all comments and review states for a job."""
    comments = await storage.get_comments_for_job(job_id)
    reviews = await storage.get_reviews_for_job(job_id)
    return {"comments": comments, "reviews": reviews}


@app.post("/results/{job_id}/comments", status_code=201)
async def add_comment(job_id: str, body: AddCommentRequest, request: Request) -> dict:
    """Add a comment to a test failure."""
    await _validate_test_name_in_result(
        job_id, body.test_name, body.child_job_name, body.child_build_number
    )

    # Read pre-computed error_signature from stored analysis
    error_signature = ""
    stored = await storage.get_result(job_id)
    if stored and stored.get("result"):
        if body.child_job_name:
            error_signature = _find_error_signature_in_children(
                stored["result"].get("child_job_analyses", []),
                body.test_name,
                body.child_job_name,
                body.child_build_number,
            )
        else:
            for f in stored["result"].get("failures", []):
                if f.get("test_name") == body.test_name:
                    error_signature = f.get("error_signature", "")
                    break

    username = request.cookies.get("jji_username", "")
    try:
        comment_id = await storage.add_comment(
            job_id=job_id,
            test_name=body.test_name,
            comment=body.comment,
            child_job_name=body.child_job_name,
            child_build_number=body.child_build_number,
            error_signature=error_signature,
            username=username,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await _invalidate_cached_html(job_id)
    return {"id": comment_id}


@app.put("/results/{job_id}/reviewed")
async def set_reviewed(job_id: str, body: SetReviewedRequest, request: Request) -> dict:
    """Toggle the reviewed state for a test failure."""
    await _validate_test_name_in_result(
        job_id, body.test_name, body.child_job_name, body.child_build_number
    )
    username = request.cookies.get("jji_username", "")
    try:
        await storage.set_reviewed(
            job_id=job_id,
            test_name=body.test_name,
            reviewed=body.reviewed,
            child_job_name=body.child_job_name,
            child_build_number=body.child_build_number,
            username=username,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await _invalidate_cached_html(job_id)
    return {"status": "ok"}


@app.post("/results/{job_id}/enrich-comments")
async def enrich_comments(
    job_id: str, settings: Settings = Depends(get_settings)
) -> dict:
    """Fetch live statuses for GitHub PRs and Jira tickets found in comments."""
    from jenkins_job_insight.comment_enrichment import (
        detect_github_prs,
        detect_jira_keys,
        fetch_github_pr_status,
        fetch_jira_ticket_status,
    )

    comments = await storage.get_comments_for_job(job_id)

    # Detect Cloud vs Server/DC auth once, matching JiraClient logic:
    # - Cloud: jira_email is set -> Basic auth with email:token
    # - Server/DC: no email -> Bearer PAT
    # Token resolution: prefer jira_api_token (backward compat), fall back to jira_pat
    auth: tuple[str, str] | None = None
    auth_headers: dict[str, str] = {}
    jira_url: str | None = settings.jira_url if settings.jira_enabled else None
    jira_active = bool(jira_url)

    if jira_active and jira_url:
        jira_token = ""
        if settings.jira_api_token:
            jira_token = settings.jira_api_token.get_secret_value()
        elif settings.jira_pat:
            jira_token = settings.jira_pat.get_secret_value()

        if settings.jira_email and jira_token:
            # Cloud: Basic auth
            auth = (settings.jira_email, jira_token)
        elif jira_token:
            # Server/DC: Bearer
            auth_headers["Authorization"] = f"Bearer {jira_token}"

    github_token = (
        settings.github_token.get_secret_value() if settings.github_token else None
    )

    # Collect all enrichment tasks for parallel execution
    tasks: list = []
    task_map: dict[int, tuple[str, dict]] = {}

    for c in comments:
        for pr in detect_github_prs(c["comment"]):
            idx = len(tasks)
            tasks.append(
                fetch_github_pr_status(
                    pr["owner"],
                    pr["repo"],
                    pr["number"],
                    token=github_token,
                )
            )
            task_map[idx] = (
                str(c["id"]),
                {
                    "type": "github_pr",
                    "key": f"{pr['owner']}/{pr['repo']}#{pr['number']}",
                },
            )

        if jira_active and jira_url:
            for key in detect_jira_keys(c["comment"]):
                idx = len(tasks)
                tasks.append(
                    fetch_jira_ticket_status(
                        jira_url,
                        key,
                        auth_headers,
                        ssl_verify=settings.jira_ssl_verify,
                        auth=auth,
                    )
                )
                task_map[idx] = (str(c["id"]), {"type": "jira", "key": key})

    enrichments: dict[str, list[dict]] = {}

    if tasks:
        results = await run_parallel_with_limit(tasks)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.debug("Enrichment task %d failed: %s", i, result)
                continue
            if result is None:
                continue
            comment_id, info = task_map[i]
            info["status"] = result
            enrichments.setdefault(comment_id, []).append(info)

    return {"enrichments": enrichments}


@app.get("/results/{job_id}/review-status")
async def get_review_status(job_id: str) -> dict:
    """Get review summary for a job (used by dashboard)."""
    return await storage.get_review_status(job_id)


@app.get("/results")
async def list_job_results(limit: int = Query(50, le=100)) -> list[dict]:
    """List recent analysis jobs."""
    return await list_results(limit)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    limit: int = Query(500, ge=1, le=10000),
) -> HTMLResponse:
    """Serve the dashboard page listing analysis reports.

    Args:
        request: The incoming request (used for base URL detection).
        limit: Maximum number of jobs to load from the database.
    """
    base_url = _extract_base_url(request)
    jobs = await list_results_for_dashboard(limit)
    html_content = generate_dashboard_html(jobs, base_url, limit=limit)
    return HTMLResponse(html_content)


@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    """Serve the application favicon as an SVG image."""
    return Response(
        content=FAVICON_SVG,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


def run() -> None:
    """Entry point for the CLI."""
    import uvicorn

    reload = os.getenv("DEBUG", "").lower() == "true"
    uvicorn.run(
        "jenkins_job_insight.main:app", host="0.0.0.0", port=8000, reload=reload
    )
