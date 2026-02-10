"""HTML report generation for Jenkins job analysis results.

Generates a self-contained, dark-themed HTML report from analysis results.
All CSS is inlined so the report can be opened directly in any browser
without external dependencies.
"""

import html
import math
import re
from collections import Counter
from collections.abc import Callable
from urllib.parse import urlparse

from jenkins_job_insight.models import AnalysisResult, ChildJobAnalysis, FailureAnalysis


def _get_ai_provider_info(ai_provider: str = "", ai_model: str = "") -> str:
    """Get the AI provider and model info for display.

    Args:
        ai_provider: AI provider name.
        ai_model: AI model name.

    Returns:
        Display string like "Claude (claude-sonnet-4-20250514)".
    """
    if not ai_provider:
        return "Unknown provider"
    if ai_model:
        return f"{ai_provider.capitalize()} ({ai_model})"
    return ai_provider.capitalize()


def _extract_section(text: str, section_name: str) -> str:
    """Extract content between ``=== SECTION_NAME ===`` markers.

    Looks for a line matching ``=== <section_name> ===`` (case-insensitive)
    and returns all text until the next ``=== ... ===`` marker or end of string.

    Args:
        text: The full analysis text to search.
        section_name: Section header to look for (e.g. ``"CLASSIFICATION"``).

    Returns:
        Extracted section content with leading/trailing whitespace stripped,
        or an empty string if the section is not found.
    """
    pattern = re.compile(
        rf"===\s*{re.escape(section_name)}\s*===\s*\n(.*?)(?====\s*\w+\s*===|\Z)",
        re.DOTALL | re.IGNORECASE,
    )
    match = pattern.search(text)
    if match:
        return match.group(1).strip()
    return ""


def _extract_field(text: str, field_name: str) -> str:
    """Extract a field value like ``"Title: some value"`` from text.

    Args:
        text: Text block to search within.
        field_name: Field name prefix (e.g. ``"Title"``, ``"Severity"``).

    Returns:
        The field value with whitespace stripped, or an empty string
        if not found.
    """
    pattern = re.compile(
        rf"^\s*{re.escape(field_name)}\s*:\s*(.+)$", re.MULTILINE | re.IGNORECASE
    )
    match = pattern.search(text)
    if match:
        return match.group(1).strip()
    return ""


def _parse_failure_analysis(failure: FailureAnalysis) -> dict:
    """Parse an individual failure's analysis text into structured fields.

    Extracts classification, severity, component, bug title, and stage
    from the free-form AI-generated analysis text.  Falls back to sensible
    defaults when structured sections are absent.

    Args:
        failure: A ``FailureAnalysis`` instance whose ``analysis`` field
            will be parsed.

    Returns:
        A dict with keys ``classification``, ``severity``, ``component``,
        ``bug_title``, and ``stage``.
    """
    analysis = failure.analysis

    # Classification
    classification_section = _extract_section(analysis, "CLASSIFICATION")
    classification = (
        classification_section.split("\n")[0].strip() if classification_section else ""
    )
    if not classification:
        classification = "Unknown"

    # Bug report section for structured fields
    bug_section = _extract_section(analysis, "BUG REPORT")

    # Severity
    severity = _extract_field(bug_section, "Severity") if bug_section else ""
    if not severity:
        severity = _extract_field(analysis, "Severity")
    severity = severity.lower() if severity else "unknown"
    if severity not in ("critical", "high", "medium", "low"):
        severity = "unknown"

    # Component
    component = _extract_field(bug_section, "Component") if bug_section else ""
    if not component:
        component = _extract_field(analysis, "Component")
    if not component:
        component = "unknown"

    # Bug title
    bug_title = _extract_field(bug_section, "Title") if bug_section else ""
    if not bug_title:
        bug_title = _extract_field(analysis, "Title")
    if not bug_title:
        bug_title = failure.error if failure.error else failure.test_name

    # Stage detection
    combined_lower = (failure.error + " " + failure.test_name).lower()
    stage = "setup" if "setup" in combined_lower else "execution"

    return {
        "classification": classification,
        "severity": severity,
        "component": component,
        "bug_title": bug_title,
        "stage": stage,
    }


def _group_failures_by_root_cause(failures: list[FailureAnalysis]) -> list[dict]:
    """Group failures that share identical analysis text.

    Failures produced by the same root cause typically receive identical
    AI analysis output.  This function groups them and assigns a short
    bug identifier to each group.

    Args:
        failures: List of ``FailureAnalysis`` instances to group.

    Returns:
        A list of dicts, each containing:
        - ``analysis_text``: the shared analysis string
        - ``failures``: list of ``FailureAnalysis`` in this group
        - ``parsed``: parsed fields from ``_parse_failure_analysis``
        - ``bug_id``: a short identifier like ``"BUG-1"``
    """
    groups_map: dict[str, list[FailureAnalysis]] = {}
    order: list[str] = []
    for f in failures:
        key = f.analysis.strip()
        if key not in groups_map:
            groups_map[key] = []
            order.append(key)
        groups_map[key].append(f)

    groups: list[dict] = []
    for idx, key in enumerate(order, start=1):
        group_failures = groups_map[key]
        groups.append(
            {
                "analysis_text": key,
                "failures": group_failures,
                "parsed": _parse_failure_analysis(group_failures[0]),
                "bug_id": f"BUG-{idx}",
            }
        )
    return groups


