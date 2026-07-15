#!/usr/bin/env python3
"""Recall and false-positive tests for the active completion-ledger guard."""

from __future__ import annotations

import importlib.util
import os
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("check_completion_ledger.py")
SPEC = importlib.util.spec_from_file_location("check_completion_ledger", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("unable to load completion-ledger checker")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
LEDGER = MODULE.completion_ledger


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


def replace_first_status(status: str) -> str:
    return OPEN_TABLE.replace("| Open |", f"| {status} |", 1)


def main() -> int:
    check(not MODULE.find_ledger_violations(OPEN_TABLE), "active table must pass")

    for status in ("Resolved", "Completed", "Done", "Closed", "Implemented and verified"):
        check("terminal Status" in messages(replace_first_status(status)), f"{status} row must fail")

    mixed = OPEN_TABLE.replace("| Waiting |", "| Resolved |")
    check("terminal Status" in messages(mixed), "mixed active and terminal rows must fail")
    for status in (
        "Open / Resolved",
        "Blocked / Resolved",
        "Open — not complete / Resolved",
        "Open — not implemented, Resolved",
        "Open — not blocked but resolved",
        "Open — no remaining work and completed",
        "Open — task is not risky but implemented",
        "Open — requirement not relevant so resolved",
    ):
        check(
            "terminal Status" in messages(replace_first_status(status)),
            f"an active label must not hide terminal status {status!r}",
        )

    for status in (
        "Open — not implemented",
        "Open — not complete",
        "Open — not yet fully implemented",
        "Blocked — dependency not fixed",
        "Blocked — until the upstream issue is fixed and resolved",
        "Blocked — dependency must be fixed",
        "Blocked — CI down",
    ):
        check(
            not MODULE.find_ledger_violations(replace_first_status(status)),
            f"pending or negated terminal wording must remain active: {status!r}",
        )

    for status in ("Blocked", "**Blocked**", "____Blocked____", "Blocked — dependency"):
        check(
            "meaningful unblock condition" in messages(replace_first_status(status)),
            f"blocked row without a concrete condition must fail: {status!r}",
        )

    unknown = replace_first_status("Historical")
    check("unrecognized Status" in messages(unknown), "unknown status must fail closed")

    hidden_history = OPEN_TABLE + "\n## Resolved\n\n- Finished old task.\n"
    check(MODULE.find_ledger_violations(hidden_history), "terminal history outside the table must fail")

    wrong_schema = OPEN_TABLE.replace("Remaining work", "Requirement", 1)
    check("columns must be exactly" in messages(wrong_schema), "undocumented table schema must fail")
    lowercase_schema = OPEN_TABLE.replace(
        "| ID | Remaining work | Why it matters | Status | Verification |",
        "| id | remaining work | why it matters | status | verification |",
    )
    check(
        "columns must be exactly" in messages(lowercase_schema),
        "checker and canonical parser must reject a lowercase near-schema identically",
    )
    no_outer_pipes = OPEN_TABLE.replace(
        "| ID | Remaining work | Why it matters | Status | Verification |",
        "ID | Remaining work | Why it matters | Status | Verification",
    )
    check("begin and end" in messages(no_outer_pipes), "canonical rows require outer pipes")

    empty_table = """# Completion Ledger

| ID | Remaining work | Why it matters | Status | Verification |
| --- | --- | --- | --- | --- |
"""
    check(MODULE.find_ledger_violations(empty_table), "header-only ledger must fail")
    check(MODULE.find_ledger_violations("# Completion Ledger\n\n- [ ] Finish it.\n"), "checklist format must fail")
    check("duplicate" in messages(OPEN_TABLE.replace("| Q-2 |", "| Q-1 |")), "duplicate IDs must fail")

    canonical_error = messages(replace_first_status("Resolved"))
    try:
        LEDGER.parse_ledger(replace_first_status("Resolved"))
    except LEDGER.LedgerError as exc:
        check(canonical_error == str(exc), "checker must expose the canonical parser's exact error")
    else:
        raise AssertionError("canonical parser unexpectedly accepted terminal work")

    with tempfile.TemporaryDirectory(prefix="completion-ledger-self-test-") as temporary:
        root = Path(temporary).resolve()
        absent = root / "CompletionLedger.md"
        check(not MODULE.audit_ledger(absent), "absent ledger must pass")

        real = root / "real.md"
        real.write_text(OPEN_TABLE, encoding="utf-8")
        check(not MODULE.audit_ledger(real), "regular active ledger must pass")

        final_link = root / "linked.md"
        final_link.symlink_to(real)
        check("symlink" in "\n".join(MODULE.audit_ledger(final_link)), "final symlink must fail closed")

        real_dir = root / "real-dir"
        real_dir.mkdir()
        (real_dir / "ledger.md").write_text(OPEN_TABLE, encoding="utf-8")
        linked_dir = root / "linked-dir"
        linked_dir.symlink_to(real_dir, target_is_directory=True)
        check(
            "symlink" in "\n".join(MODULE.audit_ledger(linked_dir / "ledger.md")),
            "symlinked intermediate path component must fail closed",
        )
        traversal_messages = "\n".join(
            MODULE.audit_ledger(linked_dir / ".." / "real-dir" / "ledger.md")
        )
        check(
            "parent traversal" in traversal_messages,
            "parent traversal after a symlink component must fail before normalization",
        )

        raced_parent = root / "raced-parent"
        raced_parent.mkdir()
        raced_ledger = raced_parent / "ledger.md"
        raced_ledger.write_text(OPEN_TABLE, encoding="utf-8")
        moved_parent = root / "moved-raced-parent"
        original_read = LEDGER.os.read
        parent_replaced = False

        def read_after_parent_replacement(descriptor: int, size: int):
            nonlocal parent_replaced
            if not parent_replaced:
                parent_replaced = True
                raced_parent.rename(moved_parent)
                raced_parent.mkdir()
                raced_ledger.write_text("invalid replacement\n", encoding="utf-8")
            return original_read(descriptor, size)

        LEDGER.os.read = read_after_parent_replacement
        try:
            raced_messages = "\n".join(MODULE.audit_ledger(raced_ledger))
        finally:
            LEDGER.os.read = original_read
        check(
            "parent path changed" in raced_messages,
            "checker must reject a parent directory replaced during the ledger read",
        )

        fifo = root / "ledger.fifo"
        os.mkfifo(fifo)
        check("regular file" in "\n".join(MODULE.audit_ledger(fifo)), "non-regular ledger must fail")

        invalid_utf8 = root / "invalid.md"
        invalid_utf8.write_bytes(b"\xff\xfe")
        check("UTF-8" in "\n".join(MODULE.audit_ledger(invalid_utf8)), "invalid UTF-8 must fail")

    print("completion ledger checker self-test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
