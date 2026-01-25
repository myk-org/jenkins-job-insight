"""SQLite storage for analysis results."""

import json
import os
from pathlib import Path

import aiosqlite
from simple_logger.logger import get_logger

logger = get_logger(name=__name__, level=os.environ.get("LOG_LEVEL", "INFO"))

DB_PATH = Path(os.getenv("DB_PATH", "/data/results.db"))


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