def _compute_stats(failures: list[FailureAnalysis], groups: list[dict]) -> dict:
    """Compute summary statistics from failures and their groups.

    Args:
        failures: All failure instances.
        groups: Root-cause groups as returned by ``_group_failures_by_root_cause``.

    Returns:
        A dict with keys ``total``, ``unique_errors``, ``setup_count``,
        ``exec_count``, ``classifications``, ``severities``, ``modules``,
        ``dominant_classification``, and ``dominant_severity``.
    """
    total = len(failures)
    unique_errors = len(groups)

    setup_count = 0
    classifications: Counter[str] = Counter()
    severities: Counter[str] = Counter()
    modules: Counter[str] = Counter()

    # Use pre-parsed data from groups instead of re-parsing each failure
    for group in groups:
        p = group["parsed"]
        group_count = len(group["failures"])
        classifications[p["classification"]] += group_count
        severities[p["severity"]] += group_count
        if p["stage"] == "setup":
            setup_count += group_count

        for f in group["failures"]:
            # Module extraction: first 2 dot-separated segments
            parts = f.test_name.split(".")
            if len(parts) >= 2:
                module = ".".join(parts[:2])
            else:
                module = f.test_name
            modules[module] += 1

    exec_count = total - setup_count

    dominant_classification = (
        classifications.most_common(1)[0][0] if classifications else "Unknown"
    )
    dominant_severity = severities.most_common(1)[0][0] if severities else "unknown"

    return {
        "total": total,
        "unique_errors": unique_errors,
        "setup_count": setup_count,
        "exec_count": exec_count,
        "classifications": dict(classifications),
        "severities": dict(severities),
        "modules": dict(modules),
        "dominant_classification": dominant_classification,
        "dominant_severity": dominant_severity,
    }


def _collect_all_failures(result: AnalysisResult) -> list[FailureAnalysis]:
    """Recursively collect all failures from the result and its children.

    Walks ``result.failures`` and all nested ``child_job_analyses`` to
    produce a flat list of every ``FailureAnalysis``.

    Args:
        result: The top-level analysis result.

    Returns:
        A flat list of all ``FailureAnalysis`` instances.
    """
    all_failures: list[FailureAnalysis] = list(result.failures)

    def _collect_from_child(child: ChildJobAnalysis) -> None:
        all_failures.extend(child.failures)
        for nested in child.failed_children:
            _collect_from_child(nested)

    for child in result.child_job_analyses:
        _collect_from_child(child)

    return all_failures


def _extract_job_info_from_url(jenkins_url: str) -> tuple[str, str]:
    """Extract job name and build number from a Jenkins URL.

    Parses URL paths like ``/job/folder/job/name/123/`` to extract the
    human-readable job name and build number.

    Args:
        jenkins_url: Full Jenkins build URL.

    Returns:
        A tuple of ``(job_name, build_number)`` as strings.  Returns
        ``("Unknown", "")`` if parsing fails.
    """
    parsed = urlparse(str(jenkins_url))
    path_parts = [p for p in parsed.path.split("/") if p]

    # Jenkins URLs: /job/<name>/job/<name>/.../<build_number>/
    job_segments: list[str] = []
    build_number = ""
    i = 0
    while i < len(path_parts):
        if path_parts[i] == "job" and i + 1 < len(path_parts):
            job_segments.append(path_parts[i + 1])
            i += 2
        else:
            # Might be the build number (a numeric segment)
            if path_parts[i].isdigit():
                build_number = path_parts[i]
            i += 1

    job_name = "/".join(job_segments) if job_segments else "Unknown"
    return job_name, build_number


def _severity_color(severity: str) -> str:
    """Return CSS color variable name for a severity level.

    Args:
        severity: One of ``"critical"``, ``"high"``, ``"medium"``,
            ``"low"``, or ``"unknown"``.

    Returns:
        CSS color value string.
    """
    mapping = {
        "critical": "#ff6b63",
        "high": "var(--accent-orange)",
        "medium": "var(--accent-yellow)",
        "low": "var(--accent-green)",
        "unknown": "var(--text-muted)",
    }
    return mapping.get(severity.lower(), "var(--text-muted)")


def _classification_css_class(classification: str) -> str:
    """Return a CSS class suffix for a classification string.

    Args:
        classification: Classification text like ``"PRODUCT BUG"``.

    Returns:
        A CSS-safe class name like ``"product-bug"`` or ``"code-issue"``.
    """
    lower = classification.lower().strip()
    if "product" in lower and "bug" in lower:
        return "product-bug"
    if "code" in lower and "issue" in lower:
        return "code-issue"
    # Generic fallback
    return re.sub(r"[^a-z0-9]+", "-", lower).strip("-") or "unknown"


