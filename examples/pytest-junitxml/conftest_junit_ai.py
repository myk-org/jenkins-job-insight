"""
Standalone conftest.py for enriching JUnit XML with AI failure analysis.

Parses the JUnit XML that pytest generates, extracts failed test cases,
sends them to a jenkins-job-insight server for AI analysis, and injects
the analysis results back into the XML.

SAFETY: This plugin NEVER fails pytest or compromises the original JUnit XML.
All operations are wrapped in error handling. The original XML is backed up
before modification and restored if anything goes wrong.

Usage:
    1. Copy conftest_junit_ai.py and conftest_junit_ai_utils.py to your project root
    2. Rename conftest_junit_ai.py to conftest.py
    3. Install dependencies: pip install requests python-dotenv
    4. Create a .env file or set environment variables:
       - JJI_SERVER_URL: jenkins-job-insight server URL (required)
       - JJI_AI_PROVIDER: AI provider - claude, gemini, or cursor (default: claude)
       - JJI_AI_MODEL: AI model (default: claude-opus-4-6[1m])
       - JJI_TIMEOUT: request timeout in seconds (default: 600)
    5. Run: pytest --junitxml=report.xml --analyze-with-ai

Requirements:
    - requests
    - python-dotenv
    - A running jenkins-job-insight server
"""

import logging

import pytest

from conftest_junit_ai_utils import enrich_junit_xml, setup_ai_analysis

logger = logging.getLogger("jenkins-job-insight")


def pytest_addoption(parser):
    """Add --analyze-with-ai CLI option."""
    group = parser.getgroup("jenkins-job-insight", "AI-powered failure analysis")
    group.addoption(
        "--analyze-with-ai",
        action="store_true",
        default=False,
        help="Enrich JUnit XML with AI-powered failure analysis from jenkins-job-insight",
    )


def pytest_sessionstart(session):
    """Set up AI analysis if --analyze-with-ai is passed."""
    if session.config.option.analyze_with_ai:
        setup_ai_analysis(session)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    """Enrich JUnit XML with AI analysis after all tests complete.

    Uses trylast to run AFTER the junitxml plugin writes the XML file.
    """
    if not session.config.option.analyze_with_ai:
        return

    try:
        enrich_junit_xml(session)
    except Exception:
        logger.exception("Failed to enrich JUnit XML, original preserved")
