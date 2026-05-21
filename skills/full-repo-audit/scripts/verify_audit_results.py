#!/usr/bin/env python3
"""Verify subagent file-coverage reports against a full-repo-audit manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath


BATCH_ID_RE = re.compile(r"\bbatch_(\d{3,})\b", re.IGNORECASE)
REPORT_FILENAME_RE = re.compile(r"^batch_\d{3,}\.md$", re.IGNORECASE)
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
SECTION_RE = re.compile(r"^##\s+(.+?)\s*$")
MARKDOWN_UNSAFE_PATH_CHARS = {"|", "`"}
REQUIRED_SECTIONS = (
    "run id",
    "batch id",
    "batch summary",
    "file coverage",
    "interface inventory",
    "findings",
    "no finding notes",
    "open questions",
)
REQUIRED_SECTION_LIST = list(REQUIRED_SECTIONS)
JOURNEY_REPORT_SECTIONS = {
    "journey_source_worker": (
        "run id",
        "worker",
        "journey sources",
        "proposed journeys",
        "ui source journey checks",
        "findings",
        "open questions",
    ),
    "visual_journey_worker": (
        "run id",
        "worker",
        "visual tooling",
        "visual journey checks",
        "findings",
        "open questions",
    ),
}
JOURNEY_WORKER_LABELS = {
    "journey_source_worker": "journey_source",
    "visual_journey_worker": "visual_journey",
}
JOURNEY_PROMPT_FIELDS = {
    "journey_source_worker": "source_prompt",
    "visual_journey_worker": "visual_prompt",
}
JOURNEY_REPORT_FIELDS = {
    "journey_source_worker": "source_report",
    "visual_journey_worker": "visual_report",
}
SOURCE_JOURNEY_TABLE_HEADERS = {
    "journey",
    "step",
    "files",
    "primary navigation/decision elements",
    "relevance estimate",
    "required information",
    "mobile/desktop availability",
    "test mode evidence",
}
VISUAL_JOURNEY_TABLE_HEADERS = {
    "journey",
    "viewport",
    "route/screen",
    "evidence",
    "navigation visibility",
    "decision information",
    "visual quality",
    "result",
}
ALLOWED_RELEVANCE_VALUES = {
    "critical-always",
    "primary-frequent",
    "secondary-occasional",
    "rare-under-5-percent",
}
ALLOWED_PRUNED_REVIEW_DECISIONS = {
    "excluded-with-rationale",
    "out-of-scope-with-user-confirmation",
    "requeued",
}
FINDING_HEADING_RE = re.compile(r"^###\s+P[0-3]\s+-\s+\S", re.IGNORECASE)
FINDING_FIELD_RE = re.compile(r"^-\s*([^:]+):")
REQUIRED_FINDING_FIELDS = {
    "files",
    "evidence",
    "interface evidence",
    "expected behavior/standard",
    "gap",
    "suggested direction",
}
PATH_IN_BACKTICKS_RE = re.compile(r"`([^`]+)`")
PLACEHOLDER_COMMENT_RE = re.compile(
    r"(?:#|//|/\*|<!--)\s*(?:TODO|FIXME|XXX)\b",
    re.IGNORECASE,
)
CODE_STUB_RE = re.compile(
    r"\b(?:throw|raise)\s+(?:new\s+)?(?:NotImplemented(?:Error|Exception)\b|"
    r"(?:Error|Exception)\s*\(\s*['\"](?:TODO|FIXME|not implemented|placeholder|stub)\b|"
    r"['\"]?(?:TODO|FIXME|not implemented|placeholder|stub)\b)"
    r"|\bpanic!\s*\(\s*['\"](?:TODO|FIXME|not implemented|placeholder|stub)\b"
    r"|\b(?:todo|unimplemented)!\s*\(",
    re.IGNORECASE,
)
CONSOLE_LOG_RE = re.compile(r"console\.(?:log|warn|error)\s*\([^)\n]*\)", re.IGNORECASE)
UI_CODE_EXTENSIONS = {".astro", ".jsx", ".mdx", ".svelte", ".tsx", ".vue"}
CODE_STUB_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".dart",
    ".go",
    ".h",
    ".hpp",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".mjs",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".scala",
    ".swift",
    ".ts",
    ".tsx",
}
MESSAGE_CATALOG_HINT_EXTENSIONS = {
    ".arb",
    ".ftl",
    ".json",
    ".po",
    ".pot",
    ".properties",
    ".resx",
    ".strings",
    ".xlf",
    ".xliff",
}
VISIBLE_JSON_KEY_TOKENS = {
    "action",
    "aria",
    "banner",
    "button",
    "cancel",
    "caption",
    "close",
    "confirm",
    "continue",
    "copy",
    "create",
    "cta",
    "delete",
    "description",
    "empty",
    "error",
    "heading",
    "help",
    "hint",
    "label",
    "loading",
    "login",
    "logout",
    "message",
    "name",
    "next",
    "notice",
    "ok",
    "placeholder",
    "previous",
    "remove",
    "save",
    "search",
    "submit",
    "success",
    "subtitle",
    "text",
    "title",
    "toast",
    "tooltip",
    "update",
    "warning",
    "welcome",
}
INTERNAL_JSON_KEY_TOKENS = {
    "analytics",
    "api",
    "class",
    "classname",
    "code",
    "debug",
    "endpoint",
    "feature",
    "flag",
    "href",
    "icon",
    "id",
    "key",
    "metadata",
    "permission",
    "route",
    "slug",
    "style",
    "telemetry",
    "token",
    "url",
}
VISIBLE_HINT_EXTENSIONS = {
    ".arb",
    ".astro",
    ".axaml",
    ".cshtml",
    ".ejs",
    ".ftl",
    ".hbs",
    ".handlebars",
    ".html",
    ".j2",
    ".jinja",
    ".jinja2",
    ".json",
    ".jsx",
    ".liquid",
    ".md",
    ".mdx",
    ".mustache",
    ".njk",
    ".po",
    ".pot",
    ".properties",
    ".pug",
    ".razor",
    ".resx",
    ".strings",
    ".svelte",
    ".svg",
    ".storyboard",
    ".tpl",
    ".tsx",
    ".twig",
    ".vue",
    ".xaml",
    ".xib",
    ".xml",
    ".xlf",
    ".xliff",
    ".yaml",
    ".yml",
}
GENERIC_PURPOSE_VALUES = {
    "component",
    "config",
    "config file",
    "file",
    "fixture source",
    "message catalog",
    "misc",
    "script",
    "source",
    "source file",
    "test",
    "test file",
    "utility",
}
DIRECTORY_ONLY_PURPOSE_RE = re.compile(
    r"\b(?:files?|sources?|items?|entries|everything)\s+(?:under|in|from|inside)\b"
    r"|\b(?:directory|folder)\s+(?:of|for|under|inside|containing)\b",
    re.IGNORECASE,
)
SIMPLE_KEY_VALUE_RE = re.compile(r"(?m)^\s*[-A-Za-z0-9_.]+\s*[:=]\s*['\"]?([^'\"\n#{}\[\]]{2,100})['\"]?\s*$")
MARKDOWN_H1_RE = re.compile(r"(?m)^#\s+(.{2,100})\s*$")
PROPERTIES_VALUE_RE = re.compile(r"(?m)^\s*[^#!\s][^:=\n]*[:=]\s*([^\n#]{2,100})\s*$")
PO_VALUE_RE = re.compile(r'(?m)^\s*msg(?:id|str)\s+"([^"]{2,100})"\s*$')
APPLE_STRINGS_VALUE_RE = re.compile(r'(?m)=\s*"([^"]{2,100})"\s*;')
FTL_VALUE_RE = re.compile(r"(?m)^\s*[-A-Za-z0-9_.]+\s*=\s*([^\n{#]{2,100})\s*$")
NO_FINDINGS_SENTINELS = {"no findings", "no confirmed findings"}
BOILERPLATE_VALUES = {
    "concrete evidence",
    "exact visible text",
    "fixture expected path",
    "fixture implementation note",
    "fixture report",
    "fixture visible text",
    "implemented",
    "n/a",
    "none",
    "not applicable",
    "todo",
}
GENERIC_INTERFACE_PHRASES = (
    "trace `",
    "source text was inspected",
    "handler/state/api/persistence/verification expected",
    "implemented/missing behavior evidence",
)
VISIBLE_KEY_RE = re.compile(
    r"(?im)^\s*(display_name|short_description|default_prompt|label|title|placeholder|description|tooltip|helper_text|empty_state|error_message|success_message)\s*:\s*['\"]?([^'\"\n#]+)['\"]?"
)
VISIBLE_ATTR_RE = re.compile(
    r"""(?ix)
    \b(?:aria-label|title|placeholder|alt|label|content|android:text|text)\s*=\s*
    (?:"([^"]{2,100})"|'([^']{2,100})')
    """
)
VISIBLE_TEXT_RE = re.compile(r">\s*([^<>{}\n][^<>{}]{1,100}?)\s*<")
EMPTY_HANDLER_RE = re.compile(
    r"\bon[A-Z][A-Za-z]*\s*=\s*{\s*(?:\(\s*\)\s*=>\s*\{\s*\}|function\s*\([^)]*\)\s*\{\s*\})\s*}",
    re.DOTALL,
)
NOOP_FUNCTION_RE = re.compile(
    r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>\s*\{\s*\}"
    r"|\bfunction\s+([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{\s*\}",
    re.DOTALL,
)
EVENT_HANDLER_REF_RE = re.compile(r"\bon[A-Z][A-Za-z]*\s*=\s*{\s*([A-Za-z_$][\w$]*)\s*}")
DEAD_HREF_RE = re.compile(r"""(?is)<a\b[^>]*\bhref\s*=\s*(?:["']#["']|{\s*["']#["']\s*})[^>]*>""")
BUTTON_TAG_RE = re.compile(r"(?is)<button\b(.*?)>(.*?)</button>")
SELF_CLOSING_BUTTON_RE = re.compile(r"(?is)<button\b(.*?)/>")
COMPONENT_BUTTON_TAG_RE = re.compile(r"(?is)<[A-Z][A-Za-z0-9_.]*Button\b(.*?)>(.*?)</[A-Z][A-Za-z0-9_.]*Button>")
SELF_CLOSING_COMPONENT_BUTTON_RE = re.compile(r"(?is)<[A-Z][A-Za-z0-9_.]*Button\b(.*?)/>")
DISABLED_ATTR_PATTERN = r"""(?<![\w:-])disabled(?![\w:-])(?:\s*=\s*(?:{\s*true\s*}|["']disabled["']|["']true["']))?"""
DISABLED_ATTR_RE = re.compile(DISABLED_ATTR_PATTERN, re.IGNORECASE)
STATIC_DISABLED_CONTROL_RE = re.compile(
    rf"(?is)<(?:button|a|[A-Z][A-Za-z0-9_.]*Button)\b[^>]*{DISABLED_ATTR_PATTERN}[^>]*>"
)
ROLE_BUTTON_RE = re.compile(r"""(?is)<([A-Za-z][\w:.-]*)\b([^>]*)\brole\s*=\s*(?:"button"|'button'|{\s*["']button["']\s*})([^>]*)>(.*?)</\1>""")
FORM_FIELD_TAG_RE = re.compile(r"(?is)<(input|select|textarea)\b([^>]*)>(.*?)</\1>|<(input)\b([^>]*)/?>")
FORM_TAG_RE = re.compile(r"(?is)<form\b([^>]*)>")
FORM_SUBMIT_ATTR_RE = re.compile(
    r"(?is)(?<![\w:-])(?:action|onsubmit|onSubmit|@submit|v-on:submit|on:submit|\(submit\))\s*="
)
ROLE_INTERACTIVE_RE = re.compile(
    r"""(?is)<([A-Za-z][\w:.-]*)\b([^>]*)\brole\s*=\s*(?:"(?:checkbox|menuitem|switch|tab)"|'(?:checkbox|menuitem|switch|tab)'|{\s*["'](?:checkbox|menuitem|switch|tab)["']\s*})([^>]*)>(.*?)</\1>"""
)
INTERACTIVE_HINT_EXTENSIONS = {
    ".axaml",
    ".astro",
    ".cshtml",
    ".cts",
    ".ejs",
    ".handlebars",
    ".hbs",
    ".html",
    ".j2",
    ".jinja",
    ".jinja2",
    ".js",
    ".jsx",
    ".liquid",
    ".mjs",
    ".mdx",
    ".mts",
    ".mustache",
    ".njk",
    ".pug",
    ".razor",
    ".svelte",
    ".storyboard",
    ".tpl",
    ".ts",
    ".tsx",
    ".twig",
    ".vue",
    ".xaml",
    ".xib",
    ".xml",
}
NATIVE_DISABLED_CONTROL_RE = re.compile(
    r"""(?is)<(?:Button|button|[A-Za-z:]+Button)\b[^>]*\b(?:IsEnabled|isEnabled|enabled|android:enabled)\s*=\s*(?:"false"|'false'|{\s*false\s*})[^>]*>"""
)
ASSET_EVIDENCE_TERMS = (
    "asset",
    "dimension",
    "height",
    "image/",
    "mime",
    "referenc",
    "render",
    "usage",
    "visual",
    "width",
)
ASSET_MIME_BY_SUFFIX = {
    ".gif": "image/gif",
    ".ico": "image/x-icon",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".eot": "application/vnd.ms-fontobject",
}
ASSET_METADATA_READ_LIMIT = 512 * 1024
SVG_ROOT_RE = re.compile(r"<svg\b(?P<attrs>[^>]*)>", re.IGNORECASE)
SVG_ATTR_RE = re.compile(r"([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*(['\"])(.*?)\2", re.DOTALL)
SVG_NUMBER_RE = re.compile(r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))")
VISUAL_EVIDENCE_TOOL_TERMS = (
    "browser",
    "command",
    "cypress",
    "mcp",
    "npx",
    "npm",
    "playwright",
    "pnpm",
    "ran",
    "storybook",
    "yarn",
)
VISUAL_EVIDENCE_ARTIFACT_TERMS = (
    ".jpeg",
    ".jpg",
    ".png",
    "artifact",
    "playwright-report",
    "recording",
    "screenshot",
    "trace",
    "video",
)
WEB_UI_EXTENSIONS = {".astro", ".css", ".html", ".jsx", ".mdx", ".scss", ".svelte", ".tsx", ".vue"}
VISUAL_DANGER_RE = re.compile(
    r"\b(overloaded?|crowded|cramped|unreadable|invisible|low[- ]contrast|clipped|cropped|truncated|"
    r"overflow|hidden overflow|no scroll|without scroll|unscannable|ambiguous hierarchy|oversized|"
    r"excessive detail|debug detail|raw status|dominates|dominating|buried|below the fold)\b",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare subagent Markdown File Coverage tables to a full-repo-audit manifest."
    )
    parser.add_argument("--manifest", required=True, help="Path to manifest.json from build_audit_batches.py.")
    parser.add_argument(
        "--reports",
        required=True,
        nargs="+",
        help="One or more Markdown report files or directories containing reports.",
    )
    parser.add_argument(
        "--skip-current-hash-check",
        action="store_true",
        help="Do not compare manifest SHA-256 fingerprints to the current repo files.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser.parse_args()


def iter_report_files(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve()
        if path.is_dir():
            files.extend(
                sorted(
                    item
                    for item in path.glob("batch_*.md")
                    if item.is_file() and REPORT_FILENAME_RE.match(item.name)
                )
            )
        elif path.is_file():
            if not REPORT_FILENAME_RE.match(path.name):
                raise ValueError(f"Report file must use exact batch_###.md filename: {path}")
            files.append(path)
        else:
            raise FileNotFoundError(f"Report path does not exist: {path}")
    return files


def validate_markdown_safe_manifest_token(value: str, field_name: str) -> None:
    if value != value.strip():
        raise ValueError(f"Manifest {field_name} must not have leading or trailing whitespace.")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"Manifest {field_name} must not contain ASCII control characters.")
    unsafe = sorted(char for char in MARKDOWN_UNSAFE_PATH_CHARS if char in value)
    if unsafe:
        raise ValueError(f"Manifest {field_name} must not contain Markdown table/code delimiters: {unsafe}.")


def validate_repo_relative_path(value: str, field_name: str) -> None:
    validate_markdown_safe_manifest_token(value, field_name)
    if "\\" in value:
        raise ValueError(f"Manifest {field_name} must use POSIX repo-relative paths.")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"Manifest {field_name} must be a repo-relative path without '.' or '..' segments.")


