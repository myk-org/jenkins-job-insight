"""SQLite storage for analysis results."""

import json
import os
from pathlib import Path

import aiosqlite
from simple_logger.logger import get_logger

logger = get_logger(name=__name__, level=os.environ.get("LOG_LEVEL", "INFO"))

DB_PATH = Path(os.getenv("DB_PATH", "/data/results.db"))
REPORTS_DIR = DB_PATH.parent / "reports"


async def init_db() -> None:
    """Initialize the database schema.

    Creates the results table if it does not exist.
    """
    logger.info(f"Initializing database at {DB_PATH}")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS results (
                job_id TEXT PRIMARY KEY,
                jenkins_url TEXT,
                status TEXT,
                result_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                test_name TEXT NOT NULL,
                child_job_name TEXT NOT NULL DEFAULT '',
                child_build_number INTEGER NOT NULL DEFAULT 0,
                comment TEXT NOT NULL,
                error_signature TEXT NOT NULL DEFAULT '',
                username TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_comments_job_id ON comments (job_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_comments_test_name ON comments (test_name)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_comments_error_signature ON comments (error_signature)"
        )
        await db.execute("""
            CREATE TABLE IF NOT EXISTS failure_reviews (
                job_id TEXT NOT NULL,
                test_name TEXT NOT NULL,
                child_job_name TEXT NOT NULL DEFAULT '',
                child_build_number INTEGER NOT NULL DEFAULT 0,
                reviewed BOOLEAN DEFAULT 0,
                username TEXT NOT NULL DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (job_id, test_name, child_job_name, child_build_number)
            )
        """)

        # Migration: add child_build_number to existing tables
        # (needed when upgrading from versions without this column)
        logger.info("Running database migrations...")
        for table in ("comments", "failure_reviews"):
            cursor = await db.execute(f"PRAGMA table_info({table})")
            columns = {row[1] for row in await cursor.fetchall()}
            if "child_build_number" not in columns:
                await db.execute(
                    f"ALTER TABLE {table} ADD COLUMN child_build_number INTEGER NOT NULL DEFAULT 0"
                )
                logger.info(f"Migration: added child_build_number column to {table}")
            else:
                logger.debug(
                    f"Migration: {table} already has child_build_number column"
                )

        # Migration: add username to comments and failure_reviews
        for table in ("comments", "failure_reviews"):
            cursor = await db.execute(f"PRAGMA table_info({table})")
            columns = {row[1] for row in await cursor.fetchall()}
            if "username" not in columns:
                await db.execute(
                    f"ALTER TABLE {table} ADD COLUMN username TEXT NOT NULL DEFAULT ''"
                )
                logger.info(f"Migration: added username column to {table}")

        # Migration: add error_signature to comments table
        cursor = await db.execute("PRAGMA table_info(comments)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "error_signature" not in columns:
            await db.execute(
                "ALTER TABLE comments ADD COLUMN error_signature TEXT NOT NULL DEFAULT ''"
            )
            logger.info("Migration: added error_signature column to comments")
        else:
            logger.debug("Migration: comments already has error_signature column")

        # Migration: rebuild failure_reviews with correct 4-column PRIMARY KEY
        # ALTER TABLE cannot change PKs in SQLite, so we need a full rebuild
        cursor = await db.execute("PRAGMA table_info(failure_reviews)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "child_build_number" in columns:
            # Check if PK includes child_build_number by inspecting table SQL
            cursor = await db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='failure_reviews'"
            )
            create_sql = (await cursor.fetchone())[0]
            if (
                "child_build_number" not in create_sql.split("PRIMARY KEY")[1]
                if "PRIMARY KEY" in create_sql
                else ""
            ):
                logger.info(
                    "Migration: rebuilding failure_reviews table with 4-column PRIMARY KEY"
                )
                await db.execute(
                    "ALTER TABLE failure_reviews RENAME TO failure_reviews_old"
                )
                await db.execute("""
                    CREATE TABLE failure_reviews (
                        job_id TEXT NOT NULL,
                        test_name TEXT NOT NULL,
                        child_job_name TEXT NOT NULL DEFAULT '',
                        child_build_number INTEGER NOT NULL DEFAULT 0,
                        reviewed BOOLEAN DEFAULT 0,
                        username TEXT NOT NULL DEFAULT '',
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (job_id, test_name, child_job_name, child_build_number)
                    )
                """)
                await db.execute("""
                    INSERT INTO failure_reviews (job_id, test_name, child_job_name, child_build_number, reviewed, username, updated_at)
                    SELECT job_id, test_name, child_job_name, child_build_number, reviewed, COALESCE(username, ''), updated_at
                    FROM failure_reviews_old
                """)
                await db.execute("DROP TABLE failure_reviews_old")
                logger.info("Migration: failure_reviews table rebuilt successfully")

        await db.commit()


def _validate_child_identifier_pairing(
    child_job_name: str, child_build_number: int
) -> None:
    """Validate that child_job_name and child_build_number are either both set or both empty."""
    if child_build_number < 0:
        raise ValueError("child_build_number must not be negative")
    if child_job_name and child_build_number <= 0:
        raise ValueError(
            "child_build_number must be positive when child_job_name is set"
        )
    if not child_job_name and child_build_number > 0:
        raise ValueError("child_job_name is required when child_build_number is set")


async def add_comment(
    job_id: str,
    test_name: str,
    comment: str,
    child_job_name: str = "",
    child_build_number: int = 0,
    error_signature: str = "",
    username: str = "",
) -> int:
    """Add a comment to a test failure."""
    _validate_child_identifier_pairing(child_job_name, child_build_number)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO comments (job_id, test_name, child_job_name, child_build_number, comment, error_signature, username) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                job_id,
                test_name,
                child_job_name,
                child_build_number,
                comment,
                error_signature,
                username,
            ),
        )
        await db.commit()
        return cursor.lastrowid


