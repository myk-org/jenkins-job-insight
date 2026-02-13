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
        await db.commit()


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