def format_result_as_html(
    result: AnalysisResult,
    ai_provider: str = "",
    ai_model: str = "",
) -> str:
    """Generate a self-contained HTML report for an analysis result.

    Produces a complete HTML document with inline CSS using a dark
    GitHub-inspired theme.  The report includes statistics, charts,
    bug cards, a detail table, and child job sections.

    Args:
        result: The analysis result to render.
        ai_provider: AI provider name (e.g. ``"claude"``).
        ai_model: AI model identifier (e.g. ``"claude-sonnet-4-20250514"``).

    Returns:
        A complete HTML document as a string.
    """
    e = html.escape  # alias for convenience

    all_failures = _collect_all_failures(result)
    groups = _group_failures_by_root_cause(all_failures)
    stats = _compute_stats(all_failures, groups)

    job_name, build_number = _extract_job_info_from_url(str(result.jenkins_url))
    provider_info = _get_ai_provider_info(ai_provider=ai_provider, ai_model=ai_model)
    jenkins_url_str = str(result.jenkins_url)

    # Donut chart calculations
    circumference = 2 * math.pi * 47  # ~295.31
    total = stats["total"] if stats["total"] > 0 else 1
    setup_pct = stats["setup_count"] / total
    exec_pct = stats["exec_count"] / total
    setup_dash = circumference * setup_pct
    exec_dash = circumference * exec_pct
    setup_gap = circumference - setup_dash
    exec_gap = circumference - exec_dash
    # Offset for exec segment: starts after setup segment
    # SVG dashoffset for exec: negative offset moves forward along the circle
    # With rotate(-90), 0 offset = 12 o'clock. We need to skip past the setup segment.
    exec_offset = -setup_dash

    # Root cause detection: dominant root cause > 50%
    dominant_root_cause = None
    if groups and stats["total"] > 0:
        largest_group = max(groups, key=lambda g: len(g["failures"]))
        if len(largest_group["failures"]) / stats["total"] > 0.5:
            dominant_root_cause = largest_group

    # Bar chart data: modules sorted by count descending
    module_items = sorted(stats["modules"].items(), key=lambda x: x[1], reverse=True)
    max_module_count = module_items[0][1] if module_items else 1

    # Build the HTML parts
    parts: list[str] = []

    # --- HTML HEAD ---
    parts.append(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Jenkins Analysis - {e(job_name)} #{e(build_number)}</title>
<style>
:root {{
    --bg-primary: #0d1117;
    --bg-secondary: #161b22;
    --bg-tertiary: #21262d;
    --bg-hover: #292e36;
    --border: #30363d;
    --text-primary: #e6edf3;
    --text-secondary: #8b949e;
    --text-muted: #6e7681;
    --accent-red: #f85149;
    --accent-red-bg: rgba(248, 81, 73, 0.12);
    --accent-green: #3fb950;
    --accent-green-bg: rgba(63, 185, 80, 0.12);
    --accent-yellow: #d29922;
    --accent-yellow-bg: rgba(210, 153, 34, 0.12);
    --accent-blue: #58a6ff;
    --accent-blue-bg: rgba(88, 166, 255, 0.08);
    --accent-purple: #bc8cff;
    --accent-orange: #f0883e;
    --accent-orange-bg: rgba(240, 136, 62, 0.12);
    --font-mono: 'SF Mono', 'Cascadia Code', 'Fira Code', 'JetBrains Mono', Consolas, monospace;
    --font-sans: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
    --radius: 8px;
}}
*,*::before,*::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
    font-family: var(--font-sans);
    background: var(--bg-primary);
    color: var(--text-primary);
    line-height: 1.6;
    min-height: 100vh;
}}
.container {{ max-width: 1200px; margin: 0 auto; padding: 0 24px 60px; }}

/* Header */
.sticky-header {{
    position: sticky;
    top: 0;
    z-index: 100;
    background: var(--bg-secondary);
    border-bottom: 1px solid var(--border);
    padding: 16px 24px;
    margin: 0 -24px 32px;
}}
.header-content {{ max-width: 1200px; margin: 0 auto; display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }}
.header-content h1 {{ font-size: 20px; font-weight: 700; flex-shrink: 0; }}
.failure-badge {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: var(--accent-red-bg);
    color: var(--accent-red);
    font-size: 13px;
    font-weight: 700;
    padding: 4px 12px;
    border-radius: 12px;
    font-family: var(--font-mono);
}}
.pulse-dot {{
    width: 8px;
    height: 8px;
    background: var(--accent-red);
    border-radius: 50%;
    animation: pulse 2s ease-in-out infinite;
}}
@keyframes pulse {{
    0%, 100% {{ opacity: 1; transform: scale(1); }}
    50% {{ opacity: 0.5; transform: scale(0.8); }}
}}
.env-chips {{ display: flex; gap: 8px; flex-wrap: wrap; margin-left: auto; }}
.env-chip {{
    font-size: 12px;
    padding: 4px 10px;
    border-radius: 6px;
    background: var(--bg-tertiary);
    border: 1px solid var(--border);
    color: var(--text-secondary);
    text-decoration: none;
}}
.env-chip a {{ color: var(--accent-blue); text-decoration: none; }}
.env-chip a:hover {{ text-decoration: underline; }}

/* Section titles */
.section-title {{
    font-size: 14px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--text-muted);
    margin: 32px 0 16px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border);
}}

/* Results overview with donut */
.results-overview {{
    display: grid;
    grid-template-columns: 200px 1fr;
    gap: 32px;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 24px;
    margin-bottom: 24px;
}}
.donut-container {{ display: flex; flex-direction: column; align-items: center; gap: 12px; }}
.donut-legend {{ font-size: 12px; color: var(--text-secondary); text-align: center; }}
.donut-legend-item {{ display: flex; align-items: center; gap: 6px; margin: 4px 0; }}
.legend-dot {{ width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }}

/* Stats grid */
.stats-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }}
.stat-card {{
    background: var(--bg-tertiary);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 16px;
}}
.stat-label {{ font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }}
.stat-value {{ font-size: 24px; font-weight: 700; font-family: var(--font-mono); }}
.stat-detail {{ font-size: 11px; color: var(--text-muted); margin-top: 2px; font-family: var(--font-mono); }}

