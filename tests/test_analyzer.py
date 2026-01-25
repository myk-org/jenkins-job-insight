"""Tests for analyzer module."""

import jenkins
import pytest
from fastapi import HTTPException

from jenkins_job_insight.analyzer import handle_jenkins_exception


class TestHandleJenkinsException:
    """Tests for the handle_jenkins_exception function."""

    def test_handle_not_found_exception(self) -> None:
        """Test that NotFoundException returns 404."""
        exc = jenkins.NotFoundException("Job not found")
        with pytest.raises(HTTPException) as exc_info:
            handle_jenkins_exception(exc, "my-job", 123)
        assert exc_info.value.status_code == 404
        assert "my-job" in exc_info.value.detail
        assert "123" in exc_info.value.detail

    def test_handle_jenkins_exception_with_not_found_message(self) -> None:
        """Test that JenkinsException with 'not found' message returns 404."""
        exc = jenkins.JenkinsException("Job does not exist")
        with pytest.raises(HTTPException) as exc_info:
            handle_jenkins_exception(exc, "my-job", 456)
        assert exc_info.value.status_code == 404

    def test_handle_jenkins_exception_with_404_message(self) -> None:
        """Test that JenkinsException with '404' in message returns 404."""
        exc = jenkins.JenkinsException("Error 404: Resource not available")
        with pytest.raises(HTTPException) as exc_info:
            handle_jenkins_exception(exc, "my-job", 789)
        assert exc_info.value.status_code == 404

    def test_handle_jenkins_exception_unauthorized(self) -> None:
        """Test that unauthorized error returns 502 with auth message."""
        exc = jenkins.JenkinsException("401 Unauthorized")
        with pytest.raises(HTTPException) as exc_info:
            handle_jenkins_exception(exc, "my-job", 123)
        assert exc_info.value.status_code == 502
        assert "authentication failed" in exc_info.value.detail.lower()

    def test_handle_jenkins_exception_forbidden(self) -> None:
        """Test that forbidden error returns 502 with permission message."""
        exc = jenkins.JenkinsException("403 Forbidden")
        with pytest.raises(HTTPException) as exc_info:
            handle_jenkins_exception(exc, "my-job", 123)
        assert exc_info.value.status_code == 502
        assert "access denied" in exc_info.value.detail.lower()
        assert "my-job" in exc_info.value.detail

    def test_handle_jenkins_exception_generic(self) -> None:
        """Test that generic JenkinsException returns 502 with error details."""
        exc = jenkins.JenkinsException("Connection timeout")
        with pytest.raises(HTTPException) as exc_info:
            handle_jenkins_exception(exc, "my-job", 123)
        assert exc_info.value.status_code == 502
        assert "Jenkins error" in exc_info.value.detail

    def test_handle_non_jenkins_exception(self) -> None:
        """Test that non-Jenkins exceptions return 502 with connection error."""
        exc = ConnectionError("Failed to connect")
        with pytest.raises(HTTPException) as exc_info:
            handle_jenkins_exception(exc, "my-job", 123)
        assert exc_info.value.status_code == 502
        assert "Failed to connect to Jenkins" in exc_info.value.detail
