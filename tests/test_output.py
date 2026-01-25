"""Tests for output formatting and delivery."""

from unittest.mock import AsyncMock, patch

from jenkins_job_insight.models import (
    AnalysisResult,
    FailureAnalysis,
)
from jenkins_job_insight.output import (
    format_slack_message,
    send_callback,
    send_slack,
)


class TestFormatSlackMessage:
    """Tests for the format_slack_message function."""

    def test_format_slack_message_basic_structure(
        self, sample_analysis_result: AnalysisResult
    ) -> None:
        """Test that format_slack_message returns correct structure."""
        message = format_slack_message(sample_analysis_result)

        assert "blocks" in message
        assert isinstance(message["blocks"], list)
        assert len(message["blocks"]) > 0

    def test_format_slack_message_header(
        self, sample_analysis_result: AnalysisResult
    ) -> None:
        """Test that message includes header block."""
        message = format_slack_message(sample_analysis_result)

        header = message["blocks"][0]
        assert header["type"] == "header"
        assert header["text"]["type"] == "plain_text"
        assert "Jenkins Analysis Complete" in header["text"]["text"]

    def test_format_slack_message_contains_key_elements(
        self, sample_analysis_result: AnalysisResult
    ) -> None:
        """Test that Slack message contains key elements from the analysis result."""
        message = format_slack_message(sample_analysis_result)

        # Combine all section block text content
        combined_text = ""
        for block in message["blocks"]:
            if block["type"] == "section":
                # Remove code block markers
                block_text = block["text"]["text"].strip("`")
                combined_text += block_text

        # The slack message should contain key elements from the result
        assert str(sample_analysis_result.jenkins_url) in combined_text
        assert sample_analysis_result.summary in combined_text
        assert sample_analysis_result.status in combined_text
        assert sample_analysis_result.job_id in combined_text

    def test_format_slack_message_includes_job_url(
        self, sample_analysis_result: AnalysisResult
    ) -> None:
        """Test that message includes job URL."""
        message = format_slack_message(sample_analysis_result)

        # Find section with job URL
        section = message["blocks"][1]
        assert section["type"] == "section"
        assert str(sample_analysis_result.jenkins_url) in section["text"]["text"]

    def test_format_slack_message_includes_summary(
        self, sample_analysis_result: AnalysisResult
    ) -> None:
        """Test that message includes summary."""
        message = format_slack_message(sample_analysis_result)

        # Find section with summary - all text content is in section blocks
        all_text = ""
        for block in message["blocks"]:
            if block["type"] == "section":
                all_text += block["text"]["text"]

        assert sample_analysis_result.summary in all_text

    def test_format_slack_message_product_bug_label(
        self, sample_analysis_result: AnalysisResult
    ) -> None:
        """Test that analysis with PRODUCT BUG is included in message."""
        message = format_slack_message(sample_analysis_result)

        # Find section with failure - all content is in code blocks
        all_text = ""
        for block in message["blocks"]:
            if block["type"] == "section":
                all_text += block["text"]["text"]

        assert "PRODUCT BUG" in all_text

    def test_format_slack_message_code_issue_label(self) -> None:
        """Test that analysis with CODE ISSUE is included in message."""
        failure = FailureAnalysis(
            test_name="test_example",
            error="AssertionError",
            analysis="""=== CLASSIFICATION ===
CODE ISSUE

=== ANALYSIS ===
Test issue
""",
        )
        result = AnalysisResult(
            job_id="test-123",
            jenkins_url="https://jenkins.example.com/job/test/1/",
            status="completed",
            summary="1 code issue",
            failures=[failure],
        )

        message = format_slack_message(result)

        all_text = ""
        for block in message["blocks"]:
            if block["type"] == "section":
                all_text += block["text"]["text"]

        assert "CODE ISSUE" in all_text

    def test_format_slack_message_no_failures(self) -> None:
        """Test message formatting with no failures."""
        result = AnalysisResult(
            job_id="test-123",
            jenkins_url="https://jenkins.example.com/job/test/1/",
            status="completed",
            summary="No failures",
            failures=[],
        )

        message = format_slack_message(result)
        # Should have header + at least one section block with the text content
        assert len(message["blocks"]) >= 2
        assert message["blocks"][0]["type"] == "header"
        assert message["blocks"][1]["type"] == "section"

    def test_format_slack_message_multiple_failures(self) -> None:
        """Test message formatting with multiple failures."""
        failures = [
            FailureAnalysis(
                test_name=f"test_{i}",
                error=f"Error {i}",
                analysis=f"""=== CLASSIFICATION ===
{"CODE ISSUE" if i % 2 == 0 else "PRODUCT BUG"}

=== ANALYSIS ===
Explanation {i}
""",
            )
            for i in range(3)
        ]
        result = AnalysisResult(
            job_id="test-123",
            jenkins_url="https://jenkins.example.com/job/test/1/",
            status="completed",
            summary="3 failures",
            failures=failures,
        )

        message = format_slack_message(result)

        # Collect all text content
        all_text = ""
        for block in message["blocks"]:
            if block["type"] == "section":
                all_text += block["text"]["text"]

        # All failures should be present
        for i in range(3):
            assert f"test_{i}" in all_text
            assert f"Error {i}" in all_text

    def test_format_slack_message_uses_code_blocks(self) -> None:
        """Test that Slack message uses code blocks for content."""
        result = AnalysisResult(
            job_id="test-123",
            jenkins_url="https://jenkins.example.com/job/test/1/",
            status="completed",
            summary="Test summary",
            failures=[],
        )

        message = format_slack_message(result)

        # Section blocks should contain code-formatted text
        for block in message["blocks"]:
            if block["type"] == "section":
                assert block["text"]["text"].startswith("```")
                assert block["text"]["text"].endswith("```")


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


class TestSendSlack:
    """Tests for the send_slack function."""

    async def test_send_slack_posts_formatted_message(
        self, sample_analysis_result: AnalysisResult
    ) -> None:
        """Test that send_slack posts formatted message."""
        with patch("jenkins_job_insight.output.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance

            await send_slack(
                "https://hooks.slack.com/services/xxx",
                sample_analysis_result,
            )

            mock_instance.post.assert_called_once()
            call_args = mock_instance.post.call_args
            assert call_args[0][0] == "https://hooks.slack.com/services/xxx"
            # Should post formatted message with blocks
            assert "blocks" in call_args[1]["json"]

    async def test_send_slack_timeout(
        self, sample_analysis_result: AnalysisResult
    ) -> None:
        """Test that send_slack sets timeout."""
        with patch("jenkins_job_insight.output.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance

            await send_slack(
                "https://hooks.slack.com/services/xxx",
                sample_analysis_result,
            )

            call_args = mock_instance.post.call_args
            assert call_args[1]["timeout"] == 30.0
