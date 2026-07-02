#!/usr/bin/env python3
"""Self-test for the cross-report findings merge tool."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from full_repo_harness import merge_findings


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


# full-repo-audit heading form; shares a finding with batch_002 (same file + summary).
BATCH_1 = """## Run ID
run-1

## Batch ID
batch_001

## File-Level Findings
### P1 - Save button uses placeholder console-only behavior
- Files: `src/SaveButton.tsx`
- Evidence: onClick only calls console.log.
- Gap: no persistence.

### P2 - Minor copy inconsistency
- Files: `src/Header.tsx`
- Evidence: title casing differs.
- Gap: cosmetic.

## No Finding Notes
- other files fine.
"""

# UI field-block form; the SaveButton finding is a duplicate that should merge.
BATCH_2 = """## Run ID
run-1

## Batch ID
batch_002

## Implementation Gap Findings
- Priority: P1
- Files: `src/SaveButton.tsx`
- Interface evidence: Save changes button
- Gap: Save button uses placeholder console-only behavior
- Suggested implementation direction: wire the handler.

- Priority: P0
- Files: `src/auth/login.ts`
- Evidence: password compared with ==
- Gap: auth bypass risk
"""

BATCH_3 = """## Run ID
run-1

## Batch ID
batch_003

## Coverage Findings
No findings.
"""


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="merge-findings-self-test-"))
    try:
        reports = tmp / "reports"
        reports.mkdir()
        (reports / "batch_001.md").write_text(BATCH_1, encoding="utf-8")
        (reports / "batch_002.md").write_text(BATCH_2, encoding="utf-8")
        (reports / "batch_003.md").write_text(BATCH_3, encoding="utf-8")

        result = merge_findings.merge_findings(reports)

        check(result["reports_scanned"] == 3, f"expected 3 reports scanned, got {result['reports_scanned']}")
        check(result["raw_findings"] == 4, f"expected 4 raw findings, got {result['raw_findings']}")
        # SaveButton finding appears in two reports and must collapse to one.
        check(result["unique_findings"] == 3, f"expected 3 unique findings, got {result['unique_findings']}")

        by_summary = {normalize(item["summary"]): item for item in result["findings"]}
        save = next(item for item in result["findings"] if "src/SaveButton.tsx" in item["files"])
        check(sorted(set(save["sources"])) == ["batch_001.md", "batch_002.md"], f"SaveButton finding should cite both reports: {save['sources']}")
        check(save["priority"] == "P1", f"SaveButton merged priority should be P1: {save['priority']}")

        priorities = [item["priority"] for item in result["findings"]]
        check(priorities == sorted(priorities, key=lambda p: {"P0": 0, "P1": 1, "P2": 2, "P3": 3}[p]), f"findings must be ranked by priority: {priorities}")
        check(result["findings"][0]["priority"] == "P0", "most severe finding must sort first")
        check(result["priority_counts"] == {"P0": 1, "P1": 1, "P2": 1, "P3": 0}, f"unexpected counts: {result['priority_counts']}")

        markdown = merge_findings.render_markdown(result)
        check("## P0" in markdown and "auth bypass" in markdown.lower(), "markdown must render the P0 finding")
        check("`src/SaveButton.tsx`" in markdown, "markdown must cite merged finding files")

        print("merge-findings self-test ok")
        return 0
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


def normalize(value: str) -> str:
    return value.strip().lower()


if __name__ == "__main__":
    raise SystemExit(main())
