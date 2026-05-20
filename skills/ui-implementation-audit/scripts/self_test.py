#!/usr/bin/env python3
"""Fixture-based smoke tests for the UI implementation audit harness."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "scripts" / "build_ui_implementation_audit_batches.py"
VERIFY = ROOT / "scripts" / "verify_ui_implementation_audit_results.py"
TIMEOUT_SECONDS = int(os.environ.get("UI_IMPLEMENTATION_AUDIT_SELF_TEST_TIMEOUT", "30"))
KEEP_TEMP_ON_FAILURE = os.environ.get("UI_IMPLEMENTATION_AUDIT_SELF_TEST_KEEP_TEMP", "").lower() in {"1", "true", "yes", "on"}
PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6360000002000100ffff03000006000557bfab9d00000000"
    "49454e44ae426082"
)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def run(args: list[str], *, expect: int = 0) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            args,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        raise AssertionError(
            f"Command timed out after {TIMEOUT_SECONDS}s: {' '.join(args)}\nstdout:\n{stdout}\nstderr:\n{stderr}"
        ) from exc
    if result.returncode != expect:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise AssertionError(f"Expected exit {expect}, got {result.returncode}: {' '.join(args)}")
    return result


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def make_ui_fixture(root: Path) -> None:
    write(
        root / "package.json",
        """{
  "scripts": {
    "dev": "vite --host 127.0.0.1",
    "test:visual": "playwright test"
  },
  "dependencies": {
    "@vitejs/plugin-react": "latest",
    "vite": "latest",
    "react": "latest",
    "react-dom": "latest"
  },
  "devDependencies": {
    "@playwright/test": "latest"
  }
}
""",
    )
    write(
        root / "src" / "App.tsx",
        """export function Dashboard() {
  return (
    <main className="dashboard-shell">
      <nav aria-label="Primary navigation">
        <a href="/reports">Reports</a>
        <a href="/settings">Settings</a>
      </nav>
      <section className="hero">
        <h1>Operations Dashboard</h1>
        <p>Review urgent incidents before routine archive details.</p>
        <button type="button">Resolve incident</button>
      </section>
      <aside className="rare-detail">Audit archive exported monthly.</aside>
    </main>
  );
}
""",
    )
    write(
        root / "src" / "styles.css",
        """.dashboard-shell {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 20rem;
  gap: 16px;
}

.hero {
  padding: 24px;
}
""",
    )
    write(
        root / "docs" / "journeys.md",
        """# Dashboard User Journey

Target user: operations lead.
Goal: review urgent incidents and resolve the highest priority item first.
Screen sequence: dashboard -> incident details -> resolution confirmation.
Primary action: Resolve incident.
Responsive requirement: mobile must show the active incident summary and action before archive detail.
Acceptance criteria: desktop and mobile screenshots match the dashboard mockup hierarchy.
""",
    )
    write_bytes(root / "design" / "mockups" / "dashboard-mobile.png", PNG_1X1)
    write_bytes(root / "public" / "logo.png", PNG_1X1)


def make_currency_rates_fixture(root: Path) -> None:
    write(root / "package.json", '{"scripts":{"dev":"vite --host 127.0.0.1","test:visual":"playwright test"},"dependencies":{"vite":"latest","react":"latest","react-dom":"latest"},"devDependencies":{"@playwright/test":"latest"}}\n')
    write(
        root / "src" / "CurrencyRatesPage.tsx",
        """export function CurrencyRatesPage() {
  return (
    <main className="rates-page">
      <section className="target-settings" aria-label="Target currency settings">
        <h1>Currency Rates</h1>
        <label>
          Target Currency
          <select defaultValue="USD"><option>USD</option><option>EUR</option></select>
        </label>
        <button type="button">Apply settings</button>
      </section>
      <section className="most-used-rates" aria-label="Most-used live currency rates">
        <h2>Most-used rates</h2>
        <article>EUR/USD 1.08</article>
        <article>GBP/USD 1.27</article>
      </section>
    </main>
  );
}
""",
    )
    write(
        root / "src" / "rates.css",
        """.rates-page {
  display: grid;
  gap: 16px;
}

