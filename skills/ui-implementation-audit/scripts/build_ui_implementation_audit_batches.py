#!/usr/bin/env python3
"""Build deterministic UI implementation audit batches."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
import tempfile
import uuid
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REPO_ROOT = Path(__file__).resolve().parents[3]
VENDOR_ROOT = SCRIPT_DIR / "_vendor"
DEV_SKILL_DIR = (REPO_ROOT / "skills" / "ui-implementation-audit").resolve()
running_in_dev_repo = DEV_SKILL_DIR == SKILL_DIR.resolve() and (REPO_ROOT / "full_repo_harness" / "queue.py").is_file()

path_roots = [REPO_ROOT, VENDOR_ROOT] if running_in_dev_repo else [VENDOR_ROOT]
for root in reversed([item for item in path_roots if item.is_dir()]):
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)

import full_repo_harness.queue as queue


ARTIFACT_OWNER = "ui-implementation-audit"
ARTIFACT_MARKER = ".ui-implementation-audit-artifacts.json"
VISUAL_ASSET_EXTENSIONS = set(queue.UI_ASSET_EXTENSIONS) | {".pdf", ".svg"}
MOCKUP_TOKENS = {
    "comp",
    "design",
    "figma",
    "flow",
    "journey",
    "mockup",
    "prototype",
    "screen",
    "screenshot",
    "spec",
    "ui",
    "ux",
    "wire",
    "wireframe",
}
MOCKUP_DIRS = {
    "design",
    "designs",
    "figma",
    "flow",
    "flows",
    "mockup",
    "mockups",
    "prototype",
    "prototypes",
    "screen",
    "screens",
    "screenshot",
    "screenshots",
    "spec",
    "specs",
    "ux",
    "wireframe",
    "wireframes",
}
REQUIREMENT_TOKENS = {
    "acceptance",
    "design",
    "flow",
    "journey",
    "mockup",
    "persona",
    "prd",
    "product",
    "requirements",
    "route",
    "scenario",
    "screen",
    "spec",
    "story",
    "ui",
    "ux",
    "workflow",
}
REQUIREMENT_EXTENSIONS = {".md", ".mdx", ".markdown", ".txt", ".json", ".jsonc", ".yaml", ".yml"}
REQUIREMENT_TEXT_RE = re.compile(
    r"\b(user journey|workflow|persona|acceptance criteria|screen sequence|primary action|responsive|mockup|wireframe|figma|visual design|ui requirement|ux requirement)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class VisualAsset:
    rel_path: str
    role: str
    size_bytes: int
    sha256: str
    evidence: str


@dataclass(frozen=True)
class RequirementSource:
    rel_path: str
    kind: str
    size_bytes: int
    sha256: str
    evidence: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create UI implementation audit manifest and worker prompts.")
    parser.add_argument("--repo", default=".", help="Repository root to audit. Defaults to cwd.")
    parser.add_argument("--out", default=None, help="Output directory. Defaults outside the audited repo.")
    parser.add_argument("--batch-size", type=queue.positive_int, default=6, help="Maximum UI source files per batch.")
    parser.add_argument(
        "--max-batch-bytes",
        type=queue.positive_int,
        default=queue.DEFAULT_MAX_BATCH_BYTES,
        help="Maximum total file bytes per batch. Larger text files are split into ranges.",
    )
    parser.add_argument("--include-config", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--include-env", action="store_true")
    parser.add_argument("--include-generated", action="store_true")
    parser.add_argument("--include-vendor", action="store_true")
    parser.add_argument("--include-assets", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--run-id", type=queue.run_id_token, default=None)
    parser.add_argument("--exclude-glob", action="append", default=[])
    parser.add_argument("--include-file", action="append", default=[])
    parser.add_argument("--include-glob", action="append", default=[])
    parser.add_argument("--mockup", action="append", default=[], help="Repo-relative mockup/design asset to force into visual evidence.")
    parser.add_argument("--journey-file", action="append", default=[], help="Repo-relative journey/requirements file to force into evidence.")
    return parser.parse_args()


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def table_cell(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def is_visual_asset_candidate(rel_path: str) -> bool:
    suffix = Path(rel_path).suffix.lower()
    if suffix not in VISUAL_ASSET_EXTENSIONS:
        return False
    parts = {part.lower() for part in Path(rel_path).parts[:-1]}
    words = queue.filename_words(Path(rel_path).name)
    return bool(
        queue.is_ui_asset_path(rel_path)
        or parts & MOCKUP_DIRS
        or words & MOCKUP_TOKENS
        or parts & queue.UI_ASSET_DIRS
        or words & queue.UI_ASSET_NAME_TOKENS
    )


def visual_asset_role(rel_path: str, forced_mockups: set[str]) -> str | None:
    if rel_path in forced_mockups:
        return "mockup"
    if not is_visual_asset_candidate(rel_path):
        return None
    parts = {part.lower() for part in Path(rel_path).parts[:-1]}
    words = queue.filename_words(Path(rel_path).name)
    if parts & MOCKUP_DIRS or words & MOCKUP_TOKENS:
        return "mockup"
    return "ui-asset"


def collect_candidate_paths(
    repo: Path,
    include_generated: bool,
    include_vendor: bool,
    include_assets: bool,
    output_rel_dirs: list[str],
) -> set[str]:
    git_paths = queue.run_git_files(repo)
    if git_paths is None:
        paths = set(queue.walk_files(repo, include_generated, include_vendor))
    else:
        paths = set(git_paths)
        if include_assets:
            paths.update(queue.run_git_ignored_files(repo, include_generated, include_vendor, output_rel_dirs))
    return paths


def discover_visual_assets(
    repo: Path,
    include_generated: bool,
    include_vendor: bool,
    include_assets: bool,
    exclude_globs: list[str],
    output_rel_dirs: list[str],
    forced_mockups: set[str],
    collected_entries: list[queue.FileEntry],
) -> list[VisualAsset]:
    candidates = collect_candidate_paths(repo, include_generated, include_vendor, include_assets, output_rel_dirs)
    candidates.update(forced_mockups)
    candidates.update(item.rel_path for item in collected_entries if is_visual_asset_candidate(item.rel_path))
    assets: dict[str, VisualAsset] = {}
    for rel_path in sorted(candidates):
        path = repo / rel_path
        forced = rel_path in forced_mockups
        reason = (
            queue.excluded_by_output_dir(rel_path, output_rel_dirs)
            or queue.excluded_by_dir(rel_path, include_generated, include_vendor)
            or queue.matches_any_glob(rel_path, exclude_globs)
        )
        if reason and not forced:
            continue
        if not path.exists() or not path.is_file() or path.is_symlink():
            continue
        role = visual_asset_role(rel_path, forced_mockups)
        if role is None:
            continue
        try:
            size = path.stat().st_size
            digest = queue.sha256_file(path)
        except OSError:
            continue
        evidence = "forced by --mockup" if forced else ("mockup/design path or filename" if role == "mockup" else "UI asset path or filename")
        assets[rel_path] = VisualAsset(rel_path=rel_path, role=role, size_bytes=size, sha256=digest, evidence=evidence)
    return list(assets.values())


def requirement_evidence_for_path(rel_path: str, path: Path, forced: bool) -> str | None:
    if forced:
        return "forced by --journey-file"
    suffix = path.suffix.lower()
    if suffix not in REQUIREMENT_EXTENSIONS:
        return None
    parts = {part.lower() for part in path.parts[:-1]}
    words = queue.filename_words(path.name)
    if words & REQUIREMENT_TOKENS or parts & {"docs", "documentation", "product", "requirements", "spec", "specs", "ux", "design"}:
        return "requirement-like path or filename"
    try:
        text = queue.read_initial_bytes(path, limit=400_000).decode("utf-8", errors="ignore")
    except OSError:
        return None
    if REQUIREMENT_TEXT_RE.search(text):
        return "journey or UI requirement terms in file"
    return None


def discover_requirement_sources(
    repo: Path,
    collected_entries: list[queue.FileEntry],
    forced_journey_files: set[str],
    include_generated: bool,
    include_vendor: bool,
    output_rel_dirs: list[str],
) -> list[RequirementSource]:
    candidates = {item.rel_path for item in collected_entries}
    candidates.update(forced_journey_files)
    candidates.update(
        rel_path
        for rel_path in collect_candidate_paths(repo, include_generated, include_vendor, True, output_rel_dirs)
        if Path(rel_path).suffix.lower() in REQUIREMENT_EXTENSIONS
    )
    records: dict[str, RequirementSource] = {}
    for rel_path in sorted(candidates):
        path = repo / rel_path
        if queue.excluded_by_output_dir(rel_path, output_rel_dirs) and rel_path not in forced_journey_files:
            continue
        if not path.exists() or not path.is_file() or path.is_symlink():
            continue
        evidence = requirement_evidence_for_path(rel_path, path, rel_path in forced_journey_files)
        if evidence is None:
            continue
        try:
            size = path.stat().st_size
            digest = queue.sha256_file(path)
        except OSError:
            continue
        kind = "forced-requirement" if rel_path in forced_journey_files else "requirement-candidate"
        records[rel_path] = RequirementSource(rel_path=rel_path, kind=kind, size_bytes=size, sha256=digest, evidence=evidence)
    return list(records.values())


def unit_lines(entries: list[queue.AuditUnit]) -> str:
    lines: list[str] = []
    for entry in entries:
        if entry.start_line is not None:
            location = f"lines {entry.start_line}-{entry.end_line}"
        elif entry.start_byte is not None:
            location = f"bytes {entry.start_byte}-{entry.end_byte}"
        else:
            location = f"{entry.size_bytes} bytes"
        lines.append(
            f"- Unit `{entry.unit_id}`: `{entry.rel_path}` {location} "
            f"({entry.kind}, sha256=`{entry.sha256}`)"
        )
    return "\n".join(lines)


def compact_asset_list(assets: list[VisualAsset], *, role: str | None = None, limit: int = 80) -> str:
    chosen = [item for item in assets if role is None or item.role == role]
    if not chosen:
        return "- None found."
    rows = [
        f"- `{item.rel_path}` ({item.role}, {item.size_bytes} bytes, sha256=`{item.sha256}`, evidence={item.evidence})"
        for item in chosen[:limit]
    ]
    if len(chosen) > limit:
        rows.append(f"- ... {len(chosen) - limit} more listed in manifest.json")
    return "\n".join(rows)


def compact_requirement_list(requirements: list[RequirementSource], limit: int = 80) -> str:
    if not requirements:
        return "- None found."
    rows = [
        f"- `{item.rel_path}` ({item.kind}, sha256=`{item.sha256}`, evidence={item.evidence})"
        for item in requirements[:limit]
    ]
    if len(requirements) > limit:
        rows.append(f"- ... {len(requirements) - limit} more listed in manifest.json")
    return "\n".join(rows)


def render_batch_prompt(
    repo: Path,
    run_id: str,
    batch_id: int,
    total_batches: int,
    entries: list[queue.AuditUnit],
    assets: list[VisualAsset],
    requirements: list[RequirementSource],
) -> str:
    return f"""# UI Implementation Audit Batch {batch_id:03d}/{total_batches:03d}

