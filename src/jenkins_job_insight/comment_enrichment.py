"""Comment enrichment: detect and fetch status for GitHub PRs and Jira tickets in comments."""

import os
import re

import httpx
from simple_logger.logger import get_logger

logger = get_logger(name=__name__, level=os.environ.get("LOG_LEVEL", "INFO"))

_GITHUB_PR_PATTERN = re.compile(r"https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)")

_JIRA_KEY_PATTERN = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")


def detect_github_prs(text: str) -> list[dict]:
    """Detect GitHub PR URLs in text.

    Args:
        text: The comment text to scan.

    Returns:
        List of dicts with 'owner', 'repo', and 'number' keys.
    """
    matches = _GITHUB_PR_PATTERN.findall(text)
    return [{"owner": m[0], "repo": m[1], "number": int(m[2])} for m in matches]


def detect_jira_keys(text: str) -> list[str]:
    """Detect Jira ticket keys in text.

    Args:
        text: The comment text to scan.

    Returns:
        List of Jira ticket keys (e.g. ['OCPBUGS-12345', 'CNV-200']).
    """
    return _JIRA_KEY_PATTERN.findall(text)


async def fetch_github_pr_status(
    owner: str,
    repo: str,
    number: int,
    token: str | None = None,
) -> str | None:
    """Fetch the status of a GitHub PR.

    Args:
        owner: Repository owner.
        repo: Repository name.
        number: Pull request number.
        token: Optional GitHub personal access token for authentication.

    Returns:
        'open', 'closed', 'merged', or None if fetch fails.
    """
    headers: dict[str, str] = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}",
                headers=headers,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            if data.get("merged"):
                return "merged"
            return data.get("state")
    except Exception:
        return None


def _extract_status_from_issues(data: dict) -> str | None:
    """Extract the status name from a Jira search response.

    Args:
        data: Parsed JSON response from the Jira search API.

    Returns:
        Status name string or None if not found.
    """
    issues = data.get("issues", [])
    if issues:
        status_obj = issues[0].get("fields", {}).get("status", {})
        return status_obj.get("name") if isinstance(status_obj, dict) else None
    return None


async def fetch_jira_ticket_status(
    jira_url: str,
    ticket_key: str,
    auth_headers: dict[str, str],
    ssl_verify: bool = True,
    auth: tuple[str, str] | None = None,
) -> str | None:
    """Fetch Jira ticket status by key using direct REST API with JQL key lookup.

    Tries the Cloud API v3 endpoint first (``/rest/api/3/search/jql``), then
    falls back to the legacy v2 endpoint (``/rest/api/2/search``) for
    Server/Data Center instances.

    Args:
        jira_url: Base Jira URL (e.g. 'https://jira.example.com').
        ticket_key: Jira ticket key (e.g. 'OCPBUGS-12345').
        auth_headers: Authorization headers for Jira API (used when *auth* is None).
        ssl_verify: Whether to verify SSL certificates.
        auth: Optional ``(username, token)`` tuple for httpx Basic auth (Cloud).
              When provided, *auth_headers* are ignored for authentication.

    Returns:
        Status string (e.g. 'Open', 'Closed') or None if fetch fails.
    """
    base = jira_url.rstrip("/")
    jql = f'key = "{ticket_key}"'
    search_params = {"jql": jql, "maxResults": 1, "fields": "status"}

    # Endpoints to try in order: Cloud v3 first, then Server/DC v2
    endpoints = [
        f"{base}/rest/api/3/search/jql",
        f"{base}/rest/api/2/search",
    ]

    try:
        async with httpx.AsyncClient(
            verify=ssl_verify, timeout=10, auth=auth, headers=auth_headers
        ) as client:
            for i, url in enumerate(endpoints):
                resp = await client.get(url, params=search_params)
                if resp.status_code == 200:
                    return _extract_status_from_issues(resp.json())
                logger.debug(
                    "Jira endpoint %s returned status %d", url, resp.status_code
                )
                # If this is the last endpoint, give up
                if i == len(endpoints) - 1:
                    return None
                # Otherwise, try the next endpoint
    except Exception:
        logger.debug(
            "Jira ticket status fetch failed for %s", ticket_key, exc_info=True
        )
        return None
    return None
