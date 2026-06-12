#!/usr/bin/env python3
"""Verify trace-fix-root-causes report shape and minimum evidence discipline."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REQUIRED_HEADINGS = [
    "fixed symptom",
    "reproduction",
    "user intent and scope check",
    "evidence used",
    "causal chain",
    "root cause classification",
    "system fix first",
    "testing procedure audit",
    "implementation gap closure",
    "retest results",
    "comprehensive retest results",
    "boundaries and non-generalizable notes",
]
EVIDENCE_RE = re.compile(
    r"\b(user report|screenshot|audit output|audit report|test|verifier|log|diff|commit|file|source|trace|reproduction|before/after)\b",
    re.IGNORECASE,
)
CAUSE_AREA_RE = re.compile(
    r"\b(requirements?|user intent|journey docs?|docs?|mockups?|audit|skill|verifier|implementation|tests?|review|policy|handoff|agents\.md|context|tool choices?)\b",
    re.IGNORECASE,
)
CLASSIFICATION_RE = re.compile(r"\b(generalizable|local-repeatable|one-off|unconfirmed)\b", re.IGNORECASE)
VALIDATION_RE = re.compile(r"\b(test|validate|verifier|audit|screenshot|reproduce|command|fixture|self-test)\b", re.IGNORECASE)
REPRODUCTION_RE = re.compile(
    r"\b(reproduce|reproduced|replicate|replicated|same surface|original surface|route|screen|command|test|audit|artifact|not possible|not reasonable|unable|blocked)\b",
    re.IGNORECASE,
)
INTENT_RE = re.compile(
    r"\b(user intent|request|requirement|changed mind|scope change|clarification|accepted plan|misread|misinterpreted|perceived|assumption|not changed|no change)\b",
    re.IGNORECASE,
)
SYSTEM_GUARDRAIL_RE = re.compile(
    r"\b(agents\.md|docs?|documentation|acceptance criteria|skill|verifier|tests?|policy|instructions?|checklist|guardrail|self-test|fixture|context)\b",
    re.IGNORECASE,
)
GAP_CLOSURE_RE = re.compile(
    r"\b(fix|fixed|close|closed|patch|patched|implementation|product|code|not in scope|not applicable|scope change)\b",
    re.IGNORECASE,
)
RETEST_RE = re.compile(
    r"\b(retest|rerun|re-run|reproduce|reproduced|original path|same surface|guardrail|test|validate|verifier|audit|screenshot|fixture|self-test|passes|passed)\b",
    re.IGNORECASE,
)
TESTING_AUDIT_RE = re.compile(
    r"\b(testing procedure|test procedure|tests?|verifier|audit|coverage|missed failures?|other possible failures?|adjacent|edge cases?|failure paths?|integration|journeys?|acceptance criteria|fixtures?|smoke checks?)\b",
    re.IGNORECASE,
)
COMPREHENSIVE_RETEST_RE = re.compile(
    r"\b(comprehensive|broader|full|suite|matrix|end-to-end|e2e|integration|unit|visual|journeys?|artifact|data|failure-path|coverage|expected result|user gets|user expectation|acceptance)\b",
    re.IGNORECASE,
)
AFTER_GAP_RE = re.compile(
    r"\b(after|post-fix|post-gap|gap closed|after closure|after fix|after the detected gap)\b",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify a trace-fix-root-causes Markdown report.")
    parser.add_argument("report", help="Path to a Markdown report.")
    return parser.parse_args()


def section_bodies(text: str) -> dict[str, str]:
    bodies: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            current = match.group(1).strip().lower()
            bodies.setdefault(current, [])
            continue
        if current is not None:
            bodies[current].append(line)
    return {key: "\n".join(value).strip() for key, value in bodies.items()}


def verify(text: str) -> list[str]:
    issues: list[str] = []
    bodies = section_bodies(text)
    missing = [heading for heading in REQUIRED_HEADINGS if heading not in bodies]
    if missing:
        issues.append(f"missing headings: {', '.join(missing)}")
        return issues

    for heading in REQUIRED_HEADINGS:
        if not bodies[heading].strip():
            issues.append(f"empty section: {heading}")

    evidence = bodies["evidence used"]
    classification = bodies["root cause classification"]
    reproduction = bodies["reproduction"]
    intent_check = bodies["user intent and scope check"]
    causal_chain = bodies["causal chain"]
    system_fix = bodies["system fix first"]
    testing_audit = bodies["testing procedure audit"]
    gap_closure = bodies["implementation gap closure"]
    retest = bodies["retest results"]
    comprehensive_retest = bodies["comprehensive retest results"]

    has_evidence = bool(EVIDENCE_RE.search(evidence))
    is_unconfirmed = "unconfirmed" in classification.lower()
    is_scope_change = bool(re.search(r"\b(changed mind|scope change|changed requirement)\b", intent_check, re.IGNORECASE))
    if not has_evidence and not is_unconfirmed:
        issues.append("reports without concrete evidence must classify the causal chain as unconfirmed")
    if "no evidence" in evidence.lower() and not is_unconfirmed:
        issues.append("explicitly missing evidence requires unconfirmed classification")
    if not REPRODUCTION_RE.search(reproduction):
        issues.append("reproduction must name the original surface or explain why replication was not possible")
    if not INTENT_RE.search(intent_check):
        issues.append("user intent and scope check must address the request, requirement, scope change, or Codex perception")
    if len(set(match.group(0).lower() for match in CAUSE_AREA_RE.finditer(causal_chain))) < 2 and not is_unconfirmed:
        issues.append("causal chain must trace at least two source areas or be marked unconfirmed")
    if not CLASSIFICATION_RE.search(classification):
        issues.append("root cause classification must include generalizable, local-repeatable, one-off, or unconfirmed")
    if re.search(r"\b(generalizable|local-repeatable)\b", classification, re.IGNORECASE) and re.search(
        r"\b(no system changes?|no workflow changes?|none)\b", system_fix, re.IGNORECASE
    ):
        issues.append("repeatable root causes require a system guardrail fix")
    if not is_scope_change and not SYSTEM_GUARDRAIL_RE.search(system_fix):
        issues.append("system fix first must name a guardrail such as AGENTS.md, docs, skill, verifier, test, policy, or checklist")
    if not is_scope_change and not TESTING_AUDIT_RE.search(testing_audit):
        issues.append("testing procedure audit must inspect tests, verifiers, coverage, adjacent risks, or other possible missed failures")
    if not GAP_CLOSURE_RE.search(gap_closure):
        issues.append("implementation gap closure must state the product/code fix, non-applicability, or scope-change boundary")
    if not RETEST_RE.search(retest) or not VALIDATION_RE.search(retest):
        issues.append("retest results must name the original path and a test, verifier, audit, screenshot, fixture, self-test, or command")
    if not is_scope_change and (
        not COMPREHENSIVE_RETEST_RE.search(comprehensive_retest)
        or not VALIDATION_RE.search(comprehensive_retest)
        or not AFTER_GAP_RE.search(comprehensive_retest)
    ):
        issues.append("comprehensive retest results must name broader post-gap tests that prove the expected user result")
    return issues


def main() -> int:
    args = parse_args()
    text = Path(args.report).read_text(encoding="utf-8")
    issues = verify(text)
    if issues:
        for issue in issues:
            print(f"ERROR: {issue}", file=sys.stderr)
        return 1
    print("root cause report ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
