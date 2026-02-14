"""Tests for Jira integration."""

import os
from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from jenkins_job_insight.config import Settings
from jenkins_job_insight.jira import (
    JiraClient,
    _collect_product_bug_reports,
    _extract_text_from_adf,
    enrich_with_jira_matches,
)
from jenkins_job_insight.models import (
    AnalysisDetail,
    FailureAnalysis,
    JiraMatch,
    ProductBugReport,
)


@pytest.fixture
def jira_settings() -> Generator[Settings, None, None]:
    """Create Settings with Jira Cloud credentials."""
    env = {
        "JENKINS_URL": "https://jenkins.example.com",
        "JENKINS_USER": "testuser",
        "JENKINS_PASSWORD": "testpassword",  # pragma: allowlist secret
        "JIRA_URL": "https://jira.example.com",
        "JIRA_EMAIL": "user@example.com",
        "JIRA_API_TOKEN": "test-token",
        "JIRA_PROJECT_KEY": "PROJ",
    }
    with patch.dict(os.environ, env, clear=True):
        yield Settings()


@pytest.fixture
def jira_server_settings() -> Generator[Settings, None, None]:
    """Create Settings with Jira Server/DC PAT credentials."""
    env = {
        "JENKINS_URL": "https://jenkins.example.com",
        "JENKINS_USER": "testuser",
        "JENKINS_PASSWORD": "testpassword",  # pragma: allowlist secret
        "JIRA_URL": "https://jira-server.example.com",
        "JIRA_PAT": "server-pat-token",
    }
    with patch.dict(os.environ, env, clear=True):
        yield Settings()


@pytest.fixture
def product_bug_failure() -> FailureAnalysis:
    """A failure classified as PRODUCT BUG with search keywords."""
    return FailureAnalysis(
        test_name="test_login",
        error="HTTP 500",
        analysis=AnalysisDetail(
            classification="PRODUCT BUG",
            details="Auth service broken",
            product_bug_report=ProductBugReport(
                title="Login fails",
                severity="high",
                component="auth",
                description="Login service returns 500 error",
                jira_search_keywords=["login", "authentication", "500 error"],
            ),
        ),
    )


@pytest.fixture
def code_issue_failure() -> FailureAnalysis:
    """A failure classified as CODE ISSUE (no Jira search needed)."""
    return FailureAnalysis(
        test_name="test_config",
        error="ImportError",
        analysis=AnalysisDetail(
            classification="CODE ISSUE",
            details="Missing import",
        ),
    )


@pytest.fixture
def product_bug_no_keywords() -> FailureAnalysis:
    """A PRODUCT BUG failure without search keywords."""
    return FailureAnalysis(
        test_name="test_api",
        error="Timeout",
        analysis=AnalysisDetail(
            classification="PRODUCT BUG",
            details="API timeout",
            product_bug_report=ProductBugReport(
                title="API timeout",
                severity="medium",
            ),
        ),
    )


class TestExtractTextFromAdf:
    """Tests for ADF text extraction."""

    def test_extracts_text_nodes(self) -> None:
        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Hello"},
                        {"type": "text", "text": "World"},
                    ],
                }
            ],
        }
        assert _extract_text_from_adf(adf) == "Hello World"

    def test_empty_doc(self) -> None:
        assert _extract_text_from_adf({}) == ""

    def test_nested_content(self) -> None:
        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "bulletList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [{"type": "text", "text": "item"}],
                                }
                            ],
                        }
                    ],
                }
            ],
        }
        assert "item" in _extract_text_from_adf(adf)


class TestCollectProductBugReports:
    """Tests for _collect_product_bug_reports."""

    def test_collects_product_bugs(self, product_bug_failure) -> None:
        reports = _collect_product_bug_reports([product_bug_failure])
        assert len(reports) == 1
        assert reports[0].title == "Login fails"

    def test_skips_code_issues(self, code_issue_failure) -> None:
        reports = _collect_product_bug_reports([code_issue_failure])
        assert len(reports) == 0

    def test_mixed_failures(self, product_bug_failure, code_issue_failure) -> None:
        reports = _collect_product_bug_reports(
            [product_bug_failure, code_issue_failure]
        )
        assert len(reports) == 1

    def test_empty_list(self) -> None:
        reports = _collect_product_bug_reports([])
        assert len(reports) == 0


