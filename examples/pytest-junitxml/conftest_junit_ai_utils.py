"""Utility functions for JUnit XML AI analysis enrichment."""

import logging
import os
import shutil
from pathlib import Path
from xml.etree import ElementTree as ET

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]

logger = logging.getLogger("jenkins-job-insight")


def nodeid_to_classname_and_name(nodeid):
    """Convert a pytest nodeid to JUnit XML (classname, name) tuple.

    Examples:
        "tests/test_foo.py::test_bar" -> ("tests.test_foo", "test_bar")
        "tests/test_foo.py::TestClass::test_bar" -> ("tests.test_foo.TestClass", "test_bar")
        "tests/sub/test_foo.py::TestClass::test_bar[param]" -> ("tests.sub.test_foo.TestClass", "test_bar[param]")
    """
    parts = nodeid.split("::")
    module = parts[0].replace("/", ".").removesuffix(".py")
    if len(parts) == 3:
        return f"{module}.{parts[1]}", parts[2]
    elif len(parts) == 2:
        return module, parts[1]
    return "", nodeid


def inject_analysis(testcase, analysis):
    """Inject AI analysis into a testcase element as properties and system-out.

    Args:
        testcase: XML Element for the testcase
        analysis: dict with classification, details, affected_tests, etc.
    """
    # Add structured properties
    properties = testcase.find("properties")
    if properties is None:
        properties = ET.SubElement(testcase, "properties")

    add_property(properties, "ai_classification", analysis.get("classification", ""))
    add_property(properties, "ai_details", analysis.get("details", ""))

    affected = analysis.get("affected_tests", [])
    if affected:
        add_property(properties, "ai_affected_tests", ", ".join(affected))

    # Code fix properties
    code_fix = analysis.get("code_fix")
    if code_fix and isinstance(code_fix, dict):
        add_property(properties, "ai_code_fix_file", code_fix.get("file", ""))
        add_property(properties, "ai_code_fix_line", code_fix.get("line", ""))
        add_property(properties, "ai_code_fix_change", code_fix.get("change", ""))

    # Product bug properties
    bug_report = analysis.get("product_bug_report")
    if bug_report and isinstance(bug_report, dict):
        add_property(properties, "ai_bug_title", bug_report.get("title", ""))
        add_property(properties, "ai_bug_severity", bug_report.get("severity", ""))
        add_property(properties, "ai_bug_component", bug_report.get("component", ""))
        add_property(
            properties, "ai_bug_description", bug_report.get("description", "")
        )

    # Add human-readable system-out
    text = format_analysis_text(analysis)
    if text:
        system_out = testcase.find("system-out")
        if system_out is None:
            system_out = ET.SubElement(testcase, "system-out")
            system_out.text = text
        else:
            # Append to existing system-out
            existing = system_out.text or ""
            system_out.text = (
                f"{existing}\n\n--- AI Analysis ---\n{text}" if existing else text
            )


def add_property(properties_elem, name, value):
    """Add a property element if value is non-empty."""
    if value:
        prop = ET.SubElement(properties_elem, "property")
        prop.set("name", name)
        prop.set("value", str(value))


def format_analysis_text(analysis):
    """Format analysis dict as human-readable text for system-out."""
    parts = []

    classification = analysis.get("classification", "")
    if classification:
        parts.append(f"Classification: {classification}")

    details = analysis.get("details", "")
    if details:
        parts.append(f"\n{details}")

    code_fix = analysis.get("code_fix")
    if code_fix and isinstance(code_fix, dict):
        parts.append("\nCode Fix:")
        parts.append(f"  File: {code_fix.get('file', '')}")
        parts.append(f"  Line: {code_fix.get('line', '')}")
        parts.append(f"  Change: {code_fix.get('change', '')}")

    bug_report = analysis.get("product_bug_report")
    if bug_report and isinstance(bug_report, dict):
        parts.append("\nProduct Bug:")
        parts.append(f"  Title: {bug_report.get('title', '')}")
        parts.append(f"  Severity: {bug_report.get('severity', '')}")
        parts.append(f"  Component: {bug_report.get('component', '')}")
        parts.append(f"  Description: {bug_report.get('description', '')}")

    return "\n".join(parts) if parts else ""


def enrich_junit_xml(session, collected_failures):
    """Internal: POST failures to server and inject analysis into XML."""
    if requests is None:
        return

    xml_path = getattr(session.config.option, "xmlpath", None)
    if not xml_path or not Path(xml_path).exists() or not collected_failures:
        return

    xml_path = Path(xml_path)

    # POST failures to jenkins-job-insight server
    server_url = os.environ.get("JJI_SERVER_URL")
    if not server_url:
        logger.warning("JJI_SERVER_URL not set, skipping AI analysis enrichment")
        return
    payload: dict = {"failures": collected_failures}

    ai_provider = os.environ.get("JJI_AI_PROVIDER")
    ai_model = os.environ.get("JJI_AI_MODEL")
    if not ai_provider or not ai_model:
        logger.warning(
            "JJI_AI_PROVIDER and JJI_AI_MODEL must be set, skipping AI analysis enrichment"
        )
        return
    payload["ai_provider"] = ai_provider
    payload["ai_model"] = ai_model

    try:
        response = requests.post(
            f"{server_url.rstrip('/')}/analyze-failures",
            json=payload,
            timeout=int(os.environ.get("JJI_TIMEOUT", "600")),
        )
        response.raise_for_status()
        result = response.json()
    except requests.RequestException as exc:
        error_detail = ""
        if hasattr(exc, "response") and exc.response is not None:
            try:
                error_detail = f" Response: {exc.response.text}"
            except Exception:
                pass
        logger.error("Server request failed: %s%s", exc, error_detail)
        return

    # Build (classname, name) -> analysis mapping using nodeid conversion
    analysis_map = {}
    for failure in result.get("failures", []):
        test_name = failure.get("test_name", "")
        analysis = failure.get("analysis", {})
        if test_name and analysis:
            key = nodeid_to_classname_and_name(test_name)
            analysis_map[key] = analysis

    if not analysis_map:
        return

    # Backup original XML before modification
    backup_path = xml_path.with_suffix(".xml.bak")
    shutil.copy2(xml_path, backup_path)

    try:
        tree = ET.parse(xml_path)
        for testcase in tree.iter("testcase"):
            key = (testcase.get("classname", ""), testcase.get("name", ""))
            if key in analysis_map:
                inject_analysis(testcase, analysis_map[key])

        tree.write(str(xml_path), encoding="unicode", xml_declaration=True)
        backup_path.unlink()  # Success - remove backup
    except Exception:
        # Restore original XML from backup
        shutil.copy2(backup_path, xml_path)
        backup_path.unlink()
        raise  # Re-raise to be caught by outer try/except in sessionfinish
