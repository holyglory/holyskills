---
name: ui-implementation-audit
description: Audit a repository's implemented user interface against mockup images, visual assets, and user journey requirements. Use when Codex needs to compare rendered desktop/mobile UI screenshots and UI source code against design assets, ImageGen mockups, Figma exports, screenshots, product journeys, or UX requirements, then produce a prioritized plan for closing visual, responsive, interaction, and journey gaps. Only interface-defining source files are queued in deterministic source batches.
---

# UI Implementation Audit

## Overview

Run a read-only, manifest-verified audit of whether the implemented UI matches
the intended UI shown in mockups/assets and described by user journey
requirements. The lead agent owns the final visual judgment. Low-effort workers
inspect deterministic batches of interface source files, while separate workers
inventory mockups/assets, identify visual tooling, and compare desktop/mobile
screenshots against the design target.

This skill exists because UI implementations often drift from generated mockups:
spacing, density, hierarchy, responsive fit, visible states, and asset use must
be checked with actual screenshots, not only source reading.

## Required Execution Model

- Use high reasoning effort or higher for the lead audit. If the current lead
  run cannot be confirmed as high effort or higher, tell the user before
  starting.
- Use low-effort subagents for source batches when the runtime supports spawned
  workers. Treat the user's request to run this audit as authorization for the
  needed low-effort batch workers.
- Queue only interface-defining source files in `batch_###.md` prompts. Do not
  batch unrelated backend, scripts, build files, or non-UI source.
- Always run the visual work when interface source files are queued:
  `mockup_asset_audit.md`, `visual_tooling_audit.md`, and
  `visual_comparison_audit.md`.
- Before comparing screenshots to mockups, define a journey priority contract:
  primary user goal, primary decision-making information, frequent actions,
  occasional controls, rare/admin/configuration controls, and expected desktop
  and mobile information order.
- The visual comparison worker must try available rendered-surface tooling:
  Playwright, Cypress, Storybook, browser MCP tools, app/browser preview,
  native simulator/preview tools, or screenshot-capable test commands. It must
  check desktop and narrow mobile viewports when a web UI exists.
- The visual comparison worker must answer what the user can decide from the
  first mobile viewport. Except on pages whose primary purpose is data entry,
  primary decision-making content must be visible before low-frequency settings,
  filters, menus, or configuration panels dominate the screen.
- Prefer test, fixture, preview, mock-data, dry-run, or Storybook paths over
  production paths. If no safe visual path exists, report the blocker with
  evidence and include an implementation step to add one.
- Keep the audited repo read-only unless the user separately asks to implement
  the resulting plan. Generated audit artifacts are allowed and should live
  outside the audited repo by default.
- Do not claim completion until the manifest, source-batch reports, visual
  reports, effort ledger, and verifier agree.

## Workflow

1. **Set scope**
   - Use the current working directory as the repo root unless the user names
     another path.
   - Identify interface source from pages, screens, components, templates,
     styles, layout files, native UI files, message catalogs, UI config, and
     visible-copy files.
   - Treat mockup/design assets, screenshots, exported Figma images, ImageGen
     outputs, brand assets, journey docs, route maps, product specs, Storybook
     stories, and visual tests as evidence, not source-batch ownership.

2. **Generate the audit queue**
   - Resolve the audited repo to an absolute path.
   - Resolve `UI_IMPLEMENTATION_AUDIT_SKILL_DIR` to the directory containing
     this `SKILL.md`.
   - Preflight the skill scripts and run:

     ```bash
     python3 "$UI_IMPLEMENTATION_AUDIT_SKILL_DIR/scripts/self_test.py"
     ```

     unless the user explicitly forbids validation commands.
   - Run:

     ```bash
     REPO_ROOT="${REPO_ROOT:-$PWD}"
     python3 "$UI_IMPLEMENTATION_AUDIT_SKILL_DIR/scripts/build_ui_implementation_audit_batches.py" --repo "$REPO_ROOT"
     ```

   - Use `--out <dir>` when the user wants a specific artifact location.
   - Use `--mockup <repo-relative-path>` to force a mockup/design asset into
     the visual evidence set, and `--journey-file <repo-relative-path>` to force
     a requirements/journey source into the evidence set.
   - Use `--include-file` or `--include-glob` only to force a source/manual file
     that truly defines the interface.
   - Inspect `audit_index.md`, `manifest.json`, and `excluded_files.json`.
     Resolve `scope_warning: true` rows before claiming full coverage.

