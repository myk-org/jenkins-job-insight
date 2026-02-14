"""HTML report generation for Jenkins job analysis results.

Generates a self-contained, dark-themed HTML report from analysis results.
All CSS is inlined so the report can be opened directly in any browser
without external dependencies.
"""

import html
from collections.abc import Callable

from jenkins_job_insight.models import (
    AnalysisDetail,
    AnalysisResult,
    ChildJobAnalysis,
    CodeFix,
    FailureAnalysis,
    JiraMatch,
    ProductBugReport,
)


def format_result_as_html(result: AnalysisResult) -> str:
    """Generate a self-contained HTML report for an analysis result.

    Produces a complete HTML document with inline CSS using a dark
    GitHub-inspired theme.  The report includes failure cards, a
    detail table, and child job sections.

    Args:
        result: The analysis result to render.

    Returns:
        A complete HTML document as a string.
    """
    e = html.escape

    job_name = result.job_name or "Unknown"
    build_number = str(result.build_number) if result.build_number else ""
    provider_info = _format_provider(result.ai_provider, result.ai_model)
    jenkins_url_str = str(result.jenkins_url)
    total_failures = len(result.failures)

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
    --accent-blue: #58a6ff;
    --accent-blue-bg: rgba(88, 166, 255, 0.08);
    --accent-yellow: #d29922;
    --accent-orange: #f0883e;
    --accent-orange-bg: rgba(240, 136, 62, 0.12);
    --accent-purple: #bc8cff;
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

/* Failure cards */
.failure-card {{
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    margin-bottom: 12px;
    overflow: hidden;
}}
.failure-card[open] {{ border-color: var(--accent-blue); }}
.failure-summary {{
    padding: 16px 20px;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
    list-style: none;
}}
.failure-summary::-webkit-details-marker {{ display: none; }}
.failure-summary::before {{
    content: "\\25B6";
    font-size: 10px;
    color: var(--text-muted);
    transition: transform 0.2s;
}}
.failure-card[open] .failure-summary::before {{ transform: rotate(90deg); }}
.failure-title {{
    flex: 1;
    font-weight: 600;
    font-size: 14px;
    font-family: var(--font-mono);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
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
.bug-id {{
    font-family: var(--font-mono);
    font-size: 12px;
    font-weight: 700;
    color: var(--accent-blue);
    background: var(--accent-blue-bg);
    padding: 2px 8px;
    border-radius: 4px;
}}
.bug-count {{
    font-size: 12px;
    color: var(--text-muted);
}}
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
.bug-title {{
    flex: 1;
    font-weight: 600;
    font-size: 14px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}}
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
/* Jira matches */
.jira-matches {{ margin-top: 12px; }}
.jira-match-link {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    margin: 3px 4px 3px 0;
    border-radius: 4px;
    background: var(--bg-tertiary);
    border: 1px solid var(--border);
    color: var(--accent-blue);
    font-size: 12px;
    font-family: var(--font-mono);
    text-decoration: none;
    transition: background 0.15s;
}}
.jira-match-link:hover {{ background: var(--bg-hover); text-decoration: underline; }}
.jira-match-status {{ color: var(--text-muted); font-size: 11px; }}
.failure-body {{
    padding: 0 20px 20px;
    border-top: 1px solid var(--border);
}}
.failure-body h4 {{
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
.detail-grid {{
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 4px 16px;
    font-size: 13px;
    margin-top: 8px;
}}
.detail-label {{ color: var(--text-muted); font-weight: 600; }}
.detail-value {{ color: var(--text-primary); font-family: var(--font-mono); font-size: 12px; }}

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
    .header-content {{ flex-direction: column; align-items: flex-start; }}
    .env-chips {{ margin-left: 0; }}
}}
@media (max-width: 480px) {{
    .failure-summary {{ font-size: 12px; gap: 8px; }}
}}
</style>
</head>
<body>
<div class="container">
""")

    # --- STICKY HEADER ---
    parts.append(f"""
<div class="sticky-header">
  <div class="header-content">
    <h1>{e(job_name)}</h1>
    <span class="failure-badge">{total_failures} failure{"s" if total_failures != 1 else ""}</span>
    <div class="env-chips">
      <span class="env-chip">Build: #{e(build_number)}</span>
      <span class="env-chip">Status: {e(result.status)}</span>
      <span class="env-chip">AI: {e(provider_info)}</span>
      <span class="env-chip"><a href="{e(jenkins_url_str)}" target="_blank" rel="noopener">Jenkins</a></span>
    </div>
  </div>
</div>
""")

    # --- NO FAILURES CASE ---
    if total_failures == 0 and not result.child_job_analyses:
        parts.append("""
<div class="no-failures">
  <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--accent-green)" stroke-width="2">
    <circle cx="12" cy="12" r="10"/>
    <path d="M8 12l2.5 2.5L16 9"/>
  </svg>
  <p>No failures detected in this build.</p>
