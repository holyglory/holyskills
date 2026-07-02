---
name: full-repo-audit
description: Run a full repository source-code, interface, and user-journey audit that combines an extra-high-effort lead architectural review with low-effort subagent batches that manually inspect every queued source file plus separate journey and visual UI workers. Use when the user asks to audit a repo for incomplete or partial features, TODO/stub behavior, industry-standard gaps, user-expectation gaps, architectural risk, UI controls or messages that imply unimplemented behavior, unclear user journeys, missing implementation or tests for the intended feature set, visual/test-mode gaps, UI assumption status, or to produce a prioritized implementation plan from repository-wide findings.
---

# Full Repo Audit

## Overview

Run a multi-level audit: the lead agent performs the architectural, product-flow, and interface review; low-effort subagents manually inspect every source file in deterministic batches; separate UI journey workers inspect source-level journeys and visual testability. Use the harness script to create a coverage manifest and worker prompts, then reconcile all results before producing the final implementation plan.

Treat documented product intent, confirmed user journeys, source-backed feature promises, visible UI elements, and expected tests as one complete product contract. Every intended journey, feature, route, control, state, handler, persistence path, permission path, error path, and verification path must be present, implemented, and tested; otherwise report the gap.
Hard reporting gate for UI-bearing repos: the final audit must contain the
literal checklist labels `badge-detail`, `row-hit-target`,
`navigation-cursor`, `transient-disclosure`, `disclosure-scrollbar`,
`icon-meaning`, `stable-expansion-width`, `hover-copy`, `status-summary`, and
`message-metadata` in `## Interface Findings`, `## User Journey Findings`, or
`## File-Level Findings`. Mark each `pass`, `gap`, `blocked`, or `not
applicable` with evidence. If any label is absent, rewrite the final report
before returning it.
Do not let source-inferred UI structure, audit-generated documentation, or an
over-prescriptive handoff doc become confirmed product truth. When a UI-heavy
repo has unclear journeys or screenshots show overloaded/default-detail-heavy
surfaces, report the UI assumption status as `source-inferred` or `missing` and
escalate to screenshot-based visual review or `ui-implementation-audit`.

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
   - Identify intended product surfaces, feature families, UI elements, user journeys, and test expectations before reading subagent findings.
   - Look for cross-cutting risks: missing integration paths, incomplete intended features, inconsistent state models, auth/permission drift, data migration gaps, error handling, observability, accessibility, security, performance, reliability, and test strategy.
   - Build an interface inventory from routes, pages, components, templates, command palettes, menus, forms, message catalogs, and visible copy.
   - Trace important controls and messages to handlers, state transitions, API calls, persistence, navigation, permission checks, and error/loading/empty states.
   - Find the repo's clear user journey description(s). Treat journey discovery as the basis for UI relevance, not as a documentation-only check. If missing, draft the most reasonable frequent journeys from app intent, routes, visible copy, and code, mark them as `draft-needs-user-confirmation`, and ask the user to confirm the most frequent use cases before treating them as final. If the audit must continue without user input, downgrade UI/user-journey coverage to `journey assumptions unconfirmed`, carry the drafts as open questions and implementation-plan assumptions, and do not state that the interface is user-friendly or convert source-inferred layout into product truth.
   - Audit all confirmed and drafted journeys, not only the single most obvious happy path. For each journey, identify the target user, goal, entry point, primary route sequence, critical decision points, rare/occasional details, destructive or heavy actions, and success/failure end states.
   - For each screen or step in each journey, compare what the user currently sees against the journey decision model: primary decision, required facts, warning/flag conditions, frequent actions, secondary/rare actions, information importance, access expectations, and unconfirmed assumptions. Do not invent a final layout from source hints alone.
   - If docs or earlier audits require many always-visible fields but do not
     explain why they are default decision content, treat that as an
     over-prescribed UI assumption. Do not preserve the overloaded layout as a
     requirement; require confirmation or a disclosure model.
   - Check compactness, fit, and layout discipline on desktop, native, and narrow/mobile surfaces: critical-always and primary-frequent information should remain usable without accidental horizontal scroll, overlap, cropping, unreadable compression, hidden overflow with no scroll path, nested visual frames, inconsistent gutters, unstable disclosure controls, or low-relevance content dominating the decision path.
   - Check interaction affordances and metadata relevance: decision badges and flags should expose hover/focus/click feedback and useful detail access when interactive; meaningful rows should not require a tiny icon-only target; elements that navigate to another screen, row, dialog, or detail surface should expose a predictable destination and pointer/focus affordance; temporary popovers and expanded panels should have an intentional close or timeout lifecycle; expand/collapse controls should not fight scrollbars; expanded and collapsed tool/result blocks should keep stable widths; copy controls should be hover/focus revealed only when they would otherwise clutter message reading and must remain reachable; concise status blocks should avoid duplicate status/severity/duration noise; unclear icons, noisy author/routing labels, selectable passive timestamps, and over-visible metadata should be treated as journey-usability defects.
   - For every UI surface that contains badges, flags, expandable rows, scrollable details, message streams, tool/result blocks, or icon-only controls, explicitly record an interaction checklist status for: `badge-detail`, `row-hit-target`, `navigation-cursor`, `transient-disclosure`, `disclosure-scrollbar`, `icon-meaning`, `stable-expansion-width`, `hover-copy`, `status-summary`, and `message-metadata`. Mark each `pass`, `gap`, `blocked`, or `not applicable`; any `gap`/`blocked` item needs a finding rather than being folded into a generic layout note.

