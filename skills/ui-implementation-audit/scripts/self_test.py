#!/usr/bin/env python3
"""Fixture-based smoke tests for the UI implementation audit harness."""

from __future__ import annotations

import hashlib
import json
import os
import re
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


INTERACTION_CHECKLIST_LINE = (
    "Interaction checklist: badge-detail=pass; row-hit-target=pass; "
    "navigation-cursor=pass; transient-disclosure=pass; disclosure-scrollbar=pass; "
    "icon-meaning=pass; stable-expansion-width=pass; hover-copy=pass; "
    "status-summary=pass; message-metadata=pass."
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
Primary decision: decide current exchange rates for the currencies used most often.
Required facts: the most-used live rates list.
Frequent action: inspect a rate and continue cost tracking.
Occasional control: adjust target currency.
Rare control: advanced target/settings configuration.
UI audit handoff: verify the rendered surface supports the rate decision and does not let target/settings controls overwhelm the decision path.
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
        if unit["rel_path"] == "src/App.tsx":
            traces = "missing | missing | not-applicable: fixture has no authenticated role model | missing | missing"
        else:
            traces = (
                "not-applicable: static stylesheet has no event handler | "
                "not-applicable: static stylesheet has no backend call | "
                "not-applicable: static stylesheet has no permission decision | "
                "not-applicable: static stylesheet has no persistence behavior | "
                "not-applicable: rendered evidence verifies stylesheet layout separately"
            )
        inventory.append(
            f"| {unit_id} | {unit['rel_path']} | dashboard | Operations Dashboard / Resolve incident | visible label and class names | urgent incident first | source renders nav, hero, button, and archive detail | {traces} | CSS grid has desktop and mobile risk notes |"
        )
    findings = "No findings."
    if "src/App.tsx" in batch["files"]:
        findings = """- Priority: P1
- Files: src/App.tsx
- Mockup/requirement evidence: dashboard journey requires a real incident resolution path
- Interface evidence: Resolve incident button has no handler, backend, persistence, or test trace
- Expected behavior/standard: primary action should bind handler, backend result, persistence, failure states, and tests
- Gap: action trace records missing implementation and verification paths
- Suggested implementation direction: implement the real resolution workflow and cover success, permission, persistence, and failure behavior
"""
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
| Unit | File | Surface | Visible Element | Source Evidence | Expected Behavior | Actual Implementation | Handler Evidence | Backend/API Evidence | Permission Evidence | Persistence Evidence | Test Evidence | Responsive/State Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
{chr(10).join(inventory)}

## Journey Decision Model
| Surface | Primary user goal | Primary decision | Required facts | Warning/flag conditions | Frequent actions | Secondary/rare actions | Unconfirmed assumptions |
| --- | --- | --- | --- | --- | --- | --- | --- |
| dashboard | review urgent incidents first | decide which incident to resolve | active incident summary and severity | urgent severity and stale status | resolve incident | navigation to reports and archive export details | none |

## Rendered Journey Usability
| Viewport | Decision supported | Visible decision-driving content | Visible secondary/detail content | Detail access pattern | Readability/contrast evidence | Layout quality result | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| desktop | decide which incident to resolve | navigation and active incident hero | archive detail | inline secondary aside | source order and CSS grid evidence | PASS | source order and CSS grid evidence |
| mobile | decide which incident to resolve | active incident summary and Resolve incident action | archive detail | secondary content after primary action | source order and responsive CSS evidence | PASS | source order and responsive CSS evidence |

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


def write_visual_evidence(out: Path, manifest: dict, *, route: str = "/dashboard") -> None:
    artifacts = out / "artifacts"
    desktop = artifacts / "desktop.png"
    mobile = artifacts / "mobile.png"
    formal = artifacts / "formal-web.json"
    write_bytes(desktop, PNG_1X1)
    write_bytes(mobile, PNG_1X1)
    write(
        formal,
        json.dumps(
            {
                "runId": "formal-self-test",
                "generatedAt": "2026-07-10T00:00:00Z",
                "browser": "chromium",
                "targets": [{"url": "http://127.0.0.1/dashboard"}],
                "pages": [
                    {"outcome": "checked", "metrics": {"visibleScrollbars": []}, "findings": []},
                    {"outcome": "checked", "metrics": {"visibleScrollbars": []}, "findings": []},
                ],
                "findings": [],
                "coverage": {"failed": False, "checkedPages": 2, "requiredCheckedPages": 1, "failures": [], "tolerated": []},
            },
            indent=2,
        ),
    )

    def record(record_id: str, path: Path, kind: str, viewport: dict, *, dimensions: bool = False) -> dict:
        value = {
            "id": record_id,
            "kind": kind,
            "path": path.relative_to(out).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "mime": "image/png" if kind == "screenshot" else "application/json",
            "route": route,
            "state": "default fixture state",
            "viewport": viewport,
            "captured_by": "self-test fixture",
        }
        if dimensions:
            value.update({"width": 1, "height": 1})
        return value

    write(
        out / "visual_evidence.json",
        json.dumps(
            {
                "schema_version": 1,
                "run_id": manifest["run_id"],
                "artifacts": [
                    record("shot-desktop", desktop, "screenshot", {"width": 1440, "height": 900, "label": "desktop"}, dimensions=True),
                    record("shot-mobile", mobile, "screenshot", {"width": 390, "height": 844, "label": "mobile"}, dimensions=True),
                    record("formal-web", formal, "formal-web-verifier", {"width": 1440, "height": 900, "label": "desktop and mobile"}),
                ],
            },
            indent=2,
        ),
    )


def write_complete_reports(
    out: Path,
    *,
    out_of_scope: bool = False,
    weak_visual_evidence: bool = False,
    real_visual_evidence: bool = True,
) -> dict:
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    complete_ledger(out, manifest)
    for batch in manifest["batches"]:
        write_batch_report(out, manifest, batch, out_of_scope=out_of_scope)
    if manifest.get("ui_implementation_audit", {}).get("visual_required"):
        if real_visual_evidence:
            write_visual_evidence(out, manifest)
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
        evidence = "looked fine" if weak_visual_evidence else "playwright capture with formal verifier evidence:formal-web"
        write(
            out / "reports" / "visual_comparison_audit.md",
            f"""## Run ID
{manifest['run_id']}

## Worker
visual_comparison_audit

## Journey Decision Model
| Surface | Primary user goal | Primary decision | Required facts | Warning/flag conditions | Frequent actions | Secondary/rare actions | Unconfirmed assumptions |
| --- | --- | --- | --- | --- | --- | --- | --- |
| dashboard | review urgent incidents first | decide which incident to resolve | active incident summary and severity | urgent severity and stale status | resolve incident | navigation to reports and archive export details | none |

## Rendered Journey Usability
| Viewport | Decision supported | Visible decision-driving content | Visible secondary/detail content | Detail access pattern | Readability/contrast evidence | Layout quality result | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| desktop | decide which incident to resolve | navigation and active incident hero | archive detail | inline secondary aside | playwright screenshot evidence:shot-desktop and DOM viewport measurement | PASS | playwright screenshot evidence:shot-desktop and DOM viewport measurement 12% controls |
| mobile | decide which incident to resolve | active incident summary and Resolve incident action | archive detail | secondary content after primary action | playwright screenshot evidence:shot-mobile and DOM viewport measurement | PASS | playwright screenshot evidence:shot-mobile and DOM viewport measurement 10% controls |

## Visual Comparison Checks
| Journey | Viewport | Route/Screen | Mockup/Requirement | Implementation Screenshot/Tool Evidence | Differences | Result |
| --- | --- | --- | --- | --- | --- | --- |
| Dashboard review | desktop | /dashboard | design/mockups/dashboard-mobile.png and docs/journeys.md | {evidence} evidence:shot-desktop | No material desktop mismatch in fixture report | MATCHED |
| Dashboard review | mobile | /dashboard | design/mockups/dashboard-mobile.png and docs/journeys.md | {evidence} evidence:shot-mobile | No material mobile mismatch in fixture report | MATCHED |

{INTERACTION_CHECKLIST_LINE}

## Findings
No findings.

## Open Questions
None.
""",
        )
    return manifest


def write_currency_priority_visual_report(out: Path, *, include_p1: bool) -> None:
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    write_visual_evidence(out, manifest, route="/currency-rates")
    source_file = next(item["rel_path"] for item in manifest["source_files"] if item["rel_path"].endswith(".tsx"))
    first_viewport_result = "GAP" if include_p1 else "PASS"
    visual_result = "GAP" if include_p1 else "MATCHED"
    findings = "No findings."
    if include_p1:
        findings = f"""- Priority: P1
- Files: {source_file}
- Mockup/requirement evidence: docs/currency-rates-journey.md requires most-used live rates before target/settings controls on mobile.
- Interface evidence: mobile screenshot currency-rates-mobile.png and DOM viewport measurement show Target Currency settings dominate the visible surface while Most-used rates are buried below secondary controls.
- Expected behavior/standard: rendered journey surface should let users decide current rates without secondary target settings overwhelming that decision path.
- Gap: the target/settings block dominates the visible surface and buries most-used rates.
- Suggested implementation direction: make most-used live rates the dominant decision-driving content and move target settings into a secondary detail path.
"""
    write(
        out / "reports" / "visual_comparison_audit.md",
        f"""## Run ID
{manifest['run_id']}

## Worker
visual_comparison_audit

## Journey Decision Model
| Surface | Primary user goal | Primary decision | Required facts | Warning/flag conditions | Frequent actions | Secondary/rare actions | Unconfirmed assumptions |
| --- | --- | --- | --- | --- | --- | --- | --- |
| currency rates | decide current most-used live rates quickly | decide current exchange rates | most-used live rates list | stale rate warning | inspect rates | target currency adjustment and target/settings configuration | none |

## Rendered Journey Usability
| Viewport | Decision supported | Visible decision-driving content | Visible secondary/detail content | Detail access pattern | Readability/contrast evidence | Layout quality result | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| desktop | decide current rates | rates chart and most-used rates | target settings | inline secondary panel | playwright screenshot evidence:shot-desktop and DOM viewport measurement | PASS | playwright screenshot evidence:shot-desktop and DOM viewport measurement 18% secondary controls |
| mobile | only target currency configuration is supported; rate decision is buried | Target Currency settings form and Apply settings button | target/settings controls dominate while most-used rates are buried under duplicate summaries and vague labels | secondary controls dominate visible surface | playwright screenshot evidence:shot-mobile and DOM viewport measurement | {first_viewport_result} | playwright screenshot evidence:shot-mobile and DOM viewport measurement 82% controls before rates |

## Visual Comparison Checks
| Journey | Viewport | Route/Screen | Mockup/Requirement | Implementation Screenshot/Tool Evidence | Differences | Result |
| --- | --- | --- | --- | --- | --- | --- |
| Currency rates decision | desktop | /currency-rates | docs/currency-rates-journey.md | playwright screenshot evidence:shot-desktop and formal evidence:formal-web | Desktop still exposes primary rates | MATCHED |
| Currency rates decision | mobile | /currency-rates | docs/currency-rates-journey.md | playwright screenshot evidence:shot-mobile and DOM viewport measurement | Target Currency block dominates the visible surface and buries most-used rates | {visual_result} |

{INTERACTION_CHECKLIST_LINE}

## Findings
{findings}

## Open Questions
None.
""",
    )


def write_layout_noise_visual_report(out: Path, *, include_p1: bool) -> None:
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    write_visual_evidence(out, manifest, route="/review")
    source_file = manifest["source_files"][0]["rel_path"]
    result = "GAP" if include_p1 else "MATCHED"
    usability_result = "GAP" if include_p1 else "PASS"
    findings = "No findings."
    if include_p1:
        findings = f"""- Priority: P1
- Files: {source_file}
- Mockup/requirement evidence: docs/journeys.md requires the review workspace to make the next-case decision quickly from primary facts.
- Interface evidence: desktop screenshot review-workspace-desktop.png shows nested blocks inside blocks, border stacks, visual noise, weak grid alignment, an unstable disclosure that changes width, a row that is not clickable unless a tiny icon-only target is hit, a disclosure icon that overlaps the scrollbar, flags with no hover/click popover feedback, selectable timestamps, permanent helper text, unintuitive icons, avatar clutter, and left/right message alignment problems.
- Expected behavior/standard: rendered UI should make critical decision information prominent, keep secondary detail reachable without dominating, and use stable aligned whole-row disclosure controls, interactive badges with useful popover detail, meaningful icons, passive metadata, and quiet message layout.
- Gap: the noisy frame stack and unstable disclosure obscure the decision hierarchy and make lower-importance detail look as important as critical decision content.
- Suggested implementation direction: flatten nested surfaces, normalize grid gutters, stabilize disclosure width and control position, move obvious instructions to hints, replace decorative/meaningless icons, and align message groups by sender.
"""
    write(
        out / "reports" / "visual_comparison_audit.md",
        f"""## Run ID
{manifest['run_id']}

## Worker
visual_comparison_audit

## Journey Decision Model
| Surface | Primary user goal | Primary decision | Required facts | Warning/flag conditions | Frequent actions | Secondary/rare actions | Unconfirmed assumptions |
| --- | --- | --- | --- | --- | --- | --- | --- |
| review workspace | choose the next case to resolve | decide which case needs action now | case status, urgency, and owner summary | blocked or stale case state | open case | raw metadata and diagnostic history | none |

## Rendered Journey Usability
| Viewport | Decision supported | Visible decision-driving content | Visible secondary/detail content | Detail access pattern | Readability/contrast evidence | Layout quality result | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| desktop | next-case decision is hard to scan | decision-critical facts are weakly placed inside nested blocks inside blocks | low-importance raw metadata, sender labels, selectable timestamps, permanent instruction noise, avatar clutter, and helper text dominate | unstable expander jumps horizontally, width changes, row is not clickable except a tiny icon-only target, and the disclosure icon interferes with the scrollbar | playwright screenshot evidence:shot-desktop and DOM viewport measurement | {usability_result} | playwright screenshot evidence:shot-desktop and DOM viewport measurement |
| mobile | next-case decision is hard to scan | decision-critical facts are buried below noisy surfaces | secondary detail and decorative clutter dominate | flags have no hover feedback and no popover detail, while expanded and collapsed result blocks have different widths | playwright screenshot evidence:shot-mobile and DOM viewport measurement | {usability_result} | playwright screenshot evidence:shot-mobile and DOM viewport measurement |

## Visual Comparison Checks
| Journey | Viewport | Route/Screen | Mockup/Requirement | Implementation Screenshot/Tool Evidence | Differences | Result |
| --- | --- | --- | --- | --- | --- | --- |
| Review workspace | desktop | /review | docs/journeys.md | playwright screenshot evidence:shot-desktop and formal evidence:formal-web | nested cards, border stacks, visual noise, misalignment, unintuitive icons, permanent instruction helper text, avatar clutter, icon-only row activation, expander/scrollbar collision, and unstable disclosure width changes | {result} |
| Review workspace | mobile | /review | docs/journeys.md | playwright screenshot evidence:shot-mobile | weak grid, badge no hover/click popover detail, low-importance detail dominates, sender labels and selectable timestamps add noise, and message alignment problems hide the decision hierarchy | {result} |

{INTERACTION_CHECKLIST_LINE}

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
        missing_visual_artifacts_out = tmp / "missing-visual-artifacts-out"
        build(ui_fixture, missing_visual_artifacts_out)
        write_complete_reports(missing_visual_artifacts_out, real_visual_evidence=False)
        missing_visual_artifacts_result = verify(missing_visual_artifacts_out, expect=1)
        check("visual evidence" in missing_visual_artifacts_result.stdout.lower(), "named but nonexistent screenshots must fail verification")
        write_complete_reports(out)
        result = verify(out)
        check("ok: true" in result.stdout, "complete report should verify")

        tampered_visual_out = tmp / "tampered-visual-out"
        shutil.copytree(out, tampered_visual_out)
        write_bytes(tampered_visual_out / "artifacts" / "desktop.png", PNG_1X1 + b"tampered")
        tampered_visual_result = verify(tampered_visual_out, expect=1)
        check("sha256" in tampered_visual_result.stdout, "tampered screenshot bytes must fail evidence hash verification")

        wrong_metadata_out = tmp / "wrong-visual-metadata-out"
        shutil.copytree(out, wrong_metadata_out)
        wrong_metadata_path = wrong_metadata_out / "visual_evidence.json"
        wrong_metadata = json.loads(wrong_metadata_path.read_text(encoding="utf-8"))
        next(item for item in wrong_metadata["artifacts"] if item["id"] == "shot-desktop")["route"] = "/invented-route"
        write(wrong_metadata_path, json.dumps(wrong_metadata, indent=2))
        wrong_metadata_result = verify(wrong_metadata_out, expect=1)
        check("route metadata does not match" in wrong_metadata_result.stdout, "screenshot route metadata must bind to the report row")

        weak_formal_out = tmp / "weak-formal-out"
        shutil.copytree(out, weak_formal_out)
        formal_path = weak_formal_out / "artifacts" / "formal-web.json"
        formal_payload = json.loads(formal_path.read_text(encoding="utf-8"))
        formal_payload["pages"][0]["metrics"].pop("visibleScrollbars")
        write(formal_path, json.dumps(formal_payload, indent=2))
        weak_formal_manifest_path = weak_formal_out / "visual_evidence.json"
        weak_formal_manifest = json.loads(weak_formal_manifest_path.read_text(encoding="utf-8"))
        next(item for item in weak_formal_manifest["artifacts"] if item["id"] == "formal-web")["sha256"] = hashlib.sha256(formal_path.read_bytes()).hexdigest()
        write(weak_formal_manifest_path, json.dumps(weak_formal_manifest, indent=2))
        weak_formal_result = verify(weak_formal_out, expect=1)
        check("visibleScrollbars" in weak_formal_result.stdout, "formal verifier JSON must preserve visible scrollbar inventory")

        invented_action_trace_out = tmp / "invented-action-trace-out"
        shutil.copytree(out, invented_action_trace_out)
        action_report = next((invented_action_trace_out / "reports").glob("batch_*.md"))
        action_report.write_text(
            action_report.read_text(encoding="utf-8").replace(
                "| missing | missing | not-applicable: fixture has no authenticated role model |",
                "| src/App.tsx#inventedHandler | missing | not-applicable: fixture has no authenticated role model |",
                1,
            ),
            encoding="utf-8",
        )
        invented_action_result = verify(invented_action_trace_out, expect=1)
        check("symbol/text is absent" in invented_action_result.stdout, "invented handler symbols must fail action-trace verification")

        missing_trace_without_finding_out = tmp / "missing-trace-without-finding-out"
        shutil.copytree(out, missing_trace_without_finding_out)
        missing_trace_report = next((missing_trace_without_finding_out / "reports").glob("batch_*.md"))
        missing_trace_report.write_text(
            re.sub(
                r"(?s)(## Implementation Gap Findings\n).*?\n\n## No Gap Notes",
                r"\1No findings.\n\n## No Gap Notes",
                missing_trace_report.read_text(encoding="utf-8"),
            ),
            encoding="utf-8",
        )
        missing_trace_result = verify(missing_trace_without_finding_out, expect=1)
        check("missing handler/backend/permission/persistence/test traces require a finding" in missing_trace_result.stdout, "missing action traces must not pass under No findings")

        checklist_missing_out = tmp / "checklist-missing-out"
        shutil.copytree(out, checklist_missing_out)
        checklist_report = checklist_missing_out / "reports" / "visual_comparison_audit.md"
        checklist_report.write_text(
            checklist_report.read_text(encoding="utf-8").replace(INTERACTION_CHECKLIST_LINE, "Interaction checklist: omitted."),
            encoding="utf-8",
        )
        checklist_missing_result = verify(checklist_missing_out, expect=1)
        check(
            "interaction checklist label" in checklist_missing_result.stdout,
            "visual comparison report missing interaction checklist labels should fail verification",
        )

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
            "rendered journey usability danger terms require a visual/usability finding" in currency_priority_result.stdout,
            "currency rates rendered usability regression should require a visual/usability finding",
        )
        write_currency_priority_visual_report(currency_out, include_p1=True)
        currency_priority_fixed = verify(currency_out)
        check("ok: true" in currency_priority_fixed.stdout, "visual/usability finding should satisfy rendered usability regression")

        layout_noise_out = tmp / "layout-noise-out"
        build(ui_fixture, layout_noise_out)
        write_complete_reports(layout_noise_out)
        write_layout_noise_visual_report(layout_noise_out, include_p1=False)
        layout_noise_result = verify(layout_noise_out, expect=1)
        check(
            "rendered journey usability danger terms require a visual/usability finding" in layout_noise_result.stdout
            or "visual danger terms require a visual/usability finding" in layout_noise_result.stdout,
            "layout noise and disclosure instability should require a visual/usability finding",
        )
        write_layout_noise_visual_report(layout_noise_out, include_p1=True)
        layout_noise_fixed = verify(layout_noise_out)
        check("ok: true" in layout_noise_fixed.stdout, "layout-noise finding should satisfy visual verifier")

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
