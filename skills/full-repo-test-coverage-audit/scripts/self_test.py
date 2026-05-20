#!/usr/bin/env python3
"""Smoke tests for the full-repo-test-coverage-audit harness."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "scripts" / "build_test_coverage_audit_batches.py"
VERIFY = ROOT / "scripts" / "verify_test_coverage_audit_results.py"
TIMEOUT = int(os.environ.get("FULL_REPO_TEST_COVERAGE_AUDIT_SELF_TEST_TIMEOUT", "30"))


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def run(args: list[str], *, expect: int = 0) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=TIMEOUT)
    if result.returncode != expect:
        raise AssertionError(
            f"Expected exit {expect} from {' '.join(args)}, got {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def make_ui_fixture(repo: Path) -> None:
    write(
        repo / "src" / "math.ts",
        """
export function clamp(value: number, min: number, max: number): number {
  if (min > max) throw new Error("invalid range");
  if (value < min) return min;
  if (value > max) return max;
  return value;
}

export async function loadUser(id: string, fetcher: (id: string) => Promise<{ id: string }>) {
  if (!id) throw new Error("id required");
  return fetcher(id);
}
""".strip()
        + "\n",
    )
    write(
        repo / "src" / "App.tsx",
        """
export function App() {
  return (
    <main>
      <button onClick={() => console.log("save")}>Save profile</button>
      <p role="status">Ready</p>
    </main>
  );
}
""".strip()
        + "\n",
    )
    write(
        repo / "tests" / "math.test.ts",
        """
import { clamp } from "../src/math";

test("clamp returns in-range values", () => {
  expect(clamp(2, 1, 3)).toBe(2);
});
""".strip()
        + "\n",
    )
    write(repo / "package.json", '{"scripts":{"test":"vitest"},"devDependencies":{"vitest":"latest"}}\n')


def make_cli_fixture(repo: Path) -> None:
    write(
        repo / "src" / "tool.py",
        """
def normalize_name(value: str) -> str:
    if not value:
        raise ValueError("value required")
    return value.strip().lower()
""".strip()
        + "\n",
    )


def complete_ledger(out: Path, manifest: dict) -> None:
    ledger_path = out / "effort_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["subagent_capability_check"]["status"] = "completed"
    ledger["subagent_capability_check"]["spawn_tool"] = "self-test"
    ledger["subagent_capability_check"]["can_set_reasoning_effort"] = True
    ledger["lead_effort"]["status"] = "completed"
    ledger["lead_effort"]["actual_reasoning_effort"] = "high"
    ledger["lead_effort"]["agent_id"] = "self-test-lead"
    ledger["lead_effort"]["runtime_provenance"] = "self-test fixture"
    ledger["lead_effort"]["evidence"] = "self-test fixture"
    for worker in ledger["batch_workers"]:
        worker["status"] = "completed"
        worker["agent_id"] = "self-test"
        worker["actual_reasoning_effort"] = "low"
        worker["runtime_provenance"] = "self-test fixture"
    for key in ("ui_test_coverage_worker", "visual_e2e_coverage_worker"):
        if ledger[key]["status"] == "pending":
            ledger[key]["status"] = "completed"
            ledger[key]["agent_id"] = "self-test"
            ledger[key]["actual_reasoning_effort"] = "low"
            ledger[key]["runtime_provenance"] = "self-test fixture"
    if ledger["pruned_directory_review"]["status"] == "pending":
        ledger["pruned_directory_review"]["status"] = "completed"
    ledger_path.write_text(json.dumps(ledger, indent=2, sort_keys=True), encoding="utf-8")


def assert_ledger_mutation_fails(out: Path, tmp: Path, label: str, mutate) -> None:
    target = tmp / label
    shutil.copytree(out, target)
    ledger_path = target / "effort_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    mutate(ledger)
    ledger_path.write_text(json.dumps(ledger, indent=2, sort_keys=True), encoding="utf-8")
    result = verify(target, expect=1)
    check("effort_ledger" in result.stdout or "runtime_provenance" in result.stdout or "agent_id" in result.stdout, f"{label} should fail effort ledger verification")


def batch_report(manifest: dict, batch: dict, *, out_of_scope_file: str | None = None, omit_inventory: bool = False) -> str:
    unit_rows = []
    inventory_rows = []
    unit_by_id = {unit["unit_id"]: unit for unit in manifest["coverage_units"]}
    for unit_id in batch["coverage_units"]:
        unit = unit_by_id[unit_id]
        unit_rows.append(f"| {unit_id} | CHECKED | {unit['sha256']} | Source/test coverage unit |")
        target = "clamp" if unit["rel_path"] == "src/math.ts" else unit["rel_path"]
        evidence = "tests/math.test.ts covers in-range clamp" if unit["rel_path"] == "src/math.ts" else "No behavior targets or existing test evidence found"
        assessment = "Missing invalid range, min boundary, max boundary, async error path" if unit["rel_path"] == "src/math.ts" else "Reviewed as non-target or supporting file"
        recommendation = "Add unit tests for boundaries and failure paths" if unit["rel_path"] == "src/math.ts" else "No additional tests required in this fixture"
        inventory_rows.append(f"| {unit_id} | {unit['rel_path']} | {target} | unit | {evidence} | {assessment} | {recommendation} |")
    finding_file = out_of_scope_file or ("src/math.ts" if "src/math.ts" in batch["files"] else "")
    findings = "No findings."
    if finding_file:
        findings = f"""- Priority: P1
