#!/usr/bin/env python3
"""Fixture-based smoke tests for the full-repo-audit harness scripts."""

from __future__ import annotations

import json
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from shutil import rmtree, which


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "scripts" / "build_audit_batches.py"
VERIFY = ROOT / "scripts" / "verify_audit_results.py"


def positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} must be a positive integer; got {raw!r}") from exc
    if value < 1:
        raise SystemExit(f"{name} must be a positive integer; got {raw!r}")
    return value


TIMEOUT_SECONDS = positive_int_env("FULL_REPO_AUDIT_SELF_TEST_TIMEOUT", 30)
KEEP_TEMP_ON_FAILURE = os.environ.get("FULL_REPO_AUDIT_SELF_TEST_KEEP_TEMP", "").lower() in {"1", "true", "yes", "on"}
PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6360000002000100ffff03000006000557bfab9d00000000"
    "49454e44ae426082"
)
CURRENT_SCENARIO: str | None = None


def load_build_module():
    spec = importlib.util.spec_from_file_location("full_repo_audit_build", BUILD)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Could not load build module from {BUILD}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_verify_module():
    spec = importlib.util.spec_from_file_location("full_repo_audit_verify", VERIFY)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Could not load verify module from {VERIFY}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def set_scenario(name: str | None) -> None:
    global CURRENT_SCENARIO
    CURRENT_SCENARIO = name


def scenario_message(message: str) -> str:
    if not CURRENT_SCENARIO or message.startswith(f"{CURRENT_SCENARIO}: "):
        return message
    return f"{CURRENT_SCENARIO}: {message}"


@contextmanager
def scenario(name: str):
    previous = CURRENT_SCENARIO
    set_scenario(name)
    try:
        yield
    finally:
        set_scenario(previous)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(scenario_message(message))


@contextmanager
def self_test_workspace():
    tmp = tempfile.mkdtemp(prefix="full-repo-audit-self-test-")
    try:
        yield tmp
    except BaseException:
        if KEEP_TEMP_ON_FAILURE:
            print(f"Preserved self-test workspace after failure: {tmp}", file=sys.stderr)
        else:
            rmtree(tmp, ignore_errors=True)
        raise
    else:
        rmtree(tmp, ignore_errors=True)


def run(args: list[str], *, expect: int = 0, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            args,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=TIMEOUT_SECONDS,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        raise AssertionError(
            scenario_message(
                f"Command timed out after {TIMEOUT_SECONDS}s: {' '.join(args)}\n"
            f"stdout:\n{stdout}\n"
            f"stderr:\n{stderr}"
            )
        ) from exc
    if result.returncode != expect:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise AssertionError(scenario_message(f"Expected exit {expect}, got {result.returncode}: {' '.join(args)}"))
    return result


def check_output(result: subprocess.CompletedProcess[str], *needles: str) -> None:
    combined = f"{result.stdout}\n{result.stderr}"
    for needle in needles:
        check(needle in combined, f"Expected command output to contain {needle!r}")


class ScenarioRunner:
    def __init__(self) -> None:
        self.failures: list[tuple[str, str]] = []

    def case(self, name: str, func) -> None:
        try:
            with scenario(name):
                func()
        except AssertionError as exc:
            message = str(exc)
            prefix = f"{name}: "
            if message.startswith(prefix):
                message = message[len(prefix):]
            self.failures.append((name, message))

    def raise_if_failed(self) -> None:
        if not self.failures:
            return
        details = "\n".join(f"- {name}: {message}" for name, message in self.failures)
        raise AssertionError(f"{len(self.failures)} scenario(s) failed:\n{details}")


def verifier_case(
    runner: ScenarioRunner,
    name: str,
    manifest_path: Path,
    report_path: Path,
    *,
    expect: int = 0,
    needles: tuple[str, ...] = (),
    extra_args: tuple[str, ...] = (),
) -> None:
    def scenario() -> None:
        result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(manifest_path),
                "--reports",
                str(report_path),
                *extra_args,
            ],
            expect=expect,
        )
        if needles:
            check_output(result, *needles)

    runner.case(name, scenario)


def make_fixture(root: Path) -> None:
    write(
        root / "SKILL.md",
        """---
name: fixture-skill
description: Fixture skill contract.
---

# Fixture Skill
""",
    )
    write(root / ".env.example", "API_URL=https://example.invalid\n")
    write(root / ".env.example.local", "LOCAL_EXAMPLE_API_URL=https://example.invalid\n")
    write(root / "sample.env", "SAMPLE_API_URL=https://example.invalid\n")
    write(root / "example.env", "EXAMPLE_API_URL=https://example.invalid\n")
    write(root / "local.env.example", "LOCAL_API_URL=https://example.invalid\n")
    write(root / ".env.schema.json", '{"API_URL":"string"}\n')
    write(root / ".env.local", "SECRET_TOKEN=do-not-audit-by-default\n")
    write(root / ".envrc", "export SECRET_TOKEN=do-not-audit-by-default\n")
    write(root / "prod.env.local", "SECRET_TOKEN=do-not-audit-by-default\n")
    write(root / ".editorconfig", "root = true\n")
    write(root / ".gitattributes", "* text=auto\n")
    write(root / ".npmrc", "engine-strict=true\n")
    write(root / "Directory.Build.props", "<Project></Project>\n")
    write(root / "Directory.Packages.props", "<Project></Project>\n")
    write(root / "Fixture.sln", "Microsoft Visual Studio Solution File\n")
    write(root / "package-lock.json", '{"lockfileVersion":3}\n')
    write(root / "pnpm-lock.yaml", "lockfileVersion: '9.0'\n")
    write(root / "yarn.lock", "# yarn lockfile\n")
    write(root / "Cargo.lock", "# cargo lockfile\n")
    write(root / "poetry.lock", "# poetry lockfile\n")
    write(root / "uv.lock", "# uv lockfile\n")
    write(root / "flake.lock", "{}\n")
    write(root / "Pipfile", "[packages]\n")
    write(root / "Procfile", "web: npm start\n")
    write(root / "Rakefile", "task default: :test\n")
    write(root / "Justfile", "test:\n  echo test\n")
    write(root / ".tool-versions", "python 3.12.0\n")
    write(root / "vendor" / "vendored.py", "VENDORED = True\n")
    write(root / "node_modules" / "fixture" / "index.js", "module.exports = true;\n")
    for index in range(105):
        write(root / "node_modules" / "large" / f"file_{index}.js", f"module.exports = {index};\n")
    write(root / ".cache" / "tool" / "state.json", "{}\n")
    write(root / "scripts" / "deploy", "#!/usr/bin/env bash\necho deploy\n")
    write(root / ".husky" / "pre-commit", "npm test\n")
    write(
        root / "agents" / "openai.yaml",
        """interface:
  display_name: "Fixture Skill"
  short_description: "Fixture interface metadata"
  default_prompt: "Use $fixture-skill to test classification."
""",
    )
    write(root / "src" / "database.py", "def connect_database():\n    return 'connected'\n")
    write(root / "src" / "Fixture.csproj", "<Project Sdk=\"Microsoft.NET.Sdk\"></Project>\n")
    write(root / "packages" / "app" / "docs" / "behavior.md", "# Nested Behavior\n")
    write(root / "packages" / "app" / "PRODUCT.md", "# Package Product Contract\n")
    write(root / "locales" / "en.po", 'msgid "Save"\nmsgstr "Save"\n')
    write(root / "locales" / "en.json", '{"save":"Save"}\n')
    write(
        root / "locales" / "mixed.json",
        '{"save":"Save","metadata":{"route":"/internal/settings","featureFlag":"dark-mode"}}\n',
    )
    write(root / "locales" / "template.pot", 'msgid "Cancel"\nmsgstr ""\n')
    write(root / "locales" / "messages.properties", "save=Save\n")
    write(root / "locales" / "Localizable.strings", '"Save" = "Save";\n')
    write(root / "locales" / "app.arb", '{"save":"Save"}\n')
    write(root / "locales" / "ui.ftl", "save = Save\n")
    write(root / "locales" / "Resources.resx", "<root></root>\n")
    write(root / "locales" / "messages.xliff", "<xliff></xliff>\n")
    write(root / "messages" / "en.json", '{"cancel":"Cancel"}\n')
    write(root / "i18n" / "en.yaml", "save: Save\n")
    write(root / "ARCHITECTURE.md", "# Architecture\n")
    write(root / "PRODUCT.md", "# Product Contract\n")
    write(root / "app" / ".well-known" / "route.ts", "export function GET() { return new Response('ok'); }\n")
    write(root / ".storybook" / "main.ts", "export default { stories: [] };\n")
    write(root / "Views" / "MainWindow.axaml", '<Button Content="Run audit" />\n')
    write(root / "ios" / "Base.lproj" / "Main.storyboard", "<document><button title=\"Save\" /></document>\n")
    write(root / "ios" / "View.xib", "<document><button title=\"Cancel\" /></document>\n")
    write(root / "android" / "app" / "src" / "main" / "res" / "layout" / "activity_main.xml", '<LinearLayout><Button android:text="Save" /></LinearLayout>\n')
    write(root / "templates" / "welcome.hbs", "<button>{{label}}</button>\n")
    write(root / "templates" / "email.j2", "<button>{{ label }}</button>\n")
    write(root / ".gitlab" / "ci.yml", "stages: [test]\n")
    write(root / "assets" / "audit.svg", '<svg role="img" aria-label="Audit mark"><title>Audit mark</title></svg>\n')
    write(root / "dist" / "generated.ts", "export const generated = true;\n")
    write(root / ".next" / "server" / "app" / "page.js", "export default function Page() {}\n")
    write(root / ".nuxt" / "app.js", "export default {}\n")
    write(root / ".svelte-kit" / "output" / "server.js", "export const server = true;\n")
    write(root / ".terraform" / "generated.tf", "resource \"null_resource\" \"fixture\" {}\n")
    write(root / "src" / "foo---bar.ts", "export const dashed = true;\n")
    write_bytes(root / "src" / "late_binary.ts", b"a" * 5000 + b"\0tail\n")
    write(root / "scratch.local.py", "LOCAL_ONLY = True\n")
    write(root / ".gitignore", "dist/\n.next/\n.nuxt/\n.svelte-kit/\n.terraform/\n.env*\nvendor/\nnode_modules/\n.cache/\n*.local.py\n")
    write(
        root / "src" / "components" / "SaveButton.tsx",
        """export function SaveButton() {
  return (
    <div>
      <button onClick={() => console.log("TODO save")}>Save changes</button>
      <button onClick={() => alert("delete")}>Delete</button>
    </div>
  );
}
""",
    )


def write_reports(root: Path, manifest_path: Path) -> tuple[
    Path, Path, Path, Path, Path, Path, Path, Path, Path, Path, Path, Path
]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    run_id = manifest["run_id"]
    repo_root = Path(manifest["repo_root"])
    source_files = manifest["source_files"]
    coverage_units = manifest.get("coverage_units") or [
        {
            "unit_id": item["rel_path"],
            "rel_path": item["rel_path"],
            "sha256": item["sha256"],
            "start_line": None,
            "end_line": None,
        }
        for item in source_files
    ]
    incomplete = root / "reports" / "incomplete" / "batch_001.md"
    unchecked = root / "reports" / "unchecked" / "batch_001.md"
    missing_sections = root / "reports" / "missing-sections" / "batch_001.md"
    wrong_batch = root / "reports" / "wrong-batch" / "batch_001.md"
    extra_section = root / "reports" / "extra-section" / "batch_001.md"
    missing_purpose = root / "reports" / "missing-purpose" / "batch_001.md"
    malformed_pipe = root / "reports" / "malformed-pipe" / "batch_001.md"
    stale_hash = root / "reports" / "stale-hash" / "batch_001.md"
    invalid_utf8 = root / "reports" / "invalid-utf8" / "batch_001.md"
    invalid_filename = root / "reports" / "renamed_report.md"
    complete = root / "reports" / "valid" / "batch_001.md"
    wrong_run_id = root / "reports" / "wrong-run-id" / "batch_001.md"
    write(root / "reports" / "README.md", "# Working notes, not a report\n\nMentions batch_999 in prose.\n")

    def purpose_for(rel_path: str) -> str:
        if "#L" in rel_path:
            source_path, line_range = rel_path.split("#", 1)
            return f"fixture-owned source range {line_range} for {source_path}"
        if "#B" in rel_path:
            source_path, byte_range = rel_path.split("#", 1)
            return f"fixture-owned source byte range {byte_range} for {source_path}"
        if rel_path == "src/database.py":
            return r"data helper with escaped A \| B purpose"
        if rel_path == "src/foo---bar.ts":
            return "dashed source filename"
        if rel_path.startswith("locales/") or rel_path.startswith("messages/") or rel_path.startswith("i18n/"):
            return f"localized UI message catalog for {rel_path}"
        return f"fixture-owned source role for {rel_path}"

    def rows(
        *,
        only_first: bool = False,
        unchecked_file: str | None = None,
        missing_purpose_file: str | None = None,
        bad_hash_file: str | None = None,
        extra_column_file: str | None = None,
    ) -> str:
        selected = coverage_units[:1] if only_first else coverage_units
        lines = []
        for item in selected:
            rel_path = item.get("unit_id") or item["rel_path"]
            status = "UNCHECKED" if rel_path == unchecked_file else "CHECKED"
            sha = "0" * 64 if rel_path == bad_hash_file else item["sha256"]
            purpose = "" if rel_path == missing_purpose_file else purpose_for(rel_path)
            line = f"| `{rel_path}` | {status} | `{sha}` | {purpose} |"
            if rel_path == extra_column_file:
                line = f"| `{rel_path}` | {status} | `{sha}` | {purpose} | extra column |"
            lines.append(line)
        return "\n".join(lines)

    def has_known_fixture_finding() -> bool:
        return any(item["rel_path"] == "src/components/SaveButton.tsx" for item in source_files)

    def no_finding_notes() -> str:
        return "\n".join(
            f"- `{item.get('unit_id') or item['rel_path']}`: Fixture report."
            for item in coverage_units
            if item["rel_path"] != "src/components/SaveButton.tsx"
        )

    def visible_text_for(rel_path: str) -> str:
        text = (repo_root / rel_path).read_text(encoding="utf-8", errors="ignore")
        preferred = (
            "Save changes",
            "Delete",
            "Run audit",
            "Fixture Skill",
            "Fixture skill contract.",
            "Fixture interface metadata",
            "Use $fixture-skill to test classification.",
            "Audit mark",
            "Cancel",
            "Save",
            "API_URL",
            "button",
        )
        for value in preferred:
            if value in text:
                return value
        match = re.search(r"['\"]([^'\"]{3,80})['\"]", text)
        if match:
            return match.group(1)
        match = re.search(r">\s*([^<]{3,80})\s*<", text)
        if match:
            return match.group(1).strip()
        match = re.search(r"[A-Za-z][A-Za-z0-9 _.-]{2,80}", text)
        return match.group(0).strip() if match else "None found"

    def visible_texts_for(rel_path: str) -> list[str]:
        text = (repo_root / rel_path).read_text(encoding="utf-8", errors="ignore")
        preferred = (
            "Save changes",
            "Delete",
            "Run audit",
            "Fixture Skill",
            "Fixture skill contract.",
            "Fixture interface metadata",
            "Use $fixture-skill to test classification.",
            "Audit mark",
            "Cancel",
            "Save",
            "API_URL",
            "button",
        )
        values = []
        for value in preferred:
            if value in text and value not in values:
                values.append(value)
        if not values:
            values.append(visible_text_for(rel_path))
        return values

    def interface_inventory() -> str:
        interface_files = [item for item in source_files if item.get("interface_relevant") is True]
        if not interface_files:
            return "No interface-relevant files in this batch."
        rows = [
            "| File | Surface | Visible text/control/message | Expected behavior path | Actual implementation notes |",
            "| --- | --- | --- | --- | --- |",
        ]
        for item in interface_files:
            for visible_text in visible_texts_for(item["rel_path"]):
                rows.append(
                    f"| `{item['rel_path']}` | fixture | {visible_text} | Static fixture audit path for `{item['rel_path']}` source-owned UI metadata or handler review. | Verified `{item['rel_path']}` contains `{visible_text}` and its fixture behavior is covered by this smoke test report. |"
                )
        return "\n".join(rows)

    def findings() -> str:
        if not has_known_fixture_finding():
            return "No findings."
        return """### P2 - Save button uses placeholder console-only behavior
- Files: `src/components/SaveButton.tsx`
- Evidence: `SaveButton` renders a `Save changes` button whose `onClick` handler only calls `console.log("TODO save")`.
- Interface evidence: Visible control text `Save changes`.
- Expected behavior/standard: A save button should persist or dispatch the save action, surface loading/error state, and avoid presenting console-only placeholder behavior as complete.
- Gap: The fixture button exposes a save action but has only TODO console behavior.
- Suggested direction: Wire the handler to the real save path and cover the user workflow with a focused test."""

    def report(batch_id: str, body_rows: str, *, include_tail: bool = True, report_run_id: str = run_id) -> str:
        tail = ""
        if include_tail:
            tail = f"""
## Interface Inventory
{interface_inventory()}

## Findings
{findings()}

## No Finding Notes
{no_finding_notes()}

## Open Questions
None.
"""
        return f"""## Run ID
{report_run_id}

## Batch ID
{batch_id}

## Batch Summary
Fixture report.

## File Coverage
| File | Status | SHA-256 | Purpose |
| --- | --- | --- | --- |
{body_rows}

{tail}"""

    write(incomplete, report("batch_001", rows(only_first=True), include_tail=False))
    write(unchecked, report("batch_001", rows(unchecked_file="SKILL.md")))
    write(missing_sections, report("batch_001", rows(), include_tail=False))
    write(wrong_batch, report("batch_999", rows()))
    write(extra_section, report("batch_001", rows()) + "\n## Extra Section\nNope.\n")
    write(missing_purpose, report("batch_001", rows(missing_purpose_file="Views/MainWindow.axaml")))
    write(complete, report("batch_001", rows()))
    write(wrong_run_id, report("batch_001", rows(), report_run_id="wrong-run-id"))
    complete_text = complete.read_text(encoding="utf-8")
    write(invalid_filename, complete_text)
    write(stale_hash, report("batch_001", rows(bad_hash_file="src/foo---bar.ts")))
    write(
        malformed_pipe,
        report("batch_001", rows(extra_column_file="src/database.py")),
    )
    invalid_utf8.parent.mkdir(parents=True, exist_ok=True)
    invalid_utf8.write_bytes(b"\xff\n")
    return (
        incomplete,
        unchecked,
        missing_sections,
        wrong_batch,
        extra_section,
        missing_purpose,
        malformed_pipe,
        stale_hash,
        invalid_utf8,
        invalid_filename,
        wrong_run_id,
        complete,
    )


