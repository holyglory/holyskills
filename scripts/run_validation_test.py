#!/usr/bin/env python3
"""Run repository validation targets and publish one bounded coordinator case."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVENT_ENV = "DEVCOORDINATOR_TEST_EVENTS"


def event_path() -> Path:
    raw = os.environ.get(EVENT_ENV)
    if not raw:
        raise SystemExit(f"{EVENT_ENV} is required")
    path = Path(raw)
    if not path.is_absolute():
        raise SystemExit(f"{EVENT_ENV} must be absolute")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


def durable_temp_parent() -> Path:
    """Return a platform-local durable parent for recorder-aware tests."""

    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        if not local or not Path(local).is_absolute():
            raise RuntimeError("LOCALAPPDATA is required for durable validation temp")
        result = Path(local) / "HolySkills" / "ValidationTemp"
    else:
        result = Path("/var/tmp").resolve(strict=True) / "hsv"
    result.mkdir(mode=0o700, parents=True, exist_ok=True)
    return result.resolve(strict=True)


def run_command(argv: list[str]) -> subprocess.CompletedProcess:
    """Run one governed command while the coordinator captures the cold log."""

    temporary = Path(tempfile.mkdtemp(prefix="r-", dir=durable_temp_parent()))
    environment = dict(os.environ)
    environment.pop(EVENT_ENV, None)
    for name in ("TMPDIR", "TMP", "TEMP"):
        environment[name] = str(temporary)
    try:
        return subprocess.run(argv, cwd=ROOT, env=environment, check=False)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--formal-web-ui-verification",
        action="store_true",
        help="run only the formal web UI verifier self-test",
    )
    args = parser.parse_args(argv)
    output = event_path()
    if args.formal_web_ui_verification:
        command = [
            sys.executable,
            str(ROOT / "skills" / "formal-web-ui-verification" / "scripts" / "self_test.py"),
        ]
        case_id = "formal-web-ui-verification"
        name = "formal web UI verifier self-test"
    else:
        command = [sys.executable, str(ROOT / "scripts" / "validate.py")]
        case_id = "repository-validation"
        name = "repository validation"
    started = time.monotonic()
    completed = run_command(command)
    duration = max(0.0, time.monotonic() - started)
    payload: dict[str, object] = {
        "case_id": case_id,
        "name": name,
        "status": "passed" if completed.returncode == 0 else "failed",
        "duration_seconds": duration,
    }
    # On failure leave the injected report empty. The governed runner then
    # creates its process-exit case and attaches the complete captured output.
    if completed.returncode == 0:
        with output.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, sort_keys=True) + "\n")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
