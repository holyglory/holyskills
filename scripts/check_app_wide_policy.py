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
