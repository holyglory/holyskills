#!/usr/bin/env python3
"""Self-tests for user-journey-docs-audit resources."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from shutil import rmtree


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "scripts" / "build_journey_docs_inventory.py"
REQUIRED_REFERENCES = {
    "references/ux_principles.md": ["# UX Principles", "Nielsen Norman Group", "WCAG"],
    "references/journey_doc_template.md": [
        "# User Journey Documentation Template",
        "## Journey Inventory",
        "## Journey Priority Contract",
        "## First Viewport Requirements",
        "## Screen Requirements",
    ],
}


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run_inventory(repo: Path) -> dict:
    result = subprocess.run(
        [sys.executable, str(INVENTORY), "--repo", str(repo), "--json"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return json.loads(result.stdout)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="user-journey-docs-audit-self-test-"))
    try:
        for rel_path, required_text in REQUIRED_REFERENCES.items():
            reference = ROOT / rel_path
            check(reference.is_file(), f"required reference is missing: {rel_path}")
            text = reference.read_text(encoding="utf-8")
            check(text.strip(), f"required reference is empty: {rel_path}")
            for needle in required_text:
                check(needle in text, f"required reference {rel_path} should contain {needle!r}")

        empty_repo = tmp / "empty"
        empty_repo.mkdir()
        write(empty_repo / "README.md", "# Tool\n\nA small app.\n")
        empty = run_inventory(empty_repo)
        check(empty["doc_count"] == 1, "README should be inventoried")
        check(empty["journey_doc_count"] == 0, "weak README should not count as journey docs")
        check(empty["missing_signals"], "weak docs should produce missing signals")

        keyword_noise_repo = tmp / "keyword-noise"
        write(keyword_noise_repo / "README.md", "# App\n\nA user-facing app with a mobile screen and desktop screen.\n")
        keyword_noise = run_inventory(keyword_noise_repo)
        check(keyword_noise["journey_doc_count"] == 0, "generic UI keywords should not count as journey docs")

        weak_mobile_repo = tmp / "weak-mobile"
        write(
            weak_mobile_repo / "docs" / "product.md",
            """# Product Overview

This app has a dashboard, mobile screen, desktop screen, settings, filters, and charts.

## Mobile

The mobile screen should be compact and avoid horizontal overflow.
""",
        )
        weak_mobile = run_inventory(weak_mobile_repo)
        check(weak_mobile["priority_contract_doc_count"] == 0, "weak mobile docs should not provide a priority contract")
        check(weak_mobile["first_viewport_doc_count"] == 0, "weak mobile docs should not provide first viewport requirements")
        check(not weak_mobile["ui_audit_handoff_ready"], "weak mobile docs should not be UI-audit handoff ready")
        check(
            any("first visible content" in item for item in weak_mobile["ui_implementation_risk_signals"]),
            "weak mobile docs should warn about missing first viewport decision content",
        )

        priority_gap_repo = tmp / "priority-gap"
        write(
            priority_gap_repo / "docs" / "metrics-dashboard.md",
            """# Metrics Dashboard Page

Users can view live metrics and adjust display settings.

## Mobile Screen

The page has a Settings panel and a primary metrics list.

## Acceptance

The mobile screen should be compact and have no horizontal overflow.
""",
        )
        priority_gap = run_inventory(priority_gap_repo)
        check(priority_gap["priority_contract_doc_count"] == 0, "ambiguous docs should not accidentally count as priority-ready")
        check(priority_gap["first_viewport_doc_count"] == 0, "ambiguous docs should not accidentally count as first-viewport-ready")
        check(
            any("settings/filters/configuration" in item for item in priority_gap["ui_implementation_risk_signals"]),
            "ambiguous docs should warn when settings and primary content are mentioned without mobile order",
        )

        complete_repo = tmp / "complete"
        write(
            complete_repo / "docs" / "journey-priority.md",
            """# Metrics Dashboard Journey Documentation

## App Idea

Product promise: help operators understand live metrics quickly.
Primary users: operations analysts.
Primary value: high-priority metrics are available before configuration.

## Journey Inventory

