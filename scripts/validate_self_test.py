#!/usr/bin/env python3
"""Prove the repository validation runner collects instead of short-circuiting."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("validate.py")
SPEC = importlib.util.spec_from_file_location("holyskills_validate", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("unable to load validation runner")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    saved = list(MODULE.FAILURES)
    MODULE.FAILURES.clear()
    try:
        with tempfile.TemporaryDirectory(prefix="validate-cycle-") as raw:
            marker = Path(raw) / "later-command-ran"
            first = MODULE.run([sys.executable, "-c", "raise SystemExit(3)"])
            later = MODULE.run(
                [
                    sys.executable,
                    "-c",
                    "from pathlib import Path; Path({!r}).write_text('ran', encoding='utf-8')".format(
                        str(marker)
                    ),
                ]
            )
            second = MODULE.run([sys.executable, "-c", "raise SystemExit(7)"])
            check(not first and later and not second, "command statuses were not retained")
            check(marker.read_text(encoding="utf-8") == "ran", "later command did not run")
            check(len(MODULE.FAILURES) == 2, "both command failures must be collected")

            MODULE.attempt("first in-process check", lambda: (_ for _ in ()).throw(ValueError("gap")))
            in_process_marker: list[str] = []
            MODULE.attempt("later in-process check", lambda: in_process_marker.append("ran"))
            check(in_process_marker == ["ran"], "later in-process check did not run")
            check(
                any("first in-process check" in failure for failure in MODULE.FAILURES),
                "in-process failure was not retained",
            )
    finally:
        MODULE.FAILURES[:] = saved

    print("validation runner self-test ok (failures collected; later checks executed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
