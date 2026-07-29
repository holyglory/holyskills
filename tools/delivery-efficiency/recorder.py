#!/usr/bin/env python3
"""Stable script entry point for an installed Holy Skills recorder runtime."""

from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from delivery_efficiency.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
