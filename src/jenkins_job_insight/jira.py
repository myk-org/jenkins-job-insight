"""Jira integration for product bug deduplication.

Searches Jira for existing issues that match product bug failures,
then uses AI to determine actual relevance, helping teams avoid
filing duplicate bug reports.
"""

import asyncio
import json
import os
from collections.abc import Sequence

import httpx
from simple_logger.logger import get_logger

from jenkins_job_insight.analyzer import call_ai_cli
from jenkins_job_insight.config import Settings
from jenkins_job_insight.models import (
    AnalysisDetail,
    FailureAnalysis,
    JiraMatch,
    ProductBugReport,
)

logger = get_logger(name=__name__, level=os.environ.get("LOG_LEVEL", "INFO"))

# JQL reserved characters that need to be stripped from search keywords
_JQL_SPECIAL_CHARS = set(r'"\'{}[]()~^&|!?*%+-:')


def _sanitize_jql_keyword(keyword: str) -> str:
    """Strip JQL-reserved characters from a search keyword.

    Args:
        keyword: Raw keyword from AI output.

    Returns:
        Sanitized keyword safe for JQL text search.
    """
    return "".join(c for c in keyword if c not in _JQL_SPECIAL_CHARS).strip()


class JiraClient:
    """HTTP client for Jira REST API.

    Auto-detects Cloud (email + API token, REST API v3) vs
    Server/DC (PAT, REST API v2) based on provided credentials.
    """

    def __init__(self, settings: Settings) -> None:
        self._base_url = (settings.jira_url or "").rstrip("/")
        self._project_key = settings.jira_project_key
        self._max_results = settings.jira_max_results

        # Detect Cloud vs Server/DC
        self._auth: tuple[str, str] | None
        if settings.jira_email and settings.jira_api_token:
            # Cloud: Basic auth with email:token, API v3
            self._auth = (
                settings.jira_email,
                settings.jira_api_token.get_secret_value(),
            )
            self._api_path = "/rest/api/3"
            self._headers: dict[str, str] = {}
        else:
            # Server/DC: PAT bearer token, API v2
            self._auth = None
            self._api_path = "/rest/api/2"
            self._headers = {
                "Authorization": f"Bearer {settings.jira_pat.get_secret_value() if settings.jira_pat else ''}"
            }

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            auth=self._auth,
            headers=self._headers,
            verify=settings.jira_ssl_verify,
            timeout=30.0,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> "JiraClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def search(self, keywords: list[str]) -> list[dict]:
        """Search Jira for Bug issues matching the given keywords.

        Builds a JQL query using ``summary ~ "keyword"`` clauses joined
        with OR, filtered to ``issuetype = Bug``, optionally scoped to
        a project.

        Args:
            keywords: Search terms to look for in Jira issue summaries.

        Returns:
            List of dicts with key, summary, description, status, priority, url.
        """
        if not keywords:
            return []

        # Build JQL: summary ~ "kw1" OR summary ~ "kw2" ...
        text_clauses = " OR ".join(
            f'summary ~ "{_sanitize_jql_keyword(kw)}"' for kw in keywords
        )
        jql = f"issuetype = Bug AND ({text_clauses})"
        if self._project_key:
            jql = f'project = "{self._project_key}" AND {jql}'

        jql += " ORDER BY updated DESC"

        params = {
            "jql": jql,
            "maxResults": self._max_results,
            "fields": "summary,description,status,priority",
        }

        response = await self._client.get(
            f"{self._api_path}/search",
            params=params,
        )
        response.raise_for_status()
        data = response.json()

        candidates: list[dict] = []
        for issue in data.get("issues", []):
            fields = issue.get("fields", {})

            # Extract status name (handles both Cloud and Server response shapes)
            status_obj = fields.get("status") or {}
            status_name = (
                status_obj.get("name", "") if isinstance(status_obj, dict) else ""
            )

            # Extract priority name
            priority_obj = fields.get("priority") or {}
            priority_name = (
                priority_obj.get("name", "") if isinstance(priority_obj, dict) else ""
            )

            # Extract description text
            desc = fields.get("description") or ""
            # Cloud API v3 returns description as ADF (Atlassian Document Format)
            if isinstance(desc, dict):
                desc = _extract_text_from_adf(desc)

            issue_key = issue.get("key", "")
            candidates.append(
                {
                    "key": issue_key,
                    "summary": fields.get("summary", ""),
                    "description": desc,
                    "status": status_name,
                    "priority": priority_name,
                    "url": f"{self._base_url}/browse/{issue_key}",
                }
            )

        return candidates


