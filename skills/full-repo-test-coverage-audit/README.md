# Full Repo Test Coverage Audit Skill

`full-repo-test-coverage-audit` is a Codex skill for auditing whether a
repository has meaningful tests for its functions, methods, UI journeys,
intended features, UI elements, integration paths, and important edge or
failure cases. It produces a verified coverage record and a prioritized plan
for closing test gaps.

## Target

Use this skill when you want to check:

- Unit coverage for reasonable functions, methods, reducers, hooks, handlers,
  services, jobs, and validation logic.
- Scenario depth for happy paths, empty values, boundaries, invalid inputs,
  async behavior, permissions, persistence, and failure paths.
- UI and user-journey coverage through component, integration, e2e, visual, or
  safe test-mode workflows.
- Intended feature and UI element coverage, including handlers, state changes,
  persistence paths, permission paths, failure paths, and required assertions.
- Missing or weak tests without modifying the audited repository.

The audited repository is kept read-only. Generated audit artifacts should live
outside the audited repo by default.

## How To Use

From Codex, invoke:

```text
Use $full-repo-test-coverage-audit to audit this repo.
```

Or name a specific repository:

```text
Use $full-repo-test-coverage-audit to audit /path/to/repo.
```

The lead audit requires high effort or higher. File batches and UI/visual
coverage checks are handled by low-effort workers when available. If worker
spawning is unavailable, the skill may use disclosed manual fallback coverage.

## What It Produces

The harness creates an audit output directory containing:

- `manifest.json`: source files, coverage units, batches, hashes, and coverage
  invariants.
- `audit_index.md`: dispatch guide for the lead agent.
- `batch_###.md`: prompts for low-effort file-audit workers.
- `ui_test_coverage_audit.md`: UI and journey test coverage prompt when
  interface files exist.
- `visual_e2e_coverage_audit.md`: visual/e2e tooling prompt when interface
  files exist.
- `effort_ledger.json`: lead-recorded worker/effort/fallback ledger.
- `excluded_files.json`: skipped files and scope-warning reasons.
- `reports/`: required returned worker reports.
- `queue_complete.json`: queue-generation marker, not proof that verification
  is complete.

## Direct Harness Usage

Run harness self-tests:

```bash
python3 skills/full-repo-test-coverage-audit/scripts/self_test.py
```

Generate an audit queue:

```bash
python3 skills/full-repo-test-coverage-audit/scripts/build_test_coverage_audit_batches.py --repo /path/to/repo --out /tmp/full-repo-test-coverage-audit-run
```

Verify saved reports:

```bash
python3 skills/full-repo-test-coverage-audit/scripts/verify_test_coverage_audit_results.py --manifest /tmp/full-repo-test-coverage-audit-run/manifest.json --reports /tmp/full-repo-test-coverage-audit-run/reports
```

Useful builder options match the full repo audit harness: `--out`,
`--include-generated`, `--include-vendor`, `--include-env`, `--include-assets`,
`--include-file`, `--include-glob`, `--batch-size`, and
`--max-batch-bytes`.

## Coverage Rules

A run is complete only after:

1. Every generated batch prompt has a saved report in `reports/batch_###.md`.
2. UI and visual/e2e reports exist when interface-relevant files are queued.
3. `effort_ledger.json` records completed lead, worker, and fallback status.
4. `verify_test_coverage_audit_results.py` returns `ok: true`.

The verifier checks structure, hashes, report coverage, current source drift,
scope warnings, and ledger completion. It does not prove the semantic truth of
each test assessment; the lead agent remains responsible for validating
high-impact findings before final synthesis.
