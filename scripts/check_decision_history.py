#!/usr/bin/env python3
"""Validate the compact decision index and its one-file-per-decision archive."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEX = ROOT / "DecisionHistory.md"
DEFAULT_DETAILS = ROOT / "DecisionDetails"

ENTRY_HEADING = re.compile(
    r"^## \[(D-\d{8}-\d{2}) — ([^\]\n]+)\]"
    r"\((DecisionDetails/(D-\d{8}-\d{2})\.md)\)$"
)
ID_PATTERN = re.compile(r"\bD-\d{8}-\d{2}\b")
WHY_CLAUSES = ("Options:", "Prior attempts:", "Intent:", "Revisit only if:")


@dataclass(frozen=True)
class HistoryEntry:
    decision_id: str
    title: str
    detail_path: str
    line: int
    why: str


def _paragraphs(lines: list[str]) -> list[list[str]]:
    paragraphs: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.strip():
            current.append(line.rstrip())
        elif current:
            paragraphs.append(current)
            current = []
    if current:
        paragraphs.append(current)
    return paragraphs


def _flat(lines: list[str]) -> str:
    return " ".join(" ".join(lines).split())


def find_index_violations(text: str) -> tuple[list[str], list[HistoryEntry]]:
    lines = text.splitlines()
    violations: list[str] = []
    entries: list[HistoryEntry] = []

    if not lines or lines[0] != "# Decision History":
        violations.append("index must begin with '# Decision History'")

    section_starts = [index for index, line in enumerate(lines) if line.startswith("## ")]
    if not section_starts:
        violations.append("index must contain at least one linked decision entry")
        return violations, entries

    preamble = _paragraphs(lines[1 : section_starts[0]])
    if len(preamble) != 1:
        violations.append("index must have exactly one Direction paragraph before its entries")
        direction = ""
    else:
        direction = _flat(preamble[0])
        if not direction.startswith("Direction:"):
            violations.append("the preamble paragraph must begin with 'Direction:'")
        if "Confirmed:" not in direction or "Inferred:" not in direction:
            violations.append("Direction must distinguish Confirmed and Inferred intent")
        if not ID_PATTERN.search(direction):
            violations.append("Direction must cite supporting decision IDs")

    seen_ids: set[str] = set()
    seen_details: set[str] = set()
    previous_date: str | None = None

    for position, start in enumerate(section_starts):
        end = section_starts[position + 1] if position + 1 < len(section_starts) else len(lines)
        heading = lines[start]
        match = ENTRY_HEADING.fullmatch(heading)
        if not match:
            violations.append(
                f"line {start + 1}: heading must link a stable ID to DecisionDetails/<ID>.md"
            )
            continue

        decision_id, title, detail_path, linked_id = match.groups()
        if linked_id != decision_id:
            violations.append(f"line {start + 1}: heading ID and detail filename differ")
        if decision_id in seen_ids:
            violations.append(f"line {start + 1}: duplicate decision ID {decision_id}")
        seen_ids.add(decision_id)
        if detail_path in seen_details:
            violations.append(f"line {start + 1}: detail file is shared by multiple decisions")
        seen_details.add(detail_path)

        date = decision_id[2:10]
        if previous_date is not None and date > previous_date:
            violations.append(f"line {start + 1}: decisions must be ordered newest date first")
        previous_date = date

        paragraphs = _paragraphs(lines[start + 1 : end])
        if len(paragraphs) != 2:
            violations.append(
                f"line {start + 1}: entry must contain exactly Decision and Why paragraphs"
            )
            continue
        if any(
            re.match(r"^\s*(?:#{1,6}\s|[-*+]\s|\d+\.\s|\|)", line)
            for paragraph in paragraphs
            for line in paragraph
        ):
            violations.append(f"line {start + 1}: index entries must not contain lists, tables, or subheadings")

        decision = _flat(paragraphs[0])
        why = _flat(paragraphs[1])
        if not decision.startswith("Decision:") or not decision.removeprefix("Decision:").strip():
            violations.append(f"line {start + 1}: first paragraph must be a nonempty Decision")
        if not why.startswith("Why:") or not why.removeprefix("Why:").strip():
            violations.append(f"line {start + 1}: second paragraph must be a nonempty Why")
        else:
            clause_positions = [why.find(clause) for clause in WHY_CLAUSES]
            if any(value < 0 for value in clause_positions) or clause_positions != sorted(clause_positions):
                violations.append(
                    f"line {start + 1}: Why must contain ordered Options, Prior attempts, Intent, and Revisit only if clauses"
                )
            else:
                options = why[clause_positions[0] : clause_positions[1]].casefold()
                prior = why[clause_positions[1] : clause_positions[2]].casefold()
                revisit = why[clause_positions[3] :].casefold()
                no_alternative = "no material alternative" in options
                selected = "selected" in options
                compared = any(term in options for term in ("rejected", " over ", "instead of"))
                if not no_alternative and not (selected and compared):
                    violations.append(
                        f"line {start + 1}: Options must identify the selected and rejected alternatives"
                    )
                no_prior = "none known" in prior
                failure_terms = (
                    "failed",
                    "did not work",
                    "caused",
                    "missed",
                    "drifted",
                    "stalled",
                    "could not",
                    "inadequate",
                    "lost",
                    "unsafe",
                    "obscured",
                    "duplicated",
                    "diverged",
                    "broke",
                    "risk",
                )
                if not no_prior and not any(term in prior for term in failure_terms):
                    violations.append(
                        f"line {start + 1}: Prior attempts must state the observed failure"
                    )
                if any(term in revisit for term in ("time passes", "later", "forgotten", "out of context")):
                    violations.append(
                        f"line {start + 1}: revisit cannot be justified by time or context loss"
                    )

        entries.append(HistoryEntry(decision_id, title.strip(), detail_path, start + 1, why))

    all_ids = {entry.decision_id for entry in entries}
    for reference in ID_PATTERN.findall(direction):
        if reference not in all_ids:
            violations.append(f"Direction cites unknown decision ID {reference}")
    for entry in entries:
        for reference in re.findall(r"(?i)\bsupersedes\s+(D-\d{8}-\d{2})\b", entry.why):
            if reference == entry.decision_id:
                violations.append(f"{entry.decision_id} cannot supersede itself")
            elif reference not in all_ids:
                violations.append(f"{entry.decision_id} supersedes unknown decision ID {reference}")

    return violations, entries


def audit_history(index: Path, details: Path) -> list[str]:
    if not index.is_file() or index.is_symlink():
        return [f"decision index must be a regular file: {index}"]

    violations, entries = find_index_violations(index.read_text(encoding="utf-8"))
    expected = {Path(entry.detail_path).name: entry for entry in entries}
    actual: set[str] = set()

    if not details.is_dir() or details.is_symlink():
        violations.append(f"decision details must be a regular directory: {details}")
    else:
        for child in details.iterdir():
            if child.is_symlink() or not child.is_file() or child.suffix != ".md":
                violations.append(f"unexpected decision-detail artifact: {child.name}")
                continue
            actual.add(child.name)

    for filename, entry in expected.items():
        path = details / filename
        if filename not in actual:
            violations.append(f"missing detail file for {entry.decision_id}: {filename}")
            continue
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        expected_heading = f"# {entry.decision_id} — {entry.title}"
        if not lines or lines[0] != expected_heading:
            violations.append(f"{filename}: detail heading does not match its index entry")
        if len(lines) < 2 or lines[1] != "Index: [DecisionHistory.md](../DecisionHistory.md)":
            violations.append(f"{filename}: detail file lacks the canonical index backlink")
        if len(lines) < 4 or lines[2] not in {"## Detail", "## Original record"}:
            violations.append(f"{filename}: detail file must contain a Detail or Original record section")

    for filename in sorted(actual - set(expected)):
        violations.append(f"orphan decision-detail file: {filename}")

    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--details", type=Path, default=DEFAULT_DETAILS)
    args = parser.parse_args()

    violations = audit_history(args.index, args.details)
    if violations:
        for violation in violations:
            print(f"decision history violation: {violation}")
        return 1

    _, entries = find_index_violations(args.index.read_text(encoding="utf-8"))
    print(f"decision history check ok ({len(entries)} indexed decisions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