def install_report(output_dir: Path, source_report: Path, batch_id: str = "batch_001") -> Path:
    target = output_dir / "reports" / f"{batch_id}.md"
    write(target, source_report.read_text(encoding="utf-8"))
    return target


def complete_effort_ledger(output_dir: Path, *, fallback: bool = False) -> None:
    ledger_path = output_dir / "effort_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    interface_files = manifest.get("journey_audit", {}).get("interface_files") or []
    journey_sources = "\n".join(f"- `{rel_path}`: Fixture interface source." for rel_path in interface_files)
    visual_sources = ", ".join(f"`{rel_path}`" for rel_path in interface_files)
    journey_rows = "\n".join(
        f"| Fixture audit | Inspect `{rel_path}` | `{rel_path}` | Audit-visible element | critical-always | Fixture report information | Source-only fixture | self-test fixture mode |"
        for rel_path in interface_files
    )
    ledger["subagent_capability_check"] = {
        "status": "completed",
        "spawn_tool": "self-test",
        "can_set_reasoning_effort": not fallback,
        "notes": "self-test ledger completion",
    }
    ledger["lead"] = {
        "status": "completed",
        "required_reasoning_effort": "xhigh",
        "actual_reasoning_effort": "xhigh",
        "agent_id": "lead-self-test",
        "notes": None,
    }
    ledger["fallback_mode"] = {"active": fallback, "reason": "self-test fallback" if fallback else None}
    pruned_review = ledger.get("pruned_directory_review")
    if isinstance(pruned_review, dict) and pruned_review.get("status") != "not-applicable":
        pruned_review["status"] = "completed"
        pruned_review["notes"] = "self-test reviewed pruned directory source-like samples and kept them excluded intentionally"
        for decision in pruned_review.get("decisions", []):
            if isinstance(decision, dict):
                decision["decision"] = "excluded-with-rationale"
                decision["rationale"] = "Fixture generated directory is intentionally excluded after lead review."
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(exist_ok=True)
    for worker_key, worker_label in (
        ("journey_source_worker", "journey_source"),
        ("visual_journey_worker", "visual_journey"),
    ):
        worker = ledger.get(worker_key)
        if not isinstance(worker, dict) or worker.get("status") == "not-applicable":
            continue
        worker["status"] = "completed"
        worker["agent_id"] = None if fallback else f"agent-{worker_label}"
        worker["actual_reasoning_effort"] = "manual-fallback" if fallback else "low"
        worker["runtime_provenance"] = (
            f"self-test manual fallback {worker_label} execution"
            if fallback
            else f"self-test spawned low-effort {worker_label} execution"
        )
        report = worker.get("report")
        if isinstance(report, str) and report:
            if worker_label == "journey_source":
                report_body = f"""## Run ID
{ledger['run_id']}

## Worker
journey_source

## Journey Sources
{journey_sources or '- No interface files.'}

## Proposed Journeys
- Confirmed journey: Run the fixture audit safely.

## UI Source Journey Checks
| Journey | Step | Files | Primary navigation/decision elements | Relevance estimate | Required information | Mobile/Desktop availability | Test mode evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
{journey_rows or '| Fixture audit | No interface source | None | None | rare-under-5-percent | None | Not applicable | self-test fixture mode |'}

## Findings
No findings.

## Open Questions
None.
"""
            else:
                report_body = f"""## Run ID
{ledger['run_id']}

## Worker
visual_journey

## Visual Tooling
- Fixture test mode is `scripts/self_test.py`; no visual UI is present, so visual checks are not applicable.
- Repo-owned interface files reviewed for visual applicability: {visual_sources or 'none'}.

## Visual Journey Checks
| Journey | Viewport | Route/screen | Evidence | Navigation visibility | Decision information | Visual quality | Result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Fixture audit | desktop | CLI fixture | self-test fixture mode | not applicable | source-only | not applicable | pass |
| Fixture audit | narrow mobile | CLI fixture | self-test fixture mode | not applicable | source-only | not applicable | pass |

## Findings
No findings.

## Open Questions
None.
"""
            write(
                output_dir / report,
                report_body,
            )
    for batch in ledger["batches"]:
        batch["status"] = "completed"
        if fallback:
            batch["agent_id"] = None
            batch["actual_reasoning_effort"] = "manual-fallback"
            batch["runtime_provenance"] = "self-test manual fallback batch execution"
        else:
            batch["agent_id"] = f"agent-{batch['batch_id']}"
            batch["actual_reasoning_effort"] = "low"
            batch["runtime_provenance"] = "self-test spawned low-effort batch execution"
    write(ledger_path, json.dumps(ledger, indent=2))