</div>
""")
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

    # --- FAILURE CARDS (grouped by root cause) ---
    groups: list[dict] = []
    if result.failures:
        groups = _group_failures(result.failures)
        parts.append('<h2 class="section-title">Root Cause Analysis</h2>')
        for group in groups:
            _render_group_card(parts, group, e)

    # --- CHILD JOB ANALYSES ---
    if result.child_job_analyses:
        parts.append('<h2 class="section-title">Child Job Analyses</h2>')
        _render_child_jobs(parts, result.child_job_analyses, e)

    # --- ALL FAILURES TABLE ---
    if result.failures:
        parts.append("""
<h2 class="section-title">All Failures</h2>
<div class="table-container">
<table>
<thead>
<tr>
  <th>#</th>
  <th>Test Name</th>
  <th>Error</th>
  <th>Classification</th>
  <th>Bug Ref</th>
</tr>
</thead>
<tbody>
""")
        # Build lookup from failure analysis key to bug_id
        analysis_to_bug: dict[str, str] = {}
        for group in groups:
            key = _grouping_key(group["analysis"])
            analysis_to_bug[key] = group["bug_id"]

        for idx, f in enumerate(result.failures, start=1):
            cls = f.analysis.classification or "Unknown"
            cls_class = _classification_css_class(cls)
            bug_ref = analysis_to_bug.get(_grouping_key(f.analysis), "")
            parts.append(f"""<tr>
  <td>{idx}</td>
  <td class="test-name">{e(f.test_name)}</td>
  <td class="error-cell" title="{e(f.error)}">{e(f.error)}</td>
  <td><span class="classification-tag {e(cls_class)}">{e(cls)}</span></td>
  <td><span class="bug-id">{e(bug_ref)}</span></td>
</tr>
""")
        parts.append("</tbody>\n</table>\n</div>")

    # --- KEY TAKEAWAY ---
    _append_takeaway(parts, result.summary, e)

    # --- FOOTER ---
    _append_footer(
        parts, job_name, build_number, result.job_id, provider_info, jenkins_url_str, e
    )

    parts.append("</div>\n</body>\n</html>")
    return "\n".join(parts)


def _format_provider(ai_provider: str, ai_model: str) -> str:
    """Format AI provider and model for display.

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


def _classification_css_class(classification: str) -> str:
    """Return a CSS class suffix for a classification string.

    Args:
        classification: Classification text like "PRODUCT BUG".

    Returns:
        A CSS-safe class name like "product-bug" or "code-issue".
    """
    lower = classification.lower().strip()
    if "product" in lower and "bug" in lower:
        return "product-bug"
    if "code" in lower and "issue" in lower:
        return "code-issue"
    return "unknown"


def _grouping_key(detail: AnalysisDetail) -> str:
    """Compute a grouping key for root cause aggregation.

    Groups by classification + first 4 words of the bug title
    (for product bugs) or classification + file path (for code issues).
    Falls back to full JSON match when neither is available.

    The first 4 words of the title capture the essence of the bug
    while tolerating minor phrasing variations from different AI calls.
    """
    cls = (detail.classification or "").strip().upper()

    # For product bugs, group by classification + first 4 words of title
    if (
        isinstance(detail.product_bug_report, ProductBugReport)
        and detail.product_bug_report.title
    ):
        title = detail.product_bug_report.title.strip().lower()
        words = title.split()[:4]
        normalized_title = " ".join(words)
        return f"{cls}|title:{normalized_title}"

    # For code issues, group by classification + file path
    if isinstance(detail.code_fix, CodeFix) and detail.code_fix.file:
        return f"{cls}|file:{detail.code_fix.file.strip()}"

    # Fallback: full JSON match
    return detail.model_dump_json()


