#!/usr/bin/env python3
"""End-to-end self-test for coordinate-product-delivery."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from shutil import rmtree


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "delivery_state.py"


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def invoke(project: Path, database: Path, *arguments: str, expect: int = 0) -> dict:
    completed = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "--project",
            str(project),
            "--db",
            str(database),
            *arguments,
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
    )
    if completed.returncode != expect:
        raise AssertionError(
            f"Expected exit {expect}, got {completed.returncode} for {arguments}:\n"
            f"stdout={completed.stdout}\nstderr={completed.stderr}"
        )
    stream = completed.stdout if expect == 0 else completed.stderr
    return json.loads(stream)


def mutation(*arguments: str) -> tuple[str, ...]:
    return (*arguments, "--actor", "self-test")


def main() -> int:
    temporary = Path(tempfile.mkdtemp(prefix="coordinate-product-delivery-self-test-"))
    try:
        project = temporary / "project"
        project.mkdir()
        subprocess.run(["git", "init", "-q", str(project)], check=True, timeout=10)
        database = (temporary / "state" / "delivery.sqlite3").resolve()

        foreign_database = (temporary / "foreign" / "state.sqlite3").resolve()
        foreign_database.parent.mkdir()
        with sqlite3.connect(foreign_database) as connection:
            connection.execute("CREATE TABLE unrelated(value TEXT)")
        foreign = invoke(project, foreign_database, "init", expect=2)
        check(
            "not a product-delivery database" in foreign["error"],
            "an existing foreign SQLite file must fail before schema creation",
        )
        with sqlite3.connect(foreign_database) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
        check(tables == {"unrelated"}, "foreign database rejection must not mutate its schema")

        initialized = invoke(project, database, "init")
        check(initialized["schema_version"] == 1, "database schema should initialize")
        other_project = temporary / "other-project"
        other_project.mkdir()
        subprocess.run(["git", "init", "-q", str(other_project)], check=True, timeout=10)
        wrong_project = invoke(other_project, database, "init", expect=2)
        check(
            "different Git repository" in wrong_project["error"],
            "an explicit database must remain bound to its repository",
        )

        invoke(
            project,
            database,
            *mutation(
                "release-create",
                "--id",
                "R1",
                "--name",
                "First release",
                "--outcome",
                "Users can complete the primary journey.",
                "--weight",
                "2",
                "--planned-start",
                "2026-08-20",
                "--planned-end",
                "2026-09-10",
            ),
        )
        invoke(
            project,
            database,
            *mutation(
                "requirement-create",
                "--id",
                "REQ-1",
                "--release",
                "R1",
                "--statement",
                "A user can save the completed form.",
                "--acceptance",
                "A saved form remains available after reload.",
            ),
        )
        invoke(
            project,
            database,
            *mutation(
                "task-create",
                "--id",
                "T1",
                "--release",
                "R1",
                "--requirement",
                "REQ-1",
                "--title",
                "Complete save journey",
                "--outcome",
                "The form saves and reloads.",
                "--weight",
                "3",
                "--planned-start",
                "2026-08-20",
                "--planned-end",
                "2026-08-25",
            ),
        )
        invoke(
            project,
            database,
            *mutation(
                "task-create",
                "--id",
                "T2",
                "--release",
                "R1",
                "--title",
                "Verify release journey",
                "--outcome",
                "The release journey is proven end to end.",
                "--weight",
                "1",
                "--planned-start",
                "2026-08-26",
                "--planned-end",
                "2026-08-28",
            ),
        )
        invoke(project, database, *mutation("dependency-add", "--task", "T2", "--depends-on", "T1"))
        cycle = invoke(
            project,
            database,
            *mutation("dependency-add", "--task", "T1", "--depends-on", "T2"),
            expect=2,
        )
        check("cycle" in cycle["error"], "cyclic dependencies must be rejected")

        invoke(
            project,
            database,
            *mutation(
                "issue-create",
                "--id",
                "CI-1",
                "--title",
                "Save control has no persistence",
                "--remaining-outcome",
                "Saving the form must persist its contents.",
                "--impact",
                "Users currently lose the form after reload, so Release 1 is not ready.",
                "--release",
                "R1",
                "--requirement",
                "REQ-1",
                "--task",
                "T1",
                "--detected-by",
                "execution-thread",
                "--blocks-release",
            ),
        )
        blocked_completion = invoke(
            project,
            database,
            *mutation(
                "task-update",
                "--id",
                "T1",
                "--state",
                "done",
                "--completion",
                "100",
                "--summary",
                "Attempted completion.",
                "--evidence-ref",
                "test:save",
            ),
            expect=2,
        )
        check(
            "unresolved blocking completion issues" in blocked_completion["error"],
            "task completion must fail while linked ledger work is unresolved",
        )

        invoke(
            project,
            database,
            *mutation(
                "issue-transition",
                "--id",
                "CI-1",
                "--state",
                "implemented",
                "--summary",
                "The save path now persists form contents.",
                "--evidence-ref",
                "change:save-persistence",
            ),
        )
        not_implemented = invoke(project, database, "issue-list")
        check(not_implemented["count"] == 0, "implemented work should leave the normal unfinished query")
        outstanding = invoke(project, database, "issue-list", "--state", "outstanding")
        check(outstanding["count"] == 1, "implemented but unverified work should remain outstanding")

        still_blocked = invoke(
            project,
            database,
            *mutation(
                "task-update",
                "--id",
                "T1",
                "--state",
                "done",
                "--completion",
                "100",
                "--summary",
                "Attempted completion before verification.",
                "--evidence-ref",
                "test:save",
            ),
            expect=2,
        )
        check("CI-1" in still_blocked["error"], "implemented issues should block until verified")

        invoke(
            project,
            database,
            *mutation(
                "issue-transition",
                "--id",
                "CI-1",
                "--state",
                "verified",
                "--summary",
                "Reload verification proved the saved form remains available.",
                "--evidence-ref",
                "test:save-reload",
            ),
        )
        invoke(
            project,
            database,
            *mutation(
                "task-update",
                "--id",
                "T1",
                "--state",
                "done",
                "--completion",
                "100",
                "--summary",
                "The save journey is complete and verified.",
                "--evidence-ref",
                "test:save-reload",
            ),
        )
        invoke(
            project,
            database,
            *mutation(
                "task-update",
                "--id",
                "T2",
                "--state",
                "in_progress",
                "--completion",
                "50",
                "--summary",
                "Half of the release checks are complete.",
                "--expected-update-at",
                "2026-08-19T10:00:00+00:00",
            ),
        )

        status = invoke(project, database, "status", "--release", "R1")
        check(
            status["releases"][0]["progress_percent"] == 87.5,
            "weighted release progress should be 87.5%",
        )
        check(
            status["overall_progress_percent"] == 0.0,
            "draft releases should not enter approved-roadmap progress",
        )
        check(status["approved_scope_baselines"] == [], "draft scope should not be an approved baseline")
        check(not status["releases"][0]["ready"], "unfinished tasks should keep the release unready")
        work_order = invoke(project, database, "release-show", "--release", "R1")
        check(work_order["scope_baseline"] == "R1:r1", "work order should bind the scope revision")
        check(len(work_order["tasks"]) == 2, "release work order should include its tasks")
        task_order = invoke(project, database, "task-show", "--task", "T2")
        check(task_order["depends_on"] == ["T1"], "task work order should include dependencies")

        monitor = invoke(
            project,
            database,
            "monitor-snapshot",
            "--now",
            "2026-08-19T11:00:00+00:00",
        )
        check([item["id"] for item in monitor["stale_tasks"]] == ["T2"], "missed updates should be stale")

        for source, target in [("draft", "approved"), ("approved", "active"), ("active", "acceptance")]:
            result = invoke(
                project,
                database,
                *mutation(
                    "release-transition",
                    "--id",
                    "R1",
                    "--state",
                    target,
                    "--summary",
                    f"Release moved from {source} to {target}.",
                ),
            )
            check(result["state"] == target, f"release should transition to {target}")

        premature_release = invoke(
            project,
            database,
            *mutation(
                "release-transition",
                "--id",
                "R1",
                "--state",
                "released",
                "--summary",
                "Attempted premature release.",
                "--evidence-ref",
                "acceptance:R1",
            ),
            expect=2,
        )
        check("T2" in premature_release["error"], "release must reject unfinished tasks")

        invoke(
            project,
            database,
            *mutation(
                "task-update",
                "--id",
                "T2",
                "--state",
                "done",
                "--completion",
                "100",
                "--summary",
                "The full release journey is verified.",
                "--evidence-ref",
                "acceptance:R1",
            ),
        )
        released = invoke(
            project,
            database,
            *mutation(
                "release-transition",
                "--id",
                "R1",
                "--state",
                "released",
                "--summary",
                "Release 1 meets its accepted outcome.",
                "--evidence-ref",
                "acceptance:R1",
            ),
        )
        check(released["state"] == "released", "verified release should transition to released")
        finished = invoke(project, database, "status", "--release", "R1")
        check(finished["overall_progress_percent"] == 100.0, "complete release should report 100%")
        check(finished["releases"][0]["ready"], "complete release should be ready")
        check(finished["approved_scope_baselines"] == ["R1:r1"], "status should name its baseline")
        check(finished["ledger"]["verified"] == 1, "status should summarize permanent ledger state")

        all_issues = invoke(project, database, "issue-list", "--state", "all")
        check(all_issues["count"] == 1, "implemented issue must remain permanently queryable")
        history = invoke(project, database, "issue-history", "--id", "CI-1")
        transitions = [event["to_state"] for event in history["events"] if event["to_state"]]
        check(
            transitions == ["detected", "implemented", "verified"],
            "issue history should retain every lifecycle transition",
        )

        invoke(
            project,
            database,
            *mutation(
                "release-create",
                "--id",
                "R2",
                "--name",
                "Second release",
                "--outcome",
                "Users receive the deferred improvement.",
            ),
        )
        invoke(
            project,
            database,
            *mutation(
                "issue-transition",
                "--id",
                "CI-1",
                "--state",
                "reopened",
                "--summary",
                "Later evidence showed that additional work remains.",
            ),
        )
        invoke(
            project,
            database,
            *mutation(
                "issue-move",
                "--id",
                "CI-1",
                "--release",
                "R2",
                "--decision-ref",
                "decision:user-approved-deferral",
                "--summary",
                "The user moved the reopened work to Release 2.",
            ),
        )
        moved = invoke(project, database, "issue-list", "--release", "R2")
        check(moved["count"] == 1, "moved unfinished work should appear in its target release")
        original_release = invoke(project, database, "status", "--release", "R1")
        check(
            original_release["releases"][0]["ready"],
            "a decision-backed release move should stop the issue from blocking the original release",
        )
        moved_history = invoke(project, database, "issue-history", "--id", "CI-1")
        moved_transitions = [
            event["to_state"] for event in moved_history["events"] if event["to_state"]
        ]
        check(
            moved_transitions == ["detected", "implemented", "verified", "reopened"],
            "issue history should preserve verification and reopening across a release move",
        )

        gantt = invoke(project, database, "gantt-data", "--release", "R1")
        check(gantt["schema"] == "holyskills.product-delivery.gantt.v1", "Gantt data needs a stable schema")
        check(
            gantt["dependencies"] == [{"depends_on_task_id": "T1", "task_id": "T2"}],
            "Gantt data should preserve task dependencies",
        )
        check(
            {item["id"]: item["weight"] for item in gantt["tasks"]} == {"T1": 3.0, "T2": 1.0},
            "Gantt data should expose task weights",
        )

        invoke(
            project,
            database,
            *mutation(
                "release-rebaseline",
                "--id",
                "R1",
                "--decision-ref",
                "decision:user-approved-scope-change",
                "--summary",
                "The user approved the revised release boundary.",
                "--weight",
                "3",
                "--planned-end",
                "2026-09-12",
            ),
        )
        rebased = invoke(project, database, "status", "--release", "R1")
        check(rebased["releases"][0]["scope_revision"] == 2, "rebaseline should increment revision")
        check(rebased["releases"][0]["weight"] == 3.0, "rebaseline should update release weight")

        with sqlite3.connect(database) as connection:
            try:
                connection.execute("DELETE FROM completion_issues WHERE id = 'CI-1'")
            except sqlite3.IntegrityError as error:
                check("permanent" in str(error), "issue deletion trigger should explain permanence")
            else:
                raise AssertionError("database must reject completion issue deletion")
            try:
                connection.execute("DELETE FROM events")
            except sqlite3.IntegrityError as error:
                check("permanent" in str(error), "event deletion trigger should explain permanence")
            else:
                raise AssertionError("database must reject event deletion")

        invalid_percent = invoke(
            project,
            database,
            *mutation(
                "task-update",
                "--id",
                "T2",
                "--completion",
                "101",
                "--summary",
                "Invalid progress.",
            ),
            expect=2,
        )
        check("between 0 and 100" in invalid_percent["error"], "invalid progress must fail")

        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        lower_skill = skill.lower()
        for required in [
            "one primary execution task",
            "do not create a separate direct-execution mode",
            "database is the authoritative work graph and Completion Ledger",
            "once per hour",
            "overall progress percentage",
            "true product expansion",
        ]:
            check(required.lower() in lower_skill, f"skill contract should contain {required!r}")

        metadata = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        check("allow_implicit_invocation: false" in metadata, "coordinator skill should require deliberate invocation")
        check("$coordinate-product-delivery" in metadata, "default prompt should invoke the skill explicitly")

        print("coordinate-product-delivery self-test ok")
        return 0
    finally:
        rmtree(temporary, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