def _extract_text_from_adf(adf: dict) -> str:
    """Extract plain text from Atlassian Document Format (ADF).

    Jira Cloud API v3 returns descriptions as ADF JSON.
    This recursively extracts all text nodes.

    Args:
        adf: ADF document dict.

    Returns:
        Plain text content.
    """
    parts: list[str] = []

    def _walk(node):
        if isinstance(node, dict):
            if node.get("type") == "text":
                parts.append(node.get("text", ""))
            for child in node.get("content", []):
                _walk(child)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(adf)
    return " ".join(parts)


async def _filter_matches_with_ai(
    bug_title: str,
    bug_description: str,
    candidates: list[dict],
    ai_provider: str,
    ai_model: str,
) -> list[JiraMatch]:
    """Use AI to determine which Jira candidates are relevant to the bug.

    Sends the bug context and all candidate issues to the AI, asking it
    to evaluate relevance. Only candidates the AI deems relevant are
    returned as JiraMatch objects.

    Args:
        bug_title: The product bug report title.
        bug_description: The product bug report description.
        candidates: List of candidate dicts from Jira search.
        ai_provider: AI provider name.
        ai_model: AI model identifier.

    Returns:
        List of JiraMatch objects for relevant candidates only.
    """
    if not candidates:
        return []

    # Build candidate list for the AI prompt
    candidate_lines = []
    for i, c in enumerate(candidates, 1):
        desc_preview = c["description"] if c["description"] else "No description"
        candidate_lines.append(
            f"{i}. {c['key']} [{c['status']}] - {c['summary']}\n"
            f"   Description: {desc_preview}"
        )

    prompt = f"""You are evaluating whether existing Jira bug tickets match a newly discovered bug.

NEW BUG:
Title: {bug_title}
Description: {bug_description}

JIRA CANDIDATES:
{chr(10).join(candidate_lines)}

For each candidate, determine if it describes the SAME bug or a closely related issue
(including regressions of previously fixed bugs).

A match means the Jira ticket describes essentially the same broken behavior,
not just that it mentions similar components or technologies.

Respond with ONLY a JSON array. For each candidate include:
- "key": the Jira issue key
- "relevant": true or false
- "score": relevance score 0.0 to 1.0 (1.0 = exact same bug, 0.5+ = likely related)

Example: [{{"key": "PROJ-123", "relevant": true, "score": 0.9}}, {{"key": "PROJ-456", "relevant": false, "score": 0.1}}]

Respond with ONLY the JSON array, no other text."""

    success, output = await call_ai_cli(
        prompt, ai_provider=ai_provider, ai_model=ai_model
    )

    if not success:
        logger.warning("AI relevance filtering failed: %s", output)
        return []

    # Parse AI response
    try:
        text = output.strip()
        # Strip markdown code block if present
        if "```json" in text:
            start = text.index("```json") + len("```json")
            end = text.index("```", start)
            text = text[start:end].strip()
        elif "```" in text:
            start = text.index("```") + len("```")
            end = text.index("```", start)
            text = text[start:end].strip()

        json_start = text.find("[")
        json_end = text.rfind("]")
        if json_start != -1 and json_end != -1:
            text = text[json_start : json_end + 1]

        evaluations = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse AI relevance response")
        return []

    # Build lookup of candidate data by key
    candidate_by_key = {c["key"]: c for c in candidates}

    relevant_matches: list[JiraMatch] = []
    for evaluation in evaluations:
        if not isinstance(evaluation, dict):
            continue
        key = evaluation.get("key", "")
        is_relevant = evaluation.get("relevant", False)
        try:
            score = float(evaluation.get("score", 0.0))
        except (ValueError, TypeError):
            score = 0.0

        if is_relevant and key in candidate_by_key:
            c = candidate_by_key[key]
            relevant_matches.append(
                JiraMatch(
                    key=key,
                    summary=c["summary"],
                    status=c["status"],
                    priority=c["priority"],
                    url=c["url"],
                    score=score,
                )
            )

    relevant_matches.sort(key=lambda m: m.score, reverse=True)
    return relevant_matches


