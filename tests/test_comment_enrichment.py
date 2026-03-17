"""Tests for comment enrichment."""

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from jenkins_job_insight.comment_enrichment import (
    detect_github_prs,
    detect_jira_keys,
    fetch_github_pr_status,
    fetch_jira_ticket_status,
)


class TestDetectGitHubPRs:
    def test_detect_pr_url(self):
        prs = detect_github_prs("Fix merged: https://github.com/org/repo/pull/123")
        assert len(prs) == 1
        assert prs[0] == {"owner": "org", "repo": "repo", "number": 123}

    def test_detect_multiple_prs(self):
        text = "See https://github.com/a/b/pull/1 and https://github.com/c/d/pull/2"
        prs = detect_github_prs(text)
        assert len(prs) == 2

    def test_no_prs(self):
        prs = detect_github_prs("just a regular comment")
        assert prs == []


class TestDetectJiraKeys:
    def test_detect_jira_key(self):
        keys = detect_jira_keys("Opened bug: OCPBUGS-12345")
        assert "OCPBUGS-12345" in keys

    def test_detect_multiple_keys(self):
        keys = detect_jira_keys("See OCPBUGS-100 and CNV-200")
        assert len(keys) == 2

    def test_no_keys(self):
        keys = detect_jira_keys("no jira here")
        assert keys == []


class TestFetchGitHubPRStatus:
    @pytest.mark.asyncio
    async def test_fetch_merged_pr(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"state": "closed", "merged": True}

        with patch(
            "jenkins_job_insight.comment_enrichment.httpx.AsyncClient"
        ) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = mock_instance

            status = await fetch_github_pr_status("org", "repo", 123)
            assert status == "merged"

    @pytest.mark.asyncio
    async def test_fetch_open_pr(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"state": "open", "merged": False}

        with patch(
            "jenkins_job_insight.comment_enrichment.httpx.AsyncClient"
        ) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = mock_instance

            status = await fetch_github_pr_status("org", "repo", 123)
            assert status == "open"

    @pytest.mark.asyncio
    async def test_fetch_pr_not_found(self):
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch(
            "jenkins_job_insight.comment_enrichment.httpx.AsyncClient"
        ) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = mock_instance

            status = await fetch_github_pr_status("org", "repo", 999)
            assert status is None


class TestFetchJiraTicketStatus:
    @pytest.mark.asyncio
    async def test_fetch_status_cloud_v3(self):
        """Cloud API v3 endpoint returns ticket status."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "issues": [
                {
                    "key": "PROJ-100",
                    "fields": {"status": {"name": "Closed"}},
                }
            ]
        }

        with patch(
            "jenkins_job_insight.comment_enrichment.httpx.AsyncClient"
        ) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = mock_instance

            status = await fetch_jira_ticket_status(
                "https://myorg.atlassian.net",
                "PROJ-100",
                {},
                auth=("user@example.com", "api-token"),
            )
            assert status == "Closed"

    @pytest.mark.asyncio
    async def test_fallback_from_v3_to_v2(self):
        """When v3 returns 410 Gone, falls back to v2 endpoint."""
        v3_response = MagicMock()
        v3_response.status_code = 410

        v2_response = MagicMock()
        v2_response.status_code = 200
        v2_response.json.return_value = {
            "issues": [
                {
                    "key": "PROJ-200",
                    "fields": {"status": {"name": "Open"}},
                }
            ]
        }

        with patch(
            "jenkins_job_insight.comment_enrichment.httpx.AsyncClient"
        ) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = [v3_response, v2_response]
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = mock_instance

            status = await fetch_jira_ticket_status(
                "https://jira-server.example.com",
                "PROJ-200",
                {"Authorization": "Bearer pat-token"},
            )
            assert status == "Open"
            assert mock_instance.get.call_count == 2

    @pytest.mark.asyncio
    async def test_returns_none_on_non_200_non_410(self):
        """Non-200/non-410 status returns None without trying fallback."""
        mock_response = MagicMock()
        mock_response.status_code = 403

        with patch(
            "jenkins_job_insight.comment_enrichment.httpx.AsyncClient"
        ) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = mock_instance

            status = await fetch_jira_ticket_status(
                "https://jira.example.com",
                "PROJ-300",
                {"Authorization": "Bearer bad-token"},
            )
            assert status is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        """Network errors return None gracefully."""
        with patch(
            "jenkins_job_insight.comment_enrichment.httpx.AsyncClient"
        ) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = httpx.ConnectError("connection refused")
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = mock_instance

            status = await fetch_jira_ticket_status(
                "https://jira.example.com",
                "PROJ-400",
                {},
            )
            assert status is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_issues(self):
        """Empty issues list returns None."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"issues": []}

        with patch(
            "jenkins_job_insight.comment_enrichment.httpx.AsyncClient"
        ) as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = mock_instance

            status = await fetch_jira_ticket_status(
                "https://jira.example.com",
                "PROJ-999",
                {},
            )
            assert status is None