def _group_failures(failures: list[FailureAnalysis]) -> list[dict]:
    """Group failures that share the same root cause.

    Groups by classification + first 4 words of the bug title
    (for product bugs) or classification + file path (for code issues).
    Falls back to full AnalysisDetail JSON match when neither is available.

    After initial grouping, singleton groups are merged into the dominant
    group (if one exists with >50% of failures) when they share the same
    classification. This handles cases where the AI uses different phrasing
    for the same root cause.

    Args:
        failures: List of FailureAnalysis instances to group.

    Returns:
        A list of dicts, each containing:
        - ``analysis``: the representative AnalysisDetail
        - ``failures``: list of FailureAnalysis in this group
        - ``bug_id``: a short identifier like ``"BUG-1"``
    """
    if not failures:
        return []

    # First pass: group by key
    groups_map: dict[str, list[FailureAnalysis]] = {}
    order: list[str] = []
    for f in failures:
        key = _grouping_key(f.analysis)
        if key not in groups_map:
            groups_map[key] = []
            order.append(key)
        groups_map[key].append(f)

    # Second pass: merge singletons into the dominant group
    total = len(failures)
    if total > 2 and len(groups_map) > 1:
        # Find the largest group
        dominant_key = max(groups_map, key=lambda k: len(groups_map[k]))
        dominant_size = len(groups_map[dominant_key])

        if dominant_size > total * 0.5:
            # Get the classification of the dominant group
            dominant_cls = (
                groups_map[dominant_key][0].analysis.classification.strip().upper()
            )
            # Merge singletons with the same classification
            keys_to_remove: list[str] = []
            for key in order:
                if key == dominant_key:
                    continue
                if len(groups_map[key]) == 1:
                    singleton_cls = (
                        groups_map[key][0].analysis.classification.strip().upper()
                    )
                    if singleton_cls == dominant_cls:
                        groups_map[dominant_key].extend(groups_map[key])
                        keys_to_remove.append(key)

            for key in keys_to_remove:
                del groups_map[key]
                order.remove(key)

    # Build final groups
    groups: list[dict] = []
    for idx, key in enumerate(order, start=1):
        group_failures = groups_map[key]
        groups.append(
            {
                "analysis": group_failures[0].analysis,
                "failures": group_failures,
                "bug_id": f"BUG-{idx}",
            }
        )
    return groups