def duplicate_values(values: list[str]) -> list[str]:
    counts = Counter(values)
    return sorted(value for value, count in counts.items() if count > 1)


def validate_manifest_count(manifest: dict, field_name: str, expected: int) -> None:
    actual = manifest.get(field_name)
    if not isinstance(actual, int) or isinstance(actual, bool):
        raise ValueError(f"Manifest {field_name} must be an integer; actual: {actual}")
    if actual != expected:
        raise ValueError(f"Manifest {field_name} must equal {expected}; actual: {actual}")


def load_manifest(manifest_path: Path) -> dict:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Manifest is not valid JSON: {manifest_path}") from exc
    if not isinstance(manifest, dict):
        raise ValueError("Manifest must be a JSON object.")

    source_files = manifest.get("source_files")
    if not isinstance(source_files, list):
        raise ValueError("Manifest field source_files must be a list.")
    source_paths: list[str] = []
    for index, item in enumerate(source_files):
        if not isinstance(item, dict):
            raise ValueError(f"Manifest source_files[{index}] must be an object.")
        if not isinstance(item.get("rel_path"), str) or not item["rel_path"]:
            raise ValueError(f"Manifest source_files[{index}].rel_path must be a non-empty string.")
        validate_repo_relative_path(item["rel_path"], f"source_files[{index}].rel_path")
        source_paths.append(item["rel_path"])
        if "sha256" in item and item["sha256"] is not None:
            if not isinstance(item["sha256"], str):
                raise ValueError(f"Manifest source_files[{index}].sha256 must be a string when present.")
            if not SHA256_RE.match(item["sha256"]):
                raise ValueError(f"Manifest source_files[{index}].sha256 must be a 64-character SHA-256 hex digest.")
    duplicate_source_paths = duplicate_values(source_paths)
    if duplicate_source_paths:
        raise ValueError(f"Manifest source_files rel_path values must be unique; duplicates: {duplicate_source_paths}")
    source_path_set = set(source_paths)
    source_hash_by_path = {
        item["rel_path"]: item.get("sha256")
        for item in source_files
        if isinstance(item, dict)
    }

    raw_coverage_units = manifest.get("coverage_units")
    if raw_coverage_units is None:
        coverage_units = [
            {
                "unit_id": item["rel_path"],
                "rel_path": item["rel_path"],
                "sha256": item.get("sha256"),
                "start_line": None,
                "end_line": None,
            }
            for item in source_files
        ]
    else:
        if not isinstance(raw_coverage_units, list):
            raise ValueError("Manifest field coverage_units must be a list when present.")
        coverage_units = raw_coverage_units
    coverage_unit_ids: list[str] = []
    coverage_unit_paths: list[str] = []
    for index, unit in enumerate(coverage_units):
        if not isinstance(unit, dict):
            raise ValueError(f"Manifest coverage_units[{index}] must be an object.")
        if not isinstance(unit.get("unit_id"), str) or not unit["unit_id"]:
            raise ValueError(f"Manifest coverage_units[{index}].unit_id must be a non-empty string.")
        if not isinstance(unit.get("rel_path"), str) or not unit["rel_path"]:
            raise ValueError(f"Manifest coverage_units[{index}].rel_path must be a non-empty string.")
        validate_markdown_safe_manifest_token(unit["unit_id"], f"coverage_units[{index}].unit_id")
        validate_repo_relative_path(unit["rel_path"], f"coverage_units[{index}].rel_path")
        if unit["rel_path"] not in source_path_set:
            raise ValueError(f"Manifest coverage_units[{index}].rel_path is absent from source_files: {unit['rel_path']}")
        if "sha256" in unit and unit["sha256"] is not None:
            if not isinstance(unit["sha256"], str):
                raise ValueError(f"Manifest coverage_units[{index}].sha256 must be a string when present.")
            if not SHA256_RE.match(unit["sha256"]):
                raise ValueError(f"Manifest coverage_units[{index}].sha256 must be a 64-character SHA-256 hex digest.")
        start_line = unit.get("start_line")
        end_line = unit.get("end_line")
        start_byte = unit.get("start_byte")
        end_byte = unit.get("end_byte")
        has_line_range = start_line is not None or end_line is not None
        has_byte_range = start_byte is not None or end_byte is not None
        if has_line_range and has_byte_range:
            raise ValueError(f"Manifest coverage_units[{index}] must not mix line and byte ranges.")
        if has_line_range:
            if (
                not isinstance(start_line, int)
                or isinstance(start_line, bool)
                or not isinstance(end_line, int)
                or isinstance(end_line, bool)
                or start_line < 1
                or end_line < start_line
            ):
                raise ValueError(f"Manifest coverage_units[{index}] line range must use positive start_line/end_line integers.")
        if has_byte_range:
            if (
                not isinstance(start_byte, int)
                or isinstance(start_byte, bool)
                or not isinstance(end_byte, int)
                or isinstance(end_byte, bool)
                or start_byte < 1
                or end_byte < start_byte
            ):
                raise ValueError(f"Manifest coverage_units[{index}] byte range must use positive start_byte/end_byte integers.")
        coverage_unit_ids.append(unit["unit_id"])
        coverage_unit_paths.append(unit["rel_path"])
    duplicate_unit_ids = duplicate_values(coverage_unit_ids)
    if duplicate_unit_ids:
        raise ValueError(f"Manifest coverage_units unit_id values must be unique; duplicates: {duplicate_unit_ids}")

    batches = manifest.get("batches")
    if not isinstance(batches, list):
        raise ValueError("Manifest field batches must be a list.")
    batch_ids: list[str] = []
    assigned_paths: list[str] = []
    assigned_units: list[str] = []
    coverage_unit_set = set(coverage_unit_ids)
    for index, batch in enumerate(batches):
        if not isinstance(batch, dict):
            raise ValueError(f"Manifest batches[{index}] must be an object.")
        if not isinstance(batch.get("id"), str) or not batch["id"]:
            raise ValueError(f"Manifest batches[{index}].id must be a non-empty string.")
        batch_ids.append(batch["id"])
        files = batch.get("files")
        if not isinstance(files, list) or not all(isinstance(item, str) for item in files):
            raise ValueError(f"Manifest batches[{index}].files must be a list of strings.")
        for file_index, rel_path in enumerate(files):
            validate_repo_relative_path(rel_path, f"batches[{index}].files[{file_index}]")
        duplicate_batch_files = duplicate_values(files)
        if duplicate_batch_files:
            raise ValueError(
                f"Manifest batches[{index}].files must not contain duplicates: {duplicate_batch_files}"
            )
        assigned_paths.extend(files)
        batch_units = batch.get("coverage_units")
        if batch_units is None:
            batch_units = files
        if not isinstance(batch_units, list) or not all(isinstance(item, str) for item in batch_units):
            raise ValueError(f"Manifest batches[{index}].coverage_units must be a list of strings when present.")
        for unit_index, unit_id in enumerate(batch_units):
            validate_markdown_safe_manifest_token(unit_id, f"batches[{index}].coverage_units[{unit_index}]")
        duplicate_batch_units = duplicate_values(batch_units)
        if duplicate_batch_units:
            raise ValueError(
                f"Manifest batches[{index}].coverage_units must not contain duplicates: {duplicate_batch_units}"
            )
        assigned_units.extend(batch_units)
    duplicate_batch_ids = duplicate_values(batch_ids)
    if duplicate_batch_ids:
        raise ValueError(f"Manifest batch ids must be unique; duplicates: {duplicate_batch_ids}")
    assigned_path_set = set(assigned_paths)
    unknown_assigned = sorted(assigned_path_set - source_path_set)
    unassigned = sorted(source_path_set - assigned_path_set)
    assigned_unit_set = set(assigned_units)
    unknown_assigned_units = sorted(assigned_unit_set - coverage_unit_set)
    unassigned_units = sorted(coverage_unit_set - assigned_unit_set)
    duplicate_assignments = duplicate_values(assigned_units)
    if unknown_assigned:
        raise ValueError(f"Manifest batches reference files absent from source_files: {unknown_assigned}")
    if unassigned:
        raise ValueError(f"Manifest source_files are not assigned to a batch: {unassigned}")
    if unknown_assigned_units:
        raise ValueError(f"Manifest batches reference coverage units absent from coverage_units: {unknown_assigned_units}")
    if unassigned_units:
        raise ValueError(f"Manifest coverage_units are not assigned to a batch: {unassigned_units}")
    if duplicate_assignments:
        raise ValueError(f"Manifest batch coverage unit assignments must be unique: {duplicate_assignments}")
    scope_warnings = manifest.get("scope_warnings", [])
    if not isinstance(scope_warnings, list):
        raise ValueError("Manifest field scope_warnings must be a list when present.")
    pruned_hints = manifest.get("pruned_directory_review_hints", [])
    if not isinstance(pruned_hints, list):
        raise ValueError("Manifest field pruned_directory_review_hints must be a list when present.")
    journey_audit = manifest.get("journey_audit")
    if journey_audit is not None and not isinstance(journey_audit, dict):
        raise ValueError("Manifest field journey_audit must be an object when present.")

    validate_manifest_count(manifest, "source_file_count", len(source_files))
    if "coverage_unit_count" in manifest:
        validate_manifest_count(manifest, "coverage_unit_count", len(coverage_units))
    validate_manifest_count(manifest, "batch_count", len(batches))
    validate_manifest_count(
        manifest,
        "interface_file_count",
        sum(1 for item in source_files if isinstance(item, dict) and item.get("interface_relevant") is True),
    )
    validate_manifest_count(manifest, "scope_warning_count", len(scope_warnings))
    validate_manifest_count(manifest, "pruned_directory_review_hint_count", len(pruned_hints))

    manifest["expected_files"] = {item["rel_path"] for item in manifest.get("source_files", [])}
    manifest["expected_hashes"] = {
        unit["unit_id"]: unit.get("sha256") or source_hash_by_path.get(unit["rel_path"])
        for unit in coverage_units
    }
    manifest["expected_unit_to_file"] = {unit["unit_id"]: unit["rel_path"] for unit in coverage_units}
    manifest["coverage_units_normalized"] = coverage_units
    manifest["expected_by_batch"] = {
        batch["id"]: set(batch.get("coverage_units") or batch.get("files", [])) for batch in manifest.get("batches", [])
    }
    manifest["expected_files_by_batch"] = {
        batch["id"]: {
            (manifest["expected_unit_to_file"].get(unit_id, unit_id))
            for unit_id in (batch.get("coverage_units") or batch.get("files", []))
        }
        for batch in manifest.get("batches", [])
    }
    return manifest


def verify_completion_marker(manifest_path: Path, manifest: dict) -> list[dict]:
    marker_path = manifest_path.parent / "queue_complete.json"
    if not marker_path.is_file():
        return [{"path": str(marker_path), "reason": "queue_complete.json is missing"}]
    legacy_marker_path = manifest_path.parent / "audit_complete.json"
    if legacy_marker_path.is_file():
        return [
            {
                "path": str(legacy_marker_path),
                "reason": "legacy audit_complete.json must not be used as a queue or verification marker",
            }
        ]
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return [{"path": str(marker_path), "reason": f"{marker_path.name} is not valid JSON"}]
    if not isinstance(marker, dict):
        return [{"path": str(marker_path), "reason": f"{marker_path.name} must be a JSON object"}]

    mismatches: list[dict] = []
    expected = {
        "run_id": manifest.get("run_id"),
        "phase": "queue_generated",
        "audit_verified": False,
        "batch_count": manifest.get("batch_count"),
        "source_file_count": manifest.get("source_file_count"),
        "manifest": "manifest.json",
        "audit_index": "audit_index.md",
        "effort_ledger": "effort_ledger.json",
        "excluded_files": "excluded_files.json",
        "reports_dir": "reports",
        "ownership_marker": ".full-repo-audit-artifacts.json",
        "marker_semantics": "Queue artifacts were generated; subagent reports and effort ledger still require verifier completion.",
    }
    for field, expected_value in expected.items():
        if expected_value is not None and marker.get(field) != expected_value:
            mismatches.append(
                {
                    "path": str(marker_path),
                    "field": field,
                    "expected": expected_value,
                    "actual": marker.get(field),
                }
            )
    return mismatches


def load_excluded_files(manifest_path: Path) -> list[dict]:
    excluded_path = manifest_path.parent / "excluded_files.json"
    if not excluded_path.is_file():
        raise ValueError(f"excluded_files.json is missing: {excluded_path}")
    try:
        excluded = json.loads(excluded_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"excluded_files.json is not valid JSON: {excluded_path}") from exc
    if not isinstance(excluded, list):
        raise ValueError("excluded_files.json must be a JSON list.")
    for index, item in enumerate(excluded):
        if not isinstance(item, dict):
            raise ValueError(f"excluded_files[{index}] must be an object.")
        if not isinstance(item.get("path"), str) or not item["path"]:
            raise ValueError(f"excluded_files[{index}].path must be a non-empty string.")
        if not isinstance(item.get("reason"), str) or not item["reason"]:
            raise ValueError(f"excluded_files[{index}].reason must be a non-empty string.")
        if "scope_warning" in item and not isinstance(item["scope_warning"], bool):
            raise ValueError(f"excluded_files[{index}].scope_warning must be boolean when present.")
    return excluded


