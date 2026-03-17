"""HTML report generation for Jenkins job analysis results.

Generates a self-contained, dark-themed HTML report from analysis results.
All CSS is inlined so the report can be opened directly in any browser
without external dependencies.
"""

import base64
import html
import json
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
from jenkins_job_insight.storage import count_all_failures

FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <rect width="32" height="32" rx="6" fill="#0d1117"/>
  <circle cx="13" cy="13" r="7" fill="none" stroke="#58a6ff" stroke-width="2.5"/>
  <line x1="18" y1="18" x2="26" y2="26" stroke="#58a6ff" stroke-width="2.5" stroke-linecap="round"/>
  <circle cx="13" cy="11" r="1.5" fill="#f85149"/>
  <path d="M10 15.5 Q13 18 16 15.5" fill="none" stroke="#f85149" stroke-width="1.5" stroke-linecap="round"/>
</svg>"""

FAVICON_DATA_URI = (
    "data:image/svg+xml;base64," + base64.b64encode(FAVICON_SVG.encode()).decode()
)


def _common_css() -> str:
    """Return the shared CSS rules used by both the analysis report and dashboard.

    Includes CSS custom properties, base element resets, body, container,
    sticky header, and report footer styles. Page-specific rules are added
    by each caller.

    Returns:
        A CSS string (without ``<style>`` tags) ready to embed directly.
    """
    return """\
:root {
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
}
*,*::before,*::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: var(--font-sans);
    background: var(--bg-primary);
    color: var(--text-primary);
    line-height: 1.6;
    min-height: 100vh;
}
.container { max-width: 1200px; margin: 0 auto; padding: 0 24px 60px; }

