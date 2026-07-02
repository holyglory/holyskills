---
name: ui-implementation-audit
description: Audit a repository's implemented user interface against mockup images, visual assets, and user journey requirements. Use when Codex needs to compare rendered desktop/mobile UI screenshots and UI source code against design assets, ImageGen mockups, Figma exports, screenshots, product journeys, or UX requirements, then produce a prioritized plan for closing visual, responsive, interaction, journey, implementation, and test gaps. Only interface-defining source files are queued in deterministic source batches.
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

Hard reporting gate: every final audit must include an interaction checklist in
`## Accessibility And Interaction Findings` with the exact labels
`badge-detail`, `row-hit-target`, `navigation-cursor`,
`transient-disclosure`, `disclosure-scrollbar`, `icon-meaning`,
`stable-expansion-width`, `hover-copy`, `status-summary`, and
`message-metadata`. Each label must be marked `pass`, `gap`, `blocked`, or
`not applicable` with evidence. If the final report does not contain all ten
literal labels, rewrite it before returning.

Treat the intended interface as a complete contract: every required screen,
journey step, UI element, visible message, interaction state, responsive layout,
handler, data path, accessibility path, and visual/test evidence must be present.
If a mockup, journey doc, product requirement, visible source promise, or
user-confirmed intent implies an element or behavior, audit it as required and
report anything missing, partial, unwired, visually wrong, or untested.
Journey docs are evidence, not immunity. If the rendered UI is overloaded,
duplicative, vague, or dominated by secondary/detail/debug content because a
journey doc over-prescribed default visibility, report both the rendered UI gap
and the documentation handoff conflict instead of marking the UI as compliant.

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
- Before comparing screenshots to mockups, define a journey decision model:
  primary user goal, primary decision, required facts, warning/flag conditions,
  frequent actions, secondary/rare actions, and unconfirmed assumptions.
- The visual comparison worker must try available rendered-surface tooling:
  Playwright, Cypress, Storybook, browser MCP tools, app/browser preview,
  native simulator/preview tools, or screenshot-capable test commands. It must
  check desktop and narrow mobile viewports when a web UI exists.
- When a web UI has a safe render path, the visual comparison worker must run
  `formal-web-ui-verification` or explicitly report why it is blocked. Treat
  unresolved critical formal findings for clipping, overlap, off-canvas
  controls, broken media, invisible text, document overflow, or area violations
  as audit gaps. Always include the verifier's visible scrollbar inventory in
  visual evidence, even when it has no critical findings.
- The visual comparison worker must answer whether each rendered viewport
  supports the current journey decision. Except on pages whose primary purpose
  is data entry, visible content should mostly drive the current decision;
  secondary detail, debug data, and rare configuration should be available
  without dominating the main surface. Use the documented information
  hierarchy to judge placement: critical-always information must be visible at
  the decision point, primary-frequent information should be prominent,
  secondary information should be reachable without dominating, and
  rare/debug/expert detail should not consume prime space unless the journey
  docs justify it.
- The visual comparison worker must check interaction affordances, not just
  static appearance. Decision badges, flags, rows, and disclosures should show
  hover/focus/click affordance when interactive; whole-row activation should be
  preferred when the row is the meaningful target; disclosure icons must not
  collide with scrollbars or adjacent controls; and expanded/collapsed states
  should keep stable width, placement, and readable alignment. Navigating rows,
  badges, links, and contextual explanations must expose a predictable
  destination and pointer/keyboard affordance. Temporary panels, popovers, and
  expanded signal regions should have an intentional lifecycle such as explicit
  close, outside click, focus loss, idle leave timer, or documented persistence.
- Treat interaction affordances as a required checklist for any UI that contains
  badges, flags, expandable rows, tool/result blocks, scrollable details,
  message streams, or icon-only controls. The audit is incomplete if it does not
  explicitly mark each relevant item as pass, gap, blocked, or not applicable:
  badge hover/focus/click feedback and popover/detail access; row/card
  activation versus tiny icon-only activation; navigation destination and
  pointer/focus cursor affordance; transient disclosure lifecycle; disclosure
  control separation from scrollbars and adjacent controls; stable
  collapsed/expanded dimensions; icon meaning; hover-revealed copy controls that
  are stable and reachable; concise status summaries that avoid duplicate
  status/severity/duration noise; message sender/routing label relevance; and
  timestamp/passive metadata selection behavior.
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
   - Write the journey decision model before inspecting screenshots: primary
     goal, primary decision, required facts, warning/flag conditions, frequent
     actions, secondary/rare actions, and unconfirmed assumptions.
   - Build a complete screen inventory: route/screen, target user, journey step, primary
     decision, required information, primary actions, secondary/rare details,
     all required UI elements, states, and supported viewport constraints.
   - For every important rendered viewport, define the decision it must support,
     which visible content is decision-driving, which content is secondary/detail
     or configuration, and whether details are reachable without overwhelming
     the decision path.
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
   - Treat rendered journey-usability failures as real UI defects even when the
     page matches a mockup, has correct data, and has no horizontal overflow.
   - Prioritize by user journey impact, missing required UI elements, visual mismatch severity, responsive
     breakage, accessibility, implementation risk, and dependency order.
   - Include concrete implementation and verification steps for every missing or incomplete UI, interaction, state, accessibility, data, and test gap.

