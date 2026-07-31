# UI Implementation Audit Skill

`ui-implementation-audit` is a Codex skill for checking whether a repo's
implemented interface matches its mockups, visual assets, and user journey
requirements. It combines source-level UI batching with rendered desktop/mobile
visual checks and produces a prioritized implementation plan for missing UI,
interaction, implementation, and test gaps.

Rendered evidence is real and bound: `visual_evidence.json` records confined artifact paths, hashes, MIME, dimensions, route, state, viewport, capture tool, and formal-verifier JSON. UI action rows also bind handlers, backend/API, permissions, persistence, and tests through real `path#symbol` references or report them missing.

This skill has a hard applicability gate. At least one substantive, repo-owned
product screen, component, or native view must already exist in executable UI
source and be named with `--implemented-ui-file`. A partial implementation is
enough. Plans, requirements, mockups, prototypes, screenshots, stories, tests,
styles/assets, backend code, and untouched framework scaffolds are not. An
inapplicable run exits `3` and creates no audit artifacts.

The normal gate also requires a recognized executable UI surface with
substantive visible content or controls, so an arbitrary path, import, empty
view shell, or route/provider/root mount cannot qualify. For a real but
unrecognized UI toolkit, the exceptional
`--implemented-ui-override PATH UI-KIND SOURCE-ANCHOR` form records two
distinct exact source facts: an imported, inherited/conformed, or constructed
UI framework/view type and a named screen/component definition whose body uses
that type. The verifier rechecks the relationship. This is not a bypass for two
unrelated backend symbols, route scaffolding, or planned UI.

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

Do not use it to design or plan a UI that has not been implemented. Start UI
design or implementation first, then audit once a real target surface exists.

The audited repository is kept read-only. Generated audit artifacts should live
outside the audited repo by default.

## How To Use

From Codex, invoke:

```text
After confirming src/App.tsx implements a real product surface, use $ui-implementation-audit to audit this repo against its mockups and user journeys.
```

Or name a specific repository:

```text
After confirming app/views/contacts.html implements a real product surface, use $ui-implementation-audit to audit /path/to/repo.
```

You can force known design or requirement inputs:

```bash
python3 skills/ui-implementation-audit/scripts/build_ui_implementation_audit_batches.py \
  --repo /path/to/repo \
  --implemented-ui-file src/App.tsx \
  --mockup docs/mockups/dashboard.png \
  --journey-file docs/product-journeys.md
```

## What It Produces

The harness creates an audit output directory containing:

- `manifest.json`: UI source files, coverage units, visual assets, mockups,
  requirement sources, implementation-gate evidence, batches, hashes, and
  coverage invariants.
- `audit_index.md`: dispatch guide for the lead agent.
- `batch_###.md`: prompts for low-effort UI source workers.
- `mockup_asset_audit.md`: prompt for extracting expected UI from mockups,
  assets, and journey requirements.
- `visual_tooling_audit.md`: prompt for finding runnable screenshot paths.
- `visual_comparison_audit.md`: prompt for desktop/mobile screenshot
  comparison.
- `visual_evidence.json`: real screenshot/native/formal-verifier artifact records referenced as `evidence:<id>`.
- `effort_ledger.json`: lead-recorded worker/effort/fallback ledger.
- `excluded_files.json`: skipped files and scope-warning reasons.
- `reports/`: required returned worker reports.
- `logs/`: verbose command output kept outside routine model context.
- `final-report.md`: complete lead visual/source synthesis.
- `queue_complete.json`: queue-generation marker, not proof that verification
  is complete.

## Direct Harness Usage

Run harness self-tests:

```bash
python3 skills/ui-implementation-audit/scripts/self_test.py
```

Generate an audit queue:

```bash
python3 skills/ui-implementation-audit/scripts/build_ui_implementation_audit_batches.py \
  --repo /path/to/repo \
  --implemented-ui-file src/App.tsx \
  --out /tmp/ui-implementation-audit-run
```

Check eligibility without creating artifacts:

```bash
python3 skills/ui-implementation-audit/scripts/build_ui_implementation_audit_batches.py \
  --repo /path/to/repo \
  --implemented-ui-file src/App.tsx \
  --eligibility-only
```

Exceptional preflight for an unrecognized toolkit, after manual inspection:

```bash
python3 skills/ui-implementation-audit/scripts/build_ui_implementation_audit_batches.py \
  --repo /path/to/repo \
  --implemented-ui-override src/contacts.rs 'canvas_kit::ContactSurface' build_contacts \
  --eligibility-only
```

Verify saved reports:

```bash
python3 skills/ui-implementation-audit/scripts/verify_ui_implementation_audit_results.py --manifest /tmp/ui-implementation-audit-run/manifest.json --reports /tmp/ui-implementation-audit-run/reports
```

Useful builder options include `--out`, `--mockup`, `--journey-file`,
`--include-generated`, `--include-vendor`, `--include-env`, `--include-file`,
`--include-glob`, `--implemented-ui-file`, `--implemented-ui-override`,
`--eligibility-only`, `--batch-size`, and `--max-batch-bytes`.

## Coverage Rules

A run is complete only after:

1. The manifest contains a passed, hash-bound implemented-UI gate.
2. Every generated source batch has a saved report in `reports/batch_###.md`.
3. Mockup/assets, visual tooling, and visual comparison reports exist.
4. `effort_ledger.json` records completed lead, worker, and fallback status.
5. `verify_ui_implementation_audit_results.py` returns `ok: true`.

The verifier checks structure, hashes, report coverage, current source drift,
scope warnings, visual comparison evidence shape, first-viewport journey
coverage, and ledger completion. It cannot prove the semantic truth of each
visual judgment; the lead agent remains responsible for reviewing screenshot
evidence before final synthesis.

Codex workers use `fork_turns="none"` and Light/runtime `low` effort; another
runtime uses the equivalent fresh worker context or disclosed manual fallback
when runtime `low` is unavailable. Workers write complete reports directly to
their declared artifact paths and return only compact filename/hash/byte/count
receipts. The final chat response is a short outcome, counts, caveats, verifier
status, and artifact index.