/* Header */
.sticky-header {
    position: sticky;
    top: 0;
    z-index: 100;
    background: var(--bg-secondary);
    border-bottom: 1px solid var(--border);
    padding: 16px 24px;
    margin: 0 -24px 32px;
}
.header-content { max-width: 1200px; margin: 0 auto; display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.header-content h1 { font-size: 20px; font-weight: 700; flex-shrink: 0; }

/* Footer */
.report-footer {
    margin-top: 48px;
    padding: 24px 0;
    border-top: 1px solid var(--border);
    font-size: 12px;
    color: var(--text-muted);
    display: flex;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 12px;
}
.report-footer a { color: var(--accent-blue); text-decoration: none; }
.report-footer a:hover { text-decoration: underline; }

/* Responsive */
@media (max-width: 768px) {
    .header-content { flex-direction: column; align-items: flex-start; }
}"""


def format_result_as_html(result: AnalysisResult, completed_at: str = "") -> str:
    """Generate a self-contained HTML report for an analysis result.

    Produces a complete HTML document with inline CSS using a dark
    GitHub-inspired theme.  The report includes failure cards, a
    detail table, and child job sections.

    Args:
        result: The analysis result to render.
        completed_at: Optional timestamp string for when the analysis completed.

    Returns:
        A complete HTML document as a string.
    """
    e = html.escape

    job_name = result.job_name or "Unknown"
    build_number = str(result.build_number) if result.build_number else ""
    provider_info = _format_provider(result.ai_provider, result.ai_model)
    jenkins_url_str = str(result.jenkins_url) if result.jenkins_url else ""
    total_failures = count_all_failures(result.model_dump())

    parts: list[str] = []

    # --- HTML HEAD ---
    parts.append(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Jenkins Analysis - {e(job_name)} #{e(build_number)}</title>
<link rel="icon" href="{FAVICON_DATA_URI}">
<style>
{_common_css()}
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
.status-chip {{
    font-size: 11px;
    font-weight: 700;
    padding: 3px 10px;
    border-radius: 12px;
    letter-spacing: 0.3px;
    white-space: nowrap;
    display: inline-flex;
    align-items: center;
    gap: 4px;
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
.regenerate-btn {{
    font-size: 12px;
    padding: 4px 10px;
    border-radius: 6px;
    background: var(--bg-tertiary);
    border: 1px solid var(--border);
    color: var(--accent-blue);
    cursor: pointer;
    text-decoration: none;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    transition: background 0.15s, border-color 0.15s;
}}
.regenerate-btn:hover {{
    background: var(--bg-hover);
    border-color: var(--accent-blue);
}}

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

/* No failures */
.no-failures {{
    text-align: center;
    padding: 60px 20px;
    color: var(--text-muted);
    font-size: 16px;
}}
.no-failures svg {{ margin-bottom: 16px; }}

/* Reviewed toggle */
.reviewed-toggle {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    padding: 4px 10px;
    border-radius: 6px;
    background: var(--bg-tertiary);
    border: 1px solid var(--border);
    color: var(--text-secondary);
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
    white-space: nowrap;
}}
.reviewed-toggle:hover {{
    background: var(--bg-hover);
    border-color: var(--accent-blue);
}}
.reviewed-toggle.checked {{
    background: rgba(63, 185, 80, 0.15);
    border-color: var(--accent-green);
    color: var(--accent-green);
}}

/* Comments section */
.comments-section {{
    margin-top: 16px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
}}
.comments-header {{
    background: var(--bg-tertiary);
    padding: 10px 16px;
    border-bottom: 1px solid var(--border);
    font-size: 13px;
    font-weight: 600;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
.comment-item {{
    padding: 10px 16px;
    border-bottom: 1px solid var(--border);
    font-size: 13px;
}}
.comment-timestamp {{
    font-size: 11px;
    font-family: var(--font-mono);
    color: var(--text-muted);
    margin-bottom: 4px;
}}
.comment-text {{
    color: var(--text-secondary);
    white-space: pre-wrap;
}}
.comment-text a {{
    color: var(--accent-blue);
    text-decoration: none;
}}
.comment-text a:hover {{ text-decoration: underline; }}
.enrichment-badge {{
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 1px 6px;
    border-radius: 4px;
    font-size: 11px;
    font-family: var(--font-mono);
    font-weight: 700;
    margin-left: 6px;
}}
.comment-input-row {{
    padding: 10px 16px;
    background: var(--bg-primary);
    display: flex;
    gap: 8px;
}}
.comment-input {{
    flex: 1;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 8px 12px;
    color: var(--text-primary);
    font-size: 13px;
    font-family: var(--font-sans);
    outline: none;
    transition: border-color 0.15s;
    resize: vertical;
    min-height: 36px;
    max-height: 200px;
}}
.comment-input::placeholder {{ color: var(--text-muted); }}
.comment-input:focus {{ border-color: var(--accent-blue); }}
.comment-add-btn {{
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 600;
    color: var(--accent-blue);
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
}}
.comment-add-btn:hover {{
    background: var(--bg-hover);
    border-color: var(--accent-blue);
}}
.comment-test-select {{
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 8px;
    color: var(--text-primary);
    font-size: 12px;
    font-family: var(--font-mono);
}}

/* Responsive (page-specific) */
@media (max-width: 768px) {{
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
    <span id="overall-review-status" class="status-chip" style="display:none"></span>
    <div class="env-chips">
      <span class="env-chip">Build: #{e(build_number)}</span>
      <span class="env-chip">Status: {e(result.status)}</span>
      <span class="env-chip">AI: {e(provider_info)}</span>
      {f'<span class="env-chip">Analyzed: {e(completed_at)}</span>' if completed_at else ""}
      {f'<span class="env-chip"><a href="{e(jenkins_url_str)}" target="_blank" rel="noopener">Jenkins</a></span>' if jenkins_url_str else ""}
      <a class="regenerate-btn" href="?refresh=1" title="Regenerate report from stored data"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 4v6h6"/><path d="M23 20v-6h-6"/><path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 0 1 3.51 15"/></svg> Regenerate</a>
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
            _render_group_card(parts, group, e, job_id=result.job_id)

    # --- CHILD JOB ANALYSES ---
    if result.child_job_analyses:
        parts.append('<h2 class="section-title">Child Job Analyses</h2>')
        _render_child_jobs(parts, result.child_job_analyses, e, job_id=result.job_id)

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

    # --- INLINE JAVASCRIPT ---
    parts.append(f"""
<script>
const JOB_ID = "{e(result.job_id)}";
// Derive base path for API calls (works behind reverse proxies with path prefixes)
const BASE_PATH = window.location.pathname.replace(/\\/results\\/.*$/, '');

async function loadCommentsAndReviews() {{
    try {{
        const resp = await fetch(`${{BASE_PATH}}/results/${{JOB_ID}}/comments`);
        if (!resp.ok) return;
        const data = await resp.json();

        data.comments.forEach(c => {{
            const childJob = c.child_job_name || '';
            const childBuildNumber = c.child_build_number || 0;
            const testNames = c.test_name;
            document.querySelectorAll('.comments-section').forEach(section => {{
                const sectionTests = JSON.parse(section.dataset.testNames || '[]');
                const sectionChild = section.dataset.childJob || '';
                const sectionChildBuild = parseInt(section.dataset.childBuild || '0');
                if (sectionTests.includes(testNames) && sectionChild === childJob && sectionChildBuild === childBuildNumber) {{
                    appendCommentToList(section, c);
                }}
            }});
        }});

        document.querySelectorAll('.comments-section').forEach(section => {{
            const count = section.querySelectorAll('.comment-item').length;
            section.querySelector('.comment-count').textContent = count;
        }});

        for (const [key, review] of Object.entries(data.reviews)) {{
            if (review.reviewed) {{
                document.querySelectorAll('.reviewed-toggle').forEach(toggle => {{
                    const testName = toggle.dataset.testName;
                    const childJob = toggle.dataset.childJob || '';
                    const toggleChildBuild = parseInt(toggle.dataset.childBuild || '0');
                    const toggleKey = childJob ? childJob + '#' + toggleChildBuild + '::' + testName : testName;
                    if (toggleKey === key) {{
                        toggle.classList.add('checked');
                        toggle.querySelector('input').checked = true;
                    }}
                }});
            }}
        }}
        updateReviewBadges();
    }} catch (err) {{
        console.warn('Failed to load comments:', err);
    }}
}}

function updateReviewBadges() {{
    // Overall job review status
    const allToggles = document.querySelectorAll('.reviewed-toggle');
    const totalTests = allToggles.length;
    const reviewedTests = document.querySelectorAll('.reviewed-toggle.checked').length;

    const overallBadge = document.getElementById('overall-review-status');
    if (overallBadge && totalTests > 0) {{
        overallBadge.style.display = '';
        if (reviewedTests >= totalTests) {{
            overallBadge.textContent = '\u2713 Fully Reviewed';
            overallBadge.style.background = 'rgba(63,185,80,0.15)';
            overallBadge.style.color = 'var(--accent-green)';
        }} else if (reviewedTests > 0) {{
            overallBadge.textContent = reviewedTests + '/' + totalTests + ' Reviewed';
            overallBadge.style.background = 'rgba(210,153,34,0.15)';
            overallBadge.style.color = 'var(--accent-yellow)';
        }} else {{
            overallBadge.textContent = 'Needs Review';
            overallBadge.style.background = 'rgba(248,81,73,0.12)';
            overallBadge.style.color = 'var(--accent-red)';
        }}
    }}

    // Per child job review status
    document.querySelectorAll('.child-review-status').forEach(badge => {{
        const job = badge.closest('.child-job');
        if (!job) return;
        const toggles = job.querySelectorAll('.reviewed-toggle');
        const total = toggles.length;
        const checked = job.querySelectorAll('.reviewed-toggle.checked').length;
        if (total === 0) return;

        badge.style.display = '';
        if (checked >= total) {{
            badge.textContent = '\u2713 Reviewed';
            badge.style.background = 'rgba(63,185,80,0.15)';
            badge.style.color = 'var(--accent-green)';
        }} else if (checked > 0) {{
            badge.textContent = checked + '/' + total;
            badge.style.background = 'rgba(210,153,34,0.15)';
            badge.style.color = 'var(--accent-yellow)';
        }} else {{
            badge.textContent = 'Needs Review';
            badge.style.background = 'rgba(248,81,73,0.12)';
            badge.style.color = 'var(--accent-red)';
        }}
    }});

    // Per bug card review status
    document.querySelectorAll('.group-review-status').forEach(badge => {{
        const card = badge.closest('.bug-card');
        if (!card) return;
        const toggles = card.querySelectorAll('.reviewed-toggle');
        const total = toggles.length;
        const checked = card.querySelectorAll('.reviewed-toggle.checked').length;
        if (total === 0) return;

        badge.style.display = '';
        if (checked >= total) {{
            badge.textContent = '\u2713 Reviewed';
            badge.style.background = 'rgba(63,185,80,0.15)';
            badge.style.color = 'var(--accent-green)';
        }} else if (checked > 0) {{
            badge.textContent = checked + '/' + total;
            badge.style.background = 'rgba(210,153,34,0.15)';
            badge.style.color = 'var(--accent-yellow)';
        }} else {{
            badge.textContent = 'Needs Review';
            badge.style.background = 'rgba(248,81,73,0.12)';
            badge.style.color = 'var(--accent-red)';
        }}
    }});
}}

function appendCommentToList(section, comment) {{
    const list = section.querySelector('.comment-list');
    const item = document.createElement('div');
    item.className = 'comment-item';
    if (comment.id) item.dataset.commentId = comment.id;
    const text = autoLink(escapeHtml(comment.comment));
    var userLabel = comment.username ? '<span style="font-family:var(--font-mono);font-size:11px;color:var(--accent-purple);margin-right:6px;">' + escapeHtml(comment.username) + '</span>' : '';
    // Safe: escapeHtml sanitizes all user content, autoLink only adds <a> tags for URL patterns
    item.innerHTML = '<div class="comment-timestamp">' + (comment.created_at || '') + '</div><div class="comment-text">' + userLabel + text + '</div>';  // nosec: innerHTML is safe here because escapeHtml sanitizes user input
    list.appendChild(item);
}}

function escapeHtml(str) {{
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}}

function autoLink(text) {{
    // GitHub PR URLs -> org/repo#number
    text = text.replace(
        /https?:\\/\\/github\\.com\\/([^\\/]+)\\/([^\\/]+)\\/pull\\/(\\d+)(?:[^\\s<]*)/g,
        '<a href="https://github.com/$1/$2/pull/$3" target="_blank" rel="noopener">$1/$2#$3</a>'
    );
    // Jira browse URLs -> TICKET-KEY (strip query params)
    text = text.replace(
        /https?:\\/\\/[^\\s<]*\\/browse\\/([A-Z][A-Z0-9]+-\\d+)(?:\\?[^\\s<]*)?/g,
        function(match, key) {{
            var cleanUrl = match.split('?')[0];
            return '<a href="' + cleanUrl + '" target="_blank" rel="noopener">' + key + '</a>';
        }}
    );
    // Other URLs -> clickable with full URL text
    text = text.replace(
        /(https?:\\/\\/[^\\s<]+)/g,
        function(match) {{
            if (match.includes('github.com') && match.includes('/pull/')) return match;
            if (match.includes('/browse/')) return match;
            return '<a href="' + match + '" target="_blank" rel="noopener">' + match + '</a>';
        }}
    );
    return text;
}}

async function toggleReviewed(label) {{
    const checkbox = label.querySelector('input');
    const testName = label.dataset.testName;
    const childJob = label.dataset.childJob || '';
    const childBuild = parseInt(label.dataset.childBuild || '0');
    const reviewed = checkbox.checked;

    try {{
        const resp = await fetch(`${{BASE_PATH}}/results/${{JOB_ID}}/reviewed`, {{
            method: 'PUT',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{test_name: testName, child_job_name: childJob, child_build_number: childBuild, reviewed: reviewed}}),
        }});
        if (resp.ok) {{
            label.classList.toggle('checked', reviewed);
            updateReviewBadges();
        }} else {{
            checkbox.checked = !reviewed;
            console.warn('Failed to toggle reviewed: server returned', resp.status);
        }}
    }} catch (err) {{
        checkbox.checked = !reviewed;
        console.warn('Failed to toggle reviewed:', err);
    }}
}}