/* Root cause banner */
.root-cause-banner {{
    background: var(--bg-secondary);
    border: 2px solid var(--accent-red);
    border-radius: var(--radius);
    padding: 20px 24px;
    margin-bottom: 24px;
}}
.root-cause-header {{ display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }}
.root-cause-header h3 {{ font-size: 16px; color: var(--accent-red); }}
.root-cause-desc {{ font-size: 14px; color: var(--text-secondary); margin-bottom: 12px; }}
.root-cause-error {{
    background: var(--bg-primary);
    border: 1px solid var(--border);
    border-left: 3px solid var(--accent-red);
    border-radius: 4px;
    padding: 12px 16px;
    font-family: var(--font-mono);
    font-size: 12px;
    color: var(--accent-red);
    margin-bottom: 12px;
    overflow-x: auto;
    white-space: pre-wrap;
    word-break: break-word;
}}
.root-cause-details {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 12px;
}}
.root-cause-detail {{
    font-size: 12px;
}}
.root-cause-detail .label {{ color: var(--text-muted); }}
.root-cause-detail .value {{ color: var(--text-primary); font-weight: 600; }}

/* Charts row */
.charts-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-bottom: 24px; }}
.chart-card {{
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 20px 24px;
}}
.chart-card h3 {{ font-size: 14px; color: var(--text-secondary); margin-bottom: 16px; }}

/* Severity badge */
.severity-badge-container {{ display: flex; justify-content: center; align-items: center; min-height: 160px; }}
.severity-badge {{
    display: flex;
    align-items: center;
    gap: 12px;
    font-size: 28px;
    font-weight: 800;
    font-family: var(--font-mono);
    text-transform: uppercase;
    letter-spacing: 2px;
    padding: 16px 32px;
    border-radius: 16px;
    border: 2px solid;
    animation: badgePulse 3s ease-in-out infinite;
}}
@keyframes badgePulse {{
    0%, 100% {{ border-color: currentColor; box-shadow: 0 0 20px rgba(255,255,255,0.05); }}
    50% {{ border-color: transparent; box-shadow: 0 0 40px rgba(255,255,255,0.1); }}
}}