@media (max-width: 600px) {
  .target-settings {
    min-height: 82vh;
    order: 1;
  }

  .most-used-rates {
    order: 2;
  }
}
""",
    )
    write(
        root / "docs" / "currency-rates-journey.md",
        """# Currency Rates Journey

Primary user goal: quickly decide current exchange rates for the currencies used most often.
Primary information: the most-used live rates list.
Frequent action: inspect a rate and continue cost tracking.
Occasional control: adjust target currency.
Rare control: advanced target/settings configuration.
Expected mobile order: most-used live rates first, target currency/settings after the decision content.
""",
    )
    write_bytes(root / "design" / "mockups" / "currency-rates-mobile.png", PNG_1X1)


def make_cli_fixture(root: Path) -> None:
    write(root / "README.md", "# CLI fixture\n\nNo rendered UI surface.\n")
    write(root / "src" / "tool.py", "def main():\n    return 1\n")


def build(repo: Path, out: Path, *extra: str) -> dict:
    run([sys.executable, str(BUILD), "--repo", str(repo), "--out", str(out), "--run-id", "selftest-run", *extra])
    return json.loads((out / "manifest.json").read_text(encoding="utf-8"))


def verify(out: Path, *, expect: int = 0) -> subprocess.CompletedProcess[str]:
    return run([sys.executable, str(VERIFY), "--manifest", str(out / "manifest.json"), "--reports", str(out / "reports")], expect=expect)


def complete_ledger(out: Path, manifest: dict) -> None:
    path = out / "effort_ledger.json"
    ledger = json.loads(path.read_text(encoding="utf-8"))
    ledger["subagent_capability_check"].update(
        {
            "status": "completed",
            "spawn_tool": "self-test",
            "can_set_reasoning_effort": True,
            "notes": "self-test fixture",
        }
    )
    ledger["lead_effort"].update(
        {
            "actual_reasoning_effort": "high",
            "status": "completed",
            "agent_id": "self-test-lead",
            "runtime_provenance": "self-test",
            "evidence": "fixture-generated reports",
        }
    )
    ledger["fallback"].update({"status": "not-used", "reason": ""})
    for row in ledger.get("batch_workers", []):
        row.update(
            {
                "status": "completed",
                "agent_id": f"self-test-{row['batch_id']}",
                "actual_reasoning_effort": "low",
                "runtime_provenance": "self-test",
                "fallback": False,
            }
        )
    if manifest.get("ui_implementation_audit", {}).get("visual_required"):
        for key in ("mockup_asset_worker", "visual_tooling_worker", "visual_comparison_worker"):
            ledger[key].update(
                {
                    "status": "completed",
                    "agent_id": f"self-test-{key}",
                    "actual_reasoning_effort": "low",
                    "runtime_provenance": "self-test",
                }
            )
    path.write_text(json.dumps(ledger, indent=2, sort_keys=True), encoding="utf-8")


def write_batch_report(out: Path, manifest: dict, batch: dict, *, out_of_scope: bool = False) -> None:
    rows = []
    inventory = []
    for unit_id in batch["coverage_units"]:
        unit = next(item for item in manifest["coverage_units"] if item["unit_id"] == unit_id)
        rows.append(f"| {unit_id} | CHECKED | {unit['sha256']} | Defines dashboard UI surface |")
        inventory.append(
            f"| {unit_id} | {unit['rel_path']} | dashboard | Operations Dashboard / Resolve incident | visible label and class names | urgent incident first | source renders nav, hero, button, and archive detail | CSS grid has desktop and mobile risk notes |"
        )
    findings = "No findings."
    if out_of_scope:
        findings = """- Priority: P2
- Files: src/not-owned.tsx
- Mockup/requirement evidence: dashboard mockup
- Interface evidence: out-of-scope source
- Expected behavior/standard: source owned by this batch only
- Gap: finding references a file outside this batch
- Suggested implementation direction: keep findings scoped
"""
    write(
        out / "reports" / f"{batch['id']}.md",
        f"""## Run ID
{manifest['run_id']}

## Batch ID
{batch['id']}

## Batch Summary
Dashboard UI source and styles for visual comparison.

## File Coverage
| Unit | Status | SHA-256 | Purpose |
| --- | --- | --- | --- |
{chr(10).join(rows)}

