#!/usr/bin/env python3
"""Verify trace-fix-root-causes report shape and minimum evidence discipline."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REQUIRED_HEADINGS = [
    "fixed symptom",
    "evidence used",
    "causal chain",
    "root cause classification",
    "workflow improvements",
    "validation plan",
    "boundaries and non-generalizable notes",
]
EVIDENCE_RE = re.compile(
    r"\b(user report|screenshot|audit output|audit report|test|verifier|log|diff|commit|file|source|trace|reproduction|before/after)\b",
    re.IGNORECASE,
)
CAUSE_AREA_RE = re.compile(
    r"\b(requirements?|journey docs?|docs?|mockups?|audit|skill|verifier|implementation|tests?|review|policy|handoff)\b",
    re.IGNORECASE,
)
CLASSIFICATION_RE = re.compile(r"\b(generalizable|local-repeatable|one-off|unconfirmed)\b", re.IGNORECASE)
VALIDATION_RE = re.compile(r"\b(test|validate|verifier|audit|screenshot|reproduce|command|fixture|self-test)\b", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify a trace-fix-root-causes Markdown report.")
    parser.add_argument("report", help="Path to a Markdown report.")
    return parser.parse_args()


def section_bodies(text: str) -> dict[str, str]:
    bodies: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            current = match.group(1).strip().lower()
            bodies.setdefault(current, [])
            continue
        if current is not None:
            bodies[current].append(line)
    return {key: "\n".join(value).strip() for key, value in bodies.items()}


def verify(text: str) -> list[str]:
    issues: list[str] = []
    bodies = section_bodies(text)
    missing = [heading for heading in REQUIRED_HEADINGS if heading not in bodies]
    if missing:
        issues.append(f"missing headings: {', '.join(missing)}")
        return issues

    for heading in REQUIRED_HEADINGS:
        if not bodies[heading].strip():
            issues.append(f"empty section: {heading}")

    evidence = bodies["evidence used"]
    classification = bodies["root cause classification"]
    causal_chain = bodies["causal chain"]
    improvements = bodies["workflow improvements"]
    validation = bodies["validation plan"]

    has_evidence = bool(EVIDENCE_RE.search(evidence))
    is_unconfirmed = "unconfirmed" in classification.lower()
    if not has_evidence and not is_unconfirmed:
        issues.append("reports without concrete evidence must classify the causal chain as unconfirmed")
    if "no evidence" in evidence.lower() and not is_unconfirmed:
        issues.append("explicitly missing evidence requires unconfirmed classification")
    if len(set(match.group(0).lower() for match in CAUSE_AREA_RE.finditer(causal_chain))) < 2 and not is_unconfirmed:
        issues.append("causal chain must trace at least two source areas or be marked unconfirmed")
    if not CLASSIFICATION_RE.search(classification):
        issues.append("root cause classification must include generalizable, local-repeatable, one-off, or unconfirmed")
    if re.search(r"\b(generalizable|local-repeatable)\b", classification, re.IGNORECASE) and re.search(
        r"\b(no workflow changes?|none)\b", improvements, re.IGNORECASE
    ):
        issues.append("repeatable root causes require workflow improvements")
    if not VALIDATION_RE.search(validation):
        issues.append("validation plan must name a test, verifier, audit, screenshot, fixture, or command")
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