async function addComment(btn) {{
    const row = btn.closest('.comment-input-row');
    const input = row.querySelector('.comment-input');
    const comment = input.value.trim();
    if (!comment) return;

    const section = btn.closest('.comments-section');
    const selector = section.querySelector('.comment-test-select');
    const testName = selector.value;
    const childJob = section.dataset.childJob || '';
    const childBuild = parseInt(section.dataset.childBuild || '0');

    try {{
        const resp = await fetch(`${{BASE_PATH}}/results/${{JOB_ID}}/comments`, {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{test_name: testName, child_job_name: childJob, child_build_number: childBuild, comment: comment}}),
        }});
        if (resp.ok) {{
            const result = await resp.json();
            const now = new Date().toISOString().replace('T', ' ').substring(0, 19);
            var currentUser = '';
            var uc = document.cookie.split('; ').find(function(c) {{ return c.startsWith('jji_username='); }});
            if (uc) currentUser = decodeURIComponent(uc.split('=')[1]);
            appendCommentToList(section, {{id: result.id, comment: comment, created_at: now, test_name: testName, username: currentUser}});
            const count = section.querySelectorAll('.comment-item').length;
            section.querySelector('.comment-count').textContent = count;
            input.value = '';
            await loadEnrichments();
        }}
    }} catch (err) {{
        console.warn('Failed to add comment:', err);
    }}
}}

