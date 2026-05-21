# Full Repo Audit Skill

`full-repo-audit` is a Codex skill for auditing an entire repository against the
complete intended product: user journeys, feature set, UI elements,
implementation paths, tests, architecture, and quality. It produces a verified
coverage record and a prioritized implementation plan.

## Target

Use this skill when you want a repository-wide audit that checks:

- Architecture and product-flow risks.
- Every queued source file, manually reviewed in deterministic batches.
- Intended journeys, features, routes, controls, states, handlers, persistence
  paths, permissions, and tests that should exist.
- UI controls, messages, routes, forms, menu items, and visible copy that imply missing or incorrect behavior.
- User journeys through the UI, including multi-journey relevance, route priority, decision-making information, information hierarchy, compact desktop/native/mobile fit, UI assumption status, rare/detail/debug content risk, readability, and test-mode availability.
- Visual journey testability when the repo has a rendered UI or visual tooling.
- TODO, stub, placeholder, console-only, mocked-as-real, dead-ended, or partially implemented behavior.

The audited repository is kept read-only. The skill may write audit artifacts, but those should normally live outside the audited repo.

## How To Use

From Codex, invoke:

```text
Use $full-repo-audit to audit this repo.
```

Or name a specific repository:

```text
Use $full-repo-audit to audit /path/to/repo.
```

The skill requires an extra-high-effort lead audit. File batches and journey checks are handled by low-effort workers when the runtime supports subagents. If worker spawning is not available, the skill may use disclosed manual fallback coverage, but the lead x-high requirement is not waived.

## What It Produces

The harness creates an audit output directory containing:

- `manifest.json`: source files, coverage units, batches, hashes, interface files, and coverage invariants.
- `audit_index.md`: dispatch guide for the lead agent.
- `batch_###.md`: prompts for low-effort file-audit workers.
- `journey_audit.md`: source-level user-journey worker prompt when interface files exist.
- `visual_journey_audit.md`: visual journey worker prompt when interface files exist.
- `effort_ledger.json`: lead-recorded worker/effort/fallback ledger.
- `excluded_files.json`: skipped files and scope-warning reasons.
- `reports/`: required returned worker reports.
- `queue_complete.json`: queue-generation marker, not proof that the audit is finished.

The final response from the skill should include coverage, architecture findings,
interface findings, user journey findings, feature and test completeness
findings, file-level findings, an implementation plan, and a verification plan.
If no explicit user journeys exist, the audit should ask for confirmation or
label UI/journey coverage as assumption-based rather than claiming the interface
is user-friendly.

## Direct Harness Usage

The skill is normally run through Codex, but the bundled scripts can be used directly.

Run harness self-tests:

```bash
cd /path/to/full-repo-audit
python3 scripts/self_test.py
```

Generate an audit queue:

```bash
cd /path/to/full-repo-audit
python3 scripts/build_audit_batches.py --repo /path/to/repo --out /tmp/full-repo-audit-run
```

Verify saved reports:

```bash
cd /path/to/full-repo-audit
python3 scripts/verify_audit_results.py --manifest /tmp/full-repo-audit-run/manifest.json --reports /tmp/full-repo-audit-run/reports
```

When working from a repository that vendors this skill under `skills/full-repo-audit`, replace `scripts/...` above with `skills/full-repo-audit/scripts/...`.

Useful builder options:

- `--out <dir>`: write artifacts to a specific harness-owned directory.
- `--include-generated`: include generated/build directories.
- `--include-vendor`: include vendor/dependency directories.
- `--include-env`: include real `.env` files intentionally.
- `--include-assets`: include binary UI assets such as logos, screenshots, and fonts.
- `--include-file <repo-relative-path>`: force a specific file into coverage.
- `--include-glob <glob>`: force matching files into coverage.
- `--batch-size <n>`: limit files per batch.
- `--max-batch-bytes <n>`: split large files into line or byte range units.

## Coverage Rules

Do not treat queue generation as audit completion. A run is complete only after:

1. Every generated batch prompt has a saved report in `reports/batch_###.md`.
2. Required journey reports exist when interface-relevant files are queued.
3. `effort_ledger.json` records completed lead, worker, journey, and fallback status.
4. `verify_audit_results.py` returns `ok: true`.

If a run is interrupted, trust the manifest and verifier over stale ledger notes. Rerun missing batch or journey prompts, save the exact report filenames, update the ledger, and verify again.

## Notes

`SKILL.md` is the authoritative operational contract. This README is a shorter orientation guide for humans who want to understand the skill and its bundled harness quickly.
