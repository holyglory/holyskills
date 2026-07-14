#!/usr/bin/env python3
"""Fail when the five-skill repository regains a DevCoordinator dependency."""

from __future__ import annotations

import argparse
import json
import re
import stat
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


CANONICAL_SKILLS = {
    "formal-web-ui-verification",
    "full-repo-audit",
    "full-repo-test-coverage-audit",
    "ui-implementation-audit",
    "user-journey-docs-audit",
}

MOVED_PATHS = (
    "skills/codex-dev-coordinator",
    "skills/postgres-docker-backup",
    "apps/CodexOpsConsole",
    "apps/DevOpsBoard",
    "apps/DevOpsConsole",
)

HISTORICAL_DOCUMENTS = {
    "DecisionHistory.md",
    "MERGE_IMPROVEMENT_LEDGER.md",
}

DECISION_DETAIL_LINK = re.compile(
    r"\(DecisionDetails/(?P<filename>D-\d{8}-\d{2}\.md)\)"
)

SELF_FILES = {
    "scripts/check_repository_boundaries.py",
    "scripts/check_repository_boundaries_self_test.py",
}

SOURCE_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".go",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".lock",
    ".mjs",
    ".plist",
    ".py",
    ".rb",
    ".service",
    ".sh",
    ".swift",
    ".toml",
    ".txt",
    ".ts",
    ".tsx",
    ".xml",
    ".yaml",
    ".yml",
}

DEPENDENCY_SURFACE_DIRECTORIES = {
    ".codex",
    ".github",
    "bin",
    "build",
    "ci",
    "deploy",
    "hooks",
    "scripts",
    "tools",
}

DEPENDENCY_SURFACE_NAMES = {
    ".gitmodules",
    "build",
    "configure",
    "dockerfile",
    "gemfile",
    "justfile",
    "makefile",
    "package-lock.json",
    "package.json",
    "podfile",
    "procfile",
    "pyproject.toml",
    "requirements.txt",
}

