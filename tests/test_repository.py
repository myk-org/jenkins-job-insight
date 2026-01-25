"""Tests for repository management."""

from unittest.mock import MagicMock, patch

import git.exc
import pytest

from jenkins_job_insight.repository import RepositoryManager


class TestRepositoryManager:
    """Tests for the RepositoryManager class."""

    def test_init_empty_temp_dirs(self) -> None:
        """Test that RepositoryManager initializes with empty temp_dirs list."""
        manager = RepositoryManager()
        assert manager.temp_dirs == []

    @patch("jenkins_job_insight.repository.Repo")
    def test_clone_creates_temp_directory(self, mock_repo: MagicMock) -> None:
        """Test that clone creates a temporary directory."""
        manager = RepositoryManager()
        repo_url = "https://github.com/example/repo"

        result = manager.clone(repo_url)

        assert result.exists()
        assert len(manager.temp_dirs) == 1
        assert manager.temp_dirs[0] == result
        mock_repo.clone_from.assert_called_once()

        # Cleanup
        manager.cleanup()

    @patch("jenkins_job_insight.repository.Repo")
    def test_clone_with_custom_depth(self, mock_repo: MagicMock) -> None:
        """Test that clone passes correct depth parameter."""
        manager = RepositoryManager()
        repo_url = "https://github.com/example/repo"
        depth = 100

        manager.clone(repo_url, depth=depth)

        mock_repo.clone_from.assert_called_once()
        call_kwargs = mock_repo.clone_from.call_args
        assert call_kwargs[1]["depth"] == depth

        # Cleanup
        manager.cleanup()

    @patch("jenkins_job_insight.repository.Repo")
    def test_clone_multiple_repos(self, mock_repo: MagicMock) -> None:
        """Test cloning multiple repositories."""
        manager = RepositoryManager()

        path1 = manager.clone("https://github.com/example/repo1")
        path2 = manager.clone("https://github.com/example/repo2")

        assert len(manager.temp_dirs) == 2
        assert path1 != path2
        assert path1 in manager.temp_dirs
        assert path2 in manager.temp_dirs
        assert mock_repo.clone_from.call_count == 2

        # Cleanup
        manager.cleanup()

    @patch("jenkins_job_insight.repository.Repo")
    def test_cleanup_removes_directories(self, _mock_repo: MagicMock) -> None:
        """Test that cleanup removes all temporary directories."""
        manager = RepositoryManager()

        path1 = manager.clone("https://github.com/example/repo1")
        path2 = manager.clone("https://github.com/example/repo2")

        # Directories should exist before cleanup
        assert path1.exists()
        assert path2.exists()

        manager.cleanup()

        # Directories should be removed after cleanup
        assert not path1.exists()
        assert not path2.exists()
        assert manager.temp_dirs == []

    @patch("jenkins_job_insight.repository.Repo")
    def test_cleanup_handles_missing_directory(self, _mock_repo: MagicMock) -> None:
        """Test that cleanup handles already deleted directories gracefully."""
        manager = RepositoryManager()

        path = manager.clone("https://github.com/example/repo")

        # Manually delete the directory
        path.rmdir()

        # Cleanup should not raise an error
        manager.cleanup()
        assert manager.temp_dirs == []

    @patch("jenkins_job_insight.repository.Repo")
    def test_context_manager_enter(self, _mock_repo: MagicMock) -> None:
        """Test context manager __enter__ returns self."""
        manager = RepositoryManager()

        with manager as ctx:
            assert ctx is manager

    @patch("jenkins_job_insight.repository.Repo")
    def test_context_manager_cleanup_on_exit(self, _mock_repo: MagicMock) -> None:
        """Test context manager cleans up on exit."""
        path = None
        with RepositoryManager() as manager:
            path = manager.clone("https://github.com/example/repo")
            assert path.exists()

        # Directory should be cleaned up after context manager exits
        assert not path.exists()

    @patch("jenkins_job_insight.repository.Repo")
    def test_context_manager_cleanup_on_exception(self, _mock_repo: MagicMock) -> None:
        """Test context manager cleans up even when exception occurs."""
        path = None
        try:
            with RepositoryManager() as manager:
                path = manager.clone("https://github.com/example/repo")
                raise ValueError("Test exception")
        except ValueError:
            pass

        # Directory should be cleaned up after exception
        assert path is not None
        assert not path.exists()

    @patch("jenkins_job_insight.repository.Repo")
    def test_clone_uses_jenkins_insight_prefix(self, _mock_repo: MagicMock) -> None:
        """Test that cloned directories are under jenkins-insight base path."""
        manager = RepositoryManager()

        path = manager.clone("https://github.com/example/repo")

        # The path should be under the jenkins-insight base directory
        assert "jenkins-insight" in str(path)
        assert path.parent.name == "jenkins-insight"

        # Cleanup
        manager.cleanup()

    @patch("jenkins_job_insight.repository.Repo")
    def test_clone_real_failure_handling(self, mock_repo: MagicMock) -> None:
        """Test that clone raises error for invalid repository."""
        mock_repo.clone_from.side_effect = git.exc.GitCommandError("clone", 128)
        manager = RepositoryManager()

        with pytest.raises(git.exc.GitCommandError):
            manager.clone("https://invalid-url-that-does-not-exist.example.com/repo")

        # Even on failure, cleanup should work
        manager.cleanup()
