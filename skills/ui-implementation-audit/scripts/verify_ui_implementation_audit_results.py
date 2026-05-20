#!/usr/bin/env python3
"""Verify returned reports for the ui-implementation-audit skill."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REPO_ROOT = Path(__file__).resolve().parents[3]
VENDOR_ROOT = SCRIPT_DIR / "_vendor"
DEV_SKILL_DIR = (REPO_ROOT / "skills" / "ui-implementation-audit").resolve()
running_in_dev_repo = DEV_SKILL_DIR == SKILL_DIR.resolve() and (REPO_ROOT / "full_repo_harness" / "verify_common.py").is_file()

path_roots = [REPO_ROOT, VENDOR_ROOT] if running_in_dev_repo else [VENDOR_ROOT]
for root in reversed([item for item in path_roots if item.is_dir()]):
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)

from full_repo_harness import verify_common as common


BATCH_SECTIONS = [
    "run id",
    "batch id",
    "batch summary",
    "file coverage",
    "ui source inventory",
    "journey priority contract",
    "first viewport journey check",
    "mockup and journey alignment",
    "implementation gap findings",
    "no gap notes",
    "open questions",
]
MOCKUP_SECTIONS = [
    "run id",
    "worker",
    "mockup/asset inputs",
    "journey requirement inputs",
    "expected screens and visual requirements",
    "findings",
    "open questions",
]
TOOLING_SECTIONS = [
    "run id",
    "worker",
    "tooling inventory",
    "safe run path",
    "desktop/mobile screenshot plan",
    "findings",
    "open questions",
]
VISUAL_SECTIONS = [
    "run id",
    "worker",
    "journey priority contract",
    "first viewport journey check",
    "visual comparison checks",
    "findings",
    "open questions",
]
REQUIRED_FINDING_FIELDS = [
    "Priority",
    "Files",
    "Mockup/requirement evidence",
    "Interface evidence",
    "Expected behavior/standard",
    "Gap",
    "Suggested implementation direction",
]
VISUAL_RESULT_VALUES = {"MATCHED", "GAP", "BLOCKED", "NOT_APPLICABLE"}
VISUAL_EVIDENCE_RE = re.compile(
    r"\b(screenshot|screen shot|png|jpg|jpeg|webp|trace|video|playwright|cypress|storybook|browser|native|preview|simulator|xcode|android|blocked|unavailable|not applicable|no runnable|no safe)\b",
    re.IGNORECASE,
)
FIRST_VIEWPORT_EVIDENCE_RE = re.compile(
    r"\b(screenshot|screen shot|png|jpg|jpeg|webp|trace|video|playwright|cypress|storybook|browser|preview|simulator|dom|viewport|measurement|measured|px|%|fold|scroll|source|css|blocked|unavailable|not applicable|no safe)\b",
    re.IGNORECASE,
)
JOURNEY_PRIORITY_COLUMNS = {
    "surface",
    "primary user goal",
    "primary information",
    "frequent actions",
    "occasional controls",
    "rare/admin/configuration controls",
    "expected desktop order",
    "expected mobile order",
}
FIRST_VIEWPORT_COLUMNS = {
    "viewport",
    "first visible content",
    "primary decision data visible?",
    "low-frequency controls above content?",
    "low-frequency/header/control share",
    "what can user decide from first viewport?",
    "result",
    "evidence",
}
FIRST_VIEWPORT_RESULT_VALUES = {"PASS", "GAP", "BLOCKED", "NOT_APPLICABLE"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify ui-implementation-audit reports.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--reports", nargs="+", required=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--skip-current-hash-check", action="store_true")
    return parser.parse_args()


def load_manifest(path: Path) -> dict:
    manifest = common.load_json_object(path, "manifest")
    if manifest.get("audit_kind") != "ui-implementation":
        raise ValueError("manifest audit_kind must be 'ui-implementation'.")
    source_files = manifest.get("source_files")
    batches = manifest.get("batches")
    coverage_units = manifest.get("coverage_units")
    if not isinstance(source_files, list):
        raise ValueError("manifest source_files must be a list.")
    if not isinstance(batches, list):
        raise ValueError("manifest batches must be a list.")
    if not isinstance(coverage_units, list):
        raise ValueError("manifest coverage_units must be a list.")

    source_paths: list[str] = []
    source_hashes: dict[str, str] = {}
    for index, item in enumerate(source_files):
        if not isinstance(item, dict) or not isinstance(item.get("rel_path"), str):
            raise ValueError(f"source_files[{index}] must contain rel_path.")
        rel_path = item["rel_path"]
        source_paths.append(rel_path)
        sha = item.get("sha256")
        if not isinstance(sha, str) or not common.SHA256_RE.fullmatch(sha):
            raise ValueError(f"source_files[{index}].sha256 must be a SHA-256 hex digest.")
        source_hashes[rel_path] = sha
        if item.get("interface_relevant") is not True:
            raise ValueError(f"source_files[{index}] must be interface_relevant.")
        if item.get("kind") == "source/ui-asset":
            raise ValueError(f"source_files[{index}] must not be a visual asset batch entry.")
    duplicates = common.duplicate_values(source_paths)
    if duplicates:
        raise ValueError(f"source_files rel_path values must be unique: {duplicates}")

    source_set = set(source_paths)
    unit_to_file: dict[str, str] = {}
    unit_hashes: dict[str, str] = {}
    for index, unit in enumerate(coverage_units):
        if not isinstance(unit, dict) or not isinstance(unit.get("unit_id"), str) or not isinstance(unit.get("rel_path"), str):
            raise ValueError(f"coverage_units[{index}] must contain unit_id and rel_path.")
        if unit["rel_path"] not in source_set:
            raise ValueError(f"coverage_units[{index}].rel_path is absent from source_files: {unit['rel_path']}")
        unit_to_file[unit["unit_id"]] = unit["rel_path"]
        sha = unit.get("sha256") or source_hashes[unit["rel_path"]]
        if not isinstance(sha, str) or not common.SHA256_RE.fullmatch(sha):
            raise ValueError(f"coverage_units[{index}].sha256 must be a SHA-256 hex digest.")
        unit_hashes[unit["unit_id"]] = sha
    duplicate_units = common.duplicate_values(list(unit_to_file))
    if duplicate_units:
        raise ValueError(f"coverage_units unit_id values must be unique: {duplicate_units}")

    expected_by_batch: dict[str, set[str]] = {}
    files_by_batch: dict[str, set[str]] = {}
    assigned_units: list[str] = []
    for index, batch in enumerate(batches):
        if not isinstance(batch, dict) or not isinstance(batch.get("id"), str):
            raise ValueError(f"batches[{index}] must contain id.")
        units = batch.get("coverage_units")
        files = batch.get("files")
        if not isinstance(units, list) or not all(isinstance(item, str) for item in units):
            raise ValueError(f"batches[{index}].coverage_units must be a list of strings.")
        if not isinstance(files, list) or not all(isinstance(item, str) for item in files):
            raise ValueError(f"batches[{index}].files must be a list of strings.")
        unknown_units = sorted(set(units) - set(unit_to_file))
        if unknown_units:
            raise ValueError(f"batch {batch['id']} references unknown coverage units: {unknown_units}")
        expected_by_batch[batch["id"]] = set(units)
        files_by_batch[batch["id"]] = set(files)
        assigned_units.extend(units)
    missing_units = sorted(set(unit_to_file) - set(assigned_units))
    extra_units = sorted(set(assigned_units) - set(unit_to_file))
    duplicate_assignments = common.duplicate_values(assigned_units)
    if missing_units or extra_units or duplicate_assignments:
        raise ValueError(
            f"coverage unit assignment mismatch; missing={missing_units} extra={extra_units} duplicates={duplicate_assignments}"
        )

    audit = manifest.get("ui_implementation_audit")
    if not isinstance(audit, dict):
        raise ValueError("manifest ui_implementation_audit must be an object.")
    asset_hashes: dict[str, str] = {}
    for index, item in enumerate(audit.get("visual_assets", [])):
        if not isinstance(item, dict) or not isinstance(item.get("rel_path"), str):
            raise ValueError(f"visual_assets[{index}] must contain rel_path.")
        sha = item.get("sha256")
        if not isinstance(sha, str) or not common.SHA256_RE.fullmatch(sha):
            raise ValueError(f"visual_assets[{index}].sha256 must be a SHA-256 hex digest.")
        asset_hashes[item["rel_path"]] = sha
    requirement_hashes: dict[str, str] = {}
    for index, item in enumerate(audit.get("requirement_sources", [])):
        if not isinstance(item, dict) or not isinstance(item.get("rel_path"), str):
            raise ValueError(f"requirement_sources[{index}] must contain rel_path.")
        sha = item.get("sha256")
        if not isinstance(sha, str) or not common.SHA256_RE.fullmatch(sha):
            raise ValueError(f"requirement_sources[{index}].sha256 must be a SHA-256 hex digest.")
        requirement_hashes[item["rel_path"]] = sha

    manifest["_source_hashes"] = source_hashes
    manifest["_asset_hashes"] = asset_hashes
    manifest["_requirement_hashes"] = requirement_hashes
    manifest["_unit_hashes"] = unit_hashes
    manifest["_unit_to_file"] = unit_to_file
    manifest["_expected_by_batch"] = expected_by_batch
    manifest["_files_by_batch"] = files_by_batch
    return manifest


def first_declared_value(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip().strip("`")
        if stripped:
            return stripped
    return ""


def split_files(value: str) -> list[str]:
    cleaned = value.replace("`", "")
    parts = re.split(r"[,;]", cleaned)
    return [part.strip() for part in parts if part.strip() and part.strip().lower() not in {"none"}]


def finding_blocks(text: str) -> list[dict[str, str]]:
    if text.strip() == "No findings.":
        return []
    blocks: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for raw in text.splitlines():
        match = re.match(r"^-\s+([^:]+):\s*(.*)$", raw.strip())
        if not match:
            continue
        key = match.group(1).strip()
        value = match.group(2).strip()
        if key == "Priority" and current:
            blocks.append(current)
            current = {}
        current[key] = value
    if current:
        blocks.append(current)
    return blocks


def validate_findings(text: str, allowed_files: set[str], path: Path, section: str, *, allow_not_applicable: bool = False) -> list[dict]:
    issues: list[dict] = []
    stripped = text.strip()
    if not stripped:
        return [{"path": str(path), "section": section, "reason": "findings section is empty"}]
    if stripped == "No findings.":
        return []
    blocks = finding_blocks(text)
    if not blocks:
        return [{"path": str(path), "section": section, "reason": "findings must use required field blocks or exact sentinel"}]
    for index, block in enumerate(blocks, start=1):
        missing = [field for field in REQUIRED_FINDING_FIELDS if not block.get(field)]
        if missing:
            issues.append({"path": str(path), "section": section, "finding": index, "missing_fields": missing})
        priority = block.get("Priority", "")
        if priority and priority not in {"P0", "P1", "P2", "P3"}:
            issues.append({"path": str(path), "section": section, "finding": index, "field": "Priority", "actual": priority})
        files = split_files(block.get("Files", ""))
        if not files:
            issues.append({"path": str(path), "section": section, "finding": index, "field": "Files", "reason": "no files listed"})
            continue
        normalized = {item for item in files if item.lower() not in {"not-applicable", "not applicable", "n/a"}}
        if not normalized and not allow_not_applicable:
            issues.append({"path": str(path), "section": section, "finding": index, "field": "Files", "reason": "not-applicable not allowed here"})
        unknown = sorted(normalized - allowed_files)
        if unknown:
            issues.append({"path": str(path), "section": section, "finding": index, "field": "Files", "out_of_scope": unknown})
    return issues


def parse_percentage(value: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", value)
    if not match:
        return None
    return float(match.group(1))


def is_mobile_viewport(value: str) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in ("mobile", "narrow", "phone", "390", "375", "360", "320"))


def is_negative(value: str) -> bool:
    lowered = value.lower()
    return bool(re.search(r"\b(no|not visible|below fold|below the fold|after scroll|hidden|cropped)\b", lowered))


def is_affirmative(value: str) -> bool:
    lowered = value.lower()
    return bool(re.search(r"\b(yes|true|above|dominates|dominant|settings|filters|configuration|config|controls)\b", lowered))


def has_p1_first_viewport_finding(findings: str) -> bool:
    for block in finding_blocks(findings):
        if block.get("Priority") != "P1":
            continue
        combined = " ".join(block.values()).lower()
        if any(token in combined for token in ("first viewport", "above the fold", "below the fold", "journey priority", "mobile", "settings", "filters", "configuration")):
            return True
    return False


def verify_journey_priority_contract(path: Path, body: str) -> list[dict]:
    issues: list[dict] = []
    rows = common.parse_markdown_table_dicts(body)
    if not rows:
        return [{"path": str(path), "section": "Journey Priority Contract", "reason": "missing journey priority table"}]
    for index, row in enumerate(rows, start=1):
        missing_columns = sorted(JOURNEY_PRIORITY_COLUMNS - set(row))
        if missing_columns:
            issues.append({"path": str(path), "section": "Journey Priority Contract", "row": index, "missing_columns": missing_columns})
            continue
        for field in JOURNEY_PRIORITY_COLUMNS:
            if not row.get(field, "").strip():
                issues.append({"path": str(path), "section": "Journey Priority Contract", "row": index, "field": field, "reason": "empty"})
    return issues


def first_viewport_priority_failure(row: dict[str, str]) -> bool:
    if not is_mobile_viewport(row.get("viewport", "")):
        return False
    primary_hidden = is_negative(row.get("primary decision data visible?", ""))
    controls_above = is_affirmative(row.get("low-frequency controls above content?", ""))
    share = parse_percentage(row.get("low-frequency/header/control share", ""))
    controls_dominate = share is not None and share >= 25
    content_text = " ".join(
        row.get(field, "")
        for field in (
            "first visible content",
            "low-frequency controls above content?",
            "what can user decide from first viewport?",
        )
    ).lower()
    low_value_content_first = any(token in content_text for token in ("setting", "filter", "configuration", "config", "target currency", "admin control"))
    return primary_hidden and (controls_above or controls_dominate or low_value_content_first)


def verify_first_viewport_table(path: Path, body: str, findings: str, *, require_visual_evidence: bool = False) -> list[dict]:
    issues: list[dict] = []
    rows = common.parse_markdown_table_dicts(body)
    if not rows:
        return [{"path": str(path), "section": "First Viewport Journey Check", "reason": "missing first viewport table"}]
    seen_mobile = False
    gap_or_blocked = False
    priority_failure = False
    for index, row in enumerate(rows, start=1):
        missing_columns = sorted(FIRST_VIEWPORT_COLUMNS - set(row))
        if missing_columns:
            issues.append({"path": str(path), "section": "First Viewport Journey Check", "row": index, "missing_columns": missing_columns})
            continue
        for field in FIRST_VIEWPORT_COLUMNS:
            if not row.get(field, "").strip():
                issues.append({"path": str(path), "section": "First Viewport Journey Check", "row": index, "field": field, "reason": "empty"})
        result = row.get("result", "").strip()
        if result not in FIRST_VIEWPORT_RESULT_VALUES:
            issues.append({"path": str(path), "section": "First Viewport Journey Check", "row": index, "field": "Result", "expected": sorted(FIRST_VIEWPORT_RESULT_VALUES), "actual": result})
        if result in {"GAP", "BLOCKED"}:
            gap_or_blocked = True
        if is_mobile_viewport(row.get("viewport", "")):
            seen_mobile = True
        evidence = row.get("evidence", "")
        if evidence.strip() and not FIRST_VIEWPORT_EVIDENCE_RE.search(evidence):
            issues.append({"path": str(path), "section": "First Viewport Journey Check", "row": index, "field": "Evidence", "reason": "must name screenshot, DOM/viewport measurement, source evidence, or a concrete blocker"})
        if require_visual_evidence and evidence.strip() and not (VISUAL_EVIDENCE_RE.search(evidence) or re.search(r"\b(dom|viewport|measurement|measured|px|%|fold)\b", evidence, re.IGNORECASE)):
            issues.append({"path": str(path), "section": "First Viewport Journey Check", "row": index, "field": "Evidence", "reason": "visual first-viewport checks require screenshot/tool evidence, DOM measurement, viewport measurement, or a concrete blocker"})
        if first_viewport_priority_failure(row):
            priority_failure = True
            if result != "GAP":
                issues.append({"path": str(path), "section": "First Viewport Journey Check", "row": index, "field": "Result", "reason": "mobile first viewport priority failure must be marked GAP"})
    if not seen_mobile:
        issues.append({"path": str(path), "section": "First Viewport Journey Check", "reason": "mobile/narrow viewport row is required"})
    if gap_or_blocked and findings.strip() == "No findings.":
        issues.append({"path": str(path), "section": "Findings", "reason": "GAP or BLOCKED first-viewport rows require a finding"})
    if priority_failure and not has_p1_first_viewport_finding(findings):
        issues.append({"path": str(path), "section": "Findings", "reason": "mobile first viewport priority failure requires a P1 journey-priority finding"})
    return issues


def verify_batch_report(path: Path, manifest: dict, batch_id: str) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    order = common.section_order(text)
    bodies = common.section_bodies(text)
    issues: list[dict] = []
    if order != BATCH_SECTIONS:
        issues.append({"path": str(path), "reason": "batch report sections must match required order", "expected": BATCH_SECTIONS, "actual": order})
    if first_declared_value(bodies.get("run id", "")) != manifest["run_id"]:
        issues.append({"path": str(path), "field": "Run ID", "expected": manifest["run_id"], "actual": first_declared_value(bodies.get("run id", ""))})
    if first_declared_value(bodies.get("batch id", "")) != batch_id:
        issues.append({"path": str(path), "field": "Batch ID", "expected": batch_id, "actual": first_declared_value(bodies.get("batch id", ""))})

    expected_units = manifest["_expected_by_batch"][batch_id]
    expected_files = manifest["_files_by_batch"][batch_id]
    unit_hashes = manifest["_unit_hashes"]
    unit_to_file = manifest["_unit_to_file"]

    coverage_rows = common.parse_markdown_table_dicts(bodies.get("file coverage", ""))
    if not coverage_rows:
        issues.append({"path": str(path), "section": "File Coverage", "reason": "missing coverage table"})
    covered_units = {row.get("unit", "") for row in coverage_rows}
    missing = sorted(expected_units - covered_units)
    extra = sorted(covered_units - expected_units)
    if missing or extra:
        issues.append({"path": str(path), "section": "File Coverage", "missing_units": missing, "extra_units": extra})
    for row in coverage_rows:
        unit = row.get("unit", "")
        if row.get("status") != "CHECKED":
            issues.append({"path": str(path), "section": "File Coverage", "unit": unit, "field": "Status", "actual": row.get("status")})
        if unit in unit_hashes and row.get("sha-256") != unit_hashes[unit]:
            issues.append({"path": str(path), "section": "File Coverage", "unit": unit, "field": "SHA-256", "expected": unit_hashes[unit], "actual": row.get("sha-256")})
        if not row.get("purpose", "").strip():
            issues.append({"path": str(path), "section": "File Coverage", "unit": unit, "field": "Purpose", "reason": "empty"})

    inventory_rows = common.parse_markdown_table_dicts(bodies.get("ui source inventory", ""))
    if not inventory_rows:
        issues.append({"path": str(path), "section": "UI Source Inventory", "reason": "missing UI source inventory table"})
    for row in inventory_rows:
        unit = row.get("unit", "")
        rel_file = row.get("file", "")
        if unit not in expected_units:
            issues.append({"path": str(path), "section": "UI Source Inventory", "unit": unit, "reason": "unit is outside this batch"})
        expected_file = unit_to_file.get(unit)
        if rel_file not in expected_files or (expected_file and rel_file != expected_file):
            issues.append({"path": str(path), "section": "UI Source Inventory", "file": rel_file, "reason": "file is outside this batch or mismatched to unit"})
        for field in ("surface", "visible element", "source evidence", "expected behavior", "actual implementation", "responsive/state notes"):
            if not row.get(field, "").strip():
                issues.append({"path": str(path), "section": "UI Source Inventory", "unit": unit, "field": field, "reason": "empty"})

    findings = bodies.get("implementation gap findings", "")
    issues.extend(verify_journey_priority_contract(path, bodies.get("journey priority contract", "")))
    issues.extend(verify_first_viewport_table(path, bodies.get("first viewport journey check", ""), findings))
    issues.extend(validate_findings(findings, expected_files, path, "Implementation Gap Findings"))
    for section in ("batch summary", "mockup and journey alignment", "no gap notes", "open questions"):
        if not bodies.get(section, "").strip():
            issues.append({"path": str(path), "section": section, "reason": "empty"})
    return issues


def verify_aux_report(path: Path, manifest: dict, expected_sections: list[str], worker: str, allowed_files: set[str]) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    order = common.section_order(text)
    bodies = common.section_bodies(text)
    issues: list[dict] = []
    if order != expected_sections:
        issues.append({"path": str(path), "reason": "worker report sections must match required order", "expected": expected_sections, "actual": order})
    if first_declared_value(bodies.get("run id", "")) != manifest["run_id"]:
        issues.append({"path": str(path), "field": "Run ID", "expected": manifest["run_id"], "actual": first_declared_value(bodies.get("run id", ""))})
    if first_declared_value(bodies.get("worker", "")) != worker:
        issues.append({"path": str(path), "field": "Worker", "expected": worker, "actual": first_declared_value(bodies.get("worker", ""))})
    issues.extend(validate_findings(bodies.get("findings", ""), allowed_files, path, "Findings", allow_not_applicable=True))
    for section in expected_sections:
        if not bodies.get(section, "").strip():
            issues.append({"path": str(path), "section": section, "reason": "empty"})
    if worker == "visual_comparison_audit":
        issues.extend(verify_journey_priority_contract(path, bodies.get("journey priority contract", "")))
        issues.extend(verify_first_viewport_table(path, bodies.get("first viewport journey check", ""), bodies.get("findings", ""), require_visual_evidence=True))
        issues.extend(verify_visual_comparison_table(path, bodies.get("visual comparison checks", ""), bodies.get("findings", "")))
    return issues


def verify_visual_comparison_table(path: Path, body: str, findings: str) -> list[dict]:
    issues: list[dict] = []
    rows = common.parse_markdown_table_dicts(body)
    if not rows:
        return [{"path": str(path), "section": "Visual Comparison Checks", "reason": "missing visual comparison table"}]
    required = {
        "journey",
        "viewport",
        "route/screen",
        "mockup/requirement",
        "implementation screenshot/tool evidence",
        "differences",
        "result",
    }
    viewports: set[str] = set()
    non_not_applicable = False
    blocked_or_gap = False
    for index, row in enumerate(rows, start=1):
        missing_columns = sorted(required - set(row))
        if missing_columns:
            issues.append({"path": str(path), "section": "Visual Comparison Checks", "row": index, "missing_columns": missing_columns})
            continue
        for field in required:
            if not row.get(field, "").strip():
                issues.append({"path": str(path), "section": "Visual Comparison Checks", "row": index, "field": field, "reason": "empty"})
        result = row.get("result", "").strip()
        if result not in VISUAL_RESULT_VALUES:
            issues.append({"path": str(path), "section": "Visual Comparison Checks", "row": index, "field": "Result", "expected": sorted(VISUAL_RESULT_VALUES), "actual": result})
        if result != "NOT_APPLICABLE":
            non_not_applicable = True
        if result in {"GAP", "BLOCKED"}:
            blocked_or_gap = True
        viewport = row.get("viewport", "").lower()
        if "desktop" in viewport:
            viewports.add("desktop")
        if "mobile" in viewport or "narrow" in viewport or "phone" in viewport:
            viewports.add("mobile")
        evidence = row.get("implementation screenshot/tool evidence", "")
        if evidence.strip() and not VISUAL_EVIDENCE_RE.search(evidence):
            issues.append(
                {
                    "path": str(path),
                    "section": "Visual Comparison Checks",
                    "row": index,
                    "field": "Implementation Screenshot/Tool Evidence",
                    "reason": "must name screenshot/trace/tool evidence or a concrete blocker",
                }
            )
    if non_not_applicable and {"desktop", "mobile"} - viewports:
        issues.append({"path": str(path), "section": "Visual Comparison Checks", "reason": "desktop and mobile/narrow viewport rows are required when visual checks are applicable", "viewports_found": sorted(viewports)})
    if blocked_or_gap and findings.strip() == "No findings.":
        issues.append({"path": str(path), "section": "Findings", "reason": "GAP or BLOCKED visual rows require a finding"})
    return issues


def verify_marker(manifest_path: Path, manifest: dict) -> list[dict]:
    marker_path = manifest_path.parent / "queue_complete.json"
    if not marker_path.is_file():
        return [{"path": str(marker_path), "reason": "queue_complete.json is missing"}]
    marker = common.load_json_object(marker_path, "queue_complete.json")
    expected = {
        "run_id": manifest["run_id"],
        "phase": "queue_generated",
        "audit_verified": False,
        "audit_kind": "ui-implementation",
        "manifest": "manifest.json",
        "audit_index": "audit_index.md",
        "effort_ledger": "effort_ledger.json",
        "excluded_files": "excluded_files.json",
        "reports_dir": "reports",
        "ownership_marker": ".ui-implementation-audit-artifacts.json",
        "batch_count": manifest["batch_count"],
        "source_file_count": manifest["source_file_count"],
    }
    return [
        {"path": str(marker_path), "field": key, "expected": value, "actual": marker.get(key)}
        for key, value in expected.items()
        if marker.get(key) != value
    ]


def verify_excluded_files(manifest_path: Path, manifest: dict) -> tuple[list[dict], list[dict]]:
    excluded_path = manifest_path.parent / "excluded_files.json"
    excluded = common.load_json_list(excluded_path, "excluded_files.json")
    issues: list[dict] = []
    if manifest.get("excluded_file_count") != len(excluded):
        issues.append({"path": str(excluded_path), "field": "excluded_file_count", "expected": manifest.get("excluded_file_count"), "actual": len(excluded)})
    digest = common.canonical_json_sha256(excluded)
    if manifest.get("excluded_files_sha256") != digest:
        issues.append({"path": str(excluded_path), "field": "excluded_files_sha256", "expected": manifest.get("excluded_files_sha256"), "actual": digest})
    warnings = [item for item in excluded if isinstance(item, dict) and item.get("scope_warning")]
    if warnings:
        issues.append({"path": str(excluded_path), "reason": "unresolved scope warnings", "scope_warnings": warnings})
    return warnings, issues


def verify_effort_ledger(manifest_path: Path, manifest: dict) -> list[dict]:
    ledger_path = manifest_path.parent / "effort_ledger.json"
    if not ledger_path.is_file():
        return [{"path": str(ledger_path), "reason": "effort_ledger.json is missing"}]
    ledger = common.load_json_object(ledger_path, "effort_ledger.json")
    issues: list[dict] = []
    if ledger.get("run_id") != manifest["run_id"]:
        issues.append({"path": str(ledger_path), "field": "run_id", "expected": manifest["run_id"], "actual": ledger.get("run_id")})
    capability = ledger.get("subagent_capability_check", {})
    if not isinstance(capability, dict):
        issues.append({"path": str(ledger_path), "field": "subagent_capability_check", "reason": "must be an object"})
    else:
        if capability.get("status") != "completed":
            issues.append({"path": str(ledger_path), "field": "subagent_capability_check.status", "expected": "completed", "actual": capability.get("status")})
        if not isinstance(capability.get("can_set_reasoning_effort"), bool):
            issues.append({"path": str(ledger_path), "field": "subagent_capability_check.can_set_reasoning_effort", "expected": "boolean", "actual": capability.get("can_set_reasoning_effort")})
        if not capability.get("spawn_tool"):
            issues.append({"path": str(ledger_path), "field": "subagent_capability_check.spawn_tool", "expected": "non-empty string", "actual": capability.get("spawn_tool")})
    lead = ledger.get("lead_effort", {})
    if not isinstance(lead, dict) or lead.get("status") not in {"completed", "confirmed", "manual-fallback-completed"}:
        issues.append({"path": str(ledger_path), "field": "lead_effort.status", "expected": "completed/confirmed", "actual": lead.get("status") if isinstance(lead, dict) else None})
    elif lead.get("actual_reasoning_effort") not in {"high", "xhigh", "high-or-higher"}:
        issues.append({"path": str(ledger_path), "field": "lead_effort.actual_reasoning_effort", "expected": "high or xhigh", "actual": lead.get("actual_reasoning_effort")})
    if isinstance(lead, dict) and not lead.get("runtime_provenance"):
        issues.append({"path": str(ledger_path), "field": "lead_effort.runtime_provenance", "expected": "non-empty string", "actual": lead.get("runtime_provenance")})
    workers = ledger.get("batch_workers")
    if not isinstance(workers, list):
        return issues + [{"path": str(ledger_path), "field": "batch_workers", "reason": "must be a list"}]
    by_id = {item.get("batch_id"): item for item in workers if isinstance(item, dict)}
    for batch in manifest["batches"]:
        row = by_id.get(batch["id"])
        if not row:
            issues.append({"path": str(ledger_path), "field": "batch_workers", "missing": batch["id"]})
        elif row.get("status") not in {"completed", "manual-fallback-completed"}:
            issues.append({"path": str(ledger_path), "batch_id": batch["id"], "field": "status", "actual": row.get("status")})
        else:
            if row.get("actual_reasoning_effort") != "low" and row.get("status") != "manual-fallback-completed":
                issues.append({"path": str(ledger_path), "batch_id": batch["id"], "field": "actual_reasoning_effort", "expected": "low", "actual": row.get("actual_reasoning_effort")})
            if not row.get("agent_id"):
                issues.append({"path": str(ledger_path), "batch_id": batch["id"], "field": "agent_id", "expected": "non-empty string", "actual": row.get("agent_id")})
            if not row.get("runtime_provenance"):
                issues.append({"path": str(ledger_path), "batch_id": batch["id"], "field": "runtime_provenance", "expected": "non-empty string", "actual": row.get("runtime_provenance")})
    if manifest.get("ui_implementation_audit", {}).get("visual_required"):
        for key in ("mockup_asset_worker", "visual_tooling_worker", "visual_comparison_worker"):
            row = ledger.get(key, {})
            if not isinstance(row, dict) or row.get("status") not in {"completed", "manual-fallback-completed"}:
                issues.append({"path": str(ledger_path), "field": f"{key}.status", "actual": row.get("status") if isinstance(row, dict) else None})
            else:
                if row.get("actual_reasoning_effort") != "low" and row.get("status") != "manual-fallback-completed":
                    issues.append({"path": str(ledger_path), "field": f"{key}.actual_reasoning_effort", "expected": "low", "actual": row.get("actual_reasoning_effort")})
                if not row.get("agent_id"):
                    issues.append({"path": str(ledger_path), "field": f"{key}.agent_id", "expected": "non-empty string", "actual": row.get("agent_id")})
                if not row.get("runtime_provenance"):
                    issues.append({"path": str(ledger_path), "field": f"{key}.runtime_provenance", "expected": "non-empty string", "actual": row.get("runtime_provenance")})
    return issues


def verify_current_hashes(manifest: dict) -> list[dict]:
    repo_root = Path(manifest["repo_root"])
    issues: list[dict] = []
    expected_hashes = {}
    expected_hashes.update(manifest["_source_hashes"])
    expected_hashes.update(manifest["_asset_hashes"])
    expected_hashes.update(manifest["_requirement_hashes"])
    for rel_path, expected in expected_hashes.items():
        path = repo_root / rel_path
        if not path.is_file():
            issues.append({"path": str(path), "reason": "manifest input file is missing"})
            continue
        actual = common.sha256_file(path)
        if actual != expected:
            issues.append({"path": rel_path, "expected": expected, "actual": actual, "reason": "current input hash differs from manifest"})
    return issues


def verify(manifest_path: Path, reports: list[Path], *, skip_current_hash_check: bool = False) -> dict:
    manifest = load_manifest(manifest_path)
    issues: dict[str, list] = {
        "completion_marker_mismatches": verify_marker(manifest_path, manifest),
        "excluded_file_issues": [],
        "effort_ledger_issues": verify_effort_ledger(manifest_path, manifest),
        "missing_reports": [],
        "report_issues": [],
        "current_hash_mismatches": [],
    }
    _, excluded_issues = verify_excluded_files(manifest_path, manifest)
    issues["excluded_file_issues"] = excluded_issues
    if not skip_current_hash_check:
        issues["current_hash_mismatches"] = verify_current_hashes(manifest)

    reports_by_name = {path.name: path for path in reports}
    for batch in manifest["batches"]:
        expected_name = f"{batch['id']}.md"
        report = reports_by_name.get(expected_name)
        if not report:
            issues["missing_reports"].append({"report": expected_name})
            continue
        issues["report_issues"].extend(verify_batch_report(report, manifest, batch["id"]))

    all_source_files = set(manifest["_source_hashes"])
    if manifest.get("ui_implementation_audit", {}).get("visual_required"):
        expected_aux = [
            ("mockup_asset_audit.md", MOCKUP_SECTIONS, "mockup_asset_audit"),
            ("visual_tooling_audit.md", TOOLING_SECTIONS, "visual_tooling_audit"),
            ("visual_comparison_audit.md", VISUAL_SECTIONS, "visual_comparison_audit"),
        ]
        for filename, sections, worker in expected_aux:
            report = reports_by_name.get(filename)
            if not report:
                issues["missing_reports"].append({"report": filename})
            else:
                issues["report_issues"].extend(verify_aux_report(report, manifest, sections, worker, all_source_files))

    ok = not any(issues.values())
    return {"ok": ok, "manifest": str(manifest_path), "run_id": manifest["run_id"], "issues": issues}


def print_human(result: dict) -> None:
    print(f"ok: {str(result['ok']).lower()}")
    print(f"run_id: {result['run_id']}")
    for key, values in result["issues"].items():
        if values:
            print(f"{key}:")
            for value in values:
                print(f"- {json.dumps(value, sort_keys=True)}")


def main() -> int:
    args = parse_args()
    try:
        reports = common.iter_report_files(args.reports)
        result = verify(Path(args.manifest), reports, skip_current_hash_check=args.skip_current_hash_check)
    except Exception as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, indent=2))
        else:
            print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print_human(result)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
