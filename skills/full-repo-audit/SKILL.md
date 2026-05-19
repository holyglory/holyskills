---
name: full-repo-audit
description: Run a full repository source-code, interface, and user-journey audit that combines an extra-high-effort lead architectural review with low-effort subagent batches that manually inspect every queued source file plus separate journey and visual UI workers. Use when the user asks to audit a repo for incomplete or partial features, TODO/stub behavior, industry-standard gaps, user-expectation gaps, architectural risk, UI controls or messages that imply unimplemented behavior, unclear user journeys, visual/test-mode gaps, or to produce a prioritized implementation plan from repository-wide findings.
---

# Full Repo Audit

## Overview

Run a multi-level audit: the lead agent performs the architectural, product-flow, and interface review; low-effort subagents manually inspect every source file in deterministic batches; separate UI journey workers inspect source-level journeys and visual testability. Use the harness script to create a coverage manifest and worker prompts, then reconcile all results before producing the final implementation plan.

## Required Execution Model

- Execute the lead audit with extra-high reasoning effort. If the current lead run cannot be confirmed or configured as extra-high effort, tell the user before starting; when the environment supports spawned agents, run the formal lead architectural pass as an extra-high-effort agent and disclose that handoff. If no current or spawned lead can be confirmed as extra-high, stop before dispatching the audit and ask the user to rerun in an x-high-capable runtime; do not produce a degraded full-audit result. Manual fallback applies only to worker coverage; do not downgrade or waive the lead x-high requirement.
- Use low-effort subagents for file-batch inspection. When spawning these agents, set `reasoning_effort` to `low`.
- When interface-relevant files are queued, use separate low-effort workers for `journey_audit.md` and `visual_journey_audit.md`. Manual fallback may process these prompts in the current agent only when worker spawning is unavailable, but the final coverage label must disclose that fallback.
- Treat the user's request to run this audit as authorization for the batch subagents required by this workflow.
- After the lead x-high gate above is satisfied, check whether the active runtime exposes a subagent tool that can set `reasoning_effort` for spawned worker agents. If that worker tool is absent, fails, or cannot set low effort, record the reason and enter manual fallback mode for worker coverage only.
- Keep a lead-recorded effort/capability ledger: record the subagent capability check, lead effort status, and each batch's assigned agent id plus `reasoning_effort` or manual fallback status from the runtime spawn results. The verifier checks the recorded ledger values and consistency, but it cannot independently prove platform scheduler settings; describe effort status as ledger-recorded unless the runtime provides separate immutable provenance.
- If the lead x-high gate is satisfied but the runtime cannot spawn worker subagents or set low worker effort, continue only in **manual fallback mode** for worker coverage: disclose the limitation, run each generated batch sequentially in the current agent, save one report per batch under `<audit-output>/reports/batch_###.md`, verify coverage with `verify_audit_results.py`, and label final coverage as `manual fallback coverage` rather than subagent coverage.
- Keep subagent ownership disjoint: one batch prompt per subagent, no overlapping file ownership unless a batch must be rechecked.
- Keep the audited repo read-only unless the user separately asks to implement the resulting plan. Generated audit artifacts are allowed, but place them outside the audited repo by default and disclose their path.
- If the user explicitly forbids all file writes or artifact creation, do not run the harness or save reports unless they authorize audit artifacts. Perform a chat-only manual audit, label coverage as `chat-only unverified coverage`, and state that manifest/report verification was not run.
- Do not claim every file was checked until the manifest coverage and subagent coverage reports match.

## Workflow

1. **Set scope**
   - Use the current working directory as the repo root unless the user names another path.
   - Include tests, build scripts, extensionless scripts/hooks under script directories such as `scripts/` and `.husky/`, lockfiles, project/build files, schema/config files, routes, jobs, migrations, native UI files, source-backed UI assets, UI components, templates, translations, message catalogs, journey/workflow docs, and operational Markdown such as `SKILL.md`, `AGENTS.md`, and repo docs that define expected behavior.
   - Exclude generated/vendor/build artifacts unless the user explicitly asks to audit them; pass `--include-generated` and/or `--include-vendor` only for that explicit request.
   - Exclude real `.env` files by default; use `--include-env` only when the user explicitly wants secret-bearing environment files audited.