def canonical_json_sha256(data: dict | list) -> str:
    payload = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def verify_excluded_files(manifest_path: Path, manifest: dict) -> tuple[list[dict], list[dict]]:
    excluded = load_excluded_files(manifest_path)
    manifest_warnings = manifest.get("scope_warnings", [])
    if not isinstance(manifest_warnings, list):
        raise ValueError("Manifest field scope_warnings must be a list when present.")
    excluded_warnings = [item for item in excluded if item.get("scope_warning")]
    issues = []
    manifest_warning_count = manifest.get("scope_warning_count", len(manifest_warnings))
    if manifest_warning_count != len(manifest_warnings):
        issues.append(
            {
                "path": str(manifest_path),
                "field": "scope_warning_count",
                "expected": len(manifest_warnings),
                "actual": manifest_warning_count,
            }
        )
    manifest_excluded_count = manifest.get("excluded_file_count")
    if manifest_excluded_count != len(excluded):
        issues.append(
            {
                "path": str(manifest_path),
                "field": "excluded_file_count",
                "expected": len(excluded),
                "actual": manifest_excluded_count,
            }
        )
    manifest_excluded_digest = manifest.get("excluded_files_sha256")
    excluded_digest = canonical_json_sha256(excluded)
    if manifest_excluded_digest != excluded_digest:
        issues.append(
            {
                "path": str(manifest_path.parent / "excluded_files.json"),
                "field": "excluded_files_sha256",
                "expected": manifest_excluded_digest,
                "actual": excluded_digest,
                "reason": "excluded_files.json content differs from manifest digest",
            }
        )
    manifest_warning_rows = set()
    for index, item in enumerate(manifest_warnings):
        if not isinstance(item, dict):
            raise ValueError(f"Manifest scope_warnings[{index}] must be an object.")
        if not isinstance(item.get("path"), str) or not item["path"]:
            raise ValueError(f"Manifest scope_warnings[{index}].path must be a non-empty string.")
        if not isinstance(item.get("reason"), str) or not item["reason"]:
            raise ValueError(f"Manifest scope_warnings[{index}].reason must be a non-empty string.")
        manifest_warning_rows.add((item["path"], item["reason"]))
    excluded_warning_rows = {(item.get("path"), item.get("reason")) for item in excluded_warnings}
    if manifest_warning_rows != excluded_warning_rows:
        def warning_dicts(rows: set[tuple[str | None, str | None]]) -> list[dict]:
            return [
                {"path": path, "reason": reason}
                for path, reason in sorted(rows, key=lambda row: (row[0] or "", row[1] or ""))
            ]

        issues.append(
            {
                "path": str(manifest_path.parent / "excluded_files.json"),
                "reason": "scope warning rows differ between manifest and excluded_files.json",
                "manifest": warning_dicts(manifest_warning_rows),
                "excluded_files": warning_dicts(excluded_warning_rows),
            }
        )
    if manifest_warning_count != len(excluded_warnings):
        issues.append(
            {
                "path": str(manifest_path.parent / "excluded_files.json"),
                "field": "scope_warning_count",
                "expected": manifest_warning_count,
                "actual": len(excluded_warnings),
            }
        )
    return excluded_warnings, issues


def validate_journey_report(
    report_path: Path,
    *,
    expected_run_id: str | None,
    worker_key: str,
    interface_files: set[str],
    known_source_files: set[str],
) -> list[dict]:
    required_sections = JOURNEY_REPORT_SECTIONS[worker_key]
    worker_label = JOURNEY_WORKER_LABELS[worker_key]
    try:
        text = report_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return [{"path": str(report_path), "reason": "journey report is not valid UTF-8", "error": str(exc)}]
    except OSError as exc:
        return [{"path": str(report_path), "reason": "journey report could not be read", "error": str(exc)}]

    section_order = [
        match.group(1).strip().lower()
        for line in text.splitlines()
        if (match := SECTION_RE.match(line.strip()))
    ]
    bodies = section_bodies(text)
    issues: list[dict] = []
    if section_order != list(required_sections):
        issues.append(
            {
                "path": str(report_path),
                "reason": "journey report sections must match the required order exactly",
                "expected": list(required_sections),
                "actual": section_order,
            }
        )
    run_ids = declared_run_ids(text)
    if len(run_ids) != 1 or (expected_run_id and run_ids and run_ids[0] != expected_run_id):
        issues.append(
            {
                "path": str(report_path),
                "field": "run id",
                "expected": expected_run_id,
                "actual": run_ids,
            }
        )
    worker_body = bodies.get("worker", "").strip().splitlines()
    worker_value = worker_body[0].strip() if worker_body else ""
    if worker_value != worker_label:
        issues.append(
            {
                "path": str(report_path),
                "field": "worker",
                "expected": worker_label,
                "actual": worker_value,
            }
        )
    for section in required_sections:
        if not bodies.get(section, "").strip():
            issues.append({"path": str(report_path), "section": section, "reason": "section body is empty"})
    findings_issues = validate_findings_schema(bodies.get("findings", ""))
    if findings_issues:
        issues.append({"path": str(report_path), "section": "findings", "issues": findings_issues})
    semantic_findings_issues = validate_journey_findings_semantics(
        bodies.get("findings", ""),
        known_source_files,
        interface_files,
    )
    if semantic_findings_issues:
        issues.append({"path": str(report_path), "section": "findings", "issues": semantic_findings_issues})
    report_text = f"{bodies.get('journey sources', '')}\n{bodies.get('ui source journey checks', '')}\n{bodies.get('visual journey checks', '')}\n{bodies.get('visual tooling', '')}"
    not_applicable_text = normalized_text(report_text)
    report_is_not_applicable = worker_key == "visual_journey_worker" and "not applicable" in not_applicable_text and (
        "no repo-owned" in not_applicable_text
        or "host-owned" in not_applicable_text
        or "no visual ui" in not_applicable_text
        or "no rendered ui" in not_applicable_text
    )
    missing_interface_mentions = sorted(
        rel_path
        for rel_path in interface_files
        if rel_path not in report_text
    )
    if missing_interface_mentions:
        issues.append(
            {
                "path": str(report_path),
                "section": "journey coverage",
                "reason": "journey report must mention each manifest interface file, including visual not-applicable reports",
                "files": missing_interface_mentions,
            }
        )
    unknown_finding_refs: set[str] = set()
    for block in parse_finding_blocks(bodies.get("findings", "")):
        refs = PATH_IN_BACKTICKS_RE.findall(block["fields"].get("files", ""))
        unknown_finding_refs.update(ref for ref in refs if ref not in known_source_files)
    if unknown_finding_refs:
        issues.append(
            {
                "path": str(report_path),
                "section": "findings",
                "reason": "journey finding Files fields must reference manifest source files",
                "files": sorted(unknown_finding_refs),
            }
        )
    if worker_key == "journey_source_worker":
        proposed_body = normalized_text(bodies.get("proposed journeys", ""))
        if "confirmed" not in proposed_body and "draft-needs-user-confirmation" not in proposed_body:
            issues.append(
                {
                    "path": str(report_path),
                    "section": "proposed journeys",
                    "reason": "source journey report must list confirmed journeys or draft-needs-user-confirmation journeys",
                }
            )
        checks_body = bodies.get("ui source journey checks", "")
        if "| journey |" not in normalized_text(checks_body) or "relevance" not in normalized_text(checks_body):
            issues.append(
                {
                    "path": str(report_path),
                    "section": "ui source journey checks",
                    "reason": "journey source report must include the required table with relevance estimates",
                }
            )
        table_rows = parse_markdown_table_dicts(checks_body)
        if table_rows and set(table_rows[0]) != SOURCE_JOURNEY_TABLE_HEADERS:
            issues.append(
                {
                    "path": str(report_path),
                    "section": "ui source journey checks",
                    "reason": "journey source table headers must exactly match the required columns",
                    "expected": sorted(SOURCE_JOURNEY_TABLE_HEADERS),
                    "actual": sorted(table_rows[0]),
                }
            )
        if table_rows:
            mentioned_in_rows = {
                rel_path
                for row in table_rows
                for rel_path in interface_files
                if rel_path in " ".join(row.values())
            }
            missing_rows = sorted(interface_files - mentioned_in_rows)
            if missing_rows:
                issues.append(
                    {
                        "path": str(report_path),
                        "section": "ui source journey checks",
                        "reason": "journey source table must cover each manifest interface file",
                        "files": missing_rows,
                    }
                )
            row_issues = []
            for index, row in enumerate(table_rows, start=1):
                relevance_values = {
                    normalized_text(value)
                    for value in re.split(r"[,;/]", row.get("relevance estimate", ""))
                    if normalized_text(value)
                }
                if not relevance_values or not relevance_values <= ALLOWED_RELEVANCE_VALUES:
                    row_issues.append({"row": index, "field": "relevance estimate", "actual": row.get("relevance estimate", "")})
                for field in ("primary navigation/decision elements", "required information", "mobile/desktop availability", "test mode evidence"):
                    if is_boilerplate_value(row.get(field, "")):
                        row_issues.append({"row": index, "field": field, "actual": row.get(field, "")})
            if row_issues:
                issues.append(
                    {
                        "path": str(report_path),
                        "section": "ui source journey checks",
                        "reason": "journey source rows must include allowed relevance values and non-boilerplate decision/test-mode fields",
                        "rows": row_issues,
                    }
                )
        else:
            issues.append(
                {
                    "path": str(report_path),
                    "section": "ui source journey checks",
                    "reason": "journey source report must include at least one journey table row",
                }
            )
    if worker_key == "visual_journey_worker":
        tooling_body = normalized_text(bodies.get("visual tooling", ""))
        checks_body_raw = bodies.get("visual journey checks", "")
        checks_body = normalized_text(checks_body_raw)
        danger_failure = False
        require_mobile = any(Path(rel_path).suffix.lower() in WEB_UI_EXTENSIONS for rel_path in interface_files)
        if not any(term in tooling_body for term in ("test mode", "fixture", "playwright", "cypress", "storybook", "browser", "not applicable", "no visual")):
            issues.append(
                {
                    "path": str(report_path),
                    "section": "visual tooling",
                    "reason": "visual report must identify visual tooling/test mode or explicitly explain why it is not applicable",
                }
            )
        if "| journey |" not in checks_body or "viewport" not in checks_body:
            issues.append(
                {
                    "path": str(report_path),
                    "section": "visual journey checks",
                    "reason": "visual report must include the required table with viewport checks",
                }
            )
        visual_rows = parse_markdown_table_dicts(checks_body_raw)
        if visual_rows and set(visual_rows[0]) != VISUAL_JOURNEY_TABLE_HEADERS:
            issues.append(
                {
                    "path": str(report_path),
                    "section": "visual journey checks",
                    "reason": "visual journey table headers must exactly match the required columns",
                    "expected": sorted(VISUAL_JOURNEY_TABLE_HEADERS),
                    "actual": sorted(visual_rows[0]),
                }
            )
        if not visual_rows:
            issues.append(
                {
                    "path": str(report_path),
                    "section": "visual journey checks",
                    "reason": "visual report must include at least one journey/viewport table row",
                }
            )
        if visual_rows and not report_is_not_applicable:
            viewports_by_journey: dict[str, set[str]] = defaultdict(set)
            for row in visual_rows:
                journey = normalized_text(row.get("journey", ""))
                viewport = normalized_text(row.get("viewport", ""))
                if journey:
                    viewports_by_journey[journey].add(viewport)
            incomplete = []
            for journey, viewports in sorted(viewports_by_journey.items()):
                has_desktop = any("desktop" in viewport for viewport in viewports)
                has_mobile = any(
                    term in viewport
                    for viewport in viewports
                    for term in ("mobile", "narrow", "small", "phone")
                )
                if not has_desktop or (require_mobile and not has_mobile):
                    incomplete.append(
                        {
                            "journey": journey,
                            "viewports": sorted(viewports),
                            "missing": [
                                label
                                for label, ok in (("desktop", has_desktop), ("narrow mobile", has_mobile or not require_mobile))
                                if not ok
                            ],
                        }
                    )
            if incomplete:
                issues.append(
                    {
                        "path": str(report_path),
                        "section": "visual journey checks",
                        "reason": (
                            "visual report must include desktop and narrow-mobile viewport rows per journey unless checks are not applicable"
                            if require_mobile
                            else "visual report must include desktop/native viewport rows per journey unless checks are not applicable"
                        ),
                        "journeys": incomplete,
                    }
                )
            evidence_text = f"{tooling_body}\n{checks_body}"
            has_tool_or_command = any(term in evidence_text for term in VISUAL_EVIDENCE_TOOL_TERMS)
            has_artifact_evidence = any(term in evidence_text for term in VISUAL_EVIDENCE_ARTIFACT_TERMS)
            if not has_tool_or_command or not has_artifact_evidence:
                issues.append(
                    {
                        "path": str(report_path),
                        "section": "visual tooling",
                        "reason": "visual report must cite commands/tools run and screenshot/trace/artifact evidence when visual checks are applicable",
                        "has_tool_or_command": has_tool_or_command,
                        "has_artifact_evidence": has_artifact_evidence,
                    }
                )
        if visual_rows:
            row_issues = []
            for index, row in enumerate(visual_rows, start=1):
                for field in ("journey", "viewport", "route/screen", "evidence"):
                    if is_boilerplate_value(row.get(field, "")) or len(plain_cell(row.get(field, ""))) < 4:
                        row_issues.append({"row": index, "field": field, "actual": row.get(field, "")})
                if not report_is_not_applicable:
                    for field in ("navigation visibility", "decision information", "visual quality", "result"):
                        if is_boilerplate_value(row.get(field, "")) or len(plain_cell(row.get(field, ""))) < 4:
                            row_issues.append({"row": index, "field": field, "actual": row.get(field, "")})
                    result = normalized_text(row.get("result", ""))
                    if result in {"pass", "passed", "matched"} and VISUAL_DANGER_RE.search(" ".join(row.values())):
                        danger_failure = True
                        row_issues.append(
                            {
                                "row": index,
                                "field": "result",
                                "reason": "visual danger terms such as overload, unreadable text, clipping, overflow, or low contrast cannot be marked pass without a finding",
                                "actual": row.get("result", ""),
                            }
                        )
            if row_issues:
                issues.append(
                    {
                        "path": str(report_path),
                        "section": "visual journey checks",
                        "reason": "visual rows must include non-boilerplate route, evidence, navigation, decision, quality, and result details",
                        "rows": row_issues,
                    }
                )
            if danger_failure and not has_visual_danger_finding(bodies.get("findings", "")):
                issues.append(
                    {
                        "path": str(report_path),
                        "section": "findings",
                        "reason": "visual danger terms require a visual/usability finding",
                    }
                )
    return issues