/* Bar chart */
.bar-chart {{ display: flex; flex-direction: column; gap: 8px; }}
.bar-row {{ display: flex; align-items: center; gap: 12px; }}
.bar-label {{ font-size: 12px; font-family: var(--font-mono); color: var(--text-secondary); min-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.bar-track {{ flex: 1; height: 20px; background: var(--bg-tertiary); border-radius: 4px; overflow: hidden; position: relative; }}
.bar-fill {{
    height: 100%;
    background: linear-gradient(90deg, var(--accent-red), #ff6b63);
    border-radius: 4px;
    transform-origin: left;
    transform: scaleX(0);
    animation: growBar 0.8s ease-out forwards;
}}
.bar-value {{ font-size: 12px; font-family: var(--font-mono); color: var(--text-muted); min-width: 30px; text-align: right; }}
@keyframes growBar {{ to {{ transform: scaleX(1); }} }}
.bar-row:nth-child(1) .bar-fill {{ animation-delay: 0.2s; }}
.bar-row:nth-child(2) .bar-fill {{ animation-delay: 0.3s; }}
.bar-row:nth-child(3) .bar-fill {{ animation-delay: 0.4s; }}
.bar-row:nth-child(4) .bar-fill {{ animation-delay: 0.5s; }}
.bar-row:nth-child(5) .bar-fill {{ animation-delay: 0.6s; }}
.bar-row:nth-child(6) .bar-fill {{ animation-delay: 0.7s; }}

/* Bug cards */
.bug-card {{
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    margin-bottom: 12px;
    overflow: hidden;
}}
.bug-card[open] {{ border-color: var(--accent-blue); }}
.bug-summary {{
    padding: 16px 20px;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
    list-style: none;
}}
.bug-summary::-webkit-details-marker {{ display: none; }}
.bug-summary::before {{
    content: "\\25B6";
    font-size: 10px;
    color: var(--text-muted);
    transition: transform 0.2s;
}}
.bug-card[open] .bug-summary::before {{ transform: rotate(90deg); }}
.bug-id {{
    font-family: var(--font-mono);
    font-size: 12px;
    font-weight: 700;
    color: var(--accent-blue);
    background: var(--accent-blue-bg);
    padding: 2px 8px;
    border-radius: 4px;
}}
.bug-title {{
    flex: 1;
    font-weight: 600;
    font-size: 14px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}}
.bug-count {{
    font-size: 12px;
    color: var(--text-muted);
}}
.classification-tag {{
    font-size: 11px;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 4px;
    text-transform: uppercase;
}}
.classification-tag.product-bug {{
    background: var(--accent-orange-bg);
    color: var(--accent-orange);
}}
.classification-tag.code-issue {{
    background: var(--accent-blue-bg);
    color: var(--accent-blue);
}}
.classification-tag.unknown {{
    background: var(--bg-tertiary);
    color: var(--text-muted);
}}
.severity-tag-inline {{
    font-size: 11px;
    font-weight: 700;
    font-family: var(--font-mono);
    padding: 2px 8px;
    border-radius: 4px;
    text-transform: uppercase;
}}
.severity-tag-inline.critical {{ background: rgba(248,81,73,0.15); color: #ff6b63; }}
.severity-tag-inline.high {{ background: rgba(240,136,62,0.15); color: var(--accent-orange); }}
.severity-tag-inline.medium {{ background: rgba(210,153,34,0.15); color: var(--accent-yellow); }}
.severity-tag-inline.low {{ background: rgba(63,185,80,0.15); color: var(--accent-green); }}
.severity-tag-inline.unknown {{ background: var(--bg-tertiary); color: var(--text-muted); }}
.bug-body {{
    padding: 0 20px 20px;
    border-top: 1px solid var(--border);
}}
.bug-body h4 {{
    font-size: 13px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin: 16px 0 8px;
}}
.analysis-pre, .error-pre {{
    background: var(--bg-primary);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 16px;
    font-family: var(--font-mono);
    font-size: 12px;
    line-height: 1.6;
    overflow-x: auto;
    white-space: pre-wrap;
    word-break: break-word;
    color: var(--text-secondary);
}}
.error-pre {{
    border-left: 3px solid var(--accent-red);
    color: var(--accent-red);
}}
.bug-tests ul {{
    list-style: none;
    padding: 0;
}}
.bug-tests li {{
    padding: 4px 0;
    font-size: 13px;
    color: var(--text-secondary);
}}
.bug-tests li::before {{
    content: "\\2192 ";
    color: var(--text-muted);
}}
.bug-tests code {{
    font-family: var(--font-mono);
    font-size: 12px;
    color: var(--text-primary);
}}

/* Detail table */
.table-container {{
    overflow-x: auto;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    margin-bottom: 24px;
}}
table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
}}
thead {{ position: sticky; top: 0; z-index: 10; }}
th {{
    background: var(--bg-tertiary);
    padding: 12px 16px;
    text-align: left;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-muted);
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
}}
td {{
    padding: 10px 16px;
    border-bottom: 1px solid var(--border);
    color: var(--text-secondary);
    vertical-align: top;
}}
tr:hover td {{ background: var(--bg-hover); }}
td.test-name {{ font-family: var(--font-mono); font-size: 12px; color: var(--text-primary); max-width: 300px; word-break: break-all; }}
td.error-cell {{ font-family: var(--font-mono); font-size: 11px; max-width: 350px; word-break: break-word; color: var(--accent-red); }}
.stage-tag {{
    font-size: 11px;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 10px;
    text-transform: uppercase;
    white-space: nowrap;
}}
.stage-tag.setup {{ background: rgba(240, 136, 62, 0.12); color: var(--accent-orange); border: 1px solid rgba(240, 136, 62, 0.25); }}
.stage-tag.execution {{ background: rgba(188, 140, 255, 0.12); color: var(--accent-purple); border: 1px solid rgba(188, 140, 255, 0.25); }}

/* Key takeaway */
.key-takeaway {{
    background: var(--bg-secondary);
    border: 1px solid var(--accent-yellow);
    border-left: 4px solid var(--accent-yellow);
    border-radius: var(--radius);
    padding: 20px 24px;
    margin-bottom: 24px;
}}
.key-takeaway-header {{ display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }}
.key-takeaway-header h3 {{ font-size: 14px; color: var(--accent-yellow); }}
.key-takeaway p {{ font-size: 14px; color: var(--text-secondary); line-height: 1.7; }}

/* Child job sections */
.child-job {{
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    margin-bottom: 12px;
    overflow: hidden;
}}
.child-job[open] {{ border-color: var(--accent-purple); }}
.child-job-summary {{
    padding: 16px 20px;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
    list-style: none;
    font-weight: 600;
    font-size: 14px;
}}
.child-job-summary::-webkit-details-marker {{ display: none; }}
.child-job-summary::before {{
    content: "\\25B6";
    font-size: 10px;
    color: var(--text-muted);
    transition: transform 0.2s;
}}
.child-job[open] .child-job-summary::before {{ transform: rotate(90deg); }}
.child-job-body {{ padding: 0 20px 20px; border-top: 1px solid var(--border); }}
.child-job-meta {{ display: flex; gap: 16px; flex-wrap: wrap; margin: 12px 0; font-size: 12px; color: var(--text-muted); }}
.child-job-meta a {{ color: var(--accent-blue); text-decoration: none; }}
.child-job-meta a:hover {{ text-decoration: underline; }}
.child-note {{ font-size: 13px; color: var(--accent-yellow); font-style: italic; margin: 8px 0; }}

/* Footer */
.report-footer {{
    margin-top: 48px;
    padding: 24px 0;
    border-top: 1px solid var(--border);
    font-size: 12px;
    color: var(--text-muted);
    display: flex;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 12px;
}}
.report-footer a {{ color: var(--accent-blue); text-decoration: none; }}
.report-footer a:hover {{ text-decoration: underline; }}

/* No failures */
.no-failures {{
    text-align: center;
    padding: 60px 20px;
    color: var(--text-muted);
    font-size: 16px;
}}
.no-failures svg {{ margin-bottom: 16px; }}

/* Responsive */
@media (max-width: 768px) {{
    .results-overview {{ grid-template-columns: 1fr; }}
    .stats-grid {{ grid-template-columns: repeat(2, 1fr); }}
    .charts-row {{ grid-template-columns: 1fr; }}
    .header-content {{ flex-direction: column; align-items: flex-start; }}
    .env-chips {{ margin-left: 0; }}
    .root-cause-details {{ grid-template-columns: 1fr 1fr; }}
}}
@media (max-width: 480px) {{
    .stats-grid {{ grid-template-columns: 1fr; }}
    .root-cause-details {{ grid-template-columns: 1fr; }}
    .bug-summary {{ font-size: 12px; gap: 8px; }}
    .bar-label {{ min-width: 120px; font-size: 11px; }}
}}
""")

    # Dynamic donut animation keyframes
    parts.append(f"""
@keyframes fillSetup {{
    from {{ stroke-dasharray: 0 {circumference:.2f}; }}
    to {{ stroke-dasharray: {setup_dash:.2f} {setup_gap:.2f}; }}
}}
@keyframes fillExec {{
    from {{ stroke-dasharray: 0 {circumference:.2f}; }}
    to {{ stroke-dasharray: {exec_dash:.2f} {exec_gap:.2f}; }}
}}
""")

    parts.append('</style>\n</head>\n<body>\n<div class="container">')

    # --- STICKY HEADER ---
    status_escaped = e(result.status)
    parts.append(f"""
<div class="sticky-header">
  <div class="header-content">
    <h1>{e(job_name)}</h1>
    <span class="failure-badge"><span class="pulse-dot"></span>{stats["total"]} failure{"s" if stats["total"] != 1 else ""}</span>
    <div class="env-chips">
      <span class="env-chip">Job: {e(job_name)}</span>
      <span class="env-chip">Build: #{e(build_number)}</span>
      <span class="env-chip">Status: {status_escaped}</span>
      <span class="env-chip"><a href="{e(jenkins_url_str)}" target="_blank" rel="noopener">Jenkins</a></span>
    </div>
  </div>
</div>
""")

    # --- NO FAILURES CASE ---
    if stats["total"] == 0:
        parts.append("""
<div class="no-failures">
  <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--accent-green)" stroke-width="2">
    <circle cx="12" cy="12" r="10"/>
    <path d="M8 12l2.5 2.5L16 9"/>
  </svg>
  <p>No failures detected in this build.</p>
</div>
""")
        # Still show summary and footer
        _append_takeaway(parts, result.summary, e)
        _append_footer(
            parts,
            job_name,
            build_number,
            result.job_id,
            provider_info,
            jenkins_url_str,
            e,
        )
        parts.append("</div>\n</body>\n</html>")
        return "\n".join(parts)

    # --- RESULTS OVERVIEW (donut + stats) ---
    setup_pct_display = round(setup_pct * 100)
    exec_pct_display = round(exec_pct * 100)

    parts.append(f"""
<h2 class="section-title">Results Overview</h2>
<div class="results-overview">
  <div class="donut-container">
    <svg width="140" height="140" viewBox="0 0 120 120">
      <circle cx="60" cy="60" r="47" fill="none" stroke="var(--bg-tertiary)" stroke-width="12"/>
      <circle cx="60" cy="60" r="47" fill="none"
              stroke="var(--accent-orange)" stroke-width="12"
              stroke-dasharray="{setup_dash:.2f} {setup_gap:.2f}"
              stroke-dashoffset="{circumference * 0.25:.2f}"
              stroke-linecap="round"
              style="animation: fillSetup 1s ease-out forwards;"
              transform="rotate(-90 60 60)"/>
      <circle cx="60" cy="60" r="47" fill="none"
              stroke="var(--accent-purple)" stroke-width="12"
              stroke-dasharray="{exec_dash:.2f} {exec_gap:.2f}"
              stroke-dashoffset="{exec_offset:.2f}"
              stroke-linecap="round"
              style="animation: fillExec 1s ease-out 0.3s forwards;"
              transform="rotate(-90 60 60)"/>
      <text x="60" y="56" text-anchor="middle" fill="var(--text-primary)" font-size="22" font-weight="700" font-family="var(--font-mono)">{stats["total"]}</text>
      <text x="60" y="72" text-anchor="middle" fill="var(--text-muted)" font-size="10">failures</text>
    </svg>
    <div class="donut-legend">
      <div class="donut-legend-item"><span class="legend-dot" style="background:var(--accent-orange)"></span> Setup ({setup_pct_display}%)</div>
      <div class="donut-legend-item"><span class="legend-dot" style="background:var(--accent-purple)"></span> Execution ({exec_pct_display}%)</div>
    </div>
  </div>
  <div class="stats-grid">
    <div class="stat-card">
      <div class="stat-label">Total Failures</div>
      <div class="stat-value" style="color:var(--accent-red)">{stats["total"]}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Unique Errors</div>
      <div class="stat-value" style="color:var(--accent-orange)">{stats["unique_errors"]}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Classification</div>
      <div class="stat-value" style="font-size:16px;color:var(--text-primary)">{e(stats["dominant_classification"])}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Severity</div>
      <div class="stat-value" style="font-size:16px;color:{_severity_color(stats["dominant_severity"])}">{e(stats["dominant_severity"].upper())}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Job ID</div>
      <div class="stat-value" style="font-size:14px;color:var(--accent-purple)">{e(result.job_id[:8])}</div>
      <div class="stat-detail">{e(result.job_id)}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Affected Modules</div>
      <div class="stat-value" style="color:var(--accent-blue)">{len(stats["modules"])}</div>
    </div>
  </div>
</div>
""")

    # --- ROOT CAUSE BANNER ---
    if dominant_root_cause is not None:
        parsed_rc = dominant_root_cause["parsed"]
        rc_failures = dominant_root_cause["failures"]
        rc_count = len(rc_failures)
        rc_pct = round(rc_count / stats["total"] * 100)
        rc_stage = parsed_rc["stage"]
        rc_setup = rc_count if rc_stage == "setup" else 0
        rc_exec = rc_count - rc_setup

        parts.append(f"""
<div class="root-cause-banner">
  <div class="root-cause-header">
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--accent-red)" stroke-width="2">
      <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/>
      <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
    </svg>
    <h3>Dominant Root Cause ({rc_pct}% of failures)</h3>
  </div>
  <div class="root-cause-desc">{e(parsed_rc["bug_title"])}</div>
  <div class="root-cause-error">{e(rc_failures[0].error)}</div>
  <div class="root-cause-details">
    <div class="root-cause-detail"><span class="label">Component: </span><span class="value">{e(parsed_rc["component"])}</span></div>
    <div class="root-cause-detail"><span class="label">Classification: </span><span class="value">{e(parsed_rc["classification"])}</span></div>
    <div class="root-cause-detail"><span class="label">Setup failures: </span><span class="value">{rc_setup}</span></div>
    <div class="root-cause-detail"><span class="label">Execution failures: </span><span class="value">{rc_exec}</span></div>
  </div>
