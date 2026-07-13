#!/usr/bin/env python3
"""Complete repository validation for the five HolySkills packages."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "full_repo_harness"
SKILL_NAMES = (
    "formal-web-ui-verification",
    "full-repo-audit",
    "full-repo-test-coverage-audit",
    "ui-implementation-audit",
    "user-journey-docs-audit",
)
SKILLS = tuple(ROOT / "skills" / name for name in SKILL_NAMES)
HARNESS_SKILL_NAMES = (
    "full-repo-audit",
    "full-repo-test-coverage-audit",
    "ui-implementation-audit",
)


def run(args: list[str], *, cwd: Path = ROOT) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run(args, cwd=cwd, check=True)


def tree_digest(path: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(
        item
        for item in path.rglob("*")
        if item.is_file() and "__pycache__" not in item.parts and item.suffix != ".pyc"
    )
    for file_path in files:
        digest.update(file_path.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def check_repository_layout() -> None:
    skills_root = ROOT / "skills"
    actual = {
        path.name
        for path in skills_root.iterdir()
        if path.is_dir() and not path.is_symlink() and (path / "SKILL.md").is_file()
    }
    expected = set(SKILL_NAMES)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise SystemExit(f"Canonical skill set mismatch; missing={missing}, unexpected={unexpected}")
    for skill in SKILLS:
        required = (skill / "SKILL.md", skill / "README.md", skill / "scripts" / "self_test.py")
        absent = [path.relative_to(ROOT).as_posix() for path in required if not path.is_file()]
        if absent:
            raise SystemExit(f"Incomplete skill {skill.name}: {', '.join(absent)}")


def check_vendor_sync() -> None:
    expected = tree_digest(HARNESS)
    for skill_name in HARNESS_SKILL_NAMES:
        vendor = ROOT / "skills" / skill_name / "scripts" / "_vendor" / "full_repo_harness"
        if not vendor.is_dir() or tree_digest(vendor) != expected:
            raise SystemExit(f"Vendored harness is stale: {vendor}")


def check_standalone_skill(skill: Path) -> None:
    temporary = Path(tempfile.mkdtemp(prefix=f"{skill.name}-standalone-"))
    try:
        if skill.name in HARNESS_SKILL_NAMES:
            stale_parent = temporary / "full_repo_harness"
            stale_parent.mkdir()
            (stale_parent / "__init__.py").write_text("", encoding="utf-8")
            (stale_parent / "queue.py").write_text(
                "raise RuntimeError('stale parent harness imported')\n",
                encoding="utf-8",
            )
        copied = temporary / skill.name
        shutil.copytree(skill, copied)
        run([sys.executable, str(copied / "scripts" / "self_test.py")])
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def check_include_glob_exclusions() -> None:
    temporary = Path(tempfile.mkdtemp(prefix="include-glob-exclusion-"))
    try:
        repository = temporary / "repo"
        (repository / "src").mkdir(parents=True)
        (repository / "node_modules" / "pkg").mkdir(parents=True)
        (repository / "src" / "app.py").write_text("print(1)\n", encoding="utf-8")
        (repository / "node_modules" / "pkg" / "index.py").write_text("print(2)\n", encoding="utf-8")
        identity = [
            "-c", "user.name=holyskills-validate",
            "-c", "user.email=validate@holyskills.local",
        ]
        run(["git", "init", "-q"], cwd=repository)
        run(["git", "add", "src/app.py"], cwd=repository)
        run(["git", *identity, "commit", "-q", "-m", "init"], cwd=repository)

        broad = temporary / "broad"
        run(
            [
                sys.executable,
                "skills/full-repo-audit/scripts/build_audit_batches.py",
                "--repo", str(repository),
                "--out", str(broad),
                "--include-glob", "**/*.py",
            ]
        )
        broad_manifest = json.loads((broad / "manifest.json").read_text(encoding="utf-8"))
        broad_files = {item["rel_path"] for item in broad_manifest["source_files"]}
        if "node_modules/pkg/index.py" in broad_files:
            raise SystemExit("Broad --include-glob unexpectedly included node_modules")

        explicit = temporary / "explicit"
        run(
            [
                sys.executable,
                "skills/full-repo-audit/scripts/build_audit_batches.py",
                "--repo", str(repository),
                "--out", str(explicit),
                "--include-glob", "node_modules/**/*.py",
            ]
        )
        explicit_manifest = json.loads((explicit / "manifest.json").read_text(encoding="utf-8"))
        explicit_files = {item["rel_path"] for item in explicit_manifest["source_files"]}
        if "node_modules/pkg/index.py" not in explicit_files:
            raise SystemExit("Explicit --include-glob should include its targeted vendor path")
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def check_interaction_label_parity() -> None:
    canonical = HARNESS / "verify_common.py"
    text = canonical.read_text(encoding="utf-8")
    labels = (
        "badge-detail",
        "row-hit-target",
        "navigation-cursor",
        "transient-disclosure",
        "disclosure-scrollbar",
        "icon-meaning",
        "stable-expansion-width",
        "hover-copy",
        "status-summary",
        "message-metadata",
    )
    for label in labels:
        if label not in text:
            raise SystemExit(f"Canonical interaction checklist label missing: {label}")
    for skill in SKILLS:
        for verifier in (skill / "scripts").glob("verify_*.py"):
            if "INTERACTION_CHECKLIST_LABELS" in verifier.read_text(encoding="utf-8"):
                raise SystemExit(
                    f"{verifier} redefines INTERACTION_CHECKLIST_LABELS; import the shared constant"
                )


def main() -> int:
    check_repository_layout()
    run([sys.executable, "scripts/check_app_wide_policy_self_test.py"])
    run([sys.executable, "scripts/check_app_wide_policy.py"])
    run([sys.executable, "scripts/check_repository_freshness_self_test.py"])
    run([sys.executable, "scripts/check_repository_boundaries_self_test.py"])
    run([sys.executable, "scripts/check_repository_boundaries.py", "--repo", str(ROOT)])
    run([sys.executable, "scripts/sync_vendored_harness.py", "--check"])
    check_vendor_sync()
    check_interaction_label_parity()
    check_include_glob_exclusions()
    run([sys.executable, "scripts/self_test_manage_skill_links.py"])
    run([sys.executable, "scripts/merge_findings_self_test.py"])
    run([sys.executable, "scripts/self_test_public_artifact_guard.py"])
    run([sys.executable, "scripts/public_artifact_guard.py", "--repo", str(ROOT)])

    for skill in SKILLS:
        run([sys.executable, str(skill.relative_to(ROOT) / "scripts" / "self_test.py")])

    run(
        [
            sys.executable,
            "-m",
            "compileall",
            "scripts",
            "full_repo_harness",
            *[f"skills/{name}/scripts" for name in SKILL_NAMES],
        ]
    )

    for skill in SKILLS:
        check_standalone_skill(skill)

    print("validation ok (5 canonical skills; standalone matrix passed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
