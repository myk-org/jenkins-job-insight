"""Shared utilities for jenkins-job-insight."""

from __future__ import annotations

import jenkins
import requests.exceptions


#: Combined tuple of exception types that indicate a transient Jenkins
#: connectivity problem (network outage, DNS failure, timeout, etc.).
#: Used by both the polling loop in *main.py* and the pre-flight check
#: in *analyzer.py*.
#:
#: Note: ``jenkins.JenkinsException`` is intentionally excluded — it is
#: the base class for many non-transient errors (auth failures, 5xx,
#: malformed responses).  Only ``jenkins.TimeoutException`` (a subclass)
#: represents a true connectivity/timeout problem.
JENKINS_CONNECTIVITY_EXCEPTIONS: tuple[type[BaseException], ...] = (
    OSError,
    TimeoutError,
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
    jenkins.TimeoutException,
)


def is_jenkins_connectivity_error(exc: Exception) -> bool:
    """Return ``True`` if *exc* looks like a transient Jenkins connectivity error."""
    return isinstance(exc, JENKINS_CONNECTIVITY_EXCEPTIONS)
