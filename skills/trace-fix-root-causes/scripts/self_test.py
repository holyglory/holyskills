#!/usr/bin/env python3
"""Self-tests for trace-fix-root-causes."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from shutil import rmtree


ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "scripts" / "verify_root_cause_report.py"
SKILL = ROOT / "SKILL.md"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run_verify(path: Path, *, expect: int = 0) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, str(VERIFY), str(path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != expect:
        raise AssertionError(
            f"expected {expect}, got {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


GOOD_BASE = """## Fixed Symptom
{symptom}

## Evidence Used
{evidence}

## Causal Chain
{chain}

## Root Cause Classification
{classification}

## Workflow Improvements
{improvements}

## Validation Plan
{validation}

## Boundaries And Non-Generalizable Notes
{boundaries}
"""


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="trace-fix-root-causes-self-test-"))
    try:
        skill_text = SKILL.read_text(encoding="utf-8")
        for needle in ("Trace Fix Root Causes", "do not invent root causes", "generalizable", "one-off"):
            check(needle.lower() in skill_text.lower(), f"SKILL.md should contain {needle!r}")

        audit_miss = tmp / "audit-miss.md"
        write(
            audit_miss,
            GOOD_BASE.format(
                symptom="UI audit passed a screen that showed overloaded status summaries.",
                evidence="User report, screenshot, audit output, and verifier source showed the pass.",
                chain="Requirements listed the facts, audit accepted source-inferred docs, verifier missed the visual overload, implementation preserved the text-heavy state.",
                classification="generalizable audit and verifier failure.",
                improvements="Update the UI audit skill and verifier fixture so overloaded default surfaces cannot pass.",
                validation="Run the verifier self-test fixture and rerun the UI audit command.",
                boundaries="The exact visual design remains repo-specific.",
            ),
        )
        run_verify(audit_miss)

        docs_induced = tmp / "docs-induced-ui.md"
        write(
            docs_induced,
            GOOD_BASE.format(
                symptom="A canonical journey doc caused a default command center to render too many detail fields.",
                evidence="File diff in docs/testing/canonical-journeys.md and before/after screenshot evidence.",
                chain="Journey docs over-prescribed visible evidence, implementation copied the handoff literally, tests checked presence rather than decision usefulness.",
                classification="local-repeatable docs-to-implementation handoff failure.",
                improvements="Change journey docs, add docs-audit regression fixture, and require disclosure paths for secondary detail.",
                validation="Run python3 scripts/validate.py and a screenshot-based audit fixture.",
                boundaries="Exact compact indicator design is product-specific.",
            ),
        )
        run_verify(docs_induced)

        implementation_only = tmp / "implementation-only.md"
        write(
            implementation_only,
            GOOD_BASE.format(
                symptom="A save button failed to persist one local field.",
                evidence="Failing unit test, source file diff, and reproduction log.",
                chain="Implementation omitted the persistence assignment, test coverage missed that field.",
                classification="one-off implementation defect.",
                improvements="Add a targeted regression test; no global policy change is recommended.",
                validation="Run the focused unit test command.",
                boundaries="No evidence connects this to docs, audits, or skill policy.",
            ),
        )
        run_verify(implementation_only)

        one_off = tmp / "one-off.md"
        write(
            one_off,
            GOOD_BASE.format(
                symptom="A local fixture used stale data after a manual run.",
                evidence="Reproduction log and before/after fixture file diff.",
                chain="Test fixture state was stale, implementation behaved correctly, review did not need a new global policy.",
                classification="one-off local fixture mistake.",
                improvements="No workflow changes; refresh the fixture and keep the existing test.",
                validation="Run the fixture reproduction command.",
                boundaries="The cause is local to one disposable fixture.",
            ),
        )
        run_verify(one_off)

        missing_evidence = tmp / "missing-evidence.md"
        write(
            missing_evidence,
            GOOD_BASE.format(
                symptom="A problem supposedly came from bad docs.",
                evidence="No evidence available.",
                chain="Docs and audit were probably responsible.",
                classification="generalizable workflow failure.",
                improvements="Update policies everywhere.",
                validation="Run a command later.",
                boundaries="None.",
            ),
        )
        run_verify(missing_evidence, expect=1)

        print("self-test ok")
        return 0
    finally:
        rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