</div>
""")

    # --- CHARTS ROW ---
    severity_color = _severity_color(stats["dominant_severity"])
    parts.append(f"""
<div class="charts-row">
  <div class="chart-card">
    <h3>Overall Severity Assessment</h3>
    <div class="severity-badge-container">
      <div class="severity-badge" style="color:{severity_color};border-color:{severity_color};background:rgba(255,255,255,0.03)">
        <svg width="28" height="28" viewBox="0 0 16 16" fill="currentColor"><path d="M4.47.22A.749.749 0 0 1 5 0h6c.199 0 .389.079.53.22l4.25 4.25c.141.14.22.331.22.53v6a.749.749 0 0 1-.22.53l-4.25 4.25A.749.749 0 0 1 11 16H5a.749.749 0 0 1-.53-.22L.22 11.53A.749.749 0 0 1 0 11V5c0-.199.079-.389.22-.53Zm.84 1.28L1.5 5.31v5.38l3.81 3.81h5.38l3.81-3.81V5.31L10.69 1.5ZM8 4a.75.75 0 0 1 .75.75v3.5a.75.75 0 0 1-1.5 0v-3.5A.75.75 0 0 1 8 4Zm0 8a1 1 0 1 1 0-2 1 1 0 0 1 0 2Z"/></svg>
        {e(stats["dominant_severity"].upper())}
      </div>
    </div>
  </div>
  <div class="chart-card">
    <h3>Failures by Module</h3>
    <div class="bar-chart">
