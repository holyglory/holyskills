#!/usr/bin/env python3
"""Complete portable-recorder self-test entry point used by CI and copied installs."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
TESTS = (
    ROOT / "delivery_efficiency" / "core_self_test.py",
    ROOT / "schema_self_test.py",
    ROOT / "codex_self_test.py",
    ROOT / "claude_self_test.py",
    ROOT / "installer_self_test.py",
    ROOT / "deferred_install_self_test.py",
    ROOT / "declarations_self_test.py",
    ROOT / "exec_runner_self_test.py",
    ROOT / "reporting_self_test.py",
    ROOT / "cli_self_test.py",
    ROOT / "runtime_self_test.py",
)


def platform_name() -> str:
    sys.path.insert(0, str(ROOT))
    from delivery_efficiency.platforms import detect_platform

    value = detect_platform()
    return "wsl" if value.environment == "wsl" else value.os


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-platform", choices=("windows", "linux", "macos", "wsl"))
    parser.add_argument("--require-loopback", action="store_true")
    args = parser.parse_args()
    actual = platform_name()
    if args.require_platform and args.require_platform != actual:
        raise SystemExit(
            "required platform {} but detected {}".format(args.require_platform, actual)
        )
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    for test in TESTS:
        if not test.is_file():
            raise SystemExit("missing recorder self-test: {}".format(test.name))
        print("+ {}".format(test.relative_to(ROOT)), flush=True)
        command = [sys.executable, str(test)]
        if args.require_loopback and test.name == "runtime_self_test.py":
            command.append("--require-loopback")
        subprocess.run(command, cwd=str(ROOT), env=environment, check=True)
    print("delivery-efficiency self-test ok ({})".format(actual))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