Run ID: `{run_id}`
Repo root: `{repo}`
Batch ID: `batch_{batch_id:03d}`

You are a low-effort worker auditing interface source implementation. Do not edit files. Inspect every owned unit below and compare source-defined UI behavior, visible text, layout, state handling, responsive intent, implementation paths, and test evidence against the mockup/assets, required UI elements, features, and journey requirements listed here and in `manifest.json`.

## Files You Own

{unit_lines(entries)}

For ranged units, inspect the assigned range manually plus nearby imports/types/callers/styles only as needed. In `File Coverage` and `UI Source Inventory`, use the exact unit id.

## Mockup And Asset Evidence

{compact_asset_list(assets)}

## Journey Requirement Evidence

{compact_requirement_list(requirements)}

## Review Rules

- Define the journey decision model before judging visual/source alignment: primary user goal, primary decision, required facts, warning/flag conditions, frequent actions, secondary/rare actions, and unconfirmed assumptions.
- Inventory every required visible label, control, field, menu, route link, toast, banner, empty/loading/error state, layout container, and visual/test evidence.
- Trace handlers, state, navigation, API/persistence, permissions, validation, and missing state branches when the UI promises behavior.
- Compare implementation to mockup/journey evidence: hierarchy, density, spacing, imagery, typography intent, copy, responsiveness, required decision information, feature behavior, and test evidence.
- Flag visible overload across desktop, native, and narrow/mobile surfaces: low-journey-relevance settings, filters, rare/admin controls, debug/raw detail, explanatory copy, or secondary metadata dominating the space needed for decision-driving content.
- Do not mark source alignment clear just because it resembles a mockup; rendered viewports must help the user make the current journey decision.
- Flag missing UI elements, unwired handlers, missing data/persistence paths, missing states, missing accessibility paths, and missing safe visual states or fixture paths when source implies heavy or production-only operations.