class TestJiraClient:
    """Tests for JiraClient."""

    def test_cloud_auth_detection(self, jira_settings) -> None:
        """Cloud credentials use email+token auth and API v3."""
        client = JiraClient(jira_settings)
        assert client._api_path == "/rest/api/3"
        assert client._auth is not None

    def test_server_auth_detection(self, jira_server_settings) -> None:
        """Server/DC credentials use PAT bearer token and API v2."""
        client = JiraClient(jira_server_settings)
        assert client._api_path == "/rest/api/2"
        assert client._auth is None
        assert "Bearer" in client._headers.get("Authorization", "")

    async def test_search_returns_candidates(self, jira_settings) -> None:
        """Search returns candidate dicts from API response."""
        mock_response = httpx.Response(
            200,
            json={
                "issues": [
                    {
                        "key": "PROJ-123",
                        "fields": {
                            "summary": "Login authentication failure",
                            "description": "Users cannot log in",
                            "status": {"name": "Open"},
                            "priority": {"name": "High"},
                        },
                    },
                ]
            },
            request=httpx.Request("GET", "https://jira.example.com"),
        )

        client = JiraClient(jira_settings)
        with patch.object(
            client._client, "get", new_callable=AsyncMock, return_value=mock_response
        ):
            candidates = await client.search(["login", "authentication"])

        assert len(candidates) == 1
        assert candidates[0]["key"] == "PROJ-123"
        assert candidates[0]["summary"] == "Login authentication failure"
        assert candidates[0]["description"] == "Users cannot log in"
        assert candidates[0]["url"].startswith("https://jira.example.com/browse/")
        await client.close()

    async def test_search_empty_keywords(self, jira_settings) -> None:
        """Search with empty keywords returns empty list."""
        client = JiraClient(jira_settings)
        candidates = await client.search([])
        assert candidates == []
        await client.close()

    async def test_search_jql_contains_bug_filter(self, jira_settings) -> None:
        """Search JQL includes issuetype = Bug and summary search."""
        mock_response = httpx.Response(
            200,
            json={"issues": []},
            request=httpx.Request("GET", "https://jira.example.com"),
        )

        client = JiraClient(jira_settings)
        with patch.object(
            client._client, "get", new_callable=AsyncMock, return_value=mock_response
        ) as mock_get:
            await client.search(["login"])

        call_kwargs = mock_get.call_args
        jql = call_kwargs.kwargs.get("params", {}).get("jql", "") or call_kwargs[1].get(
            "params", {}
        ).get("jql", "")
        assert "issuetype = Bug" in jql
        assert 'summary ~ "login"' in jql
        assert 'project = "PROJ"' in jql
        await client.close()

    async def test_search_handles_missing_fields(self, jira_settings) -> None:
        """Search handles issues with missing/null fields gracefully."""
        mock_response = httpx.Response(
            200,
            json={
                "issues": [
                    {
                        "key": "PROJ-789",
                        "fields": {
                            "summary": "Some issue",
                            "description": None,
                            "status": None,
                            "priority": None,
                        },
                    }
                ]
            },
            request=httpx.Request("GET", "https://jira.example.com"),
        )

        client = JiraClient(jira_settings)
        with patch.object(
            client._client, "get", new_callable=AsyncMock, return_value=mock_response
        ):
            candidates = await client.search(["test"])

        assert len(candidates) == 1
        assert candidates[0]["status"] == ""
        assert candidates[0]["priority"] == ""
        assert candidates[0]["description"] == ""
        await client.close()

    async def test_search_handles_adf_description(self, jira_settings) -> None:
        """Search extracts text from ADF (Cloud v3) descriptions."""
        mock_response = httpx.Response(
            200,
            json={
                "issues": [
                    {
                        "key": "PROJ-100",
                        "fields": {
                            "summary": "ADF test",
                            "description": {
                                "type": "doc",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [
                                            {
                                                "type": "text",
                                                "text": "ADF description text",
                                            },
                                        ],
                                    }
                                ],
                            },
                            "status": {"name": "Open"},
                            "priority": {"name": "High"},
                        },
                    }
                ]
            },
            request=httpx.Request("GET", "https://jira.example.com"),
        )

        client = JiraClient(jira_settings)
        with patch.object(
            client._client, "get", new_callable=AsyncMock, return_value=mock_response
        ):
            candidates = await client.search(["test"])

        assert candidates[0]["description"] == "ADF description text"
        await client.close()


