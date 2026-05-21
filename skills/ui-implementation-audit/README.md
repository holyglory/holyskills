# UI Implementation Audit Skill

`ui-implementation-audit` is a Codex skill for checking whether a repo's
implemented interface matches its mockups, visual assets, and user journey
requirements. It combines source-level UI batching with rendered desktop/mobile
visual checks and produces a prioritized implementation plan for missing UI,
interaction, implementation, and test gaps.

## Target

Use this skill when you want to audit:

- UI code against generated mockups, screenshots, Figma/ImageGen exports, brand
  assets, and product journey requirements.
- Required screens, controls, messages, states, handlers, data paths,
  accessibility paths, and visual/test evidence.
- Desktop, native, and mobile screenshots against expected visual hierarchy,
  density, spacing, imagery, states, readability, overload risk, and responsive
  fit.
- Rendered journey usability: visible content must help the user make the
  current journey decision, not merely avoid overflow or resemble the mockup.
- Interface source files that define pages, screens, components, templates,
  styles, visible copy, native UI markup, and UI message catalogs.
- Missing visual tooling or safe fixture paths that prevent real screenshot
  verification.

The audited repository is kept read-only. Generated audit artifacts should live
outside the audited repo by default.

## How To Use

From Codex, invoke:

```text
Use $ui-implementation-audit to audit this repo against its mockups and user journeys.
```

Or name a specific repository:

```text
Use $ui-implementation-audit to audit /path/to/repo.
```

You can force known design or requirement inputs:

```bash
python3 skills/ui-implementation-audit/scripts/build_ui_implementation_audit_batches.py \
  --repo /path/to/repo \
  --mockup docs/mockups/dashboard.png \
  --journey-file docs/product-journeys.md
```

## What It Produces

The harness creates an audit output directory containing:

- `manifest.json`: UI source files, coverage units, visual assets, mockups,
  requirement sources, batches, hashes, and coverage invariants.
- `audit_index.md`: dispatch guide for the lead agent.
- `batch_###.md`: prompts for low-effort UI source workers.
- `mockup_asset_audit.md`: prompt for extracting expected UI from mockups,
  assets, and journey requirements.
- `visual_tooling_audit.md`: prompt for finding runnable screenshot paths.
- `visual_comparison_audit.md`: prompt for desktop/mobile screenshot
  comparison.
- `effort_ledger.json`: lead-recorded worker/effort/fallback ledger.
- `excluded_files.json`: skipped files and scope-warning reasons.
- `reports/`: required returned worker reports.
- `queue_complete.json`: queue-generation marker, not proof that verification
  is complete.

## Direct Harness Usage

Run harness self-tests:

```bash
python3 skills/ui-implementation-audit/scripts/self_test.py
```

Generate an audit queue:

```bash
python3 skills/ui-implementation-audit/scripts/build_ui_implementation_audit_batches.py --repo /path/to/repo --out /tmp/ui-implementation-audit-run
```

Verify saved reports:

```bash
python3 skills/ui-implementation-audit/scripts/verify_ui_implementation_audit_results.py --manifest /tmp/ui-implementation-audit-run/manifest.json --reports /tmp/ui-implementation-audit-run/reports
```

Useful builder options include `--out`, `--mockup`, `--journey-file`,
`--include-generated`, `--include-vendor`, `--include-env`, `--include-file`,
`--include-glob`, `--batch-size`, and `--max-batch-bytes`.

## Coverage Rules

A run is complete only after:

1. Every generated source batch has a saved report in `reports/batch_###.md`.
2. Mockup/assets, visual tooling, and visual comparison reports exist when UI
   source files are queued.
3. `effort_ledger.json` records completed lead, worker, and fallback status.
4. `verify_ui_implementation_audit_results.py` returns `ok: true`.

The verifier checks structure, hashes, report coverage, current source drift,
scope warnings, visual comparison evidence shape, first-viewport journey
coverage, and ledger completion. It cannot prove the semantic truth of each
visual judgment; the lead agent remains responsible for reviewing screenshot
evidence before final synthesis.