## Batch Worker Review Rules

For every owned interface source unit:

- Inventory visible labels, controls, form fields, menus, route links, toasts,
  banners, empty/loading/error states, and critical layout containers.
- Trace the implementation path: handler, state, navigation, API/persistence,
  permission, validation, loading/error/empty state, and responsive rules.
- Compare source implementation against mockup/journey evidence from the prompt
  and manifest.
- Confirm every required UI element has real implementation and verification
  evidence; report missing handlers, missing persistence, missing state coverage,
  missing accessibility, and missing visual/test coverage as gaps.
- Flag visual and UX gaps: wrong hierarchy, missing content, wrong density,
  excessive decoration, missing states, dead controls, hidden primary action,
  overexposed rare detail, layout overflow, cropped text, hidden overflow
  without scrolling, unreadable controls, low-contrast or invisible theme text,
  missing asset use, accessibility gaps, and mismatched copy.
- Flag surfaces where low-journey-relevance content dominates the visible area:
  settings/filter forms, rare/admin controls, debug/raw status detail,
  explanatory copy, or secondary metadata that crowds out decision-driving
  content. Do this across desktop, native, and narrow/mobile viewports rather
  than only one mobile layout pattern.
- Flag visual-noise and layout-discipline gaps that prevent the information
  hierarchy from reading correctly: cards or blocks nested inside other cards,
  repeated borders/background changes, inconsistent gutters, controls that move
  when expanded, permanent obvious instructions, meaningless icons, decorative
  avatars or clutter, and message layouts whose sender/receiver alignment is
  inconsistent with the journey.
- Flag interaction and metadata gaps: badges or flags that look interactive but
  lack hover/click feedback or a useful popover/detail; meaningful rows that
  require hitting only a tiny icon; contextual explanation rows that navigate
  without a pointer/focus affordance or predictable destination; temporary
  popovers/panels that stay open indefinitely without a clear lifecycle;
  disclosure controls that interfere with scrollbars; icons whose meaning is
  unclear even with context; expandable tool or result blocks that change width
  between states; copy controls that permanently clutter messages or disappear
  while the pointer moves toward them; concise tool/result blocks that repeat
  completed/error/severity/duration signals instead of showing the minimum
  status needed; selectable timestamps or metadata that should be passive; and
  visible sender/routing labels that add noise when the message content alone is
  the decision-driving information.
- For ranged units, use the exact unit id in coverage rows and inventory rows.

## Required Batch Report

Each batch report must contain exactly these top-level headings in order:

```markdown
## Run ID
## Batch ID
## Batch Summary
## File Coverage
## UI Source Inventory
## Journey Decision Model
## Rendered Journey Usability
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

`Journey Decision Model` must include columns `Surface`, `Primary user goal`,
`Primary decision`, `Required facts`, `Warning/flag conditions`, `Frequent
actions`, `Secondary/rare actions`, and `Unconfirmed assumptions`.

`Rendered Journey Usability` must include columns `Viewport`, `Decision
supported`, `Visible decision-driving content`, `Visible secondary/detail
content`, `Detail access pattern`, `Readability/contrast evidence`, `Layout
quality result`, and `Evidence`. Desktop rows are required for native or desktop
apps; desktop and mobile/narrow rows are required when a web UI can be rendered.
When a viewport contains badges, flags, expandable rows, tool/result blocks,
scrollable details, message streams, or icon-only controls, its `Detail access
pattern` or `Evidence` cell must explicitly cover row activation, badge
hover/focus/click detail behavior, disclosure/scrollbar separation, icon
meaning, expanded/collapsed size stability, and passive metadata behavior. Use
`not applicable` for categories truly absent from that viewport.

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
good" or "matches the mockup." It must include `Journey Decision Model`,
`Rendered Journey Usability`, and `Visual Comparison Checks` tables with
desktop and mobile/narrow rows when a web UI can be rendered. Evidence should
name the command/tool and screenshot/trace/video/artifact path when available.
If screenshots cannot be produced, the row result must be `BLOCKED` and the
findings must explain the missing safe render path.
When the web UI can be rendered, evidence should also name the
`formal-web-ui-verification` command and report path. If the verifier cannot
run, mark formal DOM/layout verification as `BLOCKED`; if it runs, summarize
critical findings and visible scrollbars from the Markdown or JSON report.

For each rendered screen, check:

- Match to mockup composition, spacing, density, typography, color, imagery,
  iconography, and information priority.
- Desktop, native, and mobile fit: no accidental horizontal scroll, overlap,
  cropped decision data, hidden overflow without scrolling, unreadable
  compression, or low-value content dominating the decision path.
- Rendered journey usefulness: visible content should be dominated by facts,
  warnings, and actions that help the user progress through the current journey.
  Details, settings, filters, raw/debug status, and rare/admin controls may be
  present, but they should not overwhelm the primary decision path.
- Handoff conflict: if a requirement says all facts must be visible but the
  screenshot shows duplicate severity summaries, vague labels, source-model
  leakage, or detail controls dominating the main state, record a gap and
  recommend separating default indicators from hover/focus/click detail.
- Structure and alignment: if the screenshot shows nested cards/blocks,
  stacked borders, competing backgrounds, random-looking placement, weak grid
  discipline, disclosure controls that jump or change width, permanent helper
  copy, meaningless icons, avatar clutter, or inconsistent message alignment,
  record a visual/usability gap even when all data is technically present.
- Answer: "What decision can the user make from this rendered viewport?" If the
  answer is unclear, only configuration-oriented, or buried under secondary
  detail, report a journey-usability gap.
- Flag broad layout problems: overload, crowding, ambiguous hierarchy, clipped
  or truncated text, hidden overflow with no scroll path, oversized controls,
  unreadable compression, low contrast, invisible dark-theme text, and any
  visually present information that is not scannable enough to support the
  journey.
- Journey relevance: critical-always and primary-frequent content is prominent;
  secondary content is available; rare-under-5-percent detail is available
  through an appropriate detail path when visible space is tight.
- Interaction states: loading, empty, error, disabled, focus, hover/pressed,
  permission-denied, destructive confirmation, undo/rollback, and success.
- Accessibility: labels, focus order, keyboard access, contrast risk, semantic
  controls, text fitting, and state not conveyed only by color.

## Final Output

Return exactly these top-level headings:

```markdown
## Coverage
## Mockup And Requirement Inputs
## Journey Decision Model
## Rendered Journey Usability Findings
## Visual Audit Findings
## Source Implementation Findings
## Journey And Responsive Findings
## Accessibility And Interaction Findings
## Implementation Plan
## Verification Plan
```

The `Accessibility And Interaction Findings` section must include a short
checklist before or after findings with these exact labels: `badge-detail`,
`row-hit-target`, `disclosure-scrollbar`, `icon-meaning`,
`stable-expansion-width`, `message-metadata`. Each label must be marked `pass`,
`gap`, `blocked`, or `not applicable` with a file/screenshot/source reference.
If any label is `gap` or `blocked`, include a prioritized finding in this
section or in the closest specific findings section.

Use this priority scale:

- `P0`: Core journey unusable, data-loss/destructive risk, or runtime failure.
- `P1`: Major missing UI element, implementation path, test path, mismatch from mockup/requirements, or primary journey expectation.
- `P2`: Important visual, responsive, accessibility, state, or maintainability
  gap.
- `P3`: Polish, consistency, copy, or low-risk cleanup.

## Completion Rules

- The final report must state the audit output path, run id, source files
  queued, visual assets/mockups found, requirement sources found, visual tools
  attempted, formal Web UI verifier result when applicable, visible scrollbar
  inventory when applicable, screenshot/artifact evidence, unchecked
  files/units, scope warnings, ledger status, and verifier result.
- If no mockups/assets are found, label visual target coverage as
  `mockup target missing` and include a plan item to add or provide target
  imagery.
- If no safe rendered UI path exists, label visual comparison coverage as
  `blocked by missing visual harness` and include a plan item to add Playwright,
  Storybook, a fixture route, a native preview, or another screenshot path.
- Do not present source-only review as a completed visual audit.
