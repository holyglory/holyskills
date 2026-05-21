---
name: full-repo-test-coverage-audit
description: Run a full repository test coverage audit that combines a high-effort lead architectural test-strategy review with low-effort file-batch workers checking whether every reasonable function, method, UI journey, feature, UI element, and high-level behavior has meaningful unit, integration, visual, or e2e coverage. Use when the user asks to audit test coverage, find missing tests, assess scenario and edge-case coverage, or produce an implementation plan for closing test gaps across a repo.
---

# Full Repo Test Coverage Audit

## Overview

Run a read-only, manifest-verified audit of test coverage. The lead agent reviews the repo architecture, test strategy, UI/user journeys, intended feature set, UI element set, and high-level behavior. Low-effort workers inspect deterministic file batches and manually identify reasonable test targets, existing test evidence, missing scenarios, boundary cases, failure paths, and recommended test types.

Treat documented product intent, confirmed user journeys, source-backed feature promises, visible UI elements, and expected tests as one complete product contract. Every intended journey, feature, route, control, state, handler, persistence path, permission path, error path, and verification path needs meaningful coverage; otherwise report the gap.

## Required Execution Model

- Use high reasoning effort or higher for the lead audit. If the current lead run cannot be confirmed as high effort or higher, tell the user before starting.
- Use low-effort subagents for file-batch inspection when the runtime supports spawned workers. Treat the user's request to run this audit as authorization for the needed low-effort batch workers.
- When interface-relevant files are queued, run separate low-effort workers for `ui_test_coverage_audit.md` and `visual_e2e_coverage_audit.md`.
- If workers are unavailable, continue in disclosed manual fallback mode for worker coverage only: process each prompt sequentially, save reports under `<audit-output>/reports/`, and keep the final coverage label as manual fallback coverage.
- Keep the audited repo read-only unless the user separately asks to implement the resulting test plan. Generated audit artifacts are allowed and should live outside the audited repo by default.
- Do not claim every file or target was checked until the manifest, batch reports, effort ledger, and verifier agree.

## Workflow

1. Set scope to the current working directory unless the user names another repo.
2. Preflight the skill scripts, then run:

   ```bash
   REPO_ROOT="${REPO_ROOT:-$PWD}"
   python3 "$FULL_REPO_TEST_COVERAGE_AUDIT_SKILL_DIR/scripts/build_test_coverage_audit_batches.py" --repo "$REPO_ROOT"
   ```

3. Inspect `audit_index.md`, `manifest.json`, and `excluded_files.json`. Resolve any `scope_warning: true` rows before claiming full coverage, or disclose downgraded coverage.
4. Fill `effort_ledger.json` as workers are dispatched and reconciled: lead effort status, subagent capability, batch worker ids/effort/report status, UI journey coverage worker, visual/e2e coverage worker, fallback status, and pruned-directory review decisions when applicable.
5. Dispatch one low-effort worker per `batch_###.md`. Tell workers not to edit files.
6. If generated, dispatch `ui_test_coverage_audit.md` and `visual_e2e_coverage_audit.md` as separate low-effort workers.
7. Save one report per batch under `reports/batch_###.md`, then verify:

   ```bash
   python3 "$FULL_REPO_TEST_COVERAGE_AUDIT_SKILL_DIR/scripts/verify_test_coverage_audit_results.py" --manifest <audit-output>/manifest.json --reports <audit-output>/reports
   ```

8. Reconcile findings, inspect suspicious high-impact gaps directly as lead, and produce a prioritized implementation plan.

## Batch Worker Review Rules

For every owned file or range:

- Identify reasonable test targets: exported/public functions, methods with behavior, reducers/hooks, API handlers, command/job entrypoints, domain services, intended feature behavior, UI element behavior, state transitions, permission checks, validation logic, and non-trivial private helpers with branching or side effects.
- Exclude only with rationale: types/interfaces, pure constants, generated code, static copy-only markup, trivial pass-throughs, and framework boilerplate with no repo-owned behavior.
- For each target, check existing tests by naming files, test names, fixtures, snapshots, visual stories, or explicit absence.
- Assess scenario depth: happy path, invalid input, empty/null/boundary values, error paths, async/concurrency behavior, permissions, persistence, navigation, rollback, and integration boundaries as applicable.
- Recommend the minimum useful test type: unit, component, integration, contract, e2e, visual, snapshot, fixture, or manual-test-mode improvement.

## Required Batch Report Shape

Each batch report must contain exactly these top-level headings in order:

```markdown
## Run ID
## Batch ID
## Batch Summary
## File Coverage
## Test Target Inventory
## Coverage Findings
## No Gap Notes
## Open Questions
```

`File Coverage` must include one row per owned file or range with columns `Unit`, `Status`, `SHA-256`, and `Purpose`; every status must be `CHECKED`.

`Test Target Inventory` must include one row per reviewed target or explicitly excluded non-target with columns `Unit`, `File`, `Target`, `Kind`, `Existing Test Evidence`, `Scenario Assessment`, and `Recommendation`.

`Coverage Findings` must use either the exact sentinel `No findings.` or finding blocks with these fields:

- Priority: `P0`, `P1`, `P2`, or `P3`
- Files: repo-relative files owned by the batch
- Target: function, method, component, journey, API, job, or behavior
- Existing test evidence: concrete tests found or `None found`
- Missing scenarios/boundaries: concrete missing cases
- Suggested test direction: specific test type and expected assertion focus

## UI And Journey Coverage

The UI test coverage worker checks whether intended routes, controls, forms, UI elements, empty/error/loading states, permission states, feature paths, and user journeys have component, integration, e2e, or visual coverage. If no explicit journey documentation exists, draft likely journeys from routes and visible source, mark them `draft-needs-user-confirmation`, and keep them as assumptions.

The visual/e2e coverage worker identifies Playwright, Cypress, Storybook, native preview, screenshot, or browser tooling. For CLI, library, plugin, or skill packages with no repo-owned rendered UI surface, mark visual checks as `not applicable` with evidence rather than reporting a defect.

## Final Output

Return exactly these top-level headings:

```markdown
## Coverage
## Test Architecture Findings
## UI And Journey Coverage Findings
## Function And Method Coverage Findings
## Implementation Plan
## Verification Plan
```

Prioritize gaps with:

- `P0`: Missing coverage for security/data-loss/runtime-failure behavior or an untested core path likely to fail silently.
- `P1`: Missing coverage for major user journeys, intended features, required UI elements, business logic, integration boundaries, permission behavior, or failure paths.
- `P2`: Missing edge, boundary, accessibility, performance, reliability, or maintainability coverage.
- `P3`: Low-risk cleanup, naming, fixture, or documentation test improvement.