""")

    for module_name, count in module_items:
        bar_pct = round(count / max_module_count * 100)
        parts.append(f"""      <div class="bar-row">
        <span class="bar-label" title="{e(module_name)}">{e(module_name)}</span>
        <div class="bar-track"><div class="bar-fill" style="width:{bar_pct}%"></div></div>
        <span class="bar-value">{count}</span>
      </div>
""")

    parts.append("    </div>\n  </div>\n</div>")

    # --- BUG CARDS ---
    parts.append('<h2 class="section-title">Root Cause Analysis</h2>')

    for group in groups:
        parsed = group["parsed"]
        bug_id = group["bug_id"]
        cls_class = _classification_css_class(parsed["classification"])
        sev_class = parsed["severity"]
        test_count = len(group["failures"])
        test_label = f"{test_count} test{'s' if test_count != 1 else ''}"

        parts.append(f"""<details class="bug-card">
  <summary class="bug-summary">
    <span class="bug-id">{e(bug_id)}</span>
    <span class="bug-title">{e(parsed["bug_title"])}</span>
    <span class="bug-count">{e(test_label)}</span>
    <span class="classification-tag {e(cls_class)}">{e(parsed["classification"])}</span>
    <span class="severity-tag-inline {e(sev_class)}">{e(parsed["severity"].upper())}</span>
  </summary>
  <div class="bug-body">
    <div class="bug-analysis">
      <h4>AI Analysis</h4>
      <pre class="analysis-pre">{e(group["analysis_text"])}</pre>
    </div>
    <div class="bug-tests">
      <h4>Affected Tests ({test_count})</h4>
      <ul>
""")
        for f in group["failures"]:
            parts.append(f"        <li><code>{e(f.test_name)}</code></li>\n")

        parts.append(f"""      </ul>
    </div>
    <div class="bug-error">
      <h4>Error</h4>
      <pre class="error-pre">{e(group["failures"][0].error)}</pre>
    </div>
  </div>
</details>
""")

    # --- DETAIL TABLE ---
    parts.append("""
<h2 class="section-title">All Failures</h2>
<div class="table-container">
<table>
<thead>
<tr>
  <th>#</th>
  <th>Test Name</th>
  <th>Module</th>
  <th>Bug Ref</th>
  <th>Error</th>
  <th>Stage</th>
  <th>Severity</th>
</tr>
</thead>
<tbody>
""")

    # Build lookups: failure analysis text -> bug_id and parsed data
    analysis_to_bug: dict[str, str] = {}
    analysis_to_parsed: dict[str, dict] = {}
    for group in groups:
        analysis_to_bug[group["analysis_text"]] = group["bug_id"]
        analysis_to_parsed[group["analysis_text"]] = group["parsed"]

    for idx, f in enumerate(all_failures, start=1):
        parsed = analysis_to_parsed.get(f.analysis.strip(), _parse_failure_analysis(f))
        parts_name = f.test_name.split(".")
        module = ".".join(parts_name[:2]) if len(parts_name) >= 2 else f.test_name
        bug_ref = analysis_to_bug.get(f.analysis.strip(), "")
        stage_class = parsed["stage"]
        sev_class = parsed["severity"]

        parts.append(f"""<tr>
  <td>{idx}</td>
  <td class="test-name">{e(f.test_name)}</td>
  <td>{e(module)}</td>
  <td><span class="bug-id">{e(bug_ref)}</span></td>
  <td class="error-cell" title="{e(f.error)}">{e(f.error)}</td>
  <td><span class="stage-tag {e(stage_class)}">{e(stage_class)}</span></td>
  <td><span class="severity-tag-inline {e(sev_class)}">{e(parsed["severity"].upper())}</span></td>