## Required Report

Return exactly these top-level headings in order:

## Run ID
{run_id}

## Batch ID
batch_{batch_id:03d}

## Batch Summary
Briefly summarize the UI surfaces these files define.

## File Coverage
| Unit | Status | SHA-256 | Purpose |
| --- | --- | --- | --- |
| exact unit id | CHECKED | exact sha256 | one-line UI purpose |

## UI Source Inventory
| Unit | File | Surface | Visible Element | Source Evidence | Expected Behavior | Actual Implementation | Responsive/State Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| exact unit id | repo-relative file | screen/component/style/message catalog | label/control/state/layout | source line/copy/style evidence | mockup/journey/feature/test expectation or inferred standard | implemented/missing path | desktop/mobile/state notes |

## Journey Decision Model
| Surface | Primary user goal | Primary decision | Required facts | Warning/flag conditions | Frequent actions | Secondary/rare actions | Unconfirmed assumptions |
| --- | --- | --- | --- | --- | --- | --- | --- |
| screen/component | user goal | decision the user must make | facts needed for the decision | warning or flag conditions | common action(s) | occasional/rare/admin/config actions | assumptions needing confirmation |

## Rendered Journey Usability
| Viewport | Decision supported | Visible decision-driving content | Visible secondary/detail content | Detail access pattern | Readability/contrast evidence | Layout quality result | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| desktop/native/mobile | supported decision or blocker | facts/actions/warnings visible | details/settings/debug/config visible | inline/expander/menu/detail route/blocked | source/CSS/DOM/screenshot/measurement evidence | PASS/GAP/BLOCKED/NOT_APPLICABLE | source/CSS/DOM/screenshot/measurement evidence |