3. **Lead visual orientation**
   - Read the mockup/design assets listed in `manifest.json`.
   - Read journey requirement sources before deciding visual priorities.
   - Write the journey priority contract before inspecting screenshots:
     primary goal, primary information, frequent actions, occasional controls,
     rare/admin/configuration controls, and expected desktop/mobile order.
   - Build a screen inventory: route/screen, target user, journey step, primary
     decision, required information, primary actions, secondary/rare details,
     and expected desktop/mobile layout.
   - For every important mobile screen, define what must be useful in the first
     viewport and what may be pushed behind scroll, tabs, menus, or expanders.
   - Identify the safest way to render each high-priority screen.

4. **Dispatch workers**
   - Dispatch one low-effort worker per `batch_###.md`; tell workers not to edit
     files and to cover every owned unit.
   - Dispatch `mockup_asset_audit.md` to extract expected screens, visual
     hierarchy, typography, spacing, density, colors, assets, and state
     requirements from mockups and journey docs.
   - Dispatch `visual_tooling_audit.md` to find exact commands, servers,
     routes, fixtures, Storybook stories, Playwright/Cypress specs, native
     previews, and blockers.
   - Dispatch `visual_comparison_audit.md` to render or screenshot desktop and
     narrow mobile UI, compare it against mockups/assets and journey
     requirements, and report visual gaps with artifact evidence.
   - If workers are unavailable, use disclosed manual fallback coverage: process
     each prompt yourself, save reports under `reports/`, update the ledger, and
     keep the final coverage label as manual fallback coverage.

5. **Verify coverage**
   - Save one report per source batch under `reports/batch_###.md`.
   - Save visual reports under:
     - `reports/mockup_asset_audit.md`
     - `reports/visual_tooling_audit.md`
     - `reports/visual_comparison_audit.md`
   - Fill `effort_ledger.json` with lead effort, subagent capability, per-batch
     worker status, visual worker status, fallback status, and pruned-directory
     review decisions when applicable.
   - Run:

     ```bash
     python3 "$UI_IMPLEMENTATION_AUDIT_SKILL_DIR/scripts/verify_ui_implementation_audit_results.py" --manifest <audit-output>/manifest.json --reports <audit-output>/reports
     ```

   - Treat verifier failures as blockers before final synthesis.

6. **Synthesize the implementation plan**
   - Deduplicate source and visual findings.
   - Separate confirmed screenshot/source gaps from hypotheses and blockers.
   - Treat first-viewport journey failures as real UI defects even when the
     page matches a mockup, has correct data, and has no horizontal overflow.
   - Prioritize by user journey impact, visual mismatch severity, responsive
     breakage, accessibility, implementation risk, and dependency order.
   - Include concrete implementation and verification steps for every gap.

## Batch Worker Review Rules

For every owned interface source unit:

- Inventory visible labels, controls, form fields, menus, route links, toasts,
  banners, empty/loading/error states, and critical layout containers.
- Trace the implementation path: handler, state, navigation, API/persistence,
  permission, validation, loading/error/empty state, and responsive rules.
- Compare source implementation against mockup/journey evidence from the prompt
  and manifest.
- Flag visual and UX gaps: wrong hierarchy, missing content, wrong density,
  excessive decoration, missing states, dead controls, hidden primary action,
  overexposed rare detail, layout overflow, cropped text, unreadable controls,
  missing asset use, accessibility gaps, and mismatched copy.
- Flag settings/filter forms placed above primary content on mobile; repeated
  desktop ordering that breaks mobile journey priority; overexposed rare/admin
  controls; high-value content pushed below low-value configuration; and visual
  similarity to a mockup that still fails journey usefulness.
- For ranged units, use the exact unit id in coverage rows and inventory rows.

## Required Batch Report

Each batch report must contain exactly these top-level headings in order:

```markdown
## Run ID
## Batch ID
## Batch Summary
## File Coverage
## UI Source Inventory
## Journey Priority Contract
## First Viewport Journey Check
## Mockup And Journey Alignment
## Implementation Gap Findings
## No Gap Notes
## Open Questions
```

`File Coverage` must include one row per owned unit with columns `Unit`,
`Status`, `SHA-256`, and `Purpose`; every status must be `CHECKED`.

