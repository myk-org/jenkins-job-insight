"""
Standalone conftest.py for enriching JUnit XML with AI failure analysis.

Collects test failures during pytest execution and sends them to a
jenkins-job-insight server for AI analysis. Results are injected into
the JUnit XML report as <properties> and <system-out> elements.

SAFETY: This plugin NEVER fails pytest or compromises the original JUnit XML.
All operations are wrapped in error handling. The original XML is backed up
before modification and restored if anything goes wrong.

Usage:
    1. Copy this file into your project's root (or a conftest.py directory)
    2. Set environment variables:
       - JJI_SERVER_URL: jenkins-job-insight server URL (required)
       - JJI_TIMEOUT: request timeout in seconds (default: 600)
       - JJI_AI_PROVIDER: AI provider to use - claude, gemini, or cursor (required)
       - JJI_AI_MODEL: AI model to use (required)
    3. Run: pytest --junitxml=report.xml

Requirements:
    - requests
    - A running jenkins-job-insight server
"""

import logging

import pytest

from conftest_junit_ai_utils import enrich_junit_xml

logger = logging.getLogger("jenkins-job-insight")

# Module-level collection of failures
_collected_failures: list[dict] = []


@pytest.hookimpl(tryfirst=True)
def pytest_sessionstart(session):
    """Clear collected failures at the start of each session."""
    _collected_failures.clear()


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_makereport(item, call):
    """Collect failure data during test execution.

    Captures failures from all phases: setup (fixtures), call (test body),
    and teardown. Uses tryfirst to capture data before other plugins process it.
    Wrapped in try/except to never interfere with test execution.
    """
    try:
        if call.excinfo:
            _collected_failures.append(
                {
                    "test_name": item.nodeid,
                    "error_message": str(call.excinfo.value),
                    "stack_trace": str(call.excinfo.getrepr()),
                    "duration": call.duration,
                    "status": "FAILED",
                    "phase": call.when,
                }
            )
    except Exception as exc:
        logger.warning("Failed to collect failure data: %s", exc)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    """Enrich JUnit XML with AI analysis after all tests complete.

    Uses trylast to run AFTER the junitxml plugin writes the XML file.
    Wrapped in try/except to never change pytest's exit code or lose the XML.
    """
    try:
        enrich_junit_xml(session, _collected_failures)
    except Exception as exc:
        logger.error("Failed to enrich JUnit XML, original preserved: %s", exc)
