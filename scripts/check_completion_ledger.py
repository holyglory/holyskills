#!/usr/bin/env python3
"""Reject legacy Markdown ledgers and optionally verify the live database."""

from __future__ import annotations

import argparse
import sqlite3
import stat
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER = ROOT / "CompletionLedger.md"
REQUIRED_TABLES = {
    "metadata",
    "completion_issues",
    "completion_issue_tasks",
    "completion_imports",
    "events",
    "monitoring_schedules",
    "monitoring_runs",
}
REQUIRED_TRIGGERS = {
    "completion_issues_no_delete",
    "events_no_update",
    "events_no_delete",
    "monitoring_runs_no_delete",
}


def audit_legacy_ledger(path: Path) -> list[str]:
    """Require the retired Markdown ledger path to remain absent."""

    try:
        path.lstat()
    except FileNotFoundError:
        return []
    except OSError as error:
        return [f"could not inspect retired ledger path: {error}"]
    return [
        f"retired Markdown ledger exists: {path}; migrate it through the database interface and remove it"
    ]


def audit_database(path: Path) -> list[str]:
    """Verify the software-owned database without mutating it."""

    try:
        metadata = path.lstat()
    except OSError as error:
        return [f"could not inspect completion-ledger database: {error}"]
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        return [f"completion-ledger database must be a regular non-symlinked file: {path}"]
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            version = connection.execute(
                "SELECT value FROM metadata WHERE key = 'schema_version'"
            ).fetchone()
            tables = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            triggers = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger'"
                ).fetchall()
            }
            integrity = connection.execute("PRAGMA integrity_check(1)").fetchone()[0]
        finally:
            connection.close()
    except sqlite3.Error as error:
        return [f"completion-ledger database is unreadable or invalid: {error}"]
    violations: list[str] = []
    if version is None or version["value"] != "1":
        found = version["value"] if version is not None else "missing"
        violations.append(f"completion-ledger database schema is {found}; expected 1")
    missing_tables = sorted(REQUIRED_TABLES - tables)
    if missing_tables:
        violations.append("completion-ledger database is missing tables: " + ", ".join(missing_tables))
    missing_triggers = sorted(REQUIRED_TRIGGERS - triggers)
    if missing_triggers:
        violations.append("completion-ledger database is missing permanence triggers: " + ", ".join(missing_triggers))
    if integrity != "ok":
        violations.append(f"completion-ledger database integrity check failed: {integrity}")
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--database", type=Path)
    args = parser.parse_args(argv)
    violations = audit_legacy_ledger(args.ledger)
    if args.database is not None:
        violations.extend(audit_database(args.database))
    if violations:
        for violation in violations:
            print(f"completion ledger violation: {violation}")
        return 1
    suffix = f"; database verified: {args.database}" if args.database is not None else ""
    print(f"completion ledger check ok (Markdown absent{suffix})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
