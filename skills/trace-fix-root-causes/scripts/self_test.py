#!/usr/bin/env python3
"""Recall, evidence-discipline, concise-report, and false-positive tests."""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path
from shutil import rmtree


ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "scripts" / "verify_root_cause_report.py"
SKILL = ROOT / "SKILL.md"
FORMAL_REFERENCE = ROOT / "references" / "formal-report.md"


FORMAL_TEMPLATE = """## Outcome
Status: {status}

## Cause
Class: {incident_class}
Confidence: {confidence}
Request: {request}
Immediate cause: {immediate_cause}
Why missed: {why_missed}
Evidence: {evidence}

## Changes
Product: {product}
Prevention: {prevention}

## Verification
Original path: {original_path}
Checks: {checks}
Residual risk: {residual_risk}
"""


OLD_FOURTEEN_SECTION_REPORT = """## Fixed Symptom
A mobile hamburger did not open.

## Reproduction
Reproduced in the browser.

## User Intent And Scope Check
The request did not change.

## Authorization And Action Mode
diagnose-only

## Incident Class
ui

## Evidence Used
- E1 | kind: test | source: browser | observation: menu stayed closed | status: confirmed

## Causal Chain
- C1 | link: origin | evidence: E1 | status: confirmed | finding: request required a working menu

## Root Cause Classification
local-repeatable

## System Fix First
Proposed a test.

## Testing Procedure Audit
The old check missed the browser route.

## Implementation Gap Closure
Awaiting authorization.

## Retest Results
Not run.

## Comprehensive Retest Results
Not run.

## Boundaries And Non-Generalizable Notes
None.
"""


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def run_verify(
    path: Path,
    *,
    expect: int = 0,
    issue: str | None = None,
) -> subprocess.CompletedProcess[str]:
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
    if issue is not None:
        check(issue.lower() in result.stderr.lower(), f"expected issue {issue!r} in:\n{result.stderr}")
    return result


def standard_report(**overrides: str) -> str:
    values = {
        "status": "fixed",
        "incident_class": "implementation",
        "confidence": "confirmed",
        "request": "The saved preference must remain present after reload.",
        "immediate_cause": "The settings implementation omitted one persisted assignment.",
        "why_missed": "The existing test asserted the action result but not reloaded state.",
        "evidence": "The original request, SettingsStore source, and failing persistence regression established the omission.",
        "product": "Fixed the settings store by persisting the omitted field.",
        "prevention": "Added a reload regression test covering persisted state.",
        "original_path": "After the fix, reran the original settings-screen save and reload journey; it passed.",
        "checks": "Post-fix unit, integration, reload, and failure-path checks passed.",
        "residual_risk": "None known within the changed settings path.",
    }
    values.update(overrides)
    return FORMAL_TEMPLATE.format(**values)


def test_skill_contract() -> None:
    skill_text = SKILL.read_text(encoding="utf-8")
    normalized = " ".join(skill_text.split())
    check(
        bool(
            re.search(r"bug report.{0,320}authoriz", normalized, re.IGNORECASE)
            or re.search(r"authoriz.{0,320}bug report", normalized, re.IGNORECASE)
        ),
        "SKILL.md must say that an ordinary clear bug report authorizes fixing",
    )
    check(
        "safe" in normalized.lower() and bool(re.search(r"in[- ]scope", normalized, re.IGNORECASE)),
        "SKILL.md must limit implicit bug-fix authorization to safe in-scope work",
    )
    check(
        bool(re.search(r"\bconcis(?:e|ely)\b", normalized, re.IGNORECASE))
        and "default" in normalized.lower(),
        "SKILL.md must make concise output the default",
    )
    check(
        bool(
            re.search(
                r"formal (?:incident|report|output).{0,240}(?:only when|when (?:the user )?explicit|conditional)",
                normalized,
                re.IGNORECASE,
            )
            or re.search(
                r"(?:only when|when (?:the user )?explicit|conditional).{0,240}formal (?:incident|report|output)",
                normalized,
                re.IGNORECASE,
            )
        ),
        "SKILL.md must make formal reports conditional rather than routine",
    )
    check(
        "a bug report by itself is not authorization" not in normalized.lower(),
        "SKILL.md must not retain the obsolete second-authorization rule",
    )