## UI Source Inventory
| Unit | File | Surface | Visible Element | Source Evidence | Expected Behavior | Actual Implementation | Responsive/State Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
{chr(10).join(inventory)}

## Journey Priority Contract
| Surface | Primary user goal | Primary information | Frequent actions | Occasional controls | Rare/Admin/Configuration controls | Expected desktop order | Expected mobile order |
| --- | --- | --- | --- | --- | --- | --- | --- |
| dashboard | review urgent incidents first | active incident summary and severity | resolve incident | navigation to reports | archive export details | nav, active incident, action, archive detail | active incident and resolve action before archive or settings |

## First Viewport Journey Check
| Viewport | First visible content | Primary decision data visible? | Low-frequency controls above content? | Low-frequency/header/control share | What can user decide from first viewport? | Result | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| desktop | navigation and active incident hero | Yes | No | 12% | user can decide which incident to resolve | PASS | source order and CSS grid evidence |
| mobile | active incident summary and Resolve incident action | Yes | No | 10% | user can decide which incident to resolve | PASS | source order and responsive CSS evidence |

## Mockup And Journey Alignment
Source exposes the dashboard screen, primary action, navigation, and rare archive detail referenced by the journey docs.

## Implementation Gap Findings
{findings}

## No Gap Notes
Owned units are represented in the inventory with visible labels and layout notes.

## Open Questions
None.
""",
    )


def write_complete_reports(out: Path, *, out_of_scope: bool = False, weak_visual_evidence: bool = False) -> dict:
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    complete_ledger(out, manifest)
    for batch in manifest["batches"]:
        write_batch_report(out, manifest, batch, out_of_scope=out_of_scope)
    if manifest.get("ui_implementation_audit", {}).get("visual_required"):
        source_file = manifest["source_files"][0]["rel_path"]
        write(
            out / "reports" / "mockup_asset_audit.md",
            f"""## Run ID
{manifest['run_id']}

## Worker
mockup_asset_audit

## Mockup/Asset Inputs
design/mockups/dashboard-mobile.png was visually inspected as a dashboard mockup.

## Journey Requirement Inputs
docs/journeys.md defines the dashboard journey and mobile hierarchy.

## Expected Screens And Visual Requirements
Dashboard should show urgent incident summary and Resolve incident before archive details on desktop and mobile.

## Findings
No findings.

## Open Questions
None.
""",
        )
        write(
            out / "reports" / "visual_tooling_audit.md",
            f"""## Run ID
{manifest['run_id']}

## Worker
visual_tooling_audit

## Tooling Inventory
package.json exposes vite dev and Playwright visual test scripts.

## Safe Run Path
Run npm scripts in fixture mode and open the dashboard route locally.

## Desktop/Mobile Screenshot Plan
Capture desktop 1440px and mobile 390px screenshots for the dashboard route.

## Findings
No findings.

## Open Questions
None.
""",
        )
        evidence = "looked fine" if weak_visual_evidence else "playwright screenshot artifacts desktop.png and mobile.png"
        write(
            out / "reports" / "visual_comparison_audit.md",
            f"""## Run ID
{manifest['run_id']}

## Worker
visual_comparison_audit

## Journey Priority Contract
| Surface | Primary user goal | Primary information | Frequent actions | Occasional controls | Rare/Admin/Configuration controls | Expected desktop order | Expected mobile order |
| --- | --- | --- | --- | --- | --- | --- | --- |
| dashboard | review urgent incidents first | active incident summary and severity | resolve incident | navigation to reports | archive export details | nav, active incident, action, archive detail | active incident and resolve action before archive or settings |

## First Viewport Journey Check
| Viewport | First visible content | Primary decision data visible? | Low-frequency controls above content? | Low-frequency/header/control share | What can user decide from first viewport? | Result | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| desktop | navigation and active incident hero | Yes | No | 12% | user can decide which incident to resolve | PASS | playwright screenshot artifact desktop.png and DOM viewport measurement 12% controls |
| mobile | active incident summary and Resolve incident action | Yes | No | 10% | user can decide which incident to resolve | PASS | playwright screenshot artifact mobile.png and DOM viewport measurement 10% controls |

