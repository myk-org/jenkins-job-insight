"""Tests for output delivery."""

from unittest.mock import AsyncMock, patch

from jenkins_job_insight.models import AnalysisResult
from jenkins_job_insight.output import send_callback


class TestSendCallback:
    """Tests for the send_callback function."""

    async def test_send_callback_posts_result(
        self, sample_analysis_result: AnalysisResult
    ) -> None:
        """Test that send_callback posts result to callback URL."""
        with patch("jenkins_job_insight.output.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance

            await send_callback(
                "https://callback.example.com/webhook",
                sample_analysis_result,
            )

            mock_instance.post.assert_called_once()
            call_args = mock_instance.post.call_args
            assert call_args[0][0] == "https://callback.example.com/webhook"
            assert "json" in call_args[1]

    async def test_send_callback_with_headers(
        self, sample_analysis_result: AnalysisResult
    ) -> None:
        """Test that send_callback includes custom headers."""
        with patch("jenkins_job_insight.output.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance

            headers = {"Authorization": "Bearer token", "X-Custom": "value"}
            await send_callback(
                "https://callback.example.com/webhook",
                sample_analysis_result,
                headers=headers,
            )

            call_args = mock_instance.post.call_args
            assert call_args[1]["headers"] == headers

    async def test_send_callback_default_empty_headers(
        self, sample_analysis_result: AnalysisResult
    ) -> None:
        """Test that send_callback uses empty dict for None headers."""
        with patch("jenkins_job_insight.output.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance

            await send_callback(
                "https://callback.example.com/webhook",
                sample_analysis_result,
                headers=None,
            )

            call_args = mock_instance.post.call_args
            assert call_args[1]["headers"] == {}

    async def test_send_callback_timeout(
        self, sample_analysis_result: AnalysisResult
    ) -> None:
        """Test that send_callback sets timeout."""
        with patch("jenkins_job_insight.output.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance

            await send_callback(
                "https://callback.example.com/webhook",
                sample_analysis_result,
            )

            call_args = mock_instance.post.call_args
            assert call_args[1]["timeout"] == 30.0