async def get_comments_for_job(job_id: str) -> list[dict]:
    """Get all comments for a specific job."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, job_id, test_name, child_job_name, child_build_number, comment, error_signature, username, created_at "
            "FROM comments WHERE job_id = ? ORDER BY created_at ASC",
            (job_id,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def set_reviewed(
    job_id: str,
    test_name: str,
    reviewed: bool,
    child_job_name: str = "",
    child_build_number: int = 0,
    username: str = "",
) -> None:
    """Set or update the reviewed state for a test failure."""
    _validate_child_identifier_pairing(child_job_name, child_build_number)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO failure_reviews (job_id, test_name, child_job_name, child_build_number, reviewed, username, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (job_id, test_name, child_job_name, child_build_number, reviewed, username),
        )
        await db.commit()


async def get_reviews_for_job(job_id: str) -> dict[str, dict]:
    """Get all review states for a specific job."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT test_name, child_job_name, child_build_number, reviewed, username, updated_at "
            "FROM failure_reviews WHERE job_id = ?",
            (job_id,),
        )
        rows = await cursor.fetchall()
        result = {}
        for row in rows:
            if row["child_job_name"] != "":
                key = f"{row['child_job_name']}#{row['child_build_number']}::{row['test_name']}"
            else:
                key = row["test_name"]
            result[key] = {
                "reviewed": bool(row["reviewed"]),
                "username": row["username"],
                "updated_at": row["updated_at"],
            }
        return result


async def get_review_status(job_id: str) -> dict:
    """Get review summary for a job (used by dashboard)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT result_json FROM results WHERE job_id = ?", (job_id,)
        )
        row = await cursor.fetchone()
        total_failures = 0
        if row and row[0]:
            try:
                result_data = json.loads(row[0])
                total_failures = count_all_failures(result_data)
            except (json.JSONDecodeError, TypeError, AttributeError):
                total_failures = 0

        cursor = await db.execute(
            "SELECT COUNT(*) FROM failure_reviews WHERE job_id = ? AND reviewed = 1",
            (job_id,),
        )
        reviewed_count = (await cursor.fetchone())[0]

        cursor = await db.execute(
            "SELECT COUNT(*) FROM comments WHERE job_id = ?", (job_id,)
        )
        comment_count = (await cursor.fetchone())[0]

        return {
            "total_failures": total_failures,
            "reviewed_count": reviewed_count,
            "comment_count": comment_count,
        }


async def get_historical_comments(
    test_names: list[str] | None = None,
    error_signatures: list[str] | None = None,
    exclude_job_id: str | None = None,
) -> list[dict]:
    """Get historical comments for similar failures across jobs.

    Matches by test name OR by error signature.
    No arbitrary limit -- returns all matching comments.
    """
    conditions: list[str] = []
    params: list[str] = []

    if test_names:
        placeholders = ",".join("?" for _ in test_names)
        conditions.append(f"test_name IN ({placeholders})")
        params.extend(test_names)

    if error_signatures:
        placeholders = ",".join("?" for _ in error_signatures)
        conditions.append(f"error_signature IN ({placeholders})")
        params.extend(error_signatures)

    if not conditions:
        return []

    where = " OR ".join(conditions)
    if exclude_job_id:
        where = f"({where}) AND job_id != ?"
        params.append(exclude_job_id)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"SELECT id, job_id, test_name, child_job_name, child_build_number, comment, error_signature, username, created_at "
            f"FROM comments WHERE {where} ORDER BY created_at DESC",
            params,
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def save_result(
    job_id: str,
    jenkins_url: str,
    status: str,
    result: dict | None = None,
) -> None:
    """Save or update an analysis result.

    Args:
        job_id: Unique identifier for the analysis job.
        jenkins_url: URL of the analyzed Jenkins build.
        status: Current status of the analysis.
        result: Optional result data to store.
    """
    logger.debug(f"Saving result for job_id: {job_id} (status: {status})")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO results (job_id, jenkins_url, status, result_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                job_id,
                jenkins_url,
                status,
                json.dumps(result) if result is not None else None,
            ),
        )
        await db.commit()


async def update_status(
    job_id: str,
    status: str,
    result: dict | None = None,
) -> None:
    """Update the status of an existing analysis result.

    Unlike save_result, this uses UPDATE to preserve the original created_at timestamp.
    Only updates result_json when result is explicitly provided.

    Args:
        job_id: Unique identifier for the analysis job.
        status: New status for the analysis.
        result: Optional result data to store. When None, result_json is not modified.
    """
    logger.debug(f"Updating status for job_id: {job_id} (status: {status})")
    async with aiosqlite.connect(DB_PATH) as db:
        if result is not None:
            cursor = await db.execute(
                """
                UPDATE results SET status = ?, result_json = ?
                WHERE job_id = ?
                """,
                (status, json.dumps(result), job_id),
            )
        else:
            cursor = await db.execute(
                """
                UPDATE results SET status = ?
                WHERE job_id = ?
                """,
                (status, job_id),
            )
        if cursor.rowcount == 0:
            logger.warning(f"update_status: no row found for job_id={job_id}")
        await db.commit()


async def get_result(job_id: str) -> dict | None:
    """Retrieve an analysis result by job ID.

    Args:
        job_id: Unique identifier for the analysis job.

    Returns:
        Result dictionary if found, None otherwise.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM results WHERE job_id = ?",
            (job_id,),
        )
        row = await cursor.fetchone()
        if row:
            return {
                "job_id": row["job_id"],
                "jenkins_url": row["jenkins_url"],
                "status": row["status"],
                "result": json.loads(row["result_json"])
                if row["result_json"]
                else None,
                "created_at": row["created_at"],
            }
        return None