def test_formal_reference_contract() -> None:
    reference = FORMAL_REFERENCE.read_text(encoding="utf-8")
    headings = [match.group(1).strip().lower() for match in re.finditer(r"^##\s+(.+?)\s*$", reference, re.MULTILINE)]
    check(
        headings == ["outcome", "cause", "changes", "verification"],
        "formal-report.md must document the verifier's exact four-section order",
    )
    for label in (
        "Status:",
        "Class:",
        "Confidence:",
        "Request:",
        "Immediate cause:",
        "Why missed:",
        "Evidence:",
        "Product:",
        "Prevention:",
        "Original path:",
        "Checks:",
        "Residual risk:",
    ):
        check(label in reference, f"formal-report.md should document {label}")
    check("## Fixed Symptom" not in reference, "formal-report.md must not restore the legacy report schema")


def test_concise_schema_and_statuses(tmp: Path) -> None:
    fixed = tmp / "fixed.md"
    write(fixed, standard_report())
    run_verify(fixed)

    diagnosed = tmp / "diagnosed.md"
    write(
        diagnosed,
        standard_report(
            status="diagnosed",
            product="No product changes were made; investigation remained read-only.",
            prevention="Proposed a persistence regression test, but it was not applied.",
            original_path="Reproduced the original settings-screen failure using read-only browser inspection.",
            checks="Read-only source and console checks completed.",
            residual_risk="The user-visible defect remains until a fix is authorized.",
        ),
    )
    run_verify(diagnosed)

    blocked = tmp / "blocked.md"
    write(
        blocked,
        standard_report(
            status="blocked",
            confidence="unconfirmed",
            immediate_cause="Unknown because the only failing target is unavailable.",
            why_missed="Unavailable evidence prevents a confirmed detection analysis.",
            evidence="The user report is preserved; runtime logs are unavailable.",
            product="Pending access to the failing target.",
            prevention="Pending evidence; no speculative guardrail was applied.",
            original_path="The original route could not be opened because access is unavailable.",
            checks="Source inspection completed; runtime verification is blocked.",
            residual_risk="The symptom and cause remain unverified.",
        ),
    )
    run_verify(blocked)