def verify_effort_ledger(
    manifest_path: Path,
    manifest: dict,
    known_batch_ids: set[str],
    report_rel_by_batch: dict[str, str],
) -> list[dict]:
    ledger_path = manifest_path.parent / "effort_ledger.json"
    if not ledger_path.is_file():
        return [{"path": str(ledger_path), "reason": "effort_ledger.json is missing"}]
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return [{"path": str(ledger_path), "reason": "effort_ledger.json is not valid JSON"}]
    if not isinstance(ledger, dict):
        return [{"path": str(ledger_path), "reason": "effort_ledger.json must be a JSON object"}]

    issues: list[dict] = []
    if ledger.get("run_id") != manifest.get("run_id"):
        issues.append({"path": str(ledger_path), "field": "run_id", "expected": manifest.get("run_id"), "actual": ledger.get("run_id")})
    if not isinstance(ledger.get("provenance_scope"), str) or not ledger.get("provenance_scope"):
        issues.append({"path": str(ledger_path), "field": "provenance_scope", "expected": "non-empty string", "actual": ledger.get("provenance_scope")})
    if ledger.get("effort_verification_scope") != "ledger-recorded":
        issues.append({"path": str(ledger_path), "field": "effort_verification_scope", "expected": "ledger-recorded", "actual": ledger.get("effort_verification_scope")})

    capability = ledger.get("subagent_capability_check")
    if not isinstance(capability, dict) or capability.get("status") != "completed":
        issues.append({"path": str(ledger_path), "field": "subagent_capability_check.status", "expected": "completed", "actual": capability.get("status") if isinstance(capability, dict) else None})
    capability_can_set = capability.get("can_set_reasoning_effort") if isinstance(capability, dict) else None
    if not isinstance(capability_can_set, bool):
        issues.append({"path": str(ledger_path), "field": "subagent_capability_check.can_set_reasoning_effort", "expected": "boolean", "actual": capability_can_set})
    if not isinstance(capability, dict) or not isinstance(capability.get("spawn_tool"), str) or not capability.get("spawn_tool"):
        issues.append({"path": str(ledger_path), "field": "subagent_capability_check.spawn_tool", "expected": "non-empty string", "actual": capability.get("spawn_tool") if isinstance(capability, dict) else None})
    if not isinstance(capability, dict) or not isinstance(capability.get("notes"), str) or not capability.get("notes"):
        issues.append({"path": str(ledger_path), "field": "subagent_capability_check.notes", "expected": "non-empty string", "actual": capability.get("notes") if isinstance(capability, dict) else None})

    fallback = ledger.get("fallback_mode")
    if not isinstance(fallback, dict):
        issues.append({"path": str(ledger_path), "field": "fallback_mode", "expected": "object", "actual": type(fallback).__name__})
        fallback = {}
    fallback_active_value = fallback.get("active")
    if not isinstance(fallback_active_value, bool):
        issues.append({"path": str(ledger_path), "field": "fallback_mode.active", "expected": "boolean", "actual": fallback_active_value})
    fallback_active = fallback_active_value is True
    if fallback_active and not fallback.get("reason"):
        issues.append({"path": str(ledger_path), "field": "fallback_mode.reason", "expected": "non-empty reason when fallback is active", "actual": fallback.get("reason")})
    if not fallback_active and fallback.get("reason"):
        issues.append({"path": str(ledger_path), "field": "fallback_mode.reason", "expected": None, "actual": fallback.get("reason")})
    if capability_can_set is True and fallback_active:
        issues.append({"path": str(ledger_path), "field": "fallback_mode.active", "expected": False, "actual": True})
    if capability_can_set is False and not fallback_active:
        issues.append({"path": str(ledger_path), "field": "fallback_mode.active", "expected": True, "actual": False})

    raw_pruned_hint_count = manifest.get("pruned_directory_review_hint_count", 0)
    if isinstance(raw_pruned_hint_count, int) and not isinstance(raw_pruned_hint_count, bool):
        pruned_hint_count = raw_pruned_hint_count
    else:
        pruned_hint_count = 0
        issues.append(
            {
                "path": str(ledger_path),
                "field": "pruned_directory_review_hint_count",
                "expected": "integer manifest count",
                "actual": raw_pruned_hint_count,
            }
        )
    pruned_hints = manifest.get("pruned_directory_review_hints", [])
    expected_pruned_paths = {
        hint.get("path")
        for hint in pruned_hints
        if isinstance(hint, dict) and isinstance(hint.get("path"), str)
    }
    pruned_review = ledger.get("pruned_directory_review")
    if pruned_hint_count:
        if not isinstance(pruned_review, dict):
            issues.append({"path": str(ledger_path), "field": "pruned_directory_review", "expected": "object", "actual": type(pruned_review).__name__})
        else:
            if pruned_review.get("status") != "completed":
                issues.append({"path": str(ledger_path), "field": "pruned_directory_review.status", "expected": "completed", "actual": pruned_review.get("status")})
            if pruned_review.get("hint_count") != pruned_hint_count:
                issues.append({"path": str(ledger_path), "field": "pruned_directory_review.hint_count", "expected": pruned_hint_count, "actual": pruned_review.get("hint_count")})
            if not isinstance(pruned_review.get("notes"), str) or not pruned_review.get("notes"):
                issues.append({"path": str(ledger_path), "field": "pruned_directory_review.notes", "expected": "non-empty review notes", "actual": pruned_review.get("notes")})
            decisions = pruned_review.get("decisions")
            if not isinstance(decisions, list):
                issues.append({"path": str(ledger_path), "field": "pruned_directory_review.decisions", "expected": "one decision per pruned hint", "actual": type(decisions).__name__})
            else:
                observed_paths = set()
                decision_issues = []
                for index, decision in enumerate(decisions):
                    if not isinstance(decision, dict):
                        decision_issues.append({"index": index, "reason": "decision row must be an object", "actual": type(decision).__name__})
                        continue
                    path = decision.get("path")
                    if not isinstance(path, str):
                        decision_issues.append({"index": index, "field": "path", "expected": "string path from manifest pruned_directory_review_hints", "actual": path})
                    else:
                        observed_paths.add(path)
                    if not isinstance(path, str) or path not in expected_pruned_paths:
                        decision_issues.append({"index": index, "field": "path", "reason": "path is not in manifest pruned_directory_review_hints", "actual": path})
                    decision_value = decision.get("decision")
                    if decision_value not in ALLOWED_PRUNED_REVIEW_DECISIONS:
                        decision_issues.append(
                            {
                                "index": index,
                                "field": "decision",
                                "expected": sorted(ALLOWED_PRUNED_REVIEW_DECISIONS),
                                "actual": decision_value,
                            }
                        )
                    rationale = decision.get("rationale")
                    if not isinstance(rationale, str) or is_boilerplate_value(rationale) or len(plain_cell(rationale)) < 12:
                        decision_issues.append({"index": index, "field": "rationale", "expected": "non-boilerplate rationale", "actual": rationale})
                missing_decision_paths = sorted(expected_pruned_paths - observed_paths)
                extra_decision_paths = sorted(path for path in observed_paths - expected_pruned_paths if path is not None)
                if missing_decision_paths or extra_decision_paths:
                    decision_issues.append(
                        {
                            "field": "path coverage",
                            "missing": missing_decision_paths,
                            "extra": extra_decision_paths,
                        }
                    )
                if decision_issues:
                    issues.append(
                        {
                            "path": str(ledger_path),
                            "field": "pruned_directory_review.decisions",
                            "reason": "each pruned directory hint needs a structured lead decision and rationale",
                            "issues": decision_issues,
                        }
                    )
    elif isinstance(pruned_review, dict) and pruned_review.get("status") != "not-applicable":
        issues.append({"path": str(ledger_path), "field": "pruned_directory_review.status", "expected": "not-applicable", "actual": pruned_review.get("status")})

    lead = ledger.get("lead")
    if not isinstance(lead, dict):
        issues.append({"path": str(ledger_path), "field": "lead", "expected": "object", "actual": type(lead).__name__})
    else:
        if lead.get("required_reasoning_effort") != "xhigh":
            issues.append({"path": str(ledger_path), "field": "lead.required_reasoning_effort", "expected": "xhigh", "actual": lead.get("required_reasoning_effort")})

    if isinstance(lead, dict):
        if lead.get("status") != "completed":
            issues.append({"path": str(ledger_path), "field": "lead.status", "expected": "completed", "actual": lead.get("status")})
        if lead.get("actual_reasoning_effort") != "xhigh":
            issues.append({"path": str(ledger_path), "field": "lead.actual_reasoning_effort", "expected": "xhigh", "actual": lead.get("actual_reasoning_effort")})
        if not lead.get("agent_id"):
            issues.append({"path": str(ledger_path), "field": "lead.agent_id", "expected": "agent id", "actual": lead.get("agent_id")})

    journey = manifest.get("journey_audit") if isinstance(manifest.get("journey_audit"), dict) else {}
    journey_required = bool(journey.get("required"))
    for worker_key in ("journey_source_worker", "visual_journey_worker"):
        worker = ledger.get(worker_key)
        if not isinstance(worker, dict):
            issues.append({"path": str(ledger_path), "field": worker_key, "expected": "object", "actual": type(worker).__name__})
            continue
        if not journey_required:
            if worker.get("status") != "not-applicable":
                issues.append({"path": str(ledger_path), "field": f"{worker_key}.status", "expected": "not-applicable", "actual": worker.get("status")})
            continue
        if worker.get("status") != "completed":
            issues.append({"path": str(ledger_path), "field": f"{worker_key}.status", "expected": "completed", "actual": worker.get("status")})
        if worker.get("required_reasoning_effort") != "low":
            issues.append({"path": str(ledger_path), "field": f"{worker_key}.required_reasoning_effort", "expected": "low", "actual": worker.get("required_reasoning_effort")})
        expected_prompt = journey.get(JOURNEY_PROMPT_FIELDS[worker_key])
        prompt = worker.get("prompt")
        if prompt != expected_prompt:
            issues.append({"path": str(ledger_path), "field": f"{worker_key}.prompt", "expected": expected_prompt, "actual": prompt})
        if not isinstance(prompt, str) or not prompt:
            issues.append({"path": str(ledger_path), "field": f"{worker_key}.prompt", "expected": "prompt path", "actual": prompt})
        else:
            prompt_path = manifest_path.parent / prompt
            if not prompt_path.is_file():
                issues.append({"path": str(ledger_path), "field": f"{worker_key}.prompt", "expected": f"existing file {prompt}", "actual": prompt})
        expected_report = journey.get(JOURNEY_REPORT_FIELDS[worker_key])
        report = worker.get("report")
        if report != expected_report:
            issues.append({"path": str(ledger_path), "field": f"{worker_key}.report", "expected": expected_report, "actual": report})
        if not isinstance(report, str) or not report:
            issues.append({"path": str(ledger_path), "field": f"{worker_key}.report", "expected": "report path", "actual": report})
        else:
            report_path = manifest_path.parent / report
            if not report_path.is_file():
                issues.append({"path": str(ledger_path), "field": f"{worker_key}.report", "expected": f"existing file {report}", "actual": report})
            else:
                for issue in validate_journey_report(
                    report_path,
                    expected_run_id=manifest.get("run_id"),
                    worker_key=worker_key,
                    interface_files=set(journey.get("interface_files") or []),
                    known_source_files=set(manifest.get("expected_files", set())),
                ):
                    issues.append({"path": str(ledger_path), "field": worker_key, **issue})
        if fallback_active:
            if worker.get("actual_reasoning_effort") != "manual-fallback":
                issues.append({"path": str(ledger_path), "field": f"{worker_key}.actual_reasoning_effort", "expected": "manual-fallback", "actual": worker.get("actual_reasoning_effort")})
        else:
            if not worker.get("agent_id"):
                issues.append({"path": str(ledger_path), "field": f"{worker_key}.agent_id", "expected": "agent id", "actual": worker.get("agent_id")})
            if worker.get("actual_reasoning_effort") != "low":
                issues.append({"path": str(ledger_path), "field": f"{worker_key}.actual_reasoning_effort", "expected": "low", "actual": worker.get("actual_reasoning_effort")})
        if not isinstance(worker.get("runtime_provenance"), str) or not worker.get("runtime_provenance"):
            issues.append({"path": str(ledger_path), "field": f"{worker_key}.runtime_provenance", "expected": "non-empty string", "actual": worker.get("runtime_provenance")})

    batches = ledger.get("batches")
    if not isinstance(batches, list):
        issues.append({"path": str(ledger_path), "field": "batches", "expected": "list", "actual": type(batches).__name__})
        return issues

    expected_prompt_by_batch = {
        batch["id"]: batch.get("prompt")
        for batch in manifest.get("batches", [])
        if isinstance(batch, dict) and isinstance(batch.get("id"), str)
    }
    seen_batch_ids: set[str] = set()
    batch_id_counts: Counter[str] = Counter()
    for index, batch in enumerate(batches):
        if not isinstance(batch, dict):
            issues.append({"path": str(ledger_path), "field": f"batches[{index}]", "expected": "object", "actual": type(batch).__name__})
            continue
        batch_id = batch.get("batch_id")
        if not isinstance(batch_id, str):
            issues.append({"path": str(ledger_path), "field": f"batches[{index}].batch_id", "expected": "string batch id", "actual": batch_id})
            continue
        seen_batch_ids.add(batch_id)
        batch_id_counts[batch_id] += 1
        if batch_id not in known_batch_ids:
            issues.append({"path": str(ledger_path), "field": f"batches[{index}].batch_id", "expected": "known batch id", "actual": batch_id})
        expected_prompt = expected_prompt_by_batch.get(batch_id)
        if batch.get("prompt") != expected_prompt:
            issues.append({"path": str(ledger_path), "field": f"batches[{index}].prompt", "expected": expected_prompt, "actual": batch.get("prompt")})
        if batch.get("required_reasoning_effort") != "low":
            issues.append({"path": str(ledger_path), "field": f"batches[{index}].required_reasoning_effort", "expected": "low", "actual": batch.get("required_reasoning_effort")})
        if batch.get("status") != "completed":
            issues.append({"path": str(ledger_path), "field": f"batches[{index}].status", "expected": "completed", "actual": batch.get("status")})
        expected_report = f"reports/{batch_id}.md"
        actual_report = batch.get("report")
        if actual_report != expected_report:
            issues.append({"path": str(ledger_path), "field": f"batches[{index}].report", "expected": expected_report, "actual": actual_report})
        parsed_report = report_rel_by_batch.get(batch_id)
        if parsed_report and actual_report != parsed_report:
            issues.append({"path": str(ledger_path), "field": f"batches[{index}].report", "expected": parsed_report, "actual": actual_report})
        if fallback_active:
            if batch.get("actual_reasoning_effort") != "manual-fallback":
                issues.append({"path": str(ledger_path), "field": f"batches[{index}].actual_reasoning_effort", "expected": "manual-fallback", "actual": batch.get("actual_reasoning_effort")})
        else:
            if not batch.get("agent_id"):
                issues.append({"path": str(ledger_path), "field": f"batches[{index}].agent_id", "expected": "agent id", "actual": batch.get("agent_id")})
            if batch.get("actual_reasoning_effort") != "low":
                issues.append({"path": str(ledger_path), "field": f"batches[{index}].actual_reasoning_effort", "expected": "low", "actual": batch.get("actual_reasoning_effort")})
        if not isinstance(batch.get("runtime_provenance"), str) or not batch.get("runtime_provenance"):
            issues.append({"path": str(ledger_path), "field": f"batches[{index}].runtime_provenance", "expected": "non-empty string", "actual": batch.get("runtime_provenance")})

    missing = sorted(known_batch_ids - seen_batch_ids)
    extra = sorted(item for item in seen_batch_ids - known_batch_ids if item is not None)
    duplicate_batch_ids = sorted(batch_id for batch_id, count in batch_id_counts.items() if count > 1)
    if missing:
        issues.append({"path": str(ledger_path), "field": "batches", "reason": "missing batch ledger rows", "batches": missing})
    if extra:
        issues.append({"path": str(ledger_path), "field": "batches", "reason": "unknown batch ledger rows", "batches": extra})
    if duplicate_batch_ids:
        issues.append({"path": str(ledger_path), "field": "batches", "reason": "duplicate batch ledger rows", "batches": duplicate_batch_ids})
    return issues