def _render_failure_card(
    parts: list[str],
    failure: FailureAnalysis,
    e: Callable[[str], str],
    indent: str = "",
) -> None:
    """Render a single collapsible failure card.

    Args:
        parts: List of HTML string parts to append to.
        failure: A FailureAnalysis instance to render.
        e: HTML escape function reference.
        indent: HTML indentation prefix for nested cards.
    """
    detail = failure.analysis
    cls = detail.classification or "Unknown"
    cls_class = _classification_css_class(cls)

    parts.append(f"""{indent}<details class="failure-card">
{indent}  <summary class="failure-summary">
{indent}    <span class="failure-title">{e(failure.test_name)}</span>
{indent}    <span class="classification-tag {e(cls_class)}">{e(cls)}</span>
{indent}  </summary>
{indent}  <div class="failure-body">
""")

    # Error
    parts.append(f"""{indent}    <h4>Error</h4>
{indent}    <pre class="error-pre">{e(failure.error)}</pre>
""")

    # Analysis text
    if detail.details:
        parts.append(f"""{indent}    <h4>Analysis</h4>
{indent}    <pre class="analysis-pre">{e(detail.details)}</pre>
""")

    # Code Fix details
    if isinstance(detail.code_fix, CodeFix):
        fix = detail.code_fix
        parts.append(f"""{indent}    <h4>Code Fix</h4>
{indent}    <div class="detail-grid">
{indent}      <span class="detail-label">File:</span><span class="detail-value">{e(fix.file)}</span>
{indent}      <span class="detail-label">Line:</span><span class="detail-value">{e(fix.line)}</span>
{indent}      <span class="detail-label">Change:</span><span class="detail-value">{e(fix.change)}</span>
{indent}    </div>
""")

    # Product Bug Report details
    if isinstance(detail.product_bug_report, ProductBugReport):
        bug = detail.product_bug_report
        parts.append(f"""{indent}    <h4>Product Bug Report</h4>
{indent}    <div class="detail-grid">
{indent}      <span class="detail-label">Title:</span><span class="detail-value">{e(bug.title)}</span>
{indent}      <span class="detail-label">Severity:</span><span class="detail-value">{e(bug.severity)}</span>
{indent}      <span class="detail-label">Component:</span><span class="detail-value">{e(bug.component)}</span>
{indent}      <span class="detail-label">Description:</span><span class="detail-value">{e(bug.description)}</span>
{indent}      <span class="detail-label">Evidence:</span><span class="detail-value">{e(bug.evidence)}</span>
{indent}    </div>
""")
        # Jira matches
        if bug.jira_matches:
            _render_jira_matches(parts, bug.jira_matches, e, indent)

    # Affected tests
    if detail.affected_tests:
        parts.append(
            f'{indent}    <h4>Affected Tests ({len(detail.affected_tests)})</h4>\n{indent}    <ul style="list-style:none;padding:0">\n'
        )
        for t in detail.affected_tests:
            parts.append(
                f'{indent}      <li style="padding:4px 0;font-size:13px;color:var(--text-secondary)"><code style="font-family:var(--font-mono);font-size:12px;color:var(--text-primary)">{e(t)}</code></li>\n'
            )
        parts.append(f"{indent}    </ul>\n")

    parts.append(f"""{indent}  </div>
{indent}</details>
""")