async function loadEnrichments() {{
    try {{
        const resp = await fetch(`${{BASE_PATH}}/results/${{JOB_ID}}/enrich-comments`, {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
        }});
        if (!resp.ok) return;
        const data = await resp.json();

        // Remove existing enrichment badges to avoid duplicates on re-runs
        document.querySelectorAll('.enrichment-badge').forEach(el => el.remove());

        for (const [commentId, enrichments] of Object.entries(data.enrichments)) {{
            const commentEl = document.querySelector(`.comment-item[data-comment-id="${{commentId}}"]`);
            if (!commentEl) continue;
            const textEl = commentEl.querySelector('.comment-text');
            for (const e of enrichments) {{
                const badge = document.createElement('span');
                badge.className = 'enrichment-badge';
                const statusUpper = e.status.toUpperCase();
                if (e.status === 'merged') {{
                    badge.style.background = 'rgba(63,185,80,0.15)';
                    badge.style.color = 'var(--accent-green)';
                }} else if (e.status === 'open') {{
                    badge.style.background = 'rgba(63,185,80,0.15)';
                    badge.style.color = 'var(--accent-green)';
                }} else if (e.status === 'closed') {{
                    badge.style.background = 'rgba(248,81,73,0.15)';
                    badge.style.color = 'var(--accent-red)';
                }} else {{
                    badge.style.background = 'rgba(88,166,255,0.12)';
                    badge.style.color = 'var(--accent-blue)';
                }}
                badge.textContent = statusUpper;
                textEl.appendChild(badge);
            }}
        }}
    }} catch (err) {{
        console.warn('Failed to load enrichments:', err);
    }}
}}

document.addEventListener('DOMContentLoaded', async function() {{
    document.querySelectorAll('.reviewed-toggle input[type="checkbox"]').forEach(cb => {{
        cb.addEventListener('change', function(event) {{
            event.stopPropagation();
            toggleReviewed(this.closest('.reviewed-toggle'));
        }});
    }});
    // Show current user in header
    var userCookie = document.cookie.split('; ').find(function(c) {{ return c.startsWith('jji_username='); }});
    if (userCookie) {{
        var uname = decodeURIComponent(userCookie.split('=')[1]);
        var headerContent = document.querySelector('.header-content');
        if (headerContent) {{
            var chips = headerContent.querySelector('.env-chips');
            if (chips) {{
                var userChip = document.createElement('span');
                userChip.className = 'env-chip';
                userChip.textContent = 'User: ' + uname;
                chips.appendChild(userChip);
            }}
        }}
    }}
    // Enter to send, Shift+Enter for new line
    document.querySelectorAll('.comment-input').forEach(textarea => {{
        textarea.addEventListener('keydown', function(e) {{
            if (e.key === 'Enter' && !e.shiftKey) {{
                e.preventDefault();
                const btn = this.closest('.comment-input-row').querySelector('.comment-add-btn');
                if (btn) btn.click();
            }}
        }});
    }});
    await loadCommentsAndReviews();
    await loadEnrichments();
}});
</script>
""")

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

    # Artifacts evidence
    _render_artifacts_evidence(parts, detail, e, indent)

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
    job_id: str = "",
    child_job_name: str = "",
    child_build_number: int = 0,
) -> None:
    """Render a collapsible card for a group of failures sharing the same analysis.

    Args:
        parts: List of HTML string parts to append to.
        group: Dict with keys 'analysis' (AnalysisDetail), 'failures' (list), 'bug_id' (str).
        e: HTML escape function reference.
        indent: HTML indentation prefix for nested cards.
        job_id: The job identifier for reviewed toggle data attributes.
        child_job_name: The child job name for reviewed toggle data attributes.
        child_build_number: The child build number for reviewed toggle data attributes.
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
{indent}    <span class="group-review-status status-chip" style="display:none"></span>
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

    # Artifacts evidence
    _render_artifacts_evidence(parts, detail, e, indent)

    # Affected Tests
    parts.append(f"""{indent}    <div class="bug-tests">
{indent}      <h4>Affected Tests ({test_count})</h4>
{indent}      <ul>
""")
    for f in failures:
        parts.append(
            f'{indent}        <li><label class="reviewed-toggle" data-job-id="{e(job_id)}" data-test-name="{e(f.test_name)}" data-child-job="{e(child_job_name)}" data-child-build="{child_build_number}"><input type="checkbox"> <code style="font-family:var(--font-mono);font-size:12px;color:var(--text-primary)">{e(f.test_name)}</code></label></li>\n'
        )
    parts.append(f"""{indent}      </ul>
{indent}    </div>
""")

    # Error
    parts.append(f"""{indent}    <div class="bug-error">
{indent}      <h4>Error</h4>
{indent}      <pre class="error-pre">{e(failures[0].error)}</pre>
{indent}    </div>
""")

    # Comments section (populated by JavaScript)
    # Build test name selector for multi-test groups
    if len(failures) > 1:
        select_html = f'{indent}        <select class="comment-test-select">'
        for f in failures:
            select_html += f'<option value="{e(f.test_name)}">{e(f.test_name)}</option>'
        select_html += "</select>"
    else:
        select_html = f'<input type="hidden" class="comment-test-select" value="{e(failures[0].test_name)}">'

    all_test_names = e(json.dumps([f.test_name for f in failures]))
    parts.append(f"""{indent}    <div class="comments-section" data-test-names="{all_test_names}" data-child-job="{e(child_job_name)}" data-child-build="{child_build_number}">
{indent}      <div class="comments-header">Comments (<span class="comment-count">0</span>)</div>
{indent}      <div class="comment-list"></div>
{indent}      <div class="comment-input-row">
{indent}        {select_html}
{indent}        <textarea class="comment-input" placeholder="Add a comment (bug link, PR, notes...)" rows="1"></textarea>
{indent}        <button class="comment-add-btn" onclick="addComment(this)">Add</button>
{indent}      </div>
{indent}    </div>
""")

    parts.append(f"""{indent}  </div>
{indent}</details>
""")