## Mockup And Journey Alignment
Explain how the owned UI source aligns or conflicts with the listed mockups/assets, required UI elements, features, tests, and journey requirements. Mention missing target evidence if no relevant mockup or journey exists.

## Implementation Gap Findings
Use `No findings.` or one block per gap:

- Priority: P0/P1/P2/P3
- Files: repo-relative files owned by this batch
- Mockup/requirement evidence: asset, journey doc, route, or explicit absence
- Interface evidence: source file, visible text, handler, style, or state
- Expected behavior/standard: expected visual, journey, feature, UI element, implementation, or test behavior
- Gap: concrete mismatch, missing element, unwired path, or missing test evidence
- Suggested implementation direction: specific fix direction

## No Gap Notes
List units or UI behaviors that look aligned and why.

## Open Questions
List ambiguity for the lead, or `None.`
"""


def render_mockup_asset_prompt(repo: Path, run_id: str, assets: list[VisualAsset], requirements: list[RequirementSource]) -> str:
    return f"""# UI Implementation Audit: Mockup And Asset Worker

Run ID: `{run_id}`
Repo root: `{repo}`
Worker: `mockup_asset_audit`

Do not edit files. Inventory the design target from mockups/assets and journey requirement sources, including required screens, features, UI elements, states, implementation expectations, and test expectations. Use image-viewing tools when available for raster assets; otherwise describe the blocker and rely on filenames/nearby docs only as fallback.

## Mockup And Asset Inputs

{compact_asset_list(assets)}

## Journey Requirement Inputs

{compact_requirement_list(requirements)}

Return exactly:

## Run ID
{run_id}

## Worker
mockup_asset_audit

## Mockup/Asset Inputs
List each mockup/design/asset input used, including whether it was visually inspected.

## Journey Requirement Inputs
List requirement docs/source used and the journeys/screens they imply.

## Expected Screens And Visual Requirements
List expected screens, hierarchy, density, layout, typography, color, imagery, states, UI elements, feature behavior, implementation expectations, test expectations, and desktop/mobile requirements. Include the journey decision model for each important surface: primary goal, primary decision, required facts, warning/flag conditions, frequent actions, secondary/rare actions, and unconfirmed assumptions.

## Findings
Use `No findings.` or finding blocks with Priority, Files, Mockup/requirement evidence, Interface evidence, Expected behavior/standard, Gap, Suggested implementation direction. Use `Files: not-applicable` only for missing target assets or requirements.

## Open Questions
List missing mockups, unclear journeys, missing UI element/feature/test expectations, or `None.`
"""


def render_visual_tooling_prompt(repo: Path, run_id: str, ui_entries: list[queue.FileEntry], requirements: list[RequirementSource]) -> str:
    files = "\n".join(f"- `{item.rel_path}` ({item.kind}, sha256=`{item.sha256}`)" for item in ui_entries) or "- None."
    return f"""# UI Implementation Audit: Visual Tooling Worker

Run ID: `{run_id}`
Repo root: `{repo}`
Worker: `visual_tooling_audit`

Do not edit files. Identify how to render the implemented UI safely for screenshot comparison and how required screens, UI elements, states, and visual tests can be exercised. Prefer Playwright, Cypress, Storybook, Vite/Next dev servers, browser MCP tools, native previews/simulators, test fixtures, mock data modes, or existing screenshot tests.

## Interface Source Files

{files}

## Journey Requirement Inputs

{compact_requirement_list(requirements)}

Return exactly:

## Run ID
{run_id}

## Worker
visual_tooling_audit

## Tooling Inventory
List exact detected tools/configs/scripts/routes/stories/specs or the absence of them.

## Safe Run Path
List exact commands, environment/test-mode requirements, and routes/screens to open; or explain why no safe render path exists.

## Desktop/Mobile Screenshot Plan
List desktop, native, and narrow mobile viewport checks to run, including target routes/screens, required UI elements/states, expected artifacts, rendered journey usefulness, readability/contrast evidence, and how to identify visible decision-driving content versus secondary/detail/debug/configuration content.

## Findings
Use `No findings.` or finding blocks with Priority, Files, Mockup/requirement evidence, Interface evidence, Expected behavior/standard, Gap, Suggested implementation direction.

## Open Questions
List blockers or `None.`
"""


def render_visual_comparison_prompt(repo: Path, run_id: str, assets: list[VisualAsset], requirements: list[RequirementSource]) -> str:
    return f"""# UI Implementation Audit: Visual Comparison Worker