DIRECT_SOURCE_PATTERNS = tuple(re.compile(re.escape(path), re.IGNORECASE) for path in MOVED_PATHS)
CROSS_REPOSITORY_PATTERNS = (
    re.compile(r"\bDEVCOORDINATOR_ROOT\b"),
    re.compile(r"(?:^|[^A-Za-z0-9_])(?:/home/DevCoordinator|/Users/[^/\s]+/(?:src/)?DevCoordinator)(?:[/\s\"']|$)"),
    re.compile(r"(?:\.\./|file:|path\s*[=:]\s*[\"']?)[^\n\"']*DevCoordinator", re.IGNORECASE),
    re.compile(r"github\.com[/:]holyglory/DevCoordinator(?:\.git)?(?:[@#][A-Fa-f0-9]{7,40})?", re.IGNORECASE),
    re.compile(r"(?:^|[^A-Za-z0-9_.-])holyglory/DevCoordinator(?:[/@#]|$)", re.IGNORECASE),
    re.compile(r"\brepository\s*:\s*[\"']?(?:holyglory/)?DevCoordinator\b", re.IGNORECASE),
    re.compile(r"\bgit\s+(?:clone|fetch|submodule\s+add)\b[^\n]*\bDevCoordinator\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class Finding:
    rule: str
    path: str
    line: int | None
    detail: str


def _ignored(path: Path) -> bool:
    return any(part in {".git", ".build", "__pycache__", "node_modules"} for part in path.parts)


def _text_files(repository: Path) -> list[Path]:
    result: list[Path] = []
    for path in repository.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(repository)
        if _ignored(relative) or relative.as_posix() in SELF_FILES:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"\0" in data:
            continue
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        result.append(relative)
    return sorted(result)


def _without_installed_skill_paths(line: str) -> str:
    """Remove explicitly installed-skill examples, which are optional runtime support."""

    return re.sub(
        r"(?:\$HOME|~)/(?:\.codex|\.claude)/skills/(?:codex-dev-coordinator|postgres-docker-backup)(?:/[^\s`\"']*)?",
        "<installed-external-skill>",
        line,
        flags=re.IGNORECASE,
    )


def _historical_documents(repository: Path) -> set[str]:
    """Return root history plus exact regular detail files linked by its compact index."""

    result = set(HISTORICAL_DOCUMENTS)
    index = repository / "DecisionHistory.md"
    if not index.is_file() or index.is_symlink():
        return result
    try:
        text = index.read_text(encoding="utf-8")
    except OSError:
        return result
    for match in DECISION_DETAIL_LINK.finditer(text):
        relative = Path("DecisionDetails") / match.group("filename")
        path = repository / relative
        if path.is_file() and not path.is_symlink():
            result.add(relative.as_posix())
    return result


def _is_dependency_surface(repository: Path, relative: Path) -> bool:
    """Classify executable, runtime-config, source, build, hook, and CI text."""

    path = repository / relative
    try:
        executable = bool(path.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
    except OSError:
        executable = False
    parts = {part.lower() for part in relative.parts[:-1]}
    name = relative.name.lower()
    runtime_config = (
        name == ".env"
        or name.startswith(".env.")
        or name.endswith((".conf", ".config", ".ini", ".properties"))
    )
    return (
        executable
        or runtime_config
        or relative.suffix.lower() in SOURCE_SUFFIXES
        or bool(parts & DEPENDENCY_SURFACE_DIRECTORIES)
        or name in DEPENDENCY_SURFACE_NAMES
    )


def audit_repository(repository: Path) -> dict[str, object]:
    repository = repository.resolve()
    findings: list[Finding] = []
    historical_documents = _historical_documents(repository)

    for relative in MOVED_PATHS:
        if (repository / relative).exists() or (repository / relative).is_symlink():
            findings.append(Finding("moved-path-present", relative, None, "moved component is present at the repository tip"))

    skills_root = repository / "skills"
    if skills_root.is_dir():
        actual = {
            path.name
            for path in skills_root.iterdir()
            if path.is_dir() and not path.is_symlink() and (path / "SKILL.md").is_file()
        }
        if actual != CANONICAL_SKILLS:
            findings.append(
                Finding(
                    "canonical-skill-set",
                    "skills",
                    None,
                    f"expected {sorted(CANONICAL_SKILLS)}, found {sorted(actual)}",
                )
            )

    for relative in _text_files(repository):
        if relative.as_posix() in historical_documents:
            continue
        path = repository / relative
        is_source = _is_dependency_surface(repository, relative)
        for number, original_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            line = _without_installed_skill_paths(original_line)
            direct = next((pattern.pattern for pattern in DIRECT_SOURCE_PATTERNS if pattern.search(line)), None)
            if direct:
                findings.append(
                    Finding(
                        "moved-source-reference",
                        relative.as_posix(),
                        number,
                        "current file references a component path owned by DevCoordinator",
                    )
                )
            if is_source and any(pattern.search(line) for pattern in CROSS_REPOSITORY_PATTERNS):
                findings.append(
                    Finding(
                        "cross-repository-dependency",
                        relative.as_posix(),
                        number,
                        "source, build, runtime, or CI text depends on a DevCoordinator checkout or pin",
                    )
                )

    unique = sorted(set(findings), key=lambda finding: (finding.path, finding.line or 0, finding.rule))
    return {
        "ok": not unique,
        "canonical_skills": sorted(CANONICAL_SKILLS),
        "finding_count": len(unique),
        "findings": [asdict(finding) for finding in unique],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify that HolySkills owns exactly five skills and has no source/build/CI dependency on DevCoordinator."
    )
    parser.add_argument("--repo", default=".")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = audit_repository(Path(args.repo))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    elif report["ok"]:
        print("repository boundary check ok (5 skills; no DevCoordinator source/build/CI dependency)")
    else:
        for finding in report["findings"]:
            location = f"{finding['path']}:{finding['line']}" if finding["line"] else finding["path"]
            print(f"{location}: {finding['rule']}: {finding['detail']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