def _collect_product_bug_reports(
    failures: Sequence[FailureAnalysis],
) -> list[ProductBugReport]:
    """Collect all ProductBugReport instances from a list of failures.

    Args:
        failures: List of failure analyses to scan.

    Returns:
        List of ProductBugReport objects found.
    """
    reports: list[ProductBugReport] = []
    for failure in failures:
        detail: AnalysisDetail = failure.analysis
        if isinstance(detail.product_bug_report, ProductBugReport):
            reports.append(detail.product_bug_report)
    return reports


async def enrich_with_jira_matches(
    failures: Sequence[FailureAnalysis],
    settings: Settings,
    ai_provider: str = "",
    ai_model: str = "",
) -> None:
    """Search Jira for matching issues and attach results in-place.

    Collects PRODUCT BUG failures, deduplicates by keyword set,
    searches Jira in parallel, uses AI to filter relevant matches,
    and attaches results to each ``ProductBugReport.jira_matches``.

    This function never raises — all errors are logged and swallowed
    so the analysis pipeline is never interrupted.

    Args:
        failures: Failure analyses to enrich (modified in-place).
        settings: Application settings with Jira configuration.
        ai_provider: AI provider for relevance filtering.
        ai_model: AI model for relevance filtering.
    """
    if not settings.jira_enabled:
        return

    reports = _collect_product_bug_reports(failures)
    if not reports:
        return

    # Deduplicate by keyword set — same keywords = one Jira search
    keyword_to_reports: dict[tuple[str, ...], list[ProductBugReport]] = {}
    for report in reports:
        if not report.jira_search_keywords:
            continue
        key = tuple(sorted(report.jira_search_keywords))
        keyword_to_reports.setdefault(key, []).append(report)

    if not keyword_to_reports:
        logger.debug(
            "No PRODUCT BUG failures with jira_search_keywords, skipping Jira lookup"
        )
        return

    logger.info(
        "Searching Jira for %d unique keyword set(s) across %d PRODUCT BUG failure(s)",
        len(keyword_to_reports),
        len(reports),
    )

    async with JiraClient(settings) as client:
        try:
            # Search Jira for each unique keyword set in parallel
            async def _search_safe(keywords: list[str]) -> list[dict]:
                try:
                    return await client.search(keywords)
                except Exception:
                    logger.exception("Jira search failed for keywords: %s", keywords)
                    return []

            tasks = [_search_safe(list(kw_tuple)) for kw_tuple in keyword_to_reports]
            search_results = await asyncio.gather(*tasks)

            # AI relevance filtering for each keyword set
            for kw_tuple, candidates in zip(keyword_to_reports, search_results):
                if not candidates:
                    continue

                # Use the first report's title/description as context for AI filtering
                representative = keyword_to_reports[kw_tuple][0]

                if ai_provider and ai_model:
                    matches = await _filter_matches_with_ai(
                        bug_title=representative.title,
                        bug_description=representative.description,
                        candidates=candidates,
                        ai_provider=ai_provider,
                        ai_model=ai_model,
                    )
                else:
                    # No AI config — fall back to returning all candidates as matches
                    logger.debug(
                        "No AI provider configured for Jira relevance filtering, returning all candidates"
                    )
                    matches = [
                        JiraMatch(
                            key=c["key"],
                            summary=c["summary"],
                            status=c["status"],
                            priority=c["priority"],
                            url=c["url"],
                            score=0.0,
                        )
                        for c in candidates
                    ]

                # Attach matches to all reports sharing the same keyword set
                for report in keyword_to_reports[kw_tuple]:
                    report.jira_matches = matches

            total_matches = sum(
                len(r.jira_matches)
                for reports_list in keyword_to_reports.values()
                for r in reports_list
            )
            logger.info(
                "Jira search complete: %d relevant match(es) found", total_matches
            )

        except Exception:
            logger.exception("Jira enrichment failed unexpectedly")
