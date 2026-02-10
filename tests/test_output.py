"""Tests for output formatting and delivery."""

from unittest.mock import AsyncMock, patch

from jenkins_job_insight.models import (
    AnalysisResult,
    FailureAnalysis,
    ResultMessage,
)
from jenkins_job_insight.output import (
    _chunk_text,
    build_result_messages,
    format_slack_message,
    send_callback,
    send_slack,
    MAX_MESSAGE_TEXT,
)


class TestChunkText:
    """Tests for the _chunk_text helper function."""

    def test_short_text_returns_single_message(self) -> None:
        """Test that text under max_size returns a single ResultMessage."""
        result = _chunk_text("short text", "summary")
        assert len(result) == 1
        assert result[0].type == "summary"
        assert result[0].text == "short text"

    def test_long_text_splits_on_line_boundaries(self) -> None:
        """Test that long text is split on line boundaries."""
        lines = [f"Line {i}: " + "x" * 50 for i in range(100)]
        text = "\n".join(lines)
        result = _chunk_text(text, "failure_detail", max_size=500)

        assert len(result) > 1
        for msg in result:
            assert msg.type == "failure_detail"
            assert len(msg.text) <= 500

    def test_preserves_message_type(self) -> None:
        """Test that message type is preserved across all chunks."""
        text = "\n".join(["x" * 100] * 50)
        result = _chunk_text(text, "child_job", max_size=500)

        for msg in result:
            assert msg.type == "child_job"

    def test_exact_boundary_text(self) -> None:
        """Test text exactly at max_size returns single message."""
        text = "x" * MAX_MESSAGE_TEXT
        result = _chunk_text(text, "summary")
        assert len(result) == 1

    def test_single_line_exceeding_max_size(self) -> None:
        """Test that a single line exceeding max_size produces one oversized chunk.

        The _chunk_text function splits on line boundaries. When a single line
        exceeds max_size, it cannot be split further and is emitted as-is.
        The downstream format_slack_message handles block-level splitting.
        """
        text = "x" * 1000
        result = _chunk_text(text, "summary", max_size=500)
        # Single line cannot be split on line boundaries
        assert len(result) == 1
        assert result[0].text == text


