#!/usr/bin/env python3
"""Reject active instructions that restore a Markdown completion ledger."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NEGATIVE_MARKERS = (
    "never ",
    "do not ",
    "must not ",
    "no workflow ",
    "forbid",
    "prohibit",
    "reject",
    "retired",
    "remove `completionledger.md`",
    "require the repository root to contain no",
)
FORBIDDEN_TERMS = (
    "completion-ledger-plan.json",
    "open-only completion-ledger",
    "active-only completion-ledger",
    "default markdown mode",
)


def instruction_files(root: Path) -> list[Path]:
    files = [
        root / "AGENTS.md",
        root / "reference" / "codex-app-wide" / "AGENTS.md",
        root / "README.md",
        root / "SKILL_AUDIT.md",
    ]
    for skill in sorted((root / "skills").iterdir()):
        if not skill.is_dir() or skill.is_symlink():
            continue
        files.extend(path for path in (skill / "SKILL.md", skill / "README.md") if path.is_file())
        references = skill / "references"
        if references.is_dir():
            files.extend(sorted(references.glob("*.md")))
    files.extend(sorted((root / "UserIssueLedgers").rglob("*.md")))
    return files


def paragraphs(text: str) -> list[tuple[int, str]]:
    result: list[tuple[int, str]] = []
    start = 1
    buffer: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            if buffer:
                result.append((start, "\n".join(buffer)))
                buffer = []
            start = number + 1
        else:
            if not buffer:
                start = number
            buffer.append(line)
    if buffer:
        result.append((start, "\n".join(buffer)))
    return result


def find_text_violations(text: str, label: str) -> list[str]:
    violations: list[str] = []
    lowered = text.casefold()
    for term in FORBIDDEN_TERMS:
        if term in lowered:
            violations.append(f"{label}: retired completion-ledger instruction remains: {term}")
    for line, paragraph in paragraphs(text):
        folded = paragraph.casefold()
        if "completionledger.md" not in folded:
            continue
        if not any(marker in folded for marker in NEGATIVE_MARKERS):
            violations.append(
                f"{label}:{line}: CompletionLedger.md is mentioned without an explicit prohibition"
            )
    if re.search(r"(?i)completion\s+ledger", text) and "database" not in lowered:
        violations.append(f"{label}: completion-ledger instructions do not name the database authority")
    return violations


def audit(root: Path) -> list[str]:
    violations: list[str] = []
    for path in instruction_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as error:
            violations.append(f"{path}: could not read instruction file: {error}")
            continue
        violations.extend(find_text_violations(text, path.relative_to(root).as_posix()))
    return violations


def main() -> int:
    violations = audit(ROOT)
    if violations:
        for violation in violations:
            print(f"completion ledger instruction violation: {violation}")
        return 1
    print("completion ledger instruction check ok (database-only across active instructions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