def filename_batch_id(report_path: Path) -> str | None:
    match = BATCH_ID_RE.search(report_path.name)
    if not match:
        return None
    return f"batch_{match.group(1)}".lower()


def declared_batch_ids(text: str) -> list[str]:
    ids: list[str] = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        section = SECTION_RE.match(line.strip())
        if not section or section.group(1).strip().lower() != "batch id":
            continue
        for value in lines[index + 1 :]:
            stripped = value.strip()
            if stripped.startswith("## "):
                break
            if not stripped:
                continue
            match = BATCH_ID_RE.search(stripped)
            if match:
                ids.append(f"batch_{match.group(1)}".lower())
    return ids


def declared_run_ids(text: str) -> list[str]:
    ids: list[str] = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        section = SECTION_RE.match(line.strip())
        if not section or section.group(1).strip().lower() != "run id":
            continue
        for value in lines[index + 1 :]:
            stripped = value.strip()
            if stripped.startswith("## "):
                break
            if stripped:
                ids.append(stripped.strip("`"))
    return ids


def section_bodies(text: str) -> dict[str, str]:
    bodies: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        section = SECTION_RE.match(line.strip())
        if section:
            current = section.group(1).strip().lower()
            bodies.setdefault(current, [])
            continue
        if current:
            bodies[current].append(line)
    return {section: "\n".join(lines).strip() for section, lines in bodies.items()}


def split_markdown_row(row: str) -> list[str]:
    stripped = row.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]

    columns: list[str] = []
    current: list[str] = []
    escaped = False
    for char in stripped:
        if escaped:
            current.append(char if char == "|" else f"\\{char}")
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "|":
            columns.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    if escaped:
        current.append("\\")
    columns.append("".join(current).strip())
    return columns


def is_separator_row(columns: list[str]) -> bool:
    return bool(columns) and all(re.fullmatch(r":?-{3,}:?", column.strip()) for column in columns)


def plain_cell(value: str) -> str:
    return value.strip().strip("`").strip()


def normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", plain_cell(value).lower()).strip()