## Visual Comparison Checks
| Journey | Viewport | Route/Screen | Mockup/Requirement | Implementation Screenshot/Tool Evidence | Differences | Result |
| --- | --- | --- | --- | --- | --- | --- |
| Dashboard review | desktop | / dashboard | design/mockups/dashboard-mobile.png and docs/journeys.md | {evidence} | No material desktop mismatch in fixture report | MATCHED |
| Dashboard review | mobile | / dashboard | design/mockups/dashboard-mobile.png and docs/journeys.md | {evidence} | No material mobile mismatch in fixture report | MATCHED |

## Findings
No findings.

## Open Questions
None.
""",
        )
    return manifest


def write_currency_priority_visual_report(out: Path, *, include_p1: bool) -> None:
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    source_file = next(item["rel_path"] for item in manifest["source_files"] if item["rel_path"].endswith(".tsx"))
    first_viewport_result = "GAP" if include_p1 else "PASS"
    visual_result = "GAP" if include_p1 else "MATCHED"
    findings = "No findings."
    if include_p1:
        findings = f"""- Priority: P1
- Files: {source_file}
- Mockup/requirement evidence: docs/currency-rates-journey.md requires most-used live rates before target/settings controls on mobile.
- Interface evidence: mobile screenshot currency-rates-mobile.png and DOM viewport measurement show Target Currency settings consume 82% of the first viewport while Most-used rates start below the fold.
- Expected behavior/standard: mobile first viewport should show primary decision-making rate data before occasional target settings.
- Gap: the target/settings block dominates the first mobile viewport and pushes most-used rates below the fold.
- Suggested implementation direction: reorder mobile layout so most-used live rates appear first and collapse target settings behind a secondary control.
"""
    write(
        out / "reports" / "visual_comparison_audit.md",
        f"""## Run ID
{manifest['run_id']}

## Worker
visual_comparison_audit

## Journey Priority Contract
| Surface | Primary user goal | Primary information | Frequent actions | Occasional controls | Rare/Admin/Configuration controls | Expected desktop order | Expected mobile order |
| --- | --- | --- | --- | --- | --- | --- | --- |
| currency rates | decide current most-used live rates quickly | most-used live rates list | inspect rates | target currency adjustment | target/settings configuration | rates and chart, then controls | most-used live rates before target/settings controls |

## First Viewport Journey Check
| Viewport | First visible content | Primary decision data visible? | Low-frequency controls above content? | Low-frequency/header/control share | What can user decide from first viewport? | Result | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| desktop | rates chart and most-used rates beside settings | Yes | No | 18% | user can decide current rates | PASS | playwright screenshot currency-rates-desktop.png and DOM viewport measurement 18% controls |
| mobile | Target Currency settings form and Apply settings button | No, most-used rates are below the fold | Yes, target/settings controls are above content | 82% | user can only configure target currency, not decide a rate | {first_viewport_result} | playwright screenshot currency-rates-mobile.png and DOM viewport measurement 82% controls before fold |

## Visual Comparison Checks
| Journey | Viewport | Route/Screen | Mockup/Requirement | Implementation Screenshot/Tool Evidence | Differences | Result |
| --- | --- | --- | --- | --- | --- | --- |
| Currency rates decision | desktop | /currency-rates | docs/currency-rates-journey.md | playwright screenshot currency-rates-desktop.png | Desktop still exposes primary rates | MATCHED |
| Currency rates decision | mobile | /currency-rates | docs/currency-rates-journey.md | playwright screenshot currency-rates-mobile.png and DOM viewport measurement | Target Currency block consumes first viewport before most-used rates | {visual_result} |

## Findings
{findings}