Run ID: `{run_id}`
Repo root: `{repo}`
Worker: `visual_comparison_audit`

Do not edit files. Use available screenshot-capable tooling to compare the implemented UI against mockups/assets, required UI elements, feature behavior, tests, and user journey requirements. Prefer safe test/fixture/preview mode. If the UI cannot be rendered, create desktop and mobile `BLOCKED` rows with concrete tool/route evidence and report the missing visual harness as a finding.

Before visual comparison, define the journey decision model and required UI element set. A visual check is not clear merely because it matches a mockup, has correct data, or avoids overflow. Each rendered viewport must support the primary journey decision unless the surface is itself primarily a data-entry form. If settings, filters, menus, target/configuration blocks, raw/debug detail, explanatory copy, or other low-relevance content dominates the visible surface while the primary decision is unclear or buried, report a journey-usability finding.

## Mockup And Asset Evidence

{compact_asset_list(assets)}

## Journey Requirement Evidence

{compact_requirement_list(requirements)}

Return exactly:

## Run ID
{run_id}

## Worker
visual_comparison_audit

## Journey Decision Model
| Surface | Primary user goal | Primary decision | Required facts | Warning/flag conditions | Frequent actions | Secondary/rare actions | Unconfirmed assumptions |
| --- | --- | --- | --- | --- | --- | --- | --- |
| route/screen | user goal | decision the user must make | facts needed for the decision | warning or flag conditions | common action(s) | occasional/rare/admin/config actions | assumptions needing confirmation |

## Rendered Journey Usability
| Viewport | Decision supported | Visible decision-driving content | Visible secondary/detail content | Detail access pattern | Readability/contrast evidence | Layout quality result | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| desktop/native/mobile | supported decision or blocker | facts/actions/warnings visible | details/settings/debug/config visible | inline/expander/menu/detail route/blocked | screenshot/tool/DOM/viewport evidence | PASS/GAP/BLOCKED/NOT_APPLICABLE | screenshot/tool/DOM/viewport evidence |

## Visual Comparison Checks
| Journey | Viewport | Route/Screen | Mockup/Requirement | Implementation Screenshot/Tool Evidence | Differences | Result |
| --- | --- | --- | --- | --- | --- | --- |
| journey or screen | desktop/mobile | route/screen/story | asset or requirement | screenshot/trace/tool command or blocker evidence | visual/responsive differences | MATCHED/GAP/BLOCKED/NOT_APPLICABLE |

## Findings
Use `No findings.` or finding blocks with Priority, Files, Mockup/requirement evidence, Interface evidence, Expected behavior/standard, Gap, Suggested implementation direction. If screenshot production is blocked, include a finding that names the missing safe visual path. If a required element/state is absent, content is overloaded/crowded/unreadable, or low-relevance detail dominates while the primary decision is unclear or buried, include a finding.

