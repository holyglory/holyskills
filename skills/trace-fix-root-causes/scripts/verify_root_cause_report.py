#!/usr/bin/env python3
"""Verify trace-fix-root-causes report shape, evidence, authorization, and closure."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable


REQUIRED_HEADINGS = [
    "fixed symptom",
    "reproduction",
    "user intent and scope check",
    "authorization and action mode",
    "incident class",
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
EVIDENCE_KINDS = {
    "user-report",
    "screenshot",
    "log",
    "test",
    "verifier",
    "diff",
    "commit",
    "file",
    "source",
    "source-citation",
    "tool-trace",
    "command",
    "artifact",
    "audit",
}
EVIDENCE_STATUSES = {"confirmed", "source-inferred", "unconfirmed"}
CAUSAL_LINKS = {"origin", "immediate-defect", "missed-detection", "scope-change", "external-change"}
REQUIRED_CAUSAL_LINKS = {"origin", "immediate-defect", "missed-detection"}
INCIDENT_CLASSES = {"implementation", "ui", "factual", "reasoning", "tool-use", "artifact", "service", "audit", "verification", "other"}
RECORD_RE = re.compile(r"^\s*-\s+([A-Za-z][A-Za-z0-9_-]*)\s*\|\s*(.*?)\s*$")
CLASSIFICATION_RE = re.compile(r"\b(generalizable|local-repeatable|one-off|unconfirmed)\b", re.IGNORECASE)
REPRODUCTION_RE = re.compile(
    r"\b(reproduce|reproduced|replicate|replicated|same surface|original surface|route|screen|command|test|audit|artifact|prompt|citation|tool|not possible|not reasonable|unable|blocked)\b",
    re.IGNORECASE,
)
INTENT_RE = re.compile(
    r"\b(user intent|request|requirement|changed mind|scope change|external change|clarification|accepted plan|misread|misinterpreted|assumption|not changed|no change)\b",
    re.IGNORECASE,
)
CAUSE_AREA_RE = re.compile(
    r"\b(requirements?|user intent|journey docs?|docs?|mockups?|audit|skill|verifier|implementation|tests?|review|policy|handoff|agents\.md|claude\.md|context|tool|citation|source|toolchain|cache|wrapper)\b",
    re.IGNORECASE,
)
SYSTEM_GUARDRAIL_RE = re.compile(
    r"\b(agents\.md|claude\.md|docs?|documentation|acceptance criteria|skill|verifier|tests?|policy|instructions?|checklist|guardrail|self-test|fixture|context)\b",
    re.IGNORECASE,
)
TESTING_AUDIT_RE = re.compile(
    r"\b(ran|run|test|verifier|audit|coverage|missed|absent|adjacent|edge case|failure path|integration|journey|fixture|smoke|assert)\b",
    re.IGNORECASE,
)
RETEST_RE = re.compile(
    r"\b(reran|re-run|retest|reproduce|original path|same surface|test|validate|verifier|audit|screenshot|fixture|command|passed|not run)\b",
    re.IGNORECASE,
)
COMPREHENSIVE_RE = re.compile(
    r"\b(comprehensive|broader|full|suite|matrix|end-to-end|e2e|integration|unit|visual|journey|artifact|failure-path|expected result|acceptance|not run)\b",
    re.IGNORECASE,
)
POLICY_TARGET_RE = re.compile(
    r"\b(agents\.md|claude\.md|global polic(?:y|ies)|repo-wide polic(?:y|ies)|project polic(?:y|ies)|policy file|policy update)\b",
    re.IGNORECASE,
)
POLICY_SCOPE_RE = re.compile(
    r"\b(scope|scoped|global|repo-wide|project|local|skill|verifier|tests?|docs?|persistent context)\b",
    re.IGNORECASE,
)
GENERALIZED_POLICY_RE = re.compile(
    r"\b(generalized|generalised|reusable|abstract|stable rule|durable rule|policy rule|not incident-specific)\b",
    re.IGNORECASE,
)
INCIDENT_POLICY_RE = re.compile(
    r"\b(incident explanation|specific incident|this incident|this error|this bug|exact bug|timeline|one-off root cause|root-cause narrative)\b",
    re.IGNORECASE,
)
POLICY_ALTERNATIVE_RE = re.compile(
    r"\b(no|not|do not|don't|without)\b[\s\S]{0,80}\b(agents\.md|claude\.md|policy|global policy|repo-wide policy)\b|"
    r"\b(DecisionHistory\.md|root-cause report|targeted test|fixture|code review note)\b",
    re.IGNORECASE,
)
GLOBAL_SCOPE_RE = re.compile(
    r"\b(global polic(?:y|ies)|global guardrail|app-wide|cross-repo|all repos|all projects|Codex tasks|Claude Code tasks|cross-runtime|app-wide agent behavior)\b",
    re.IGNORECASE,
)
PORTABLE_POLICY_RE = re.compile(
    r"\b(CODEX_HOME/AGENTS\.md|CLAUDE_CONFIG_DIR/CLAUDE\.md|runtime-provided global policy|active runtime global policy)\b",
    re.IGNORECASE,
)
PRIVATE_POLICY_RE = re.compile(r"/Users/[^/]+/\.(?:codex/AGENTS|claude/CLAUDE)\.md", re.IGNORECASE)
SERVICE_LOG_RE = re.compile(r"\b(log_path|coordinator log|app log|stderr|stdout|events\.jsonl|process exit|exit event|latest\.log)\b", re.IGNORECASE)
SERVICE_PID_RE = re.compile(r"\b(pid|pid_alive|process exit|exit code|coordinator status|inventory|health)\b", re.IGNORECASE)
SERVICE_CAUSE_RE = re.compile(r"\b(toolchain|cache|build output|wrapper|coordinator|dependency|policy|skill trigger|guardrail)\b", re.IGNORECASE)
SERVICE_SUSTAINED_RE = re.compile(r"\b(sustained|same url|failing url|coordinator status|browser|curl|ttfb|monitor|stability)\b", re.IGNORECASE)


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
        elif current is not None:
            bodies[current].append(line)
    return {key: "\n".join(value).strip() for key, value in bodies.items()}


def parse_records(
    body: str,
    *,
    section: str,
    id_prefix: str,
    required_fields: set[str],
    issues: list[str],
) -> dict[str, dict[str, str]]:
    records: dict[str, dict[str, str]] = {}
    nonempty_lines = [line for line in body.splitlines() if line.strip()]
    if not nonempty_lines:
        issues.append(f"{section} must contain structured records")
        return records
    for line_number, line in enumerate(nonempty_lines, start=1):
        match = RECORD_RE.match(line)
        if not match:
            issues.append(f"{section} line {line_number} must use '- {id_prefix}1 | field: value' structure")
            continue
        record_id, payload = match.groups()
        if not record_id.upper().startswith(id_prefix):
            issues.append(f"{section} record {record_id} must use an {id_prefix} identifier")
        if record_id in records:
            issues.append(f"{section} contains duplicate id {record_id}")
            continue
        fields: dict[str, str] = {}
        for part in payload.split("|"):
            if ":" not in part:
                issues.append(f"{section} record {record_id} has a malformed field: {part.strip()}")
                continue
            key, value = part.split(":", 1)
            key = key.strip().lower()
            value = value.strip()
            if key in fields:
                issues.append(f"{section} record {record_id} repeats field {key}")
            fields[key] = value
        missing = sorted(field for field in required_fields if not fields.get(field))
        if missing:
            issues.append(f"{section} record {record_id} is missing fields: {', '.join(missing)}")
        records[record_id] = fields
    return records


def evidence_text(records: dict[str, dict[str, str]]) -> str:
    return "\n".join(f"{record_id} " + " ".join(fields.values()) for record_id, fields in records.items())


def has_kind(records: dict[str, dict[str, str]], kinds: Iterable[str]) -> bool:
    accepted = set(kinds)
    return any(fields.get("kind", "").lower() in accepted for fields in records.values())


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

    classification = bodies["root cause classification"]
    reproduction = bodies["reproduction"]
    intent = bodies["user intent and scope check"]
    mode_body = bodies["authorization and action mode"]
    incident_class = bodies["incident class"].strip().lower()
    system_fix = bodies["system fix first"]
    testing_audit = bodies["testing procedure audit"]
    gap_closure = bodies["implementation gap closure"]
    retest = bodies["retest results"]
    comprehensive = bodies["comprehensive retest results"]

    modes = {mode for mode in ("diagnose-only", "authorized-fix") if re.search(rf"\b{re.escape(mode)}\b", mode_body, re.IGNORECASE)}
    if len(modes) != 1:
        issues.append("authorization and action mode must include exactly one of diagnose-only or authorized-fix")
    mode = next(iter(modes), None)
    if incident_class not in INCIDENT_CLASSES:
        issues.append("incident class must be exactly one allowed class: " + ", ".join(sorted(INCIDENT_CLASSES)))
        incident_class = ""

    evidence = parse_records(
        bodies["evidence used"],
        section="evidence used",
        id_prefix="E",
        required_fields={"kind", "source", "observation", "status"},
        issues=issues,
    )
    for record_id, fields in evidence.items():
        if fields.get("kind", "").lower() not in EVIDENCE_KINDS:
            issues.append(f"evidence record {record_id} has unsupported kind {fields.get('kind', '')!r}")
        if fields.get("status", "").lower() not in EVIDENCE_STATUSES:
            issues.append(f"evidence record {record_id} has unsupported status {fields.get('status', '')!r}")

    causal = parse_records(
        bodies["causal chain"],
        section="causal chain",
        id_prefix="C",
        required_fields={"link", "evidence", "status", "finding"},
        issues=issues,
    )
    present_links: set[str] = set()
    for record_id, fields in causal.items():
        link = fields.get("link", "").lower()
        status = fields.get("status", "").lower()
        present_links.add(link)
        if link not in CAUSAL_LINKS:
            issues.append(f"causal record {record_id} has unsupported link {link!r}")
        if status not in EVIDENCE_STATUSES:
            issues.append(f"causal record {record_id} has unsupported status {status!r}")
        references = [item.strip() for item in fields.get("evidence", "").split(",") if item.strip()]
        if references == ["none"]:
            if status != "unconfirmed":
                issues.append(f"causal record {record_id} may use evidence none only when unconfirmed")
        else:
            unknown = [reference for reference in references if reference not in evidence]
            if unknown:
                issues.append(f"causal record {record_id} references unknown evidence: {', '.join(unknown)}")
            if status == "confirmed" and references and not any(
                evidence.get(reference, {}).get("status", "").lower() == "confirmed" for reference in references
            ):
                issues.append(f"confirmed causal record {record_id} must reference confirmed evidence")
    missing_links = sorted(REQUIRED_CAUSAL_LINKS - present_links)
    if missing_links:
        issues.append(f"causal chain is missing required links: {', '.join(missing_links)}")

    is_unconfirmed = bool(re.search(r"\bunconfirmed\b", classification, re.IGNORECASE))
    is_scope_change = bool(re.search(r"\b(scope change|changed requirement|changed mind)\b", intent, re.IGNORECASE))
    if not CLASSIFICATION_RE.search(classification):
        issues.append("root cause classification must include generalizable, local-repeatable, one-off, or unconfirmed")
    if not REPRODUCTION_RE.search(reproduction):
        issues.append("reproduction must name the original surface or explain why replication was not possible")
    if not INTENT_RE.search(intent):
        issues.append("user intent and scope check must address the request, requirement, scope, or external change")
    causal_findings = "\n".join(fields.get("finding", "") for fields in causal.values())
    if len(set(match.group(0).lower() for match in CAUSE_AREA_RE.finditer(causal_findings))) < 2 and not is_unconfirmed:
        issues.append("causal findings must trace at least two source areas or classify the cause unconfirmed")
    if not evidence and not is_unconfirmed:
        issues.append("reports without structured evidence must classify the cause unconfirmed")

    if re.search(r"\b(generalizable|local-repeatable)\b", classification, re.IGNORECASE) and re.search(
        r"\b(no system changes?|no workflow changes?|none)\b", system_fix, re.IGNORECASE
    ):
        issues.append("repeatable root causes require an applied or proposed system guardrail")
    if not is_scope_change and not SYSTEM_GUARDRAIL_RE.search(system_fix):
        issues.append("system fix first must name a guardrail such as docs, skill, verifier, test, policy, or checklist")
    if POLICY_TARGET_RE.search(system_fix):
        if not POLICY_SCOPE_RE.search(system_fix):
            issues.append("policy guardrail updates must state their scope")
        if INCIDENT_POLICY_RE.search(system_fix):
            issues.append("incident narratives belong in the report, DecisionHistory.md, or fixtures, not policy")
        if re.search(r"\b(one-off|unconfirmed)\b", classification, re.IGNORECASE) and not POLICY_ALTERNATIVE_RE.search(system_fix):
            issues.append("one-off or unconfirmed causes must use a targeted alternative instead of policy")
        if re.search(r"\b(generalizable|local-repeatable)\b", classification, re.IGNORECASE) and not GENERALIZED_POLICY_RE.search(system_fix):
            issues.append("policy guardrails for repeatable causes must be generalized reusable rules")
        if PRIVATE_POLICY_RE.search(system_fix):
            issues.append("policy targets must be runtime-portable, not username-specific absolute paths")
        if GLOBAL_SCOPE_RE.search(f"{classification}\n{causal_findings}\n{system_fix}") and not POLICY_ALTERNATIVE_RE.search(system_fix) and not PORTABLE_POLICY_RE.search(system_fix):
            issues.append("global policy work must name CODEX_HOME/AGENTS.md, CLAUDE_CONFIG_DIR/CLAUDE.md, or the runtime-provided global policy")

    if not TESTING_AUDIT_RE.search(testing_audit) or not re.search(r"\b(missed|absent|gap|not covered|failed to catch|adjacent)\b", testing_audit, re.IGNORECASE):
        issues.append("testing procedure audit must distinguish checks run from missed or adjacent coverage")
    if not RETEST_RE.search(retest):
        issues.append("retest results must name a completed original-path check or an explicitly unrun check")
    if not COMPREHENSIVE_RE.search(comprehensive):
        issues.append("comprehensive retest results must name a broader matrix or explicitly unrun required tests")

    if mode == "diagnose-only":
        if not re.search(r"\b(proposed|recommend|not applied|await(?:s|ing)? authorization)\b", system_fix, re.IGNORECASE):
            issues.append("diagnose-only system fixes must be marked proposed/not applied")
        if not re.search(r"\b(not authorized|no (?:code |product )?changes?|diagnose-only|await(?:s|ing)? authorization)\b", gap_closure, re.IGNORECASE):
            issues.append("diagnose-only implementation closure must state that mutation was not authorized")
        if not re.search(r"\b(not run|not executed|await(?:s|ing)? authorization)\b", comprehensive, re.IGNORECASE):
            issues.append("diagnose-only comprehensive tests must be marked not run")
    elif mode == "authorized-fix":
        if not is_scope_change and not re.search(r"\b(applied|updated|patched|added|fixed|implemented)\b", system_fix, re.IGNORECASE):
            issues.append("authorized-fix system fix first must state what guardrail was applied")
        if not re.search(r"\b(fixed|closed|patched|implemented|not applicable|scope change)\b", gap_closure, re.IGNORECASE):
            issues.append("authorized-fix implementation closure must state the completed product correction or boundary")
        if not re.search(r"\b(after|post-fix|post-gap|gap closed|after closure|after fix)\b", comprehensive, re.IGNORECASE):
            issues.append("authorized-fix comprehensive tests must run after implementation closure")

    structured_evidence = evidence_text(evidence)
    if incident_class == "service" and not is_unconfirmed:
        if not has_kind(evidence, {"log"}) or not SERVICE_LOG_RE.search(structured_evidence):
            issues.append("service incidents require structured crash/log evidence")
        if not SERVICE_PID_RE.search(f"{structured_evidence}\n{causal_findings}"):
            issues.append("service incidents require PID, health, inventory, or process-exit evidence")
        if not SERVICE_CAUSE_RE.search(causal_findings):
            issues.append("service causal chains must inspect toolchain, cache, wrapper, coordinator, dependency, policy, or skill-trigger paths")
        if mode == "authorized-fix" and not SERVICE_SUSTAINED_RE.search(f"{retest}\n{comprehensive}"):
            issues.append("fixed service incidents require sustained verification through the failing surface")
    if incident_class in {"factual", "reasoning"} and not is_unconfirmed:
        if not has_kind(evidence, {"source", "source-citation"}):
            issues.append("factual, citation, and reasoning incidents require source-backed structured evidence")
        if not re.search(r"\b(as of|timestamp|dated|date|at delivery|answer time)\b", structured_evidence, re.IGNORECASE):
            issues.append("factual incidents must record source or answer timing to distinguish later changes")
    if incident_class == "tool-use" and not is_unconfirmed:
        if not has_kind(evidence, {"tool-trace", "command", "log"}):
            issues.append("tool-use incidents require a structured tool trace, command, or log")
        if not re.search(r"\b(argument|argv|result|error|exit|state)\b", structured_evidence, re.IGNORECASE):
            issues.append("tool-use evidence must preserve redacted arguments and result/error state")
    if incident_class == "artifact" and not is_unconfirmed:
        if not has_kind(evidence, {"artifact"}) or not has_kind(evidence, {"test", "verifier", "screenshot"}):
            issues.append("artifact incidents require the artifact plus render/parser/screenshot verification evidence")
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