## Open Questions
None.
""",
    )


def assert_ledger_mutation_fails(out: Path, tmp: Path, name: str, mutate) -> None:
    mutated = tmp / name
    shutil.copytree(out, mutated)
    ledger_path = mutated / "effort_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    mutate(ledger)
    ledger_path.write_text(json.dumps(ledger, indent=2, sort_keys=True), encoding="utf-8")
    result = verify(mutated, expect=1)
    check("effort_ledger_issues" in result.stdout, f"{name} should fail effort ledger verification")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="ui-implementation-audit-self-test-"))
    try:
        ui_fixture = tmp / "ui-fixture"
        make_ui_fixture(ui_fixture)
        out = tmp / "out"
        manifest = build(ui_fixture, out)
        check(manifest["audit_kind"] == "ui-implementation", "manifest should record ui-implementation audit kind")
        check(manifest["source_file_count"] == 2, "only interface source files should be queued")
        queued = {item["rel_path"] for item in manifest["source_files"]}
        check(queued == {"src/App.tsx", "src/styles.css"}, f"unexpected source queue: {queued}")
        check(manifest["ui_implementation_audit"]["mockup_asset_count"] >= 1, "mockup asset should be discovered")
        check(manifest["ui_implementation_audit"]["requirement_source_count"] >= 1, "journey requirement should be discovered")
        write_complete_reports(out)
        result = verify(out)
        check("ok: true" in result.stdout, "complete report should verify")

        missing_report_out = tmp / "missing-report-out"
        shutil.copytree(out, missing_report_out)
        first_report = next((missing_report_out / "reports").glob("batch_*.md"))
        first_report.unlink()
        missing_result = verify(missing_report_out, expect=1)
        check("missing_reports" in missing_result.stdout, "missing batch report should fail verification")

        weak_visual_out = tmp / "weak-visual-out"
        build(ui_fixture, weak_visual_out)
        write_complete_reports(weak_visual_out, weak_visual_evidence=True)
        weak_visual_result = verify(weak_visual_out, expect=1)
        check("Implementation Screenshot/Tool Evidence" in weak_visual_result.stdout, "weak visual evidence should fail verification")

        currency_fixture = tmp / "currency-rates-fixture"
        make_currency_rates_fixture(currency_fixture)
        currency_out = tmp / "currency-rates-out"
        build(currency_fixture, currency_out)
        write_complete_reports(currency_out)
        write_currency_priority_visual_report(currency_out, include_p1=False)
        currency_priority_result = verify(currency_out, expect=1)
        check(
            "mobile first viewport priority failure requires a P1 journey-priority finding" in currency_priority_result.stdout,
            "currency rates mobile first-viewport regression should require a P1 journey-priority finding",
        )
        write_currency_priority_visual_report(currency_out, include_p1=True)
        currency_priority_fixed = verify(currency_out)
        check("ok: true" in currency_priority_fixed.stdout, "P1 journey-priority finding should satisfy first-viewport regression")

        out_of_scope_out = tmp / "out-of-scope-out"
        build(ui_fixture, out_of_scope_out, "--batch-size", "1")
        write_complete_reports(out_of_scope_out, out_of_scope=True)
        out_of_scope_result = verify(out_of_scope_out, expect=1)
        check("out_of_scope" in out_of_scope_result.stdout, "out-of-batch finding should fail verification")

        stale_out = tmp / "stale-out"
        build(ui_fixture, stale_out)
        write_complete_reports(stale_out)
        write(ui_fixture / "src" / "App.tsx", (ui_fixture / "src" / "App.tsx").read_text(encoding="utf-8") + "\n// changed\n")
        stale_result = verify(stale_out, expect=1)
        check("current_hash_mismatches" in stale_result.stdout, "stale input hashes should fail verification")

        assert_ledger_mutation_fails(
            out,
            tmp,
            "weak-capability-ledger-out",
            lambda ledger: ledger["subagent_capability_check"].update({"can_set_reasoning_effort": None}),
        )
        assert_ledger_mutation_fails(
            out,
            tmp,
            "weak-visual-worker-ledger-out",
            lambda ledger: ledger["visual_comparison_worker"].update({"runtime_provenance": ""}),
        )

        cli_fixture = tmp / "cli-fixture"
        make_cli_fixture(cli_fixture)
        cli_out = tmp / "cli-out"
        cli_manifest = build(cli_fixture, cli_out)
        check(cli_manifest["source_file_count"] == 0, "CLI fixture should not queue non-interface source")
        complete_ledger(cli_out, cli_manifest)
        cli_result = verify(cli_out)
        check("ok: true" in cli_result.stdout, "non-UI fixture should verify without visual reports")

        print("self-test ok")
        return 0
    finally:
        if KEEP_TEMP_ON_FAILURE:
            print(f"Preserved self-test workspace: {tmp}", file=sys.stderr)
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