`UI Source Inventory` must include columns `Unit`, `File`, `Surface`, `Visible
Element`, `Source Evidence`, `Expected Behavior`, `Actual Implementation`, and
`Responsive/State Notes`.

`Journey Priority Contract` must include columns `Surface`, `Primary user goal`,
`Primary information`, `Frequent actions`, `Occasional controls`,
`Rare/Admin/Configuration controls`, `Expected desktop order`, and `Expected
mobile order`.

`First Viewport Journey Check` must include columns `Viewport`, `First visible
content`, `Primary decision data visible?`, `Low-frequency controls above
content?`, `Low-frequency/header/control share`, `What can user decide from
first viewport?`, `Result`, and `Evidence`. Mobile/narrow rows are required.

Findings must use either `No findings.` or field blocks with:

- Priority: `P0`, `P1`, `P2`, or `P3`
- Files: repo-relative files owned by the batch
- Mockup/requirement evidence: asset, journey doc, route, or explicit absence
- Interface evidence: source file, visible text, handler, style, or state
- Expected behavior/standard: expected visual or journey behavior
- Gap: concrete mismatch
- Suggested implementation direction: specific fix direction

## Visual Worker Requirements

The visual comparison report is not complete if it only says the UI "looks
good" or "matches the mockup." It must include `Journey Priority Contract`,
`First Viewport Journey Check`, and `Visual Comparison Checks` tables with
desktop and mobile/narrow rows when a web UI can be rendered. Evidence should
name the command/tool and screenshot/trace/video/artifact path when available.
If screenshots cannot be produced, the row result must be `BLOCKED` and the
findings must explain the missing safe render path.

For each rendered screen, check:

- Match to mockup composition, spacing, density, typography, color, imagery,
  iconography, and information priority.
- Desktop and mobile fit: no accidental horizontal scroll, overlap, cropped
  decision data, unreadable compression, or primary action pushed below low
  value content.
- First mobile viewport usefulness: primary decision-making content is visible
  before scroll unless the page is itself a data-entry form; low-frequency
  settings, filters, menus, and configuration panels do not dominate before the
  user can make the primary decision.
- Estimate the percentage of the first mobile viewport occupied by navigation,
  headers, settings, filters, and controls. If low-frequency controls consume
  roughly 25-30% or more while primary content is below the fold, report a P1.
- Answer: "What can the user decide from the first viewport?" If the answer is
  only configuration choices while the primary data is below the fold, report a
  journey-priority gap.
- Flag mobile layouts that simply stack the desktop order and thereby put rare
  or occasional controls before primary content.
- Journey relevance: critical-always and primary-frequent content is prominent;
  secondary content is available; rare-under-5-percent detail is hidden behind
  menus, expanders, tabs, or drill-in views when space is tight.
- Interaction states: loading, empty, error, disabled, focus, hover/pressed,
  permission-denied, destructive confirmation, undo/rollback, and success.
- Accessibility: labels, focus order, keyboard access, contrast risk, semantic
  controls, text fitting, and state not conveyed only by color.

## Final Output

Return exactly these top-level headings:

```markdown
## Coverage
## Mockup And Requirement Inputs
## Journey Priority Contract
## First Viewport Journey Findings
## Visual Audit Findings
## Source Implementation Findings
## Journey And Responsive Findings
## Accessibility And Interaction Findings
## Implementation Plan
## Verification Plan
```

Use this priority scale:

- `P0`: Core journey unusable, data-loss/destructive risk, or runtime failure.
- `P1`: Major mismatch from mockup/requirements or primary journey expectation.
- `P2`: Important visual, responsive, accessibility, state, or maintainability
  gap.
- `P3`: Polish, consistency, copy, or low-risk cleanup.

## Completion Rules

- The final report must state the audit output path, run id, source files
  queued, visual assets/mockups found, requirement sources found, visual tools
  attempted, screenshot/artifact evidence, unchecked files/units, scope
  warnings, ledger status, and verifier result.
- If no mockups/assets are found, label visual target coverage as
  `mockup target missing` and include a plan item to add or provide target
  imagery.
- If no safe rendered UI path exists, label visual comparison coverage as
  `blocked by missing visual harness` and include a plan item to add Playwright,
  Storybook, a fixture route, a native preview, or another screenshot path.
- Do not present source-only review as a completed visual audit.
