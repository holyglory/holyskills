#!/usr/bin/env python3
"""Inventory documentation relevant to user journey completeness."""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath


DOC_EXTENSIONS = {".md", ".mdx", ".markdown"}
SOURCE_HINT_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx", ".vue", ".svelte", ".html", ".cshtml", ".razor"}
EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".next",
    ".nuxt",
    ".svelte-kit",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "out",
    "target",
    "vendor",
}

JOURNEY_TERMS = {
    "journey",
    "workflow",
    "flow",
    "onboarding",
    "persona",
    "user",
    "route",
    "screen",
    "mobile",
    "desktop",
    "empty state",
    "error",
    "permission",
    "acceptance",
}
JOURNEY_STRUCTURE_TERMS = {
    "acceptance",
    "decision",
    "entry point",
    "failure",
    "goal",
    "primary action",
    "route",
    "screen sequence",
    "success",
    "trigger",
}
EXPLICIT_JOURNEY_TERMS = {"journey", "workflow", "user flow", "persona", "scenario"}
APP_IDEA_TERMS = {"purpose", "overview", "goal", "mission", "product", "app", "value", "problem"}
PRODUCT_STRUCTURE_TERMS = {
    "app idea",
    "goal",
    "mission",
    "problem",
    "purpose",
    "requirements",
    "target user",
    "users",
    "value",
}
UX_TERMS = {
    "navigation",
    "priority",
    "hierarchy",
    "accessibility",
    "responsive",
    "mobile",
    "progressive disclosure",
    "empty",
    "loading",
    "error",
    "undo",
}
PRIORITY_CONTRACT_TERMS = {
    "decision data",
    "decision-making information",
    "expected desktop order",
    "expected mobile order",
    "frequent action",
    "frequent actions",
    "journey priority",
    "journey priority contract",
    "low-frequency controls",
    "mobile order",
    "occasional controls",
    "primary decision",
    "primary information",
    "primary user goal",
    "rare controls",
    "rare/admin/configuration controls",
}
FIRST_VIEWPORT_TERMS = {
    "above the fold",
    "before scroll",
    "below the fold",
    "first mobile viewport",
    "first screen",
    "first visible content",
    "first viewport",
    "primary decision data visible",
    "what can the user decide",
    "without scrolling",
}
UI_AUDIT_HANDOFF_TERMS = {
    "dom measurement",
    "mockup",
    "screenshot",
    "test mode",
    "ui audit handoff",
    "ui implementation audit",
    "viewport measurement",
    "visual audit",
}
LOW_FREQUENCY_CONTROL_TERMS = {
    "admin",
    "configuration",
    "filter",
    "filters",
    "settings",
}
PRIMARY_CONTENT_TERMS = {
    "chart",
    "dashboard",
    "decision",
    "metric",
    "metrics",
    "primary content",
    "summary",
}
MOBILE_SCREEN_TERMS = {
    "mobile",
    "narrow",
    "phone",
    "responsive",
    "screen",
    "viewport",
}
ROUTE_HINT_RE = re.compile(r"(?:route|path|href|to)\s*[:=]\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass
class DocRecord:
    path: str
    kind: str
    headings: list[str]
    app_idea_hits: int
    journey_hits: int
    ux_hits: int
    priority_contract_hits: int
    first_viewport_hits: int
    ui_audit_handoff_hits: int
    likely_journey_doc: bool
    likely_product_doc: bool
    likely_priority_contract_doc: bool
    likely_first_viewport_doc: bool
    likely_ui_audit_handoff_doc: bool


@dataclass
class SourceHint:
    path: str
    routes: list[str]
    visible_text_hits: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inventory docs for user journey documentation audits.")
    parser.add_argument("--repo", default=".", help="Repository root. Defaults to cwd.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of Markdown.")
    return parser.parse_args()


def skip_dir(path: Path) -> bool:
    return any(part in EXCLUDED_DIRS for part in path.parts)


def iter_files(repo: Path):
    for root, dirs, files in os.walk(repo):
        root_path = Path(root)
        dirs[:] = [item for item in dirs if item not in EXCLUDED_DIRS]
        if skip_dir(root_path.relative_to(repo)):
            continue
        for filename in files:
            path = root_path / filename
            rel = path.relative_to(repo)
            if skip_dir(rel):
                continue
            yield path


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def count_terms(text: str, terms: set[str]) -> int:
    lowered = text.lower()
    total = 0
    for term in terms:
        pattern = r"(?<![a-z0-9])" + re.escape(term.lower()).replace(r"\ ", r"\s+") + r"(?![a-z0-9])"
        total += len(re.findall(pattern, lowered))
    return total


def has_any_term(text: str, terms: set[str]) -> bool:
    return count_terms(text, terms) > 0


def journey_structure_score(text: str) -> int:
    return sum(1 for term in JOURNEY_STRUCTURE_TERMS if count_terms(text, {term}))


def is_operational_skill_doc(rel_path: str) -> bool:
    parts = PurePosixPath(rel_path).parts
    return len(parts) >= 2 and parts[0] == "skills"


def is_operational_docs_repo_text(text: str) -> bool:
    lowered = text.lower()
    markers = (
        "codex skill",
        "codex skills",
        "skill directory",
        "skill directories",
        "skills/",
        "full_repo_harness",
        "scripts/validate.py",
    )
    return any(marker in lowered for marker in markers)


def is_operational_doc(rel_path: str, text: str) -> bool:
    return is_operational_skill_doc(rel_path) or is_operational_docs_repo_text(text)


def is_likely_journey_doc(rel_path: str, text: str, journey_hits: int) -> bool:
    if is_operational_doc(rel_path, text):
        return False
    lowered = text.lower()
    structural_score = journey_structure_score(lowered)
    explicit = has_any_term(lowered, EXPLICIT_JOURNEY_TERMS)
    return (explicit and structural_score >= 1) or (journey_hits >= 3 and structural_score >= 2)


def is_likely_product_doc(rel_path: str, text: str, app_hits: int) -> bool:
    if is_operational_doc(rel_path, text):
        return False
    lowered = text.lower()
    structural_score = sum(1 for term in PRODUCT_STRUCTURE_TERMS if count_terms(lowered, {term}))
    has_product_language = has_any_term(lowered, {"product", "requirements", "app idea", "overview"})
    return (has_product_language and structural_score >= 2) or app_hits >= 4


def is_likely_priority_contract_doc(rel_path: str, text: str) -> bool:
    if is_operational_doc(rel_path, text):
        return False
    lowered = text.lower()
    has_goal = has_any_term(lowered, {"primary user goal", "primary goal", "goal"})
    has_information = has_any_term(lowered, {"primary information", "decision data", "decision-making information", "primary decision"})
    has_action_frequency = has_any_term(lowered, {"frequent action", "frequent actions", "occasional controls", "rare controls", "rare/admin/configuration controls"})
    has_order = has_any_term(lowered, {"expected mobile order", "mobile order", "expected desktop order", "desktop order"})
    explicit_contract = has_any_term(lowered, {"journey priority contract", "journey priority"})
    return explicit_contract or (has_goal and has_information and has_action_frequency and has_order)


def is_likely_first_viewport_doc(rel_path: str, text: str) -> bool:
    if is_operational_doc(rel_path, text):
        return False
    lowered = text.lower()
    explicit_viewport = has_any_term(lowered, FIRST_VIEWPORT_TERMS)
    has_decision = has_any_term(lowered, {"primary decision data visible", "what can the user decide", "primary information", "decision data"})
    has_controls = has_any_term(lowered, {"low-frequency controls", "settings", "filters", "configuration", "rare controls"})
    return explicit_viewport and has_decision and has_controls


def is_likely_ui_audit_handoff_doc(rel_path: str, text: str) -> bool:
    if is_operational_doc(rel_path, text):
        return False
    lowered = text.lower()
    return has_any_term(lowered, {"ui implementation audit", "ui audit handoff"}) or (
        has_any_term(lowered, {"mockup", "screenshot", "viewport measurement"})
        and is_likely_priority_contract_doc(rel_path, text)
        and is_likely_first_viewport_doc(rel_path, text)
    )


def classify_doc(rel_path: str, text: str) -> str:
    lowered = rel_path.lower()
    if "readme" in lowered:
        return "readme"
    if any(term in lowered for term in ("journey", "workflow", "flow", "persona", "product", "spec")):
        return "product-doc"
    if any(term in lowered for term in ("architecture", "design", "adr")):
        return "architecture-doc"
    if "test" in lowered or "qa" in lowered:
        return "test-doc"
    if is_likely_journey_doc(rel_path, text, count_terms(text, JOURNEY_TERMS)):
        return "journey-candidate"
    return "doc"


def doc_record(repo: Path, path: Path) -> DocRecord:
    text = read_text(path)
    rel = path.relative_to(repo).as_posix()
    headings = [match.group(2).strip() for line in text.splitlines() if (match := HEADING_RE.match(line))]
    app_hits = count_terms(text, APP_IDEA_TERMS)
    journey_hits = count_terms(text, JOURNEY_TERMS)
    ux_hits = count_terms(text, UX_TERMS)
    priority_hits = count_terms(text, PRIORITY_CONTRACT_TERMS)
    first_viewport_hits = count_terms(text, FIRST_VIEWPORT_TERMS)
    handoff_hits = count_terms(text, UI_AUDIT_HANDOFF_TERMS)
    likely_journey = is_likely_journey_doc(rel, text, journey_hits)
    likely_product = is_likely_product_doc(rel, text, app_hits)
    likely_priority = is_likely_priority_contract_doc(rel, text)
    likely_first_viewport = is_likely_first_viewport_doc(rel, text)
    likely_handoff = is_likely_ui_audit_handoff_doc(rel, text)
    return DocRecord(
        path=rel,
        kind=classify_doc(rel, text),
        headings=headings[:20],
        app_idea_hits=app_hits,
        journey_hits=journey_hits,
        ux_hits=ux_hits,
        priority_contract_hits=priority_hits,
        first_viewport_hits=first_viewport_hits,
        ui_audit_handoff_hits=handoff_hits,
        likely_journey_doc=likely_journey,
        likely_product_doc=likely_product,
        likely_priority_contract_doc=likely_priority,
        likely_first_viewport_doc=likely_first_viewport,
        likely_ui_audit_handoff_doc=likely_handoff,
    )


def source_hint(repo: Path, path: Path) -> SourceHint | None:
    text = read_text(path)
    routes = sorted(set(match.group(1) for match in ROUTE_HINT_RE.finditer(text)))[:30]
    visible_text_hits = len(re.findall(r">[^<]{3,}<|aria-label=|placeholder=|title=", text))
    if not routes and not visible_text_hits:
        return None
    return SourceHint(path=path.relative_to(repo).as_posix(), routes=routes, visible_text_hits=visible_text_hits)


def build_inventory(repo: Path) -> dict:
    docs: list[DocRecord] = []
    hints: list[SourceHint] = []
    for path in iter_files(repo):
        if path.suffix.lower() in DOC_EXTENSIONS:
            docs.append(doc_record(repo, path))
        elif path.suffix.lower() in SOURCE_HINT_EXTENSIONS:
            hint = source_hint(repo, path)
            if hint:
                hints.append(hint)
    missing_signals: list[str] = []
    ui_implementation_risk_signals: list[str] = []
    if not any(doc.likely_product_doc for doc in docs):
        missing_signals.append("No strong app idea/product overview documentation detected.")
    if not any(doc.likely_journey_doc for doc in docs):
        missing_signals.append("No strong user journey/workflow/persona documentation detected.")
    if sum(doc.ux_hits for doc in docs) < 3:
        missing_signals.append("Very little UI/UX hierarchy, navigation, responsive, or accessibility documentation detected.")
    priority_contract_doc_count = sum(1 for doc in docs if doc.likely_priority_contract_doc)
    first_viewport_doc_count = sum(1 for doc in docs if doc.likely_first_viewport_doc)
    ui_audit_handoff_doc_count = sum(1 for doc in docs if doc.likely_ui_audit_handoff_doc)
    doc_texts = [read_text(repo / doc.path).lower() for doc in docs]
    has_mobile_screen_docs = any(has_any_term(text, MOBILE_SCREEN_TERMS) for text in doc_texts)
    has_low_frequency_controls = any(has_any_term(text, LOW_FREQUENCY_CONTROL_TERMS) for text in doc_texts)
    has_primary_content = any(has_any_term(text, PRIMARY_CONTENT_TERMS) for text in doc_texts)
    if docs and priority_contract_doc_count == 0:
        missing_signals.append("No journey priority contract documentation detected.")
        ui_implementation_risk_signals.append(
            "Docs do not define primary goal, primary decision information, action frequency, rare controls, and desktop/mobile order for UI implementation."
        )
    if has_mobile_screen_docs and first_viewport_doc_count == 0:
        missing_signals.append("No first-viewport usefulness documentation detected for mobile or responsive screens.")
        ui_implementation_risk_signals.append(
            "Docs mention mobile/screens but do not define first visible content, primary decision data, or what the user can decide before scrolling."
        )
    if has_mobile_screen_docs and has_low_frequency_controls and has_primary_content and first_viewport_doc_count == 0:
        ui_implementation_risk_signals.append(
            "Docs mention mobile screens plus settings/filters/configuration and primary content, but do not state that primary decision content appears before low-frequency controls."
        )
    if hints and priority_contract_doc_count == 0:
        ui_implementation_risk_signals.append(
            "Source hints expose UI surfaces, but docs do not provide the journey priority contract; source hints must not substitute for product truth."
        )
    ui_audit_handoff_ready = bool(priority_contract_doc_count and first_viewport_doc_count and ui_audit_handoff_doc_count)
    return {
        "repo_root": str(repo),
        "doc_count": len(docs),
        "journey_doc_count": sum(1 for doc in docs if doc.likely_journey_doc),
        "product_doc_count": sum(1 for doc in docs if doc.likely_product_doc),
        "priority_contract_doc_count": priority_contract_doc_count,
        "first_viewport_doc_count": first_viewport_doc_count,
        "ui_audit_handoff_doc_count": ui_audit_handoff_doc_count,
        "ui_audit_handoff_ready": ui_audit_handoff_ready,
        "source_hint_count": len(hints),
        "docs": [asdict(doc) for doc in sorted(docs, key=lambda item: item.path)],
        "source_hints": [asdict(hint) for hint in sorted(hints, key=lambda item: item.path)[:100]],
        "missing_signals": missing_signals,
        "ui_implementation_risk_signals": ui_implementation_risk_signals,
    }


def print_markdown(inventory: dict) -> None:
    print(f"# Journey Documentation Inventory\n")
    print(f"Repo root: `{inventory['repo_root']}`")
    print(f"Docs: **{inventory['doc_count']}**")
    print(f"Likely journey docs: **{inventory['journey_doc_count']}**")
    print(f"Likely product docs: **{inventory['product_doc_count']}**")
    print(f"Journey priority docs: **{inventory['priority_contract_doc_count']}**")
    print(f"First viewport docs: **{inventory['first_viewport_doc_count']}**")
    print(f"UI audit handoff ready: **{str(inventory['ui_audit_handoff_ready']).lower()}**")
    print(f"Source hint files: **{inventory['source_hint_count']}**\n")
    if inventory["missing_signals"]:
        print("## Missing Signals")
        for item in inventory["missing_signals"]:
            print(f"- {item}")
        print()
    if inventory["ui_implementation_risk_signals"]:
        print("## UI Implementation Risk Signals")
        for item in inventory["ui_implementation_risk_signals"]:
            print(f"- {item}")
        print()
    print("## Docs")
    print("| File | Kind | Headings | Journey hits | UX hits | Priority hits | First viewport hits |")
    print("| --- | --- | --- | ---: | ---: | ---: | ---: |")
    for doc in inventory["docs"]:
        headings = "; ".join(doc["headings"][:5]) or "None"
        print(
            f"| `{doc['path']}` | {doc['kind']} | {headings.replace('|', '/')} | "
            f"{doc['journey_hits']} | {doc['ux_hits']} | {doc['priority_contract_hits']} | {doc['first_viewport_hits']} |"
        )


def main() -> int:
    args = parse_args()
    repo = Path(args.repo).expanduser().resolve()
    if not repo.is_dir():
        raise SystemExit(f"Repo path is not a directory: {repo}")
    inventory = build_inventory(repo)
    if args.json:
        print(json.dumps(inventory, indent=2, sort_keys=True))
    else:
        print_markdown(inventory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