async def list_results(limit: int = 50) -> list[dict]:
    """List recent analysis results.

    Args:
        limit: Maximum number of results to return.

    Returns:
        List of result summary dictionaries.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT job_id, jenkins_url, status, created_at
            FROM results
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


def count_all_failures(result_data: dict) -> int:
    """Count all failures including those in nested child job analyses.

    Walks the top-level ``failures`` list, then recursively counts failures in
    ``child_job_analyses`` (top-level key) and ``failed_children`` (nested key
    inside each child).

    Args:
        result_data: Parsed result dictionary from result_json.

    Returns:
        Total number of failures across all levels.
    """
    count = len(result_data.get("failures", []))
    for child in result_data.get("child_job_analyses", []):
        count += _count_child_failures_recursive(child)
    return count


def _count_child_failures_recursive(child: dict) -> int:
    """Recursively count failures in a child job analysis dict.

    Each child has a ``failures`` list and a ``failed_children`` list that can
    nest arbitrarily deep.

    Args:
        child: A single child job analysis dictionary.

    Returns:
        Total number of failures for this child and its descendants.
    """
    count = len(child.get("failures", []))
    for nested in child.get("failed_children", []):
        count += _count_child_failures_recursive(nested)
    return count


async def list_results_for_dashboard(limit: int = 500) -> list[dict]:
    """List recent analysis results with summary data for dashboard display.

    Unlike list_results, this function also extracts key fields from result_json
    for any row that has a stored result (job_name, build_number, failure_count).
    Returns at most ``limit`` results; pagination is handled client-side.

    Args:
        limit: Maximum number of results to return.

    Returns:
        List of result dictionaries enriched with summary data from result_json.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT r.job_id, r.jenkins_url, r.status, r.result_json, r.created_at,
                (SELECT COUNT(*) FROM failure_reviews fr
                 WHERE fr.job_id = r.job_id AND fr.reviewed = 1) AS reviewed_count,
                (SELECT COUNT(*) FROM comments c
                 WHERE c.job_id = r.job_id) AS comment_count
            FROM results r
            ORDER BY r.created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            entry: dict = {
                "job_id": row["job_id"],
                "jenkins_url": row["jenkins_url"],
                "status": row["status"],
                "created_at": row["created_at"],
                "reviewed_count": row["reviewed_count"],
                "comment_count": row["comment_count"],
            }
            if row["result_json"]:
                try:
                    result_data = json.loads(row["result_json"])
                    entry["job_name"] = result_data.get("job_name", "")
                    entry["build_number"] = result_data.get("build_number", "")
                    entry["failure_count"] = count_all_failures(result_data)
                    child_jobs = result_data.get("child_job_analyses", [])
                    if child_jobs:
                        entry["child_job_count"] = len(child_jobs)
                except (json.JSONDecodeError, TypeError, AttributeError):
                    logger.debug(f"Failed to parse result_json for job {row['job_id']}")
            results.append(entry)
        return results


async def save_html_report(job_id: str, html_content: str) -> Path:
    """Save an HTML report to disk.

    Args:
        job_id: Unique identifier for the analysis job.
        html_content: The HTML report content.

    Returns:
        Path to the saved HTML file.
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"{job_id}.html"
    report_path.write_text(html_content, encoding="utf-8")
    logger.debug(f"Saved HTML report for job_id: {job_id} at {report_path}")
    return report_path


async def get_html_report(job_id: str) -> str | None:
    """Read an HTML report from disk.

    Args:
        job_id: Unique identifier for the analysis job.

    Returns:
        HTML content as string, or None if not found.
    """
    report_path = REPORTS_DIR / f"{job_id}.html"
    if report_path.exists():
        return report_path.read_text(encoding="utf-8")
    return None