2. **Generate the audit queue**
   - Resolve the audited repo to an absolute path before generation and echo it in your working notes.
   - Resolve `FULL_REPO_AUDIT_SKILL_DIR` to the directory containing this `SKILL.md` from the loaded skill path. Preflight the skill harness before starting: verify `scripts/build_audit_batches.py`, `scripts/verify_audit_results.py`, and `scripts/self_test.py` exist under `$FULL_REPO_AUDIT_SKILL_DIR` and are readable, then run `python3 "$FULL_REPO_AUDIT_SKILL_DIR/scripts/self_test.py"` unless the user explicitly forbids validation commands. If any companion script is missing or the self-test fails, stop and tell the user the skill harness is incomplete or failing instead of treating the failure as an audited-repo finding.
   - Run:
     ```bash
     REPO_ROOT="${REPO_ROOT:-$PWD}"
     python3 "$FULL_REPO_AUDIT_SKILL_DIR/scripts/build_audit_batches.py" --repo "$REPO_ROOT"
     ```
   - If the user names a repo path, set `REPO_ROOT` to that path instead of `$PWD`.
   - By default, output goes under a unique system temp directory, not inside the audited repo.
   - Use `--out <dir>` when the user wants a specific artifact location.
   - Treat `--out` as a harness-owned artifact directory. The harness writes `.full-repo-audit-artifacts.json` and refuses to clean non-empty directories that are not marked as harness-owned.
   - Use `--include-generated`, `--include-vendor`, or `--include-env` only when the user explicitly wants those normally excluded artifacts audited.
   - Use `--include-assets` when the user explicitly wants binary UI assets such as logos, icons, screenshots, or fonts audited; without it, likely UI assets are excluded with scope warnings that must be resolved before full coverage is claimed.
   - Use `--include-file <repo-relative-path>` or `--include-glob <glob>` to force a source/manual batch for a high-signal unknown file that was raised as a scope warning.
   - Use `--run-id <stable-token>` only when an external orchestrator or repeated audit loop needs artifacts to share a caller-supplied run id; otherwise let the harness generate one.
   - Use `--batch-size` and `--max-batch-bytes` to keep batches small enough for manual inspection. Oversized UTF-8 multi-line files are split into line-range coverage units; long/minified single-line or non-UTF-8 files are split into byte-range coverage units. Dispatch and verify each unit instead of treating a very large file as one undifferentiated worker task.
   - Confirm `queue_complete.json` exists, its `phase` is `queue_generated`, and its `run_id` matches `manifest.json` before dispatching subagents. This marker means queue generation completed; it is not proof that the audit reports are complete.
   - Fill `effort_ledger.json` as you dispatch and reconcile: subagent capability check, spawn tool, capability notes/evidence, lead effort status, fallback status, pruned-directory review status/notes when required, journey worker agent id/effort/status/report, per-batch agent id/effort/status/report, per-batch runtime provenance, and the ledger's self-reported provenance scope.
   - Inspect `excluded_files.json` after generation and resolve any `scope_warning: true` rows before claiming full coverage. If `manifest.json` has `pruned_directory_review_hint_count > 0`, inspect `pruned_directory_review_hints`, requeue first-party source-like samples when needed, and record one structured `pruned_directory_review.decisions[]` entry per hinted path in `effort_ledger.json` using `requeued`, `excluded-with-rationale`, or `out-of-scope-with-user-confirmation` plus a concrete rationale.
   - A scope warning is verifier-cleared only by re-running the queue with the needed include flag or requeuing the specific file in a new/manual batch. If the user confirms an exclusion or the lead downgrades the final coverage claim, keep the verifier failure visible and list the exclusion explicitly.

3. **Run the lead architectural pass**
   - Inspect the repo structure, docs, package/build files, routes, schemas, tests, deployment config, entry points, and domain terminology.
   - Identify intended product surfaces and feature families before reading subagent findings.
   - Look for cross-cutting risks: missing integration paths, inconsistent state models, auth/permission drift, data migration gaps, error handling, observability, accessibility, security, performance, reliability, and test strategy.
   - Build an interface inventory from routes, pages, components, templates, command palettes, menus, forms, message catalogs, and visible copy.
   - Trace important controls and messages to handlers, state transitions, API calls, persistence, navigation, permission checks, and error/loading/empty states.
   - Find the repo's clear user journey description(s). If missing, draft the most reasonable frequent journeys from app intent, routes, visible copy, and code, mark them as draft, and ask the user to confirm the most frequent use cases before treating them as final; if the audit must continue without user input, carry the drafts as open questions and implementation-plan assumptions.

