#!/usr/bin/env python3
"""Verify the final user-journey documentation audit report contract."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


REQUIRED_HEADINGS = [
    "Coverage",
    "Interview Summary",
    "Confirmed App Idea",
    "Confirmed Users And Contexts",
    "Confirmed Journey Inventory",
    "Missing Or Weak Journeys",
    "Journey Decision Model Gaps",
    "Information Relevance Inventory Gaps",
    "Documentation Completeness Findings",
    "Information Hierarchy And Navigation Gaps",
    "Interaction Affordance And Metadata Gaps",
    "UX Documentation Gaps",
    "UI Handoff Constraints",
    "Recommended Documentation Plan",
    "Readiness Score",
    "Questions Still Unanswered",
]
PLACEHOLDER_RE = re.compile(r"\b(?:todo|tbd|placeholder|fill\s+this|lorem\s+ipsum)\b|<[^>]+>", re.IGNORECASE)
INTERACTION_TERMS = (
    "activation target",
    "focus",
    "destination",
    "disclosure lifecycle",
    "detail access",
    "scrollbar",
    "stable dimension",
    "hover-copy",
    "concise status",
    "icon meaning",
    "passive metadata",
)


def sections(text: str) -> tuple[list[str], dict[str, str]]:
    matches = list(re.finditer(r"^##\s+(.+?)\s*$", text, re.MULTILINE))
    order: list[str] = []
    bodies: dict[str, str] = {}
    for index, match in enumerate(matches):
        heading = match.group(1).strip()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        order.append(heading)
        bodies[heading] = text[match.end():end].strip()
    return order, bodies


def verify(text: str) -> list[str]:
    issues: list[str] = []
    order, bodies = sections(text)
    if order != REQUIRED_HEADINGS:
        missing = [item for item in REQUIRED_HEADINGS if item not in order]
        unexpected = [item for item in order if item not in REQUIRED_HEADINGS]
        issues.append(f"top-level headings must exactly match the required order; missing={missing}; unexpected={unexpected}")
    for heading in REQUIRED_HEADINGS:
        body = bodies.get(heading, "")
        if not body:
            issues.append(f"section is missing or empty: {heading}")
        elif PLACEHOLDER_RE.search(body):
            issues.append(f"section contains placeholder text: {heading}")

    coverage = bodies.get("Coverage", "")
    interview = bodies.get("Interview Summary", "")
    inventory = bodies.get("Confirmed Journey Inventory", "")
    readiness = bodies.get("Readiness Score", "")
    questions = bodies.get("Questions Still Unanswered", "")
    interaction = bodies.get("Interaction Affordance And Metadata Gaps", "").lower()

    interview_status = re.search(r"\b(confirmed|answered|unconfirmed|not answered|unavailable|declined)\b", interview, re.IGNORECASE)
    if not interview_status:
        issues.append("Interview Summary must state whether the user confirmed/answered or remained unavailable/unconfirmed")
    if inventory and not re.search(r"\b(confirmed|draft-needs-user-confirmation|draft|rejected|blocked)\b", inventory, re.IGNORECASE):
        issues.append("Confirmed Journey Inventory must label each journey status")

    unconfirmed = "journey assumptions unconfirmed" in coverage.lower()
    if unconfirmed:
        for heading, body in (("Readiness Score", readiness), ("Questions Still Unanswered", questions)):
            if "journey assumptions unconfirmed" not in body.lower():
                issues.append(f"{heading} must repeat 'journey assumptions unconfirmed' when coverage is unconfirmed")
    elif not re.search(r"\bconfirmed\b", coverage, re.IGNORECASE):
        issues.append("Coverage must label journey assumptions confirmed or use the exact unconfirmed phrase")

    missing_interaction = [term for term in INTERACTION_TERMS if term not in interaction]
    if missing_interaction:
        issues.append(f"Interaction Affordance And Metadata Gaps omits required checks: {missing_interaction}")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    if not args.report.is_file():
        print(f"ERROR: report not found: {args.report}")
        return 1
    issues = verify(args.report.read_text(encoding="utf-8", errors="replace"))
    if issues:
        for issue in issues:
            print(f"ERROR: {issue}")
        return 1
    print("journey-docs audit report verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
