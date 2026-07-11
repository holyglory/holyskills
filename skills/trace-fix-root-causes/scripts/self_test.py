#!/usr/bin/env python3
"""Recall, evidence-discipline, authorization, and false-positive tests."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from shutil import rmtree


ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "scripts" / "verify_root_cause_report.py"
SKILL = ROOT / "SKILL.md"


TEMPLATE = """## Fixed Symptom
{symptom}

## Reproduction
{reproduction}

## User Intent And Scope Check
{intent}

## Authorization And Action Mode
{mode}

## Incident Class
{incident_class}

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
{comprehensive}

## Boundaries And Non-Generalizable Notes
{boundaries}
"""


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def run_verify(path: Path, *, expect: int = 0, issue: str | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, str(VERIFY), str(path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != expect:
        raise AssertionError(f"expected {expect}, got {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
    if issue is not None:
        check(issue.lower() in result.stderr.lower(), f"expected issue {issue!r} in:\n{result.stderr}")
    return result


def standard_report(**overrides: str) -> str:
    values = {
        "symptom": "A saved preference was missing after the agent reported the implementation complete.",
        "reproduction": "Reproduced through the original settings screen and persistence test command.",
        "intent": "The user requirement did not change; the request explicitly required persistent storage.",
        "mode": "authorized-fix",
        "incident_class": "implementation",
        "evidence": "\n".join(
            [
                "- E1 | kind: user-report | source: conversation request | observation: persistent storage was required | status: confirmed",
                "- E2 | kind: file | source: SettingsStore.swift | observation: implementation omitted the assignment | status: confirmed",
                "- E3 | kind: test | source: persistence regression test | observation: pre-fix test failed and exposed missing saved state | status: confirmed",
            ]
        ),
        "chain": "\n".join(
            [
                "- C1 | link: origin | evidence: E1 | status: confirmed | finding: user intent and requirements specified persistence",
                "- C2 | link: immediate-defect | evidence: E2 | status: confirmed | finding: implementation omitted one persisted assignment",
                "- C3 | link: missed-detection | evidence: E3 | status: confirmed | finding: tests asserted the action result but not persisted state",
            ]
        ),
        "classification": "local-repeatable implementation and test gap.",
        "system_fix": "Applied a realistic persistence regression test and verifier guardrail before product code changes.",
        "testing_audit": "The unit test ran but missed persisted state; adjacent field, reload, and failure-path coverage was absent, so those tests were added.",
        "gap_closure": "Fixed the product implementation by persisting the omitted field.",
        "retest": "Reran the original settings-screen reproduction and regression test; both passed.",
        "comprehensive": "After the fix, ran the broader unit, integration, reload, and failure-path test matrix for the expected result.",
        "boundaries": "The exact field is product-specific; the persistence test pattern is reusable.",
    }
    values.update(overrides)
    return TEMPLATE.format(**values)


def test_advertised_incident_classes(tmp: Path) -> None:
    implementation = tmp / "implementation.md"
    write(implementation, standard_report())
    run_verify(implementation)

    service = tmp / "service.md"
    write(
        service,
        standard_report(
            incident_class="service",
            symptom="A coordinator-managed local service crashed and showed unhealthy with pid_alive=false.",
            reproduction="Reproduced through the original coordinator status command and failing localhost URL.",
            evidence="\n".join(
                [
                    "- E1 | kind: user-report | source: reported localhost URL | observation: service was not responding | status: confirmed",
                    "- E2 | kind: log | source: coordinator log_path and events.jsonl | observation: process exit code 1, stderr cache failure, pid_alive=false | status: confirmed",
                    "- E3 | kind: command | source: coordinator inventory command | observation: health was unhealthy before restart | status: confirmed",
                ]
            ),
            chain="\n".join(
                [
                    "- C1 | link: origin | evidence: E1 | status: confirmed | finding: user request required the local service to remain available",
                    "- C2 | link: immediate-defect | evidence: E2 | status: confirmed | finding: toolchain generated cache failure terminated the server wrapper",
                    "- C3 | link: missed-detection | evidence: E3 | status: confirmed | finding: coordinator skill tests checked start success but missed sustained health",
                ]
            ),
            classification="generalizable service-crash detection gap.",
            system_fix="Applied a coordinator skill guardrail and self-test requiring crash evidence before restart and sustained health afterward.",
            testing_audit="The start check ran but missed process-exit and cache failure coverage; adjacent wrong-port, dependency, and stale-metadata tests were absent and added.",
            gap_closure="Fixed the wrapper and cache recovery implementation after preserving evidence.",
            retest="Reran coordinator status and the same failing URL with sustained health monitoring; all passed.",
            comprehensive="After the service fix, ran the broader coordinator, browser, curl, dependency, and stability test matrix.",
        ),
    )
    run_verify(service)

    factual = tmp / "factual.md"
    write(
        factual,
        standard_report(
            incident_class="factual",
            symptom="The delivered answer contained an incorrect fact, a factual error at answer time.",
            reproduction="Reproduced from the original answer and cited primary-source page.",
            evidence="\n".join(
                [
                    "- E1 | kind: user-report | source: conversation answer | observation: exact disputed claim was preserved | status: confirmed",
                    "- E2 | kind: source-citation | source: primary source dated 2026-07-09 | observation: as of the answer timestamp, the claim contradicted the source | status: confirmed",
                    "- E3 | kind: verifier | source: citation checker | observation: pre-fix citation check failed | status: confirmed",
                ]
            ),
            chain="\n".join(
                [
                    "- C1 | link: origin | evidence: E1 | status: confirmed | finding: user intent required a current sourced fact",
                    "- C2 | link: immediate-defect | evidence: E2 | status: confirmed | finding: source citation contradicted the answer implementation",
                    "- C3 | link: missed-detection | evidence: E3 | status: confirmed | finding: verifier tests checked citation presence but not claim support",
                ]
            ),
            classification="generalizable factual verification gap.",
            system_fix="Applied a source-support verifier test and freshness guardrail.",
            testing_audit="Citation checks ran but missed claim support and date freshness; adjacent primary-source and changed-fact coverage was absent and added.",
            gap_closure="Fixed the answer with the source-supported fact.",
            retest="Reran the original source citation check and support verifier; both passed.",
            comprehensive="After the factual fix, ran the broader citation, freshness, and primary-source verification matrix.",
        ),
    )
    run_verify(factual)

    reasoning = tmp / "reasoning.md"
    write(
        reasoning,
        standard_report(
            incident_class="reasoning",
            symptom="The recommendation contained a reasoning error caused by an invalid assumption.",
            reproduction="Reproduced with the original input constraints and counterexample test command.",
            evidence="\n".join(
                [
                    "- E1 | kind: user-report | source: original prompt | observation: required constraint was explicit | status: confirmed",
                    "- E2 | kind: source | source: constraint document dated 2026-07-10 | observation: at delivery the assumption contradicted the documented constraint | status: confirmed",
                    "- E3 | kind: test | source: executable counterexample | observation: proposed decision violated the constraint | status: confirmed",
                ]
            ),
            chain="\n".join(
                [
                    "- C1 | link: origin | evidence: E1 | status: confirmed | finding: requirements included the constraint",
                    "- C2 | link: immediate-defect | evidence: E2,E3 | status: confirmed | finding: reasoning used an invalid source assumption",
                    "- C3 | link: missed-detection | evidence: E3 | status: confirmed | finding: tests omitted the counterexample path",
                ]
            ),
            classification="local-repeatable reasoning and test gap.",
            system_fix="Applied a counterexample test fixture and constraint checklist guardrail.",
            testing_audit="Manual review ran but missed the counterexample; adjacent boundary constraints and failure paths were absent and added.",
            gap_closure="Fixed the recommendation using the documented constraint.",
            retest="Reran the original input and executable counterexample test; both passed.",
            comprehensive="After the reasoning fix, ran the broader boundary and constraint test matrix.",
        ),
    )
    run_verify(reasoning)

    tool = tmp / "tool.md"
    write(
        tool,
        standard_report(
            incident_class="tool-use",
            symptom="The agent made an incorrect tool call and used the wrong tool for the requested operation.",
            reproduction="Reproduced through the original tool invocation with a disposable target.",
            evidence="\n".join(
                [
                    "- E1 | kind: user-report | source: requested operation | observation: read-only inspection was requested | status: confirmed",
                    "- E2 | kind: tool-trace | source: redacted tool invocation | observation: arguments selected a mutating command; result exit 0 changed state | status: confirmed",
                    "- E3 | kind: test | source: disposable integration fixture | observation: pre-fix tool-selection test detected the state change | status: confirmed",
                ]
            ),
            chain="\n".join(
                [
                    "- C1 | link: origin | evidence: E1 | status: confirmed | finding: user intent required read-only tool use",
                    "- C2 | link: immediate-defect | evidence: E2 | status: confirmed | finding: tool implementation chose a mutating operation",
                    "- C3 | link: missed-detection | evidence: E3 | status: confirmed | finding: tests checked tool result but not external state",
                ]
            ),
            classification="generalizable tool-selection gap.",
            system_fix="Applied a tool-selection verifier and disposable-state regression test.",
            testing_audit="The command check ran but missed external-state effects; adjacent permission and failure-path tests were absent and added.",
            gap_closure="Fixed the workflow to use the required read-only tool.",
            retest="Reran the original tool path and state verifier; both passed.",
            comprehensive="After the tool fix, ran the broader tool-selection, permission, and external-state integration matrix.",
        ),
    )
    run_verify(tool)

    artifact = tmp / "artifact.md"
    write(
        artifact,
        standard_report(
            incident_class="artifact",
            symptom="The delivered file was a broken artifact with malformed PDF layout.",
            reproduction="Reproduced by rendering the original PDF artifact with the same renderer command.",
            evidence="\n".join(
                [
                    "- E1 | kind: user-report | source: delivered file | observation: final page was clipped | status: confirmed",
                    "- E2 | kind: artifact | source: output.pdf sha256 abc123 | observation: original generated artifact hash and input were preserved | status: confirmed",
                    "- E3 | kind: screenshot | source: rendered page PNG | observation: bottom content was visibly clipped | status: confirmed",
                ]
            ),
            chain="\n".join(
                [
                    "- C1 | link: origin | evidence: E1 | status: confirmed | finding: requirements called for a readable PDF",
                    "- C2 | link: immediate-defect | evidence: E2,E3 | status: confirmed | finding: artifact implementation overflowed the final page",
                    "- C3 | link: missed-detection | evidence: E3 | status: confirmed | finding: verifier tests parsed the PDF but did not render every page",
                ]
            ),
            classification="local-repeatable artifact verification gap.",
            system_fix="Applied a render-all-pages verifier fixture before regenerating the artifact.",
            testing_audit="Parser tests ran but missed visual clipping; adjacent overflow and blank-page render checks were absent and added.",
            gap_closure="Fixed and regenerated the PDF artifact layout.",
            retest="Reran the original render command and screenshot verifier; both passed.",
            comprehensive="After the artifact fix, ran the broader parser, render, visual, and page-boundary matrix.",
        ),
    )
    run_verify(artifact)


def test_modes_and_policy_scope(tmp: Path) -> None:
    diagnose = tmp / "diagnose.md"
    write(
        diagnose,
        standard_report(
            mode="diagnose-only",
            system_fix="Proposed a targeted test guardrail; not applied and awaiting authorization.",
            gap_closure="No code changes were authorized in diagnose-only mode; implementation closure awaits authorization.",
            retest="Reran the original read-only reproduction command; no mutation was performed.",
            comprehensive="Broader integration and failure-path tests were not run because implementation awaits authorization.",
        ),
    )
    run_verify(diagnose)

    invalid_diagnose = tmp / "invalid-diagnose.md"
    write(invalid_diagnose, standard_report(mode="diagnose-only"))
    run_verify(invalid_diagnose, expect=1, issue="diagnose-only")

    invalid_class = tmp / "invalid-class.md"
    write(invalid_class, standard_report(incident_class="service and implementation"))
    run_verify(invalid_class, expect=1, issue="incident class")

    portable_policy = tmp / "portable-policy.md"
    write(
        portable_policy,
        standard_report(
            classification="generalizable cross-runtime app-wide agent behavior gap.",
            system_fix="Applied a generalized reusable global policy rule in CODEX_HOME/AGENTS.md and CLAUDE_CONFIG_DIR/CLAUDE.md, plus a verifier fixture.",
        ),
    )
    run_verify(portable_policy)

    private_policy = tmp / "private-policy.md"
    write(
        private_policy,
        standard_report(
            classification="generalizable app-wide agent behavior gap.",
            system_fix="Applied a generalized reusable global policy rule in /Users/example/.codex/AGENTS.md.",
        ),
    )
    run_verify(private_policy, expect=1, issue="runtime-portable")


def test_structured_evidence_recall(tmp: Path) -> None:
    unstructured = tmp / "unstructured.md"
    write(unstructured, standard_report(evidence="User report, source, and test proved the defect."))
    run_verify(unstructured, expect=1, issue="structure")

    unknown = tmp / "unknown-reference.md"
    write(unknown, standard_report(chain=standard_report().split("## Causal Chain\n", 1)[1].split("\n\n## Root Cause", 1)[0].replace("evidence: E2", "evidence: E99")))
    run_verify(unknown, expect=1, issue="unknown evidence")

    inferred_confirmation = tmp / "inferred-confirmation.md"
    write(
        inferred_confirmation,
        standard_report(
            evidence=standard_report().split("## Evidence Used\n", 1)[1].split("\n\n## Causal Chain", 1)[0].replace(
                "E2 | kind: file | source: SettingsStore.swift | observation: implementation omitted the assignment | status: confirmed",
                "E2 | kind: file | source: SettingsStore.swift | observation: implementation omitted the assignment | status: source-inferred",
            )
        ),
    )
    run_verify(inferred_confirmation, expect=1, issue="confirmed causal")

    missing_link = tmp / "missing-link.md"
    chain = standard_report().split("## Causal Chain\n", 1)[1].split("\n\n## Root Cause", 1)[0]
    chain = "\n".join(line for line in chain.splitlines() if "immediate-defect" not in line)
    write(missing_link, standard_report(chain=chain))
    run_verify(missing_link, expect=1, issue="missing required links")


def test_incident_specific_recall_and_false_positive_guards(tmp: Path) -> None:
    shallow_service = tmp / "shallow-service.md"
    write(
        shallow_service,
        standard_report(
            incident_class="service",
            symptom="The local service crashed and coordinator status showed unhealthy pid_alive=false.",
            chain="\n".join(
                [
                    "- C1 | link: origin | evidence: E1 | status: confirmed | finding: requirements expected a working service",
                    "- C2 | link: immediate-defect | evidence: E2 | status: confirmed | finding: implementation process stopped",
                    "- C3 | link: missed-detection | evidence: E3 | status: confirmed | finding: tests missed the failure",
                ]
            ),
        ),
    )
    run_verify(shallow_service, expect=1, issue="crash/log evidence")

    shallow_fact = tmp / "shallow-fact.md"
    write(shallow_fact, standard_report(incident_class="factual", symptom="The answer contained a factual error and incorrect fact."))
    run_verify(shallow_fact, expect=1, issue="source-backed")

    shallow_tool = tmp / "shallow-tool.md"
    write(shallow_tool, standard_report(incident_class="tool-use", symptom="The agent made an incorrect tool call and wrong tool selection."))
    run_verify(shallow_tool, expect=1, issue="tool trace")

    shallow_artifact = tmp / "shallow-artifact.md"
    write(shallow_artifact, standard_report(incident_class="artifact", symptom="The output was a broken artifact."))
    run_verify(shallow_artifact, expect=1, issue="artifact plus")

    explicit_exclusions = tmp / "explicit-exclusions.md"
    write(
        explicit_exclusions,
        standard_report(
            boundaries="Service health was checked and a crash was ruled out. This was not a factual error, not a tool error, and not a broken artifact.",
        ),
    )
    run_verify(explicit_exclusions)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="trace-fix-root-causes-self-test-"))
    try:
        skill_text = SKILL.read_text(encoding="utf-8")
        for needle in (
            "diagnose-only",
            "authorized-fix",
            "Incident Class",
            "factual mistakes",
            "reasoning mistakes",
            "incorrect tool use",
            "pid_alive=false",
            "CODEX_HOME/AGENTS.md",
            "CLAUDE_CONFIG_DIR/CLAUDE.md",
            "`$HOME`",
            "structured evidence",
            "false-positive guards",
        ):
            check(needle.lower() in skill_text.lower(), f"SKILL.md should contain {needle!r}")
        check("/Users/holyglory" not in skill_text, "SKILL.md must not hardcode a private user path")
        test_advertised_incident_classes(tmp)
        test_modes_and_policy_scope(tmp)
        test_structured_evidence_recall(tmp)
        test_incident_specific_recall_and_false_positive_guards(tmp)
        print("self-test ok")
        return 0
    finally:
        rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
