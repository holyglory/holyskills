#!/usr/bin/env python3
"""Recall and precision tests for the database-only completion-ledger guard."""

from __future__ import annotations

import importlib.util
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from shutil import rmtree


SCRIPT = Path(__file__).with_name("check_completion_ledger.py")
DELIVERY_STATE = SCRIPT.parents[1] / "skills" / "coordinate-product-delivery" / "scripts" / "delivery_state.py"
SPEC = importlib.util.spec_from_file_location("check_completion_ledger", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("unable to load completion-ledger checker")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    temporary = Path(tempfile.mkdtemp(prefix="completion-ledger-self-test-"))
    try:
        root = temporary.resolve()
        retired = root / "CompletionLedger.md"
        check(not MODULE.audit_legacy_ledger(retired), "absent Markdown ledger must pass")
        retired.write_text("# Completion Ledger\n", encoding="utf-8")
        check(MODULE.audit_legacy_ledger(retired), "any Markdown ledger file must fail")
        retired.unlink()
        retired.symlink_to(root / "missing")
        check(MODULE.audit_legacy_ledger(retired), "a broken Markdown ledger symlink must fail")
        retired.unlink()

        project = root / "repo"
        project.mkdir()
        subprocess.run(["git", "init", "-q", str(project)], check=True, timeout=10)
        initialized = subprocess.run(
            [sys.executable, str(DELIVERY_STATE), "--project", str(project), "init"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
        check(initialized.returncode == 0, f"database fixture must initialize: {initialized.stderr}")
        database = project / ".product-delivery" / "delivery.sqlite3"
        check(not MODULE.audit_database(database), "valid software-owned database must pass")

        with sqlite3.connect(database) as connection:
            connection.execute("DROP TRIGGER events_no_delete")
        missing_trigger = MODULE.audit_database(database)
        check(
            any("permanence triggers" in item for item in missing_trigger),
            "missing permanent-history trigger must fail",
        )

        invalid = root / "invalid.sqlite3"
        invalid.write_text("not sqlite", encoding="utf-8")
        check(MODULE.audit_database(invalid), "non-SQLite content must fail")

        print("completion ledger checker self-test ok")
        return 0
    finally:
        rmtree(temporary, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
