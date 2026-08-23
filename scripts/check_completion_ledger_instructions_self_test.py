#!/usr/bin/env python3
"""Recall and precision tests for database-only ledger instructions."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).with_name("check_completion_ledger_instructions.py")
SPEC = importlib.util.spec_from_file_location("check_completion_ledger_instructions", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("unable to load completion-ledger instruction checker")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def must_fail(text: str, needle: str) -> None:
    violations = MODULE.find_text_violations(text, "fixture.md")
    check(any(needle in item for item in violations), f"expected {needle!r}: {violations}")


def main() -> int:
    must_fail(
        "Maintain project-root `CompletionLedger.md` with unresolved rows.\n",
        "without an explicit prohibition",
    )
    must_fail(
        "Create the completion ledger here:\n`CompletionLedger.md`\n",
        "without an explicit prohibition",
    )
    must_fail(
        "Write completion-ledger-plan.json before applying findings to the database.\n",
        "completion-ledger-plan.json",
    )
    must_fail(
        "Use an open-only completion-ledger for routine work.\n",
        "open-only completion-ledger",
    )
    must_fail(
        "Record every incomplete outcome in the Completion Ledger.\n",
        "do not name the database authority",
    )

    passing = (
        "The software-owned database Completion Ledger retains permanent history. "
        "Never create or update `CompletionLedger.md`; there is no file fallback.\n"
    )
    check(not MODULE.find_text_violations(passing, "passing.md"), "database-only instruction must pass")
    historical_correction = (
        "The mistake created `CompletionLedger.md`; no workflow may create, update, or fall back "
        "to it because the database is authoritative.\n"
    )
    check(
        not MODULE.find_text_violations(historical_correction, "ledger.md"),
        "a durable negative correction must pass",
    )

    print("completion ledger instruction checker self-test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