class TestEnrichWithJiraMatches:
    """Tests for enrich_with_jira_matches."""

    async def test_skips_when_jira_disabled(self, product_bug_failure) -> None:
        """Does nothing when Jira is not configured."""
        env = {
            "JENKINS_URL": "https://jenkins.example.com",
            "JENKINS_USER": "testuser",
            "JENKINS_PASSWORD": "testpassword",  # pragma: allowlist secret
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings()

        await enrich_with_jira_matches([product_bug_failure], settings)
        assert product_bug_failure.analysis.product_bug_report.jira_matches == []

    async def test_skips_when_no_product_bugs(
        self, code_issue_failure, jira_settings
    ) -> None:
        """Does nothing when no PRODUCT BUG failures exist."""
        await enrich_with_jira_matches([code_issue_failure], jira_settings)

    async def test_skips_when_no_keywords(
        self, product_bug_no_keywords, jira_settings
    ) -> None:
        """Does nothing when PRODUCT BUG has no search keywords."""
        with patch("jenkins_job_insight.jira.JiraClient") as mock_client_cls:
            await enrich_with_jira_matches([product_bug_no_keywords], jira_settings)
            mock_client_cls.assert_not_called()

    async def test_enriches_with_ai_filtering(
        self, product_bug_failure, jira_settings
    ) -> None:
        """Searches Jira then uses AI to filter relevant matches."""
        mock_candidates = [
            {
                "key": "PROJ-100",
                "summary": "Login fails with 500",
                "description": "Auth service returns 500",
                "status": "Open",
                "priority": "High",
                "url": "https://jira.example.com/browse/PROJ-100",
            },
        ]
        mock_ai_matches = [
            JiraMatch(
                key="PROJ-100", summary="Login fails with 500", status="Open", score=0.9
            ),
        ]

        with patch("jenkins_job_insight.jira.JiraClient") as mock_client_cls:
            mock_instance = AsyncMock()
            mock_instance.search = AsyncMock(return_value=mock_candidates)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_instance

            with patch(
                "jenkins_job_insight.jira._filter_matches_with_ai",
                new_callable=AsyncMock,
                return_value=mock_ai_matches,
            ):
                await enrich_with_jira_matches(
                    [product_bug_failure], jira_settings, "claude", "test-model"
                )

        report = product_bug_failure.analysis.product_bug_report
        assert len(report.jira_matches) == 1
        assert report.jira_matches[0].key == "PROJ-100"
        assert report.jira_matches[0].score == 0.9

    async def test_fallback_without_ai_config(
        self, product_bug_failure, jira_settings
    ) -> None:
        """Returns all candidates when no AI provider is configured."""
        mock_candidates = [
            {
                "key": "PROJ-200",
                "summary": "Some bug",
                "description": "Details",
                "status": "Open",
                "priority": "Medium",
                "url": "https://jira.example.com/browse/PROJ-200",
            },
        ]

        with patch("jenkins_job_insight.jira.JiraClient") as mock_client_cls:
            mock_instance = AsyncMock()
            mock_instance.search = AsyncMock(return_value=mock_candidates)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_instance

            # No ai_provider/ai_model — should fall back
            await enrich_with_jira_matches([product_bug_failure], jira_settings)

        report = product_bug_failure.analysis.product_bug_report
        assert len(report.jira_matches) == 1
        assert report.jira_matches[0].key == "PROJ-200"
        assert report.jira_matches[0].score == 0.0

    async def test_deduplicates_by_keyword_set(self, jira_settings) -> None:
        """Same keyword set causes only one Jira search."""
        failure1 = FailureAnalysis(
            test_name="test_a",
            error="err",
            analysis=AnalysisDetail(
                classification="PRODUCT BUG",
                product_bug_report=ProductBugReport(
                    title="Bug A",
                    jira_search_keywords=["login", "auth"],
                ),
            ),
        )
        failure2 = FailureAnalysis(
            test_name="test_b",
            error="err",
            analysis=AnalysisDetail(
                classification="PRODUCT BUG",
                product_bug_report=ProductBugReport(
                    title="Bug B",
                    jira_search_keywords=["auth", "login"],
                ),
            ),
        )

        with patch("jenkins_job_insight.jira.JiraClient") as mock_client_cls:
            mock_instance = AsyncMock()
            mock_instance.search = AsyncMock(return_value=[])
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_instance

            await enrich_with_jira_matches([failure1, failure2], jira_settings)

            assert mock_instance.search.call_count == 1

    async def test_never_raises(self, product_bug_failure, jira_settings) -> None:
        """Jira errors are caught and logged, never raised."""
        with patch("jenkins_job_insight.jira.JiraClient") as mock_client_cls:
            mock_instance = AsyncMock()
            mock_instance.search = AsyncMock(
                side_effect=httpx.ConnectError("Connection refused")
            )
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_instance

            # Should not raise
            await enrich_with_jira_matches([product_bug_failure], jira_settings)

        assert product_bug_failure.analysis.product_bug_report.jira_matches == []