def _render_group_card(
    parts: list[str],
    group: dict,
    e: Callable[[str], str],
    indent: str = "",
) -> None:
    """Render a collapsible card for a group of failures sharing the same analysis.

    Args:
        parts: List of HTML string parts to append to.
        group: Dict with keys 'analysis' (AnalysisDetail), 'failures' (list), 'bug_id' (str).
        e: HTML escape function reference.
        indent: HTML indentation prefix for nested cards.
    """
    detail = group["analysis"]
    bug_id = group["bug_id"]
    failures = group["failures"]
    cls = detail.classification or "Unknown"
    cls_class = _classification_css_class(cls)
    test_count = len(failures)
    test_label = f"{test_count} test{'s' if test_count != 1 else ''}"

    # Severity from product bug report if available
    severity = ""
    if (
        isinstance(detail.product_bug_report, ProductBugReport)
        and detail.product_bug_report.severity
    ):
        severity = detail.product_bug_report.severity.lower()
    if severity not in ("critical", "high", "medium", "low"):
        severity = "unknown"

    # Card title: bug report title, or first test error
    if (
        isinstance(detail.product_bug_report, ProductBugReport)
        and detail.product_bug_report.title
    ):
        card_title = detail.product_bug_report.title
    else:
        card_title = failures[0].error or failures[0].test_name

    parts.append(f"""{indent}<details class="bug-card">
{indent}  <summary class="bug-summary">
{indent}    <span class="bug-id">{e(bug_id)}</span>
{indent}    <span class="bug-title">{e(card_title)}</span>
{indent}    <span class="bug-count">{e(test_label)}</span>
{indent}    <span class="classification-tag {e(cls_class)}">{e(cls)}</span>
{indent}    <span class="severity-tag-inline {e(severity)}">{e(severity.upper())}</span>
{indent}  </summary>
{indent}  <div class="bug-body">
""")

    # AI Analysis
    if detail.details:
        parts.append(f"""{indent}    <div class="bug-analysis">
{indent}      <h4>AI Analysis</h4>
{indent}      <pre class="analysis-pre">{e(detail.details)}</pre>
{indent}    </div>
""")

    # Code Fix details (improvement over reference)
    if isinstance(detail.code_fix, CodeFix):
        fix = detail.code_fix
        parts.append(f"""{indent}    <h4>Code Fix</h4>
{indent}    <div class="detail-grid">
{indent}      <span class="detail-label">File:</span><span class="detail-value">{e(fix.file)}</span>
{indent}      <span class="detail-label">Line:</span><span class="detail-value">{e(fix.line)}</span>
{indent}      <span class="detail-label">Change:</span><span class="detail-value">{e(fix.change)}</span>
{indent}    </div>
""")

    # Product Bug Report details (improvement over reference)
    if isinstance(detail.product_bug_report, ProductBugReport):
        bug = detail.product_bug_report
        parts.append(f"""{indent}    <h4>Product Bug Report</h4>
{indent}    <div class="detail-grid">
{indent}      <span class="detail-label">Title:</span><span class="detail-value">{e(bug.title)}</span>
{indent}      <span class="detail-label">Severity:</span><span class="detail-value">{e(bug.severity)}</span>
{indent}      <span class="detail-label">Component:</span><span class="detail-value">{e(bug.component)}</span>
{indent}      <span class="detail-label">Description:</span><span class="detail-value">{e(bug.description)}</span>
{indent}      <span class="detail-label">Evidence:</span><span class="detail-value">{e(bug.evidence)}</span>
{indent}    </div>
""")
        # Jira matches
        if bug.jira_matches:
            _render_jira_matches(parts, bug.jira_matches, e, indent)

    # Affected Tests
    parts.append(f"""{indent}    <div class="bug-tests">
{indent}      <h4>Affected Tests ({test_count})</h4>
{indent}      <ul>
""")
    for f in failures:
        parts.append(f"{indent}        <li><code>{e(f.test_name)}</code></li>\n")
    parts.append(f"""{indent}      </ul>
{indent}    </div>
""")

    # Error
    parts.append(f"""{indent}    <div class="bug-error">
{indent}      <h4>Error</h4>
{indent}      <pre class="error-pre">{e(failures[0].error)}</pre>
{indent}    </div>
""")

    parts.append(f"""{indent}  </div>
{indent}</details>
""")


def _render_jira_matches(
    parts: list[str],
    matches: list[JiraMatch],
    e: Callable[[str], str],
    indent: str = "",
) -> None:
    """Render Jira match links.

    Args:
        parts: List of HTML string parts to append to.
        matches: List of JiraMatch objects to render.
        e: HTML escape function reference.
        indent: HTML indentation prefix.
    """
    parts.append(f"{indent}    <h4>Possible Jira Matches ({len(matches)})</h4>\n")
    parts.append(f'{indent}    <div class="jira-matches">\n')
    for match in matches:
        parts.append(
            f'{indent}      <a class="jira-match-link" href="{e(match.url)}" '
            f'target="_blank" rel="noopener">'
            f"{e(match.key)}: {e(match.summary)} "
            f'<span class="jira-match-status">[{e(match.status)}]</span>'
            f"</a>\n"
        )
    parts.append(f"{indent}    </div>\n")