def assert_manifest(manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    check(manifest["scope_warning_count"] == 0, "default fixture should not have scope warnings")
    check(manifest["pruned_directory_review_hint_count"] >= 1, "default fixture should surface pruned source-like directory hints")
    check(manifest["pruned_directory_review_hints"], "manifest should list pruned source-like directory hints")
    check(manifest["coverage_invariants"]["all_source_files_queued_exactly_once"], "batch coverage invariant failed")
    check(manifest["coverage_invariants"]["all_coverage_units_queued_exactly_once"], "coverage unit invariant failed")
    check(manifest["coverage_unit_count"] >= manifest["source_file_count"], "coverage units should cover every source file")
    check(manifest["run_id"], "manifest should include a run_id")
    check(all(item.get("sha256") for item in manifest["source_files"]), "every source file should include sha256")
    check(str(VERIFY) in manifest["verifier_command"], "manifest should include absolute verifier command")
    expected_reports_dir = str((manifest_path.parent / "reports").resolve())
    check(expected_reports_dir in manifest["verifier_command"], "manifest should point verification at reports/")
    check(manifest["reports_dir"] == expected_reports_dir, "manifest should record reports_dir")
    owner_marker = json.loads((manifest_path.parent / ".full-repo-audit-artifacts.json").read_text(encoding="utf-8"))
    check(owner_marker["owned_by"] == "full-repo-audit", "output directory should include ownership marker")
    check("batch_001.md" in owner_marker["generated_artifacts"], "ownership marker should record generated batch prompts")
    check("effort_ledger.json" in owner_marker["generated_artifacts"], "ownership marker should record effort ledger")
    marker = json.loads((manifest_path.parent / "queue_complete.json").read_text(encoding="utf-8"))
    check(marker["run_id"] == manifest["run_id"], "completion marker run_id should match manifest")
    check(marker["phase"] == "queue_generated", "completion marker should label queue generation phase")
    check(marker["audit_verified"] is False, "completion marker should not claim verified audit coverage")
    check(marker["batch_count"] == manifest["batch_count"], "completion marker should include batch_count")
    check(marker["effort_ledger"] == "effort_ledger.json", "completion marker should reference effort ledger")
    check(marker["ownership_marker"] == ".full-repo-audit-artifacts.json", "completion marker should reference ownership marker")
    check(
        marker["marker_semantics"] == "Queue artifacts were generated; subagent reports and effort ledger still require verifier completion.",
        "completion marker should record queue marker semantics",
    )
    check(not (manifest_path.parent / "audit_complete.json").exists(), "legacy audit_complete marker should not be generated")
    owner_marker = json.loads((manifest_path.parent / ".full-repo-audit-artifacts.json").read_text(encoding="utf-8"))
    ledger = json.loads((manifest_path.parent / "effort_ledger.json").read_text(encoding="utf-8"))
    check(ledger["run_id"] == manifest["run_id"], "effort ledger run_id should match manifest")
    check(ledger["effort_verification_scope"] == "ledger-recorded", "effort ledger should disclose ledger-recorded effort scope")
    check(len(ledger["batches"]) == manifest["batch_count"], "effort ledger should scaffold each batch")
    if manifest["pruned_directory_review_hint_count"]:
        check(ledger["pruned_directory_review"]["status"] == "pending", "pruned directory review should be pending when hints exist")
        pruned_decisions = ledger["pruned_directory_review"].get("decisions")
        check(isinstance(pruned_decisions, list), "pruned directory review should scaffold per-hint decisions")
        check(
            len(pruned_decisions) == manifest["pruned_directory_review_hint_count"],
            "pruned directory review should include one decision row per hint",
        )
    check("journey_audit" in manifest, "manifest should include journey audit metadata")
    if manifest["interface_file_count"]:
        check((manifest_path.parent / "journey_audit.md").is_file(), "journey source prompt should be generated for UI repos")
        check((manifest_path.parent / "visual_journey_audit.md").is_file(), "visual journey prompt should be generated for UI repos")
        check("journey_audit.md" in owner_marker["generated_artifacts"], "ownership marker should record journey source prompt")
        check("visual_journey_audit.md" in owner_marker["generated_artifacts"], "ownership marker should record visual journey prompt")
        check(ledger["journey_source_worker"]["status"] == "pending", "journey source worker should be scaffolded")
        check(ledger["visual_journey_worker"]["status"] == "pending", "visual journey worker should be scaffolded")
        journey_prompt_text = (manifest_path.parent / "journey_audit.md").read_text(encoding="utf-8")
        visual_prompt_text = (manifest_path.parent / "visual_journey_audit.md").read_text(encoding="utf-8")
        for required_field in (
            "- Files:",
            "- Evidence:",
            "- Interface evidence:",
            "- Expected behavior/standard:",
            "- Gap:",
            "- Suggested direction:",
        ):
            check(required_field in journey_prompt_text, "journey source prompt should spell out verifier-required finding fields")
            check(required_field in visual_prompt_text, "visual journey prompt should spell out verifier-required finding fields")
        check(
            "screenshot, trace, recording, or other artifact" in visual_prompt_text,
            "visual journey prompt should require command/tool and visual artifact evidence when applicable",
        )

    files = {item["rel_path"]: item for item in manifest["source_files"]}
    expected_files = {
            ".env.example",
            ".env.example.local",
            "sample.env",
            "example.env",
            ".editorconfig",
            "local.env.example",
            ".env.schema.json",
            "Cargo.lock",
            ".gitattributes",
            ".gitignore",
            ".npmrc",
            "Directory.Build.props",
            "Directory.Packages.props",
            "Fixture.sln",
            "Justfile",
            "Pipfile",
            "Procfile",
            "Rakefile",
            "SKILL.md",
            "ARCHITECTURE.md",
            "PRODUCT.md",
            "flake.lock",
            "package-lock.json",
            "pnpm-lock.yaml",
            "poetry.lock",
            "uv.lock",
            "yarn.lock",
            ".tool-versions",
            ".gitlab/ci.yml",
            ".husky/pre-commit",
            "android/app/src/main/res/layout/activity_main.xml",
            "agents/openai.yaml",
            "app/.well-known/route.ts",
            "assets/audit.svg",
            "i18n/en.yaml",
            "locales/en.po",
            "locales/en.json",
            "locales/mixed.json",
            "locales/template.pot",
            "locales/messages.properties",
            "locales/Localizable.strings",
            "locales/app.arb",
            "locales/ui.ftl",
            "locales/Resources.resx",
            "locales/messages.xliff",
            "messages/en.json",
            "packages/app/docs/behavior.md",
            "packages/app/PRODUCT.md",
            ".storybook/main.ts",
            "scripts/deploy",
            "templates/email.j2",
            "templates/welcome.hbs",
            "Views/MainWindow.axaml",
            "ios/Base.lproj/Main.storyboard",
            "ios/View.xib",
            "src/components/SaveButton.tsx",
            "src/Fixture.csproj",
            "src/database.py",
            "src/foo---bar.ts",
    }
    missing_expected_files = sorted(expected_files - set(files))
    check(not missing_expected_files, f"source files missed expected fixture entries: {missing_expected_files}")
    check(
        manifest["source_file_count"] >= len(expected_files),
        "source_file_count should include at least the representative fixture inventory",
    )
    check(
        manifest["interface_file_count"] >= 21,
        "interface_file_count should include representative skill metadata, catalogs, native UI, SVG, templates, UI component, and XAML",
    )
    check(files["SKILL.md"]["interface_relevant"] is True, "SKILL.md frontmatter should be interface-relevant")
    check(files["agents/openai.yaml"]["interface_relevant"] is True, "openai.yaml should be interface-relevant")
    check(files["app/.well-known/route.ts"]["interface_relevant"] is False, ".well-known route should not be UI-relevant")
    check(files["assets/audit.svg"]["interface_relevant"] is True, "audit.svg should be interface-relevant")
    check(files["i18n/en.yaml"]["kind"] == "source/message-catalog", "YAML catalogs under i18n should be message catalogs")
    check(files["i18n/en.yaml"]["interface_relevant"] is True, "YAML catalogs should be interface-relevant")
    check(files["locales/en.po"]["interface_relevant"] is True, "PO catalogs should be interface-relevant")
    check(files["locales/en.json"]["kind"] == "source/message-catalog", "JSON catalogs under locales should be message catalogs")
    check(files["locales/en.json"]["interface_relevant"] is True, "JSON catalogs should be interface-relevant")
    check(files["locales/messages.properties"]["interface_relevant"] is True, "properties catalogs should be interface-relevant")
    check(files["locales/Localizable.strings"]["interface_relevant"] is True, "strings catalogs should be interface-relevant")
    check(files["locales/app.arb"]["interface_relevant"] is True, "ARB catalogs should be interface-relevant")
    check(files["locales/ui.ftl"]["interface_relevant"] is True, "Fluent catalogs should be interface-relevant")
    check(files["locales/Resources.resx"]["interface_relevant"] is True, "RESX catalogs should be interface-relevant")
    check(files["locales/messages.xliff"]["interface_relevant"] is True, "XLIFF catalogs should be interface-relevant")
    check(files["messages/en.json"]["kind"] == "source/message-catalog", "JSON catalogs under messages should be message catalogs")
    check(files[".editorconfig"]["kind"] == "source/config", ".editorconfig should be audited as source config")
    check(files[".env.example.local"]["kind"] == "source/config", ".env.example.local should be audited as env example config")
    check(files["sample.env"]["kind"] == "source/config", "sample.env should be audited as env sample config")
    check(files["example.env"]["kind"] == "source/config", "example.env should be audited as env sample config")
    check(files[".gitattributes"]["kind"] == "source/config", ".gitattributes should be audited as source config")
    check(files[".gitignore"]["kind"] == "source/config", ".gitignore should be audited as source config")
    check(files[".npmrc"]["kind"] == "source/config", ".npmrc should be audited as source config")
    check(files["Directory.Build.props"]["kind"] == "source/config", "Directory.Build.props should be audited as source config")
    check(files["Directory.Packages.props"]["kind"] == "source/config", "Directory.Packages.props should be audited as source config")
    check(files[".gitlab/ci.yml"]["kind"] == "config", ".gitlab config should be audited")
    check(files["Fixture.sln"]["kind"] == "config", ".sln files should be audited as config")
    check(files["src/Fixture.csproj"]["kind"] == "config", ".csproj files should be audited as config")
    check(files["package-lock.json"]["kind"] == "source/config", "package-lock.json should be audited as source config")
    check(files["pnpm-lock.yaml"]["kind"] == "source/config", "pnpm-lock.yaml should be audited as source config")
    check(files["yarn.lock"]["kind"] == "source/config", "yarn.lock should be audited as source config")
    check(files["Cargo.lock"]["kind"] == "source/config", "Cargo.lock should be audited as source config")
    check(files["poetry.lock"]["kind"] == "source/config", "poetry.lock should be audited as source config")
    check(files["uv.lock"]["kind"] == "source/config", "uv.lock should be audited as source config")
    check(files["flake.lock"]["kind"] == "source/config", "flake.lock should be audited as source config")
    check(files["Pipfile"]["kind"] == "source/config", "Pipfile should be audited as source config")
    check(files["Procfile"]["kind"] == "source/config", "Procfile should be audited as source config")
    check(files["Rakefile"]["kind"] == "source/config", "Rakefile should be audited as source config")
    check(files["Justfile"]["kind"] == "source/config", "Justfile should be audited as source config")
    check(files[".tool-versions"]["kind"] == "source/config", ".tool-versions should be audited as source config")
    check(files["scripts/deploy"]["kind"] == "source/script", "extensionless scripts under scripts/ should be audited")
    check(files[".husky/pre-commit"]["kind"] == "source/script", "extensionless Husky hooks should be audited")
    check(files["templates/welcome.hbs"]["interface_relevant"] is True, "Handlebars templates should be interface-relevant")
    check(files["templates/email.j2"]["interface_relevant"] is True, "Jinja templates should be interface-relevant")
    check(files["packages/app/PRODUCT.md"]["kind"] == "source/contract", "nested PRODUCT.md should be source/contract")
    check(files["Views/MainWindow.axaml"]["interface_relevant"] is True, "MainWindow.axaml should be interface-relevant")
    check(files["ios/Base.lproj/Main.storyboard"]["interface_relevant"] is True, "storyboard files should be interface-relevant")
    check(files["ios/View.xib"]["interface_relevant"] is True, "xib files should be interface-relevant")
    check(files["android/app/src/main/res/layout/activity_main.xml"]["interface_relevant"] is True, "Android layout XML should be interface-relevant")
    check(files["src/components/SaveButton.tsx"]["interface_relevant"] is True, "SaveButton should be interface-relevant")
    check(files["src/database.py"]["interface_relevant"] is False, "database.py should not be interface-relevant")
    check(files["src/foo---bar.ts"]["interface_relevant"] is False, "foo---bar.ts should not be interface-relevant")


def assert_exclusions(excluded_path: Path) -> None:
    excluded = json.loads(excluded_path.read_text(encoding="utf-8"))
    reasons = {item["path"]: item["reason"] for item in excluded}
    check(".env.local" in reasons, ".env.local should be excluded by default")
    check(
        reasons[".env.local"].startswith("secret-bearing env file excluded"),
        ".env.local should be excluded as secret-bearing env file",
    )
    check(".envrc" in reasons, ".envrc should be excluded by default")
    check(
        reasons[".envrc"].startswith("secret-bearing env file excluded"),
        ".envrc should be excluded as secret-bearing env file",
    )
    check(
        reasons["prod.env.local"].startswith("secret-bearing env file excluded"),
        "prod.env.local should be excluded as secret-bearing env file",
    )
    check(reasons.get("src/late_binary.ts") == "binary file content", "late NUL bytes should exclude binary file content")
    dir_rows = {item["path"]: item for item in excluded if item.get("entry_type") == "directory"}
    check("dist" in dir_rows, "dist directory should be summarized in exclusions")
    check("node_modules" in dir_rows, "node_modules directory should be summarized in exclusions")
    check(".cache" in dir_rows, ".cache tooling directory should be summarized in exclusions")
    check(dir_rows["dist"]["file_count"] >= 1, "directory exclusions should include file counts")
    check(
        dir_rows["dist"].get("contains_source_like_samples") is True,
        "generated directory exclusions should flag source-like samples for lead review",
    )
    check("dist/generated.ts" in dir_rows["dist"].get("source_like_sample_paths", []), "source-like pruned samples should be listed")
    check(dir_rows["node_modules"]["sample_paths"], "directory exclusions should include sample paths")
    check(dir_rows["node_modules"]["file_count"] == 100, "large directory exclusion counts should be capped")
    check(dir_rows["node_modules"]["file_count_capped"] is True, "large directory exclusions should mark capped counts")


def assert_generated_included(manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = {item["rel_path"] for item in manifest["source_files"]}
    check("dist/generated.ts" in files, "--include-generated should include dist/generated.ts")
    check(".next/server/app/page.js" in files, "--include-generated should include .next output")
    check(".nuxt/app.js" in files, "--include-generated should include .nuxt output")
    check(".svelte-kit/output/server.js" in files, "--include-generated should include .svelte-kit output")
    check(".terraform/generated.tf" in files, "--include-generated should include .terraform output")
    check("scratch.local.py" not in files, "--include-generated should not include unrelated ignored local files")


def assert_env_included(manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = {item["rel_path"] for item in manifest["source_files"]}
    check(".env.local" in files, "--include-env should include .env.local")
    check(".envrc" in files, "--include-env should include .envrc")
    check("prod.env.local" in files, "--include-env should include prod.env.local")
    check("scratch.local.py" not in files, "--include-env should not include unrelated ignored local files")


def assert_env_included_without_config(manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = {item["rel_path"]: item for item in manifest["source_files"]}
    check(files["prod.env.local"]["kind"] == "config", "--include-env should include prod.env.local even with --no-include-config")
    check(files[".env.local"]["kind"] == "config", "--include-env should include .env.local even with --no-include-config")
    check(files[".envrc"]["kind"] == "config", "--include-env should include .envrc even with --no-include-config")


def assert_vendor_included(manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = {item["rel_path"] for item in manifest["source_files"]}
    check("vendor/vendored.py" in files, "--include-vendor should include vendor/vendored.py")
    check("scratch.local.py" not in files, "--include-vendor should not include unrelated ignored local files")


def assert_message_catalogs_without_config(manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = {item["rel_path"]: item for item in manifest["source_files"]}
    check(files["locales/en.json"]["kind"] == "source/message-catalog", "--no-include-config should still include locales/en.json")
    check(files["messages/en.json"]["kind"] == "source/message-catalog", "--no-include-config should still include messages/en.json")
    check(files["i18n/en.yaml"]["kind"] == "source/message-catalog", "--no-include-config should still include i18n/en.yaml")


def assert_generated_excluded(manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = {item["rel_path"] for item in manifest["source_files"]}
    check("dist/generated.ts" not in files, "dist/generated.ts should be excluded by default")
    check(".next/server/app/page.js" not in files, ".next output should be excluded by default")
    check("vendor/vendored.py" not in files, "vendor/vendored.py should be excluded by default")
    check("node_modules/fixture/index.js" not in files, "node_modules files should be excluded by default")
    check("scratch.local.py" not in files, "ignored local scratch files should be excluded by default")


def assert_scope_warning(manifest_path: Path, excluded_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    excluded = json.loads(excluded_path.read_text(encoding="utf-8"))
    check(manifest["scope_warning_count"] == 1, "explicitly excluded source should create one scope warning")
    warning = next(item for item in excluded if item["path"] == "src/database.py")
    check(warning["scope_warning"] is True, "src/database.py exclusion should be a scope warning")


def main() -> int:
    with scenario("self-test scenario labeling"):
        try:
            check(False, "intentional scenario-label probe")
        except AssertionError as exc:
            check("self-test scenario labeling" in str(exc), "scenario labels should annotate direct check failures")
        else:
            raise AssertionError("intentional scenario-label probe did not fail")

    set_scenario("startup and environment validation")
    if not which("git"):
        print("self-test requires git on PATH", file=sys.stderr)
        return 2

    invalid_timeout_env = os.environ.copy()
    invalid_timeout_env["FULL_REPO_AUDIT_SELF_TEST_TIMEOUT"] = "not-an-int"
    invalid_timeout_result = run(
        [sys.executable, str(Path(__file__))],
        expect=1,
        env=invalid_timeout_env,
    )
    check_output(invalid_timeout_result, "FULL_REPO_AUDIT_SELF_TEST_TIMEOUT must be a positive integer")

    with scenario("coverage invariant helper"):
        build_module = load_build_module()
        duplicate_whole = build_module.AuditUnit(
            unit_id="src/a.py",
            rel_path="src/a.py",
            size_bytes=1,
            kind="source",
            interface_relevant=False,
            sha256="0" * 64,
        )
        ranged_one = build_module.AuditUnit(
            unit_id="src/b.py#L1-L10",
            rel_path="src/b.py",
            size_bytes=1,
            kind="source",
            interface_relevant=False,
            sha256="1" * 64,
            start_line=1,
            end_line=10,
        )
        ranged_two = build_module.AuditUnit(
            unit_id="src/b.py#L11-L20",
            rel_path="src/b.py",
            size_bytes=1,
            kind="source",
            interface_relevant=False,
            sha256="1" * 64,
            start_line=11,
            end_line=20,
        )
        duplicates = build_module.duplicate_whole_file_paths_for_batches(
            [[duplicate_whole, ranged_one], [duplicate_whole, ranged_two]]
        )
        check(duplicates == ["src/a.py"], "whole-file duplicate invariant should ignore intentional line-range splits")

    with scenario("asset metadata bounded read"):
        verify_module = load_verify_module()

        class FakeAssetHandle:
            def __init__(self, owner):
                self.owner = owner

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _traceback):
                return False

            def read(self, size=-1):
                self.owner.read_sizes.append(size)
                header = (
                    b"\x89PNG\r\n\x1a\n"
                    + b"\x00\x00\x00\rIHDR"
                    + (17).to_bytes(4, "big")
                    + (23).to_bytes(4, "big")
                )
                return header + (b"0" * 1024)

        class FakeAssetPath:
            suffix = ".png"

            def __init__(self):
                self.read_sizes: list[int] = []

            def open(self, _mode):
                return FakeAssetHandle(self)

        fake_asset = FakeAssetPath()
        metadata = verify_module.asset_metadata_for(fake_asset)
        check(metadata["valid"], "asset metadata should parse dimensions from a bounded prefix")
        check(metadata["width"] == 17 and metadata["height"] == 23, "asset metadata should preserve parsed dimensions")
        check(
            fake_asset.read_sizes == [verify_module.ASSET_METADATA_READ_LIMIT],
            "asset metadata should read a bounded prefix instead of the full file",
        )
        svg_asset = Path(tempfile.mkdtemp()) / "logo.svg"
        try:
            write(
                svg_asset,
                '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="24" viewBox="0 0 32 24"><rect width="32" height="24"/></svg>\n',
            )
            svg_metadata = verify_module.asset_metadata_for(svg_asset)
            check(svg_metadata["valid"], "SVG UI asset metadata should be parsed as a supported asset type")
            check(svg_metadata["mime"] == "image/svg+xml", "SVG UI asset metadata should expose image/svg+xml MIME")
            check(svg_metadata["width"] == 32 and svg_metadata["height"] == 24, "SVG UI asset metadata should parse dimensions")
            check(
                verify_module.asset_evidence_matches_metadata(
                    "source UI asset: MIME image/svg+xml, dimensions 32x24, screenshot-ready logo.",
                    svg_metadata,
                ),
                "SVG UI asset evidence should match MIME and dimensions",
            )
        finally:
            rmtree(svg_asset.parent, ignore_errors=True)

    with self_test_workspace() as tmp:
        set_scenario("fixture generation and primary queue build")
        base = Path(tmp)
        scenario_runner = ScenarioRunner()
        fixture = base / "fixture"
        output = base / "audit-output"
        custom_run_output = base / "audit-output-custom-run"
        reuse_output = base / "audit-output-reuse"
        generated_output = base / "audit-output-generated"
        env_output = base / "audit-output-env"
        env_no_config_output = base / "audit-output-env-no-config"
        vendor_output = base / "audit-output-vendor"
        excluded_output = base / "audit-output-excluded"
        no_config_output = base / "audit-output-no-config"
        byte_output = base / "audit-output-byte-limit"
        fallback_output = base / "audit-output-fallback"
        hidden_output = base / "hidden-output"
        hidden_forced_file_output = base / "hidden-forced-file-output"
        hidden_forced_glob_output = base / "hidden-forced-glob-output"
        non_git_forced_file_output = base / "non-git-forced-file-output"
        non_git_forced_glob_output = base / "non-git-forced-glob-output"
        broad_glob_output = base / "broad-glob-output"
        asset_warning_output = base / "asset-warning-output"
        asset_include_output = base / "asset-include-output"
        spaced_output = base / "audit output with spaces"
        reports_dir = base / "reports"
        make_fixture(fixture)
        run(["git", "-C", str(fixture), "init"], expect=0)
        run(["git", "-C", str(fixture), "add", ".editorconfig", ".gitattributes", ".gitignore", ".npmrc", ".tool-versions", "SKILL.md", "sample.env", "example.env", "local.env.example", "ARCHITECTURE.md", "PRODUCT.md", "Cargo.lock", "Directory.Build.props", "Directory.Packages.props", "Fixture.sln", "Justfile", "Pipfile", "Procfile", "Rakefile", "flake.lock", "package-lock.json", "pnpm-lock.yaml", "poetry.lock", "uv.lock", "yarn.lock", ".gitlab", ".husky", "agents/openai.yaml", "android", "app", "assets", "i18n", "ios", "locales", "messages", "scripts", "src", "templates", "packages", ".storybook"])
        run(["git", "-C", str(fixture), "add", "-f", ".env.example", ".env.example.local", ".env.schema.json"])

        run([sys.executable, str(BUILD), "--repo", str(fixture), "--out", str(output), "--batch-size", "200"])
        assert_manifest(output / "manifest.json")
        assert_exclusions(output / "excluded_files.json")
        assert_generated_excluded(output / "manifest.json")
        check(str(VERIFY) in (output / "audit_index.md").read_text(encoding="utf-8"), "audit_index should include verifier path")

        set_scenario("run-id and harness-owned output reuse")
        run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(fixture),
                "--out",
                str(custom_run_output),
                "--batch-size",
                "200",
                "--run-id",
                "loop-1234",
            ]
        )
        custom_manifest = json.loads((custom_run_output / "manifest.json").read_text(encoding="utf-8"))
        check(custom_manifest["run_id"] == "loop-1234", "--run-id should populate manifest run_id")
        check(
            "loop-1234" in (custom_run_output / "batch_001.md").read_text(encoding="utf-8"),
            "--run-id should populate generated batch prompts",
        )
        invalid_run_id = run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(fixture),
                "--out",
                str(base / "audit-output-invalid-run-id"),
                "--run-id",
                "../bad",
            ],
            expect=2,
        )
        check_output(invalid_run_id, "must be 8-128 characters")

        run([sys.executable, str(BUILD), "--repo", str(fixture), "--out", str(reuse_output), "--batch-size", "1"])
        check((reuse_output / "batch_002.md").exists(), "batch-size 1 should create multiple prompt files")
        run([sys.executable, str(BUILD), "--repo", str(fixture), "--out", str(reuse_output), "--batch-size", "200"])
        remaining_prompts = sorted(path.name for path in reuse_output.glob("batch_*.md"))
        check(remaining_prompts == ["batch_001.md"], "reusing an output dir should remove stale batch prompts")
        check((reuse_output / "queue_complete.json").exists(), "reused output should have a fresh queue completion marker")
        write(reuse_output / "batch_999.md", "manual note\n")
        run([sys.executable, str(BUILD), "--repo", str(fixture), "--out", str(reuse_output), "--batch-size", "200"])
        check((reuse_output / "batch_999.md").read_text(encoding="utf-8") == "manual note\n", "owned output cleanup should preserve unknown root batch files")
        write(reuse_output / "reports" / "batch_001.md", "stale report\n")
        run([sys.executable, str(BUILD), "--repo", str(fixture), "--out", str(reuse_output), "--batch-size", "200"])
        stale_report_dirs = sorted(reuse_output.glob("reports.stale.*"))
        check(len(stale_report_dirs) == 1, "non-empty reports/ should be archived on reuse")
        run([sys.executable, str(BUILD), "--repo", str(fixture), "--out", str(reuse_output), "--batch-size", "200"])
        check(not stale_report_dirs[0].exists(), "tracked stale report archive should be cleaned on the next reuse")
        reuse_marker_path = reuse_output / ".full-repo-audit-artifacts.json"
        reuse_marker = json.loads(reuse_marker_path.read_text(encoding="utf-8"))
        write(reuse_output / "manual-root-sentinel.txt", "do not recreate me\n")
        reuse_marker["generated_artifacts"] = ["."]
        write(reuse_marker_path, json.dumps(reuse_marker, indent=2))
        run([sys.executable, str(BUILD), "--repo", str(fixture), "--out", str(reuse_output), "--batch-size", "200"])
        check(reuse_output.exists(), "corrupted generated artifact name '.' must not delete the output root")
        check(
            (reuse_output / "manual-root-sentinel.txt").read_text(encoding="utf-8") == "do not recreate me\n",
            "corrupted generated artifact name '.' must preserve existing output-root contents",
        )
        symlink_output = base / "symlink-owned-output"
        symlink_output.mkdir()
        outside_output_target = base / "outside-output-target"
        outside_output_target.mkdir()
        write(outside_output_target / "victim.txt", "must remain\n")
        os.symlink(outside_output_target, symlink_output / "link")
        write(
            symlink_output / ".full-repo-audit-artifacts.json",
            json.dumps(
                {
                    "owned_by": "full-repo-audit",
                    "repo_root": str(fixture.resolve()),
                    "generated_artifacts": ["link/victim.txt"],
                },
                indent=2,
            ),
        )
        run([sys.executable, str(BUILD), "--repo", str(fixture), "--out", str(symlink_output), "--batch-size", "200"])
        check((outside_output_target / "victim.txt").exists(), "cleanup must not follow intermediate symlinked parents outside output root")
        interrupted_output = base / "interrupted-owned-output"
        interrupted_output.mkdir()
        write(
            interrupted_output / ".full-repo-audit-artifacts.json",
            json.dumps({"owned_by": "full-repo-audit", "repo_root": str(fixture.resolve()), "generated_artifacts": []}, indent=2),
        )
        write(interrupted_output / "batch_999.md", "stale interrupted prompt\n")
        run([sys.executable, str(BUILD), "--repo", str(fixture), "--out", str(interrupted_output), "--batch-size", "200"])
        check(not (interrupted_output / "batch_999.md").exists(), "owned interrupted output cleanup should remove stale batch prompts")

        unowned_output = base / "unowned-output"
        write(unowned_output / "batch_999.md", "user notes\n")
        unowned_result = run(
            [sys.executable, str(BUILD), "--repo", str(fixture), "--out", str(unowned_output), "--batch-size", "200"],
            expect=2,
        )
        check_output(unowned_result, "not marked as full-repo-audit-owned")
        check(
            (unowned_output / "batch_999.md").read_text(encoding="utf-8") == "user notes\n",
            "unowned output cleanup must not delete lookalike user files",
        )

        in_repo_fixture = base / "in-repo-fixture"
        make_fixture(in_repo_fixture)
        in_repo_output = in_repo_fixture / "audit-output"
        run([sys.executable, str(BUILD), "--repo", str(in_repo_fixture), "--out", str(in_repo_output), "--batch-size", "200"])
        run([sys.executable, str(BUILD), "--repo", str(in_repo_fixture), "--out", str(in_repo_output), "--batch-size", "200"])
        in_repo_manifest = json.loads((in_repo_output / "manifest.json").read_text(encoding="utf-8"))
        check(
            all(not item["rel_path"].startswith("audit-output/") for item in in_repo_manifest["source_files"]),
            "in-repo output artifacts should be excluded from the next manifest",
        )
        in_repo_glob_output = in_repo_fixture / "audit-output-glob"
        run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(in_repo_fixture),
                "--out",
                str(in_repo_glob_output),
                "--batch-size",
                "200",
                "--include-glob",
                "audit-output/**",
            ]
        )
        in_repo_glob_manifest = json.loads((in_repo_glob_output / "manifest.json").read_text(encoding="utf-8"))
        check(
            all(not item["rel_path"].startswith("audit-output/") for item in in_repo_glob_manifest["source_files"]),
            "--include-glob should not traverse or queue audit output directories",
        )

        byte_limit = 120
        run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(fixture),
                "--out",
                str(byte_output),
                "--batch-size",
                "200",
                "--max-batch-bytes",
                str(byte_limit),
            ]
        )
        byte_manifest = json.loads((byte_output / "manifest.json").read_text(encoding="utf-8"))
        check(byte_manifest["batch_count"] > 1, "--max-batch-bytes should split the fixture into multiple batches")
        check(byte_manifest["coverage_invariants"]["all_source_files_queued_exactly_once"], "byte-limited batching should preserve exact-once coverage")
        byte_units = [unit_id for batch in byte_manifest["batches"] for unit_id in batch["coverage_units"]]
        check(
            len(byte_units) == len(set(byte_units)) == byte_manifest["coverage_unit_count"],
            "byte-limited batches should cover each coverage unit exactly once",
        )
        check(
            byte_manifest["coverage_invariants"]["all_coverage_units_queued_exactly_once"],
            "byte-limited batching should preserve exact-once coverage unit assignment",
        )
        check(
            any("#B" in unit["unit_id"] or "#L" in unit["unit_id"] for unit in byte_manifest["coverage_units"]),
            "byte-limited batching should split oversized files into range coverage units",
        )
        check(
            all(unit["size_bytes"] <= byte_limit for unit in byte_manifest["coverage_units"]),
            "byte-limited coverage units should not understate bytes beyond --max-batch-bytes",
        )
        check(
            byte_manifest["coverage_invariants"]["duplicates_in_batches"] == [],
            "range splits should not be reported as duplicate whole-file batches",
        )
        check(
            all(batch["byte_count"] <= byte_limit or batch["file_count"] == 1 for batch in byte_manifest["batches"]),
            "byte-limited multi-file batches should respect --max-batch-bytes",
        )

        line_range_fixture = base / "line-range-fixture"
        line_range_output = base / "line-range-output"
        write(
            line_range_fixture / "src" / "large.py",
            "".join(f"VALUE_{index} = '{'x' * 12}'\n" for index in range(40)),
        )
        run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(line_range_fixture),
                "--out",
                str(line_range_output),
                "--batch-size",
                "200",
                "--max-batch-bytes",
                str(byte_limit),
            ]
        )
        line_range_manifest = json.loads((line_range_output / "manifest.json").read_text(encoding="utf-8"))
        line_range_units = line_range_manifest["coverage_units"]
        check(line_range_manifest["coverage_unit_count"] > 1, "large multi-line UTF-8 files should be split")
        check(
            all("#L" in unit["unit_id"] for unit in line_range_units),
            "large multi-line UTF-8 files should prefer line-range unit ids",
        )
        check(
            all(isinstance(unit.get("start_line"), int) and isinstance(unit.get("end_line"), int) for unit in line_range_units),
            "line-range units should record start_line/end_line metadata",
        )
        check(
            all(unit["size_bytes"] <= byte_limit for unit in line_range_units),
            "line-range units should respect --max-batch-bytes",
        )
        check(
            "exact ranged unit id must also appear"
            in (line_range_output / "batch_001.md").read_text(encoding="utf-8"),
            "range batch prompts should tell workers to cite exact unit ids in narrative evidence",
        )

        long_line_fixture = base / "long-line-fixture"
        long_line_output = base / "long-line-output"
        write(long_line_fixture / "src" / "minified.js", "const data = '" + ("x" * 1000) + "';")
        run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(long_line_fixture),
                "--out",
                str(long_line_output),
                "--batch-size",
                "200",
                "--max-batch-bytes",
                str(byte_limit),
            ]
        )
        long_line_manifest = json.loads((long_line_output / "manifest.json").read_text(encoding="utf-8"))
        long_line_units = long_line_manifest["coverage_units"]
        check(long_line_manifest["coverage_unit_count"] > 1, "long single-line files should be split into multiple byte-range units")
        check(
            all("#B" in unit["unit_id"] for unit in long_line_units),
            "long single-line files should use byte-range unit ids",
        )
        check(
            all(unit["size_bytes"] <= byte_limit for unit in long_line_units),
            "long single-line byte-range units should respect --max-batch-bytes",
        )
        check(
            all(isinstance(unit.get("start_byte"), int) and isinstance(unit.get("end_byte"), int) for unit in long_line_units),
            "byte-range units should record start_byte/end_byte metadata",
        )

        set_scenario("scope warnings, forced includes, and glob traversal")
        warning_fixture = base / "warning-fixture"
        write(warning_fixture / "src" / "mystery.widget", "custom source-ish text\n")
        warning_output = base / "warning-output"
        run([sys.executable, str(BUILD), "--repo", str(warning_fixture), "--out", str(warning_output), "--batch-size", "200"])
        warning_manifest = json.loads((warning_output / "manifest.json").read_text(encoding="utf-8"))
        warning_excluded = json.loads((warning_output / "excluded_files.json").read_text(encoding="utf-8"))
        check(warning_manifest["scope_warning_count"] == 1, "unknown text under src should create a scope warning")
        check(warning_excluded[0]["path"] == "src/mystery.widget", "scope warning should name the high-signal unknown file")

        generated_pruned_fixture = base / "generated-pruned-fixture"
        write(generated_pruned_fixture / "dist" / "generated.ts", "export const generated = true;\n")
        generated_pruned_output = base / "generated-pruned-output"
        run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(generated_pruned_fixture),
                "--out",
                str(generated_pruned_output),
                "--batch-size",
                "200",
                "--include-glob",
                "dist/*.ts",
            ]
        )
        generated_pruned_manifest = json.loads((generated_pruned_output / "manifest.json").read_text(encoding="utf-8"))
        generated_pruned_files = {item["rel_path"] for item in generated_pruned_manifest["source_files"]}
        check("dist/generated.ts" in generated_pruned_files, "--include-glob should requeue generated source-like files")
        check(generated_pruned_manifest["pruned_directory_review_hint_count"] == 0, "explicit generated include-globs should clear matching pruned-directory review hints")

        output_pruned_fixture = base / "output-pruned-fixture"
        output_pruned_output = output_pruned_fixture / "audit-output"
        write(output_pruned_fixture / "src" / "app.ts", "export const app = true;\n")
        run([sys.executable, str(BUILD), "--repo", str(output_pruned_fixture), "--out", str(output_pruned_output), "--batch-size", "200"])
        write(output_pruned_output / "dist" / "generated.ts", "export const generated = true;\n")
        run([sys.executable, str(BUILD), "--repo", str(output_pruned_fixture), "--out", str(output_pruned_output), "--batch-size", "200"])
        output_pruned_manifest = json.loads((output_pruned_output / "manifest.json").read_text(encoding="utf-8"))
        output_pruned_hints = output_pruned_manifest["pruned_directory_review_hints"]
        check(
            all(not hint.get("path", "").startswith("audit-output/") for hint in output_pruned_hints),
            "owned output directories should be excluded from pruned-directory review hints on rerun",
        )

        unsafe_path_fixture = base / "unsafe-path-fixture"
        unsafe_path_output = base / "unsafe-path-output"
        write(unsafe_path_fixture / "src" / "bad`name.ts", "export const unsafePath = true;\n")
        unsafe_path_result = run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(unsafe_path_fixture),
                "--out",
                str(unsafe_path_output),
                "--batch-size",
                "200",
            ],
            expect=2,
        )
        check_output(unsafe_path_result, "source_files[0].rel_path", "Markdown table/code delimiters")
        check(not (unsafe_path_output / "batch_001.md").exists(), "unsafe repo paths should fail before prompt files are written")

        large_pruned_fixture = base / "large-pruned-fixture"
        large_pruned_total = build_module.DIR_EXCLUSION_COUNT_LIMIT + 25
        for index in range(large_pruned_total):
            write(large_pruned_fixture / "dist" / f"file-{index:03}.ts", f"export const value{index} = true;\n")
        write(large_pruned_fixture / "dist" / "node_modules" / "dep" / "ignored.ts", "export const nestedVendor = true;\n")
        large_pruned_output = base / "large-pruned-output"
        run([sys.executable, str(BUILD), "--repo", str(large_pruned_fixture), "--out", str(large_pruned_output), "--batch-size", "200"])
        large_pruned_manifest = json.loads((large_pruned_output / "manifest.json").read_text(encoding="utf-8"))
        large_pruned_hints = large_pruned_manifest["pruned_directory_review_hints"]
        check(large_pruned_manifest["pruned_directory_review_hint_count"] == 1, "large pruned source-like directory should require one review hint")
        large_pruned_hint = large_pruned_hints[0]
        check(large_pruned_hint["path"] == "dist", "large pruned hint should identify the excluded directory")
        check(large_pruned_hint["file_count_capped"], "large pruned hint should disclose capped total file count")
        check(large_pruned_hint["file_count"] == build_module.DIR_EXCLUSION_COUNT_LIMIT, "large pruned hint should bound file counting")
        check(large_pruned_hint["scan_file_limit"] == build_module.DIR_EXCLUSION_COUNT_LIMIT, "large pruned hint should disclose scan limit")
        check(
            large_pruned_hint["source_like_observed_count"] == build_module.DIR_EXCLUSION_COUNT_LIMIT,
            "large pruned hint should report observed source-like count from the bounded scan",
        )
        check(
            large_pruned_hint["source_like_count_capped"],
            "large pruned hint should disclose capped source-like counts",
        )
        check(
            large_pruned_hint["source_like_sample_count"] == build_module.DIR_EXCLUSION_COUNT_LIMIT,
            "large pruned hint should count unresolved source-like files only within the bounded scan",
        )
        check(
            len(large_pruned_hint["source_like_sample_paths"]) == build_module.DIR_EXCLUSION_SAMPLE_LIMIT,
            "large pruned hint should cap source-like sample paths separately from observed source-like counts",
        )
        check(
            "dist/node_modules/dep/ignored.ts" not in large_pruned_hint["sample_paths"],
            "large pruned hint should prune nested excluded directories during bounded scans",
        )

        nested_ignored_fixture = base / "nested-ignored-fixture"
        write(nested_ignored_fixture / ".gitignore", "packages/app/node_modules/\napps/web/dist/\n")
        write(nested_ignored_fixture / "src" / "app.ts", "export const app = true;\n")
        write(nested_ignored_fixture / "packages" / "app" / "node_modules" / "dep" / "index.js", "module.exports = true;\n")
        write(nested_ignored_fixture / "apps" / "web" / "dist" / "generated.ts", "export const built = true;\n")
        run(["git", "-C", str(nested_ignored_fixture), "init"], expect=0)
        run(["git", "-C", str(nested_ignored_fixture), "add", ".gitignore", "src/app.ts"])
        nested_ignored_output = base / "nested-ignored-output"
        run([sys.executable, str(BUILD), "--repo", str(nested_ignored_fixture), "--out", str(nested_ignored_output), "--batch-size", "200"])
        nested_ignored_manifest = json.loads((nested_ignored_output / "manifest.json").read_text(encoding="utf-8"))
        nested_ignored_excluded = json.loads((nested_ignored_output / "excluded_files.json").read_text(encoding="utf-8"))
        nested_ignored_sources = {item["rel_path"] for item in nested_ignored_manifest["source_files"]}
        nested_ignored_rows = {item["path"] for item in nested_ignored_excluded}
        check("packages/app/node_modules/dep/index.js" not in nested_ignored_sources, "nested ignored vendor files should not be source units")
        check("apps/web/dist/generated.ts" not in nested_ignored_sources, "nested ignored generated files should not be source units")
        check("packages/app/node_modules/dep/index.js" not in nested_ignored_rows, "nested ignored vendor files should be pruned by git pathspecs, not file-row filtered later")
        check("apps/web/dist/generated.ts" not in nested_ignored_rows, "nested ignored generated files should be pruned by git pathspecs, not file-row filtered later")

        root_unknown_fixture = base / "root-unknown-fixture"
        write(root_unknown_fixture / "Customfile", "custom operational config\n")
        write(root_unknown_fixture / "src" / "app.ts", "export const app = true;\n")
        root_unknown_output = base / "root-unknown-output"
        run([sys.executable, str(BUILD), "--repo", str(root_unknown_fixture), "--out", str(root_unknown_output), "--batch-size", "200"])
        root_unknown_manifest = json.loads((root_unknown_output / "manifest.json").read_text(encoding="utf-8"))
        root_unknown_excluded = json.loads((root_unknown_output / "excluded_files.json").read_text(encoding="utf-8"))
        root_unknown_warning = next(item for item in root_unknown_excluded if item["path"] == "Customfile")
        check(root_unknown_manifest["scope_warning_count"] == 1, "top-level operational unknowns should warn")
        check(root_unknown_warning["scope_warning"] is True, "top-level operational unknown row should be a warning")

        ignored_fixture = base / "ignored-fixture"
        write(ignored_fixture / ".gitignore", "*.local.py\n")
        write(ignored_fixture / "src" / "ignored.local.py", "IGNORED = True\n")
        run(["git", "-C", str(ignored_fixture), "init"], expect=0)
        run(["git", "-C", str(ignored_fixture), "add", ".gitignore"])
        ignored_output = base / "ignored-output"
        run([sys.executable, str(BUILD), "--repo", str(ignored_fixture), "--out", str(ignored_output), "--batch-size", "200"])
        ignored_manifest = json.loads((ignored_output / "manifest.json").read_text(encoding="utf-8"))
        ignored_excluded = json.loads((ignored_output / "excluded_files.json").read_text(encoding="utf-8"))
        check(ignored_manifest["scope_warning_count"] == 1, "gitignored source-like files under src should be scope warnings")
        ignored_row = next(item for item in ignored_excluded if item["path"] == "src/ignored.local.py")
        check(ignored_row["scope_warning"] is True, "gitignored source-like row should warn")

        hidden_fixture = base / "hidden-fixture"
        write(hidden_fixture / ".vscode" / "settings.json", '{"editor.formatOnSave": true}\n')
        run(["git", "-C", str(hidden_fixture), "init"], expect=0)
        run(["git", "-C", str(hidden_fixture), "add", ".vscode/settings.json"])
        run([sys.executable, str(BUILD), "--repo", str(hidden_fixture), "--out", str(hidden_output), "--batch-size", "200"])
        hidden_manifest = json.loads((hidden_output / "manifest.json").read_text(encoding="utf-8"))
        hidden_excluded = json.loads((hidden_output / "excluded_files.json").read_text(encoding="utf-8"))
        check(hidden_manifest["scope_warning_count"] == 1, "tracked hidden tooling config should create a scope warning")
        hidden_row = next(item for item in hidden_excluded if item["path"] == ".vscode/settings.json")
        check(hidden_row["scope_warning"] is True, "tracked hidden tooling config should warn")
        run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(hidden_fixture),
                "--out",
                str(hidden_forced_file_output),
                "--batch-size",
                "200",
                "--include-file",
                ".vscode/settings.json",
            ]
        )
        hidden_forced_manifest = json.loads((hidden_forced_file_output / "manifest.json").read_text(encoding="utf-8"))
        hidden_forced_files = {item["rel_path"]: item for item in hidden_forced_manifest["source_files"]}
        check(".vscode/settings.json" in hidden_forced_files, "--include-file should force hidden tooling files")
        check(hidden_forced_manifest["scope_warning_count"] == 0, "--include-file should resolve hidden tooling warnings")
        run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(hidden_fixture),
                "--out",
                str(hidden_forced_glob_output),
                "--batch-size",
                "200",
                "--include-glob",
                ".vscode/*.json",
            ]
        )
        hidden_glob_manifest = json.loads((hidden_forced_glob_output / "manifest.json").read_text(encoding="utf-8"))
        hidden_glob_files = {item["rel_path"] for item in hidden_glob_manifest["source_files"]}
        check(".vscode/settings.json" in hidden_glob_files, "--include-glob should force hidden tooling files")
        check(hidden_glob_manifest["scope_warning_count"] == 0, "--include-glob should resolve hidden tooling warnings")

        non_git_hidden_fixture = base / "non-git-hidden-fixture"
        write(non_git_hidden_fixture / ".vscode" / "settings.json", '{"editor.tabSize": 2}\n')
        run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(non_git_hidden_fixture),
                "--out",
                str(non_git_forced_file_output),
                "--batch-size",
                "200",
                "--include-file",
                ".vscode/settings.json",
            ]
        )
        non_git_file_manifest = json.loads((non_git_forced_file_output / "manifest.json").read_text(encoding="utf-8"))
        non_git_file_files = {item["rel_path"] for item in non_git_file_manifest["source_files"]}
        check(".vscode/settings.json" in non_git_file_files, "--include-file should work in non-git repos")
        run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(non_git_hidden_fixture),
                "--out",
                str(non_git_forced_glob_output),
                "--batch-size",
                "200",
                "--include-glob",
                ".vscode/*.json",
            ]
        )
        non_git_glob_manifest = json.loads((non_git_forced_glob_output / "manifest.json").read_text(encoding="utf-8"))
        non_git_glob_files = {item["rel_path"] for item in non_git_glob_manifest["source_files"]}
        check(".vscode/settings.json" in non_git_glob_files, "--include-glob should work in non-git repos")
        non_git_hidden_project_fixture = base / "non-git-hidden-project-fixture"
        write(non_git_hidden_project_fixture / ".github" / "workflows" / "ci.yml", "name: root\n")
        write(non_git_hidden_project_fixture / "examples" / ".github" / "workflows" / "ci.yml", "name: nested\n")
        non_git_hidden_project_output = base / "non-git-hidden-project-output"
        run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(non_git_hidden_project_fixture),
                "--out",
                str(non_git_hidden_project_output),
                "--batch-size",
                "200",
            ]
        )
        non_git_hidden_project_manifest = json.loads((non_git_hidden_project_output / "manifest.json").read_text(encoding="utf-8"))
        non_git_hidden_project_files = {item["rel_path"] for item in non_git_hidden_project_manifest["source_files"]}
        check(".github/workflows/ci.yml" in non_git_hidden_project_files, "root hidden project dirs should remain first-party")
        check("examples/.github/workflows/ci.yml" not in non_git_hidden_project_files, "nested hidden project dirs should not be audited by fallback walk by default")
        prefix_collision_fixture = base / "prefix-collision-fixture"
        write(prefix_collision_fixture / "node" / "target.js", "export const target = true;\n")
        write(prefix_collision_fixture / "node_modules" / "large" / "accidental.js", "module.exports = true;\n")
        prefix_collision_output = base / "prefix-collision-output"
        run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(prefix_collision_fixture),
                "--out",
                str(prefix_collision_output),
                "--batch-size",
                "200",
                "--include-glob",
                "node/*.js",
            ]
        )
        prefix_collision_manifest = json.loads((prefix_collision_output / "manifest.json").read_text(encoding="utf-8"))
        prefix_collision_files = {item["rel_path"] for item in prefix_collision_manifest["source_files"]}
        check("node/target.js" in prefix_collision_files, "--include-glob should enter the targeted path segment")
        check(
            all(not rel_path.startswith("node_modules/") for rel_path in prefix_collision_files),
            "--include-glob prefix matching should not enter sibling paths such as node_modules",
        )
        run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(fixture),
                "--out",
                str(broad_glob_output),
                "--batch-size",
                "200",
                "--include-glob",
                "*.js",
            ]
        )
        broad_glob_manifest = json.loads((broad_glob_output / "manifest.json").read_text(encoding="utf-8"))
        broad_glob_files = {item["rel_path"] for item in broad_glob_manifest["source_files"]}
        check(
            all(not rel_path.startswith("node_modules/") for rel_path in broad_glob_files),
            "broad --include-glob should not enter default-excluded dependency directories",
        )
        nested_generated_glob_output = base / "nested-generated-glob-output"
        run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(fixture),
                "--out",
                str(nested_generated_glob_output),
                "--batch-size",
                "200",
                "--include-glob",
                "**/dist/*.ts",
            ]
        )
        nested_generated_glob_manifest = json.loads((nested_generated_glob_output / "manifest.json").read_text(encoding="utf-8"))
        nested_generated_glob_files = {item["rel_path"] for item in nested_generated_glob_manifest["source_files"]}
        check("dist/generated.ts" in nested_generated_glob_files, "broad --include-glob should discover matching generated directories")
        dot_glob_fixture = base / "dot-glob-fixture"
        write(dot_glob_fixture / ".vscode" / "settings.json", '{"editor.wordWrap": "on"}\n')
        run(["git", "-C", str(dot_glob_fixture), "init"], expect=0)
        run(["git", "-C", str(dot_glob_fixture), "add", ".vscode/settings.json"])
        dot_glob_output = base / "dot-glob-output"
        run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(dot_glob_fixture),
                "--out",
                str(dot_glob_output),
                "--batch-size",
                "200",
                "--include-glob",
                "./.vscode/*.json",
            ]
        )
        dot_glob_files = {item["rel_path"] for item in json.loads((dot_glob_output / "manifest.json").read_text(encoding="utf-8"))["source_files"]}
        check(".vscode/settings.json" in dot_glob_files, "leading ./ --include-glob should force matching repo-relative files")
        dot_exclude_output = base / "dot-exclude-output"
        run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(fixture),
                "--out",
                str(dot_exclude_output),
                "--batch-size",
                "200",
                "--exclude-glob",
                "./src/database.py",
            ]
        )
        dot_exclude_manifest = json.loads((dot_exclude_output / "manifest.json").read_text(encoding="utf-8"))
        dot_exclude_files = {item["rel_path"] for item in dot_exclude_manifest["source_files"]}
        check("src/database.py" not in dot_exclude_files, "leading ./ --exclude-glob should match repo-relative files")
        check(dot_exclude_manifest["scope_warning_count"] == 1, "leading ./ excluded source should still create a scope warning")

        set_scenario("ui asset warning and metadata verification")
        asset_fixture = base / "asset-fixture"
        write(asset_fixture / "src" / "app.ts", "export const app = true;\n")
        write_bytes(asset_fixture / "public" / "logo.png", PNG_1X1)
        run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(asset_fixture),
                "--out",
                str(asset_warning_output),
                "--batch-size",
                "200",
            ]
        )
        asset_warning_manifest = json.loads((asset_warning_output / "manifest.json").read_text(encoding="utf-8"))
        asset_warning_excluded = json.loads((asset_warning_output / "excluded_files.json").read_text(encoding="utf-8"))
        logo_warning = next(item for item in asset_warning_excluded if item["path"] == "public/logo.png")
        check(asset_warning_manifest["scope_warning_count"] == 1, "UI binary assets should warn when excluded")
        check(logo_warning["scope_warning"] is True, "public/logo.png should be a scope warning")
        run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(asset_fixture),
                "--out",
                str(asset_include_output),
                "--batch-size",
                "200",
                "--include-assets",
            ]
        )
        asset_include_manifest = json.loads((asset_include_output / "manifest.json").read_text(encoding="utf-8"))
        asset_include_files = {item["rel_path"]: item for item in asset_include_manifest["source_files"]}
        check(asset_include_files["public/logo.png"]["kind"] == "source/ui-asset", "--include-assets should queue UI assets")
        check(asset_include_files["public/logo.png"]["interface_relevant"] is True, "UI assets should be interface-relevant")
        check(asset_include_manifest["scope_warning_count"] == 0, "--include-assets should resolve UI asset warnings")
        ignored_asset_fixture = base / "ignored-asset-fixture"
        write(ignored_asset_fixture / ".gitignore", "public/*.png\n")
        write(ignored_asset_fixture / "src" / "app.ts", "export const app = true;\n")
        write_bytes(ignored_asset_fixture / "public" / "logo.png", PNG_1X1)
        run(["git", "-C", str(ignored_asset_fixture), "init"], expect=0)
        run(["git", "-C", str(ignored_asset_fixture), "add", ".gitignore", "src/app.ts"])
        ignored_asset_warning_output = base / "ignored-asset-warning-output"
        run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(ignored_asset_fixture),
                "--out",
                str(ignored_asset_warning_output),
                "--batch-size",
                "200",
            ]
        )
        ignored_asset_warning_manifest = json.loads((ignored_asset_warning_output / "manifest.json").read_text(encoding="utf-8"))
        ignored_asset_excluded = json.loads((ignored_asset_warning_output / "excluded_files.json").read_text(encoding="utf-8"))
        ignored_logo_warning = next(item for item in ignored_asset_excluded if item["path"] == "public/logo.png")
        check(ignored_asset_warning_manifest["scope_warning_count"] == 1, "gitignored UI assets should warn when excluded")
        check(ignored_logo_warning["scope_warning"] is True, "gitignored public/logo.png should be a scope warning")
        ignored_asset_include_output = base / "ignored-asset-include-output"
        run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(ignored_asset_fixture),
                "--out",
                str(ignored_asset_include_output),
                "--batch-size",
                "200",
                "--include-assets",
            ]
        )
        ignored_asset_include_manifest = json.loads((ignored_asset_include_output / "manifest.json").read_text(encoding="utf-8"))
        ignored_asset_include_files = {item["rel_path"]: item for item in ignored_asset_include_manifest["source_files"]}
        check("public/logo.png" in ignored_asset_include_files, "--include-assets should include gitignored UI assets")
        check(ignored_asset_include_manifest["scope_warning_count"] == 0, "--include-assets should resolve gitignored UI asset warnings")

        asset_complete = write_reports(base / "asset-include-reports", asset_include_output / "manifest.json")[-1]
        complete_effort_ledger(asset_include_output)
        asset_missing_evidence_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(asset_include_output / "manifest.json"),
                "--reports",
                str(install_report(asset_include_output, asset_complete)),
            ],
            expect=1,
        )
        check_output(asset_missing_evidence_result, "interface_inventory_issues", "verifier-backed MIME/type")
        asset_evidence_report = base / "asset-include-reports" / "asset-evidence" / "batch_001.md"
        asset_text = asset_complete.read_text(encoding="utf-8")
        write(
            asset_evidence_report,
            asset_text.replace(
                "and its fixture behavior is covered by this smoke test report.",
                "as source UI asset: MIME image/png, dimensions 1x1 fixture, visually readable logo, referenced by public branding.",
                1,
            ),
        )
        run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(asset_include_output / "manifest.json"),
                "--reports",
                str(install_report(asset_include_output, asset_evidence_report)),
            ]
        )

        invalid_asset_fixture = base / "invalid-asset-fixture"
        write(invalid_asset_fixture / "src" / "app.ts", "export const app = true;\n")
        write_bytes(invalid_asset_fixture / "public" / "logo.png", b"\x89PNG\r\n\x1a\nnot-a-real-png")
        invalid_asset_output = base / "invalid-asset-output"
        run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(invalid_asset_fixture),
                "--out",
                str(invalid_asset_output),
                "--batch-size",
                "200",
                "--include-assets",
            ]
        )
        invalid_asset_complete = write_reports(base / "invalid-asset-reports", invalid_asset_output / "manifest.json")[-1]
        invalid_asset_report = base / "invalid-asset-reports" / "metadata-evidence" / "batch_001.md"
        invalid_asset_text = invalid_asset_complete.read_text(encoding="utf-8")
        write(
            invalid_asset_report,
            invalid_asset_text.replace(
                "and its fixture behavior is covered by this smoke test report.",
                "as source UI asset: MIME image/png, dimensions 1x1 fixture, visually readable logo, referenced by public branding.",
                1,
            ),
        )
        complete_effort_ledger(invalid_asset_output)
        invalid_asset_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(invalid_asset_output / "manifest.json"),
                "--reports",
                str(install_report(invalid_asset_output, invalid_asset_report)),
            ],
            expect=1,
        )
        check_output(invalid_asset_result, "source-backed UI asset could not be parsed")

        set_scenario("report verifier negative cases")
        (
            incomplete,
            unchecked,
            missing_sections,
            wrong_batch,
            extra_section,
            missing_purpose,
            malformed_pipe,
            stale_hash,
            invalid_utf8,
            invalid_filename,
            wrong_run_id,
            complete,
        ) = write_reports(reports_dir, output / "manifest.json")
        semantic_gap = reports_dir / "reports" / "semantic-gap" / "batch_001.md"
        interface_gap = reports_dir / "reports" / "interface-gap" / "batch_001.md"
        interface_boilerplate_gap = reports_dir / "reports" / "interface-boilerplate-gap" / "batch_001.md"
        interface_missing_hint_gap = reports_dir / "reports" / "interface-missing-hint-gap" / "batch_001.md"
        markdown_missing_hint_gap = reports_dir / "reports" / "markdown-missing-hint-gap" / "batch_001.md"
        catalog_missing_hint_gap = reports_dir / "reports" / "catalog-missing-hint-gap" / "batch_001.md"
        finding_schema_gap = reports_dir / "reports" / "finding-schema-gap" / "batch_001.md"
        ghost_finding_gap = reports_dir / "reports" / "ghost-finding-gap" / "batch_001.md"
        boilerplate_finding_gap = reports_dir / "reports" / "boilerplate-finding-gap" / "batch_001.md"
        interface_evidence_punct_gap = reports_dir / "reports" / "interface-evidence-punct-gap" / "batch_001.md"
        fake_interface_evidence_gap = reports_dir / "reports" / "fake-interface-evidence-gap" / "batch_001.md"
        mention_only_placeholder_gap = reports_dir / "reports" / "mention-only-placeholder-gap" / "batch_001.md"
        marker_detail_placeholder_gap = reports_dir / "reports" / "marker-detail-placeholder-gap" / "batch_001.md"
        placeholder_omission_gap = reports_dir / "reports" / "placeholder-omission-gap" / "batch_001.md"
        directory_purpose_gap = reports_dir / "reports" / "directory-purpose-gap" / "batch_001.md"
        complete_text = complete.read_text(encoding="utf-8")
        output_manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        interface_rows = "\n".join(
            f"| `{item['rel_path']}` | fixture | Fixture visible text | Fixture expected path | Fixture implementation note |"
            for item in output_manifest["source_files"]
            if item.get("interface_relevant") is True
        )
        interface_start = complete_text.index("## Interface Inventory")
        findings_start = complete_text.index("## Findings")
        no_notes_start = complete_text.index("## No Finding Notes")
        open_questions_start = complete_text.index("## Open Questions")
        write(
            semantic_gap,
            complete_text[:no_notes_start]
            + "## No Finding Notes\n- Fixture report.\n\n"
            + complete_text[open_questions_start:],
        )
        write(
            interface_gap,
            complete_text[:interface_start]
            + "## Interface Inventory\nNo interface-relevant files in this batch.\n\n"
            + complete_text[findings_start:],
        )
        write(
            interface_boilerplate_gap,
            complete_text[:interface_start]
            + "## Interface Inventory\n"
            + "| File | Surface | Visible text/control/message | Expected behavior path | Actual implementation notes |\n"
            + "| --- | --- | --- | --- | --- |\n"
            + interface_rows
            + "\n\n"
            + complete_text[findings_start:],
        )
        write(
            interface_missing_hint_gap,
            "\n".join(
                line for line in complete_text.splitlines() if " | Delete | " not in line
            )
            + "\n",
        )
        write(
            markdown_missing_hint_gap,
            "\n".join(
                line for line in complete_text.splitlines() if " | Fixture Skill | " not in line
            )
            + "\n",
        )
        write(
            catalog_missing_hint_gap,
            "\n".join(
                line
                for line in complete_text.splitlines()
                if not (line.startswith("| `locales/en.json` |") and " | Save | " in line)
            )
            + "\n",
        )
        write(
            directory_purpose_gap,
            complete_text.replace(
                "| `scripts/deploy` | CHECKED |",
                "| `scripts/deploy` | CHECKED |",
                1,
            ).replace(
                "fixture-owned source role for scripts/deploy",
                "files under scripts",
                1,
            ),
        )
        write(
            finding_schema_gap,
            complete_text[:findings_start]
            + "## Findings\nThis vague finding mentions `SKILL.md` but has no severity heading or required fields.\n\n"
            + complete_text[no_notes_start:],
        )
        write(
            ghost_finding_gap,
            complete_text[:no_notes_start]
            + """
### P2 - Ghost file should not validate
- Files: `ghost.py`
- Evidence: A concrete-looking but impossible evidence statement for a file outside the batch.
- Interface evidence: Not applicable.
- Expected behavior/standard: Findings should be tied to files owned by the batch.
- Gap: This finding references a file absent from the manifest batch.
- Suggested direction: Reject findings whose Files field points outside the batch.

"""
            + complete_text[no_notes_start:],
        )
        write(
            boilerplate_finding_gap,
            complete_text[:findings_start]
            + """
## Findings
### P2 - Boilerplate finding should not validate
- Files: `src/components/SaveButton.tsx`
- Evidence: `SaveButton` renders a `Save changes` button whose `onClick` handler only calls `console.log(\"TODO save\")`.
- Interface evidence: Visible control text `Save changes`.
- Expected behavior/standard: TODO
- Gap: TODO
- Suggested direction: TODO

"""
            + complete_text[no_notes_start:],
        )
        write(
            interface_evidence_punct_gap,
            complete_text[:findings_start]
            + """
## Findings
### P2 - Interface evidence punctuation should not validate
- Files: `src/components/SaveButton.tsx`
- Evidence: `SaveButton` renders a `Save changes` button whose `onClick` handler only calls `console.log(\"TODO save\")`.
- Interface evidence: Not applicable.
- Expected behavior/standard: Interface findings should cite concrete visible label, control, message, or source anchor.
- Gap: Punctuated boilerplate interface evidence should not satisfy the interface finding contract.
- Suggested direction: Normalize punctuation before matching boilerplate evidence values.

"""
            + complete_text[no_notes_start:],
        )
        write(
            fake_interface_evidence_gap,
            complete_text[:findings_start]
            + """
## Findings
### P2 - Fabricated interface evidence should not validate
- Files: `src/components/SaveButton.tsx`
- Evidence: `SaveButton` renders a `Save changes` button whose `onClick` handler only calls `console.log(\"TODO save\")`.
- Interface evidence: Launch Banana Spaceship
- Expected behavior/standard: Interface findings should cite visible source text or a verified interface inventory row.
- Gap: Non-boilerplate but fabricated interface evidence should not satisfy the interface finding contract.
- Suggested direction: Compare interface evidence against source text and accepted inventory rows.

"""
            + complete_text[no_notes_start:],
        )
        write(
            mention_only_placeholder_gap,
            complete_text[:findings_start]
            + """
## Findings
### P2 - Mention-only placeholder should not validate
- Files: `SKILL.md`
- Evidence: This finding mentions `src/components/SaveButton.tsx` but does not own it in the Files field.
- Interface evidence: Not applicable.
- Expected behavior/standard: Placeholder files must be explicitly listed in the finding Files field.
- Gap: Mention-only coverage should not satisfy placeholder enforcement.
- Suggested direction: Require marker-bearing files to appear in a parsed finding Files field.

"""
            + complete_text[no_notes_start:],
        )
        write(
            marker_detail_placeholder_gap,
            complete_text[:findings_start]
            + """
## Findings
### P2 - Vague placeholder coverage should not validate
- Files: `src/components/SaveButton.tsx`
- Evidence: The save control is suspicious, but this report omits the concrete placeholder call.
- Interface evidence: Visible control text `Save changes`.
- Expected behavior/standard: Placeholder files must be covered with the exact source marker or normalized placeholder category.
- Gap: Listing the file alone should not satisfy placeholder enforcement.
- Suggested direction: Require evidence or gap text to name the marker category.

"""
            + complete_text[no_notes_start:],
        )
        write(
            placeholder_omission_gap,
            complete_text[:findings_start]
            + "## Findings\nNo findings.\n\n"
            + complete_text[no_notes_start:],
        )
        canonical_complete = install_report(output, complete)
        verifier_case(
            scenario_runner,
            "pending effort ledger is rejected",
            output / "manifest.json",
            canonical_complete,
            expect=1,
            needles=("effort_ledger_mismatches", "subagent_capability_check.status"),
        )
        complete_effort_ledger(output)
        output_ledger_path = output / "effort_ledger.json"
        output_ledger_text = output_ledger_path.read_text(encoding="utf-8")
        pruned_decision_ledger = json.loads(output_ledger_text)
        pruned_decisions = pruned_decision_ledger.get("pruned_directory_review", {}).get("decisions", [])
        if pruned_decisions:
            pruned_decisions[0]["decision"] = "reviewed"
            pruned_decisions[0]["rationale"] = "ok"
            write(output_ledger_path, json.dumps(pruned_decision_ledger, indent=2))
            pruned_decision_result = run(
                [
                    sys.executable,
                    str(VERIFY),
                    "--manifest",
                    str(output / "manifest.json"),
                    "--reports",
                    str(canonical_complete),
                ],
                expect=1,
            )
            check_output(pruned_decision_result, "pruned_directory_review.decisions", "excluded-with-rationale")
            write(output_ledger_path, output_ledger_text)
        pruned_path_ledger = json.loads(output_ledger_text)
        pruned_path_decisions = pruned_path_ledger.get("pruned_directory_review", {}).get("decisions", [])
        if pruned_path_decisions:
            pruned_path_decisions[0]["path"] = []
            write(output_ledger_path, json.dumps(pruned_path_ledger, indent=2))
            pruned_path_result = run(
                [
                    sys.executable,
                    str(VERIFY),
                    "--manifest",
                    str(output / "manifest.json"),
                    "--reports",
                    str(canonical_complete),
                ],
                expect=1,
            )
            check_output(pruned_path_result, "pruned_directory_review.decisions", "string path from manifest pruned_directory_review_hints")
            check("Traceback" not in f"{pruned_path_result.stdout}\n{pruned_path_result.stderr}", "malformed pruned-review path should not crash verifier")
            write(output_ledger_path, output_ledger_text)
        journey_report_path = output / "reports" / "journey_audit.md"
        original_journey_report = journey_report_path.read_text(encoding="utf-8")
        write(
            journey_report_path,
            f"""## Run ID
{output_manifest['run_id']}

## Worker
journey_source

## Findings
No findings.
""",
        )
        bad_journey_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(output / "manifest.json"),
                "--reports",
                str(canonical_complete),
            ],
            expect=1,
        )
        check_output(bad_journey_result, "journey report sections must match")
        write(journey_report_path, original_journey_report)
        first_interface_file = output_manifest["journey_audit"]["interface_files"][0]
        write(
            journey_report_path,
            original_journey_report.replace(first_interface_file, "__omitted_interface_file__"),
        )
        missing_journey_file_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(output / "manifest.json"),
                "--reports",
                str(canonical_complete),
            ],
            expect=1,
        )
        check_output(missing_journey_file_result, "journey report must mention each manifest interface file")
        write(journey_report_path, original_journey_report)
        write(
            journey_report_path,
            original_journey_report.replace(
                "## Findings\nNo findings.",
                """## Findings
### P2 - Boilerplate journey finding should not validate
- Files: `src/components/SaveButton.tsx`
- Evidence: concrete evidence
- Interface evidence: Save changes
- Expected behavior/standard: TODO
- Gap: TODO
- Suggested direction: TODO""",
                1,
            ),
        )
        boilerplate_journey_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(output / "manifest.json"),
                "--reports",
                str(canonical_complete),
            ],
            expect=1,
        )
        check_output(boilerplate_journey_result, "Evidence field must contain concrete non-boilerplate journey/source detail")
        write(journey_report_path, original_journey_report)
        visual_report_path = output / "reports" / "visual_journey_audit.md"
        original_visual_report = visual_report_path.read_text(encoding="utf-8")
        interface_mentions = ", ".join(f"`{path}`" for path in output_manifest["journey_audit"]["interface_files"])
        write(
            visual_report_path,
            f"""## Run ID
{output_manifest['run_id']}

## Worker
visual_journey

## Visual Tooling
- Playwright test mode is available for {interface_mentions}.

## Visual Journey Checks
| Journey | Viewport | Evidence |
| --- | --- | --- |
| Fixture audit | desktop | Playwright run |
| Fixture audit | narrow mobile | Playwright run |

## Findings
No findings.

## Open Questions
None.
""",
        )
        visual_bad_header_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(output / "manifest.json"),
                "--reports",
                str(canonical_complete),
            ],
            expect=1,
        )
        check_output(visual_bad_header_result, "visual journey table headers must exactly match")
        write(visual_report_path, original_visual_report)
        write(
            visual_report_path,
            f"""## Run ID
{output_manifest['run_id']}

## Worker
visual_journey

## Visual Tooling
- Playwright test mode is available for {interface_mentions}.

## Visual Journey Checks
| Journey | Viewport | Route/screen | Evidence | Navigation visibility | Decision information | Visual quality | Result |
| --- | --- | --- | --- | --- | --- | --- | --- |

## Findings
No findings.

## Open Questions
None.
""",
        )
        visual_empty_rows_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(output / "manifest.json"),
                "--reports",
                str(canonical_complete),
            ],
            expect=1,
        )
        check_output(visual_empty_rows_result, "at least one journey/viewport table row")
        write(visual_report_path, original_visual_report)
        write(
            visual_report_path,
            f"""## Run ID
{output_manifest['run_id']}

## Worker
visual_journey

## Visual Tooling
- Not applicable because no repo-owned rendered UI exists.

## Visual Journey Checks
| Journey | Viewport | Route/screen | Evidence | Navigation visibility | Decision information | Visual quality | Result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Fixture audit | desktop | Host UI | not applicable | not applicable | not applicable | not applicable | not applicable |

## Findings
No findings.

## Open Questions
None.
""",
        )
        visual_not_applicable_missing_file_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(output / "manifest.json"),
                "--reports",
                str(canonical_complete),
            ],
            expect=1,
        )
        check_output(visual_not_applicable_missing_file_result, "journey report must mention each manifest interface file")
        write(visual_report_path, original_visual_report)
        write(
            visual_report_path,
            f"""## Run ID
{output_manifest['run_id']}

## Worker
visual_journey

## Visual Tooling
- Playwright test mode is available for {interface_mentions}.

## Visual Journey Checks
| Journey | Viewport | Route/screen | Evidence | Navigation visibility | Decision information | Visual quality | Result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Fixture audit | desktop | Fixture UI | Playwright run | visible | visible | readable | pass |

## Findings
No findings.

## Open Questions
None.
""",
        )
        desktop_only_visual_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(output / "manifest.json"),
                "--reports",
                str(canonical_complete),
            ],
            expect=1,
        )
        check_output(desktop_only_visual_result, "desktop and narrow-mobile")
        write(visual_report_path, original_visual_report)
        write(
            visual_report_path,
            f"""## Run ID
{output_manifest['run_id']}

## Worker
visual_journey

## Visual Tooling
- Playwright test mode is available for {interface_mentions}.

## Visual Journey Checks
| Journey | Viewport | Route/screen | Evidence | Navigation visibility | Decision information | Visual quality | Result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Fixture audit | desktop | Fixture UI | Playwright run | primary actions visible | decision labels visible | readable | pass |
| Fixture audit | narrow mobile | Fixture UI | Playwright run | primary actions visible | decision labels visible | readable | pass |

## Findings
No findings.

## Open Questions
None.
""",
        )
        visual_missing_artifact_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(output / "manifest.json"),
                "--reports",
                str(canonical_complete),
            ],
            expect=1,
        )
        check_output(visual_missing_artifact_result, "screenshot/trace/artifact evidence")
        write(
            visual_report_path,
            f"""## Run ID
{output_manifest['run_id']}

## Worker
visual_journey

## Visual Tooling
- Ran command `npx playwright test --project=chromium` for {interface_mentions}; screenshots saved at `artifacts/fixture-desktop.png` and `artifacts/fixture-mobile.png`.

## Visual Journey Checks
| Journey | Viewport | Route/screen | Evidence | Navigation visibility | Decision information | Visual quality | Result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Fixture audit | desktop | Fixture UI | Playwright command with screenshot `artifacts/fixture-desktop.png` for {interface_mentions} | primary actions visible | decision labels visible | readable contrast and no crop | pass |
| Fixture audit | narrow mobile | Fixture UI | Playwright command with screenshot `artifacts/fixture-mobile.png` for {interface_mentions} | primary actions visible | decision labels visible | readable contrast and no horizontal scroll | pass |

## Findings
No findings.

## Open Questions
None.
""",
        )
        run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(output / "manifest.json"),
                "--reports",
                str(canonical_complete),
            ]
        )
        write(visual_report_path, original_visual_report)
        invalid_sha_report = reports_dir / "reports" / "invalid-sha" / "batch_001.md"
        first_hash = output_manifest["source_files"][0]["sha256"]
        write(invalid_sha_report, complete_text.replace(first_hash, "not-a-hash", 1))
        verifier_case(
            scenario_runner,
            "malformed report sha256 values are rejected",
            output / "manifest.json",
            install_report(output, invalid_sha_report),
            expect=1,
            needles=("malformed_rows", "invalid SHA-256 digest"),
        )
        verifier_case(
            scenario_runner,
            "reports outside audit output are rejected",
            output / "manifest.json",
            complete,
            expect=1,
            needles=("report_location_mismatches", "outside the audit output directory"),
        )
        verifier_case(
            scenario_runner,
            "report-level run id mismatches are rejected",
            output / "manifest.json",
            install_report(output, wrong_run_id),
            expect=1,
            needles=("run_id_mismatches", "wrong-run-id"),
        )
        verifier_case(
            scenario_runner,
            "checked files must be named in narrative evidence",
            output / "manifest.json",
            install_report(output, semantic_gap),
            expect=1,
            needles=("semantic_report_issues", "checked files must be referenced"),
        )
        verifier_case(
            scenario_runner,
            "missing interface inventory rows are rejected",
            output / "manifest.json",
            install_report(output, interface_gap),
            expect=1,
            needles=("interface_inventory_issues", "missing interface inventory rows"),
        )
        verifier_case(
            scenario_runner,
            "boilerplate interface inventory rows are rejected",
            output / "manifest.json",
            install_report(output, interface_boilerplate_gap),
            expect=1,
            needles=("interface_inventory_issues", "boilerplate"),
        )
        verifier_case(
            scenario_runner,
            "missing TSX visible text hints are rejected",
            output / "manifest.json",
            install_report(output, interface_missing_hint_gap),
            expect=1,
            needles=("interface_inventory_issues", "Delete"),
        )
        verifier_case(
            scenario_runner,
            "missing Markdown visible text hints are rejected",
            output / "manifest.json",
            install_report(output, markdown_missing_hint_gap),
            expect=1,
            needles=("interface_inventory_issues", "Fixture Skill"),
        )
        verifier_case(
            scenario_runner,
            "missing catalog visible text hints are rejected",
            output / "manifest.json",
            install_report(output, catalog_missing_hint_gap),
            expect=1,
            needles=("interface_inventory_issues", "locales/en.json", "Save"),
        )
        verifier_case(
            scenario_runner,
            "directory-only file coverage purposes are rejected",
            output / "manifest.json",
            install_report(output, directory_purpose_gap),
            expect=1,
            needles=("semantic_report_issues", "directory or group"),
        )
        verifier_case(
            scenario_runner,
            "malformed finding schema is rejected",
            output / "manifest.json",
            install_report(output, finding_schema_gap),
            expect=1,
            needles=("semantic_report_issues", "findings must use severity subsections"),
        )
        verifier_case(
            scenario_runner,
            "finding files outside the batch are rejected",
            output / "manifest.json",
            install_report(output, ghost_finding_gap),
            expect=1,
            needles=("finding_schema_issues", "outside this batch", "ghost.py"),
        )
        verifier_case(
            scenario_runner,
            "boilerplate finding fields are rejected",
            output / "manifest.json",
            install_report(output, boilerplate_finding_gap),
            expect=1,
            needles=("finding_schema_issues", "meaningful non-boilerplate"),
        )
        verifier_case(
            scenario_runner,
            "punctuated boilerplate interface evidence is rejected",
            output / "manifest.json",
            install_report(output, interface_evidence_punct_gap),
            expect=1,
            needles=("finding_schema_issues", "Interface findings must include concrete"),
        )
        verifier_case(
            scenario_runner,
            "fabricated interface evidence is rejected",
            output / "manifest.json",
            install_report(output, fake_interface_evidence_gap),
            expect=1,
            needles=("finding_schema_issues", "source-visible", "Launch Banana Spaceship"),
        )
        verifier_case(
            scenario_runner,
            "mention-only placeholder coverage is rejected",
            output / "manifest.json",
            install_report(output, mention_only_placeholder_gap),
            expect=1,
            needles=("placeholder_omissions", "SaveButton.tsx"),
        )
        verifier_case(
            scenario_runner,
            "placeholder file findings must name marker details",
            output / "manifest.json",
            install_report(output, marker_detail_placeholder_gap),
            expect=1,
            needles=("placeholder_omissions", "marker details"),
        )
        verifier_case(
            scenario_runner,
            "no-findings placeholder omissions are rejected",
            output / "manifest.json",
            install_report(output, placeholder_omission_gap),
            expect=1,
            needles=("placeholder_omissions", "SaveButton.tsx"),
        )
        canonical_complete = install_report(output, complete)
        output_ledger_path = output / "effort_ledger.json"
        output_ledger_text = output_ledger_path.read_text(encoding="utf-8")
        misleading_ledger = json.loads(output_ledger_text)
        misleading_ledger["lead"]["required_reasoning_effort"] = "medium"
        for batch in misleading_ledger["batches"]:
            batch["required_reasoning_effort"] = "medium"
            batch["prompt"] = "wrong-prompt.md"
            batch["report"] = "reports/wrong-report.md"
        write(output_ledger_path, json.dumps(misleading_ledger, indent=2))
        misleading_ledger_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(output / "manifest.json"),
                "--reports",
                str(canonical_complete),
            ],
            expect=1,
        )
        check_output(
            misleading_ledger_result,
            "effort_ledger_mismatches",
            "lead.required_reasoning_effort",
            "required_reasoning_effort",
            "wrong-report.md",
        )
        write(output_ledger_path, output_ledger_text)
        malformed_batch_id_ledger = json.loads(output_ledger_text)
        malformed_batch_id_ledger["batches"][0]["batch_id"] = ["batch_001"]
        write(output_ledger_path, json.dumps(malformed_batch_id_ledger, indent=2))
        malformed_batch_id_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(output / "manifest.json"),
                "--reports",
                str(canonical_complete),
            ],
            expect=1,
        )
        check_output(malformed_batch_id_result, "effort_ledger_mismatches", "string batch id")
        check("Traceback" not in malformed_batch_id_result.stderr, "malformed ledger batch id should not traceback")
        write(output_ledger_path, output_ledger_text)
        duplicate_batch_ledger = json.loads(output_ledger_text)
        duplicate_batch_ledger["batches"].append(dict(duplicate_batch_ledger["batches"][0]))
        write(output_ledger_path, json.dumps(duplicate_batch_ledger, indent=2))
        duplicate_batch_ledger_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(output / "manifest.json"),
                "--reports",
                str(canonical_complete),
            ],
            expect=1,
        )
        check_output(duplicate_batch_ledger_result, "effort_ledger_mismatches", "duplicate batch ledger rows")
        write(output_ledger_path, output_ledger_text)
        malformed_fallback_ledger = json.loads(output_ledger_text)
        malformed_fallback_ledger["fallback_mode"]["active"] = "false"
        write(output_ledger_path, json.dumps(malformed_fallback_ledger, indent=2))
        malformed_fallback_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(output / "manifest.json"),
                "--reports",
                str(canonical_complete),
            ],
            expect=1,
        )
        check_output(malformed_fallback_result, "fallback_mode.active", "boolean")
        write(output_ledger_path, output_ledger_text)

        set_scenario("fallback ledger and optional scope modes")
        run([sys.executable, str(BUILD), "--repo", str(fixture), "--out", str(fallback_output), "--batch-size", "200"])
        fallback_complete = write_reports(base / "fallback-reports", fallback_output / "manifest.json")[-1]
        fallback_canonical_complete = install_report(fallback_output, fallback_complete)
        complete_effort_ledger(fallback_output, fallback=True)
        run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(fallback_output / "manifest.json"),
                "--reports",
                str(fallback_canonical_complete),
            ]
        )
        fallback_ledger_path = fallback_output / "effort_ledger.json"
        fallback_ledger_text = fallback_ledger_path.read_text(encoding="utf-8")
        fallback_ledger = json.loads(fallback_ledger_text)
        fallback_ledger["lead"] = {
            "status": "fallback-disclosed",
            "required_reasoning_effort": "xhigh",
            "actual_reasoning_effort": "manual-fallback",
            "agent_id": None,
            "notes": "self-test invalid lead fallback",
        }
        write(fallback_ledger_path, json.dumps(fallback_ledger, indent=2))
        lead_fallback_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(fallback_output / "manifest.json"),
                "--reports",
                str(fallback_canonical_complete),
            ],
            expect=1,
        )
        check_output(lead_fallback_result, "lead.actual_reasoning_effort", "xhigh")
        fallback_ledger = json.loads(fallback_ledger_text)
        fallback_ledger["subagent_capability_check"]["can_set_reasoning_effort"] = True
        write(fallback_ledger_path, json.dumps(fallback_ledger, indent=2))
        contradictory_fallback_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(fallback_output / "manifest.json"),
                "--reports",
                str(fallback_canonical_complete),
            ],
            expect=1,
        )
        check_output(contradictory_fallback_result, "effort_ledger_mismatches", "fallback_mode.active")
        write(fallback_ledger_path, fallback_ledger_text)

        run([sys.executable, str(BUILD), "--repo", str(fixture), "--out", str(spaced_output), "--batch-size", "200"])
        spaced_complete = write_reports(base / "spaced-reports", spaced_output / "manifest.json")[-1]
        write(spaced_output / "reports" / "batch_001.md", spaced_complete.read_text(encoding="utf-8"))
        complete_effort_ledger(spaced_output)
        spaced_manifest = json.loads((spaced_output / "manifest.json").read_text(encoding="utf-8"))
        check(spaced_manifest["verifier_args"][0] == sys.executable, "manifest should include the active Python executable in verifier_args")
        check(str((spaced_output / "manifest.json").resolve()) in spaced_manifest["verifier_args"], "verifier_args should include the manifest path")
        check(str((spaced_output / "reports").resolve()) in spaced_manifest["verifier_args"], "verifier_args should include the reports directory")
        run(spaced_manifest["verifier_args"])

        run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(fixture),
                "--out",
                str(no_config_output),
                "--batch-size",
                "200",
                "--no-include-config",
            ]
        )
        assert_message_catalogs_without_config(no_config_output / "manifest.json")

        run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(fixture),
                "--out",
                str(generated_output),
                "--batch-size",
                "200",
                "--include-generated",
            ]
        )
        assert_generated_included(generated_output / "manifest.json")

        run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(fixture),
                "--out",
                str(env_output),
                "--batch-size",
                "200",
                "--include-env",
            ]
        )
        assert_env_included(env_output / "manifest.json")

        run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(fixture),
                "--out",
                str(env_no_config_output),
                "--batch-size",
                "200",
                "--include-env",
                "--no-include-config",
            ]
        )
        assert_env_included_without_config(env_no_config_output / "manifest.json")

        run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(fixture),
                "--out",
                str(vendor_output),
                "--batch-size",
                "200",
                "--include-vendor",
            ]
        )
        assert_vendor_included(vendor_output / "manifest.json")

        run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(fixture),
                "--out",
                str(excluded_output),
                "--batch-size",
                "200",
                "--exclude-glob",
                "src/database.py",
            ]
        )
        assert_scope_warning(excluded_output / "manifest.json", excluded_output / "excluded_files.json")
        excluded_complete = write_reports(base / "excluded-reports", excluded_output / "manifest.json")[-1]
        complete_effort_ledger(excluded_output)
        unresolved_scope_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(excluded_output / "manifest.json"),
                "--reports",
                str(excluded_complete),
            ],
            expect=1,
        )
        check_output(unresolved_scope_result, "unresolved_scope_warnings", "src/database.py")

        forced_warning_output = base / "warning-output-forced"
        run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(warning_fixture),
                "--out",
                str(forced_warning_output),
                "--batch-size",
                "200",
                "--include-file",
                "src/mystery.widget",
            ]
        )
        forced_manifest = json.loads((forced_warning_output / "manifest.json").read_text(encoding="utf-8"))
        forced_files = {item["rel_path"]: item for item in forced_manifest["source_files"]}
        check(forced_files["src/mystery.widget"]["kind"] == "source/manual", "--include-file should force source/manual")
        check(forced_manifest["scope_warning_count"] == 0, "--include-file should resolve the warning")
        forced_complete = write_reports(base / "forced-warning-reports", forced_warning_output / "manifest.json")[-1]
        forced_canonical_complete = install_report(forced_warning_output, forced_complete)
        complete_effort_ledger(forced_warning_output)
        run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(forced_warning_output / "manifest.json"),
                "--reports",
                str(forced_canonical_complete),
            ]
        )
        bad_sentinel_report = base / "forced-warning-reports" / "bad-sentinel" / "batch_001.md"
        write(
            bad_sentinel_report,
            forced_complete.read_text(encoding="utf-8").replace(
                "No interface-relevant files in this batch.",
                "no interface-relevant files in this batch.",
            ),
        )
        bad_sentinel_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(forced_warning_output / "manifest.json"),
                "--reports",
                str(install_report(forced_warning_output, bad_sentinel_report)),
            ],
            expect=1,
        )
        check_output(bad_sentinel_result, "interface_inventory_issues", "exact no-interface sentinel")

        set_scenario("source-backed placeholder and dead-control enforcement")
        non_interface_todo_fixture = base / "non-interface-todo-fixture"
        write(non_interface_todo_fixture / "src" / "service.py", "# TODO wire this service\nVALUE = 1\n")
        non_interface_todo_output = base / "non-interface-todo-output"
        run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(non_interface_todo_fixture),
                "--out",
                str(non_interface_todo_output),
                "--batch-size",
                "200",
            ]
        )
        non_interface_todo_complete = write_reports(
            base / "non-interface-todo-reports",
            non_interface_todo_output / "manifest.json",
        )[-1]
        complete_effort_ledger(non_interface_todo_output)
        non_interface_todo_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(non_interface_todo_output / "manifest.json"),
                "--reports",
                str(install_report(non_interface_todo_output, non_interface_todo_complete)),
            ],
            expect=1,
        )
        check_output(non_interface_todo_result, "placeholder_omissions", "service.py")

        partial_placeholder_fixture = base / "partial-placeholder-fixture"
        write(
            partial_placeholder_fixture / "src" / "service.py",
            "# TODO wire this service\ndef run():\n    raise NotImplementedError('wire real runner')\n",
        )
        partial_placeholder_output = base / "partial-placeholder-output"
        run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(partial_placeholder_fixture),
                "--out",
                str(partial_placeholder_output),
                "--batch-size",
                "200",
            ]
        )
        partial_placeholder_complete = write_reports(
            base / "partial-placeholder-reports",
            partial_placeholder_output / "manifest.json",
        )[-1]
        partial_placeholder_report = base / "partial-placeholder-reports" / "partial" / "batch_001.md"
        write(
            partial_placeholder_report,
            partial_placeholder_complete.read_text(encoding="utf-8").replace(
                "No findings.",
                """### P2 - TODO only
- Files: `src/service.py`
- Evidence: The file contains a TODO comment for wiring the service.
- Interface evidence: Not applicable.
- Expected behavior/standard: Placeholder files should have every detected marker covered.
- Gap: The finding covers only the TODO marker and omits the runtime placeholder path.
- Suggested direction: Require per-marker placeholder coverage.""",
                1,
            ),
        )
        complete_effort_ledger(partial_placeholder_output)
        partial_placeholder_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(partial_placeholder_output / "manifest.json"),
                "--reports",
                str(install_report(partial_placeholder_output, partial_placeholder_report)),
            ],
            expect=1,
        )
        check_output(partial_placeholder_result, "placeholder_omissions", "missing_markers", "NotImplementedError")

        non_interface_stub_fixture = base / "non-interface-stub-fixture"
        write(non_interface_stub_fixture / "src" / "service.py", "def run():\n    raise NotImplementedError('wire real runner')\n")
        non_interface_stub_output = base / "non-interface-stub-output"
        run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(non_interface_stub_fixture),
                "--out",
                str(non_interface_stub_output),
                "--batch-size",
                "200",
            ]
        )
        non_interface_stub_complete = write_reports(
            base / "non-interface-stub-reports",
            non_interface_stub_output / "manifest.json",
        )[-1]
        complete_effort_ledger(non_interface_stub_output)
        non_interface_stub_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(non_interface_stub_output / "manifest.json"),
                "--reports",
                str(install_report(non_interface_stub_output, non_interface_stub_complete)),
            ],
            expect=1,
        )
        check_output(non_interface_stub_result, "placeholder_omissions", "NotImplementedError")

        noop_ui_fixture = base / "noop-ui-fixture"
        write(
            noop_ui_fixture / "src" / "components" / "IconButton.tsx",
            """const noop = () => {};

export function IconButton() {
  return (
	    <div>
	      <button onClick={() => {}} />
	      <button disabled>Disabled action</button>
	      <a href={"#"}>Dead link</a>
	      <IconButton onClick={noop} />
	      <div role="button"></div>
	      <form>
	        <input />
	        <select disabled><option>Any</option></select>
	        <textarea></textarea>
	        <div role="tab"></div>
	      </form>
	      <form data-action="fake">
	        <input aria-label="Search term" />
	      </form>
	      <button onClick={() => console.warn("placeholder")}>Warn only</button>
	    </div>
  );
}
""",
        )
        noop_ui_output = base / "noop-ui-output"
        run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(noop_ui_fixture),
                "--out",
                str(noop_ui_output),
                "--batch-size",
                "200",
            ]
        )
        noop_ui_complete = write_reports(
            base / "noop-ui-reports",
            noop_ui_output / "manifest.json",
        )[-1]
        complete_effort_ledger(noop_ui_output)
        noop_ui_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(noop_ui_output / "manifest.json"),
                "--reports",
                str(install_report(noop_ui_output, noop_ui_complete)),
            ],
            expect=1,
        )
        check_output(
            noop_ui_result,
            "interface_control_omissions",
            "unlabeled button",
            "empty handler",
            "named no-op handler",
	            "dead link",
	            "static disabled control",
	            "form without submit handler or action",
	            "data-action",
	            "unlabeled form field",
	            "static disabled form field",
	            "interactive role without handler",
	            "role button without click or keyboard handler",
	        )
        native_ui_fixture = base / "native-ui-fixture"
        write(
            native_ui_fixture / "Views" / "MainWindow.axaml",
            '<Window><Button Content="Disabled Native" IsEnabled="False" /></Window>\n',
        )
        native_ui_output = base / "native-ui-output"
        run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(native_ui_fixture),
                "--out",
                str(native_ui_output),
                "--batch-size",
                "200",
            ]
        )
        native_ui_complete = write_reports(
            base / "native-ui-reports",
            native_ui_output / "manifest.json",
        )[-1]
        complete_effort_ledger(native_ui_output)
        native_ui_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(native_ui_output / "manifest.json"),
                "--reports",
                str(install_report(native_ui_output, native_ui_complete)),
            ],
            expect=1,
        )
        check_output(native_ui_result, "interface_control_omissions", "static disabled control", "IsEnabled")
        partial_control_report = base / "noop-ui-reports" / "partial-control" / "batch_001.md"
        partial_control_text = noop_ui_complete.read_text(encoding="utf-8").replace(
            "No findings.",
            """### P2 - Empty handler only
- Files: `src/components/IconButton.tsx`
- Evidence: The source has an empty handler on the first button.
- Interface evidence: source anchor empty handler
- Expected behavior/standard: Interface controls should not expose no-op actions.
- Gap: The report covers only the empty handler and misses the other dead controls.
- Suggested direction: Cover every detected dead-control marker in findings.""",
            1,
        )
        write(partial_control_report, partial_control_text)
        partial_control_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(noop_ui_output / "manifest.json"),
                "--reports",
                str(install_report(noop_ui_output, partial_control_report)),
            ],
            expect=1,
        )
        check_output(partial_control_result, "interface_control_omissions", "missing_markers", "dead link", "static disabled control", "unlabeled form field")

        invalid_batch_size = run(
            [
                sys.executable,
                str(BUILD),
                "--repo",
                str(fixture),
                "--out",
                str(base / "audit-output-invalid"),
                "--batch-size",
                "0",
            ],
            expect=2,
        )
        check("Traceback" not in invalid_batch_size.stderr, "invalid --batch-size should not emit a traceback")

        incomplete_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(output / "manifest.json"),
                "--reports",
                str(install_report(output, incomplete)),
            ],
            expect=1,
        )
        check_output(incomplete_result, "missing:", "missing_sections:")
        malformed_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(output / "manifest.json"),
                "--reports",
                str(install_report(output, malformed_pipe)),
            ],
            expect=1,
        )
        check_output(malformed_result, "malformed_rows:", "extra column")
        stale_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(output / "manifest.json"),
                "--reports",
                str(install_report(output, stale_hash)),
            ],
            expect=1,
        )
        check_output(stale_result, "report_hash_mismatches:")
        invalid_utf8_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(output / "manifest.json"),
                "--reports",
                str(invalid_utf8),
            ],
            expect=2,
        )
        check_output(invalid_utf8_result, "Report file is not valid UTF-8")
        invalid_filename_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(output / "manifest.json"),
                "--reports",
                str(invalid_filename),
            ],
            expect=2,
        )
        check_output(invalid_filename_result, "Report file must use exact batch_###.md filename")
        missing_purpose_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(output / "manifest.json"),
                "--reports",
                str(install_report(output, missing_purpose)),
            ],
            expect=1,
        )
        check_output(missing_purpose_result, "malformed_rows:")
        wrong_batch_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(output / "manifest.json"),
                "--reports",
                str(install_report(output, wrong_batch)),
            ],
            expect=1,
        )
        check_output(wrong_batch_result, "batch_id_mismatches:", "batch_999")
        missing_sections_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(output / "manifest.json"),
                "--reports",
                str(install_report(output, missing_sections)),
            ],
            expect=1,
        )
        check_output(missing_sections_result, "missing_sections:")
        extra_section_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(output / "manifest.json"),
                "--reports",
                str(install_report(output, extra_section)),
            ],
            expect=1,
        )
        check_output(extra_section_result, "section_shape_mismatches:", "extra section")
        unchecked_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(output / "manifest.json"),
                "--reports",
                str(install_report(output, unchecked)),
            ],
            expect=1,
        )
        check_output(unchecked_result, "unchecked:", "SKILL.md")
        canonical_complete = install_report(output, complete)
        excluded_files_path = output / "excluded_files.json"
        original_excluded_files = excluded_files_path.read_text(encoding="utf-8")
        excluded_files_path.unlink()
        missing_excluded_files_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(output / "manifest.json"),
                "--reports",
                str(canonical_complete),
            ],
            expect=2,
        )
        check_output(missing_excluded_files_result, "excluded_files.json is missing")
        write(excluded_files_path, original_excluded_files)
        stale_excluded_files = json.loads(original_excluded_files)
        stale_excluded_files.append({"path": "ghost.py", "reason": "stale warning", "scope_warning": True})
        stale_excluded_files.append({"path": "ghost-two.py", "reason": "stale warning", "scope_warning": True})
        write(excluded_files_path, json.dumps(stale_excluded_files, indent=2))
        stale_excluded_files_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(output / "manifest.json"),
                "--reports",
                str(canonical_complete),
            ],
            expect=1,
        )
        check_output(stale_excluded_files_result, "excluded_file_mismatches", "ghost.py", "ghost-two.py")
        check("Traceback" not in stale_excluded_files_result.stderr, "stale excluded files should not traceback")
        write(excluded_files_path, original_excluded_files)
        truncated_excluded_files = [
            item for item in json.loads(original_excluded_files) if item.get("scope_warning")
        ]
        write(excluded_files_path, json.dumps(truncated_excluded_files, indent=2))
        truncated_excluded_files_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(output / "manifest.json"),
                "--reports",
                str(canonical_complete),
            ],
            expect=1,
        )
        check_output(truncated_excluded_files_result, "excluded_files_sha256", "excluded_file_count")
        write(excluded_files_path, original_excluded_files)
        run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(output / "manifest.json"),
                "--reports",
                str(canonical_complete),
            ]
        )
        skip_freshness_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(output / "manifest.json"),
                "--reports",
                str(canonical_complete),
                "--skip-current-hash-check",
            ],
            expect=1,
        )
        check_output(skip_freshness_result, "verification_warnings:", "--skip-current-hash-check", "ok: false")
        marker_text = (output / "queue_complete.json").read_text(encoding="utf-8")
        ledger_text = (output / "effort_ledger.json").read_text(encoding="utf-8")
        missing_root_dir = base / "missing-root-copy"
        missing_root_manifest = missing_root_dir / "manifest.json"
        write(missing_root_dir / "queue_complete.json", marker_text)
        write(missing_root_dir / "effort_ledger.json", ledger_text)
        write(missing_root_dir / "excluded_files.json", original_excluded_files)
        missing_root_report = install_report(missing_root_dir, complete)
        missing_root_data = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        missing_root_data["repo_root"] = str(base / "missing-repo-root")
        write(missing_root_manifest, json.dumps(missing_root_data, indent=2))
        missing_root_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(missing_root_manifest),
                "--reports",
                str(missing_root_report),
            ],
            expect=1,
        )
        check_output(missing_root_result, "current_hash_errors:", "repo_root is missing")
        missing_root_skip_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(missing_root_manifest),
                "--reports",
                str(missing_root_report),
                "--skip-current-hash-check",
            ],
            expect=1,
        )
        check_output(missing_root_skip_result, "source_text_errors:", "source-backed interface")
        empty_root_dir = base / "empty-root-copy"
        empty_root_manifest = empty_root_dir / "manifest.json"
        write(empty_root_dir / "queue_complete.json", marker_text)
        write(empty_root_dir / "effort_ledger.json", ledger_text)
        write(empty_root_dir / "excluded_files.json", original_excluded_files)
        empty_root_report = install_report(empty_root_dir, complete)
        empty_root_data = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        empty_root_data["repo_root"] = ""
        write(empty_root_manifest, json.dumps(empty_root_data, indent=2))
        empty_root_skip_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(empty_root_manifest),
                "--reports",
                str(empty_root_report),
                "--skip-current-hash-check",
            ],
            expect=1,
        )
        check_output(empty_root_skip_result, "source_text_errors:", "repo_root")
        invalid_manifest_dir = base / "invalid-manifest-copy"
        invalid_manifest = invalid_manifest_dir / "manifest.json"
        write(invalid_manifest_dir / "queue_complete.json", marker_text)
        write(invalid_manifest, '{"source_files":[{}],"batches":[]}\n')
        invalid_manifest_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(invalid_manifest),
                "--reports",
                str(complete),
            ],
            expect=2,
        )
        check_output(invalid_manifest_result, "source_files[0].rel_path")
        invalid_manifest_json_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(invalid_manifest),
                "--reports",
                str(complete),
                "--json",
            ],
            expect=2,
        )
        fatal_payload = json.loads(invalid_manifest_json_result.stdout)
        check(fatal_payload["ok"] is False, "--json fatal verifier errors should return ok=false")
        check(fatal_payload["error"]["type"] == "ValueError", "--json fatal verifier errors should name the error type")
        check(
            "source_files[0].rel_path" in fatal_payload["error"]["message"],
            "--json fatal verifier errors should include the validation message",
        )
        check(not invalid_manifest_json_result.stderr.strip(), "--json fatal verifier errors should avoid plain stderr")
        duplicate_manifest_dir = base / "duplicate-manifest-copy"
        duplicate_manifest = duplicate_manifest_dir / "manifest.json"
        write(duplicate_manifest_dir / "queue_complete.json", marker_text)
        duplicate_data = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        duplicate_data["source_files"].append(duplicate_data["source_files"][0])
        write(duplicate_manifest, json.dumps(duplicate_data, indent=2))
        duplicate_manifest_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(duplicate_manifest),
                "--reports",
                str(complete),
            ],
            expect=2,
        )
        check_output(duplicate_manifest_result, "source_files rel_path values must be unique")
        unit_hash_type_dir = base / "unit-hash-type-manifest-copy"
        unit_hash_type_manifest = unit_hash_type_dir / "manifest.json"
        write(unit_hash_type_dir / "queue_complete.json", marker_text)
        unit_hash_type_data = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        unit_hash_type_data["coverage_units"][0]["sha256"] = 7
        write(unit_hash_type_manifest, json.dumps(unit_hash_type_data, indent=2))
        unit_hash_type_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(unit_hash_type_manifest),
                "--reports",
                str(complete),
            ],
            expect=2,
        )
        check_output(unit_hash_type_result, "coverage_units[0].sha256 must be a string")
        count_manifest_dir = base / "count-manifest-copy"
        count_manifest = count_manifest_dir / "manifest.json"
        count_marker = json.loads(marker_text)
        count_marker["batch_count"] = 999
        count_marker["source_file_count"] = 999
        write(count_manifest_dir / "queue_complete.json", json.dumps(count_marker, indent=2))
        write(count_manifest_dir / "effort_ledger.json", ledger_text)
        write(count_manifest_dir / "excluded_files.json", original_excluded_files)
        install_report(count_manifest_dir, complete)
        count_data = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        count_data["source_file_count"] = 999
        count_data["batch_count"] = 999
        count_data["interface_file_count"] = 999
        count_data["scope_warning_count"] = 999
        write(count_manifest, json.dumps(count_data, indent=2))
        count_manifest_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(count_manifest),
                "--reports",
                str(count_manifest_dir / "reports"),
            ],
            expect=2,
        )
        check_output(count_manifest_result, "source_file_count must equal")
        bool_count_manifest_dir = base / "bool-count-manifest-copy"
        bool_count_manifest = bool_count_manifest_dir / "manifest.json"
        write(bool_count_manifest_dir / "queue_complete.json", marker_text)
        bool_count_data = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        bool_count_data["scope_warning_count"] = False
        write(bool_count_manifest, json.dumps(bool_count_data, indent=2))
        bool_count_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(bool_count_manifest),
                "--reports",
                str(complete),
            ],
            expect=2,
        )
        check_output(bool_count_result, "scope_warning_count must be an integer")
        journey_type_manifest_dir = base / "journey-type-manifest-copy"
        journey_type_manifest = journey_type_manifest_dir / "manifest.json"
        write(journey_type_manifest_dir / "queue_complete.json", marker_text)
        journey_type_data = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        journey_type_data["journey_audit"] = []
        write(journey_type_manifest, json.dumps(journey_type_data, indent=2))
        journey_type_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(journey_type_manifest),
                "--reports",
                str(complete),
            ],
            expect=2,
        )
        check_output(journey_type_result, "journey_audit must be an object")
        check("Traceback" not in f"{journey_type_result.stdout}\n{journey_type_result.stderr}", "non-object journey_audit should not crash verifier")
        escaping_manifest_dir = base / "escaping-manifest-copy"
        escaping_manifest = escaping_manifest_dir / "manifest.json"
        write(escaping_manifest_dir / "queue_complete.json", marker_text)
        escaping_data = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        escaping_data["source_files"][0]["rel_path"] = "../outside.py"
        write(escaping_manifest, json.dumps(escaping_data, indent=2))
        escaping_manifest_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(escaping_manifest),
                "--reports",
                str(complete),
            ],
            expect=2,
        )
        check_output(escaping_manifest_result, "repo-relative path")
        unsafe_manifest_dir = base / "unsafe-manifest-copy"
        unsafe_manifest = unsafe_manifest_dir / "manifest.json"
        write(unsafe_manifest_dir / "queue_complete.json", marker_text)
        unsafe_cases = [
            (
                "source path table delimiter",
                lambda data: data["source_files"][0].update({"rel_path": "src/bad|name.ts"}),
                "Markdown table/code delimiters",
            ),
            (
                "source path control character",
                lambda data: data["source_files"][0].update({"rel_path": "src/bad\nname.ts"}),
                "ASCII control characters",
            ),
            (
                "coverage unit id table delimiter",
                lambda data: data["coverage_units"][0].update({"unit_id": "src/foo---bar.ts|L1"}),
                "Markdown table/code delimiters",
            ),
            (
                "batch file leading whitespace",
                lambda data: data["batches"][0]["files"].__setitem__(0, " src/foo---bar.ts"),
                "leading or trailing whitespace",
            ),
        ]
        for case_name, mutate_manifest, expected_text in unsafe_cases:
            set_scenario(f"manifest unsafe token validation: {case_name}")
            unsafe_data = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            mutate_manifest(unsafe_data)
            write(unsafe_manifest, json.dumps(unsafe_data, indent=2))
            unsafe_manifest_result = run(
                [
                    sys.executable,
                    str(VERIFY),
                    "--manifest",
                    str(unsafe_manifest),
                    "--reports",
                    str(complete),
                ],
                expect=2,
            )
            check_output(unsafe_manifest_result, expected_text)
        set_scenario("manifest validation")
        bad_marker = output / "queue_complete.json"
        original_marker = bad_marker.read_text(encoding="utf-8")
        marker_data = json.loads(original_marker)
        marker_data["run_id"] = "wrong-run-id"
        write(bad_marker, json.dumps(marker_data, indent=2))
        marker_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(output / "manifest.json"),
                "--reports",
                str(canonical_complete),
            ],
            expect=1,
        )
        check_output(marker_result, "completion_marker_mismatches", "wrong-run-id")
        write(bad_marker, original_marker)
        marker_data = json.loads(original_marker)
        marker_data["ownership_marker"] = "foreign-marker.json"
        write(bad_marker, json.dumps(marker_data, indent=2))
        marker_ownership_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(output / "manifest.json"),
                "--reports",
                str(canonical_complete),
            ],
            expect=1,
        )
        check_output(marker_ownership_result, "completion_marker_mismatches", "ownership_marker", "foreign-marker.json")
        write(bad_marker, original_marker)
        marker_data = json.loads(original_marker)
        marker_data["marker_semantics"] = "already verified"
        write(bad_marker, json.dumps(marker_data, indent=2))
        marker_semantics_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(output / "manifest.json"),
                "--reports",
                str(canonical_complete),
            ],
            expect=1,
        )
        check_output(marker_semantics_result, "completion_marker_mismatches", "marker_semantics", "already verified")
        write(bad_marker, original_marker)
        legacy_marker_path = output / "audit_complete.json"
        write(legacy_marker_path, original_marker)
        legacy_marker_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(output / "manifest.json"),
                "--reports",
                str(canonical_complete),
            ],
            expect=1,
        )
        check_output(legacy_marker_result, "legacy audit_complete.json must not be used")
        legacy_marker_path.unlink()
        canonical_complete = install_report(output, complete)
        write(output / "reports" / "nested" / "batch_999.md", "stale nested report\n")
        run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(output / "manifest.json"),
                "--reports",
                str(output / "reports"),
            ]
        )
        write(fixture / "src" / "foo---bar.ts", "export const dashed = 'changed';\n")
        drift_result = run(
            [
                sys.executable,
                str(VERIFY),
                "--manifest",
                str(output / "manifest.json"),
                "--reports",
                str(canonical_complete),
            ],
            expect=1,
        )
        check_output(drift_result, "current_hash_mismatches:", "changed")
        scenario_runner.raise_if_failed()

    print("self-test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
