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

## Reproduction
{reproduction}

## User Intent And Scope Check
{intent}

## Evidence Used
{evidence}

## Causal Chain
{chain}

## Root Cause Classification
{classification}

## System Fix First
{system_fix}

## Testing Procedure Audit
{testing_audit}

## Implementation Gap Closure
{gap_closure}

## Retest Results
{retest}

## Comprehensive Retest Results
{comprehensive_retest}

## Boundaries And Non-Generalizable Notes
{boundaries}
"""


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="trace-fix-root-causes-self-test-"))
    try:
        skill_text = SKILL.read_text(encoding="utf-8")
        for needle in (
            "Trace Fix Root Causes",
            "do not invent root causes",
            "guardrail scope",
            "DecisionHistory.md",
            "generalized reusable rule",
            "/Users/holyglory/.codex/AGENTS.md",
            "generalizable",
            "one-off",
        ):
            check(needle.lower() in skill_text.lower(), f"SKILL.md should contain {needle!r}")

        audit_miss = tmp / "audit-miss.md"
        write(
            audit_miss,
            GOOD_BASE.format(
                symptom="UI audit passed a screen that showed overloaded status summaries.",
                reproduction="Reproduced through the same screenshot-based audit surface and original audit command.",
                intent="The user request was not changed; Codex and the audit perceived visible evidence as more important than the primary decision journey.",
                evidence="User report, screenshot, audit output, and verifier source showed the pass.",
                chain="Requirements listed the facts, audit accepted source-inferred docs, verifier missed the visual overload, implementation preserved the text-heavy state.",
                classification="generalizable audit and verifier failure.",
                system_fix="Updated the UI audit skill and verifier fixture so overloaded default surfaces cannot pass.",
                testing_audit="Audited the screenshot audit procedure for missed failures in adjacent journeys, edge cases, and acceptance criteria; added verifier coverage for overloaded default surfaces.",
                gap_closure="Fixed the implementation to reduce the default status surface.",
                retest="Reran the original audit command and the verifier self-test fixture; both passed.",
                comprehensive_retest="After the detected gap was closed, ran a broader visual audit suite and journey coverage matrix to prove the expected result.",
                boundaries="The exact visual design remains repo-specific.",
            ),
        )
        run_verify(audit_miss)

        docs_induced = tmp / "docs-induced-ui.md"
        write(
            docs_induced,
            GOOD_BASE.format(
                symptom="A canonical journey doc caused a default command center to render too many detail fields.",
                reproduction="Replicated on the original screen route with the before/after screenshot evidence.",
                intent="No user requirement changed; Codex followed the docs literally and missed the intended decision priority.",
                evidence="File diff in docs/testing/canonical-journeys.md and before/after screenshot evidence.",
                chain="Journey docs over-prescribed visible evidence, implementation copied the handoff literally, tests checked presence rather than decision usefulness.",
                classification="local-repeatable docs-to-implementation handoff failure.",
                system_fix="Changed journey docs, added a docs-audit regression fixture, and required disclosure paths for secondary detail.",
                testing_audit="Audited tests and docs verifier coverage for other possible missed failures in secondary detail, edge cases, and decision-usefulness acceptance criteria.",
                gap_closure="Patched the UI implementation to move secondary detail behind disclosure.",
                retest="Reran python3 scripts/validate.py and the screenshot-based audit fixture.",
                comprehensive_retest="After the gap closed, ran comprehensive screenshot, docs-audit, and end-to-end journey tests for the expected user result.",
                boundaries="Exact compact indicator design is product-specific.",
            ),
        )
        run_verify(docs_induced)

        implementation_only = tmp / "implementation-only.md"
        write(
            implementation_only,
            GOOD_BASE.format(
                symptom="A save button failed to persist one local field.",
                reproduction="Reproduced with the original focused unit test command.",
                intent="The request and requirement were not changed; Codex omitted one field assignment in implementation.",
                evidence="Failing unit test, source file diff, and reproduction log.",
                chain="Implementation omitted the persistence assignment, test coverage missed that field.",
                classification="one-off implementation defect.",
                system_fix="Added a targeted regression test; no broad policy change is recommended.",
                testing_audit="Audited the field persistence tests for adjacent missed fields and edge cases; no other possible failures were found beyond the targeted coverage.",
                gap_closure="Fixed the product code by assigning the missing persistence field.",
                retest="Reran the original focused unit test command and the new regression test; both passed.",
                comprehensive_retest="After the fix, ran the full unit suite and persistence coverage test matrix to prove the expected result.",
                boundaries="No evidence connects this to docs, audits, or skill policy.",
            ),
        )
        run_verify(implementation_only)

        one_off = tmp / "one-off.md"
        write(
            one_off,
            GOOD_BASE.format(
                symptom="A local fixture used stale data after a manual run.",
                reproduction="Replicated with the original fixture reproduction command.",
                intent="The user request did not change; this was a stale local test fixture, not a changed requirement.",
                evidence="Reproduction log and before/after fixture file diff.",
                chain="Test fixture state was stale, implementation behaved correctly, review did not need a new global policy.",
                classification="one-off local fixture mistake.",
                system_fix="Refreshed the fixture and kept the existing test as the targeted guardrail.",
                testing_audit="Audited fixture and smoke test coverage for adjacent stale data risks and other possible missed failures.",
                gap_closure="No product code fix was applicable because implementation behaved correctly.",
                retest="Reran the fixture reproduction command and existing test; both passed.",
                comprehensive_retest="After fixture refresh, ran the comprehensive fixture suite and smoke checks for the expected result.",
                boundaries="The cause is local to one disposable fixture.",
            ),
        )
        run_verify(one_off)

        one_off_policy_explanation = tmp / "one-off-policy-explanation.md"
        write(
            one_off_policy_explanation,
            GOOD_BASE.format(
                symptom="Codex wrote an incident-specific explanation into repo AGENTS.md for a mistake that may never happen again.",
                reproduction="Reproduced from the same conversation log and repo policy surface.",
                intent="The request used global policies and AGENTS.md ambiguously; Codex treated repo-wide AGENTS.md as the policy target.",
                evidence="User report and conversation log showed the AGENTS.md update and follow-up concern.",
                chain="User intent around policy scope was ambiguous; skill instructions listed AGENTS.md as a guardrail; implementation wrote incident explanation into repo policy.",
                classification="one-off recurrence risk for this exact incident.",
                system_fix="Update repo-wide AGENTS.md with an explanation of this incident so future agents remember it.",
                testing_audit="Audited verifier coverage for adjacent missed failures around guardrail scope and policy placement.",
                gap_closure="Fixed the policy text.",
                retest="Reran the verifier command and self-test.",
                comprehensive_retest="After the gap was closed, ran the full skill self-test suite.",
                boundaries="The exact action-row mistake may never recur.",
            ),
        )
        run_verify(one_off_policy_explanation, expect=1)

        repeatable_policy_without_general_rule = tmp / "repeatable-policy-without-general-rule.md"
        write(
            repeatable_policy_without_general_rule,
            GOOD_BASE.format(
                symptom="A repeated destructive-action UI mistake was traced to unclear repo policy.",
                reproduction="Reproduced from the same UI journey and source diff.",
                intent="The user request was not changed; Codex missed row-level destructive action placement.",
                evidence="User report, screenshot, and code diff.",
                chain="Requirements and implementation both missed row-action placement; policy did not cover destructive list actions.",
                classification="local-repeatable UI policy gap.",
                system_fix="Update repo-wide AGENTS.md with a note about the mistake.",
                testing_audit="Audited UI smoke tests for adjacent destructive action failure modes.",
                gap_closure="Fixed the implementation code.",
                retest="Reran the verifier command and self-test.",
                comprehensive_retest="After the gap was closed, ran the full UI test suite.",
                boundaries="Exact copy and layout remain product-specific.",
            ),
        )
        run_verify(repeatable_policy_without_general_rule, expect=1)

        global_policy_without_app_agents = tmp / "global-policy-without-app-agents.md"
        write(
            global_policy_without_app_agents,
            GOOD_BASE.format(
                symptom="Codex agents repeatedly miss a cross-repo policy requirement.",
                reproduction="Reproduced with a report accepted by the verifier while omitting the app-wide AGENTS.md target.",
                intent="The request was not changed; the issue is global across Codex behavior, not repo-local.",
                evidence="User report, skill text, and verifier source showed the gap.",
                chain="User intent required app-wide behavior; skill policy allowed global policy wording; verifier accepted reports that did not name the Codex app-wide AGENTS.md guardrail.",
                classification="generalizable policy-scope failure across Codex tasks.",
                system_fix="Update global policy with a generalized reusable rule requiring app-wide guardrails for broad Codex behavior.",
                testing_audit="Audited verifier tests for adjacent policy-scope failure modes and app-wide guardrail coverage.",
                gap_closure="Fixed the skill and verifier.",
                retest="Reran the verifier command and self-test.",
                comprehensive_retest="After the gap was closed, ran the full skill self-test suite.",
                boundaries="Repo-local policies still apply when the cause is repo-specific.",
            ),
        )
        run_verify(global_policy_without_app_agents, expect=1)

        global_policy_with_app_agents = tmp / "global-policy-with-app-agents.md"
        write(
            global_policy_with_app_agents,
            GOOD_BASE.format(
                symptom="Codex agents repeatedly miss a cross-repo policy requirement.",
                reproduction="Reproduced with a report accepted by the verifier while omitting the app-wide AGENTS.md target.",
                intent="The request was not changed; the issue is global across Codex behavior, not repo-local.",
                evidence="User report, skill text, and verifier source showed the gap.",
                chain="User intent required app-wide behavior; skill policy allowed global policy wording; verifier accepted reports that did not name the Codex app-wide AGENTS.md guardrail.",
                classification="generalizable policy-scope failure across Codex tasks.",
                system_fix="Update /Users/holyglory/.codex/AGENTS.md with a generalized reusable rule requiring app-wide guardrails for broad Codex behavior, plus update the skill verifier.",
                testing_audit="Audited verifier tests for adjacent policy-scope failure modes and app-wide guardrail coverage.",
                gap_closure="Fixed the skill and verifier.",
                retest="Reran the verifier command and self-test.",
                comprehensive_retest="After the gap was closed, ran the full skill self-test suite.",
                boundaries="Repo-local policies still apply when the cause is repo-specific.",
            ),
        )
        run_verify(global_policy_with_app_agents)

        missing_reproduction = tmp / "missing-reproduction.md"
        write(
            missing_reproduction,
            GOOD_BASE.format(
                symptom="Codex shipped the wrong behavior.",
                reproduction="User saw it.",
                intent="The request was not changed; Codex misread the requirement.",
                evidence="User report and source file diff.",
                chain="Implementation missed the docs and tests did not cover the journey.",
                classification="local-repeatable implementation and test gap.",
                system_fix="Updated docs and tests.",
                testing_audit="Audited tests for adjacent edge cases and missed failures.",
                gap_closure="Fixed the implementation code.",
                retest="Reran the original command and regression test.",
                comprehensive_retest="After the gap was closed, ran the broader integration test suite.",
                boundaries="None.",
            ),
        )
        run_verify(missing_reproduction, expect=1)

        missing_system_fix = tmp / "missing-system-fix.md"
        write(
            missing_system_fix,
            GOOD_BASE.format(
                symptom="Codex shipped the wrong behavior.",
                reproduction="Reproduced with the same screen route.",
                intent="No requirement changed; Codex misread the user request.",
                evidence="User report, screenshot, and source file diff.",
                chain="Implementation missed the docs and tests did not cover the journey.",
                classification="local-repeatable implementation and test gap.",
                system_fix="None.",
                testing_audit="Audited tests for adjacent edge cases and missed failures.",
                gap_closure="Fixed the implementation code.",
                retest="Reran the original route and regression test.",
                comprehensive_retest="After the gap was closed, ran the broader integration test suite.",
                boundaries="None.",
            ),
        )
        run_verify(missing_system_fix, expect=1)

        missing_testing_audit = tmp / "missing-testing-audit.md"
        write(
            missing_testing_audit,
            GOOD_BASE.format(
                symptom="Codex missed a broken export flow after implementation.",
                reproduction="Reproduced on the same screen route and export command.",
                intent="The user request was not changed; Codex misread the requirement.",
                evidence="User report, screenshot, source file diff, and reproduction log.",
                chain="Implementation skipped one export branch and tests only covered the happy path.",
                classification="local-repeatable implementation and test gap.",
                system_fix="Updated the test fixture for the missed export branch.",
                testing_audit="Added one regression.",
                gap_closure="Fixed the product code for the export branch.",
                retest="Reran the original route and regression test; both passed.",
                comprehensive_retest="After the gap was closed, ran the broader integration test suite.",
                boundaries="None.",
            ),
        )
        run_verify(missing_testing_audit, expect=1)

        missing_comprehensive_retest = tmp / "missing-comprehensive-retest.md"
        write(
            missing_comprehensive_retest,
            GOOD_BASE.format(
                symptom="Codex missed a broken export flow after implementation.",
                reproduction="Reproduced on the same screen route and export command.",
                intent="The user request was not changed; Codex misread the requirement.",
                evidence="User report, screenshot, source file diff, and reproduction log.",
                chain="Implementation skipped one export branch and tests only covered the happy path.",
                classification="local-repeatable implementation and test gap.",
                system_fix="Updated the test fixture for the missed export branch.",
                testing_audit="Audited the testing procedure for adjacent journeys, edge cases, and other possible missed failures.",
                gap_closure="Fixed the product code for the export branch.",
                retest="Reran the original route and regression test; both passed.",
                comprehensive_retest="Reran the regression test.",
                boundaries="None.",
            ),
        )
        run_verify(missing_comprehensive_retest, expect=1)

        missing_evidence = tmp / "missing-evidence.md"
        write(
            missing_evidence,
            GOOD_BASE.format(
                symptom="A problem supposedly came from bad docs.",
                reproduction="Unable to reproduce because no original surface or artifact was available.",
                intent="The request status is unconfirmed because no original request or clarification evidence is available.",
                evidence="No evidence available.",
                chain="Docs and audit were probably responsible.",
                classification="generalizable workflow failure.",
                system_fix="Updated policies everywhere.",
                testing_audit="Audited testing procedure status is unconfirmed because no tests or missed-failure evidence is available.",
                gap_closure="No product fix was applicable without evidence.",
                retest="Run a verifier command later.",
                comprehensive_retest="After evidence is available, run comprehensive verifier and test coverage checks.",
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