class TestBuildResultMessages:
    """Tests for the build_result_messages function."""

    def test_summary_always_present(
        self, sample_analysis_result: AnalysisResult
    ) -> None:
        """Test that summary message is always included."""
        messages = build_result_messages(sample_analysis_result)
        summary_msgs = [m for m in messages if m.type == "summary"]
        assert len(summary_msgs) >= 1

    def test_summary_contains_key_elements(
        self, sample_analysis_result: AnalysisResult
    ) -> None:
        """Test that summary message contains key elements."""
        messages = build_result_messages(sample_analysis_result)
        summary_msgs = [m for m in messages if m.type == "summary"]
        summary_text = "\n".join(m.text for m in summary_msgs)

        assert str(sample_analysis_result.jenkins_url) in summary_text
        assert sample_analysis_result.status in summary_text
        assert sample_analysis_result.job_id in summary_text
        assert sample_analysis_result.summary in summary_text

    def test_failure_detail_messages(
        self, sample_analysis_result: AnalysisResult
    ) -> None:
        """Test that failure detail messages are created."""
        messages = build_result_messages(sample_analysis_result)
        failure_msgs = [m for m in messages if m.type == "failure_detail"]
        assert len(failure_msgs) >= 1

    def test_failure_detail_contains_analysis(
        self, sample_analysis_result: AnalysisResult
    ) -> None:
        """Test that failure detail contains PRODUCT BUG analysis."""
        messages = build_result_messages(sample_analysis_result)
        failure_msgs = [m for m in messages if m.type == "failure_detail"]
        all_failure_text = "\n".join(m.text for m in failure_msgs)
        assert "PRODUCT BUG" in all_failure_text

    def test_no_failures_no_failure_messages(self) -> None:
        """Test that no failure messages when there are no failures."""
        result = AnalysisResult(
            job_id="test-123",
            jenkins_url="https://jenkins.example.com/job/test/1/",
            status="completed",
            summary="No failures",
            failures=[],
        )
        messages = build_result_messages(result)
        failure_msgs = [m for m in messages if m.type == "failure_detail"]
        assert len(failure_msgs) == 0

    def test_multiple_failure_groups(self) -> None:
        """Test that each unique failure group gets its own message."""
        failures = [
            FailureAnalysis(
                test_name=f"test_{i}",
                error=f"Error {i}",
                analysis=f"Analysis {i}",
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
        messages = build_result_messages(result)
        failure_msgs = [m for m in messages if m.type == "failure_detail"]
        # 3 unique analyses should produce 3 failure messages
        assert len(failure_msgs) == 3

    def test_deduplicated_failures_grouped(self) -> None:
        """Test that failures with same analysis are grouped together."""
        failures = [
            FailureAnalysis(
                test_name=f"test_{i}",
                error="Same error",
                analysis="Same analysis text",
            )
            for i in range(3)
        ]
        result = AnalysisResult(
            job_id="test-123",
            jenkins_url="https://jenkins.example.com/job/test/1/",
            status="completed",
            summary="3 failures, 1 group",
            failures=failures,
        )
        messages = build_result_messages(result)
        failure_msgs = [m for m in messages if m.type == "failure_detail"]
        # All 3 share the same analysis, so 1 group
        assert len(failure_msgs) == 1
        assert "3 test(s) with same error" in failure_msgs[0].text

    def test_ai_provider_info_in_summary(self) -> None:
        """Test that AI provider info is included in summary."""
        result = AnalysisResult(
            job_id="test-123",
            jenkins_url="https://jenkins.example.com/job/test/1/",
            status="completed",
            summary="No failures",
            failures=[],
        )
        messages = build_result_messages(result, ai_provider="claude", ai_model="opus")
        summary_msgs = [m for m in messages if m.type == "summary"]
        summary_text = "\n".join(m.text for m in summary_msgs)
        assert "Claude (opus)" in summary_text

    def test_child_job_messages(self) -> None:
        """Test that child job analyses produce child_job type messages."""
        from jenkins_job_insight.models import ChildJobAnalysis

        child = ChildJobAnalysis(
            job_name="child-job",
            build_number=42,
            jenkins_url="https://jenkins.example.com/job/child-job/42/",
            summary="2 failure(s) analyzed",
            failures=[
                FailureAnalysis(
                    test_name="test_child_1",
                    error="Some error",
                    analysis="Analysis of child failure",
                ),
            ],
        )
        result = AnalysisResult(
            job_id="test-123",
            jenkins_url="https://jenkins.example.com/job/test/1/",
            status="completed",
            summary="Pipeline failed",
            failures=[],
            child_job_analyses=[child],
        )
        messages = build_result_messages(result)
        child_msgs = [m for m in messages if m.type == "child_job"]
        assert len(child_msgs) >= 1
        child_text = "\n".join(m.text for m in child_msgs)
        assert "child-job" in child_text
        assert "Analysis of child failure" in child_text


class TestFormatResultMessage:
    """Tests for the format_slack_message function."""

    def test_format_slack_message_basic_structure(self) -> None:
        """Test that format_slack_message returns correct structure."""
        slack_msg = ResultMessage(type="summary", text="Test content")
        message = format_slack_message(slack_msg)

        assert "blocks" in message
        assert isinstance(message["blocks"], list)
        assert len(message["blocks"]) > 0

    def test_format_slack_message_summary_header(self) -> None:
        """Test that summary message has correct header."""
        slack_msg = ResultMessage(type="summary", text="Test content")
        message = format_slack_message(slack_msg)

        header = message["blocks"][0]
        assert header["type"] == "header"
        assert header["text"]["type"] == "plain_text"
        assert "Jenkins Analysis Summary" in header["text"]["text"]

    def test_format_slack_message_failure_detail_header(self) -> None:
        """Test that failure_detail message has correct header."""
        slack_msg = ResultMessage(type="failure_detail", text="Test content")
        message = format_slack_message(slack_msg)

        header = message["blocks"][0]
        assert "Failure Details" in header["text"]["text"]

    def test_format_slack_message_child_job_header(self) -> None:
        """Test that child_job message has correct header."""
        slack_msg = ResultMessage(type="child_job", text="Test content")
        message = format_slack_message(slack_msg)

        header = message["blocks"][0]
        assert "Child Job Analysis" in header["text"]["text"]

    def test_format_slack_message_contains_text(self) -> None:
        """Test that Slack message contains the provided text."""
        slack_msg = ResultMessage(
            type="summary",
            text="Job URL: https://jenkins.example.com/job/my-job/123/\nStatus: completed",
        )
        message = format_slack_message(slack_msg)

        all_text = ""
        for block in message["blocks"]:
            if block["type"] == "section":
                all_text += block["text"]["text"]

        assert "https://jenkins.example.com/job/my-job/123/" in all_text
        assert "completed" in all_text

    def test_format_slack_message_uses_code_blocks(self) -> None:
        """Test that Slack message uses code blocks for content."""
        slack_msg = ResultMessage(type="summary", text="Test summary")
        message = format_slack_message(slack_msg)

        for block in message["blocks"]:
            if block["type"] == "section":
                assert block["text"]["text"].startswith("```")
                assert block["text"]["text"].endswith("```")

    def test_format_slack_message_header_and_section(self) -> None:
        """Test message has header + at least one section block."""
        slack_msg = ResultMessage(type="summary", text="No failures")
        message = format_slack_message(slack_msg)

        assert len(message["blocks"]) >= 2
        assert message["blocks"][0]["type"] == "header"
        assert message["blocks"][1]["type"] == "section"


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
        sample_analysis_result.messages = build_result_messages(sample_analysis_result)
        with patch("jenkins_job_insight.output.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance

            await send_slack(
                "https://hooks.slack.com/services/xxx",
                sample_analysis_result,
            )

            assert mock_instance.post.call_count == len(sample_analysis_result.messages)
            # Each call should post formatted message with blocks
            for call in mock_instance.post.call_args_list:
                assert call[0][0] == "https://hooks.slack.com/services/xxx"
                assert "blocks" in call[1]["json"]

    async def test_send_slack_timeout(
        self, sample_analysis_result: AnalysisResult
    ) -> None:
        """Test that send_slack sets timeout."""
        sample_analysis_result.messages = build_result_messages(sample_analysis_result)
        with patch("jenkins_job_insight.output.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance

            await send_slack(
                "https://hooks.slack.com/services/xxx",
                sample_analysis_result,
            )

            for call in mock_instance.post.call_args_list:
                assert call[1]["timeout"] == 30.0

    async def test_send_slack_no_messages_warns(self) -> None:
        """Test that send_slack warns when no messages are set."""
        result = AnalysisResult(
            job_id="test-123",
            jenkins_url="https://jenkins.example.com/job/test/1/",
            status="completed",
            summary="No failures",
            failures=[],
        )
        with patch("jenkins_job_insight.output.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance

            await send_slack(
                "https://hooks.slack.com/services/xxx",
                result,
            )

            mock_instance.post.assert_not_called()

    async def test_send_slack_continues_on_individual_failure(self) -> None:
        """Test that send_slack continues sending remaining messages when one fails."""
        result = AnalysisResult(
            job_id="test-123",
            jenkins_url="https://jenkins.example.com/job/test/1/",
            status="completed",
            summary="Test",
            failures=[],
            messages=[
                ResultMessage(type="summary", text="Message 1"),
                ResultMessage(type="failure_detail", text="Message 2"),
                ResultMessage(type="child_job", text="Message 3"),
            ],
        )
        with patch("jenkins_job_insight.output.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance

            # Second call raises, first and third should still be attempted
            mock_instance.post.side_effect = [
                None,  # first succeeds
                Exception("network error"),  # second fails
                None,  # third succeeds
            ]

            await send_slack("https://hooks.slack.com/services/xxx", result)

            # All 3 messages should have been attempted
            assert mock_instance.post.call_count == 3
