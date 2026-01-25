"""Git repository management for cloning and cleanup."""

import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Self

from git import Repo
from pydantic import HttpUrl
from simple_logger.logger import get_logger

logger = get_logger(name=__name__, level=os.environ.get("LOG_LEVEL", "INFO"))


class RepositoryManager:
    """Manages temporary git repository clones."""

    def __init__(self) -> None:
        """Initialize repository manager."""
        self.base_path = Path(tempfile.gettempdir()) / "jenkins-insight"
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.temp_dirs: list[Path] = []

    def clone(self, repo_url: str | HttpUrl, depth: int = 50) -> Path:
        """Clone repository to a unique temporary directory.

        Each clone gets a UUID-based directory to support parallel webhook calls.

        Args:
            repo_url: URL of the git repository to clone (string or HttpUrl).
            depth: Number of commits to fetch for git history context.

        Returns:
            Path to the cloned repository.

        Raises:
            ValueError: If repo_url uses an unsafe scheme (not https:// or git://).
        """
        # Validate URL scheme to prevent SSRF and local file access
        url_str = str(repo_url).lower()
        if not url_str.startswith(("https://", "git://")):
            raise ValueError(
                f"Invalid repository URL scheme. Only https:// and git:// are allowed, got: {repo_url}"
            )
        clone_id = str(uuid.uuid4())[:8]
        repo_name = str(repo_url).rstrip("/").split("/")[-1].replace(".git", "")
        clone_dir = self.base_path / f"{repo_name}-{clone_id}"
        clone_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dirs.append(clone_dir)
        logger.info(f"Cloning repository to {clone_dir}")
        Repo.clone_from(str(repo_url), clone_dir, depth=depth)
        return clone_dir

    def cleanup(self) -> None:
        """Remove all cloned repositories."""
        logger.debug("Cleaning up temporary directories")
        for temp_dir in self.temp_dirs:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
        self.temp_dirs.clear()

    def __enter__(self) -> Self:
        """Enter context manager."""
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: object,
    ) -> None:
        """Exit context manager and cleanup."""
        self.cleanup()
