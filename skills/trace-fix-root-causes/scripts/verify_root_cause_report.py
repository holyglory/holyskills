#!/usr/bin/env python3
"""Verify a concise formal trace-fix-root-causes report."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REQUIRED_HEADINGS = ["outcome", "cause", "changes", "verification"]
SECTION_FIELDS = {
    "outcome": {"status"},
    "cause": {"class", "confidence", "request", "immediate cause", "why missed", "evidence"},
    "changes": {"product", "prevention"},
    "verification": {"original path", "checks", "residual risk"},
}
STATUSES = {"fixed", "diagnosed", "blocked"}
CONFIDENCE_LEVELS = {"confirmed", "source-inferred", "unconfirmed"}
INCIDENT_CLASSES = {
    "implementation",
    "ui",
    "factual",
    "reasoning",
    "tool-use",
    "artifact",
    "service",
    "audit",
    "verification",
    "other",
}
FIELD_RE = re.compile(r"^\s*(?:[-*]\s+)?([A-Za-z][A-Za-z -]*):\s*(.*)$")
FORBIDDEN_ACTION_MODE_RE = re.compile(
    r"^\s*(?:[-*]\s+)?(?:authorization(?:\s+and\s+action\s+mode)?|action\s+mode):",
    re.IGNORECASE | re.MULTILINE,
)

PRODUCT_COMPLETED_RE = re.compile(
    r"\b(fixed|repaired|corrected|patched|implemented|updated|changed|restored|"
    r"restarted|removed|added|configured|set|applied|completed|no product change (?:was )?needed)\b",
    re.IGNORECASE,
)
PRODUCT_NO_CHANGE_NEEDED_RE = re.compile(r"\bno product change (?:was )?needed\b", re.IGNORECASE)
PREVENTION_COMPLETED_RE = re.compile(
    r"\b(added|updated|strengthened|implemented|applied|covered|fixed|patched|"
    r"completed|not applicable|no prevention change (?:was )?needed)\b",
    re.IGNORECASE,
)
PREVENTION_NOT_APPLICABLE_RE = re.compile(
    r"\b(not applicable|no prevention change (?:was )?needed)\b",
    re.IGNORECASE,
)
INCOMPLETE_CHANGE_RE = re.compile(
    r"\b(pending|planned|proposed|recommended|awaiting|"
    r"not (?:yet )?(?:fixed|repaired|corrected|patched|implemented|updated|changed|"
    r"restored|added|configured|set|applied|completed))\b",
    re.IGNORECASE,
)
ORIGINAL_PATH_COMPLETED_RE = re.compile(
    r"\b(reran|re-ran|retested|re-tested|verified|exercised|opened|tapped|passed|"
    r"works|worked|now opens|now succeeds)\b",
    re.IGNORECASE,
)
POST_FIX_RE = re.compile(
    r"\b(post-fix|after (?:the )?(?:fix|change|patch)|with (?:the )?fix applied|"
    r"following (?:the )?(?:fix|change|patch))\b",
    re.IGNORECASE,
)
CHECKS_COMPLETED_RE = re.compile(
    r"\b(passed|completed|reran|re-ran|retested|re-tested|verified|succeeded|green)\b",
    re.IGNORECASE,
)
NOT_RUN_RE = re.compile(r"\b(not run|not executed|pending|awaiting)\b", re.IGNORECASE)
NEGATED_VERIFICATION_RE = re.compile(
    r"\b(?:not|never|could not|unable to|failed to)\s+(?:be\s+)?"
    r"(?:rerun|re-run|retested|re-tested|verified|exercised|opened|passed|completed)\b",
    re.IGNORECASE,
)
READ_ONLY_RE = re.compile(
    r"\b(read-only|no (?:product |code |file )?changes?|nothing was changed|"
    r"not changed|not modified|unchanged)\b",
    re.IGNORECASE,
)
PREVENTION_NOT_APPLIED_RE = re.compile(
    r"\b(proposed|recommended|not applied|no prevention changes?|read-only|unchanged)\b",
    re.IGNORECASE,
)

SERVICE_LOG_RE = re.compile(
    r"\b(log_path|coordinator log|app log|stderr|stdout|events\.jsonl|process exit|"
    r"exit event|latest\.log)\b",
    re.IGNORECASE,
)
SERVICE_PID_RE = re.compile(
    r"\b(pid|pid_alive|process exit|exit code|coordinator status|inventory|health)\b",
    re.IGNORECASE,
)
SERVICE_CAUSE_RE = re.compile(
    r"\b(toolchain|cache|build output|wrapper|coordinator|dependency|policy|skill trigger|guardrail)\b",
    re.IGNORECASE,
)
SERVICE_SUSTAINED_RE = re.compile(
    r"\b(sustained|same url|failing url|coordinator status|browser|curl|ttfb|monitor|stability)\b",
    re.IGNORECASE,
)
SOURCE_EVIDENCE_RE = re.compile(
    r"\b(primary source|official source|source citation|source passage|published source|"
    r"document dated|documentation dated)\b|https?://",
    re.IGNORECASE,
)
SOURCE_TIMING_RE = re.compile(
    r"\b(as of|timestamp|dated|date|at delivery|answer time|when answered)\b",
    re.IGNORECASE,
)
TOOL_TRACE_RE = re.compile(
    r"\b(tool trace|tool invocation|command|cli|stdout|stderr|execution log)\b",
    re.IGNORECASE,
)
TOOL_RESULT_RE = re.compile(
    r"\b(argument|arguments|argv|result|error|exit|external state|changed state)\b",
    re.IGNORECASE,
)
ARTIFACT_OBJECT_RE = re.compile(
    r"\b(artifact|sha256|file hash|output file|rendered file)\b|"
    r"\.(?:pdf|docx|pptx|xlsx)\b",
    re.IGNORECASE,
)
ARTIFACT_CHECK_RE = re.compile(
    r"\b(screenshot|render|renderer|parser|structural check|page image|png|opened the file)\b",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify a concise four-section formal trace-fix-root-causes Markdown report."
    )
    parser.add_argument("report", help="Path to a formal Markdown report.")
    return parser.parse_args()


def parse_sections(text: str) -> tuple[list[str], dict[str, str], list[str]]:
    order: list[str] = []
    lines_by_heading: dict[str, list[str]] = {}
    duplicates: list[str] = []
    current: str | None = None
    for line in text.splitlines():
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            current = match.group(1).strip().lower()
            order.append(current)
            if current in lines_by_heading:
                duplicates.append(current)
            else:
                lines_by_heading[current] = []
        elif current is not None and current in lines_by_heading:
            lines_by_heading[current].append(line)
    bodies = {heading: "\n".join(lines).strip() for heading, lines in lines_by_heading.items()}
    return order, bodies, duplicates


def parse_fields(
    body: str,
    *,
    section: str,
    required: set[str],
    issues: list[str],
) -> dict[str, str]:
    values: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.splitlines():
        match = FIELD_RE.match(line)
        if match:
            label = " ".join(match.group(1).lower().split())
            if label in required:
                if label in values:
                    issues.append(f"{section} must contain exactly one {label.title()}: field")
                else:
                    values[label] = [match.group(2).strip()]
                current = label
                continue
        if current is not None and line.strip():
            if current not in {"status", "class", "confidence"}:
                values[current].append(line.strip())

    parsed = {label: "\n".join(parts).strip() for label, parts in values.items()}
    for label in sorted(required):
        if label not in parsed:
            issues.append(f"{section} is missing required field {label.title()}:")
        elif not parsed[label]:
            issues.append(f"{section} field {label.title()}: must not be empty")
    return parsed


def verify(text: str) -> list[str]:
    issues: list[str] = []
    order, bodies, duplicates = parse_sections(text)
    expected = ", ".join(f"## {heading.title()}" for heading in REQUIRED_HEADINGS)
    if duplicates:
        issues.append("duplicate headings: " + ", ".join(sorted(set(duplicates))))
    if order != REQUIRED_HEADINGS:
        missing = [heading for heading in REQUIRED_HEADINGS if heading not in order]
        unexpected = [heading for heading in order if heading not in REQUIRED_HEADINGS]
        issues.append(f"formal report headings must be exactly, in order: {expected}")
        if missing:
            issues.append("missing headings: " + ", ".join(missing))
        if unexpected:
            issues.append("unexpected headings: " + ", ".join(unexpected))
    if any(heading not in bodies for heading in REQUIRED_HEADINGS):
        return issues
    for heading in REQUIRED_HEADINGS:
        if not bodies[heading]:
            issues.append(f"empty section: {heading}")

    if FORBIDDEN_ACTION_MODE_RE.search(text):
        issues.append("formal reports must not expose an authorization/action-mode field")

    fields = {
        heading: parse_fields(
            bodies[heading], section=heading, required=SECTION_FIELDS[heading], issues=issues
        )
        for heading in REQUIRED_HEADINGS
    }
    if any(label not in fields[heading] or not fields[heading][label] for heading in REQUIRED_HEADINGS for label in SECTION_FIELDS[heading]):
        return issues

    status = fields["outcome"]["status"].strip().lower()
    incident_class = fields["cause"]["class"].strip().lower()
    confidence = fields["cause"]["confidence"].strip().lower()
    product = fields["changes"]["product"]
    prevention = fields["changes"]["prevention"]
    original_path = fields["verification"]["original path"]
    checks = fields["verification"]["checks"]
    evidence = fields["cause"]["evidence"]
    causal_text = "\n".join(
        [fields["cause"]["request"], fields["cause"]["immediate cause"], fields["cause"]["why missed"]]
    )
    verification_text = f"{original_path}\n{checks}"

    if status not in STATUSES:
        issues.append("outcome Status: must be exactly fixed, diagnosed, or blocked")
    if incident_class not in INCIDENT_CLASSES:
        issues.append("cause Class: must be exactly one allowed class: " + ", ".join(sorted(INCIDENT_CLASSES)))
        incident_class = ""
    if confidence not in CONFIDENCE_LEVELS:
        issues.append("cause Confidence: must be exactly confirmed, source-inferred, or unconfirmed")
        confidence = ""

    if status == "fixed":
        if not PRODUCT_NO_CHANGE_NEEDED_RE.search(product) and (
            INCOMPLETE_CHANGE_RE.search(product) or not PRODUCT_COMPLETED_RE.search(product)
        ):
            issues.append("fixed reports must describe the completed product change")
        if not PREVENTION_NOT_APPLICABLE_RE.search(prevention) and (
            INCOMPLETE_CHANGE_RE.search(prevention) or not PREVENTION_COMPLETED_RE.search(prevention)
        ):
            issues.append("fixed reports must describe completed prevention work or a completed not-applicable disposition")
        if (
            NOT_RUN_RE.search(original_path)
            or NEGATED_VERIFICATION_RE.search(original_path)
            or not ORIGINAL_PATH_COMPLETED_RE.search(original_path)
        ):
            issues.append("fixed reports must verify the completed result through the original path")
        if NOT_RUN_RE.search(checks) or NEGATED_VERIFICATION_RE.search(checks) or not CHECKS_COMPLETED_RE.search(checks):
            issues.append("fixed reports must list completed checks")
        if not POST_FIX_RE.search(verification_text):
            issues.append("fixed reports must identify verification as post-fix")
    elif status == "diagnosed":
        if not READ_ONLY_RE.search(product):
            issues.append("diagnosed reports must state explicitly that product investigation was read-only/no-change")
        if not PREVENTION_NOT_APPLIED_RE.search(prevention):
            issues.append("diagnosed reports must state that prevention was proposed, read-only, or not applied")

    if incident_class == "service" and confidence != "unconfirmed":
        if not SERVICE_LOG_RE.search(evidence):
            issues.append("service incidents require concrete crash/log evidence")
        if not SERVICE_PID_RE.search(f"{evidence}\n{causal_text}"):
            issues.append("service incidents require PID, health, inventory, or process-exit evidence")
        if not SERVICE_CAUSE_RE.search(causal_text):
            issues.append("service causes must inspect toolchain, cache, wrapper, coordinator, dependency, policy, or skill-trigger paths")
        if status == "fixed" and not SERVICE_SUSTAINED_RE.search(verification_text):
            issues.append("fixed service incidents require sustained verification through the failing surface")
    if incident_class in {"factual", "reasoning"} and confidence != "unconfirmed":
        if not SOURCE_EVIDENCE_RE.search(evidence):
            issues.append("factual and reasoning incidents require source-backed evidence")
        if not SOURCE_TIMING_RE.search(evidence):
            issues.append("factual and reasoning evidence must record source or answer timing")
    if incident_class == "tool-use" and confidence != "unconfirmed":
        if not TOOL_TRACE_RE.search(evidence):
            issues.append("tool-use incidents require a tool trace, invocation, command, or execution log")
        if not TOOL_RESULT_RE.search(evidence):
            issues.append("tool-use evidence must preserve redacted arguments and result/error state")
    if incident_class == "artifact" and confidence != "unconfirmed":
        if not ARTIFACT_OBJECT_RE.search(evidence) or not ARTIFACT_CHECK_RE.search(evidence):
            issues.append("artifact incidents require the artifact plus render/parser/screenshot verification evidence")
    return issues


def main() -> int:
    args = parse_args()
    text = Path(args.report).read_text(encoding="utf-8")
    issues = verify(text)
    if issues:
        for issue in issues:
            print(f"ERROR: {issue}", file=sys.stderr)
        return 1
    print("root cause report ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