def test_all_incident_classes(tmp: Path) -> None:
    for incident_class in ("implementation", "ui", "audit", "verification", "other"):
        report = tmp / f"{incident_class}.md"
        write(report, standard_report(incident_class=incident_class))
        run_verify(report)

    service = tmp / "service.md"
    write(
        service,
        standard_report(
            incident_class="service",
            request="The coordinator-managed local service must remain available at the routed URL.",
            immediate_cause="A toolchain cache failure terminated the coordinator wrapper process.",
            why_missed="The coordinator start test checked launch success but not sustained health.",
            evidence="The coordinator log_path and events.jsonl recorded stderr, process exit code 1, pid_alive=false, and unhealthy inventory health.",
            product="Fixed the wrapper cache recovery and restarted the managed service.",
            prevention="Added a coordinator regression check for process exit and sustained health.",
            original_path="After the fix, reran the same failing URL in the browser and coordinator status; both passed.",
            checks="Post-fix curl and browser checks plus a sustained stability monitor passed.",
        ),
    )
    run_verify(service)

    factual = tmp / "factual.md"
    write(
        factual,
        standard_report(
            incident_class="factual",
            request="The answer must state the current value supported by a primary source.",
            immediate_cause="The answer used a value contradicted by the cited source.",
            why_missed="Citation review checked presence but not whether the claim was supported.",
            evidence="A primary source dated 2026-07-09 showed that, as of the answer timestamp, the delivered claim was wrong.",
            product="Corrected the answer to match the primary source.",
            prevention="Added a claim-support and freshness verification check.",
            original_path="After the fix, reran the original citation lookup and verified the corrected answer.",
            checks="Post-fix primary-source, claim-support, and freshness checks passed.",
        ),
    )
    run_verify(factual)

    reasoning = tmp / "reasoning.md"
    write(
        reasoning,
        standard_report(
            incident_class="reasoning",
            request="The recommendation must honor the documented boundary constraint.",
            immediate_cause="The recommendation relied on an assumption that violated the constraint.",
            why_missed="The review omitted the executable counterexample path.",
            evidence="The official source document dated 2026-07-10 and an executable counterexample proved the assumption invalid at delivery.",
            product="Corrected the recommendation using the documented constraint.",
            prevention="Added the counterexample to the reasoning verification checklist.",
            original_path="After the fix, reran the original input and verified the boundary result.",
            checks="Post-fix boundary and counterexample checks passed.",
        ),
    )
    run_verify(reasoning)

    tool = tmp / "tool-use.md"
    write(
        tool,
        standard_report(
            incident_class="tool-use",
            request="The requested inspection must remain read-only.",
            immediate_cause="The workflow selected a mutating tool invocation.",
            why_missed="The check asserted command success but did not inspect external state.",
            evidence="The redacted tool invocation arguments and result exit 0 showed that the command changed external state.",
            product="Fixed the workflow to use the required read-only tool.",
            prevention="Added a disposable-state tool-selection regression check.",
            original_path="After the fix, reran the original tool path and verified state remained unchanged.",
            checks="Post-fix tool-selection and external-state checks passed.",
        ),
    )
    run_verify(tool)

    artifact = tmp / "artifact.md"
    write(
        artifact,
        standard_report(
            incident_class="artifact",
            request="The generated PDF must render every page without clipping.",
            immediate_cause="The artifact layout overflowed the final page.",
            why_missed="The old check parsed the PDF but never rendered the final page.",
            evidence="The output.pdf artifact sha256 abc123 and renderer screenshot PNG showed clipped bottom content.",
            product="Fixed the layout and regenerated the PDF artifact.",
            prevention="Added render-all-pages clipping coverage.",
            original_path="After the fix, reran the original PDF render and verified every page.",
            checks="Post-fix parser, renderer, and screenshot checks passed.",
        ),
    )
    run_verify(artifact)


def test_schema_recall(tmp: Path) -> None:
    old = tmp / "old-fourteen-section.md"
    write(old, OLD_FOURTEEN_SECTION_REPORT)
    run_verify(old, expect=1, issue="headings must be exactly")

    duplicate_class = tmp / "duplicate-class.md"
    write(duplicate_class, standard_report(incident_class="implementation\nClass: ui"))
    run_verify(duplicate_class, expect=1, issue="exactly one class")

    invalid_class = tmp / "invalid-class.md"
    write(invalid_class, standard_report(incident_class="service and implementation"))
    run_verify(invalid_class, expect=1, issue="exactly one allowed class")

    invalid_status = tmp / "invalid-status.md"
    write(invalid_status, standard_report(status="fixed and verified"))
    run_verify(invalid_status, expect=1, issue="status")

    missing_evidence = tmp / "missing-evidence.md"
    write(missing_evidence, standard_report(evidence=""))
    run_verify(missing_evidence, expect=1, issue="must not be empty")

    public_mode = tmp / "public-action-mode.md"
    write(public_mode, standard_report(request="Fix the regression.\nAction mode: authorized-fix"))
    run_verify(public_mode, expect=1, issue="must not expose")

    public_authorization = tmp / "public-authorization.md"
    write(public_authorization, standard_report(request="Fix the regression.\nAuthorization: implicit"))
    run_verify(public_authorization, expect=1, issue="must not expose")

    pending_product = tmp / "pending-product.md"
    write(pending_product, standard_report(product="A product correction is still pending."))
    run_verify(pending_product, expect=1, issue="completed product change")

    pending_prevention = tmp / "pending-prevention.md"
    write(pending_prevention, standard_report(prevention="A regression test is planned later."))
    run_verify(pending_prevention, expect=1, issue="completed prevention")

    negated_product = tmp / "negated-product.md"
    write(negated_product, standard_report(product="The product defect was not fixed."))
    run_verify(negated_product, expect=1, issue="completed product change")

    negated_prevention = tmp / "negated-prevention.md"
    write(negated_prevention, standard_report(prevention="A regression test was proposed but not applied."))
    run_verify(negated_prevention, expect=1, issue="completed prevention")

    before_only = tmp / "before-only.md"
    write(
        before_only,
        standard_report(
            original_path="Reproduced the original settings-screen failure before editing.",
            checks="The pre-fix regression check passed by detecting the failure.",
        ),
    )
    run_verify(before_only, expect=1, issue="post-fix")

    negated_verification = tmp / "negated-verification.md"
    write(
        negated_verification,
        standard_report(
            original_path="After the fix, the original settings journey could not be verified.",
            checks="Post-fix checks passed in a different internal path.",
        ),
    )
    run_verify(negated_verification, expect=1, issue="original path")

    invalid_diagnosed = tmp / "invalid-diagnosed.md"
    write(invalid_diagnosed, standard_report(status="diagnosed"))
    run_verify(invalid_diagnosed, expect=1, issue="read-only/no-change")