def _render_artifacts_evidence(
    parts: list[str], detail: AnalysisDetail, e: Callable, indent: str
) -> None:
    """Render artifacts_evidence into the HTML parts list if present."""
    if not detail.artifacts_evidence:
        return
    parts.append(f"""{indent}    <div class="detail-grid">
{indent}      <span class="detail-label">Artifacts Evidence:</span><pre class="detail-value" style="white-space: pre-wrap; margin: 0;">{e(detail.artifacts_evidence)}</pre>
{indent}    </div>
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
    job_id: str = "",
) -> None:
    """Render child job analysis sections recursively.

    Args:
        parts: List of HTML string parts to append to.
        children: Child job analyses to render.
        e: HTML escape function reference.
        depth: Current recursion depth.
        max_depth: Maximum recursion depth for nested children.
        job_id: The job identifier for reviewed toggle data attributes.
    """
    for child in children:
        child_failures_count = len(child.failures)
        child_groups = _group_failures(child.failures) if child.failures else []
        child_groups_count = len(child_groups)

        # Show group count when grouping reduces the visible cards
        if child_groups_count and child_groups_count < child_failures_count:
            badge_text = (
                f"{child_groups_count} root cause{'s' if child_groups_count != 1 else ''}"
                f" ({child_failures_count} failure{'s' if child_failures_count != 1 else ''})"
            )
        else:
            badge_text = f"{child_failures_count} failure{'s' if child_failures_count != 1 else ''}"

        parts.append(f"""<details class="child-job">
  <summary class="child-job-summary">
    <span style="color:var(--accent-purple)">{e(child.job_name)}</span>
    <span style="color:var(--text-muted)">#{child.build_number}</span>
    <span class="failure-badge" style="font-size:11px;padding:2px 8px">{badge_text}</span>
    <span class="child-review-status status-chip" data-child-job="{e(child.job_name)}" style="display:none"></span>
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

        if child_groups:
            for group in child_groups:
                _render_group_card(
                    parts,
                    group,
                    e,
                    indent="    ",
                    job_id=job_id,
                    child_job_name=child.job_name,
                    child_build_number=child.build_number,
                )

        # Recurse into nested children
        if child.failed_children and depth < max_depth:
            _render_child_jobs(
                parts,
                child.failed_children,
                e,
                depth=depth + 1,
                max_depth=max_depth,
                job_id=job_id,
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
    jenkins_link = (
        f'<a href="{e(jenkins_url)}" target="_blank" rel="noopener">View in Jenkins</a>'
        if jenkins_url
        else ""
    )
    parts.append(f"""
<div class="report-footer">
  <span>{e(job_name)} #{e(build_number)} | Job ID: {e(job_id)} | Analyzed by {e(provider_info)}</span>
  {jenkins_link}
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
<link rel="icon" href="{FAVICON_DATA_URI}">
<style>
/* Minimal standalone styles — this lightweight status page intentionally
   skips _common_css() to keep the response small and self-contained. */
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


def generate_dashboard_html(
    jobs: list[dict], base_url: str = "", limit: int = 500
) -> str:
    """Generate a self-contained HTML dashboard page listing analysis jobs.

    Produces a complete HTML document with inline CSS using the same dark
    GitHub-inspired theme as the analysis reports. Each job is rendered as
    a clickable card linking to its HTML report.

    Args:
        jobs: List of dicts from list_results_for_dashboard(). Each dict has
            job_id, jenkins_url, status, created_at, and optionally job_name,
            build_number, failure_count.
        base_url: External base URL for constructing absolute report links.
        limit: The server-side cap that was used to load jobs. Shown in the UI
            so the user can adjust it.

    Returns:
        A complete HTML document as a string.
    """
    e = html.escape
    total_jobs = len(jobs)

    parts: list[str] = []

    parts.append(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Jenkins Job Insight - Dashboard</title>
<link rel="icon" href="{FAVICON_DATA_URI}">
<style>
{_common_css()}
.jobs-badge {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: rgba(88, 166, 255, 0.12);
    color: var(--accent-blue);
    font-size: 13px;
    font-weight: 700;
    padding: 4px 12px;
    border-radius: 12px;
    font-family: var(--font-mono);
}}

/* Dashboard cards */
.dashboard-card {{
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 16px 20px;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    margin-bottom: 8px;
    text-decoration: none;
    color: inherit;
    transition: background 0.15s, border-color 0.15s;
}}
.dashboard-card:hover {{
    background: var(--bg-hover);
    border-color: var(--accent-blue);
}}
.card-main {{
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
}}
.card-job-name {{
    font-weight: 600;
    font-size: 14px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 400px;
}}
.card-build-chip {{
    font-size: 12px;
    font-family: var(--font-mono);
    padding: 2px 8px;
    border-radius: 4px;
    background: var(--bg-tertiary);
    border: 1px solid var(--border);
    color: var(--text-secondary);
    white-space: nowrap;
}}
.status-chip {{
    font-size: 11px;
    font-weight: 700;
    padding: 3px 10px;
    border-radius: 12px;
    text-transform: uppercase;
    letter-spacing: 0.3px;
    white-space: nowrap;
}}
.status-chip.completed {{ background: rgba(63, 185, 80, 0.15); color: var(--accent-green); }}
.status-chip.failed {{ background: rgba(248, 81, 73, 0.15); color: var(--accent-red); }}
.status-chip.running {{ background: rgba(210, 153, 34, 0.15); color: var(--accent-yellow); }}
.status-chip.pending {{ background: rgba(88, 166, 255, 0.12); color: var(--accent-blue); }}
.failure-count-badge {{
    font-size: 12px;
    font-weight: 700;
    font-family: var(--font-mono);
    padding: 2px 8px;
    border-radius: 4px;
    background: rgba(248, 81, 73, 0.12);
    color: var(--accent-red);
    white-space: nowrap;
}}
/* Result indicators */
.card-result-icon {{
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    border-radius: 50%;
}}
.card-result-icon.passed {{
    background: rgba(63, 185, 80, 0.15);
    color: var(--accent-green);
}}
.card-result-icon.has-failures {{
    background: rgba(248, 81, 73, 0.15);
    color: var(--accent-red);
}}
.dashboard-card.result-passed {{
    border-left: 3px solid var(--accent-green);
}}
.dashboard-card.result-failures {{
    border-left: 3px solid var(--accent-red);
}}
.passed-badge {{
    font-size: 11px;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 4px;
    background: rgba(63, 185, 80, 0.12);
    color: var(--accent-green);
    white-space: nowrap;
}}
.child-jobs-badge {{
    font-size: 11px;
    font-weight: 700;
    font-family: var(--font-mono);
    padding: 2px 8px;
    border-radius: 4px;
    background: rgba(188, 140, 255, 0.12);
    color: var(--accent-purple);
    white-space: nowrap;
}}
.card-meta {{
    display: flex;
    align-items: center;
    gap: 12px;
    flex-shrink: 0;
}}
.card-timestamp {{
    font-size: 12px;
    color: var(--text-muted);
    font-family: var(--font-mono);
    white-space: nowrap;
}}
.card-jenkins-icon {{
    color: var(--text-muted);
    flex-shrink: 0;
}}
.card-job-id {{
    font-size: 11px;
    font-family: var(--font-mono);
    color: var(--text-muted);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 120px;
}}

/* Controls bar (search + per-page) */
.controls-bar {{
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 20px;
    flex-wrap: wrap;
}}
.search-input {{
    flex: 1;
    min-width: 200px;
    padding: 10px 14px;
    font-size: 14px;
    font-family: var(--font-sans);
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    color: var(--text-primary);
    outline: none;
    transition: border-color 0.15s;
}}
.search-input::placeholder {{ color: var(--text-muted); }}
.search-input:focus {{ border-color: var(--accent-blue); }}
.per-page-select {{
    padding: 10px 14px;
    font-size: 14px;
    font-family: var(--font-sans);
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    color: var(--text-primary);
    cursor: pointer;
    outline: none;
}}
.per-page-select:focus {{ border-color: var(--accent-blue); }}
.limit-control {{
    display: flex;
    align-items: center;
    gap: 6px;
    flex-shrink: 0;
}}
.limit-label {{
    font-size: 13px;
    color: var(--text-secondary);
    white-space: nowrap;
}}
.limit-input {{
    width: 80px;
    padding: 10px 10px;
    font-size: 14px;
    font-family: var(--font-mono);
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    color: var(--text-primary);
    outline: none;
    transition: border-color 0.15s;
}}
.limit-input:focus {{ border-color: var(--accent-blue); }}
.limit-btn {{
    padding: 10px 16px;
    font-size: 13px;
    font-weight: 600;
    font-family: var(--font-sans);
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    color: var(--text-primary);
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
    white-space: nowrap;
}}
.limit-btn:hover {{
    background: var(--bg-hover);
    border-color: var(--accent-blue);
}}

/* Pagination controls */
.pagination-controls {{
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 16px;
    margin-top: 24px;
    padding: 16px 0;
}}
.pagination-btn {{
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 600;
    font-family: var(--font-sans);
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    color: var(--text-primary);
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
}}
.pagination-btn:hover:not(:disabled) {{
    background: var(--bg-hover);
    border-color: var(--accent-blue);
}}
.pagination-btn:disabled {{
    opacity: 0.4;
    cursor: not-allowed;
}}
.page-info {{
    font-size: 13px;
    font-family: var(--font-mono);
    color: var(--text-secondary);
}}

/* Empty state */
.empty-state {{
    text-align: center;
    padding: 80px 20px;
    color: var(--text-muted);
}}
.empty-state svg {{ margin-bottom: 20px; }}
.empty-state p {{
    font-size: 16px;
    margin-top: 8px;
}}

/* Responsive (page-specific) */
@media (max-width: 768px) {{
    .dashboard-card {{ flex-direction: column; align-items: flex-start; gap: 10px; }}
    .card-meta {{ width: 100%; justify-content: space-between; }}
    .card-job-name {{ max-width: 100%; }}
    .controls-bar {{ flex-direction: column; }}
    .search-input {{ min-width: 100%; }}
}}
@media (max-width: 480px) {{
    .card-main {{ font-size: 12px; gap: 6px; }}
    .card-job-id {{ max-width: 80px; }}
}}
</style>
</head>
<body>
<div class="container">
""")

    # --- STICKY HEADER ---
    limit_note = f" (showing last {limit})" if total_jobs >= limit else ""
    parts.append(f"""
<div class="sticky-header">
  <div class="header-content">
    <h1>Jenkins Job Insight</h1>
    <span id="jobs-badge" class="jobs-badge">{total_jobs} job{"s" if total_jobs != 1 else ""}{e(limit_note)}</span>
  </div>
</div>
""")

    # --- EMPTY STATE ---
    if total_jobs == 0:
        parts.append(f"""
<div class="controls-bar">
  <div class="limit-control">
    <span class="limit-label">Load last</span>
    <input type="number" id="limit-input" class="limit-input" min="1" value="{limit}">
    <button id="limit-btn" class="limit-btn" onclick="window.location.href='{e(base_url)}/dashboard?limit='+document.getElementById('limit-input').value">Load</button>
  </div>
</div>
<div class="empty-state">
  <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <rect x="3" y="3" width="18" height="18" rx="2"/>
    <line x1="9" y1="9" x2="15" y2="9"/>
    <line x1="9" y1="13" x2="15" y2="13"/>
    <line x1="9" y1="17" x2="12" y2="17"/>
  </svg>
  <p>No analysis results yet</p>
</div>
""")
    else:
        # --- CONTROLS BAR ---
        parts.append(f"""
<div class="controls-bar">
  <input type="text" id="search-input" class="search-input" placeholder="Search jobs by name, ID, or status...">
  <select id="per-page-select" class="per-page-select">
    <option value="10" selected>10 per page</option>
    <option value="50">50 per page</option>
    <option value="100">100 per page</option>
  </select>
  <div class="limit-control">
    <span class="limit-label">Load last</span>
    <input type="number" id="limit-input" class="limit-input" min="1" value="{limit}">
    <button id="limit-btn" class="limit-btn" onclick="window.location.href='{e(base_url)}/dashboard?limit='+document.getElementById('limit-input').value">Load</button>
  </div>
</div>
""")

        # --- JOB CARDS ---
        parts.append('<div id="job-cards">')
        for job in jobs:
            _render_dashboard_card(parts, job, base_url, e)
        parts.append("</div>")

        # --- PAGINATION CONTROLS ---
        parts.append("""
<div class="pagination-controls">
  <button id="prev-btn" class="pagination-btn" disabled>Previous</button>
  <span id="page-info" class="page-info">Page 1 of 1</span>
  <button id="next-btn" class="pagination-btn" disabled>Next</button>
</div>
""")

    # --- FOOTER ---
    parts.append("""
<div class="report-footer">
  <span>Jenkins Job Insight Dashboard</span>
</div>
""")

    # --- JAVASCRIPT (only when there are jobs) ---
    if total_jobs > 0:
        parts.append(f"""
<script>
(function() {{
  var currentPage = 1;
  var perPage = 10;
  var serverLimit = {limit};
  var allCards = Array.from(document.querySelectorAll('#job-cards .dashboard-card'));
  var totalAll = allCards.length;
  var filteredCards = allCards.slice();

  var searchInput = document.getElementById('search-input');
  var perPageSelect = document.getElementById('per-page-select');
  var prevBtn = document.getElementById('prev-btn');
  var nextBtn = document.getElementById('next-btn');
  var pageInfo = document.getElementById('page-info');
  var jobsBadge = document.getElementById('jobs-badge');

  function getCardText(card) {{
    var text = card.textContent.toLowerCase();
    var titles = card.querySelectorAll('[title]');
    for (var i = 0; i < titles.length; i++) {{
      text += ' ' + titles[i].getAttribute('title').toLowerCase();
    }}
    var href = card.getAttribute('href');
    if (href) {{
      text += ' ' + href.toLowerCase();
    }}
    return text;
  }}

  function applyFilter() {{
    var query = searchInput.value.toLowerCase().trim();
    if (query === '') {{
      filteredCards = allCards.slice();
    }} else {{
      filteredCards = allCards.filter(function(card) {{
        return getCardText(card).indexOf(query) !== -1;
      }});
    }}
    currentPage = 1;
    render();
  }}

  function render() {{
    var totalFiltered = filteredCards.length;
    var totalPages = Math.max(1, Math.ceil(totalFiltered / perPage));
    if (currentPage > totalPages) currentPage = totalPages;
    var start = (currentPage - 1) * perPage;
    var end = start + perPage;

    // Hide all cards first
    for (var i = 0; i < allCards.length; i++) {{
      allCards[i].style.display = 'none';
    }}
    // Show only the filtered cards for the current page
    for (var j = 0; j < filteredCards.length; j++) {{
      if (j >= start && j < end) {{
        filteredCards[j].style.display = '';
      }}
    }}

    // Update page info
    pageInfo.textContent = 'Page ' + currentPage + ' of ' + totalPages;

    // Update buttons
    prevBtn.disabled = (currentPage <= 1);
    nextBtn.disabled = (currentPage >= totalPages);

    // Update badge
    var suffix = (totalAll !== 1 ? 's' : '');
    if (totalFiltered === totalAll) {{
      var limitNote = (totalAll >= serverLimit) ? ' (showing last ' + serverLimit + ')' : '';
      jobsBadge.textContent = totalAll + ' job' + suffix + limitNote;
    }} else {{
      jobsBadge.textContent = totalFiltered + ' of ' + totalAll + ' job' + suffix;
    }}
  }}

  searchInput.addEventListener('input', applyFilter);

  perPageSelect.addEventListener('change', function() {{
    perPage = parseInt(perPageSelect.value, 10);
    currentPage = 1;
    render();
  }});

  prevBtn.addEventListener('click', function() {{
    if (currentPage > 1) {{
      currentPage--;
      render();
    }}
  }});

  nextBtn.addEventListener('click', function() {{
    var totalPages = Math.max(1, Math.ceil(filteredCards.length / perPage));
    if (currentPage < totalPages) {{
      currentPage++;
      render();
    }}
  }});

  // Initial render
  render();
}})();
</script>
""")

    # --- USERNAME DISPLAY (always, regardless of job count) ---
    parts.append("""
<script>
(function() {
    var userCookie = document.cookie.split('; ').find(function(c) { return c.startsWith('jji_username='); });
    if (userCookie) {
        var uname = decodeURIComponent(userCookie.split('=')[1]);
        var headerContent = document.querySelector('.header-content');
        if (headerContent) {
            var userChip = document.createElement('span');
            userChip.className = 'env-chip';
            userChip.style.marginLeft = 'auto';
            userChip.textContent = 'User: ' + uname;
            headerContent.appendChild(userChip);
        }
    }
})();
</script>
""")

    parts.append("</div>\n</body>\n</html>")
    return "\n".join(parts)


def _render_dashboard_card(
    parts: list[str],
    job: dict,
    base_url: str,
    e: Callable[[str], str],
) -> None:
    """Render a single dashboard job card as a clickable link.

    Args:
        parts: List of HTML string parts to append to.
        job: Job dict from list_results_for_dashboard().
        base_url: External base URL for constructing report links.
        e: HTML escape function reference.
    """
    job_id = job.get("job_id", "")
    status = job.get("status", "unknown")
    created_at = job.get("created_at", "")
    jenkins_url = job.get("jenkins_url", "")
    job_name = job.get("job_name", "") or "Direct Analysis"
    build_number = job.get("build_number", "")
    failure_count = job.get("failure_count")

    status_class = (
        status if status in ("completed", "failed", "running", "pending") else "pending"
    )
    report_href = f"{base_url}/results/{job_id}.html"

    # Truncated job_id for display (first 8 chars)
    short_id = job_id[:8] if len(job_id) > 8 else job_id

    # Determine result class for the card border
    result_class = ""
    if status == "completed" and failure_count is not None:
        if failure_count > 0:
            result_class = " result-failures"
        else:
            result_class = " result-passed"

    parts.append(
        f'<a class="dashboard-card{result_class}" href="{e(report_href)}" target="_blank" rel="noopener">'
    )
    parts.append('  <div class="card-main">')

    # Result icon for completed jobs with known failure count
    if status == "completed" and failure_count is not None:
        if failure_count > 0:
            parts.append(
                '    <span class="card-result-icon has-failures">'
                '<svg width="14" height="14" viewBox="0 0 24 24" fill="none"'
                ' stroke="currentColor" stroke-width="3">'
                '<line x1="18" y1="6" x2="6" y2="18"/>'
                '<line x1="6" y1="6" x2="18" y2="18"/>'
                "</svg></span>"
            )
        else:
            parts.append(
                '    <span class="card-result-icon passed">'
                '<svg width="14" height="14" viewBox="0 0 24 24" fill="none"'
                ' stroke="currentColor" stroke-width="3">'
                '<polyline points="20 6 9 17 4 12"/>'
                "</svg></span>"
            )

    parts.append(f'    <span class="card-job-name">{e(job_name)}</span>')

    if build_number:
        parts.append(
            f'    <span class="card-build-chip">#{e(str(build_number))}</span>'
        )

    parts.append(f'    <span class="status-chip {e(status_class)}">{e(status)}</span>')

    if failure_count is not None and failure_count > 0:
        parts.append(
            f'    <span class="failure-count-badge">'
            f"{failure_count} failure{'s' if failure_count != 1 else ''}"
            f"</span>"
        )
    elif status == "completed" and failure_count is not None:
        parts.append('    <span class="passed-badge">passed</span>')

    child_job_count = job.get("child_job_count")
    if child_job_count is not None and child_job_count > 0:
        parts.append(
            f'    <span class="child-jobs-badge">'
            f"{child_job_count} child job{'s' if child_job_count != 1 else ''}"
            f"</span>"
        )

    # Review status chip (only for cards with failures)
    reviewed_count = job.get("reviewed_count", 0)
    comment_count = job.get("comment_count", 0)
    if failure_count is not None and failure_count > 0:
        if reviewed_count >= failure_count:
            parts.append(
                '    <span class="status-chip" '
                'style="background: rgba(63,185,80,0.15); color: var(--accent-green)">'
                "\u2713 Fully Reviewed</span>"
            )
        elif reviewed_count > 0:
            parts.append(
                '    <span class="status-chip" '
                'style="background: rgba(210,153,34,0.15); color: var(--accent-yellow)">'
                f"{reviewed_count}/{failure_count} Reviewed</span>"
            )
        else:
            parts.append(
                '    <span class="status-chip" '
                'style="background: rgba(248,81,73,0.12); color: var(--accent-red)">'
                "Needs Review</span>"
            )

    # Comment count badge
    if comment_count > 0:
        parts.append(
            f'    <span class="card-build-chip">'
            f"{comment_count} comment{'s' if comment_count != 1 else ''}"
            f"</span>"
        )

    parts.append("  </div>")
    parts.append('  <div class="card-meta">')
    parts.append(
        f'    <span class="card-job-id" title="{e(job_id)}">{e(short_id)}</span>'
    )
    parts.append(f'    <span class="card-timestamp">{e(created_at)}</span>')

    if jenkins_url:
        parts.append(
            '    <span class="card-jenkins-icon" title="Jenkins build available">'
            '\n      <svg width="14" height="14" viewBox="0 0 24 24" fill="none"'
            ' stroke="currentColor" stroke-width="2">'
            '\n        <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>'
            '\n        <polyline points="15 3 21 3 21 9"/>'
            '\n        <line x1="10" y1="14" x2="21" y2="3"/>'
            "\n      </svg>"
            "\n    </span>"
        )

    parts.append("  </div>")
    parts.append("</a>")


def generate_register_html() -> str:
    """Generate the user registration page HTML.

    Returns:
        A complete HTML document as a string with the registration form.
    """
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Jenkins Job Insight - Register</title>
<link rel="icon" href="{FAVICON_DATA_URI}">
<style>
{_common_css()}
.register-container {{
    max-width: 400px;
    margin: 100px auto;
    padding: 40px;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    text-align: center;
}}
.register-container h2 {{
    font-size: 20px;
    margin-bottom: 8px;
    color: var(--text-primary);
}}
.register-container p {{
    font-size: 14px;
    color: var(--text-secondary);
    margin-bottom: 24px;
}}
.register-input {{
    width: 100%;
    padding: 12px 16px;
    font-size: 16px;
    font-family: var(--font-sans);
    background: var(--bg-primary);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text-primary);
    outline: none;
    margin-bottom: 16px;
    transition: border-color 0.15s;
}}
.register-input::placeholder {{ color: var(--text-muted); }}
.register-input:focus {{ border-color: var(--accent-blue); }}
.register-btn {{
    width: 100%;
    padding: 12px;
    font-size: 14px;
    font-weight: 600;
    font-family: var(--font-sans);
    background: var(--bg-tertiary);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--accent-blue);
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
}}
.register-btn:hover {{
    background: var(--bg-hover);
    border-color: var(--accent-blue);
}}
</style>
</head>
<body>
<div class="register-container">
    <h2>Welcome to Jenkins Job Insight</h2>
    <p>Enter your name to get started</p>
    <form method="POST" action="/register">
        <input class="register-input" type="text" name="username" placeholder="Your name" required autofocus>
        <button class="register-btn" type="submit">Continue</button>
    </form>
</div>
</body>
</html>"""
