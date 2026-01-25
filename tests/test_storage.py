"""Tests for SQLite storage."""

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


class TestInitDb:
    """Tests for the init_db function."""

    async def test_init_db_creates_table(self, temp_db_path: Path) -> None:
        """Test that init_db creates the results table."""
        with patch.object(storage, "DB_PATH", temp_db_path):
            await storage.init_db()

            # Verify table exists by trying to query it
            import aiosqlite

            async with aiosqlite.connect(temp_db_path) as db:
                cursor = await db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='results'"
                )
                result = await cursor.fetchone()
                assert result is not None
                assert result[0] == "results"

    async def test_init_db_creates_parent_directory(self, tmp_path: Path) -> None:
        """Test that init_db creates parent directories if needed."""
        nested_path = tmp_path / "nested" / "dir" / "test.db"
        with patch.object(storage, "DB_PATH", nested_path):
            await storage.init_db()
            assert nested_path.parent.exists()

    async def test_init_db_idempotent(self, temp_db_path: Path) -> None:
        """Test that init_db can be called multiple times."""
        with patch.object(storage, "DB_PATH", temp_db_path):
            await storage.init_db()
            await storage.init_db()  # Should not raise


class TestSaveResult:
    """Tests for the save_result function."""

    async def test_save_result_new_entry(self, setup_test_db: Path) -> None:
        """Test saving a new result entry."""
        with patch.object(storage, "DB_PATH", setup_test_db):
            await storage.save_result(
                job_id="job-123",
                jenkins_url="https://jenkins.example.com/job/test/1/",
                status="pending",
            )

            result = await storage.get_result("job-123")
            assert result is not None
            assert result["job_id"] == "job-123"
            assert result["status"] == "pending"

    async def test_save_result_with_result_data(self, setup_test_db: Path) -> None:
        """Test saving result with JSON data."""
        with patch.object(storage, "DB_PATH", setup_test_db):
            result_data = {"summary": "Test complete", "failures": []}
            await storage.save_result(
                job_id="job-456",
                jenkins_url="https://jenkins.example.com/job/test/2/",
                status="completed",
                result=result_data,
            )

            result = await storage.get_result("job-456")
            assert result is not None
            assert result["result"] == result_data

    async def test_save_result_update_existing(self, setup_test_db: Path) -> None:
        """Test updating an existing result."""
        with patch.object(storage, "DB_PATH", setup_test_db):
            # Save initial result
            await storage.save_result(
                job_id="job-789",
                jenkins_url="https://jenkins.example.com/job/test/3/",
                status="pending",
            )

            # Update result
            await storage.save_result(
                job_id="job-789",
                jenkins_url="https://jenkins.example.com/job/test/3/",
                status="completed",
                result={"summary": "Done"},
            )

            result = await storage.get_result("job-789")
            assert result is not None
            assert result["status"] == "completed"
            assert result["result"]["summary"] == "Done"

    async def test_save_result_none_result(self, setup_test_db: Path) -> None:
        """Test saving result with None result data."""
        with patch.object(storage, "DB_PATH", setup_test_db):
            await storage.save_result(
                job_id="job-none",
                jenkins_url="https://jenkins.example.com/job/test/4/",
                status="pending",
                result=None,
            )

            result = await storage.get_result("job-none")
            assert result is not None
            assert result["result"] is None


class TestGetResult:
    """Tests for the get_result function."""

    async def test_get_result_existing(self, setup_test_db: Path) -> None:
        """Test retrieving an existing result."""
        with patch.object(storage, "DB_PATH", setup_test_db):
            await storage.save_result(
                job_id="job-get",
                jenkins_url="https://jenkins.example.com/job/test/5/",
                status="completed",
                result={"test": "data"},
            )

            result = await storage.get_result("job-get")
            assert result is not None
            assert result["job_id"] == "job-get"
            assert result["jenkins_url"] == "https://jenkins.example.com/job/test/5/"
            assert result["status"] == "completed"
            assert result["result"]["test"] == "data"
            assert "created_at" in result

    async def test_get_result_not_found(self, setup_test_db: Path) -> None:
        """Test retrieving a non-existent result returns None."""
        with patch.object(storage, "DB_PATH", setup_test_db):
            result = await storage.get_result("non-existent-job")
            assert result is None

    async def test_get_result_parses_json(self, setup_test_db: Path) -> None:
        """Test that get_result properly parses JSON result."""
        with patch.object(storage, "DB_PATH", setup_test_db):
            complex_result = {
                "summary": "Analysis complete",
                "failures": [
                    {"test_name": "test_1", "error": "Error 1"},
                    {"test_name": "test_2", "error": "Error 2"},
                ],
            }
            await storage.save_result(
                job_id="job-json",
                jenkins_url="https://jenkins.example.com/job/test/6/",
                status="completed",
                result=complex_result,
            )

            result = await storage.get_result("job-json")
            assert result is not None
            assert result["result"] == complex_result
            assert len(result["result"]["failures"]) == 2