def test_incident_specific_recall(tmp: Path) -> None:
    shallow_service = tmp / "shallow-service.md"
    write(
        shallow_service,
        standard_report(
            incident_class="service",
            immediate_cause="The process stopped.",
            why_missed="A test missed the failure.",
            evidence="The service was unavailable.",
        ),
    )
    run_verify(shallow_service, expect=1, issue="crash/log evidence")

    no_sustained_service = tmp / "no-sustained-service.md"
    write(
        no_sustained_service,
        standard_report(
            incident_class="service",
            immediate_cause="A toolchain cache failure terminated the coordinator wrapper.",
            why_missed="The coordinator test omitted post-start health.",
            evidence="The coordinator log_path showed process exit code 1 and pid_alive=false health.",
        ),
    )
    run_verify(no_sustained_service, expect=1, issue="sustained verification")

    for incident_class in ("factual", "reasoning"):
        shallow_source = tmp / f"shallow-{incident_class}.md"
        write(
            shallow_source,
            standard_report(
                incident_class=incident_class,
                evidence="A generic review suggested the answer might be wrong.",
            ),
        )
        run_verify(shallow_source, expect=1, issue="source-backed")

    shallow_tool = tmp / "shallow-tool.md"
    write(shallow_tool, standard_report(incident_class="tool-use", evidence="The operation was wrong."))
    run_verify(shallow_tool, expect=1, issue="tool trace")

    shallow_artifact = tmp / "shallow-artifact.md"
    write(shallow_artifact, standard_report(incident_class="artifact", evidence="The output looked wrong."))
    run_verify(shallow_artifact, expect=1, issue="artifact plus")


def test_false_positive_guards(tmp: Path) -> None:
    explicit_exclusions = tmp / "explicit-exclusions.md"
    write(
        explicit_exclusions,
        standard_report(
            incident_class="implementation",
            evidence="Browser and source checks confirmed an implementation omission. Service crash, factual error, tool misuse, and broken artifact were ruled out.",
            residual_risk="This was not a service, factual, tool-use, or artifact incident.",
        ),
    )
    run_verify(explicit_exclusions)

    for incident_class in ("service", "factual", "reasoning", "tool-use", "artifact"):
        unconfirmed = tmp / f"unconfirmed-{incident_class}.md"
        write(
            unconfirmed,
            standard_report(
                incident_class=incident_class,
                confidence="unconfirmed",
                evidence="Only the user report is available; detailed evidence could not be preserved.",
            ),
        )
        run_verify(unconfirmed)

    no_code_needed = tmp / "no-product-code-needed.md"
    write(
        no_code_needed,
        standard_report(
            product="No product change was needed; the routed local service was restored.",
            prevention="Not applicable for this one-off external-state recovery.",
            original_path="After the fix, reran the original routed browser journey; it passed.",
            checks="Post-fix browser and health checks passed.",
        ),
    )
    run_verify(no_code_needed)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="trace-fix-root-causes-self-test-"))
    try:
        test_skill_contract()
        test_formal_reference_contract()
        test_concise_schema_and_statuses(tmp)
        test_all_incident_classes(tmp)
        test_schema_recall(tmp)
        test_incident_specific_recall(tmp)
        test_false_positive_guards(tmp)
        print("self-test ok")
        return 0
    finally:
        rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
