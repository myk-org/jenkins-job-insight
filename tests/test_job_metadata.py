"""Tests for job metadata storage, API endpoints, and CLI commands."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from jenkins_job_insight import storage


@pytest.fixture
async def setup_test_db(temp_db_path: Path):
    """Set up a test database with the path patched."""
    with patch.object(storage, "DB_PATH", temp_db_path):
        await storage.init_db()
        yield temp_db_path


# --- Storage tests ---


class TestJobMetadataStorage:
    """Tests for job_metadata CRUD in storage.py."""

    async def test_set_and_get_metadata(self, setup_test_db: Path) -> None:
        with patch.object(storage, "DB_PATH", setup_test_db):
            result = await storage.set_job_metadata(
                "my-job",
                team="platform",
                tier="critical",
                version="v1.0",
                labels=["nightly", "smoke"],
            )
            assert result["job_name"] == "my-job"
            assert result["team"] == "platform"
            assert result["labels"] == ["nightly", "smoke"]

            fetched = await storage.get_job_metadata("my-job")
            assert fetched is not None
            assert fetched["team"] == "platform"
            assert fetched["tier"] == "critical"
            assert fetched["labels"] == ["nightly", "smoke"]

    async def test_get_metadata_not_found(self, setup_test_db: Path) -> None:
        with patch.object(storage, "DB_PATH", setup_test_db):
            result = await storage.get_job_metadata("nonexistent")
            assert result is None

    async def test_update_metadata(self, setup_test_db: Path) -> None:
        with patch.object(storage, "DB_PATH", setup_test_db):
            await storage.set_job_metadata("my-job", team="alpha")
            await storage.set_job_metadata("my-job", team="beta", tier="low")
            fetched = await storage.get_job_metadata("my-job")
            assert fetched is not None
            assert fetched["team"] == "beta"
            assert fetched["tier"] == "low"

    async def test_delete_metadata(self, setup_test_db: Path) -> None:
        with patch.object(storage, "DB_PATH", setup_test_db):
            await storage.set_job_metadata("my-job", team="platform")
            deleted = await storage.delete_job_metadata("my-job")
            assert deleted is True
            assert await storage.get_job_metadata("my-job") is None

    async def test_delete_metadata_not_found(self, setup_test_db: Path) -> None:
        with patch.object(storage, "DB_PATH", setup_test_db):
            deleted = await storage.delete_job_metadata("nonexistent")
            assert deleted is False

    async def test_list_all_metadata(self, setup_test_db: Path) -> None:
        with patch.object(storage, "DB_PATH", setup_test_db):
            await storage.set_job_metadata("job-a", team="alpha")
            await storage.set_job_metadata("job-b", team="beta")
            await storage.set_job_metadata("job-c", team="alpha")

            all_items = await storage.list_jobs_with_metadata()
            assert len(all_items) == 3

    async def test_list_filter_by_team(self, setup_test_db: Path) -> None:
        with patch.object(storage, "DB_PATH", setup_test_db):
            await storage.set_job_metadata("job-a", team="alpha")
            await storage.set_job_metadata("job-b", team="beta")
            await storage.set_job_metadata("job-c", team="alpha")

            filtered = await storage.list_jobs_with_metadata(team="alpha")
            assert len(filtered) == 2
            assert all(j["team"] == "alpha" for j in filtered)

    async def test_list_filter_by_tier(self, setup_test_db: Path) -> None:
        with patch.object(storage, "DB_PATH", setup_test_db):
            await storage.set_job_metadata("job-a", tier="critical")
            await storage.set_job_metadata("job-b", tier="low")

            filtered = await storage.list_jobs_with_metadata(tier="critical")
            assert len(filtered) == 1
            assert filtered[0]["job_name"] == "job-a"

    async def test_list_filter_by_version(self, setup_test_db: Path) -> None:
        with patch.object(storage, "DB_PATH", setup_test_db):
            await storage.set_job_metadata("job-a", version="v1.0")
            await storage.set_job_metadata("job-b", version="v2.0")

            filtered = await storage.list_jobs_with_metadata(version="v1.0")
            assert len(filtered) == 1
            assert filtered[0]["job_name"] == "job-a"

    async def test_list_filter_by_labels(self, setup_test_db: Path) -> None:
        with patch.object(storage, "DB_PATH", setup_test_db):
            await storage.set_job_metadata("job-a", labels=["nightly", "smoke"])
            await storage.set_job_metadata("job-b", labels=["nightly"])
            await storage.set_job_metadata("job-c", labels=["regression"])

            # Filter by single label
            filtered = await storage.list_jobs_with_metadata(labels=["nightly"])
            assert len(filtered) == 2

            # Filter by multiple labels (AND logic)
            filtered = await storage.list_jobs_with_metadata(
                labels=["nightly", "smoke"]
            )
            assert len(filtered) == 1
            assert filtered[0]["job_name"] == "job-a"

    async def test_list_filter_combined(self, setup_test_db: Path) -> None:
        with patch.object(storage, "DB_PATH", setup_test_db):
            await storage.set_job_metadata(
                "job-a", team="alpha", tier="critical", labels=["nightly"]
            )
            await storage.set_job_metadata(
                "job-b", team="alpha", tier="low", labels=["nightly"]
            )
            await storage.set_job_metadata(
                "job-c", team="beta", tier="critical", labels=["nightly"]
            )

            filtered = await storage.list_jobs_with_metadata(
                team="alpha", tier="critical"
            )
            assert len(filtered) == 1
            assert filtered[0]["job_name"] == "job-a"

    async def test_bulk_set_metadata(self, setup_test_db: Path) -> None:
        with patch.object(storage, "DB_PATH", setup_test_db):
            items = [
                {"job_name": "job-a", "team": "alpha", "labels": ["smoke"]},
                {"job_name": "job-b", "team": "beta", "tier": "critical"},
            ]
            result = await storage.bulk_set_metadata(items)
            assert result["updated"] == 2

            a = await storage.get_job_metadata("job-a")
            assert a is not None
            assert a["team"] == "alpha"
            assert a["labels"] == ["smoke"]

            b = await storage.get_job_metadata("job-b")
            assert b is not None
            assert b["team"] == "beta"
            assert b["tier"] == "critical"

    async def test_metadata_with_none_fields(self, setup_test_db: Path) -> None:
        with patch.object(storage, "DB_PATH", setup_test_db):
            await storage.set_job_metadata("my-job", team="alpha")
            fetched = await storage.get_job_metadata("my-job")
            assert fetched is not None
            assert fetched["team"] == "alpha"
            assert fetched["tier"] is None
            assert fetched["version"] is None
            assert fetched["labels"] == []

    async def test_metadata_empty_labels(self, setup_test_db: Path) -> None:
        with patch.object(storage, "DB_PATH", setup_test_db):
            await storage.set_job_metadata("my-job", labels=[])
            fetched = await storage.get_job_metadata("my-job")
            assert fetched is not None
            assert fetched["labels"] == []


# --- API endpoint tests ---


@pytest.fixture
def mock_settings():
    env = {
        "JENKINS_URL": "https://jenkins.example.com",
        "JENKINS_USER": "testuser",
        "JENKINS_PASSWORD": "testpassword",  # pragma: allowlist secret
        "GEMINI_API_KEY": "test-key",  # pragma: allowlist secret
    }
    with patch.dict(os.environ, env, clear=True):
        from jenkins_job_insight.config import get_settings

        get_settings.cache_clear()
        try:
            yield
        finally:
            get_settings.cache_clear()


@pytest.fixture
def api_client(mock_settings, temp_db_path: Path):
    with patch.object(storage, "DB_PATH", temp_db_path):
        from starlette.testclient import TestClient
        from jenkins_job_insight.main import app

        with TestClient(app) as client:
            yield client


class TestJobMetadataAPI:
    """Tests for job metadata API endpoints."""

    def test_set_and_get_metadata(self, api_client) -> None:
        resp = api_client.put(
            "/api/jobs/my-job/metadata",
            json={"team": "platform", "tier": "critical", "labels": ["smoke"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_name"] == "my-job"
        assert data["team"] == "platform"

        resp = api_client.get("/api/jobs/my-job/metadata")
        assert resp.status_code == 200
        assert resp.json()["team"] == "platform"

    def test_get_metadata_not_found(self, api_client) -> None:
        resp = api_client.get("/api/jobs/nonexistent/metadata")
        assert resp.status_code == 404

    def test_delete_metadata(self, api_client) -> None:
        api_client.put("/api/jobs/my-job/metadata", json={"team": "alpha"})
        resp = api_client.delete("/api/jobs/my-job/metadata")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

        resp = api_client.get("/api/jobs/my-job/metadata")
        assert resp.status_code == 404

    def test_delete_metadata_not_found(self, api_client) -> None:
        resp = api_client.delete("/api/jobs/nonexistent/metadata")
        assert resp.status_code == 404

    def test_list_metadata(self, api_client) -> None:
        api_client.put("/api/jobs/job-a/metadata", json={"team": "alpha"})
        api_client.put("/api/jobs/job-b/metadata", json={"team": "beta"})

        resp = api_client.get("/api/jobs/metadata")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    def test_list_metadata_filter_by_team(self, api_client) -> None:
        api_client.put("/api/jobs/job-a/metadata", json={"team": "alpha"})
        api_client.put("/api/jobs/job-b/metadata", json={"team": "beta"})

        resp = api_client.get("/api/jobs/metadata", params={"team": "alpha"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["team"] == "alpha"

    def test_list_metadata_filter_by_label(self, api_client) -> None:
        api_client.put(
            "/api/jobs/job-a/metadata",
            json={"labels": ["nightly", "smoke"]},
        )
        api_client.put(
            "/api/jobs/job-b/metadata",
            json={"labels": ["nightly"]},
        )

        resp = api_client.get(
            "/api/jobs/metadata", params={"label": ["nightly", "smoke"]}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["job_name"] == "job-a"

    def test_bulk_import(self, api_client) -> None:
        resp = api_client.put(
            "/api/jobs/metadata/bulk",
            json={
                "items": [
                    {"job_name": "job-a", "team": "alpha"},
                    {"job_name": "job-b", "team": "beta", "labels": ["ci"]},
                ]
            },
        )
        assert resp.status_code == 200
        assert resp.json()["updated"] == 2

        resp = api_client.get("/api/jobs/job-b/metadata")
        assert resp.status_code == 200
        assert resp.json()["labels"] == ["ci"]

    def test_dashboard_filtered_no_filters(self, api_client) -> None:
        resp = api_client.get("/api/dashboard/filtered")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_dashboard_filtered_with_team(self, api_client) -> None:
        # Set metadata for a job
        api_client.put("/api/jobs/my-job/metadata", json={"team": "alpha"})

        resp = api_client.get("/api/dashboard/filtered", params={"team": "alpha"})
        assert resp.status_code == 200
        data = resp.json()
        # Even if no analysis results, the response should be a list
        assert isinstance(data, list)

    def test_folder_style_job_name(self, api_client) -> None:
        """Test that folder-style job names (with /) work correctly."""
        resp = api_client.put(
            "/api/jobs/folder/subfolder/my-job/metadata",
            json={"team": "platform"},
        )
        assert resp.status_code == 200
        assert resp.json()["job_name"] == "folder/subfolder/my-job"

        resp = api_client.get("/api/jobs/folder/subfolder/my-job/metadata")
        assert resp.status_code == 200
        assert resp.json()["team"] == "platform"
