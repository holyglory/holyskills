#!/usr/bin/env python3
"""Validate the stable semantic contract of the universal agent policy."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "reference" / "codex-app-wide" / "AGENTS.md"
MAX_WORDS = 1800

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
            ),
        )
        if not re.search(
            r"(?is)\b(?:record|use|maintain)\b.{0,160}\bproject-root\b.{0,80}`DecisionHistory\.md`",
            decision,
        ):
            violations.append("DecisionHistory.md must be positively assigned as the project-root record")
        if re.search(r"(?is)\b(?:do not|never)\b.{0,100}`DecisionHistory\.md`", decision):
            violations.append("DecisionHistory.md appears only or ambiguously in a negative instruction")
        if not re.search(r"(?is)\bunder-engineering\b.{0,100}\bmore serious\b", decision):
            violations.append("foundation asymmetry must make under-engineering the more serious failure")
        if not re.search(r"(?is)\bover-provisioned\b.{0,80}\bacceptable\b", decision):
            violations.append("foundation asymmetry must make over-provisioned capacity acceptable")

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
                "partial implementation",
                "TODO",
                "improvement",
                "generalization",
                "before readiness",
                "end-to-end",
            ),
        )
        if not re.search(
            r"(?is)\b(?:create|use|maintain)\b.{0,180}\bproject-root\b.{0,80}`CompletionLedger\.md`",
            delivery,
        ):
            violations.append("CompletionLedger.md must be positively assigned as the project-root ledger")
        if re.search(r"(?is)\b(?:do not|never)\b.{0,100}`CompletionLedger\.md`", delivery):
            violations.append("CompletionLedger.md appears only or ambiguously in a negative instruction")

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

    word_count = len(re.findall(r"\b\w[\w'-]*\b", text))
    if word_count > MAX_WORDS:
        violations.append(f"universal policy exceeds {MAX_WORDS} words: {word_count}")

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
