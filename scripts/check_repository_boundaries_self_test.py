#!/usr/bin/env python3
"""Recall and false-positive tests for the HolySkills ownership boundary."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path
from shutil import rmtree
from types import ModuleType


SCRIPT = Path(__file__).with_name("check_repository_boundaries.py")


def load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_repository_boundaries", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load boundary checker")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = load_checker()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_clean_repository(root: Path) -> None:
    for name in checker.CANONICAL_SKILLS:
        write(root / "skills" / name / "SKILL.md", f"---\nname: {name}\n---\n")
    write(
        root / "skills" / "formal-web-ui-verification" / "SKILL.md",
        "Use the optional script at $HOME/.codex/skills/codex-dev-coordinator/scripts/dev_coordinator.py.\n",
    )
    write(
        root / "DecisionHistory.md",
        "# Decision History\n\n"
        "## [D-20260701-01 — Historical split](DecisionDetails/D-20260701-01.md)\n",
    )
    write(
        root / "DecisionDetails" / "D-20260701-01.md",
        "Historical migration moved skills/codex-dev-coordinator and apps/DevOpsConsole to DevCoordinator.\n",
    )
    write(
        root / "MERGE_IMPROVEMENT_LEDGER.md",
        "Historical source path apps/DevOpsBoard was retained before the split.\n",
    )
    write(
        root / "README.md",
        "The independently versioned product now lives at https://github.com/holyglory/DevCoordinator.\n",
    )
    write(
        root / "skills" / "formal-web-ui-verification" / "scripts" / "verify.mjs",
        "const args = ['--from-coordinator', '--coordinator-script', process.env.COORDINATOR_SCRIPT];\n",
    )


def rules(report: dict[str, object]) -> set[str]:
    return {finding["rule"] for finding in report["findings"]}


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    temporary = Path(tempfile.mkdtemp(prefix="holyskills-boundary-self-test-"))
    try:
        make_clean_repository(temporary)
        clean = checker.audit_repository(temporary)
        check(clean["ok"] is True, f"history and optional installed-skill support must pass: {clean['findings']}")

        unlinked_history = temporary / "DecisionDetails" / "D-20260701-02.md"
        write(unlinked_history, "Historical source path apps/DevOpsBoard was never linked.\n")
        report = checker.audit_repository(temporary)
        check(
            "moved-source-reference" in rules(report),
            "an unlinked decision-detail file must not become a history exemption",
        )
        unlinked_history.unlink()

        moved = temporary / "apps" / "DevOpsConsole"
        write(moved / "package.json", "{}\n")
        report = checker.audit_repository(temporary)
        check("moved-path-present" in rules(report), "a moved application restored at tip must be caught")
        (moved / "package.json").unlink()
        moved.rmdir()
        moved.parent.rmdir()

        build = temporary / "scripts" / "package.py"
        write(build, "root = '../DevCoordinator'\nhelper = 'skills/postgres-docker-backup/scripts/postgres_docker_backup.py'\n")
        report = checker.audit_repository(temporary)
        check("cross-repository-dependency" in rules(report), "a build-time checkout dependency must be caught")
        check("moved-source-reference" in rules(report), "a moved helper source path must be caught")
        build.unlink()

        workflow = temporary / ".github" / "workflows" / "validate.yml"
        write(
            workflow,
            "steps:\n  - uses: actions/checkout@v4\n    with:\n      repository: holyglory/DevCoordinator\n      ref: 0123456789abcdef\n",
        )
        report = checker.audit_repository(temporary)
        check("cross-repository-dependency" in rules(report), "a CI checkout/pin must be caught")
        workflow.unlink()

        action_workflow = temporary / ".github" / "workflows" / "action.yml"
        write(action_workflow, "steps:\n  - uses: holyglory/DevCoordinator/.github/actions/setup@0123456789abcdef\n")
        report = checker.audit_repository(temporary)
        check("cross-repository-dependency" in rules(report), "a pinned cross-repository CI action must be caught")
        action_workflow.unlink()

        manifest = temporary / "package.json"
        write(manifest, '{"dependencies":{"coordinator":"file:../DevCoordinator"}}\n')
        report = checker.audit_repository(temporary)
        check("cross-repository-dependency" in rules(report), "a local package path dependency must be caught")
        manifest.unlink()

        requirements = temporary / "requirements.txt"
        write(requirements, "helper @ git+https://github.com/holyglory/DevCoordinator@0123456789abcdef\n")
        report = checker.audit_repository(temporary)
        check("cross-repository-dependency" in rules(report), "a pinned requirements dependency must be caught")
        requirements.unlink()

        bootstrap = temporary / "bin" / "bootstrap"
        write(bootstrap, "#!/bin/sh\ngit clone https://github.com/holyglory/DevCoordinator.git vendor/devcoordinator\n")
        bootstrap.chmod(0o755)
        report = checker.audit_repository(temporary)
        check(
            "cross-repository-dependency" in rules(report),
            "an extensionless executable checkout dependency must be caught",
        )
        bootstrap.unlink()
        bootstrap.parent.rmdir()

        env_template = temporary / ".env.example"
        write(env_template, "DEVCOORDINATOR_ROOT=../DevCoordinator\n")
        report = checker.audit_repository(temporary)
        check(
            "cross-repository-dependency" in rules(report),
            "a runtime env-template checkout dependency must be caught",
        )
        env_template.unlink()

        current_docs = temporary / "USAGE.md"
        write(current_docs, "Run $PROJECT_ROOT/skills/codex-dev-coordinator/scripts/dev_coordinator.py.\n")
        report = checker.audit_repository(temporary)
        check("moved-source-reference" in rules(report), "current docs must not teach a removed in-repo source path")
        current_docs.unlink()

        write(temporary / "skills" / "unexpected-skill" / "SKILL.md", "---\nname: unexpected-skill\n---\n")
        report = checker.audit_repository(temporary)
        check("canonical-skill-set" in rules(report), "an unexpected sixth canonical skill must be caught")

        print("repository boundary self-test ok")
        return 0
    finally:
        rmtree(temporary, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