</tr>
""")

    parts.append("</tbody>\n</table>\n</div>")

    # --- CHILD JOB ANALYSES ---
    if result.child_job_analyses:
        parts.append('<h2 class="section-title">Child Job Analyses</h2>')
        _render_child_jobs(parts, result.child_job_analyses, e)

    # --- KEY TAKEAWAY ---
    _append_takeaway(parts, result.summary, e)

    # --- FOOTER ---
    _append_footer(
        parts, job_name, build_number, result.job_id, provider_info, jenkins_url_str, e
    )

    parts.append("</div>\n</body>\n</html>")
    return "\n".join(parts)


def _render_child_jobs(
    parts: list[str],
    children: list[ChildJobAnalysis],
    e: Callable[[str], str],
) -> None:
    """Render child job analysis sections recursively.

    Args:
        parts: List of HTML string parts to append to.
        children: Child job analyses to render.
        e: HTML escape function reference.
    """
    for child in children:
        child_failures_count = len(child.failures)
        parts.append(f"""<details class="child-job">
  <summary class="child-job-summary">
    <span style="color:var(--accent-purple)">{e(child.job_name)}</span>
    <span style="color:var(--text-muted)">#{child.build_number}</span>
    <span class="failure-badge" style="font-size:11px;padding:2px 8px">{child_failures_count} failure{"s" if child_failures_count != 1 else ""}</span>
  </summary>
  <div class="child-job-body">
    <div class="child-job-meta">
      <span>Build: #{child.build_number}</span>
""")
        if child.jenkins_url:
            parts.append(
                f'      <a href="{e(child.jenkins_url)}" target="_blank" rel="noopener">View in Jenkins</a>\n'
            )
        parts.append("    </div>")

        if child.note:
            parts.append(f'    <div class="child-note">{e(child.note)}</div>')

        if child.summary:
            parts.append(
                f'    <p style="font-size:13px;color:var(--text-secondary);margin:8px 0">{e(child.summary)}</p>'
            )

        if child.failures:
            child_groups = _group_failures_by_root_cause(child.failures)
            for group in child_groups:
                parsed = group["parsed"]
                test_count = len(group["failures"])
                cls_class = _classification_css_class(parsed["classification"])
                sev_class = parsed["severity"]

                parts.append(f"""    <details class="bug-card" style="margin-top:12px">
      <summary class="bug-summary">
        <span class="bug-id">{e(group["bug_id"])}</span>
        <span class="bug-title">{e(parsed["bug_title"])}</span>
        <span class="bug-count">{test_count} test{"s" if test_count != 1 else ""}</span>
        <span class="classification-tag {e(cls_class)}">{e(parsed["classification"])}</span>
        <span class="severity-tag-inline {e(sev_class)}">{e(parsed["severity"].upper())}</span>
      </summary>
      <div class="bug-body">
        <div class="bug-analysis">
          <h4>AI Analysis</h4>
          <pre class="analysis-pre">{e(group["analysis_text"])}</pre>
        </div>
        <div class="bug-tests">
          <h4>Affected Tests ({test_count})</h4>
          <ul>
""")
                for f in group["failures"]:
                    parts.append(
                        f"            <li><code>{e(f.test_name)}</code></li>\n"
                    )

                parts.append(f"""          </ul>
        </div>
        <div class="bug-error">
          <h4>Error</h4>
          <pre class="error-pre">{e(group["failures"][0].error)}</pre>
        </div>
      </div>
    </details>
""")

        # Recurse into nested children
        if child.failed_children:
            _render_child_jobs(parts, child.failed_children, e)

        parts.append("  </div>\n</details>\n")


def _append_takeaway(parts: list[str], summary: str, e: Callable[[str], str]) -> None:
    """Append the key takeaway callout section.

    Args:
        parts: List of HTML string parts to append to.
        summary: The analysis summary text.
        e: HTML escape function reference.
    """
    parts.append(f"""
<div class="key-takeaway">
  <div class="key-takeaway-header">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--accent-yellow)" stroke-width="2">
      <circle cx="12" cy="12" r="10"/>
      <line x1="12" y1="16" x2="12" y2="12"/>
      <line x1="12" y1="8" x2="12.01" y2="8"/>
    </svg>
    <h3>Key Takeaway</h3>
  </div>
  <p>{e(summary)}</p>
</div>
""")


def _append_footer(
    parts: list[str],
    job_name: str,
    build_number: str,
    job_id: str,
    provider_info: str,
    jenkins_url: str,
    e: Callable[[str], str],
) -> None:
    """Append the report footer section.

    Args:
        parts: List of HTML string parts to append to.
        job_name: Jenkins job name.
        build_number: Build number string.
        job_id: Analysis job identifier.
        provider_info: AI provider display string.
        jenkins_url: Full Jenkins build URL.
        e: HTML escape function reference.
    """
    parts.append(f"""
<div class="report-footer">
  <span>{e(job_name)} #{e(build_number)} | Job ID: {e(job_id)} | Analyzed by {e(provider_info)}</span>
  <a href="{e(jenkins_url)}" target="_blank" rel="noopener">View in Jenkins</a>
</div>
""")