## Open Questions
List visual blockers, missing mockups, unclear routes, or `None.`
"""


def write_effort_ledger(out_dir: Path, manifest: dict) -> None:
    ui_required = bool(manifest.get("ui_implementation_audit", {}).get("visual_required"))
    ledger = {
        "run_id": manifest["run_id"],
        "repo_root": manifest["repo_root"],
        "audit_kind": "ui-implementation",
        "provenance_scope": "lead-recorded runtime ledger",
        "effort_verification_scope": "ledger-recorded",
        "subagent_capability_check": {
            "status": "pending",
            "spawn_tool": None,
            "can_set_reasoning_effort": None,
            "notes": "",
        },
        "lead_effort": {
            "required_reasoning_effort": "high-or-higher",
            "actual_reasoning_effort": None,
            "status": "pending",
            "agent_id": None,
            "runtime_provenance": None,
            "evidence": "",
        },
        "fallback": {"status": "not-started", "reason": ""},
        "mockup_asset_worker": {
            "status": "pending" if ui_required else "not-applicable",
            "prompt": "mockup_asset_audit.md" if ui_required else None,
            "required_reasoning_effort": "low" if ui_required else None,
            "report": "reports/mockup_asset_audit.md" if ui_required else None,
            "agent_id": None,
            "actual_reasoning_effort": None,
            "runtime_provenance": None,
        },
        "visual_tooling_worker": {
            "status": "pending" if ui_required else "not-applicable",
            "prompt": "visual_tooling_audit.md" if ui_required else None,
            "required_reasoning_effort": "low" if ui_required else None,
            "report": "reports/visual_tooling_audit.md" if ui_required else None,
            "agent_id": None,
            "actual_reasoning_effort": None,
            "runtime_provenance": None,
        },
        "visual_comparison_worker": {
            "status": "pending" if ui_required else "not-applicable",
            "prompt": "visual_comparison_audit.md" if ui_required else None,
            "required_reasoning_effort": "low" if ui_required else None,
            "report": "reports/visual_comparison_audit.md" if ui_required else None,
            "agent_id": None,
            "actual_reasoning_effort": None,
            "runtime_provenance": None,
        },
        "batch_workers": [
            {
                "batch_id": batch["id"],
                "status": "pending",
                "prompt": batch["prompt"],
                "required_reasoning_effort": "low",
                "report": f"reports/{batch['id']}.md",
                "agent_id": None,
                "actual_reasoning_effort": None,
                "runtime_provenance": None,
                "fallback": False,
            }
            for batch in manifest["batches"]
        ],
        "pruned_directory_review": {
            "status": "pending" if manifest.get("pruned_directory_review_hint_count") else "not-applicable",
            "hint_count": manifest.get("pruned_directory_review_hint_count", 0),
            "decisions": [],
        },
    }
    queue.write_json(out_dir / "effort_ledger.json", ledger)


def write_completion_marker(out_dir: Path, manifest: dict) -> None:
    marker = {
        "run_id": manifest["run_id"],
        "phase": "queue_generated",
        "audit_verified": False,
        "audit_kind": "ui-implementation",
        "manifest": "manifest.json",
        "audit_index": "audit_index.md",
        "effort_ledger": "effort_ledger.json",
        "excluded_files": "excluded_files.json",
        "reports_dir": "reports",
        "ownership_marker": ARTIFACT_MARKER,
        "batch_count": manifest["batch_count"],
        "source_file_count": manifest["source_file_count"],
        "marker_semantics": "Queue artifacts were generated; worker reports and effort ledger still require verifier completion.",
    }
    queue.write_json(out_dir / "queue_complete.json", marker)


def render_index(repo: Path, out_dir: Path, manifest: dict) -> str:
    rows = "\n".join(
        f"| {table_cell(batch['id'])} | `{table_cell(batch['prompt'])}` | {batch['file_count']} | {batch['coverage_unit_count']} | {table_cell(batch['purpose'])} |"
        for batch in manifest["batches"]
    )
    if not rows:
        rows = "| None | None | 0 | 0 | No interface source files queued |"
    audit = manifest["ui_implementation_audit"]
    visual_prompts = (
        "- Mockup/assets prompt: `mockup_asset_audit.md` -> `reports/mockup_asset_audit.md`\n"
        "- Visual tooling prompt: `visual_tooling_audit.md` -> `reports/visual_tooling_audit.md`\n"
        "- Visual comparison prompt: `visual_comparison_audit.md` -> `reports/visual_comparison_audit.md`"
        if audit["visual_required"]
        else "- No visual worker prompts were generated because no interface source files were queued."
    )
    return f"""# UI Implementation Audit Index

Repo root: `{repo}`
Output directory: `{out_dir}`
Run ID: `{manifest['run_id']}`
Audit kind: `ui-implementation`

Interface source files queued: **{manifest['source_file_count']}**
Coverage units queued: **{manifest['coverage_unit_count']}**
Batches: **{manifest['batch_count']}**
Visual assets found: **{audit['visual_asset_count']}**
Mockup assets found: **{audit['mockup_asset_count']}**
Requirement sources found: **{audit['requirement_source_count']}**
Scope warnings: **{manifest['scope_warning_count']}**

## Dispatch

1. Fill `effort_ledger.json` as workers are assigned.
2. Dispatch one low-effort worker per batch prompt.
3. Save returned reports under `reports/batch_###.md`.
4. Dispatch visual workers when listed below.
5. Run verifier: `{manifest['verifier_command']}`
6. The lead must review visual evidence directly before final synthesis; source-only review is not a completed visual audit.

{visual_prompts}

## Batches