def _render_child_jobs(
    parts: list[str],
    children: list[ChildJobAnalysis],
    e: Callable[[str], str],
    depth: int = 0,
    max_depth: int = 10,
) -> None:
    """Render child job analysis sections recursively.

    Args:
        parts: List of HTML string parts to append to.
        children: Child job analyses to render.
        e: HTML escape function reference.
        depth: Current recursion depth.
        max_depth: Maximum recursion depth for nested children.
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
            child_groups = _group_failures(child.failures)
            for group in child_groups:
                _render_group_card(parts, group, e, indent="    ")

        # Recurse into nested children
        if child.failed_children and depth < max_depth:
            _render_child_jobs(
                parts, child.failed_children, e, depth=depth + 1, max_depth=max_depth
            )

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


def format_status_page(job_id: str, status: str, result: dict) -> str:
    """Generate a status page for a job that is still processing.

    Uses the same dark theme as the full report, with auto-refresh
    and a simple status indicator.

    Args:
        job_id: The analysis job identifier.
        status: Current job status (pending/running).
        result: The job result dict from storage.

    Returns:
        A complete HTML document as a string.
    """
    e = html.escape

    jenkins_url = result.get("jenkins_url", "")
    created_at = result.get("created_at", "")

    status_icon = "&#9203;" if status == "running" else "&#8987;"
    status_label = "Analyzing..." if status == "running" else "Queued"
    status_detail = (
        "AI is analyzing the Jenkins build failures. This page will auto-refresh."
        if status == "running"
        else "Job is queued and waiting to start. This page will auto-refresh."
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Analysis {e(status_label)} - {e(job_id)}</title>
<style>
:root {{
    --bg-primary: #0d1117;
    --bg-secondary: #161b22;
    --border: #30363d;
    --text-primary: #e6edf3;
    --text-secondary: #8b949e;
    --text-muted: #6e7681;
    --accent-blue: #58a6ff;
    --accent-yellow: #d29922;
    --font-mono: 'SF Mono', 'Cascadia Code', Consolas, monospace;
    --font-sans: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    --radius: 8px;
}}
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
    font-family: var(--font-sans);
    background: var(--bg-primary);
    color: var(--text-primary);
    line-height: 1.6;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
}}
.status-container {{
    max-width: 520px;
    width: 100%;
    padding: 40px;
    text-align: center;
}}
.status-icon {{
    font-size: 48px;
    margin-bottom: 20px;
    animation: pulse 2s ease-in-out infinite;
}}
@keyframes pulse {{
    0%, 100% {{ opacity: 1; }}
    50% {{ opacity: 0.5; }}
}}
.status-label {{
    font-size: 24px;
    font-weight: 700;
    margin-bottom: 8px;
    color: var(--accent-yellow);
}}
.status-detail {{
    font-size: 14px;
    color: var(--text-secondary);
    margin-bottom: 32px;
}}
.info-card {{
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 20px;
    text-align: left;
}}
.info-row {{
    display: flex;
    justify-content: space-between;
    padding: 8px 0;
    font-size: 13px;
    border-bottom: 1px solid var(--border);
}}
.info-row:last-child {{ border-bottom: none; }}
.info-label {{ color: var(--text-muted); font-weight: 600; }}
.info-value {{ color: var(--text-primary); font-family: var(--font-mono); font-size: 12px; }}
.info-value a {{ color: var(--accent-blue); text-decoration: none; }}
.info-value a:hover {{ text-decoration: underline; }}
.spinner {{
    display: inline-block;
    width: 16px;
    height: 16px;
    border: 2px solid var(--border);
    border-top-color: var(--accent-yellow);
    border-radius: 50%;
    animation: spin 1s linear infinite;
    vertical-align: middle;
    margin-right: 6px;
}}
@keyframes spin {{
    to {{ transform: rotate(360deg); }}
}}
.refresh-note {{
    margin-top: 20px;
    font-size: 12px;
    color: var(--text-muted);
}}
</style>
</head>
<body>
<div class="status-container">
    <div class="status-icon">{status_icon}</div>
    <div class="status-label"><span class="spinner"></span>{e(status_label)}</div>
    <div class="status-detail">{e(status_detail)}</div>
    <div class="info-card">
        <div class="info-row">
            <span class="info-label">Job ID</span>
            <span class="info-value">{e(job_id)}</span>
        </div>
        <div class="info-row">
            <span class="info-label">Status</span>
            <span class="info-value">{e(status)}</span>
        </div>
        <div class="info-row">
            <span class="info-label">Created</span>
            <span class="info-value">{e(created_at)}</span>
        </div>
        {
        ""
        if not jenkins_url
        else f'''<div class="info-row">
            <span class="info-label">Jenkins</span>
            <span class="info-value"><a href="{e(jenkins_url)}" target="_blank" rel="noopener">View Build</a></span>
        </div>'''
    }
    </div>
    <div class="refresh-note">Auto-refreshing every 10 seconds</div>
</div>
</body>
</html>"""
