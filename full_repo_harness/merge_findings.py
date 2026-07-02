#!/usr/bin/env python3
"""Merge findings across many audit batch/worker reports into one ranked list.

The audit skills dispatch one worker per deterministic file batch, so a large
repository produces dozens or hundreds of report files. The lead agent is then
expected to deduplicate and rank findings across all of them by hand, which does
not scale and is the step most likely to drop or double-count issues.

This tool does the mechanical part: it reads every ``*.md`` report in a reports
directory, extracts findings from any ``## ...Findings`` / ``## ...Gap`` section
(handling both the ``### P1 - title`` heading form used by full-repo-audit and
the ``- Priority: P1`` field-block form used by the UI and test-coverage
skills), deduplicates findings that share a primary file and near-identical
summary, ranks them P0 -> P3, and writes a consolidated JSON + Markdown digest.
It is deliberately conservative: it never invents severity and it preserves the
source report names so the lead can trace every merged finding back.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


SECTION_RE = re.compile(r"^##\s+(.+?)\s*$")
# A findings section is any H2 whose title mentions "finding" or "gap"
# (e.g. "Findings", "Implementation Gap Findings", "Coverage Findings",
# "File-Level Findings"). "No gap notes" is intentionally excluded below.
FINDINGS_SECTION_RE = re.compile(r"\b(finding|gap)s?\b", re.IGNORECASE)
HEADING_FINDING_RE = re.compile(r"^###\s+(P[0-3])\s*[-–—:]\s*(.+?)\s*$", re.IGNORECASE)
PRIORITY_FIELD_RE = re.compile(r"^-\s*Priority\s*:\s*(P[0-3])\b", re.IGNORECASE)
FIELD_RE = re.compile(r"^-\s*([^:]+?)\s*:\s*(.*)$")
PATH_IN_BACKTICKS_RE = re.compile(r"`([^`]+)`")
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
NO_FINDINGS_SENTINELS = {"no findings.", "no findings", "none.", "none"}


def section_blocks(text: str) -> dict[str, str]:
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        match = SECTION_RE.match(line.strip())
        if match:
            current = match.group(1).strip()
            blocks.setdefault(current, [])
            continue
        if current is not None:
            blocks[current].append(line)
    return {title: "\n".join(lines).strip() for title, lines in blocks.items()}


def is_findings_section(title: str) -> bool:
    lowered = title.lower()
    if "no gap" in lowered or "no finding" in lowered:
        return False
    return bool(FINDINGS_SECTION_RE.search(lowered))


def split_files(value: str) -> list[str]:
    refs = PATH_IN_BACKTICKS_RE.findall(value)
    if refs:
        candidates = refs
    else:
        candidates = re.split(r"[,;]", value)
    out: list[str] = []
    for candidate in candidates:
        cleaned = candidate.strip().strip("`").strip()
        if cleaned and cleaned.lower() not in {"none", "n/a", "not applicable"}:
            out.append(cleaned)
    return out


def parse_findings_from_section(body: str) -> list[dict]:
    """Parse both the heading form and the field-block form from one section."""
    lines = body.splitlines()
    findings: list[dict] = []
    current: dict | None = None

    def flush() -> None:
        nonlocal current
        if current is not None:
            findings.append(current)
            current = None

    for raw in lines:
        line = raw.rstrip()
        heading = HEADING_FINDING_RE.match(line.strip())
        if heading:
            flush()
            current = {"priority": heading.group(1).upper(), "summary": heading.group(2).strip(), "fields": {}}
            continue
        priority_field = PRIORITY_FIELD_RE.match(line.strip())
        if priority_field:
            # New field-block finding begins at each "- Priority:" line.
            flush()
            current = {"priority": priority_field.group(1).upper(), "summary": "", "fields": {}}
            continue
        field = FIELD_RE.match(line.strip())
        if field and current is not None:
            key = field.group(1).strip().lower()
            value = field.group(2).strip()
            current["fields"][key] = value
    flush()

    for finding in findings:
        fields = finding["fields"]
        if not finding["summary"]:
            finding["summary"] = (
                fields.get("gap")
                or fields.get("summary")
                or fields.get("evidence")
                or fields.get("missing scenarios/boundaries")
                or "(no summary)"
            )
        files = []
        for key in ("files", "docs/files", "file"):
            if fields.get(key):
                files = split_files(fields[key])
                break
        finding["files"] = files
        finding["evidence"] = fields.get("evidence") or fields.get("interface evidence") or ""
    return findings


def normalize_summary(summary: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", summary.lower()).strip()


def dedupe_key(finding: dict) -> tuple:
    primary_file = finding["files"][0] if finding["files"] else ""
    summary = normalize_summary(finding["summary"])
    return (primary_file, summary[:80])


def merge_findings(reports_dir: Path) -> dict:
    report_paths = sorted(p for p in reports_dir.glob("*.md") if p.is_file())
    merged: dict[tuple, dict] = {}
    total_raw = 0
    for report_path in report_paths:
        try:
            text = report_path.read_text(encoding="utf-8")
        except OSError:
            continue
        for title, body in section_blocks(text).items():
            if not is_findings_section(title):
                continue
            if body.strip().lower() in NO_FINDINGS_SENTINELS:
                continue
            for finding in parse_findings_from_section(body):
                total_raw += 1
                key = dedupe_key(finding)
                if key in merged:
                    entry = merged[key]
                    entry["sources"].append(report_path.name)
                    # Keep the most severe priority seen for a duplicated finding.
                    if PRIORITY_ORDER.get(finding["priority"], 9) < PRIORITY_ORDER.get(entry["priority"], 9):
                        entry["priority"] = finding["priority"]
                    for extra_file in finding["files"]:
                        if extra_file not in entry["files"]:
                            entry["files"].append(extra_file)
                else:
                    merged[key] = {
                        "priority": finding["priority"],
                        "summary": finding["summary"],
                        "files": list(finding["files"]),
                        "evidence": finding["evidence"],
                        "sources": [report_path.name],
                    }
    consolidated = sorted(
        merged.values(),
        key=lambda item: (PRIORITY_ORDER.get(item["priority"], 9), item["files"][0] if item["files"] else "", item["summary"]),
    )
    counts = {priority: 0 for priority in ("P0", "P1", "P2", "P3")}
    for item in consolidated:
        counts[item["priority"]] = counts.get(item["priority"], 0) + 1
    return {
        "reports_scanned": len(report_paths),
        "raw_findings": total_raw,
        "unique_findings": len(consolidated),
        "priority_counts": counts,
        "findings": consolidated,
    }


def render_markdown(result: dict) -> str:
    lines = ["# Consolidated Audit Findings", ""]
    counts = result["priority_counts"]
    lines.append(
        f"{result['unique_findings']} unique findings from {result['raw_findings']} raw findings "
        f"across {result['reports_scanned']} reports "
        f"(P0 {counts.get('P0', 0)}, P1 {counts.get('P1', 0)}, P2 {counts.get('P2', 0)}, P3 {counts.get('P3', 0)})."
    )
    lines.append("")
    current_priority: str | None = None
    for item in result["findings"]:
        if item["priority"] != current_priority:
            current_priority = item["priority"]
            lines.append(f"## {current_priority}")
            lines.append("")
        files = ", ".join(f"`{path}`" for path in item["files"]) or "_no file cited_"
        sources = ", ".join(sorted(set(item["sources"])))
        lines.append(f"- **{item['summary']}**")
        lines.append(f"  - Files: {files}")
        if item["evidence"]:
            lines.append(f"  - Evidence: {item['evidence']}")
        lines.append(f"  - Reported by: {sources}")
        lines.append("")
    if not result["findings"]:
        lines.append("_No findings reported across the scanned reports._")
        lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge and rank findings across audit reports.")
    parser.add_argument("--reports", required=True, help="Directory containing batch/worker *.md reports.")
    parser.add_argument("--json-out", help="Write the consolidated findings JSON here.")
    parser.add_argument("--markdown-out", help="Write the consolidated findings Markdown here.")
    parser.add_argument("--json", action="store_true", help="Print consolidated JSON to stdout.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    reports_dir = Path(args.reports)
    if not reports_dir.is_dir():
        print(f"reports directory not found: {reports_dir}", file=sys.stderr)
        return 2
    result = merge_findings(reports_dir)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.markdown_out:
        Path(args.markdown_out).write_text(render_markdown(result) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        counts = result["priority_counts"]
        print(
            f"{result['unique_findings']} unique findings from {result['raw_findings']} raw "
            f"across {result['reports_scanned']} reports "
            f"(P0 {counts.get('P0', 0)}, P1 {counts.get('P1', 0)}, P2 {counts.get('P2', 0)}, P3 {counts.get('P3', 0)})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