4. **Dispatch low-effort workers**
   - Open the generated `audit_index.md`.
   - For each `batch_###.md`, spawn one low-effort subagent and pass the entire prompt file content.
   - When generated, spawn a separate low-effort source journey worker with `journey_audit.md`. This worker checks journey documentation, drafts missing journeys, estimates UI element relevance, and traces navigation/decision information through UI source.
   - When generated, spawn a separate low-effort visual journey worker with `visual_journey_audit.md`. This worker identifies Playwright/Cypress/Storybook/browser/native-preview tooling, uses test mode when available, and verifies or plans visual desktop/mobile journey checks.
   - Tell subagents not to edit files and to report coverage for every listed file.
   - Run in waves if the repo is large; keep a ledger of batch id, agent id, status, and returned checked files.
   - If subagents are unavailable, use manual fallback mode: process each `batch_###.md` and generated journey prompt yourself, save the required reports under `<audit-output>/reports/`, and keep the reduced coverage label through the final report.

5. **Reconcile coverage**
   - Compare `manifest.json` source files, coverage units, run id, and SHA-256 fingerprints with every subagent `File Coverage` table. For range units, the coverage row must use the exact unit id such as `path#Lstart-Lend` or `path#Bstart-end`; the exact unit id must also appear in `Findings` or `No Finding Notes` so the verifier can prove that specific range was checked, while the finding `Files` field still references the real repo-relative file path.
   - Confirm required journey reports exist at `reports/journey_audit.md` and `reports/visual_journey_audit.md` when interface-relevant files were queued, and that `effort_ledger.json` records those workers as completed or manual fallback.
   - Save one subagent Markdown report per batch under `<audit-output>/reports/` using the exact filename `batch_###.md`, then run:
     ```bash
     python3 "$FULL_REPO_AUDIT_SKILL_DIR/scripts/verify_audit_results.py" --manifest <audit-output>/manifest.json --reports <audit-output>/reports
     ```
   - Treat verifier failures for unresolved scope warnings, incomplete effort or journey-worker ledger entries, queue marker mismatches, missing or boilerplate interface inventory rows, missing high-confidence visible controls/messages, generic interface trace rows, placeholder/stub source omissions, malformed or boilerplate finding fields, out-of-batch finding file references, missing files, `UNCHECKED` rows, missing/mismatched SHA-256 values, stale run ids, changed files, unavailable repo source for source-backed checks, excluded-file digest drift, or directory-only descriptions as blockers before final synthesis. Every `scope_warning: true` row is intentionally unresolved until it is requeued or cleared by regenerating the queue.
   - If a run is interrupted or the ledger claims a worker is complete but its report file is missing, treat the verifier as authoritative and recover from the manifest rather than the stale ledger: inspect `manifest.json` and `reports/`, mark missing batch/journey reports back to pending or rerun them, save the exact report filenames, update `effort_ledger.json` with the new agent/fallback status, and rerun the verifier. Do not claim completion from ledger status alone.
   - Requeue any source-like unknown file or source-backed UI asset needed to resolve a warning by regenerating the queue with `--include-file`, `--include-glob`, or `--include-assets`, then rerun the affected batch and verifier.
   - Inspect suspicious high-impact findings directly as lead before including them.

6. **Synthesize the implementation plan**
   - Deduplicate batch findings.
   - Separate confirmed issues from hypotheses and open questions.
   - Prioritize by user impact, correctness, security/reliability, blast radius, and implementation dependency order.
   - Produce an implementation plan with concrete verification steps that reproduce or demonstrate each gap.

## Subagent Result Requirements

Require each batch subagent to return:

- `Run ID`: the exact run id from the batch prompt.
- `Batch ID`: the exact `batch_###` id.
- `Batch Summary`: what the files collectively do.
- `File Coverage`: one row per listed file with `CHECKED` or `UNCHECKED`, the exact SHA-256 from the batch prompt, and a one-line purpose.
- `Interface Inventory`: for every interface-relevant file, one or more table rows with file, surface, visible label/control/message, expected behavior path, and actual implementation notes; visible text must be concrete source text or an explicit `None found` note, not boilerplate; for non-interface batches, the exact sentinel `No interface-relevant files in this batch.`
- `Findings`: prioritized issues with file references, concrete evidence, expected behavior or standard, gap, and suggested fix direction. Finding `Files` fields must reference only files owned by the batch.
- `No Finding Notes`: files checked with no notable issue.
- `Open Questions`: ambiguity the lead should resolve.

Reject or requeue a batch result if it omits files, claims broad conclusions without file-level inspection, or proposes edits without evidence.

Require the journey source worker to return `Run ID`, `Worker`, `Journey Sources`, `Proposed Journeys`, `UI Source Journey Checks`, `Findings`, and `Open Questions`. Require the visual journey worker to return `Run ID`, `Worker`, `Visual Tooling`, `Visual Journey Checks`, `Findings`, and `Open Questions`. Their `Findings` sections must use the same field schema as batch findings (`Files`, `Evidence`, `Interface evidence`, `Expected behavior/standard`, `Gap`, `Suggested direction`) or the exact clean sentinel `No findings.` If no explicit journey documentation exists, the journey source report must include draft journeys marked `draft-needs-user-confirmation`.

## Final Audit Output

Return a concise but complete plan with exactly these top-level Markdown headings, in this order:

## Coverage
Repo root, audit output path, run id, source files queued, coverage units queued, files or units checked by subagents or manual fallback, files rechecked by the lead, journey workers run, scope warnings, exclusions, unchecked files or units, verifier result, subagent capability check result, ledger-recorded lead effort status, and per-batch/journey effort/fallback ledger.

## Architecture Findings
Repo-wide design and product-flow gaps from the lead pass, or `No confirmed findings.`

## Interface Findings
Buttons, menu items, links, form fields, messages, command items, empty states, toasts, or labels that point to unimplemented, partial, misleading, or wrongly wired behavior, or `No confirmed findings.`

## User Journey Findings
Missing or unclear journeys, navigation relevance problems, missing decision information, mobile/desktop visibility/cropping issues, missing test mode, unavailable visual test tooling, or `No confirmed findings.`

## File-Level Findings
Confirmed issues from batch results, deduplicated and grouped by feature area, or `No confirmed findings.`

## Implementation Plan
Ordered work items with expected behavior, affected files or modules, implementation steps, tests, and risk. Use `No implementation work recommended from this audit.` when clean.

## Verification Plan
Commands, browser/API checks, fixtures, or user workflows needed to prove each improvement. Include the exact verifier command and any commands already run.

Use this priority scale:

- `P0`: Security/data-loss/runtime failure or feature unusable for core workflows.
- `P1`: Major user expectation gap, partial feature, broken integration path, or standards gap likely to affect real use.
- `P2`: Important quality, maintainability, accessibility, performance, or test gap.
- `P3`: Polish, documentation, cleanup, or low-risk consistency improvement.

## Interface Audit Requirements

During both lead and subagent review, inspect UI implementation as a source of product promises. Inventory visible controls and copy, then check whether the code actually implements what a user would expect.

Look for:

- Buttons, icon buttons, menu items, tabs, command palette items, links, and keyboard shortcuts with missing handlers, placeholder handlers, TODO handlers, console-only handlers, disabled dead ends, or handlers that do not persist/navigate/refresh.
- Text fields, filters, selectors, toggles, uploads, settings, and forms whose values are ignored, only locally mocked, not validated, not saved, or not reflected in later UI/API behavior.
- Toasts, banners, empty states, tooltips, helper text, onboarding copy, success/error messages, and labels that promise capabilities not implemented in code.
- UI states that are missing or misleading: loading, empty, error, permission denied, offline, undo/redo, destructive confirmation, optimistic update rollback, or background job progress.
- Navigation surfaces that expose unavailable routes, hidden admin-only paths without permission handling, orphaned pages, or pages not linked from expected menus.
- Accessibility and interaction gaps that make an implemented feature behave as partially implemented: unlabeled controls, keyboard traps, focus loss, non-semantic buttons/links, or state conveyed only visually.

