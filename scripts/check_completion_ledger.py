#!/usr/bin/env python3
"""Require CompletionLedger.md to contain active work only or be absent."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from full_repo_harness import completion_ledger  # noqa: E402


DEFAULT_LEDGER = ROOT / "CompletionLedger.md"


def find_ledger_violations(text: str) -> list[str]:
    """Return canonical-parser violations for one ledger snapshot."""

    try:
        completion_ledger.parse_ledger(text)
    except completion_ledger.LedgerError as exc:
        return [str(exc)]
    return []


def audit_ledger(path: Path) -> list[str]:
    """Read and validate a ledger without following supplied path symlinks."""

    try:
        text = completion_ledger.read_text_nofollow(path)
        if text is None:
            return []
        completion_ledger.parse_ledger(text)
    except (OSError, completion_ledger.LedgerError) as exc:
        return [str(exc)]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    args = parser.parse_args()

    violations = audit_ledger(args.ledger)
    if violations:
        for violation in violations:
            print(f"completion ledger violation: {violation}")
        return 1

    print(f"completion ledger check ok (active-only or absent: {args.ledger})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