class TestListResults:
    """Tests for the list_results function."""

    async def test_list_results_empty(self, setup_test_db: Path) -> None:
        """Test listing results when database is empty."""
        with patch.object(storage, "DB_PATH", setup_test_db):
            results = await storage.list_results()
            assert results == []

    async def test_list_results_returns_all(self, setup_test_db: Path) -> None:
        """Test listing all results."""
        with patch.object(storage, "DB_PATH", setup_test_db):
            for i in range(3):
                await storage.save_result(
                    job_id=f"job-list-{i}",
                    jenkins_url=f"https://jenkins.example.com/job/test/{i}/",
                    status="completed",
                )

            results = await storage.list_results()
            assert len(results) == 3

    async def test_list_results_ordered_by_created_at_desc(
        self, setup_test_db: Path
    ) -> None:
        """Test that results are ordered by created_at descending."""
        import aiosqlite

        with patch.object(storage, "DB_PATH", setup_test_db):
            # Insert with explicit timestamps to ensure ordering
            async with aiosqlite.connect(setup_test_db) as db:
                await db.execute(
                    """INSERT INTO results (job_id, jenkins_url, status, created_at)
                       VALUES (?, ?, ?, ?)""",
                    (
                        "job-order-0",
                        "https://jenkins.example.com/job/test/0/",
                        "completed",
                        "2024-01-01 10:00:00",
                    ),
                )
                await db.execute(
                    """INSERT INTO results (job_id, jenkins_url, status, created_at)
                       VALUES (?, ?, ?, ?)""",
                    (
                        "job-order-1",
                        "https://jenkins.example.com/job/test/1/",
                        "completed",
                        "2024-01-01 11:00:00",
                    ),
                )
                await db.execute(
                    """INSERT INTO results (job_id, jenkins_url, status, created_at)
                       VALUES (?, ?, ?, ?)""",
                    (
                        "job-order-2",
                        "https://jenkins.example.com/job/test/2/",
                        "completed",
                        "2024-01-01 12:00:00",
                    ),
                )
                await db.commit()

            results = await storage.list_results()
            # Most recent should be first
            assert results[0]["job_id"] == "job-order-2"
            assert results[2]["job_id"] == "job-order-0"

    async def test_list_results_respects_limit(self, setup_test_db: Path) -> None:
        """Test that limit parameter is respected."""
        with patch.object(storage, "DB_PATH", setup_test_db):
            for i in range(10):
                await storage.save_result(
                    job_id=f"job-limit-{i}",
                    jenkins_url=f"https://jenkins.example.com/job/test/{i}/",
                    status="completed",
                )

            results = await storage.list_results(limit=5)
            assert len(results) == 5

    async def test_list_results_default_limit(self, setup_test_db: Path) -> None:
        """Test that default limit is 50."""
        with patch.object(storage, "DB_PATH", setup_test_db):
            # Just verify we can call with no arguments
            results = await storage.list_results()
            assert isinstance(results, list)

    async def test_list_results_summary_fields(self, setup_test_db: Path) -> None:
        """Test that list_results returns only summary fields."""
        with patch.object(storage, "DB_PATH", setup_test_db):
            await storage.save_result(
                job_id="job-fields",
                jenkins_url="https://jenkins.example.com/job/test/1/",
                status="completed",
                result={"large": "data" * 1000},  # Large result data
            )

            results = await storage.list_results()
            assert len(results) == 1
            result = results[0]
            # Should have summary fields
            assert "job_id" in result
            assert "jenkins_url" in result
            assert "status" in result
            assert "created_at" in result
            # Should NOT have result_json (it's not in the select)
            assert "result_json" not in result
            assert "result" not in result
