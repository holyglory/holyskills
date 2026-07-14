#!/usr/bin/env python3
"""Recall and false-positive tests for the active completion-ledger guard."""

from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("check_completion_ledger.py")
SPEC = importlib.util.spec_from_file_location("check_completion_ledger", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("unable to load completion-ledger checker")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


OPEN_TABLE = """# Completion Ledger

| ID | Remaining work | Why it matters | Status | Verification |
| --- | --- | --- | --- | --- |
| Q-1 | Finish the real integration. | Users need the real result. | Open | Prove the issue is resolved end to end. |
| Q-2 | Replace the temporary bridge. | The bridge is not maintainable. | Waiting | Rerun after the dependency returns. |
"""


def messages(text: str) -> str:
    return "\n".join(MODULE.find_ledger_violations(text))


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    check(not MODULE.find_ledger_violations(OPEN_TABLE), "active table must pass")

    for status in ("Resolved", "Completed", "Done", "Closed", "Implemented and verified"):
        terminal = OPEN_TABLE.replace("| Open |", f"| {status} |", 1)
        check("terminal Status" in messages(terminal), f"{status} row must fail")

    mixed = OPEN_TABLE.replace("| Waiting |", "| Resolved |")
    check("terminal Status" in messages(mixed), "mixed active and terminal rows must fail")

    contradictory_status = OPEN_TABLE.replace("| Open |", "| Open / Resolved |", 1)
    check(
        "terminal Status" in messages(contradictory_status),
        "an active label must not hide a terminal status",
    )

    unknown = OPEN_TABLE.replace("| Open |", "| Historical |", 1)
    check("unrecognized Status" in messages(unknown), "unknown status must fail closed")

    hidden_history = OPEN_TABLE + "\n## Resolved\n\n- Finished old task.\n"
    check(
        "unexpected content" in messages(hidden_history),
        "terminal history outside the table must fail",
    )

    wrong_schema = OPEN_TABLE.replace("Remaining work", "Requirement", 1)
    check("table columns" in messages(wrong_schema), "undocumented table schema must fail")

    empty_table = """# Completion Ledger

| ID | Remaining work | Why it matters | Status | Verification |
| --- | --- | --- | --- | --- |
"""
    check("no active items" in messages(empty_table), "header-only ledger must fail")

    unchecked = "# Completion Ledger\n\n- [ ] Finish the integration.\n"
    check("canonical table" in messages(unchecked), "checklist format must fail")

    checked = "# Completion Ledger\n\n- [x] Finished integration.\n"
    check("canonical table" in messages(checked), "checked history must fail")

    duplicate = OPEN_TABLE.replace("| Q-2 |", "| Q-1 |")
    check("duplicate ID" in messages(duplicate), "duplicate item IDs must fail")

    with tempfile.TemporaryDirectory(prefix="completion-ledger-self-test-") as temporary:
        absent = Path(temporary) / "CompletionLedger.md"
        check(not MODULE.audit_ledger(absent), "absent ledger must pass")

    print("completion ledger checker self-test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
