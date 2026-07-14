#!/usr/bin/env python3
"""Recall and precision tests for the compact decision-history contract."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("check_decision_history.py")
SPEC = importlib.util.spec_from_file_location("check_decision_history", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("unable to load decision-history checker")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


VALID_INDEX = """# Decision History

Direction: Confirmed: primary content stays visible (D-20260714-02). Inferred: stable, truthful interfaces are the default (D-20260713-01).

## [D-20260714-02 — Stable collection interface](DecisionDetails/D-20260714-02.md)

Decision: Show the real collection before creation controls.

Why: Buried content made the named destination misleading. Options: selected collection-first over a leading creation form because it matches the user's destination. Prior attempts: the leading form caused the list to disappear below the first viewport. Intent: favor direct, content-first UI with stable context. Revisit only if: the destination's explicit primary task becomes creating one item.

## [D-20260713-01 — Truthful data contract](DecisionDetails/D-20260713-01.md)

Decision: Production interfaces display only real or explicitly unavailable data.

Why: Synthetic production content misstates system behavior. Options: no material alternative. Prior attempts: none known. Intent: preserve truthful, evidence-backed product behavior. Revisit only if: the user explicitly requests an isolated mockup or test fixture.
"""


def detail(decision_id: str, title: str) -> str:
    return (
        f"# {decision_id} — {title}\n\n"
        "Index: [DecisionHistory.md](../DecisionHistory.md)\n\n"
        "## Detail\n\nFull evidence, implementation, results, and sources.\n"
    )


def write_valid(root: Path) -> tuple[Path, Path]:
    index = root / "DecisionHistory.md"
    details = root / "DecisionDetails"
    details.mkdir()
    index.write_text(VALID_INDEX, encoding="utf-8")
    (details / "D-20260714-02.md").write_text(
        detail("D-20260714-02", "Stable collection interface"), encoding="utf-8"
    )
    (details / "D-20260713-01.md").write_text(
        detail("D-20260713-01", "Truthful data contract"), encoding="utf-8"
    )
    return index, details


def messages(index: Path, details: Path) -> str:
    return "\n".join(MODULE.audit_history(index, details))


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="decision-history-self-test-") as temporary:
        root = Path(temporary)
        index, details = write_valid(root)
        check(not MODULE.audit_history(index, details), "valid compact history must pass")

        verbose = VALID_INDEX.replace(
            "\n## [D-20260713-01",
            "\nResult: Implementation and verification details.\n\n## [D-20260713-01",
        )
        index.write_text(verbose, encoding="utf-8")
        check("exactly Decision and Why" in messages(index, details), "third Result paragraph must fail")

        index.write_text(VALID_INDEX.replace("Options: selected", "Options: considered"), encoding="utf-8")
        check("selected and rejected" in messages(index, details), "unselected options must fail")

        index.write_text(
            VALID_INDEX.replace(
                "Prior attempts: the leading form caused the list to disappear",
                "Prior attempts: a leading form was used",
            ),
            encoding="utf-8",
        )
        check("observed failure" in messages(index, details), "unexplained prior attempt must fail")

        index.write_text(
            VALID_INDEX.replace(
                "Revisit only if: the destination's explicit primary task becomes creating one item.",
                "Revisit only if: enough time passes and the failure is out of context.",
            ),
            encoding="utf-8",
        )
        check("time or context loss" in messages(index, details), "context-loss revisit must fail")

        index.write_text(VALID_INDEX.replace("Confirmed:", "Current:"), encoding="utf-8")
        check("Confirmed and Inferred" in messages(index, details), "unlabeled direction inference must fail")

        index.write_text(VALID_INDEX, encoding="utf-8")
        missing = details / "D-20260713-01.md"
        missing.unlink()
        check("missing detail file" in messages(index, details), "missing detail must fail")
        missing.write_text(detail("D-20260713-01", "Truthful data contract"), encoding="utf-8")

        orphan = details / "D-20260712-01.md"
        orphan.write_text(detail("D-20260712-01", "Orphan"), encoding="utf-8")
        check("orphan decision-detail" in messages(index, details), "orphan detail must fail")
        orphan.unlink()

        broken_detail = details / "D-20260713-01.md"
        original = broken_detail.read_text(encoding="utf-8")
        broken_detail.write_text(original.replace("Index:", "Source:"), encoding="utf-8")
        check("canonical index backlink" in messages(index, details), "missing backlink must fail")
        broken_detail.write_text(original, encoding="utf-8")

        traversal = VALID_INDEX.replace(
            "DecisionDetails/D-20260713-01.md",
            "DecisionDetails/../D-20260713-01.md",
        )
        index.write_text(traversal, encoding="utf-8")
        check("heading must link" in messages(index, details), "detail traversal must fail")

        index.write_text(VALID_INDEX, encoding="utf-8")
        target = details / "D-20260713-01.md"
        target.unlink()
        target.symlink_to(details / "D-20260714-02.md")
        check("unexpected decision-detail artifact" in messages(index, details), "detail symlink must fail")

    print("decision history checker self-test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