def parse_markdown_table_dicts(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    headers: list[str] | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        columns = split_markdown_row(stripped)
        if is_separator_row(columns):
            continue
        if headers is None:
            headers = [normalized_text(column) for column in columns]
            continue
        if len(columns) != len(headers):
            continue
        rows.append({header: columns[index] for index, header in enumerate(headers)})
    return rows


def loose_normalized_text(value: str) -> str:
    return re.sub(r"[^a-z0-9_.!#()-]+", " ", value.lower()).strip()


def is_boilerplate_value(value: str) -> bool:
    normalized = normalized_text(value)
    punctuationless = re.sub(r"[^\w\s]+", "", normalized).strip()
    return not normalized or normalized in BOILERPLATE_VALUES or punctuationless in BOILERPLATE_VALUES


def dedupe_hints(hints: list[str]) -> list[str]:
    cleaned = []
    seen = set()
    for hint in hints:
        normalized = re.sub(r"\s+", " ", hint).strip().strip("'\"")
        if (
            len(normalized) < 2
            or len(normalized) > 100
            or "{{" in normalized
            or "}}" in normalized
            or normalized in seen
        ):
            continue
        seen.add(normalized)
        cleaned.append(normalized)
    return cleaned


def split_json_key_tokens(key: str) -> set[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", key)
    return {item.lower() for item in re.split(r"[^A-Za-z0-9]+", spaced) if item}


def looks_like_visible_json_string(key_stack: list[str], value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    if re.match(r"(?i)^(?:[a-z][a-z0-9+.-]*:)?//", stripped) or stripped.startswith(("/", "./", "../")):
        return False
    if re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", stripped):
        return False
    tokens: set[str] = set()
    for key in key_stack:
        tokens.update(split_json_key_tokens(key))
    if tokens & INTERNAL_JSON_KEY_TOKENS:
        return False
    if tokens & VISIBLE_JSON_KEY_TOKENS:
        return True
    if any(char.isspace() for char in stripped) or any(char.isupper() for char in stripped):
        return True
    return False


def json_string_hints(text: str) -> list[str]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    hints: list[str] = []

    def walk(value: object, key_stack: list[str]) -> None:
        if isinstance(value, str):
            if looks_like_visible_json_string(key_stack, value):
                hints.append(value)
        elif isinstance(value, list):
            for item in value:
                walk(item, key_stack)
        elif isinstance(value, dict):
            for key, item in value.items():
                walk(item, [*key_stack, str(key)])

    walk(payload, [])
    return hints


def xml_element_text_hints(text: str, element_names: set[str]) -> list[str]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    hints: list[str] = []
    for element in root.iter():
        local_name = element.tag.rsplit("}", 1)[-1].lower()
        if local_name not in element_names:
            continue
        value = " ".join(part.strip() for part in element.itertext() if part.strip())
        if 2 <= len(value) <= 100:
            hints.append(value)
    return hints


def message_catalog_hints(suffix: str, text: str) -> list[str]:
    if suffix in {".json", ".arb"}:
        return json_string_hints(text)
    if suffix in {".po", ".pot"}:
        return [match.group(1).strip() for match in PO_VALUE_RE.finditer(text)]
    if suffix == ".properties":
        return [match.group(1).strip() for match in PROPERTIES_VALUE_RE.finditer(text)]
    if suffix == ".strings":
        return [match.group(1).strip() for match in APPLE_STRINGS_VALUE_RE.finditer(text)]
    if suffix == ".ftl":
        return [match.group(1).strip() for match in FTL_VALUE_RE.finditer(text)]
    if suffix == ".resx":
        return xml_element_text_hints(text, {"value"})
    if suffix in {".xlf", ".xliff"}:
        return xml_element_text_hints(text, {"source", "target"})
    return []


def visible_text_hints(rel_path: str, text: str) -> list[str]:
    suffix = PurePosixPath(rel_path).suffix.lower()
    if suffix not in VISIBLE_HINT_EXTENSIONS:
        return []
    hints: list[str] = []
    if suffix == ".md":
        h1_match = MARKDOWN_H1_RE.search(text)
        if h1_match:
            hints.append(h1_match.group(1).strip())
    if suffix in MESSAGE_CATALOG_HINT_EXTENSIONS:
        hints.extend(message_catalog_hints(suffix, text))
    if suffix in {".yaml", ".yml"}:
        hints.extend(match.group(1).strip() for match in SIMPLE_KEY_VALUE_RE.finditer(text))
    for match in VISIBLE_KEY_RE.finditer(text):
        hints.append(match.group(2).strip())
    for match in VISIBLE_ATTR_RE.finditer(text):
        hints.append((match.group(1) or match.group(2)).strip())
    for match in VISIBLE_TEXT_RE.finditer(text):
        hints.append(match.group(1).strip())
    return dedupe_hints(hints)


def appears_inside_quoted_literal(line: str, index: int) -> bool:
    escaped = False
    quote_counts = {"'": 0, '"': 0}
    for char in line[:index]:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char in quote_counts:
            quote_counts[char] += 1
    return any(count % 2 for count in quote_counts.values())


def placeholder_markers_for(rel_path: str, text: str) -> list[str]:
    suffix = PurePosixPath(rel_path).suffix.lower()
    markers = set()
    for line in text.splitlines():
        for match in PLACEHOLDER_COMMENT_RE.finditer(line):
            if not appears_inside_quoted_literal(line, match.start()):
                markers.add(line.strip()[:160])
        if suffix in CODE_STUB_EXTENSIONS:
            for match in CODE_STUB_RE.finditer(line):
                if not appears_inside_quoted_literal(line, match.start()):
                    markers.add(match.group(0).strip())
    if suffix in UI_CODE_EXTENSIONS:
        for line in text.splitlines():
            for match in CONSOLE_LOG_RE.finditer(line):
                if not appears_inside_quoted_literal(line, match.start()):
                    markers.add(match.group(0).strip())
    return sorted(markers)


def placeholder_marker_terms(marker: str) -> set[str]:
    normalized = loose_normalized_text(marker)
    terms = {normalized}
    backticked = PATH_IN_BACKTICKS_RE.findall(marker)
    terms.update(loose_normalized_text(item) for item in backticked)
    return {term for term in terms if len(term) >= 4}


def marker_is_covered_by_block(block: dict, marker: str, term_builder) -> bool:
    block_text = loose_normalized_text(block.get("text", ""))
    return any(term in block_text for term in term_builder(marker))


def uncovered_placeholder_markers(blocks: list[dict], markers: list[str]) -> list[str]:
    return [
        marker
        for marker in markers
        if not any(marker_is_covered_by_block(block, marker, placeholder_marker_terms) for block in blocks)
    ]


def strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value)


def has_accessible_label(attrs: str, body: str = "") -> bool:
    if re.search(
        r"""(?i)\b(?:aria-label|aria-labelledby|title|content|contentdescription|android:text|text|label|accessibilityLabel)\s*=\s*(?:"[^"]+"|'[^']+'|{[^}]+})""",
        attrs,
    ):
        return True
    text_body = strip_tags(body).strip()
    if text_body:
        return True
    return bool(re.search(r"{\s*[A-Za-z_$][\w$.]*(?:\([^)]*\))?\s*}", body))


def attr_value(attrs: str, name: str) -> str | None:
    match = re.search(
        rf"""(?is)\b{re.escape(name)}\s*=\s*(?:"([^"]*)"|'([^']*)'|{{\s*["']?([^}}"']+)["']?\s*}})""",
        attrs,
    )
    if not match:
        return None
    return next((value for value in match.groups() if value is not None), None)


def has_event_handler(attrs: str) -> bool:
    return bool(re.search(r"\bon(?:Click|Change|Input|Submit|KeyDown|KeyUp|KeyPress|CheckedChange|ValueChange)\s*=", attrs))


def has_static_disabled_attr(attrs: str) -> bool:
    return bool(DISABLED_ATTR_RE.search(attrs))


def form_field_kind(match: re.Match[str]) -> tuple[str, str, str]:
    if match.group(1):
        return match.group(1).lower(), match.group(2) or "", match.group(3) or ""
    return (match.group(4) or "input").lower(), match.group(5) or "", ""


def no_op_handler_names(text: str) -> set[str]:
    names: set[str] = set()
    for match in NOOP_FUNCTION_RE.finditer(text):
        name = match.group(1) or match.group(2)
        if name:
            names.add(name)
    return names


def interface_control_markers_for(rel_path: str, text: str) -> list[str]:
    suffix = PurePosixPath(rel_path).suffix.lower()
    if suffix not in INTERACTIVE_HINT_EXTENSIONS:
        return []
    markers: set[str] = set()
    noop_names = no_op_handler_names(text)
    for match in EMPTY_HANDLER_RE.finditer(text):
        markers.add(f"empty handler `{match.group(0).strip()[:80]}`")
    for match in EVENT_HANDLER_REF_RE.finditer(text):
        handler_name = match.group(1)
        if handler_name in noop_names:
            markers.add(f"named no-op handler `{handler_name}`")
    for match in DEAD_HREF_RE.finditer(text):
        markers.add(f"dead link `{match.group(0).strip()[:120]}`")
    for match in STATIC_DISABLED_CONTROL_RE.finditer(text):
        markers.add(f"static disabled control `{match.group(0).strip()[:120]}`")
    for match in NATIVE_DISABLED_CONTROL_RE.finditer(text):
        markers.add(f"static disabled control `{match.group(0).strip()[:120]}`")
    for match in FORM_TAG_RE.finditer(text):
        attrs = match.group(1) or ""
        if not FORM_SUBMIT_ATTR_RE.search(attrs):
            markers.add(f"form without submit handler or action `{match.group(0).strip()[:120]}`")
    for match in FORM_FIELD_TAG_RE.finditer(text):
        tag_name, attrs, body = form_field_kind(match)
        field_type = (attr_value(attrs, "type") or "").strip().lower()
        if tag_name == "input" and field_type == "hidden":
            continue
        if has_static_disabled_attr(attrs):
            markers.add(f"static disabled form field `{match.group(0).strip()[:120]}`")
        if not has_accessible_label(attrs, body):
            markers.add(f"unlabeled form field `{match.group(0).strip()[:120]}`")
        if tag_name in {"input", "select", "textarea"} and not has_event_handler(attrs):
            name_or_id = attr_value(attrs, "name") or attr_value(attrs, "id") or attr_value(attrs, "placeholder")
            if not name_or_id:
                markers.add(f"untracked form field `{match.group(0).strip()[:120]}`")
    for match in BUTTON_TAG_RE.finditer(text):
        attrs = match.group(1) or ""
        body = match.group(2) or ""
        if not has_accessible_label(attrs, body):
            markers.add(f"unlabeled button `{match.group(0).strip()[:120]}`")
    for match in SELF_CLOSING_BUTTON_RE.finditer(text):
        attrs = match.group(1) or ""
        if not has_accessible_label(attrs):
            markers.add(f"unlabeled button `{match.group(0).strip()[:120]}`")
    for match in COMPONENT_BUTTON_TAG_RE.finditer(text):
        attrs = match.group(1) or ""
        body = match.group(2) or ""
        if not has_accessible_label(attrs, body):
            markers.add(f"unlabeled button component `{match.group(0).strip()[:120]}`")
    for match in SELF_CLOSING_COMPONENT_BUTTON_RE.finditer(text):
        attrs = match.group(1) or ""
        if not has_accessible_label(attrs):
            markers.add(f"unlabeled button component `{match.group(0).strip()[:120]}`")
    for match in ROLE_BUTTON_RE.finditer(text):
        attrs = f"{match.group(2) or ''} {match.group(3) or ''}"
        body = match.group(4) or ""
        if not has_accessible_label(attrs, body):
            markers.add(f"unlabeled role button `{match.group(0).strip()[:120]}`")
        if not re.search(r"\bon(?:Click|KeyDown|KeyUp|KeyPress)\s*=", attrs):
            markers.add(f"role button without click or keyboard handler `{match.group(0).strip()[:120]}`")
    for match in ROLE_INTERACTIVE_RE.finditer(text):
        attrs = f"{match.group(2) or ''} {match.group(3) or ''}"
        body = match.group(4) or ""
        if not has_accessible_label(attrs, body):
            markers.add(f"unlabeled interactive role `{match.group(0).strip()[:120]}`")
        if not has_event_handler(attrs):
            markers.add(f"interactive role without handler `{match.group(0).strip()[:120]}`")
    return sorted(markers)


def interface_control_marker_terms(marker: str) -> set[str]:
    normalized = loose_normalized_text(marker)
    terms = {normalized}
    backticked = PATH_IN_BACKTICKS_RE.findall(marker)
    terms.update(loose_normalized_text(item) for item in backticked)
    return {term for term in terms if len(term) >= 4}


def uncovered_interface_control_markers(blocks: list[dict], markers: list[str]) -> list[str]:
    return [
        marker
        for marker in markers
        if not any(marker_is_covered_by_block(block, marker, interface_control_marker_terms) for block in blocks)
    ]


def file_purpose_tokens(rel_path: str) -> set[str]:
    path = PurePosixPath(rel_path)
    tokens = set(part.lower() for part in re.split(r"[^A-Za-z0-9]+", path.stem) if part)
    tokens.update(part.lower() for part in path.parts[:-1] if part)
    if path.suffix:
        tokens.add(path.suffix.lower().lstrip("."))
    return tokens


def validate_file_coverage_purposes(rows: list[dict]) -> list[dict]:
    issues: list[dict] = []
    purpose_counts = Counter(normalized_text(row["purpose"]) for row in rows)
    for row in rows:
        purpose = row["purpose"]
        normalized = normalized_text(purpose)
        tokens = file_purpose_tokens(row["file"])
        purpose_words = set(re.split(r"[^a-z0-9]+", normalized))
        if DIRECTORY_ONLY_PURPOSE_RE.search(purpose):
            issues.append(
                {
                    "section": "file coverage",
                    "file": row["file"],
                    "reason": "file coverage purpose must describe the file role, not only a directory or group",
                    "actual": purpose,
                }
            )
        elif normalized in GENERIC_PURPOSE_VALUES:
            issues.append(
                {
                    "section": "file coverage",
                    "file": row["file"],
                    "reason": "file coverage purpose is too generic",
                    "actual": purpose,
                }
            )
        elif purpose_counts[normalized] >= 3 and not (tokens & purpose_words):
            issues.append(
                {
                    "section": "file coverage",
                    "file": row["file"],
                    "reason": "repeated file coverage purpose must include file-specific role detail",
                    "actual": purpose,
                }
            )
    return issues


def png_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24 or not data.startswith(b"\x89PNG\r\n\x1a\n") or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def gif_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 10 or data[:6] not in {b"GIF87a", b"GIF89a"}:
        return None
    width, height = struct.unpack("<HH", data[6:10])
    return width, height


def jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 4 or not data.startswith(b"\xff\xd8"):
        return None
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        if marker in {0xD8, 0xD9}:
            continue
        if index + 2 > len(data):
            return None
        segment_length = int.from_bytes(data[index:index + 2], "big")
        if segment_length < 2 or index + segment_length > len(data):
            return None
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            if segment_length < 7:
                return None
            height = int.from_bytes(data[index + 3:index + 5], "big")
            width = int.from_bytes(data[index + 5:index + 7], "big")
            return width, height
        index += segment_length
    return None


def webp_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    chunk = data[12:16]
    if chunk == b"VP8X" and len(data) >= 30:
        width = 1 + int.from_bytes(data[24:27], "little")
        height = 1 + int.from_bytes(data[27:30], "little")
        return width, height
    if chunk == b"VP8 " and len(data) >= 30 and data[23:26] == b"\x9d\x01\x2a":
        width = int.from_bytes(data[26:28], "little") & 0x3FFF
        height = int.from_bytes(data[28:30], "little") & 0x3FFF
        return width, height
    if chunk == b"VP8L" and len(data) >= 25 and data[20] == 0x2F:
        bits = int.from_bytes(data[21:25], "little")
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
        return width, height
    return None


def read_asset_prefix(path: Path, limit: int = ASSET_METADATA_READ_LIMIT) -> bytes:
    with path.open("rb") as handle:
        return handle.read(limit)


def svg_dimension_number(raw_value: str) -> int | float | None:
    match = SVG_NUMBER_RE.match(raw_value)
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    if value <= 0:
        return None
    return int(value) if value.is_integer() else value


def parse_svg_metadata(data: bytes) -> tuple[int | float | None, int | float | None] | None:
    text = data.decode("utf-8", errors="ignore")
    match = SVG_ROOT_RE.search(text)
    if not match:
        return None
    attrs = {
        name.lower(): value.strip()
        for name, _quote, value in SVG_ATTR_RE.findall(match.group("attrs"))
    }
    width = svg_dimension_number(attrs.get("width", ""))
    height = svg_dimension_number(attrs.get("height", ""))
    if width is not None and height is not None:
        return width, height
    viewbox = attrs.get("viewbox")
    if viewbox:
        parts = re.split(r"[\s,]+", viewbox.strip())
        if len(parts) == 4:
            viewbox_width = svg_dimension_number(parts[2])
            viewbox_height = svg_dimension_number(parts[3])
            if viewbox_width is not None and viewbox_height is not None:
                return viewbox_width, viewbox_height
    return None, None


def asset_metadata_for(path: Path) -> dict:
    suffix = path.suffix.lower()
    metadata = {
        "mime": ASSET_MIME_BY_SUFFIX.get(suffix),
        "width": None,
        "height": None,
        "valid": False,
        "reason": None,
    }
    if suffix not in ASSET_MIME_BY_SUFFIX:
        metadata["reason"] = f"unsupported asset extension {suffix}"
        return metadata
    try:
        if suffix in {".woff", ".woff2", ".ttf", ".eot", ".ico"}:
            metadata["valid"] = path.stat().st_size > 0
            return metadata
        data = read_asset_prefix(path)
    except OSError as exc:
        metadata["reason"] = str(exc)
        return metadata
    if suffix == ".svg":
        dimensions = parse_svg_metadata(data)
        if dimensions is None:
            metadata["reason"] = "could not parse SVG root metadata"
            return metadata
        metadata["width"], metadata["height"] = dimensions
        metadata["valid"] = True
        return metadata
    dimensions = None
    if suffix == ".png":
        dimensions = png_dimensions(data)
    elif suffix in {".jpg", ".jpeg"}:
        dimensions = jpeg_dimensions(data)
    elif suffix == ".gif":
        dimensions = gif_dimensions(data)
    elif suffix == ".webp":
        dimensions = webp_dimensions(data)
    if not dimensions:
        metadata["reason"] = "could not parse asset dimensions"
        return metadata
    metadata["width"], metadata["height"] = dimensions
    metadata["valid"] = True
    return metadata


def asset_evidence_matches_metadata(text: str, metadata: dict) -> bool:
    normalized = normalized_text(text)
    mime = metadata.get("mime")
    width = metadata.get("width")
    height = metadata.get("height")
    if mime and mime.lower() not in normalized:
        return False
    if width is not None and height is not None:
        width_text = str(int(width)) if isinstance(width, float) and width.is_integer() else str(width)
        height_text = str(int(height)) if isinstance(height, float) and height.is_integer() else str(height)
        compact = f"{width_text}x{height_text}"
        spaced = f"{width_text} x {height_text}"
        named = f"width {width_text} height {height_text}"
        if compact not in normalized and spaced not in normalized and named not in normalized:
            return False
    return True


def parse_interface_inventory_rows(text: str, report_path: Path) -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    malformed_rows: list[str] = []
    in_inventory = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("## interface inventory"):
            in_inventory = True
            continue
        if in_inventory and stripped.startswith("## ") and not stripped.lower().startswith("## interface inventory"):
            break
        if not in_inventory or not stripped.startswith("|"):
            continue
        columns = split_markdown_row(stripped)
        if [column.lower() for column in columns[:5]] == [
            "file",
            "surface",
            "visible text/control/message",
            "expected behavior path",
            "actual implementation notes",
        ]:
            continue
        if is_separator_row(columns):
            continue
        if len(columns) != 5 or any(not column for column in columns):
            malformed_rows.append(stripped)
            continue
        rows.append(
            {
                "file": columns[0].strip("`").strip(),
                "surface": columns[1],
                "visible_text": columns[2],
                "expected_behavior_path": columns[3],
                "actual_implementation_notes": columns[4],
                "report": str(report_path),
            }
        )
    return rows, malformed_rows


def parse_finding_blocks(findings_body: str) -> list[dict]:
    lines = findings_body.splitlines()
    heading_indexes = [index for index, line in enumerate(lines) if FINDING_HEADING_RE.match(line.strip())]
    blocks = []
    for position, start in enumerate(heading_indexes):
        end = heading_indexes[position + 1] if position + 1 < len(heading_indexes) else len(lines)
        block_lines = lines[start + 1 : end]
        fields = {}
        for line in block_lines:
            match = re.match(r"^-\s*([^:]+):\s*(.*)$", line.strip())
            if match:
                fields[match.group(1).strip().lower()] = match.group(2).strip()
        blocks.append(
            {
                "heading": lines[start].strip(),
                "fields": fields,
                "text": "\n".join([lines[start], *block_lines]).strip(),
            }
        )
    return blocks


def has_visual_danger_finding(findings_body: str) -> bool:
    normalized = re.sub(r"[\s.]+", " ", findings_body.strip().lower()).strip()
    if not normalized or normalized in NO_FINDINGS_SENTINELS:
        return False
    for block in parse_finding_blocks(findings_body):
        text = normalized_text(block.get("text", ""))
        if VISUAL_DANGER_RE.search(text) or any(
            token in text
            for token in ("journey usability", "decision path", "rendered journey", "readability", "contrast", "scannable")
        ):
            return True
    return False


def validate_findings_schema(findings_body: str) -> list[dict]:
    stripped = findings_body.strip()
    if not stripped:
        return []
    normalized = re.sub(r"[\s.]+", " ", stripped.lower()).strip()
    if normalized in NO_FINDINGS_SENTINELS:
        return []

    lines = findings_body.splitlines()
    heading_indexes = [index for index, line in enumerate(lines) if FINDING_HEADING_RE.match(line.strip())]
    malformed_headings = [
        line.strip()
        for line in lines
        if line.strip().startswith("###") and not FINDING_HEADING_RE.match(line.strip())
    ]
    issues: list[dict] = []
    if malformed_headings:
        issues.append(
            {
                "section": "findings",
                "reason": "finding headings must match '### P0/P1/P2/P3 - Short title'",
                "headings": malformed_headings,
            }
        )
    if not heading_indexes:
        issues.append(
            {
                "section": "findings",
                "reason": "findings must use severity subsections or an explicit no-findings sentinel",
            }
        )
        return issues

    for block in parse_finding_blocks(findings_body):
        missing = sorted(REQUIRED_FINDING_FIELDS - set(block["fields"]))
        if missing:
            issues.append(
                {
                    "section": "findings",
                    "heading": block["heading"],
                    "reason": "finding is missing required fields",
                    "missing": missing,
                }
            )
    return issues


def validate_journey_findings_semantics(
    findings_body: str,
    known_source_files: set[str],
    interface_files: set[str],
) -> list[dict]:
    stripped = findings_body.strip()
    if not stripped:
        return []
    normalized = re.sub(r"[\s.]+", " ", stripped.lower()).strip()
    if normalized in NO_FINDINGS_SENTINELS:
        return []

    issues: list[dict] = []
    for block in parse_finding_blocks(findings_body):
        fields = block["fields"]
        file_refs = PATH_IN_BACKTICKS_RE.findall(fields.get("files", ""))
        if not file_refs:
            issues.append(
                {
                    "section": "findings",
                    "heading": block["heading"],
                    "reason": "Files field must contain one or more backticked manifest source files",
                }
            )
            continue
        unknown_refs = sorted(set(file_refs) - known_source_files)
        if unknown_refs:
            issues.append(
                {
                    "section": "findings",
                    "heading": block["heading"],
                    "reason": "Files field references files outside the manifest source inventory",
                    "files": unknown_refs,
                }
            )
        evidence = fields.get("evidence", "")
        if is_boilerplate_value(evidence) or len(plain_cell(evidence)) < 12:
            issues.append(
                {
                    "section": "findings",
                    "heading": block["heading"],
                    "reason": "Evidence field must contain concrete non-boilerplate journey/source detail",
                    "actual": evidence,
                }
            )
        for field_name in REQUIRED_FINDING_FIELDS - {"files", "evidence", "interface evidence"}:
            value = fields.get(field_name, "")
            if is_boilerplate_value(value) or len(plain_cell(value)) < 12:
                issues.append(
                    {
                        "section": "findings",
                        "heading": block["heading"],
                        "field": field_name,
                        "reason": "required journey finding field must contain meaningful non-boilerplate content",
                        "actual": value,
                    }
                )
        if set(file_refs) & interface_files:
            interface_evidence = fields.get("interface evidence", "")
            if is_boilerplate_value(interface_evidence) or len(plain_cell(interface_evidence)) < 4:
                issues.append(
                    {
                        "section": "findings",
                        "heading": block["heading"],
                        "reason": "Interface journey findings must include concrete visible label/control/message evidence",
                        "actual": interface_evidence,
                    }
                )
    return issues


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_report(report_path: Path, known_batch_ids: set[str]) -> dict:
    try:
        text = report_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Report file is not valid UTF-8: {report_path}") from exc
    except OSError as exc:
        raise ValueError(f"Report file could not be read: {report_path}: {exc}") from exc
    rows: list[dict] = []
    malformed_rows: list[str] = []
    in_coverage = False
    bodies = section_bodies(text)
    ordered_sections = [
        match.group(1).strip().lower()
        for line in text.splitlines()
        if (match := SECTION_RE.match(line.strip()))
    ]
    sections = set(ordered_sections)
    run_ids = declared_run_ids(text)
    declared_ids = declared_batch_ids(text)
    file_batch_id = filename_batch_id(report_path)
    known_declared_ids = [batch_id for batch_id in declared_ids if batch_id in known_batch_ids]
    batch_id = known_declared_ids[0] if len(known_declared_ids) == 1 else None
    interface_rows, malformed_interface_rows = parse_interface_inventory_rows(text, report_path)

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("## file coverage"):
            in_coverage = True
            continue
        if in_coverage and stripped.startswith("## ") and not stripped.lower().startswith("## file coverage"):
            break
        if not in_coverage or not stripped.startswith("|"):
            continue
        columns = split_markdown_row(stripped)
        if [column.lower() for column in columns[:4]] == ["file", "status", "sha-256", "purpose"]:
            continue
        if is_separator_row(columns):
            continue
        if len(columns) != 4 or not columns[0] or not columns[1] or not columns[2] or not columns[3]:
            malformed_rows.append(stripped)
            continue
        sha_value = columns[2].strip("`").strip()
        if not SHA256_RE.match(sha_value):
            malformed_rows.append(f"{stripped} (invalid SHA-256 digest)")
            continue
        rows.append(
            {
                "file": columns[0].strip("`").strip(),
                "status": columns[1].strip().upper(),
                "sha256": sha_value.lower(),
                "purpose": columns[3],
                "report": str(report_path),
            }
        )

    narrative_issues = []
    for section in ("batch summary", "findings", "no finding notes", "open questions"):
        if not bodies.get(section):
            narrative_issues.append({"section": section, "reason": "section body is empty"})
    narrative_issues.extend(validate_file_coverage_purposes(rows))
    narrative_issues.extend(validate_findings_schema(bodies.get("findings", "")))
    evidence_text = f"{bodies.get('findings', '')}\n{bodies.get('no finding notes', '')}"
    missing_evidence_files = sorted(
        row["file"]
        for row in rows
        if row.get("status") == "CHECKED" and row["file"] not in evidence_text
    )
    if missing_evidence_files:
        narrative_issues.append(
            {
                "section": "findings/no finding notes",
                "reason": "checked files must be referenced in Findings or No Finding Notes",
                "files": missing_evidence_files,
            }
        )

    return {
        "report": str(report_path),
        "run_ids": run_ids,
        "batch_id": batch_id,
        "filename_batch_id": file_batch_id,
        "declared_batch_ids": declared_ids,
        "rows": rows,
        "malformed_rows": malformed_rows,
        "interface_rows": interface_rows,
        "malformed_interface_rows": malformed_interface_rows,
        "interface_inventory_body": bodies.get("interface inventory", ""),
        "findings_body": bodies.get("findings", ""),
        "finding_blocks": parse_finding_blocks(bodies.get("findings", "")),
        "missing_sections": [section for section in REQUIRED_SECTIONS if section not in sections],
        "section_order": ordered_sections,
        "section_shape_mismatch": ordered_sections != REQUIRED_SECTION_LIST,
        "narrative_issues": narrative_issues,
    }


def report_location_issue(manifest_path: Path, parsed: dict) -> dict | None:
    report_path = Path(parsed["report"]).resolve()
    expected_root = (manifest_path.parent / "reports").resolve()
    batch_id = parsed["filename_batch_id"] or parsed["batch_id"]
    expected_rel = f"reports/{batch_id}.md" if batch_id else "reports/batch_###.md"
    try:
        rel_path = report_path.relative_to(manifest_path.parent.resolve()).as_posix()
    except ValueError:
        return {
            "report": str(report_path),
            "expected": expected_rel,
            "reason": "report is outside the audit output directory",
        }
    if report_path.parent != expected_root:
        return {
            "report": str(report_path),
            "expected": expected_rel,
            "actual": rel_path,
            "reason": "report must be directly under the audit output reports directory",
        }
    if batch_id and rel_path != expected_rel:
        return {
            "report": str(report_path),
            "expected": expected_rel,
            "actual": rel_path,
            "reason": "report filename/path does not match its batch id",
        }
    return None


def interface_evidence_is_source_backed(
    interface_evidence: str,
    file_refs: list[str],
    interface_files: set[str],
    source_text_getter,
    inventory_visible_by_file: dict[str, set[str]],
) -> bool:
    evidence = plain_cell(interface_evidence)
    normalized = normalized_text(evidence)
    if not evidence or is_boilerplate_value(evidence):
        return False
    if normalized.startswith("visible control text "):
        evidence = evidence[len("visible control text ") :].strip(" `\"'")
    if normalized.startswith("visible text "):
        evidence = evidence[len("visible text ") :].strip(" `\"'")
    if normalized.startswith("visible label "):
        evidence = evidence[len("visible label ") :].strip(" `\"'")
    if normalized.startswith("source anchor "):
        evidence = evidence[len("source anchor ") :].strip(" `\"'")
    if normalized.startswith("exact visible text "):
        evidence = evidence[len("exact visible text ") :].strip(" `\"'")
    evidence = evidence.strip().strip(".")
    backticked = PATH_IN_BACKTICKS_RE.findall(evidence)
    if backticked:
        evidence = backticked[-1]
    evidence = evidence.strip("`\"'.")
    normalized_evidence = normalized_text(evidence)
    if not evidence or normalized_evidence in {"source-backed", "source anchor"}:
        return False
    for rel_path in file_refs:
        if rel_path not in interface_files:
            continue
        if evidence in inventory_visible_by_file.get(rel_path, set()):
            return True
        if source_text_getter and evidence in source_text_getter(rel_path):
            return True
    return False


def validate_finding_bindings(
    parsed: dict,
    expected_batch: set[str],
    interface_files: set[str],
    source_text_getter=None,
    inventory_visible_by_file: dict[str, set[str]] | None = None,
) -> list[dict]:
    inventory_visible_by_file = inventory_visible_by_file or {}
    issues = []
    for block in parsed["finding_blocks"]:
        fields = block["fields"]
        file_refs = PATH_IN_BACKTICKS_RE.findall(fields.get("files", ""))
        if not file_refs:
            issues.append(
                {
                    "section": "findings",
                    "heading": block["heading"],
                    "reason": "Files field must contain one or more backticked repo-relative paths",
                }
            )
            continue
        unknown_refs = sorted(set(file_refs) - expected_batch)
        if unknown_refs:
            issues.append(
                {
                    "section": "findings",
                    "heading": block["heading"],
                    "reason": "Files field references files outside this batch",
                    "files": unknown_refs,
                }
            )
        evidence = fields.get("evidence", "")
        if is_boilerplate_value(evidence) or len(plain_cell(evidence)) < 12:
            issues.append(
                {
                    "section": "findings",
                    "heading": block["heading"],
                    "reason": "Evidence field must contain concrete non-boilerplate detail",
                    "actual": evidence,
                }
            )
        for field_name in REQUIRED_FINDING_FIELDS - {"files", "evidence", "interface evidence"}:
            value = fields.get(field_name, "")
            if is_boilerplate_value(value) or len(plain_cell(value)) < 12:
                issues.append(
                    {
                        "section": "findings",
                        "heading": block["heading"],
                        "field": field_name,
                        "reason": "required finding field must contain meaningful non-boilerplate content",
                        "actual": value,
                    }
                )
        if set(file_refs) & interface_files:
            interface_evidence = fields.get("interface evidence", "")
            if is_boilerplate_value(interface_evidence):
                issues.append(
                    {
                        "section": "findings",
                        "heading": block["heading"],
                        "reason": "Interface findings must include concrete visible label/control/message evidence",
                        "actual": interface_evidence,
                    }
                )
            elif not interface_evidence_is_source_backed(
                interface_evidence,
                file_refs,
                interface_files,
                source_text_getter,
                inventory_visible_by_file,
            ):
                issues.append(
                    {
                        "section": "findings",
                        "heading": block["heading"],
                        "reason": "Interface evidence must match source-visible text/control/message or an accepted interface inventory row",
                        "actual": interface_evidence,
                    }
                )
    return issues


def verify(manifest_path: Path, reports: list[Path], *, skip_current_hash_check: bool = False) -> dict:
    manifest = load_manifest(manifest_path)
    expected_source_files = manifest["expected_files"]
    expected_hashes = manifest["expected_hashes"]
    expected_by_batch = manifest["expected_by_batch"]
    expected_files_by_batch = manifest.get("expected_files_by_batch", expected_by_batch)
    expected_unit_to_file = manifest.get("expected_unit_to_file", {})
    coverage_unit_by_id = {
        unit.get("unit_id"): unit
        for unit in manifest.get("coverage_units_normalized", [])
        if isinstance(unit, dict) and isinstance(unit.get("unit_id"), str)
    }
    expected = set(expected_hashes)
    expected_source_hashes = {
        item["rel_path"]: item.get("sha256")
        for item in manifest.get("source_files", [])
        if isinstance(item, dict) and isinstance(item.get("rel_path"), str)
    }
    known_batch_ids = set(expected_by_batch)
    expected_run_id = manifest.get("run_id")
    repo_root_raw = manifest.get("repo_root")
    repo_root_text = repo_root_raw.strip() if isinstance(repo_root_raw, str) else ""
    repo_root = Path(repo_root_text).expanduser() if repo_root_text else None
    source_text_checks_enabled = repo_root is not None and repo_root.exists() and repo_root.is_dir()
    source_text_cache: dict[str, str] = {}

    def source_text(rel_path: str) -> str:
        if not source_text_checks_enabled or repo_root is None:
            return ""
        if rel_path not in source_text_cache:
            path = repo_root / rel_path
            try:
                source_text_cache[rel_path] = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                source_text_cache[rel_path] = ""
        return source_text_cache[rel_path]

    def source_text_for_unit(unit_id: str) -> str:
        rel_path = expected_unit_to_file.get(unit_id, unit_id)
        unit = coverage_unit_by_id.get(unit_id, {})
        start_byte = unit.get("start_byte") if isinstance(unit, dict) else None
        end_byte = unit.get("end_byte") if isinstance(unit, dict) else None
        if (
            source_text_checks_enabled
            and repo_root is not None
            and isinstance(start_byte, int)
            and isinstance(end_byte, int)
            and start_byte >= 1
            and end_byte >= start_byte
        ):
            try:
                with (repo_root / rel_path).open("rb") as handle:
                    handle.seek(start_byte - 1)
                    return handle.read(end_byte - start_byte + 1).decode("utf-8", errors="ignore")
            except OSError:
                return ""
        text = source_text(rel_path)
        start_line = unit.get("start_line") if isinstance(unit, dict) else None
        end_line = unit.get("end_line") if isinstance(unit, dict) else None
        if not isinstance(start_line, int) or not isinstance(end_line, int):
            return text
        lines = text.splitlines()
        return "\n".join(lines[start_line - 1 : end_line])

    unresolved_scope_warnings, excluded_file_mismatches = verify_excluded_files(manifest_path, manifest)
    completion_marker_mismatches = verify_completion_marker(manifest_path, manifest)

    parsed_reports = [parse_report(report, known_batch_ids) for report in reports]
    source_interface_relevance = {
        item["rel_path"]: item.get("interface_relevant") is True
        for item in manifest.get("source_files", [])
        if isinstance(item, dict) and isinstance(item.get("rel_path"), str)
    }
    source_kind_by_file = {
        item["rel_path"]: item.get("kind")
        for item in manifest.get("source_files", [])
        if isinstance(item, dict) and isinstance(item.get("rel_path"), str)
    }
    expected_interface_by_batch = {
        batch_id: {rel_path for rel_path in files if source_interface_relevance.get(rel_path)}
        for batch_id, files in expected_files_by_batch.items()
    }
    report_rel_by_batch = {}
    report_location_mismatches = []
    for parsed in parsed_reports:
        location_issue = report_location_issue(manifest_path, parsed)
        if location_issue:
            report_location_mismatches.append(location_issue)
        batch_id = parsed["batch_id"]
        if not batch_id:
            continue
        try:
            report_rel = Path(parsed["report"]).resolve().relative_to(manifest_path.parent).as_posix()
        except ValueError:
            report_rel = str(Path(parsed["report"]).resolve())
        report_rel_by_batch[batch_id] = report_rel
    effort_ledger_mismatches = verify_effort_ledger(
        manifest_path, manifest, known_batch_ids, report_rel_by_batch
    )
    observed: dict[str, list[dict]] = defaultdict(list)
    for parsed in parsed_reports:
        for row in parsed["rows"]:
            observed[row["file"]].append(row)

    observed_paths = set(observed)
    missing = sorted(expected - observed_paths)
    extra = sorted(observed_paths - expected)
    duplicate = sorted(path for path, rows in observed.items() if len(rows) > 1)
    unchecked = sorted(
        path
        for path in expected & observed_paths
        if any(row["status"] != "CHECKED" for row in observed[path])
    )

    batch_counts = Counter(parsed["batch_id"] for parsed in parsed_reports if parsed["batch_id"])
    missing_batch_reports = sorted(batch_id for batch_id in known_batch_ids if batch_counts[batch_id] == 0)
    duplicate_batch_reports = sorted(batch_id for batch_id, count in batch_counts.items() if count > 1)
    unassigned_reports = sorted(parsed["report"] for parsed in parsed_reports if not parsed["batch_id"])
    run_id_mismatches = []
    for parsed in parsed_reports:
        run_ids = parsed["run_ids"]
        reasons = []
        if len(run_ids) != 1:
            reasons.append(f"expected exactly one Run ID, found {len(run_ids)}")
        elif expected_run_id and run_ids[0] != expected_run_id:
            reasons.append(f"declared Run ID {run_ids[0]} does not match manifest {expected_run_id}")
        if reasons:
            run_id_mismatches.append({"report": parsed["report"], "run_ids": run_ids, "reasons": reasons})

    report_hash_mismatches = []
    for path, rows in observed.items():
        expected_hash = expected_hashes.get(path)
        if not expected_hash:
            continue
        for row in rows:
            if row.get("sha256") != expected_hash:
                report_hash_mismatches.append(
                    {
                        "file": path,
                        "report": row["report"],
                        "expected": expected_hash,
                        "reported": row.get("sha256"),
                    }
                )

    current_hash_mismatches = []
    current_hash_errors = []
    source_text_errors = []
    verification_warnings = []
    if not source_text_checks_enabled:
        source_text_errors.append(
            {
                "repo_root": str(repo_root) if repo_root is not None else None,
                "reason": "manifest repo_root is missing or not a directory; source-backed interface, placeholder, dead-control, and asset checks cannot run",
            }
        )
    if skip_current_hash_check:
        verification_warnings.append(
            {
                "flag": "--skip-current-hash-check",
                "reason": "current source fingerprint freshness check was skipped; verification is degraded",
            }
        )
    elif repo_root is None or not repo_root.exists() or not repo_root.is_dir():
        current_hash_errors.append(
            {
                "repo_root": str(repo_root) if repo_root is not None else None,
                "reason": "manifest repo_root is missing or not a directory; current SHA-256 check cannot run",
            }
        )
    else:
        for rel_path, expected_hash in expected_source_hashes.items():
            if not expected_hash:
                continue
            fs_path = repo_root / rel_path
            if not fs_path.is_file():
                current_hash_mismatches.append(
                    {"file": rel_path, "expected": expected_hash, "current": None, "reason": "missing"}
                )
                continue
            try:
                current_hash = sha256_file(fs_path)
            except OSError as exc:
                current_hash_errors.append(
                    {
                        "file": rel_path,
                        "expected": expected_hash,
                        "current": None,
                        "reason": f"current SHA-256 check could not read file: {exc}",
                    }
                )
                continue
            if current_hash != expected_hash:
                current_hash_mismatches.append(
                    {"file": rel_path, "expected": expected_hash, "current": current_hash, "reason": "changed"}
                )
    batch_id_mismatches = []
    for parsed in parsed_reports:
        declared_ids = parsed["declared_batch_ids"]
        file_batch_id = parsed["filename_batch_id"]
        mismatch_reasons = []
        if len(declared_ids) != 1:
            mismatch_reasons.append(f"expected exactly one declared Batch ID, found {len(declared_ids)}")
        elif declared_ids[0] not in known_batch_ids:
            mismatch_reasons.append(f"declared unknown Batch ID {declared_ids[0]}")
        if file_batch_id and declared_ids and declared_ids[0] != file_batch_id:
            mismatch_reasons.append(f"filename Batch ID {file_batch_id} does not match declared {declared_ids[0]}")
        if mismatch_reasons:
            batch_id_mismatches.append(
                {
                    "report": parsed["report"],
                    "filename_batch_id": file_batch_id,
                    "declared_batch_ids": declared_ids,
                    "reasons": mismatch_reasons,
                }
            )
    malformed = [
        {"report": parsed["report"], "rows": parsed["malformed_rows"]}
        for parsed in parsed_reports
        if parsed["malformed_rows"]
    ]
    interface_inventory_issues = []
    for parsed in parsed_reports:
        batch_id = parsed["batch_id"]
        if not batch_id or batch_id not in expected_by_batch:
            continue
        expected_interface_files = expected_interface_by_batch.get(batch_id, set())
        observed_interface_files = [row["file"] for row in parsed["interface_rows"]]
        observed_interface_set = set(observed_interface_files)
        issues = []
        if parsed["malformed_interface_rows"]:
            issues.append({"reason": "malformed interface inventory rows", "rows": parsed["malformed_interface_rows"]})
        missing_interface_files = sorted(expected_interface_files - observed_interface_set)
        extra_interface_files = sorted(observed_interface_set - expected_interface_files)
        if expected_interface_files:
            if missing_interface_files:
                issues.append({"reason": "missing interface inventory rows", "files": missing_interface_files})
            if extra_interface_files:
                issues.append({"reason": "interface inventory rows for non-interface files", "files": extra_interface_files})
            visible_by_file: dict[str, set[str]] = defaultdict(set)
            for row in parsed["interface_rows"]:
                if row["file"] not in expected_interface_files:
                    continue
                visible_by_file[row["file"]].add(plain_cell(row["visible_text"]))
                for field in ("visible_text", "expected_behavior_path", "actual_implementation_notes"):
                    if is_boilerplate_value(row[field]):
                        issues.append(
                            {
                                "reason": "interface inventory row contains boilerplate text",
                                "file": row["file"],
                                "field": field,
                                "actual": row[field],
                            }
                        )
                expected_path_note = normalized_text(row["expected_behavior_path"])
                implementation_note = normalized_text(row["actual_implementation_notes"])
                if any(phrase in expected_path_note for phrase in GENERIC_INTERFACE_PHRASES) or any(
                    phrase in implementation_note for phrase in GENERIC_INTERFACE_PHRASES
                ):
                    issues.append(
                        {
                            "reason": "interface inventory row must trace behavior to concrete implementation anchors or static metadata rationale",
                            "file": row["file"],
                            "expected_behavior_path": row["expected_behavior_path"],
                            "actual_implementation_notes": row["actual_implementation_notes"],
                        }
                    )
                visible_text = plain_cell(row["visible_text"])
                if (
                    source_text_checks_enabled
                    and normalized_text(visible_text) != "none found"
                    and visible_text not in source_text(row["file"])
                ):
                    issues.append(
                        {
                            "reason": "visible text/control/message is not present in the source file",
                            "file": row["file"],
                            "visible_text": row["visible_text"],
                        }
                    )
                if source_text_checks_enabled and repo_root is not None and source_kind_by_file.get(row["file"]) == "source/ui-asset":
                    asset_evidence = f"{row['expected_behavior_path']} {row['actual_implementation_notes']}"
                    metadata = asset_metadata_for(repo_root / row["file"])
                    if not metadata["valid"]:
                        issues.append(
                            {
                                "reason": "source-backed UI asset could not be parsed for verifier-backed metadata",
                                "file": row["file"],
                                "metadata": metadata,
                            }
                        )
                    elif not asset_evidence_matches_metadata(asset_evidence, metadata):
                        issues.append(
                            {
                                "reason": "source-backed UI asset inventory must cite verifier-backed MIME/type and dimensions when available",
                                "file": row["file"],
                                "expected_metadata": metadata,
                                "expected_behavior_path": row["expected_behavior_path"],
                                "actual_implementation_notes": row["actual_implementation_notes"],
                            }
                        )
            if source_text_checks_enabled:
                for rel_path in sorted(expected_interface_files):
                    missing_hints = [
                        hint for hint in visible_text_hints(rel_path, source_text(rel_path))
                        if hint not in visible_by_file.get(rel_path, set())
                    ]
                    if missing_hints:
                        issues.append(
                            {
                                "reason": "interface inventory is missing visible text/control/message hints",
                                "file": rel_path,
                                "missing_visible_text": missing_hints,
                            }
                        )
        else:
            body = parsed["interface_inventory_body"].strip()
            sentinel = "No interface-relevant files in this batch."
            if observed_interface_files:
                issues.append(
                    {
                        "reason": "non-interface batch should not include interface inventory rows",
                        "files": sorted(observed_interface_set),
                    }
                )
            if body != sentinel:
                issues.append(
                    {
                        "reason": "non-interface batch must use exact no-interface sentinel",
                        "expected": sentinel,
                        "actual": parsed["interface_inventory_body"].strip(),
                    }
                )
        if issues:
            interface_inventory_issues.append({"batch": batch_id, "report": parsed["report"], "issues": issues})
    finding_schema_issues = []
    placeholder_omissions = []
    interface_control_omissions = []
    for parsed in parsed_reports:
        batch_id = parsed["batch_id"]
        if not batch_id or batch_id not in expected_by_batch:
            continue
        expected_batch = expected_files_by_batch.get(batch_id, set())
        interface_files = expected_interface_by_batch.get(batch_id, set())
        inventory_visible_by_file: dict[str, set[str]] = defaultdict(set)
        for row in parsed["interface_rows"]:
            inventory_visible_by_file[row["file"]].add(plain_cell(row["visible_text"]))
        binding_issues = validate_finding_bindings(
            parsed,
            expected_batch,
            interface_files,
            source_text if source_text_checks_enabled else None,
            inventory_visible_by_file,
        )
        if binding_issues:
            finding_schema_issues.append({"batch": batch_id, "report": parsed["report"], "issues": binding_issues})
        findings_body = parsed["findings_body"]
        normalized_findings = re.sub(r"[\s.]+", " ", findings_body.strip().lower()).strip()
        finding_files = {
            file_ref
            for block in parsed["finding_blocks"]
            for file_ref in PATH_IN_BACKTICKS_RE.findall(block["fields"].get("files", ""))
        }
        for unit_id in sorted(expected_by_batch[batch_id]):
            if not source_text_checks_enabled:
                continue
            rel_path = expected_unit_to_file.get(unit_id, unit_id)
            unit_text = source_text_for_unit(unit_id)
            markers = placeholder_markers_for(rel_path, unit_text)
            marker_blocks = [
                block
                for block in parsed["finding_blocks"]
                if rel_path in PATH_IN_BACKTICKS_RE.findall(block["fields"].get("files", ""))
            ]
            missing_markers = uncovered_placeholder_markers(marker_blocks, markers)
            if markers and (
                normalized_findings in NO_FINDINGS_SENTINELS
                or rel_path not in finding_files
                or missing_markers
            ):
                placeholder_omissions.append(
                    {
                        "batch": batch_id,
                        "report": parsed["report"],
                        "file": unit_id,
                        "source_file": rel_path,
                        "markers": markers,
                        "missing_markers": missing_markers or markers,
                        "reason": "source file contains placeholder markers but report Findings do not cover the marker details",
                    }
                )
            control_markers = interface_control_markers_for(rel_path, unit_text)
            control_blocks = marker_blocks
            missing_control_markers = uncovered_interface_control_markers(control_blocks, control_markers)
            if control_markers and (
                normalized_findings in NO_FINDINGS_SENTINELS
                or rel_path not in finding_files
                or missing_control_markers
            ):
                interface_control_omissions.append(
                    {
                        "batch": batch_id,
                        "report": parsed["report"],
                        "file": unit_id,
                        "source_file": rel_path,
                        "markers": control_markers,
                        "missing_markers": missing_control_markers or control_markers,
                        "reason": "interface file contains dead, no-op, or unlabeled controls but report Findings do not cover them",
                    }
                )
    missing_sections = [
        {"report": parsed["report"], "sections": parsed["missing_sections"]}
        for parsed in parsed_reports
        if parsed["missing_sections"]
    ]
    section_shape_mismatches = [
        {
            "report": parsed["report"],
            "expected": REQUIRED_SECTION_LIST,
            "actual": parsed["section_order"],
        }
        for parsed in parsed_reports
        if parsed["section_shape_mismatch"]
    ]
    semantic_report_issues = [
        {"report": parsed["report"], "issues": parsed["narrative_issues"]}
        for parsed in parsed_reports
        if parsed["narrative_issues"]
    ]

    batch_mismatches = []
    for parsed in parsed_reports:
        batch_id = parsed["batch_id"]
        if not batch_id or batch_id not in expected_by_batch:
            continue
        expected_batch = expected_by_batch[batch_id]
        observed_batch = {row["file"] for row in parsed["rows"]}
        missing_in_batch = sorted(expected_batch - observed_batch)
        extra_in_batch = sorted(observed_batch - expected_batch)
        unchecked_in_batch = sorted(
            row["file"]
            for row in parsed["rows"]
            if row["file"] in expected_batch and row["status"] != "CHECKED"
        )
        if missing_in_batch or extra_in_batch or unchecked_in_batch:
            batch_mismatches.append(
                {
                    "batch": batch_id,
                    "report": parsed["report"],
                    "missing": missing_in_batch,
                    "extra": extra_in_batch,
                    "unchecked": unchecked_in_batch,
                }
            )

    ok = not any(
        [
            missing,
            extra,
            duplicate,
            unchecked,
            missing_batch_reports,
            duplicate_batch_reports,
            unassigned_reports,
            report_location_mismatches,
            run_id_mismatches,
            report_hash_mismatches,
            current_hash_mismatches,
            current_hash_errors,
            source_text_errors,
            verification_warnings,
            unresolved_scope_warnings,
            excluded_file_mismatches,
            completion_marker_mismatches,
            effort_ledger_mismatches,
            batch_id_mismatches,
            malformed,
            interface_inventory_issues,
            finding_schema_issues,
            placeholder_omissions,
            interface_control_omissions,
            missing_sections,
            section_shape_mismatches,
            semantic_report_issues,
            batch_mismatches,
        ]
    )

    return {
        "expected_count": len(expected),
        "reported_count": len(observed_paths),
        "expected_batch_count": len(known_batch_ids),
        "report_files": [str(path) for path in reports],
        "effort_ledger_provenance_note": (
            "Ledger-recorded effort consistency only; scheduler effort settings are not independently verified by this script."
        ),
        "effort_verification_scope": "ledger-recorded",
        "missing": missing,
        "extra": extra,
        "duplicate": duplicate,
        "unchecked": unchecked,
        "missing_batch_reports": missing_batch_reports,
        "duplicate_batch_reports": duplicate_batch_reports,
        "unassigned_reports": unassigned_reports,
        "report_location_mismatches": report_location_mismatches,
        "run_id_mismatches": run_id_mismatches,
        "report_hash_mismatches": report_hash_mismatches,
        "current_hash_mismatches": current_hash_mismatches,
        "current_hash_errors": current_hash_errors,
        "source_text_errors": source_text_errors,
        "current_hash_check_skipped": skip_current_hash_check,
        "verification_warnings": verification_warnings,
        "unresolved_scope_warnings": unresolved_scope_warnings,
        "excluded_file_mismatches": excluded_file_mismatches,
        "completion_marker_mismatches": completion_marker_mismatches,
        "effort_ledger_mismatches": effort_ledger_mismatches,
        "batch_id_mismatches": batch_id_mismatches,
        "malformed_rows": malformed,
        "interface_inventory_issues": interface_inventory_issues,
        "finding_schema_issues": finding_schema_issues,
        "placeholder_omissions": placeholder_omissions,
        "interface_control_omissions": interface_control_omissions,
        "missing_sections": missing_sections,
        "section_shape_mismatches": section_shape_mismatches,
        "semantic_report_issues": semantic_report_issues,
        "batch_mismatches": batch_mismatches,
        "ok": ok,
    }


def print_values(key: str, values: list) -> None:
    print(f"{key}: {len(values)}")
    for value in values:
        print(f"  - {value}")


def print_human(result: dict) -> None:
    print(f"Expected files: {result['expected_count']}")
    print(f"Reported files: {result['reported_count']}")
    print(f"Expected batches: {result['expected_batch_count']}")
    print(f"Reports read: {len(result['report_files'])}")
    print(f"Effort ledger provenance: {result['effort_ledger_provenance_note']}")
    for key in (
        "missing",
        "unchecked",
        "duplicate",
        "extra",
        "missing_batch_reports",
        "duplicate_batch_reports",
        "unassigned_reports",
        "report_location_mismatches",
        "run_id_mismatches",
        "report_hash_mismatches",
        "current_hash_mismatches",
        "current_hash_errors",
        "source_text_errors",
        "verification_warnings",
        "unresolved_scope_warnings",
        "excluded_file_mismatches",
        "completion_marker_mismatches",
        "effort_ledger_mismatches",
        "batch_id_mismatches",
        "malformed_rows",
        "interface_inventory_issues",
        "finding_schema_issues",
        "placeholder_omissions",
        "interface_control_omissions",
        "missing_sections",
        "section_shape_mismatches",
        "semantic_report_issues",
        "batch_mismatches",
    ):
        print_values(key, result[key])
    print(f"ok: {str(result['ok']).lower()}")


def emit_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2))


def main() -> int:
    args = parse_args()
    manifest_path = Path(args.manifest).expanduser().resolve()
    reports = iter_report_files(args.reports)
    result = verify(manifest_path, reports, skip_current_hash_check=args.skip_current_hash_check)
    if args.json:
        emit_json(result)
    else:
        print_human(result)
    return 0 if result["ok"] else 1


def wants_json_output(argv: list[str]) -> bool:
    return "--json" in argv


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, OSError, ValueError) as exc:
        if wants_json_output(sys.argv[1:]):
            emit_json({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}})
        else:
            print(str(exc), file=sys.stderr)
        raise SystemExit(2)
