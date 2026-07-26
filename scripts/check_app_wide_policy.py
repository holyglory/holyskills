#!/usr/bin/env python3
"""Validate the stable semantic contract of the universal agent policy."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "reference" / "codex-app-wide" / "AGENTS.md"

FORBIDDEN_NAMES = (
    "Codex",
    "Claude",
    "ImageGen",
    "Next.js",
    "Vercel",
    "Swift",
    "macOS",
    "Docker",
    "PostgreSQL",
    "systemd",
    "formal-web-ui-verification",
    "codex-dev-coordinator",
    "postgres-docker-backup",
)


def section(text: str, heading: str) -> str:
    match = re.search(
        rf"^## {re.escape(heading)}\s*$\n(?P<body>.*?)(?=^## |\Z)",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    return match.group("body") if match else ""


def require_terms(
    violations: list[str],
    body: str,
    label: str,
    terms: tuple[str, ...],
) -> None:
    folded = " ".join(body.casefold().split())
    missing = [term for term in terms if term.casefold() not in folded]
    if missing:
        violations.append(f"{label} missing required concepts: {', '.join(missing)}")


def find_policy_violations(text: str) -> list[str]:
    violations: list[str] = []

    if not text.startswith("# Universal Agent Instructions\n"):
        violations.append("policy must use the universal title")

    decision = section(text, "Use authoritative context and informed decisions")
    if not decision:
        violations.append("informed-decisions section is missing")
    else:
        require_terms(
            violations,
            decision,
            "informed-decisions contract",
            (
                "before asking",
                "realistic options",
                "plain language",
                "third-party",
                "exact name",
                "capabilities",
                "limitations",
                "authoritative sources",
                "specifications",
                "maturity",
                "maintenance",
                "licensing",
                "security",
                "privacy",
                "lock-in",
                "integration",
                "facts",
                "inferences",
                "unknowns",
                "costs",
                "risks",
                "recommendation",
                "industry-standard",
                "under-engineering",
                "over-provisioned",
                "present scale",
                "DecisionHistory.md",
                "dense",
                "concise",
                "major",
                "not a report",
                "timeline",
                "implementation log",
                "stable ID",
                "DecisionDetails/<decision-id>.md",
                "file per decision",
                "routine context",
                "options considered",
                "selected option",
                "better",
                "previously tried",
                "did not work",
                "project direction",
                "quality bar",
                "workflow expectations",
                "UI preferences",
                "taste",
                "Direction",
                "confirmed user intent",
                "inferred patterns",
                "decision IDs",
                "analogous work",
                "ambiguous choice",
                "rejected or failed",
                "new evidence",
                "what changed",
                "superseding",
                "context loss",
            ),
        )
        if not re.search(
            r"(?is)\b(?:keep|record|use|maintain)\b.{0,160}\bproject-root\b"
            r".{0,80}`DecisionHistory\.md`",
            decision,
        ):
            violations.append("DecisionHistory.md must be positively assigned as the project-root record")
        if re.search(r"(?is)\b(?:do not|never)\b.{0,100}`DecisionHistory\.md`", decision):
            violations.append("DecisionHistory.md appears only or ambiguously in a negative instruction")
        if not re.search(r"(?is)\bunder-engineering\b.{0,100}\bmore serious\b", decision):
            violations.append("foundation asymmetry must make under-engineering the more serious failure")
        if not re.search(r"(?is)\bover-provisioned\b.{0,80}\bacceptable\b", decision):
            violations.append("foundation asymmetry must make over-provisioned capacity acceptable")
        if not re.search(
            r"(?is)\beach entry.{0,100}\bonly\b.{0,80}\bDecision\b.{0,80}\bWhy\b",
            decision,
        ):
            violations.append("DecisionHistory.md entries must contain only Decision and Why")
        if not re.search(
            r"(?is)\bexactly one\b.{0,100}\bproject-root\b.{0,80}"
            r"`DecisionDetails/<decision-id>\.md`.{0,80}\bfile per decision\b",
            decision,
        ):
            violations.append("each decision must have exactly one named detail file")
        if not re.search(
            r"(?is)\bDirection\b.{0,240}\bconfirmed user intent\b.{0,160}"
            r"\binferred\s+patterns\b.{0,160}\bdecision IDs\b",
            decision,
        ):
            violations.append("DecisionHistory.md must synthesize evidence-linked project direction")
        if not re.search(
            r"(?is)\bdo not load\b.{0,100}\broutine context\b.{0,120}"
            r"\bread only\b.{0,100}\brelevant file\b",
            decision,
        ):
            violations.append("decision details must remain outside routine context")
        if re.search(
            r"(?is)\b(?:store|keep|record|include)\b.{0,80}"
            r"\b(?:implementation|verification|timeline|results?)\b.{0,80}"
            r"`DecisionHistory\.md`",
            decision,
        ):
            violations.append("DecisionHistory.md must not become an implementation archive")
        if re.search(
            r"(?is)\b(?:load|read)\s+(?:all|every)\b.{0,100}"
            r"`?DecisionDetails(?:/|`)",
            decision,
        ):
            violations.append("routine work must not load every decision detail")

    delivery = section(text, "Deliver the complete requested scope")
    if not delivery:
        violations.append("complete-delivery section is missing")
    else:
        require_terms(
            violations,
            delivery,
            "completion-ledger contract",
            (
                "CompletionLedger.md",
                "only active unresolved",
                "partial implementation",
                "TODO",
                "improvement",
                "generalization",
                "same change",
                "implemented and verified",
                "never retain",
                "resolved",
                "completed",
                "closed",
                "no active items remain",
                "version control",
                "DecisionHistory.md",
                "CompletionHistory.md",
                "explicit audit retention",
                "routine agent context",
                "explicit historical or audit work",
                "before readiness",
                "end-to-end",
            ),
        )
        if not re.search(
            r"(?is)\b(?:create|use|maintain)\b.{0,180}\bproject-root\b.{0,80}`CompletionLedger\.md`",
            delivery,
        ):
            violations.append("CompletionLedger.md must be positively assigned as the project-root ledger")
        if re.search(
            r"(?is)\b(?:do not|never|must not|may not)\s+(?:create|use|maintain)\b"
            r".{0,100}`CompletionLedger\.md`",
            delivery,
        ):
            violations.append("CompletionLedger.md appears only or ambiguously in a negative instruction")
        if not re.search(
            r"(?is)`CompletionLedger\.md`.{0,160}\bonly active unresolved\b",
            delivery,
        ):
            violations.append("CompletionLedger.md must contain only active unresolved work")
        if not re.search(
            r"(?is)\bremove\b.{0,60}\b(?:item|entry)\b.{0,80}\bsame change\b"
            r".{0,100}\bimplemented and verified\b",
            delivery,
        ):
            violations.append("implemented ledger items must be removed in the same change")
        if not re.search(
            r"(?is)\bnever retain\b.{0,100}\bresolved\b.{0,80}\bcompleted\b"
            r".{0,80}\bclosed\b",
            delivery,
        ):
            violations.append("terminal ledger entries must never be retained")
        if not re.search(
            r"(?is)\bdelete\b.{0,60}`CompletionLedger\.md`.{0,100}"
            r"\bno active items remain\b",
            delivery,
        ):
            violations.append("an empty CompletionLedger.md must be deleted")
        if not re.search(
            r"(?is)\bversion control\b.{0,80}\bdefault\b.{0,80}\bhistory\b",
            delivery,
        ):
            violations.append("version control must be the default completion history")
        if not re.search(
            r"(?is)\bconsequential\s+decisions\b.{0,100}`DecisionHistory\.md`",
            delivery,
        ):
            violations.append("consequential decisions must remain in DecisionHistory.md")
        if not re.search(
            r"(?is)\bcreate\b.{0,80}`CompletionHistory\.md`.{0,80}\bonly\b"
            r".{0,80}\bexplicit audit retention\b",
            delivery,
        ):
            violations.append("CompletionHistory.md must be an explicit-audit-only archive")

        terminal_entry = re.compile(
            r"(?is)(?:\b(?:resolved|completed|closed)\b.{0,100}"
            r"\b(?:entries|items|rows|evidence)\b|"
            r"\b(?:entries|items|rows|evidence)\b.{0,100}"
            r"\b(?:resolved|completed|closed)\b)"
        )
        retention_verb = re.compile(
            r"(?i)\b(?:keep|retain|archive|store|preserve|leave|remain)\b"
        )
        negative_removal = re.compile(
            r"(?is)\b(?:do not|never|must not|may not|shall not|should not)\b"
            r".{0,30}\b(?:remove|delete|clear|drop|removed|deleted|cleared|dropped)\b"
        )
        removal = r"\b(?:remove|delete|clear|drop|removed|deleted|cleared|dropped)\b"
        delay = r"\b(?:later|eventually|subsequently|after readiness|separate change)\b"
        delayed_removal = re.compile(
            rf"(?is)(?:{removal}.{{0,80}}{delay}|{delay}.{{0,80}}{removal})"
        )
        negative_prefix = re.compile(
            r"(?is)(?:\bnever\b|\b(?:do|must|may|shall|should|can)\s+not\b|"
            r"\bnot\b(?:\s+\w+){0,2})\s*$"
        )
        clauses = re.split(r"[.!?;]\s+|[—–]|\s+(?i:but)\s+|\n(?=- )", delivery)
        for clause in clauses:
            if not terminal_entry.search(clause):
                continue
            active_context = "`CompletionLedger.md`" in clause or bool(
                re.search(r"(?i)\bactive\s+(?:completion\s+)?ledger\b", clause)
            )
            cold_history = "`CompletionHistory.md`" in clause or bool(
                re.search(r"(?i)\bversion control\b", clause)
            )
            if cold_history and not active_context:
                continue
            if negative_removal.search(clause) or delayed_removal.search(clause):
                violations.append("CompletionLedger.md must not preserve terminal entries as history")
                break
            for match in retention_verb.finditer(clause):
                prefix = clause[: match.start()].rsplit(",", 1)[-1]
                if negative_prefix.search(prefix):
                    continue
                violations.append("CompletionLedger.md must not preserve terminal entries as history")
                break
            else:
                continue
            break

    efficiency = section(text, "Measure delivery efficiency truthfully")
    if not efficiency:
        violations.append("delivery-efficiency section is missing")
    else:
        require_terms(
            violations,
            efficiency,
            "delivery-efficiency contract",
            (
                "observational",
                "complete scope",
                "never omit",
                "required work",
                "tests",
                "improve a metric",
                "runtime",
                "harness",
                "recorder",
                "request receipt",
                "first model or tool activity",
                "terminal delivery",
                "request-to-delivery wall time",
                "execution wall time",
                "queue or scheduling delay",
                "concurrency-safely",
                "EfficiencyLedger.jsonl",
                "outside source worktrees",
                "routine context",
                "does not itself capture telemetry",
                "instrumentation gap",
                "reconstruct",
                "estimate",
                "zero",
                "complete instrumentation",
                "proves no usage",
                "not-applicable",
                "task start",
                "terminal status",
                "complete",
                "incomplete",
                "blocked",
                "cancelled",
                "superseded",
                "interrupted",
                "preserve prior events",
                "continuations",
                "corrections",
                "defects",
                "retries",
                "rollback",
                "rework",
                "original lineage",
                "double-counting",
                "separate dimensions",
                "kind",
                "continuation",
                "defect repair",
                "cause",
                "agent-caused",
                "changed user intent",
                "new scope",
                "external cause",
                "authoritative runtime or provider token counters",
                "monotonic clock",
                "provider-native",
                "input",
                "output",
                "cached",
                "reasoning",
                "provenance",
                "instrumentation coverage",
                "root",
                "delegated agents",
                "failed attempts",
                "two independent dimensions",
                "planning",
                "implementation",
                "testing",
                "deployment",
                "reporting",
                "unattributed",
                "model-active",
                "tool-active",
                "external-wait",
                "user-wait",
                "blocked-wait",
                "test authoring",
                "test execution",
                "planning covers requirements",
                "context",
                "research",
                "diagnosis",
                "design",
                "sequencing",
                "implementation covers changes",
                "configuration",
                "documentation",
                "data",
                "test artifacts",
                "testing covers executing and reviewing verification",
                "deployment covers release or environment mutation",
                "reporting covers user-facing status and handoff",
                "ambiguous mixed work",
                "measurement provenance",
                "attribution provenance",
                "agent-declared",
                "classifier or schema version",
                "inferred allocation",
                "measured",
                "phase-inclusive elapsed",
                "interval unions",
                "activity-state duration",
                "deduplicate overlapping spans",
                "end-to-end wall time",
                "summed per-agent active time",
                "concurrent phase unions",
                "task lineage",
                "opaque project and revision",
                "schema",
                "recorder",
                "policy",
                "model or runtime configuration versions",
                "outcome",
                "delivered scope",
                "agreed requested-scope",
                "acceptance baseline",
                "user-approved scope changes",
                "requirement ID",
                "evidence reference",
                "satisfied",
                "partial",
                "explicitly removed",
                "in-scope requirement",
                "unresolved",
                "verification",
                "evidence provenance",
                "coverage",
                "measurement overhead",
                "runtime-observed",
                "declared",
                "inferred",
                "unknown",
                "task-type",
                "scope-size",
                "method tags",
                "compatible measurement semantics",
                "prompts",
                "source content",
                "tool payloads",
                "secrets",
                "credentials",
                "personal data",
            ),
        )
        efficiency = " ".join(efficiency.split())
        if not re.search(
            r"(?is)\buse a runtime-\s+or harness-owned recorder\b",
            efficiency,
        ) or not re.search(r"(?is)\brecorder\b.{0,500}`EfficiencyLedger\.jsonl`", efficiency):
            violations.append("the cold efficiency ledger must be assigned to a runtime or harness recorder")
        if not re.search(
            r"(?is)`EfficiencyLedger\.jsonl`.{0,100}\boutside source worktrees\b"
            r".{0,100}\broutine context\b",
            efficiency,
        ):
            violations.append("efficiency telemetry must remain outside worktrees and routine context")
        if not re.search(
            r"(?is)\bpolicy\b.{0,60}\bdoes not itself capture telemetry\b.{0,140}"
            r"\binstrumentation gap\b",
            efficiency,
        ):
            violations.append("policy must distinguish its contract from an operational recorder")
        if not re.search(
            r"(?is)\brecorder\s+from\s+request receipt\s+through\s+terminal delivery\b"
            r".{0,120}\bfirst model or tool activity\b.{0,40}\bseparately\b",
            efficiency,
        ) or not re.search(
            r"(?is)\brequest-to-delivery wall time\b.{0,80}\bexecution wall time\b"
            r".{0,40}\bseparately\b.{0,100}\b(?:queue|scheduling) delay\b",
            efficiency,
        ):
            violations.append("efficiency timing must expose request delay separately from execution")
        terminal_window = re.search(
            r"(?is)\bterminal status of\s+(?P<statuses>.{0,180}?)(?:\.|\n\s*-)",
            efficiency,
        )
        terminal_statuses = ("complete", "incomplete", "blocked", "cancelled", "superseded", "interrupted")
        recorded_statuses = (
            {
                word.casefold()
                for word in re.findall(r"\b[A-Za-z][A-Za-z-]*\b", terminal_window.group("statuses"))
                if word.casefold() not in {"and", "or"}
            }
            if terminal_window
            else set()
        )
        if recorded_statuses != set(terminal_statuses):
            violations.append("efficiency telemetry must retain the exact terminal status set")
        if not re.search(
            r"(?is)\btask start\b.{0,100}\bterminal status\b.{0,220}"
            r"\bpreserve prior events\b.{0,140}\bappend linked\b.{0,100}"
            r"\b(?:continuations|corrections)\b",
            efficiency,
        ):
            violations.append("efficiency events must preserve the complete append-only lifecycle")
        if not re.search(
            r"(?is)\bauthoritative\b.{0,80}\b(?:runtime|provider)\b.{0,80}"
            r"\btoken counters\b.{0,100}\bmonotonic\s+clock\b",
            efficiency,
        ):
            violations.append("token and time measurements must have authoritative provenance")
        if not re.search(
            r"(?is)\bprovider-native\b.{0,100}\binput\b.{0,40}\boutput\b.{0,40}"
            r"\bcached\b.{0,40}\breasoning\b.{0,80}\btoken categories\b",
            efficiency,
        ):
            violations.append("provider-native token categories must remain distinct when available")
        if not re.search(
            r"(?is)\brecord zero only\b.{0,80}\bcomplete instrumentation\b.{0,60}"
            r"\bproves no usage\b.{0,80}\bunknown\b.{0,40}\bnot-applicable\b",
            efficiency,
        ):
            violations.append("zero requires proven complete instrumentation; missing values remain unknown")
        if not re.search(
            r"(?is)\btwo independent dimensions\b.{0,180}\bphase\b.{0,240}"
            r"\bactivity state\b",
            efficiency,
        ):
            violations.append("phase and activity state must remain independent dimensions")
        if not re.search(
            r"(?is)\bmeasurement provenance\b.{0,80}\battribution provenance\b.{0,220}"
            r"\bruntime-observed\b.{0,80}\bagent-declared\b.{0,80}\binferred\b.{0,80}"
            r"\bunknown\b.{0,120}\bclassifier or schema version\b",
            efficiency,
        ) or not re.search(
            r"(?is)\bnever present an inferred allocation as measured\b",
            efficiency,
        ):
            violations.append("phase and classification attribution must carry separate provenance")
        if not re.search(
            r"(?is)\btest authoring\b.{0,100}\bimplementation\b.{0,100}"
            r"\btest execution\b.{0,100}\btesting\b",
            efficiency,
        ):
            violations.append("test authoring and execution must use stable phase boundaries")
        if not re.search(
            r"(?is)\bplanning covers requirements\b.{0,160}\bcontext\b.{0,80}\bresearch\b"
            r".{0,80}\bdiagnosis\b.{0,80}\bdesign\b.{0,80}\bsequencing\b",
            efficiency,
        ) or not re.search(
            r"(?is)\bimplementation covers changes\b.{0,80}\bcode\b.{0,80}"
            r"\bconfiguration\b.{0,80}\bdocumentation\b.{0,80}\bdata\b.{0,80}"
            r"\btest artifacts\b",
            efficiency,
        ) or not re.search(
            r"(?is)\btesting covers executing and reviewing verification\b.{0,100}"
            r"\bdeployment covers release or environment mutation\b.{0,120}"
            r"\breporting covers user-facing status and handoff\b.{0,100}"
            r"\bambiguous mixed work\b.{0,60}\bunattributed\b",
            efficiency,
        ):
            violations.append("efficiency phases must have stable operational boundaries")
        if not re.search(
            r"(?is)\bphase-inclusive elapsed\b.{0,80}\binterval unions\b.{0,120}"
            r"\bactivity-state duration\b",
            efficiency,
        ):
            violations.append("phase-inclusive and activity-state timing must both be reported")
        if not re.search(
            r"(?is)\bend-to-end wall time\b.{0,80}\bseparately\b.{0,100}"
            r"\bsummed per-agent active time\b.{0,140}\bconcurrent phase unions\b"
            r".{0,100}\bmust not be summed as wall time\b",
            efficiency,
        ):
            violations.append("concurrent agent time must not be confused with wall time")
        if not re.search(
            r"(?is)\bterminal event\b.{0,400}\boutcome\b",
            efficiency,
        ) or not re.search(
            r"(?is)\bdelivered scope\b.{0,100}\bverification\b.{0,100}\bevidence provenance\b",
            efficiency,
        ):
            violations.append("terminal telemetry must bind cost to outcome, scope, and verification")
        if not re.search(
            r"(?is)\bagreed requested-scope\b.{0,80}\bacceptance baseline\b.{0,80}"
            r"\buser-approved scope changes\b.{0,220}\brequirement ID\b.{0,80}"
            r"\bevidence reference\b.{0,120}\bsatisfied\b.{0,60}\bpartial\b.{0,60}"
            r"\bblocked\b.{0,60}\bexplicitly removed\b",
            efficiency,
        ) or not re.search(
            r"(?is)\bcannot be complete\b.{0,100}\bin-scope requirement\b.{0,80}\bunresolved\b",
            efficiency,
        ):
            violations.append("terminal telemetry must prove agreed-scope and requirement coverage")
        if not re.search(
            r"(?is)\bwithout double-counting\b.{0,160}\bseparate dimensions\b.{0,80}"
            r"\bkind\b.{0,80}\bcontinuation\b.{0,60}\bretry\b.{0,60}\brollback\b"
            r".{0,60}\bdefect repair\b.{0,60}\brework\b.{0,100}\bcause\b.{0,80}"
            r"\bagent-caused\b.{0,80}\bchanged user intent\b.{0,80}\bnew scope\b"
            r".{0,80}\bexternal cause\b.{0,60}\bunknown\b",
            efficiency,
        ):
            violations.append("linked work must separate kind from cause and avoid double-counting")
        if not re.search(
            r"(?is)\bnonsensitive opaque project and\s+revision identifiers\b",
            efficiency,
        ):
            violations.append("project and revision identity must be nonsensitive and opaque")

        contradictions = (
            (
                r"(?ims)(?:^\s*(?:-\s+)?|\b(?:may|should|must|can|will)\s+)"
                r"(?:store|keep|write|maintain)\b.{0,80}`EfficiencyLedger\.jsonl`"
                r".{0,40}\b(?:in|inside|within|under)\b.{0,60}"
                r"\b(?:project-root|source worktree|routine context)\b",
                "EfficiencyLedger.jsonl must not become hot project context",
            ),
            (
                r"(?is)\b(?:may|should|must|can|will)\s+(?:be\s+)?"
                r"(?:estimate|estimated|reconstruct|reconstructed|infer|inferred)\b"
                r".{0,120}\b(?:missing|unknown|unavailable|unsupported)\b",
                "missing efficiency measurements must not be estimated",
            ),
            (
                r"(?ims)^\s*(?:-\s+)?(?:use\s+(?:a\s+)?(?:heuristic\s+)?estimates?|"
                r"estimate|reconstruct|infer)\b.{0,160}"
                r"(?:missing|unknown|unavailable|unsupported|authoritative counters?)\b",
                "missing efficiency measurements must not be estimated",
            ),
            (
                r"(?ims)(?:^\s*(?:-\s+)?|\b(?:may|should|must|can|will)\s+)"
                r"(?:record|treat|fill|substitute|report)\b.{0,80}"
                r"\b(?:missing|unknown|unavailable|unsupported|uninstrumented|unobserved)\b.{0,80}"
                r"\b(?:as|with)\s+(?:a\s+)?zero\b",
                "unknown efficiency measurements must not be zero-filled",
            ),
            (
                r"(?ims)(?:^\s*(?:-\s+)?|\b(?:may|should|must|can)\s+)(?:omit|skip|reduce|narrow|drop)\b"
                r".{0,120}\b(?:scope|required work|tests?|verification|quality|context|explanation)\b"
                r".{0,120}\b(?:metric|efficien)",
                "efficiency metrics must not reward reduced delivery quality or scope",
            ),
            (
                r"(?ims)(?:^\s*(?:-\s+)?|\b(?:may|should|must|can)\s+)(?:rewrite|replace|delete|discard)\b"
                r".{0,100}\b(?:prior|earlier|old)\s+(?:events?|history|records?)\b",
                "efficiency history must be corrected append-only",
            ),
            (
                r"(?ims)(?:^\s*(?:-\s+)?|\b(?:may|should|must|can)\s+)(?:combine|collapse|merge|treat)\b"
                r".{0,100}\bphase\b.{0,100}\bactivity(?: state)?\b",
                "phase and activity state must not be collapsed",
            ),
            (
                r"(?ims)(?:^\s*(?:-\s+)?|\b(?:may|should|must|can)\s+)(?:omit|exclude|ignore|drop)\b"
                r".{0,100}\b(?:failed attempts?|retries|rollback|rework|delegated agents?)\b",
                "efficiency telemetry must include failed and delegated work",
            ),
            (
                r"(?is)\b(?:do not|don't|never)\s+(?:include|record|count)\b"
                r".{0,100}\b(?:failed attempts?|retries|rollback|rework|delegated agents?)\b",
                "efficiency telemetry must include failed and delegated work",
            ),
            (
                r"(?is)\b(?:begin|start|measure|record)\b.{0,80}\bafter\s+(?:the\s+)?"
                r"first model or tool activity\b",
                "efficiency timing must not omit pre-execution request delay",
            ),
            (
                r"(?ims)(?:^\s*(?:-\s+)?|\b(?:may|should|must|can|will)\s+)"
                r"(?:report|present|treat|label|count|record)\b.{0,100}\binferred\b.{0,80}"
                r"\ballocations?\b.{0,60}\b(?:as|like)\s+"
                r"(?:measured(?:\s+values?)?|measurements?|observed values?)\b",
                "inferred efficiency attribution must not be presented as measured",
            ),
            (
                r"(?ims)(?:^\s*(?:-\s+)?)(?:"
                r"(?:a\s+)?task\b.{0,60}\b(?:may|can|should)\b.{0,40}"
                r"(?:be\s+)?(?:(?:called|marked|reported|treated)\s+)?complete\b|"
                r"complete\b.{0,40}\b(?:the\s+)?task\b|"
                r"(?:declare|mark|report|treat|call)\b.{0,60}\bcomplete\b)"
                r"(?=.{0,260}\bin-scope\b)(?=.{0,260}\b(?:unresolved|partial|blocked)\b)",
                "completion telemetry must not ignore unresolved in-scope requirements",
            ),
            (
                r"(?ims)(?:^\s*(?:-\s+)?|\b(?:may|should|must|can|will)\s+)"
                r"(?:use|add|allow|record|treat)\s+[a-z][a-z0-9_-]*\s+as\s+"
                r"(?:an?\s+)?(?:additional|extra|new|another)\s+terminal\s+(?:status|outcome)\b",
                "efficiency telemetry must retain the exact terminal status set",
            ),
            (
                r"(?ims)(?:^\s*(?:-\s+)?|\b(?:may|should|must|can|will)\s+)"
                r"(?:combine|collapse|merge|aggregate|discard)\b.{0,120}"
                r"\b(?:provider-native|input|output|cached|reasoning)\b.{0,100}\btoken categor",
                "provider-native token categories must not be collapsed",
            ),
            (
                r"(?ims)(?:^\s*(?:-\s+)?|\b(?:may|should|must|can|will)\s+)"
                r"report\b.{0,100}\b(?:one|single|combined|aggregate)\s+total\b"
                r".{0,100}\b(?:instead of|rather than|for)\b.{0,100}"
                r"\bprovider-native\b.{0,80}\btoken categor",
                "provider-native token categories must not be collapsed",
            ),
            (
                r"(?ims)(?:^\s*(?:-\s+)?|\b(?:may|should|must|can|will)\s+)"
                r"(?:combine|collapse|merge|sum)\b.{0,140}\b(?:request-to-delivery|request)\b"
                r".{0,100}\bexecution wall time\b",
                "request-to-delivery and execution wall time must remain separate",
            ),
            (
                r"(?ims)^\s*(?:-\s+)?report\b.{0,100}\b(?:request-to-delivery|request)\b"
                r".{0,100}\bexecution\b.{0,80}\b(?:one|single|combined)\b.{0,40}\bwall time\b",
                "request-to-delivery and execution wall time must remain separate",
            ),
            (
                r"(?ims)(?:^\s*(?:-\s+)?|\b(?:may|should|must|can|will)\s+)"
                r"(?:treat|classify|count|label)\b.{0,120}"
                r"\b(?:changed user intent|new scope)\b.{0,100}\bas\s+agent-caused\b",
                "changed intent and new scope must not be counted as agent-caused rework",
            ),
            (
                r"(?ims)(?:^\s*(?:-\s+)?|\b(?:may|should|must|can|will)\s+)"
                r"(?:record|store|retain|use)\b.{0,100}\b(?:raw|private|confidential)\b"
                r".{0,100}\b(?:project|revision)\b(?:.{0,40}\b(?:name|metadata|identity)\b)?",
                "project and revision identity must remain nonsensitive and opaque",
            ),
            (
                r"(?ims)(?:^\s*(?:-\s+)?|\b(?:may|should|must|can|will)\s+)"
                r"(?:treat|classify|label|count)\b.{0,120}"
                r"\b(?:requirements?|context|research|diagnosis|design|sequencing)\b"
                r".{0,120}\bas\s+implementation\b",
                "planning work must not be reclassified as implementation",
            ),
            (
                r"(?is)\b(?:only|just)\s+(?:record|write|keep)\b.{0,100}"
                r"\bterminal\s+(?:event|record|status)\b",
                "efficiency telemetry must include start and terminal lifecycle events",
            ),
        )
        for pattern, message in contradictions:
            if re.search(pattern, text):
                violations.append(message)

        for line in text.splitlines():
            directive = line.strip().removeprefix("-").strip()
            if (
                re.match(r"(?i)^(?:use|record|report|treat|substitute)\b", directive)
                and re.search(r"(?i)\bzero\b", directive)
                and re.search(
                    r"(?i)\b(?:missing|unknown|unavailable|unsupported|uninstrumented|unobserved)\b",
                    directive,
                )
                and not (
                    re.search(r"(?i)\bonly\b", directive)
                    and re.search(r"(?i)\bcomplete instrumentation\b", directive)
                    and re.search(r"(?i)\bproves no usage\b", directive)
                )
            ):
                violations.append("unknown efficiency measurements must not be zero-filled")
            sensitive = re.search(
                r"(?i)\b(?:prompts?|source content|tool payloads?|secrets?|credentials?|personal data)\b",
                directive,
            )
            if not sensitive:
                continue
            positive_retention = re.match(r"(?i)^(?:store|retain|record|include)\b", directive) or re.search(
                r"(?i)\b(?:may|should|must|can|will)\s+(?:store|retain|record|include)\b",
                directive,
            )
            if not positive_retention:
                continue
            if re.search(
                r"(?i)\b(?:never|not|without|omit(?:ted|ting)?|exclud(?:e|ed|ing)|redact(?:ed|ing)?|safeguard)\b",
                directive,
            ):
                continue
            violations.append("efficiency telemetry must not retain sensitive content")
            break

    mistakes = section(text, "Learn from agent-made mistakes")
    if not mistakes:
        violations.append("agent-mistake section is missing")
    else:
        require_terms(
            violations,
            mistakes,
            "agent-mistake contract",
            ("user intent", "before fixing", "guardrail", "retest"),
        )

    interface = section(text, "Put requested interface content first")
    if not interface:
        violations.append("content-first interface section is missing")
    else:
        require_terms(
            violations,
            interface,
            "collection-destination contract",
            (
                "content promise",
                "first substantial content",
                "first viewport",
                "list or collection",
                "real items",
                "narrow screens",
                "loading",
                "error",
                "empty state",
            ),
        )
        require_terms(
            violations,
            interface,
            "visible-create-flow contract",
            (
                "add or create",
                "current viewport",
                "dialog",
                "sheet",
                "dedicated page",
                "below a long list",
                "off-screen",
                "focused",
                "successful creation",
                "new item",
            ),
        )
        require_terms(
            violations,
            interface,
            "persistent-approval contract",
            (
                "visual exploration",
                "approval state",
                "exact response request",
                "embedding",
                "no follow-up",
            ),
        )
        if not re.search(
            r"(?is)^- .*\b(?:list or collection|collection)\b.*\b(?:show|first|lead)\b",
            interface,
            flags=re.MULTILINE,
        ):
            violations.append("collection-first behavior must be an operative policy bullet")
        if not re.search(
            r"(?is)^- .*\badd or create\b.*\bcurrent\s+viewport\b",
            interface,
            flags=re.MULTILINE,
        ):
            violations.append("visible add/create behavior must be an operative policy bullet")

    for name in FORBIDDEN_NAMES:
        if name.casefold() in text.casefold():
            violations.append(f"universal policy contains named product or tool: {name}")

    absolute_path = re.search(r"(?m)(?:^|[\s`])(?:/[^\s`]+|~/[^\s`]+)", text)
    if absolute_path:
        violations.append(f"universal policy contains a filesystem path: {absolute_path.group(0).strip()}")

    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    args = parser.parse_args()

    if not args.policy.is_file():
        raise SystemExit(f"policy not found: {args.policy}")
    violations = find_policy_violations(args.policy.read_text(encoding="utf-8"))
    if violations:
        for violation in violations:
            print(f"policy violation: {violation}")
        return 1
    print(f"app-wide policy check ok ({args.policy})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