4. **Dispatch low-effort workers**
   - Open the generated `audit_index.md`.
   - For each `batch_###.md`, spawn one low-effort subagent and pass the entire prompt file content.
   - When generated, spawn a separate low-effort source journey worker with `journey_audit.md`. This worker checks journey documentation, drafts missing journeys, estimates UI element relevance, and traces navigation/decision information through UI source.
   - When generated, spawn a separate visual journey worker with `visual_journey_audit.md`. If the repo is UI-heavy or screenshots are available, the lead must review the visual findings directly or rerun the dedicated `ui-implementation-audit`; do not let low-effort visual notes be the only basis for declaring a UI usable.
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
   - For large repos, first consolidate findings mechanically instead of merging
     hundreds of reports by hand:
     ```bash
     python3 "$FULL_REPO_AUDIT_SKILL_DIR/scripts/_vendor/full_repo_harness/merge_findings.py" \
       --reports <audit-output>/reports \
       --markdown-out <audit-output>/consolidated-findings.md \
       --json-out <audit-output>/consolidated-findings.json
     ```
     This deduplicates findings that share a primary file and summary, ranks them
     P0→P3, and records which reports raised each one. Use it as the starting
     point for the lead synthesis; it does not replace lead judgment.
   - Deduplicate batch findings.
   - Separate confirmed issues from hypotheses and open questions.
   - Prioritize by user impact, correctness, security/reliability, blast radius, and implementation dependency order.
   - Produce an implementation plan with concrete verification steps that reproduce or demonstrate each gap across the intended product contract.

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

Require the journey source worker to return `Run ID`, `Worker`, `Journey Sources`, `Proposed Journeys`, `UI Source Journey Checks`, `Findings`, and `Open Questions`. Require `UI Source Journey Checks` to cover every confirmed and drafted journey and to compare current UI hierarchy against journey-derived relevance: critical information, primary navigation, secondary information, rare/detail/debug content, interaction target expectations, message metadata relevance, UI assumption status, and desktop/native/mobile fit. Require the visual journey worker to return `Run ID`, `Worker`, `Visual Tooling`, `Visual Journey Checks`, `Findings`, and `Open Questions`. Journey and visual workers must include the interaction checklist labels `badge-detail`, `row-hit-target`, `navigation-cursor`, `transient-disclosure`, `disclosure-scrollbar`, `icon-meaning`, `stable-expansion-width`, `hover-copy`, `status-summary`, and `message-metadata` in `UI Source Journey Checks`, `Visual Journey Checks`, or the first line of `Findings`; any `gap`/`blocked` status must have a finding. Their `Findings` sections must use the same field schema as batch findings (`Files`, `Evidence`, `Interface evidence`, `Expected behavior/standard`, `Gap`, `Suggested direction`) or the exact clean sentinel `No findings.` If no explicit journey documentation exists, the journey source report must include draft journeys marked `draft-needs-user-confirmation`, and the final audit must either ask the user to confirm them or label UI/journey coverage as assumption-based.