| Batch | Prompt | Files | Units | Purpose |
| --- | --- | ---: | ---: | --- |
{rows}
"""


def write_outputs(
    repo: Path,
    out_dir: Path,
    entries: list[queue.FileEntry],
    excluded: list[dict],
    units: list[queue.AuditUnit],
    batches: list[list[queue.AuditUnit]],
    run_id: str,
    visual_assets: list[VisualAsset],
    requirements: list[RequirementSource],
    non_interface_source_count: int,
) -> None:
    queue.ARTIFACT_OWNER = ARTIFACT_OWNER
    queue.ARTIFACT_MARKER = ARTIFACT_MARKER
    queue.validate_generated_artifact_tokens(entries, units)
    marker = queue.ensure_output_dir_safe(out_dir, repo)
    out_dir.mkdir(parents=True, exist_ok=True)
    if marker is None:
        queue.write_ownership_marker(out_dir, repo, [])
        marker = queue.read_ownership_marker(out_dir)
    queue.clean_generated_artifacts(out_dir, marker)
    reports_dir = out_dir / "reports"
    archived_reports_name = None
    archived_reports_dir = None
    if reports_dir.exists() and any(reports_dir.iterdir()):
        archive = out_dir / f"reports.stale.{utc_stamp()}"
        suffix = 1
        while archive.exists():
            suffix += 1
            archive = out_dir / f"reports.stale.{utc_stamp()}.{suffix}"
        reports_dir.rename(archive)
        archived_reports_name = archive.name
        archived_reports_dir = str(archive)
    reports_dir.mkdir(exist_ok=True)

    batch_records: list[dict] = []
    all_paths: list[str] = []
    all_units: list[str] = []
    for index, batch in enumerate(batches, start=1):
        prompt = f"batch_{index:03d}.md"
        (out_dir / prompt).write_text(
            render_batch_prompt(repo, run_id, index, len(batches), batch, visual_assets, requirements),
            encoding="utf-8",
        )
        paths = sorted({item.rel_path for item in batch})
        unit_ids = [item.unit_id for item in batch]
        all_paths.extend(paths)
        all_units.extend(unit_ids)
        batch_records.append(
            {
                "id": f"batch_{index:03d}",
                "prompt": prompt,
                "file_count": len(paths),
                "coverage_unit_count": len(batch),
                "interface_file_count": len(paths),
                "byte_count": sum(item.size_bytes for item in batch),
                "files": paths,
                "coverage_units": unit_ids,
                "purpose": queue.purpose_for(batch),
            }
        )

    source_paths = [item.rel_path for item in entries]
    unit_ids = [item.unit_id for item in units]
    missing_paths = sorted(set(source_paths) - set(all_paths))
    extra_paths = sorted(set(all_paths) - set(source_paths))
    missing_units = sorted(set(unit_ids) - set(all_units))
    duplicate_units = sorted(unit for unit, count in Counter(all_units).items() if count > 1)
    extra_units = sorted(set(all_units) - set(unit_ids))
    scope_warnings = [item for item in excluded if item.get("scope_warning")]
    pruned_hints = [item for item in excluded if item.get("entry_type") == "directory" and item.get("contains_source_like_samples")]
    visual_required = bool(entries)

    if visual_required:
        (out_dir / "mockup_asset_audit.md").write_text(render_mockup_asset_prompt(repo, run_id, visual_assets, requirements), encoding="utf-8")
        (out_dir / "visual_tooling_audit.md").write_text(render_visual_tooling_prompt(repo, run_id, entries, requirements), encoding="utf-8")
        (out_dir / "visual_comparison_audit.md").write_text(render_visual_comparison_prompt(repo, run_id, visual_assets, requirements), encoding="utf-8")

    verifier_args = [
        sys.executable,
        str(Path(__file__).resolve().with_name("verify_ui_implementation_audit_results.py")),
        "--manifest",
        str(out_dir / "manifest.json"),
        "--reports",
        str(reports_dir),
    ]
    generated_artifacts = [
        "audit_index.md",
        "effort_ledger.json",
        "excluded_files.json",
        "manifest.json",
        "queue_complete.json",
        *(["mockup_asset_audit.md", "visual_tooling_audit.md", "visual_comparison_audit.md"] if visual_required else []),
        *([archived_reports_name] if archived_reports_name else []),
        *[batch["prompt"] for batch in batch_records],
    ]
    manifest = {
        "repo_root": str(repo),
        "run_id": run_id,
        "audit_kind": "ui-implementation",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reports_dir": str(reports_dir),
        "archived_reports_dir": archived_reports_dir,
        "artifact_marker": str(out_dir / ARTIFACT_MARKER),
        "effort_ledger": str(out_dir / "effort_ledger.json"),
        "generated_artifacts": generated_artifacts,
        "verifier_command": " ".join(shlex.quote(arg) for arg in verifier_args),
        "verifier_args": verifier_args,
        "source_file_count": len(entries),
        "interface_file_count": len(entries),
        "non_interface_source_count": non_interface_source_count,
        "scope_warning_count": len(scope_warnings),
        "pruned_directory_review_hint_count": len(pruned_hints),
        "excluded_file_count": len(excluded),
        "excluded_files_sha256": queue.canonical_json_sha256(excluded),
        "batch_count": len(batch_records),
        "source_files": [asdict(item) for item in entries],
        "coverage_unit_count": len(units),
        "coverage_units": [asdict(item) for item in units],
        "batches": batch_records,
        "ui_implementation_audit": {
            "visual_required": visual_required,
            "source_selection": "Only interface-defining non-asset source files are queued in batches.",
            "visual_asset_count": len(visual_assets),
            "mockup_asset_count": sum(1 for item in visual_assets if item.role == "mockup"),
            "requirement_source_count": len(requirements),
            "visual_assets": [asdict(item) for item in visual_assets],
            "requirement_sources": [asdict(item) for item in requirements],
            "mockup_asset_prompt": "mockup_asset_audit.md" if visual_required else None,
            "mockup_asset_report": "reports/mockup_asset_audit.md" if visual_required else None,
            "visual_tooling_prompt": "visual_tooling_audit.md" if visual_required else None,
            "visual_tooling_report": "reports/visual_tooling_audit.md" if visual_required else None,
            "visual_comparison_prompt": "visual_comparison_audit.md" if visual_required else None,
            "visual_comparison_report": "reports/visual_comparison_audit.md" if visual_required else None,
        },
        "coverage_invariants": {
            "unique_batched_file_count": len(set(all_paths)),
            "unique_batched_unit_count": len(set(all_units)),
            "missing_from_batches": missing_paths,
            "duplicates_in_batches": queue.duplicate_whole_file_paths_for_batches(batches),
            "extra_in_batches": extra_paths,
            "missing_units_from_batches": missing_units,
            "duplicate_units_in_batches": duplicate_units,
            "extra_units_in_batches": extra_units,
            "all_coverage_units_queued_exactly_once": not missing_units and not duplicate_units and not extra_units,
            "all_source_files_queued_exactly_once": not missing_paths and not extra_paths and not missing_units and not duplicate_units and not extra_units,
        },
        "scope_warnings": scope_warnings,
        "pruned_directory_review_hints": pruned_hints,
    }
    queue.write_json(out_dir / "manifest.json", manifest)
    queue.write_json(out_dir / "excluded_files.json", excluded)
    (out_dir / "audit_index.md").write_text(render_index(repo, out_dir, manifest), encoding="utf-8")
    write_effort_ledger(out_dir, manifest)
    queue.write_ownership_marker(out_dir, repo, generated_artifacts)
    write_completion_marker(out_dir, manifest)


def main() -> int:
    queue.ARTIFACT_OWNER = ARTIFACT_OWNER
    queue.ARTIFACT_MARKER = ARTIFACT_MARKER
    args = parse_args()
    repo = Path(args.repo).expanduser().resolve()
    if not repo.exists() or not repo.is_dir():
        print(f"Repo path is not a directory: {repo}", file=sys.stderr)
        return 2
    run_id = args.run_id or uuid.uuid4().hex
    out_dir = (
        Path(args.out).expanduser().resolve()
        if args.out
        else Path(tempfile.gettempdir()) / "ui-implementation-audit" / (repo.name or "repo") / f"{utc_stamp()}-{run_id[:8]}"
    )
    output_rel_dirs: list[str] = []
    output_rel_dir = queue.relative_dir_if_child(repo, out_dir)
    if output_rel_dir == "":
        print("--out cannot be the repository root; choose a dedicated audit output directory.", file=sys.stderr)
        return 2
    if output_rel_dir is not None:
        output_rel_dirs.append(output_rel_dir)
    for owned in queue.discover_owned_output_dirs(repo, args.include_generated, args.include_vendor):
        if owned not in output_rel_dirs:
            output_rel_dirs.append(owned)
    try:
        include_files = {queue.validate_repo_relative_include(repo, raw) for raw in args.include_file}
        forced_mockups = {queue.validate_repo_relative_include(repo, raw) for raw in args.mockup}
        forced_journey_files = {queue.validate_repo_relative_include(repo, raw) for raw in args.journey_file}
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    entries, excluded = queue.collect_files(
        repo,
        args.include_config,
        args.include_env,
        args.include_generated,
        args.include_vendor,
        args.include_assets,
        args.exclude_glob,
        include_files,
        args.include_glob,
        output_rel_dirs,
    )
    visual_assets = discover_visual_assets(
        repo,
        args.include_generated,
        args.include_vendor,
        args.include_assets,
        args.exclude_glob,
        output_rel_dirs,
        forced_mockups,
        entries,
    )
    requirements = discover_requirement_sources(
        repo,
        entries,
        forced_journey_files,
        args.include_generated,
        args.include_vendor,
        output_rel_dirs,
    )
    interface_entries = [
        item
        for item in entries
        if item.interface_relevant and item.kind != "source/ui-asset" and not is_visual_asset_candidate(item.rel_path)
    ]
    non_interface_source_count = len(entries) - len(interface_entries)
    units = queue.audit_units_for(repo, interface_entries, args.max_batch_bytes)
    batches = queue.batch_files(units, args.batch_size, args.max_batch_bytes)
    try:
        write_outputs(repo, out_dir, interface_entries, excluded, units, batches, run_id, visual_assets, requirements, non_interface_source_count)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"Wrote {len(batches)} UI implementation batches covering {len(interface_entries)} interface source files to {out_dir}")
    print(f"Found {len(visual_assets)} visual assets and {len(requirements)} requirement sources")
    print(f"Excluded {len(excluded)} files; see {out_dir / 'excluded_files.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
