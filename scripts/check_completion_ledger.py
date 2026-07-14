#!/usr/bin/env python3
"""Require CompletionLedger.md to contain active work only or be absent."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER = ROOT / "CompletionLedger.md"
REQUIRED_COLUMNS = (
    "id",
    "remaining work",
    "why it matters",
    "status",
    "verification",
)

TERMINAL_STATUSES = {
    "closed",
    "complete",
    "completed",
    "done",
    "fixed",
    "implemented",
    "implemented and verified",
    "resolved",
    "verified",
}

ACTIVE_STATUSES = {
    "active",
    "blocked",
    "in progress",
    "incomplete",
    "open",
    "partial",
    "pending",
    "to do",
    "todo",
    "unresolved",
    "waiting",
}


def _table_cells(line: str) -> list[str] | None:
    stripped = line.strip()
    if "|" not in stripped:
        return None
    cells = re.split(r"(?<!\\)\|", stripped)
    if stripped.startswith("|"):
        cells = cells[1:]
    if stripped.endswith("|"):
        cells = cells[:-1]
    return [cell.replace(r"\|", "|").strip() for cell in cells]


def _is_separator(cells: list[str] | None) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _status_key(value: str) -> str:
    plain = re.sub(r"[`*_]", "", value).strip().casefold()
    plain = re.sub(r"[\s_-]+", " ", plain)
    return plain.strip(" .:;()[]{}")


def _classified_status(value: str) -> str | None:
    key = _status_key(value)
    for status in sorted(TERMINAL_STATUSES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(status)}(?:\b|$)", key):
            return "terminal"
    for status in sorted(ACTIVE_STATUSES, key=len, reverse=True):
        if re.match(rf"^{re.escape(status)}(?:\b|$)", key):
            return "active"
    return None


def find_ledger_violations(text: str) -> list[str]:
    """Return violations for the repository's one canonical active-work table."""

    lines = text.splitlines()
    violations: list[str] = []
    active_items = 0
    row_count = 0
    allowed_lines: set[int] = set()
    seen_ids: set[str] = set()

    nonblank = [index for index, line in enumerate(lines) if line.strip()]
    if not nonblank or lines[nonblank[0]].strip() != "# Completion Ledger":
        violations.append("ledger must begin with '# Completion Ledger'")
    else:
        allowed_lines.add(nonblank[0])

    table_starts: list[int] = []
    for index in range(len(lines) - 1):
        header = _table_cells(lines[index])
        separator = _table_cells(lines[index + 1])
        if header and _is_separator(separator):
            table_starts.append(index)

    if len(table_starts) != 1:
        violations.append(
            f"ledger must contain exactly one canonical table; found {len(table_starts)}"
        )

    if table_starts:
        index = table_starts[0]
        header = _table_cells(lines[index]) or []
        separator = _table_cells(lines[index + 1]) or []
        allowed_lines.update((index, index + 1))
        folded = tuple(cell.casefold() for cell in header)
        if folded != REQUIRED_COLUMNS:
            violations.append(
                "table columns must be exactly: ID | Remaining work | Why it matters | "
                "Status | Verification"
            )
        if len(separator) != len(header):
            violations.append("table separator must match the header column count")

        status_index = folded.index("status") if "status" in folded else None
        row_index = index + 2
        while row_index < len(lines):
            cells = _table_cells(lines[row_index])
            if not cells:
                break
            allowed_lines.add(row_index)
            row_count += 1
            if len(cells) != len(header):
                violations.append(
                    f"line {row_index + 1}: row has {len(cells)} cells; expected {len(header)}"
                )
            if folded == REQUIRED_COLUMNS and len(cells) == len(REQUIRED_COLUMNS):
                empty_columns = [
                    REQUIRED_COLUMNS[cell_index]
                    for cell_index, cell in enumerate(cells)
                    if not cell.strip()
                ]
                if empty_columns:
                    violations.append(
                        f"line {row_index + 1}: empty required fields: {', '.join(empty_columns)}"
                    )
                item_id = cells[0].casefold()
                if item_id in seen_ids:
                    violations.append(f"line {row_index + 1}: duplicate ID {cells[0]!r}")
                seen_ids.add(item_id)

            if status_index is None or status_index >= len(cells):
                violations.append(f"line {row_index + 1}: ledger row has no Status value")
                row_index += 1
                continue
            status = cells[status_index]
            classification = _classified_status(status)
            if classification == "terminal":
                violations.append(
                    f"line {row_index + 1}: terminal Status {status!r} must be removed"
                )
            elif classification == "active":
                active_items += 1
            else:
                violations.append(
                    f"line {row_index + 1}: unrecognized Status {status!r}; use an active status"
                )
            row_index += 1

    unexpected = [index + 1 for index in nonblank if index not in allowed_lines]
    if unexpected:
        rendered = ", ".join(str(line) for line in unexpected)
        violations.append(f"unexpected content outside the canonical heading/table at lines: {rendered}")

    if row_count == 0 or active_items == 0:
        violations.append("present ledger has no active items and must be deleted")

    return violations


def audit_ledger(path: Path) -> list[str]:
    if not path.exists():
        return []
    if not path.is_file():
        return [f"ledger path is not a file: {path}"]
    return find_ledger_violations(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    args = parser.parse_args()

    if not args.ledger.exists():
        print(f"completion ledger check ok (absent: {args.ledger})")
        return 0

    violations = audit_ledger(args.ledger)
    if violations:
        for violation in violations:
            print(f"completion ledger violation: {violation}")
        return 1

    print(f"completion ledger check ok (active-only: {args.ledger})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