## Final Audit Output

Return a concise but complete plan with exactly these top-level Markdown headings, in this order:

## Coverage
Repo root, audit output path, run id, source files queued, coverage units queued, files or units checked by subagents or manual fallback, files rechecked by the lead, journey workers run, scope warnings, exclusions, unchecked files or units, verifier result, subagent capability check result, ledger-recorded lead effort status, and per-batch/journey effort/fallback ledger.

## Architecture Findings
Repo-wide design, feature-completeness, and product-flow gaps from the lead pass, or `No confirmed findings.`

## Interface Findings
Buttons, menu items, links, form fields, messages, command items, empty states, toasts, or labels that point to missing, unimplemented, partial, untested, misleading, wrongly wired, wrongly prioritized, or journey-mismatched behavior, or `No confirmed findings.`

## User Journey Findings
Missing or unclear journeys, explicit UI assumption status (`confirmed`, `source-inferred`, or `missing`), unconfirmed drafted journeys, navigation relevance problems, information hierarchy mismatches, missing decision information, overexposed rare/detail/debug content, hidden critical information, desktop/native/mobile compactness or visibility/cropping/readability issues, missing test mode, unavailable visual test tooling, or `No confirmed findings.`

## File-Level Findings
Confirmed issues from batch results, deduplicated and grouped by feature area, or `No confirmed findings.`

## Implementation Plan
Ordered work items with expected behavior, affected files or modules, implementation steps, tests, and risk for completing the intended product contract. Use `No implementation work recommended from this audit.` when clean.

## Verification Plan
Commands, browser/API checks, fixtures, or user workflows needed to prove each improvement. Include the exact verifier command and any commands already run.

Use this priority scale:

- `P0`: Security/data-loss/runtime failure or feature unusable for core workflows.
- `P1`: Major user expectation gap, partial feature, broken integration path, or standards gap likely to affect real use.
- `P2`: Important quality, maintainability, accessibility, performance, or test gap.
- `P3`: Polish, documentation, cleanup, or low-risk consistency improvement.

## Interface Audit Requirements

During both lead and subagent review, inspect UI implementation as a source of product promises and as a journey-specific information hierarchy. Inventory visible controls and copy, then check whether the code actually implements what a user would expect and whether the interface shows the right things at the right priority for each user journey.

Look for:

- Buttons, icon buttons, menu items, tabs, command palette items, links, and keyboard shortcuts with missing handlers, placeholder handlers, TODO handlers, console-only handlers, disabled dead ends, or handlers that do not persist/navigate/refresh.
- Text fields, filters, selectors, toggles, uploads, settings, and forms whose values are ignored, only locally mocked, not validated, not saved, or not reflected in UI/API behavior.
- Toasts, banners, empty states, tooltips, helper text, onboarding copy, success/error messages, and labels that promise capabilities not implemented in code.
- UI states that are missing or misleading: loading, empty, error, permission denied, offline, undo/redo, destructive confirmation, optimistic update rollback, or background job progress.
- Navigation surfaces that expose unavailable routes, hidden admin-only paths without permission handling, orphaned pages, or pages not linked from expected menus.
- Accessibility and interaction gaps that make an implemented feature behave as partially implemented: unlabeled controls, keyboard traps, focus loss, non-semantic buttons/links, or state conveyed only visually.
- Journey relevance gaps: most-probable routes hidden behind lower-probability routes, critical-always information buried under low-value content, primary actions displaced by rare actions, rare/detail/debug content permanently consuming prime screen space without journey rationale, lower-importance information lacking a clear access model, or source-inferred UI assumptions treated as confirmed product truth.
- Visual hierarchy gaps: cards or blocks nested inside other cards, repeated borders/background changes, inconsistent gutters, random-looking placement, disclosure controls that jump or change width, permanent obvious instructions, meaningless icons, decorative avatar clutter, hover affordances that clutter by default or vanish before they can be reached, or inconsistent message alignment that makes the journey harder to scan.
- Handoff conflicts: source-inferred or audit-generated UI assumptions, over-prescribed always-visible detail, duplicate severity/status/duration summaries, vague labels, source-model leakage, missing navigation destination/cursor rules, missing transient disclosure lifecycle, or detail controls dominating the default state.
- Compactness and responsive-fit gaps: desktop, native, or mobile screens where critical journey information does not fit, accidental horizontal scrolling, cropped/truncated decision data, overlapping content, hidden overflow without a scroll path, unreadable contrast, invisible theme text, large decorative or low-relevance areas that displace primary workflow content, or controls whose labels/states do not fit their containers.