For each interface finding, capture the visible label or message text, the file that defines it, the expected implementation path, the actual implementation path, and the missing or wrong behavior.

## User Journey Audit Requirements

Audit whether the repo clearly describes the most important user journey(s) through the UI. Accept journey docs, route maps, onboarding specs, product docs, tests, Storybook stories, or source-backed route/component flows. If none exist, draft likely journeys from the app intent and visible code, ask the user to confirm the most frequent use cases, and keep unconfirmed journeys as assumptions/open questions.

During the source journey pass, check:

- Primary navigation and decision elements are visible, reachable, and visually prominent relative to less relevant elements. Estimate relevance as `critical-always`, `primary-frequent`, `secondary-occasional`, or `rare-under-5-percent`.
- Users have enough information on each screen, on mobile and desktop, to make weighted decisions. Always-needed information should be visible; rare information should be reachable within one click/tap through menus, expandables, or details views; warning/threshold information must be visible without requiring expansion.
- Important information is not cropped, hidden behind accidental overflow, or displaced by lower-relevance content. Less important information should not poison dense screens unless free space is available.
- Heavy or side-effecting UI actions can be exercised in a test mode, fixture mode, mock data mode, dry run, preview mode, or other safe visual path.

During the visual journey pass, use available visual tooling such as Playwright, Cypress, Storybook, browser MCP tools, native UI preview tools, or screenshots. Prefer test mode; use production mode only when the user explicitly requested it or the journey has no heavy/side-effecting operations. Check desktop and narrow mobile viewports for journey completion, real navigation rather than abstracted mocks, visible decision information, theme consistency, readable font sizes, sufficient color contrast, non-cropped content, and unnecessary horizontal scrolling. When visual checks are applicable, include the command/tool used and screenshot, trace, recording, or other artifact evidence in the report. For CLI, library, plugin, or skill packages that expose only metadata/Markdown and no repo-owned rendered UI surface, mark visual checks as `not applicable` with evidence instead of treating host-owned rendering as a repo defect.

## Harness

`scripts/build_audit_batches.py` creates audit-run artifacts:

- `manifest.json`: source-file inventory, coverage-unit inventory, batch membership, and coverage invariants.
- `audit_index.md`: lead-agent instructions and a batch table.
- `.full-repo-audit-artifacts.json`: ownership marker that lets reruns clean stale harness artifacts without deleting user files.
- `queue_complete.json`: queue-generation marker written last with `phase: queue_generated` and `audit_verified: false`; if it is absent or the run id differs from `manifest.json`, regenerate the queue before dispatch.
- `effort_ledger.json`: lead-recorded capability, effort, fallback, and per-batch assignment ledger that must be completed before final synthesis.
- `journey_audit.md`: source-level user-journey worker prompt generated when interface-relevant files exist.
- `visual_journey_audit.md`: visual journey worker prompt generated when interface-relevant files exist.
- `batch_###.md`: subagent-ready prompts with exact file or range ownership and interface-specific checks when relevant.
- `excluded_files.json`: files skipped with reasons for transparency.
- `reports/`: required destination for returned subagent reports, one exact `batch_###.md` file per batch.

Companion scripts included with this skill:

- `scripts/verify_audit_results.py`: result verifier for returned subagent `Run ID`, exact report section shape, `File Coverage` SHA-256 tables, `Interface Inventory` coverage and concrete visible-text checks for interface-relevant files, high-confidence visible-control/message hint coverage, source-backed UI asset evidence, generic interface trace rejection, obvious placeholder/stub/dead-control source omission checks, finding severity/field shape/content and batch-file binding, current file fingerprints, queue marker consistency, effort and journey-worker ledger completion/provenance fields including duplicate batch rows, `excluded_files.json` count/digest consistency, and policy-blocking unresolved scope warnings.
- `scripts/self_test.py`: fixture-based smoke tests for classification, interface detection, env/generated/vendor exclusion and opt-in behavior, batch invariants, and result verification.

The harness is the source of truth for batch coverage; the lead agent is responsible for validating that every manifest source file has a corresponding subagent coverage row before final synthesis.