- Files: {finding_file}
- Target: clamp
- Existing test evidence: tests/math.test.ts covers only the in-range happy path
- Missing scenarios/boundaries: invalid min/max ordering, lower boundary, upper boundary, async fetcher failure
- Suggested test direction: add unit tests that assert thrown errors and boundary return values"""
    inventory = "\n".join(inventory_rows) if not omit_inventory else ""
    return f"""## Run ID
{manifest['run_id']}

## Batch ID
{batch['id']}

## Batch Summary
Fixture batch used by the self-test.

## File Coverage
| Unit | Status | SHA-256 | Purpose |
| --- | --- | --- | --- |
{chr(10).join(unit_rows)}

## Test Target Inventory
| Unit | File | Target | Kind | Existing Test Evidence | Scenario Assessment | Recommendation |
| --- | --- | --- | --- | --- | --- | --- |
{inventory}

## Coverage Findings
{findings}

## No Gap Notes
Supporting files were reviewed and either mapped to a finding or marked as non-targets.

## Open Questions
None.
"""


def write_complete_reports(out: Path, *, out_of_scope: bool = False, omit_inventory: bool = False) -> dict:
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    complete_ledger(out, manifest)
    reports = out / "reports"
    reports.mkdir(exist_ok=True)
    all_files = [item["rel_path"] for item in manifest["source_files"]]
    fallback_out_of_scope = next((path for path in all_files if path != manifest["batches"][0]["files"][0]), "outside.ts")
    for index, batch in enumerate(manifest["batches"]):
        out_file = fallback_out_of_scope if out_of_scope and index == 0 else None
        write(reports / f"{batch['id']}.md", batch_report(manifest, batch, out_of_scope_file=out_file, omit_inventory=omit_inventory and index == 0))
    coverage = manifest.get("test_coverage_audit", {})
    if coverage.get("ui_required"):
        write(
            reports / "ui_test_coverage_audit.md",
            f"""## Run ID
{manifest['run_id']}

## Worker
ui_test_coverage

## Journey/Test Sources
src/App.tsx and tests/math.test.ts.

## UI Coverage Checks
Save profile button has no component or e2e test evidence.

## Findings
- Priority: P1
- Files: src/App.tsx
- Target: Save profile button
- Existing test evidence: None found
- Missing scenarios/boundaries: click behavior, status update, failure state
- Suggested test direction: add component or e2e test for the save path

## Open Questions
None.
""",
        )
        write(
            reports / "visual_e2e_coverage_audit.md",
            f"""## Run ID
{manifest['run_id']}

## Worker
visual_e2e_coverage

## Visual/E2E Tooling
No Playwright, Cypress, or Storybook config found in fixture.

## Visual/E2E Coverage Checks
No safe visual harness exists for the UI fixture.

## Findings
- Priority: P2
- Files: src/App.tsx
- Target: profile screen visual state
- Existing test evidence: None found
- Missing scenarios/boundaries: desktop and mobile render checks
- Suggested test direction: add a lightweight component visual test or e2e smoke