For each interface finding, capture the visible label or message text, the journey(s) affected, the file that defines it, the expected implementation path, the actual implementation path, the current visible priority, the expected priority, and the missing, wrong, hidden, or overexposed behavior.

## User Journey Audit Requirements

Audit whether the repo clearly describes the most important user journey(s) through the UI. Accept journey docs, route maps, onboarding specs, product docs, tests, Storybook stories, analytics notes, support/common-task docs, or source-backed route/component flows. If none exist, draft likely journeys from the app intent and visible code, ask the user to confirm the most frequent use cases, and keep unconfirmed journeys as assumptions/open questions. Relevance is journey-relative: the same UI element can be critical for one journey and rare for another, so audit every confirmed or drafted journey independently before synthesizing cross-journey priorities.

During the source journey pass, check:

- Primary navigation and decision elements are visible, reachable, and visually prominent relative to less relevant elements. Estimate relevance as `critical-always`, `primary-frequent`, `secondary-occasional`, or `rare-under-5-percent`.
- Users have enough information on each screen, on desktop, native, and mobile surfaces, to make the documented journey decision. Rare or conditional information should remain reachable through an appropriate detail path; warning/threshold information must be available at the decision point.
- Important information is not cropped, hidden behind accidental overflow, unreadable, or displaced by lower-relevance content. Dense screens should mean compact decision support, not always-visible raw/detail/debug material or visual frame stacks.
- Most probable navigation routes for the journey are first, easiest, or most prominent; less probable routes are secondary, grouped, menued, or lower in the layout.
- Rarely needed detail has an appropriate access path when screen space is tight; critical or warning detail is never hidden from the decision point.
- Critical journey information and primary actions fit on desktop, native, and mobile surfaces without overlap, accidental horizontal scrolling, unreadable compression, low contrast, invisible theme text, or being buried under decorative or low-relevance content.
- Heavy or side-effecting UI actions can be exercised in a test mode, fixture mode, mock data mode, dry run, preview mode, or other safe visual path.

During the visual journey pass, use available visual tooling such as Playwright, Cypress, Storybook, browser MCP tools, native UI preview tools, or screenshots. Prefer test mode; use production mode only when the user explicitly requested it or the journey has no heavy/side-effecting operations. Check desktop, native, and narrow mobile viewports for journey completion, real navigation rather than abstracted mocks, visible decision information, route priority, information hierarchy, rendered journey usefulness, theme consistency, readable font sizes, sufficient color contrast, non-cropped/non-truncated content, scroll paths for overflow, unnecessary horizontal scrolling, nested visual frames, grid/alignment discipline, stable disclosure controls, icon meaning, instruction noise, and message alignment. When visual checks are applicable, include the command/tool used and screenshot, trace, recording, or other artifact evidence in the report. For CLI, library, plugin, or skill packages that expose only metadata/Markdown and no repo-owned rendered UI surface, mark visual checks as `not applicable` with evidence instead of treating host-owned rendering as a repo defect.

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