| Journey | User | Frequency | Importance | Risk if broken | Entry point | Success state |
| --- | --- | ---: | ---: | ---: | --- | --- |
| Review live metrics | operations analyst | high | high | high | /metrics | user can decide current metric status |

## Journey Priority Contract

| Surface | Primary user goal | Primary information | Frequent actions | Occasional controls | Rare/Admin/Configuration controls | Expected desktop order | Expected mobile order |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Metrics Dashboard | understand current live metrics quickly | high-priority metric list and latest chart | inspect metric details | adjust display filter | advanced settings configuration | chart and metrics before settings | high-priority metrics before settings/filter controls |

## First Viewport Requirements

| Viewport | First visible content | Primary decision data | Low-frequency controls | Allowed control share | What can the user decide? |
| --- | --- | --- | --- | --- | --- |
| mobile | high-priority metrics and latest update | visible before scroll | settings and filters below primary content | under 25% before metrics | user can decide current metric status from the first viewport |

## UI Audit Handoff

Use the UI implementation audit with a mobile screenshot, mockup, and DOM viewport measurement to confirm high-priority metrics stay above settings/filter controls.
""",
        )
        complete = run_inventory(complete_repo)
        check(complete["journey_doc_count"] >= 1, "complete docs should count as journey docs")
        check(complete["priority_contract_doc_count"] >= 1, "complete docs should count priority contract docs")
        check(complete["first_viewport_doc_count"] >= 1, "complete docs should count first viewport docs")
        check(complete["ui_audit_handoff_ready"], "complete docs should be UI-audit handoff ready")
        check(not complete["ui_implementation_risk_signals"], "complete docs should clear UI implementation risk signals")

        journey_repo = tmp / "journey"
        write(
            journey_repo / "docs" / "user-journeys.md",
            """# User Journeys

## Admin reviews upload

User: admin
Goal: review uploaded evidence
Entry point: dashboard
Route: /admin/uploads
Primary decision: approve or reject
Mobile: critical summary and warnings fit first
Error state: permission denied
Acceptance: admin can recover from failed upload
""",
        )
        write(journey_repo / "README.md", "# Evidence App\n\nProduct overview and purpose for users.\n")
        rich = run_inventory(journey_repo)
        check(rich["journey_doc_count"] >= 1, "journey docs should be detected")
        check(rich["product_doc_count"] >= 1, "product docs should be detected")
        check(not any("No strong user journey" in item for item in rich["missing_signals"]), "journey warning should clear")

        source_repo = tmp / "source"
        write(source_repo / "README.md", "# App\n\nPurpose and app value for users.\n")
        write(source_repo / "src" / "App.tsx", '<a href="/settings">Settings</a><button aria-label="Save profile">Save</button>')
        source = run_inventory(source_repo)
        check(source["source_hint_count"] == 1, "source route/visible text hints should be detected")

        skill_repo = tmp / "skill-repo"
        write(
            skill_repo / "skills" / "sample-skill" / "SKILL.md",
            """# Sample Skill

This operational skill guide mentions user journeys, workflow, product, overview, app, mobile, desktop, route, screen, goal, and acceptance so agents know what to ask.
""",
        )
        skill_inventory = run_inventory(skill_repo)
        check(skill_inventory["journey_doc_count"] == 0, "operational skill docs should not count as app journey docs")
        check(skill_inventory["product_doc_count"] == 0, "operational skill docs should not count as app product docs")

        skill_readme_repo = tmp / "skill-readme-repo"
        write(
            skill_readme_repo / "README.md",
            """# Holy Skills

This is a local curation repository for Codex skills.

- `skills/user-journey-docs-audit/`: checks whether docs describe app idea, users, journeys, UI priorities, edge cases, and acceptance criteria.
- `scripts/validate.py`: validates standalone skill-copy execution.
""",
        )
        skill_readme_inventory = run_inventory(skill_readme_repo)
        check(skill_readme_inventory["journey_doc_count"] == 0, "skill repo README should not count as app journey docs")
        check(skill_readme_inventory["product_doc_count"] == 0, "skill repo README should not count as app product docs")

        print("self-test ok")
        return 0
    finally:
        rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