## Open Questions
None.
""",
        )
    return manifest


def build(repo: Path, out: Path, *extra: str) -> dict:
    run([sys.executable, str(BUILD), "--repo", str(repo), "--out", str(out), "--run-id", "selftest-run", *extra])
    return json.loads((out / "manifest.json").read_text(encoding="utf-8"))


def verify(out: Path, *, expect: int = 0) -> subprocess.CompletedProcess[str]:
    return run([sys.executable, str(VERIFY), "--manifest", str(out / "manifest.json"), "--reports", str(out / "reports")], expect=expect)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="full-repo-test-coverage-audit-self-test-"))
    try:
        vendor_root = ROOT / "scripts" / "_vendor"
        for import_root in (ROOT.parents[1], vendor_root):
            if import_root.exists() and str(import_root) not in sys.path:
                sys.path.insert(0, str(import_root))
        from full_repo_harness import verify_common

        escaped_rows = verify_common.parse_markdown_table_dicts(
            "| Unit | File | Target |\n"
            "| --- | --- | --- |\n"
            "| src/a.ts | src/a.ts | handles A \\| B branch |\n"
        )
        check(escaped_rows[0]["target"] == "handles A | B branch", "escaped Markdown table pipes should stay inside a cell")

        fixture = tmp / "ui-fixture"
        make_ui_fixture(fixture)
        out = tmp / "out"
        manifest = build(fixture, out)
        check(manifest["audit_kind"] == "test-coverage", "manifest should record test-coverage audit kind")
        check("test_coverage_audit" in manifest, "manifest should include test_coverage_audit block")
        write_complete_reports(out)
        result = verify(out)
        check("ok: true" in result.stdout, "complete report should verify")

        missing_report_out = tmp / "missing-report-out"
        shutil.copytree(out, missing_report_out)
        first_report = next((missing_report_out / "reports").glob("batch_*.md"))
        first_report.unlink()
        missing_result = verify(missing_report_out, expect=1)
        check("missing_reports" in missing_result.stdout, "missing batch report should fail verification")

        weak_ledger_out = tmp / "weak-ledger-out"
        shutil.copytree(out, weak_ledger_out)
        weak_ledger = json.loads((weak_ledger_out / "effort_ledger.json").read_text(encoding="utf-8"))
        weak_ledger["batch_workers"][0]["actual_reasoning_effort"] = None
        (weak_ledger_out / "effort_ledger.json").write_text(json.dumps(weak_ledger, indent=2, sort_keys=True), encoding="utf-8")
        weak_ledger_result = verify(weak_ledger_out, expect=1)
        check("actual_reasoning_effort" in weak_ledger_result.stdout, "missing worker effort should fail verification")
        assert_ledger_mutation_fails(
            out,
            tmp,
            "weak-capability-ledger-out",
            lambda ledger: ledger["subagent_capability_check"].update({"can_set_reasoning_effort": None}),
        )
        assert_ledger_mutation_fails(
            out,
            tmp,
            "weak-lead-provenance-out",
            lambda ledger: ledger["lead_effort"].update({"runtime_provenance": ""}),
        )
        assert_ledger_mutation_fails(
            out,
            tmp,
            "weak-worker-agent-out",
            lambda ledger: ledger["batch_workers"][0].update({"agent_id": ""}),
        )
        assert_ledger_mutation_fails(
            out,
            tmp,
            "weak-ui-provenance-out",
            lambda ledger: ledger["ui_test_coverage_worker"].update({"runtime_provenance": ""}),
        )

        missing_inventory_out = tmp / "missing-inventory-out"
        manifest = build(fixture, missing_inventory_out)
        write_complete_reports(missing_inventory_out, omit_inventory=True)
        missing_inventory_result = verify(missing_inventory_out, expect=1)
        check("Test Target Inventory" in missing_inventory_result.stdout, "missing target inventory should fail verification")

        out_of_scope_out = tmp / "out-of-scope-out"
        manifest = build(fixture, out_of_scope_out, "--batch-size", "1")
        write_complete_reports(out_of_scope_out, out_of_scope=True)
        out_of_scope_result = verify(out_of_scope_out, expect=1)
        check("out_of_scope" in out_of_scope_result.stdout, "out-of-batch finding should fail verification")

        stale_out = tmp / "stale-out"
        build(fixture, stale_out)
        write_complete_reports(stale_out)
        write(fixture / "src" / "math.ts", (fixture / "src" / "math.ts").read_text(encoding="utf-8") + "\n// changed\n")
        stale_result = verify(stale_out, expect=1)
        check("current_hash_mismatches" in stale_result.stdout, "stale source hash should fail verification")

        scope_fixture = tmp / "scope-fixture"
        make_cli_fixture(scope_fixture)
        scope_out = tmp / "scope-out"
        build(scope_fixture, scope_out, "--exclude-glob", "src/tool.py")
        complete_ledger(scope_out, json.loads((scope_out / "manifest.json").read_text(encoding="utf-8")))
        scope_result = verify(scope_out, expect=1)
        check("unresolved scope warnings" in scope_result.stdout, "scope warning should fail verification")

        cli_fixture = tmp / "cli-fixture"
        make_cli_fixture(cli_fixture)
        cli_out = tmp / "cli-out"
        cli_manifest = build(cli_fixture, cli_out)
        check(not cli_manifest["test_coverage_audit"]["ui_required"], "CLI fixture should not require visual reports")
        write_complete_reports(cli_out)
        cli_result = verify(cli_out)
        check("ok: true" in cli_result.stdout, "non-UI fixture should verify without visual reports")

        stale_output_fixture = tmp / "stale-output-fixture"
        make_cli_fixture(stale_output_fixture)
        stale_owned_dir = stale_output_fixture / "old-test-output"
        stale_owned_dir.mkdir(parents=True)
        write(
            stale_owned_dir / ".full-repo-test-coverage-audit-artifacts.json",
            json.dumps(
                {
                    "owned_by": "full-repo-test-coverage-audit",
                    "repo_root": str(stale_output_fixture.resolve()),
                    "generated_artifacts": ["manifest.json"],
                },
                indent=2,
            ),
        )
        write(stale_owned_dir / "manifest.json", '{"stale": true}\n')
        stale_owned_out = tmp / "stale-owned-out"
        stale_owned_manifest = build(stale_output_fixture, stale_owned_out)
        queued_files = {item["rel_path"] for item in stale_owned_manifest["source_files"]}
        check(
            "old-test-output/.full-repo-test-coverage-audit-artifacts.json" not in queued_files,
            "owned stale test-coverage output directories should not be queued",
        )

        print("self-test ok")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
