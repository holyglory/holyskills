#!/usr/bin/env python3
"""Software-owned product-delivery work graph and completion ledger."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence


SCHEMA_VERSION = 1
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
MAX_TEXT = 4000
MAX_RESULTS = 200
MAX_IMPORT_BYTES = 2 * 1024 * 1024
IMPORT_SCHEMA = "holyskills.completion-ledger-import.v1"

RELEASE_STATES = {
    "draft",
    "approved",
    "active",
    "acceptance",
    "paused",
    "released",
    "cancelled",
}
TASK_STATES = {
    "planned",
    "ready",
    "in_progress",
    "blocked",
    "review",
    "done",
    "failed",
    "cancelled",
}
ISSUE_STATES = {
    "detected",
    "planned",
    "in_progress",
    "blocked",
    "implemented",
    "verified",
    "reopened",
    "superseded",
}
MONITOR_STATES = {"unarmed", "arming", "armed", "blocked", "stopped"}
MONITOR_RUN_STATES = {"running", "completed", "failed", "skipped_overlap"}
NOT_IMPLEMENTED_STATES = {
    "detected",
    "planned",
    "in_progress",
    "blocked",
    "reopened",
}
OUTSTANDING_ISSUE_STATES = NOT_IMPLEMENTED_STATES | {"implemented"}

RELEASE_TRANSITIONS = {
    "draft": {"approved", "paused", "cancelled"},
    "approved": {"active", "paused", "cancelled"},
    "active": {"acceptance", "paused", "cancelled"},
    "acceptance": {"active", "paused", "released"},
    "paused": {"approved", "active", "cancelled"},
    "released": set(),
    "cancelled": set(),
}
ISSUE_TRANSITIONS = {
    "detected": {"planned", "in_progress", "blocked", "implemented", "superseded"},
    "planned": {"in_progress", "blocked", "implemented", "superseded"},
    "in_progress": {"blocked", "implemented", "superseded"},
    "blocked": {"planned", "in_progress", "implemented", "superseded"},
    "implemented": {"verified", "reopened"},
    "verified": {"reopened"},
    "reopened": {"planned", "in_progress", "blocked", "implemented", "superseded"},
    "superseded": {"reopened"},
}


class DeliveryStateError(RuntimeError):
    """Raised when a requested state mutation violates the delivery contract."""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def json_output(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True))


def require_id(value: object, label: str) -> str:
    if not isinstance(value, str) or ID_PATTERN.fullmatch(value) is None:
        raise DeliveryStateError(f"{label} must be a stable ID of at most 128 characters")
    return value


def require_text(value: object | None, label: str, *, optional: bool = False) -> str | None:
    if value is None:
        if optional:
            return None
        raise DeliveryStateError(f"{label} is required")
    if not isinstance(value, str):
        raise DeliveryStateError(f"{label} must be text")
    normalized = value.strip()
    if not normalized and not optional:
        raise DeliveryStateError(f"{label} must not be empty")
    if len(normalized) > MAX_TEXT:
        raise DeliveryStateError(f"{label} exceeds {MAX_TEXT} characters")
    return normalized or None


def require_percent(value: int) -> int:
    if value < 0 or value > 100:
        raise DeliveryStateError("completion must be between 0 and 100")
    return value


def require_positive(value: float, label: str) -> float:
    if value <= 0:
        raise DeliveryStateError(f"{label} must be greater than zero")
    return value


def require_limit(value: int) -> int:
    if value < 1 or value > MAX_RESULTS:
        raise DeliveryStateError(f"limit must be between 1 and {MAX_RESULTS}")
    return value


def normalize_date(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    try:
        return dt.date.fromisoformat(value).isoformat()
    except ValueError as error:
        raise DeliveryStateError(f"{label} must use YYYY-MM-DD") from error


def normalize_timestamp(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise DeliveryStateError(f"{label} must be an ISO 8601 timestamp") from error
    if parsed.tzinfo is None:
        raise DeliveryStateError(f"{label} must include a timezone")
    return parsed.astimezone(dt.timezone.utc).isoformat(timespec="seconds")


def git_identity(project: Path) -> tuple[Path, Path]:
    project = project.expanduser().resolve(strict=True)
    if not project.is_dir():
        raise DeliveryStateError(f"project is not a directory: {project}")
    try:
        root_result = subprocess.run(
            ["git", "-C", str(project), "rev-parse", "--show-toplevel"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
        )
        common_result = subprocess.run(
            ["git", "-C", str(project), "rev-parse", "--git-common-dir"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise DeliveryStateError("project must be inside a readable Git repository") from error
    root = Path(root_result.stdout.strip()).resolve(strict=True)
    raw_common = Path(common_result.stdout.strip())
    common = raw_common if raw_common.is_absolute() else root / raw_common
    return root, common.resolve(strict=True)


def resolve_database(project: Path, explicit: Path | None) -> tuple[Path, Path, str]:
    root, common = git_identity(project)
    project_key = hashlib.sha256(str(common).encode("utf-8")).hexdigest()
    if explicit is None:
        shared_root = common.parent if common.name == ".git" else root
        database = shared_root / ".product-delivery" / "delivery.sqlite3"
    else:
        database = explicit.expanduser()
        if not database.is_absolute():
            raise DeliveryStateError("--db must be an absolute path")
    database.parent.mkdir(mode=0o770, parents=True, exist_ok=True)
    if database.is_symlink():
        raise DeliveryStateError("database path must not be a symlink")
    return root, database, project_key


SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS releases (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    outcome TEXT NOT NULL,
    status TEXT NOT NULL,
    weight REAL NOT NULL CHECK(weight > 0),
    scope_revision INTEGER NOT NULL DEFAULT 1 CHECK(scope_revision > 0),
    planned_start TEXT,
    planned_end TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS requirements (
    id TEXT PRIMARY KEY,
    release_id TEXT NOT NULL REFERENCES releases(id),
    statement TEXT NOT NULL,
    acceptance TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'approved',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    release_id TEXT NOT NULL REFERENCES releases(id),
    requirement_id TEXT REFERENCES requirements(id),
    title TEXT NOT NULL,
    outcome TEXT NOT NULL,
    state TEXT NOT NULL,
    completion INTEGER NOT NULL CHECK(completion BETWEEN 0 AND 100),
    weight REAL NOT NULL CHECK(weight > 0),
    duration_hours REAL CHECK(duration_hours IS NULL OR duration_hours > 0),
    planned_start TEXT,
    planned_end TEXT,
    owner_thread_id TEXT,
    owner_host_id TEXT,
    blocker_summary TEXT,
    evidence_ref TEXT,
    last_event_at TEXT NOT NULL,
    expected_update_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_dependencies (
    task_id TEXT NOT NULL REFERENCES tasks(id),
    depends_on_task_id TEXT NOT NULL REFERENCES tasks(id),
    PRIMARY KEY(task_id, depends_on_task_id),
    CHECK(task_id <> depends_on_task_id)
);

CREATE TABLE IF NOT EXISTS completion_issues (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    remaining_outcome TEXT NOT NULL,
    impact TEXT NOT NULL,
    state TEXT NOT NULL,
    blocks_release INTEGER NOT NULL CHECK(blocks_release IN (0, 1)),
    release_id TEXT REFERENCES releases(id),
    requirement_id TEXT REFERENCES requirements(id),
    detected_by TEXT NOT NULL,
    implemented_at TEXT,
    verified_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS completion_issue_tasks (
    issue_id TEXT NOT NULL REFERENCES completion_issues(id),
    task_id TEXT NOT NULL REFERENCES tasks(id),
    PRIMARY KEY(issue_id, task_id)
);

CREATE TABLE IF NOT EXISTS completion_imports (
    id TEXT PRIMARY KEY,
    digest TEXT NOT NULL,
    issue_count INTEGER NOT NULL CHECK(issue_count >= 0),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS monitoring_schedules (
    release_id TEXT PRIMARY KEY REFERENCES releases(id),
    coordinator_thread_id TEXT NOT NULL,
    executor_thread_id TEXT NOT NULL,
    executor_host_id TEXT NOT NULL,
    automation_id TEXT,
    cadence_minutes INTEGER NOT NULL CHECK(cadence_minutes > 0),
    state TEXT NOT NULL,
    cursor TEXT,
    local_files INTEGER NOT NULL CHECK(local_files IN (0, 1)),
    availability_confirmed_at TEXT,
    automation_enabled INTEGER NOT NULL CHECK(automation_enabled IN (0, 1)),
    first_run_verified_at TEXT,
    next_run_at TEXT,
    last_run_key TEXT,
    last_started_at TEXT,
    last_completed_at TEXT,
    blocker_summary TEXT,
    stop_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS monitoring_runs (
    run_key TEXT PRIMARY KEY,
    release_id TEXT NOT NULL REFERENCES monitoring_schedules(release_id),
    scheduled_for TEXT NOT NULL,
    state TEXT NOT NULL,
    cursor_before TEXT,
    cursor_after TEXT,
    summary TEXT,
    evidence_ref TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT,
    summary TEXT NOT NULL,
    evidence_ref TEXT,
    actor TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS tasks_release_idx ON tasks(release_id);
CREATE INDEX IF NOT EXISTS tasks_expected_update_idx ON tasks(expected_update_at);
CREATE INDEX IF NOT EXISTS issues_release_idx ON completion_issues(release_id);
CREATE INDEX IF NOT EXISTS issues_state_idx ON completion_issues(state);
CREATE INDEX IF NOT EXISTS events_entity_idx ON events(entity_type, entity_id, sequence);
CREATE INDEX IF NOT EXISTS monitoring_runs_release_idx ON monitoring_runs(release_id, started_at);

CREATE TRIGGER IF NOT EXISTS completion_issues_no_delete
BEFORE DELETE ON completion_issues
BEGIN
    SELECT RAISE(ABORT, 'completion issues are permanent');
END;

CREATE TRIGGER IF NOT EXISTS events_no_update
BEFORE UPDATE ON events
BEGIN
    SELECT RAISE(ABORT, 'delivery events are immutable');
END;

CREATE TRIGGER IF NOT EXISTS events_no_delete
BEFORE DELETE ON events
BEGIN
    SELECT RAISE(ABORT, 'delivery events are permanent');
END;

CREATE TRIGGER IF NOT EXISTS monitoring_runs_no_delete
BEFORE DELETE ON monitoring_runs
BEGIN
    SELECT RAISE(ABORT, 'monitoring run history is permanent');
END;
"""


class Store:
    def __init__(self, project: Path, database: Path | None):
        self.project_root, self.database, self.project_key = resolve_database(project, database)
        self.connection = sqlite3.connect(str(self.database), timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA busy_timeout = 30000")
        database_metadata = self.database.stat()
        current_user_owns_database = not hasattr(os, "geteuid") or database_metadata.st_uid == os.geteuid()
        if current_user_owns_database:
            try:
                self.database.chmod(0o660)
            except OSError as error:
                raise DeliveryStateError(f"could not make the shared database group-writable: {error}") from error

    def close(self) -> None:
        self.connection.close()

    @property
    def database_id(self) -> str:
        return hashlib.sha256(str(self.database).encode("utf-8")).hexdigest()[:24]

    def initialize(self) -> None:
        tables = {
            row["name"]
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if tables:
            if "metadata" not in tables:
                raise DeliveryStateError("existing database is not a product-delivery database")
            version = self.connection.execute(
                "SELECT value FROM metadata WHERE key = 'schema_version'"
            ).fetchone()
            recorded = self.connection.execute(
                "SELECT value FROM metadata WHERE key = 'project_key'"
            ).fetchone()
            if version is None or version["value"] != str(SCHEMA_VERSION):
                found = version["value"] if version is not None else "missing"
                raise DeliveryStateError(
                    f"unsupported database schema {found}; expected {SCHEMA_VERSION}"
                )
            if recorded is None or recorded["value"] != self.project_key:
                raise DeliveryStateError("database belongs to a different Git repository")
        self.connection.execute("PRAGMA journal_mode = WAL")
        with self.connection:
            self.connection.executescript(SCHEMA)
            version = self.connection.execute(
                "SELECT value FROM metadata WHERE key = 'schema_version'"
            ).fetchone()
            if version is None:
                self.connection.executemany(
                    "INSERT INTO metadata(key, value) VALUES (?, ?)",
                    [
                        ("schema_version", str(SCHEMA_VERSION)),
                        ("project_key", self.project_key),
                        ("created_at", utc_now()),
                    ],
                )
            elif version["value"] != str(SCHEMA_VERSION):
                raise DeliveryStateError(
                    f"unsupported database schema {version['value']}; expected {SCHEMA_VERSION}"
                )
            recorded = self.connection.execute(
                "SELECT value FROM metadata WHERE key = 'project_key'"
            ).fetchone()
            if recorded is None or recorded["value"] != self.project_key:
                raise DeliveryStateError("database belongs to a different Git repository")

    def row(self, table: str, identifier: str) -> sqlite3.Row:
        allowed = {"releases", "requirements", "tasks", "completion_issues"}
        if table not in allowed:
            raise DeliveryStateError("invalid internal table selection")
        result = self.connection.execute(
            f"SELECT * FROM {table} WHERE id = ?", (identifier,)
        ).fetchone()
        if result is None:
            raise DeliveryStateError(f"unknown {table[:-1]}: {identifier}")
        return result

    def event(
        self,
        *,
        entity_type: str,
        entity_id: str,
        event_type: str,
        summary: str,
        actor: str,
        from_state: str | None = None,
        to_state: str | None = None,
        evidence_ref: str | None = None,
        metadata: dict[str, object] | None = None,
        created_at: str | None = None,
    ) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO events(
                entity_type, entity_id, event_type, from_state, to_state,
                summary, evidence_ref, actor, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entity_type,
                entity_id,
                event_type,
                from_state,
                to_state,
                require_text(summary, "event summary"),
                require_text(evidence_ref, "evidence reference", optional=True),
                require_text(actor, "actor"),
                json.dumps(metadata or {}, sort_keys=True, separators=(",", ":")),
                created_at or utc_now(),
            ),
        )
        return int(cursor.lastrowid)


def as_dict(row: sqlite3.Row) -> dict[str, object]:
    return {key: row[key] for key in row.keys()}


def monitoring_row(store: Store, release_id: str) -> sqlite3.Row | None:
    return store.connection.execute(
        "SELECT * FROM monitoring_schedules WHERE release_id = ?", (release_id,)
    ).fetchone()


def monitoring_ready(row: sqlite3.Row | None) -> bool:
    return bool(
        row is not None
        and row["state"] == "armed"
        and row["automation_enabled"] == 1
        and row["automation_id"]
        and row["executor_thread_id"]
        and row["executor_host_id"]
        and row["first_run_verified_at"]
        and row["cursor"]
        and row["next_run_at"]
        and not row["blocker_summary"]
        and (row["local_files"] == 0 or row["availability_confirmed_at"])
    )


def ensure_requirement_release(store: Store, requirement_id: str | None, release_id: str) -> None:
    if requirement_id is None:
        return
    requirement = store.row("requirements", requirement_id)
    if requirement["release_id"] != release_id:
        raise DeliveryStateError("requirement and task must belong to the same release")


def linked_blocking_issues(store: Store, task_id: str) -> list[sqlite3.Row]:
    return store.connection.execute(
        """
        SELECT issue.id, issue.state, issue.remaining_outcome
        FROM completion_issues AS issue
        JOIN completion_issue_tasks AS link ON link.issue_id = issue.id
        JOIN tasks AS task ON task.id = link.task_id
        WHERE link.task_id = ?
          AND issue.release_id = task.release_id
          AND issue.blocks_release = 1
          AND issue.state NOT IN ('verified', 'superseded')
        ORDER BY issue.id
        """,
        (task_id,),
    ).fetchall()


def command_init(store: Store, _args: argparse.Namespace) -> dict[str, object]:
    return {
        "ok": True,
        "database_id": store.database_id,
        "project_key": store.project_key,
        "schema_version": SCHEMA_VERSION,
    }


def command_release_create(store: Store, args: argparse.Namespace) -> dict[str, object]:
    identifier = require_id(args.id, "release ID")
    now = utc_now()
    start = normalize_date(args.planned_start, "planned start")
    end = normalize_date(args.planned_end, "planned end")
    if start and end and end < start:
        raise DeliveryStateError("planned end must not precede planned start")
    with store.connection:
        store.connection.execute(
            """
            INSERT INTO releases(
                id, name, outcome, status, weight, scope_revision,
                planned_start, planned_end, created_at, updated_at
            ) VALUES (?, ?, ?, 'draft', ?, 1, ?, ?, ?, ?)
            """,
            (
                identifier,
                require_text(args.name, "release name"),
                require_text(args.outcome, "release outcome"),
                require_positive(args.weight, "release weight"),
                start,
                end,
                now,
                now,
            ),
        )
        sequence = store.event(
            entity_type="release",
            entity_id=identifier,
            event_type="created",
            summary=f"Release {args.name.strip()} was created.",
            actor=args.actor,
            to_state="draft",
            created_at=now,
        )
    return {"ok": True, "release": identifier, "scope_revision": 1, "event_sequence": sequence}


def command_release_rebaseline(store: Store, args: argparse.Namespace) -> dict[str, object]:
    identifier = require_id(args.id, "release ID")
    release = store.row("releases", identifier)
    decision = require_text(args.decision_ref, "decision reference")
    summary = require_text(args.summary, "rebaseline summary")
    now = utc_now()
    revision = int(release["scope_revision"]) + 1
    name = require_text(args.name, "release name") if args.name is not None else release["name"]
    outcome = (
        require_text(args.outcome, "release outcome") if args.outcome is not None else release["outcome"]
    )
    weight = (
        require_positive(args.weight, "release weight") if args.weight is not None else release["weight"]
    )
    start = (
        normalize_date(args.planned_start, "planned start")
        if args.planned_start is not None
        else release["planned_start"]
    )
    end = (
        normalize_date(args.planned_end, "planned end")
        if args.planned_end is not None
        else release["planned_end"]
    )
    if start and end and end < start:
        raise DeliveryStateError("planned end must not precede planned start")
    with store.connection:
        store.connection.execute(
            """
            UPDATE releases SET name = ?, outcome = ?, weight = ?, scope_revision = ?,
                planned_start = ?, planned_end = ?, updated_at = ?
            WHERE id = ?
            """,
            (name, outcome, weight, revision, start, end, now, identifier),
        )
        sequence = store.event(
            entity_type="release",
            entity_id=identifier,
            event_type="rebaselined",
            summary=summary or "Release scope was rebaselined.",
            actor=args.actor,
            evidence_ref=decision,
            metadata={
                "scope_revision": revision,
                "weight_before": release["weight"],
                "weight_after": weight,
                "planned_start": start,
                "planned_end": end,
            },
            created_at=now,
        )
    return {"ok": True, "release": identifier, "scope_revision": revision, "event_sequence": sequence}


def release_blockers(store: Store, release_id: str) -> tuple[list[str], list[str]]:
    tasks = store.connection.execute(
        """
        SELECT id FROM tasks
        WHERE release_id = ? AND state NOT IN ('done', 'cancelled')
        ORDER BY id
        """,
        (release_id,),
    ).fetchall()
    issues = store.connection.execute(
        """
        SELECT id FROM completion_issues
        WHERE release_id = ? AND blocks_release = 1
          AND state NOT IN ('verified', 'superseded')
        ORDER BY id
        """,
        (release_id,),
    ).fetchall()
    return [row["id"] for row in tasks], [row["id"] for row in issues]


def command_release_transition(store: Store, args: argparse.Namespace) -> dict[str, object]:
    identifier = require_id(args.id, "release ID")
    target = args.state
    release = store.row("releases", identifier)
    current = release["status"]
    if target not in RELEASE_TRANSITIONS[current]:
        raise DeliveryStateError(f"release cannot transition from {current} to {target}")
    evidence = require_text(args.evidence_ref, "evidence reference", optional=True)
    monitor = monitoring_row(store, identifier)
    if target in {"paused", "cancelled", "released"} and monitor is not None:
        if monitor["automation_enabled"] == 1 or monitor["state"] in {"arming", "armed"}:
            raise DeliveryStateError(
                "release monitoring must be disabled and stopped before transition to " + target
            )
    if target == "released":
        if evidence is None:
            raise DeliveryStateError("releasing requires an evidence reference")
        requirement_count = store.connection.execute(
            "SELECT COUNT(*) AS value FROM requirements WHERE release_id = ? AND status = 'approved'",
            (identifier,),
        ).fetchone()["value"]
        task_count = store.connection.execute(
            "SELECT COUNT(*) AS value FROM tasks WHERE release_id = ? AND state <> 'cancelled'",
            (identifier,),
        ).fetchone()["value"]
        if requirement_count == 0 or task_count == 0:
            raise DeliveryStateError("releasing requires at least one approved requirement and one active task")
        open_tasks, open_issues = release_blockers(store, identifier)
        if open_tasks or open_issues:
            raise DeliveryStateError(
                "release is not ready; unfinished tasks={} blocking issues={}".format(
                    open_tasks, open_issues
                )
            )
    now = utc_now()
    with store.connection:
        store.connection.execute(
            "UPDATE releases SET status = ?, updated_at = ? WHERE id = ?",
            (target, now, identifier),
        )
        sequence = store.event(
            entity_type="release",
            entity_id=identifier,
            event_type="status_changed",
            summary=require_text(args.summary, "transition summary") or "Release status changed.",
            actor=args.actor,
            from_state=current,
            to_state=target,
            evidence_ref=evidence,
            created_at=now,
        )
    return {"ok": True, "release": identifier, "state": target, "event_sequence": sequence}


def command_requirement_create(store: Store, args: argparse.Namespace) -> dict[str, object]:
    identifier = require_id(args.id, "requirement ID")
    release_id = require_id(args.release, "release ID")
    store.row("releases", release_id)
    now = utc_now()
    with store.connection:
        store.connection.execute(
            """
            INSERT INTO requirements(
                id, release_id, statement, acceptance, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'approved', ?, ?)
            """,
            (
                identifier,
                release_id,
                require_text(args.statement, "requirement statement"),
                require_text(args.acceptance, "requirement acceptance"),
                now,
                now,
            ),
        )
        sequence = store.event(
            entity_type="requirement",
            entity_id=identifier,
            event_type="created",
            summary=f"Requirement {identifier} was added to {release_id}.",
            actor=args.actor,
            to_state="approved",
            created_at=now,
        )
    return {"ok": True, "requirement": identifier, "release": release_id, "event_sequence": sequence}


def command_task_create(store: Store, args: argparse.Namespace) -> dict[str, object]:
    identifier = require_id(args.id, "task ID")
    release_id = require_id(args.release, "release ID")
    requirement_id = require_id(args.requirement, "requirement ID") if args.requirement else None
    store.row("releases", release_id)
    ensure_requirement_release(store, requirement_id, release_id)
    start = normalize_date(args.planned_start, "planned start")
    end = normalize_date(args.planned_end, "planned end")
    if start and end and end < start:
        raise DeliveryStateError("planned end must not precede planned start")
    expected = normalize_timestamp(args.expected_update_at, "expected update")
    now = utc_now()
    with store.connection:
        store.connection.execute(
            """
            INSERT INTO tasks(
                id, release_id, requirement_id, title, outcome, state, completion,
                weight, duration_hours, planned_start, planned_end, owner_thread_id,
                owner_host_id, blocker_summary, evidence_ref, last_event_at,
                expected_update_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'planned', 0, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?)
            """,
            (
                identifier,
                release_id,
                requirement_id,
                require_text(args.title, "task title"),
                require_text(args.outcome, "task outcome"),
                require_positive(args.weight, "task weight"),
                require_positive(args.duration_hours, "duration hours")
                if args.duration_hours is not None
                else None,
                start,
                end,
                require_text(args.owner_thread, "owner thread", optional=True),
                require_text(args.owner_host, "owner host", optional=True),
                now,
                expected,
                now,
                now,
            ),
        )
        sequence = store.event(
            entity_type="task",
            entity_id=identifier,
            event_type="created",
            summary=f"Task {identifier} was added to {release_id}.",
            actor=args.actor,
            to_state="planned",
            created_at=now,
        )
    return {"ok": True, "task": identifier, "release": release_id, "event_sequence": sequence}


def command_dependency_add(store: Store, args: argparse.Namespace) -> dict[str, object]:
    task_id = require_id(args.task, "task ID")
    dependency_id = require_id(args.depends_on, "dependency task ID")
    if task_id == dependency_id:
        raise DeliveryStateError("a task cannot depend on itself")
    store.row("tasks", task_id)
    store.row("tasks", dependency_id)
    cycle = store.connection.execute(
        """
        WITH RECURSIVE chain(id) AS (
            SELECT depends_on_task_id FROM task_dependencies WHERE task_id = ?
            UNION
            SELECT dependency.depends_on_task_id
            FROM task_dependencies AS dependency
            JOIN chain ON dependency.task_id = chain.id
        )
        SELECT 1 FROM chain WHERE id = ? LIMIT 1
        """,
        (dependency_id, task_id),
    ).fetchone()
    if cycle is not None:
        raise DeliveryStateError("dependency would create a cycle")
    with store.connection:
        store.connection.execute(
            "INSERT INTO task_dependencies(task_id, depends_on_task_id) VALUES (?, ?)",
            (task_id, dependency_id),
        )
        sequence = store.event(
            entity_type="task",
            entity_id=task_id,
            event_type="dependency_added",
            summary=f"Task {task_id} now depends on {dependency_id}.",
            actor=args.actor,
            metadata={"depends_on": dependency_id},
        )
    return {"ok": True, "task": task_id, "depends_on": dependency_id, "event_sequence": sequence}


def command_task_update(store: Store, args: argparse.Namespace) -> dict[str, object]:
    identifier = require_id(args.id, "task ID")
    task = store.row("tasks", identifier)
    state = args.state if args.state is not None else task["state"]
    completion = require_percent(args.completion if args.completion is not None else task["completion"])
    if state == "done" and completion != 100:
        raise DeliveryStateError("a done task must have 100 percent completion")
    if completion == 100 and state != "done":
        raise DeliveryStateError("100 percent completion requires the done state")
    evidence = (
        require_text(args.evidence_ref, "evidence reference", optional=True)
        if args.evidence_ref is not None
        else task["evidence_ref"]
    )
    if state == "done":
        if not evidence:
            raise DeliveryStateError("completing a task requires an evidence reference")
        blocking = linked_blocking_issues(store, identifier)
        if blocking:
            raise DeliveryStateError(
                "task has unresolved blocking completion issues: "
                + ", ".join(row["id"] for row in blocking)
            )
    blocker = (
        require_text(args.blocker, "blocker summary", optional=True)
        if args.blocker is not None
        else task["blocker_summary"]
    )
    if state == "blocked" and not blocker:
        raise DeliveryStateError("a blocked task requires a blocker summary")
    if state != "blocked" and args.blocker == "":
        blocker = None
    start = normalize_date(args.planned_start, "planned start") if args.planned_start else task["planned_start"]
    end = normalize_date(args.planned_end, "planned end") if args.planned_end else task["planned_end"]
    if start and end and end < start:
        raise DeliveryStateError("planned end must not precede planned start")
    expected = (
        normalize_timestamp(args.expected_update_at, "expected update")
        if args.expected_update_at is not None
        else task["expected_update_at"]
    )
    owner_thread = (
        require_text(args.owner_thread, "owner thread", optional=True)
        if args.owner_thread is not None
        else task["owner_thread_id"]
    )
    owner_host = (
        require_text(args.owner_host, "owner host", optional=True)
        if args.owner_host is not None
        else task["owner_host_id"]
    )
    weight = require_positive(args.weight, "task weight") if args.weight is not None else task["weight"]
    duration = (
        require_positive(args.duration_hours, "duration hours")
        if args.duration_hours is not None
        else task["duration_hours"]
    )
    now = utc_now()
    with store.connection:
        store.connection.execute(
            """
            UPDATE tasks SET
                state = ?, completion = ?, owner_thread_id = ?, owner_host_id = ?,
                blocker_summary = ?, evidence_ref = ?, weight = ?, duration_hours = ?,
                planned_start = ?, planned_end = ?, expected_update_at = ?,
                last_event_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                state,
                completion,
                owner_thread,
                owner_host,
                blocker,
                evidence,
                weight,
                duration,
                start,
                end,
                expected,
                now,
                now,
                identifier,
            ),
        )
        sequence = store.event(
            entity_type="task",
            entity_id=identifier,
            event_type="status_updated",
            summary=require_text(args.summary, "task update summary") or "Task status changed.",
            actor=args.actor,
            from_state=task["state"],
            to_state=state,
            evidence_ref=evidence,
            metadata={
                "completion_before": task["completion"],
                "completion_after": completion,
                "weight_before": task["weight"],
                "weight_after": weight,
                "duration_hours": duration,
            },
            created_at=now,
        )
    return {
        "ok": True,
        "task": identifier,
        "state": state,
        "completion": completion,
        "event_sequence": sequence,
    }


def command_issue_create(store: Store, args: argparse.Namespace) -> dict[str, object]:
    identifier = require_id(args.id, "completion issue ID")
    release_id = require_id(args.release, "release ID") if args.release else None
    requirement_id = require_id(args.requirement, "requirement ID") if args.requirement else None
    if release_id:
        store.row("releases", release_id)
    if requirement_id:
        requirement = store.row("requirements", requirement_id)
        if release_id and requirement["release_id"] != release_id:
            raise DeliveryStateError("issue requirement and release must match")
        release_id = release_id or requirement["release_id"]
    task_ids = [require_id(value, "task ID") for value in args.task]
    for task_id in task_ids:
        task = store.row("tasks", task_id)
        if release_id and task["release_id"] != release_id:
            raise DeliveryStateError("issue task and release must match")
        release_id = release_id or task["release_id"]
    now = utc_now()
    with store.connection:
        store.connection.execute(
            """
            INSERT INTO completion_issues(
                id, title, remaining_outcome, impact, state, blocks_release,
                release_id, requirement_id, detected_by, implemented_at,
                verified_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'detected', ?, ?, ?, ?, NULL, NULL, ?, ?)
            """,
            (
                identifier,
                require_text(args.title, "issue title"),
                require_text(args.remaining_outcome, "remaining outcome"),
                require_text(args.impact, "issue impact"),
                1 if args.blocks_release else 0,
                release_id,
                requirement_id,
                require_text(args.detected_by, "detected by"),
                now,
                now,
            ),
        )
        for task_id in task_ids:
            store.connection.execute(
                "INSERT INTO completion_issue_tasks(issue_id, task_id) VALUES (?, ?)",
                (identifier, task_id),
            )
        sequence = store.event(
            entity_type="completion_issue",
            entity_id=identifier,
            event_type="detected",
            summary=require_text(args.remaining_outcome, "remaining outcome") or "Incomplete work was detected.",
            actor=args.actor,
            to_state="detected",
            metadata={"release_id": release_id, "task_ids": task_ids},
            created_at=now,
        )
    return {
        "ok": True,
        "issue": identifier,
        "state": "detected",
        "release": release_id,
        "event_sequence": sequence,
    }


def command_issue_link_task(store: Store, args: argparse.Namespace) -> dict[str, object]:
    issue_id = require_id(args.issue, "completion issue ID")
    task_id = require_id(args.task, "task ID")
    issue = store.row("completion_issues", issue_id)
    task = store.row("tasks", task_id)
    if issue["release_id"] and issue["release_id"] != task["release_id"]:
        raise DeliveryStateError("issue and task must belong to the same release")
    with store.connection:
        store.connection.execute(
            "INSERT INTO completion_issue_tasks(issue_id, task_id) VALUES (?, ?)",
            (issue_id, task_id),
        )
        if issue["release_id"] is None:
            store.connection.execute(
                "UPDATE completion_issues SET release_id = ?, updated_at = ? WHERE id = ?",
                (task["release_id"], utc_now(), issue_id),
            )
        sequence = store.event(
            entity_type="completion_issue",
            entity_id=issue_id,
            event_type="task_linked",
            summary=f"Issue {issue_id} was linked to task {task_id}.",
            actor=args.actor,
            metadata={"task_id": task_id},
        )
    return {"ok": True, "issue": issue_id, "task": task_id, "event_sequence": sequence}


def command_issue_transition(store: Store, args: argparse.Namespace) -> dict[str, object]:
    identifier = require_id(args.id, "completion issue ID")
    issue = store.row("completion_issues", identifier)
    current = issue["state"]
    target = args.state
    if target not in ISSUE_TRANSITIONS[current]:
        raise DeliveryStateError(f"completion issue cannot transition from {current} to {target}")
    evidence = require_text(args.evidence_ref, "evidence reference", optional=True)
    if target in {"implemented", "verified", "superseded"} and evidence is None:
        raise DeliveryStateError(f"transitioning to {target} requires an evidence reference")
    now = utc_now()
    implemented_at = issue["implemented_at"]
    verified_at = issue["verified_at"]
    if target == "implemented":
        implemented_at = now
    if target == "verified":
        verified_at = now
    if target == "reopened":
        verified_at = None
    with store.connection:
        store.connection.execute(
            """
            UPDATE completion_issues SET
                state = ?, implemented_at = ?, verified_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (target, implemented_at, verified_at, now, identifier),
        )
        sequence = store.event(
            entity_type="completion_issue",
            entity_id=identifier,
            event_type="status_changed",
            summary=require_text(args.summary, "issue transition summary") or "Issue status changed.",
            actor=args.actor,
            from_state=current,
            to_state=target,
            evidence_ref=evidence,
            created_at=now,
        )
    return {"ok": True, "issue": identifier, "state": target, "event_sequence": sequence}


def command_issue_move(store: Store, args: argparse.Namespace) -> dict[str, object]:
    identifier = require_id(args.id, "completion issue ID")
    release_id = require_id(args.release, "release ID")
    issue = store.row("completion_issues", identifier)
    store.row("releases", release_id)
    decision = require_text(args.decision_ref, "decision reference")
    now = utc_now()
    with store.connection:
        store.connection.execute(
            "UPDATE completion_issues SET release_id = ?, updated_at = ? WHERE id = ?",
            (release_id, now, identifier),
        )
        sequence = store.event(
            entity_type="completion_issue",
            entity_id=identifier,
            event_type="release_changed",
            summary=require_text(args.summary, "release move summary") or "Issue release changed.",
            actor=args.actor,
            evidence_ref=decision,
            metadata={"from_release": issue["release_id"], "to_release": release_id},
            created_at=now,
        )
    return {"ok": True, "issue": identifier, "release": release_id, "event_sequence": sequence}


def command_issue_note(store: Store, args: argparse.Namespace) -> dict[str, object]:
    identifier = require_id(args.id, "completion issue ID")
    store.row("completion_issues", identifier)
    with store.connection:
        sequence = store.event(
            entity_type="completion_issue",
            entity_id=identifier,
            event_type="note",
            summary=require_text(args.summary, "note summary") or "Issue note added.",
            actor=args.actor,
            evidence_ref=require_text(args.evidence_ref, "evidence reference", optional=True),
        )
    return {"ok": True, "issue": identifier, "event_sequence": sequence}


def command_issue_import(store: Store, args: argparse.Namespace) -> dict[str, object]:
    source = args.input.expanduser()
    if not source.is_absolute():
        raise DeliveryStateError("issue import path must be absolute")
    if source.is_symlink() or not source.is_file():
        raise DeliveryStateError("issue import must be a regular non-symlinked file")
    raw = source.read_bytes()
    if len(raw) > MAX_IMPORT_BYTES:
        raise DeliveryStateError(f"issue import exceeds {MAX_IMPORT_BYTES} bytes")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DeliveryStateError("issue import must be valid UTF-8 JSON") from error
    if not isinstance(payload, dict) or set(payload) != {"schema", "import_id", "issues"}:
        raise DeliveryStateError("issue import must contain exactly schema, import_id, and issues")
    if payload["schema"] != IMPORT_SCHEMA:
        raise DeliveryStateError(f"issue import schema must be {IMPORT_SCHEMA}")
    import_id = require_id(payload["import_id"], "issue import ID")
    issues = payload["issues"]
    if not isinstance(issues, list) or len(issues) > MAX_RESULTS:
        raise DeliveryStateError(f"issue import issues must be a list of at most {MAX_RESULTS}")
    digest = hashlib.sha256(raw).hexdigest()
    prior = store.connection.execute(
        "SELECT digest, issue_count FROM completion_imports WHERE id = ?", (import_id,)
    ).fetchone()
    if prior is not None:
        if prior["digest"] != digest:
            raise DeliveryStateError("issue import ID was already used with different content")
        return {
            "ok": True,
            "status": "already_applied",
            "import_id": import_id,
            "digest": digest,
            "issue_count": prior["issue_count"],
        }

    expected_keys = {
        "id",
        "title",
        "remaining_outcome",
        "impact",
        "state",
        "blocks_release",
        "release_id",
        "requirement_id",
        "task_ids",
        "detected_by",
        "summary",
        "evidence_ref",
        "metadata",
    }
    normalized: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, item in enumerate(issues):
        if not isinstance(item, dict) or set(item) != expected_keys:
            raise DeliveryStateError(f"issue import item {index} has invalid fields")
        identifier = require_id(item["id"], f"issue import item {index} ID")
        if identifier in seen:
            raise DeliveryStateError(f"duplicate imported issue ID: {identifier}")
        seen.add(identifier)
        if store.connection.execute(
            "SELECT 1 FROM completion_issues WHERE id = ?", (identifier,)
        ).fetchone() is not None:
            raise DeliveryStateError(f"completion issue already exists: {identifier}")
        state = item["state"]
        if state not in ISSUE_STATES:
            raise DeliveryStateError(f"issue import item {identifier} has invalid state")
        if not isinstance(item["blocks_release"], bool):
            raise DeliveryStateError(f"issue import item {identifier} blocks_release must be boolean")
        release_id = (
            require_id(item["release_id"], "release ID") if item["release_id"] is not None else None
        )
        requirement_id = (
            require_id(item["requirement_id"], "requirement ID")
            if item["requirement_id"] is not None
            else None
        )
        if release_id:
            store.row("releases", release_id)
        if requirement_id:
            requirement = store.row("requirements", requirement_id)
            if release_id and requirement["release_id"] != release_id:
                raise DeliveryStateError(f"issue import item {identifier} requirement and release differ")
            release_id = release_id or requirement["release_id"]
        if not isinstance(item["task_ids"], list):
            raise DeliveryStateError(f"issue import item {identifier} task_ids must be a list")
        task_ids = [require_id(value, "task ID") for value in item["task_ids"]]
        if len(task_ids) != len(set(task_ids)):
            raise DeliveryStateError(f"issue import item {identifier} has duplicate task IDs")
        for task_id in task_ids:
            task = store.row("tasks", task_id)
            if release_id and task["release_id"] != release_id:
                raise DeliveryStateError(f"issue import item {identifier} task and release differ")
            release_id = release_id or task["release_id"]
        metadata = item["metadata"]
        if not isinstance(metadata, dict):
            raise DeliveryStateError(f"issue import item {identifier} metadata must be an object")
        serialized_metadata = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
        if len(serialized_metadata) > MAX_TEXT:
            raise DeliveryStateError(f"issue import item {identifier} metadata is too large")
        normalized.append(
            {
                "id": identifier,
                "title": require_text(item["title"], "issue title"),
                "remaining_outcome": require_text(item["remaining_outcome"], "remaining outcome"),
                "impact": require_text(item["impact"], "issue impact"),
                "state": state,
                "blocks_release": item["blocks_release"],
                "release_id": release_id,
                "requirement_id": requirement_id,
                "task_ids": task_ids,
                "detected_by": require_text(item["detected_by"], "detected by"),
                "summary": require_text(item["summary"], "import summary"),
                "evidence_ref": require_text(item["evidence_ref"], "evidence reference", optional=True),
                "metadata": metadata,
            }
        )

    now = utc_now()
    sequences: list[int] = []
    with store.connection:
        for item in normalized:
            state = str(item["state"])
            store.connection.execute(
                """
                INSERT INTO completion_issues(
                    id, title, remaining_outcome, impact, state, blocks_release,
                    release_id, requirement_id, detected_by, implemented_at,
                    verified_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["id"],
                    item["title"],
                    item["remaining_outcome"],
                    item["impact"],
                    state,
                    1 if item["blocks_release"] else 0,
                    item["release_id"],
                    item["requirement_id"],
                    item["detected_by"],
                    now if state in {"implemented", "verified"} else None,
                    now if state == "verified" else None,
                    now,
                    now,
                ),
            )
            for task_id in item["task_ids"]:
                store.connection.execute(
                    "INSERT INTO completion_issue_tasks(issue_id, task_id) VALUES (?, ?)",
                    (item["id"], task_id),
                )
            event_metadata = dict(item["metadata"])
            event_metadata["import_id"] = import_id
            sequences.append(
                store.event(
                    entity_type="completion_issue",
                    entity_id=str(item["id"]),
                    event_type="imported",
                    summary=str(item["summary"]),
                    actor=args.actor,
                    to_state=state,
                    evidence_ref=item["evidence_ref"],
                    metadata=event_metadata,
                    created_at=now,
                )
            )
        store.connection.execute(
            "INSERT INTO completion_imports(id, digest, issue_count, created_at) VALUES (?, ?, ?, ?)",
            (import_id, digest, len(normalized), now),
        )
    return {
        "ok": True,
        "status": "applied",
        "import_id": import_id,
        "digest": digest,
        "issue_count": len(normalized),
        "issue_ids": [item["id"] for item in normalized],
        "event_sequences": sequences,
    }


def command_monitor_configure(store: Store, args: argparse.Namespace) -> dict[str, object]:
    release_id = require_id(args.release, "release ID")
    store.row("releases", release_id)
    existing = monitoring_row(store, release_id)
    if existing is not None and (
        existing["automation_enabled"] == 1 or existing["state"] in {"arming", "armed"}
    ):
        raise DeliveryStateError("active monitoring must be stopped before it is reconfigured")
    coordinator_thread = require_text(args.coordinator_thread, "coordinator thread ID")
    executor_thread = require_text(args.executor_thread, "executor thread ID")
    executor_host = require_text(args.executor_host, "executor host ID")
    cadence = int(args.cadence_minutes)
    if cadence < 1 or cadence > 1440:
        raise DeliveryStateError("monitor cadence must be between 1 and 1440 minutes")
    now = utc_now()
    availability = now if args.availability_confirmed else None
    with store.connection:
        store.connection.execute(
            """
            INSERT INTO monitoring_schedules(
                release_id, coordinator_thread_id, executor_thread_id,
                executor_host_id, automation_id, cadence_minutes, state, cursor,
                local_files, availability_confirmed_at, automation_enabled,
                first_run_verified_at, next_run_at, last_run_key, last_started_at,
                last_completed_at, blocker_summary, stop_reason, created_at, updated_at
            ) VALUES (?, ?, ?, ?, NULL, ?, 'unarmed', NULL, ?, ?, 0, NULL, NULL,
                      NULL, NULL, NULL, NULL, NULL, ?, ?)
            ON CONFLICT(release_id) DO UPDATE SET
                coordinator_thread_id = excluded.coordinator_thread_id,
                executor_thread_id = excluded.executor_thread_id,
                executor_host_id = excluded.executor_host_id,
                automation_id = NULL,
                cadence_minutes = excluded.cadence_minutes,
                state = 'unarmed',
                cursor = NULL,
                local_files = excluded.local_files,
                availability_confirmed_at = excluded.availability_confirmed_at,
                automation_enabled = 0,
                first_run_verified_at = NULL,
                next_run_at = NULL,
                blocker_summary = NULL,
                stop_reason = NULL,
                updated_at = excluded.updated_at
            """,
            (
                release_id,
                coordinator_thread,
                executor_thread,
                executor_host,
                cadence,
                1 if args.local_files else 0,
                availability,
                now,
                now,
            ),
        )
        sequence = store.event(
            entity_type="monitoring",
            entity_id=release_id,
            event_type="configured",
            summary="Durable same-chat monitoring was configured but is not armed.",
            actor=args.actor,
            from_state=existing["state"] if existing is not None else None,
            to_state="unarmed",
            metadata={
                "cadence_minutes": cadence,
                "coordinator_thread_id": coordinator_thread,
                "executor_thread_id": executor_thread,
                "executor_host_id": executor_host,
                "local_files": bool(args.local_files),
                "availability_confirmed": bool(args.availability_confirmed),
            },
            created_at=now,
        )
    return {"ok": True, "release": release_id, "state": "unarmed", "event_sequence": sequence}


def command_monitor_arm(store: Store, args: argparse.Namespace) -> dict[str, object]:
    release_id = require_id(args.release, "release ID")
    monitor = monitoring_row(store, release_id)
    if monitor is None:
        raise DeliveryStateError("monitoring must be configured before it is armed")
    if monitor["state"] not in {"unarmed", "blocked", "stopped"}:
        raise DeliveryStateError(f"monitoring cannot be armed from {monitor['state']}")
    if monitor["local_files"] == 1 and not monitor["availability_confirmed_at"]:
        raise DeliveryStateError("local-file monitoring requires desktop app and machine availability confirmation")
    automation_id = require_text(args.automation_id, "scheduled task ID")
    next_run = normalize_timestamp(args.next_run_at, "next scheduled run")
    evidence = require_text(args.evidence_ref, "schedule creation evidence")
    now = utc_now()
    with store.connection:
        store.connection.execute(
            """
            UPDATE monitoring_schedules SET automation_id = ?, state = 'arming',
                automation_enabled = 1, first_run_verified_at = NULL,
                next_run_at = ?, blocker_summary = NULL, stop_reason = NULL,
                updated_at = ? WHERE release_id = ?
            """,
            (automation_id, next_run, now, release_id),
        )
        sequence = store.event(
            entity_type="monitoring",
            entity_id=release_id,
            event_type="schedule_enabled",
            summary="The same-chat scheduled task is enabled; first-run verification remains required.",
            actor=args.actor,
            from_state=monitor["state"],
            to_state="arming",
            evidence_ref=evidence,
            metadata={"automation_id": automation_id, "next_run_at": next_run},
            created_at=now,
        )
    return {"ok": True, "release": release_id, "state": "arming", "event_sequence": sequence}


def command_monitor_run_start(store: Store, args: argparse.Namespace) -> dict[str, object]:
    release_id = require_id(args.release, "release ID")
    run_key = require_id(args.run_key, "monitor run key")
    scheduled_for = normalize_timestamp(args.scheduled_for, "scheduled run time")
    monitor = monitoring_row(store, release_id)
    if monitor is None or monitor["state"] not in {"arming", "armed"}:
        raise DeliveryStateError("monitoring must be arming or armed before a run starts")
    if monitor["automation_enabled"] != 1:
        raise DeliveryStateError("monitoring scheduled task is not enabled")
    existing = store.connection.execute(
        "SELECT * FROM monitoring_runs WHERE run_key = ?", (run_key,)
    ).fetchone()
    if existing is not None:
        return {
            "ok": True,
            "status": "already_recorded" if existing["state"] != "running" else "already_running",
            "release": release_id,
            "run_key": run_key,
            "state": existing["state"],
        }
    overlap = store.connection.execute(
        "SELECT run_key FROM monitoring_runs WHERE release_id = ? AND state = 'running' LIMIT 1",
        (release_id,),
    ).fetchone()
    now = utc_now()
    with store.connection:
        if overlap is not None:
            store.connection.execute(
                """
                INSERT INTO monitoring_runs(
                    run_key, release_id, scheduled_for, state, cursor_before,
                    cursor_after, summary, evidence_ref, started_at, completed_at
                ) VALUES (?, ?, ?, 'skipped_overlap', ?, ?, ?, NULL, ?, ?)
                """,
                (
                    run_key,
                    release_id,
                    scheduled_for,
                    monitor["cursor"],
                    monitor["cursor"],
                    f"Skipped because run {overlap['run_key']} is still active.",
                    now,
                    now,
                ),
            )
            sequence = store.event(
                entity_type="monitoring",
                entity_id=release_id,
                event_type="overlap_skipped",
                summary=f"Monitor run {run_key} was skipped because another run is active.",
                actor=args.actor,
                metadata={"run_key": run_key, "active_run_key": overlap["run_key"]},
                created_at=now,
            )
            return {
                "ok": True,
                "status": "skipped_overlap",
                "release": release_id,
                "run_key": run_key,
                "active_run_key": overlap["run_key"],
                "event_sequence": sequence,
            }
        store.connection.execute(
            """
            INSERT INTO monitoring_runs(
                run_key, release_id, scheduled_for, state, cursor_before,
                cursor_after, summary, evidence_ref, started_at, completed_at
            ) VALUES (?, ?, ?, 'running', ?, NULL, NULL, NULL, ?, NULL)
            """,
            (run_key, release_id, scheduled_for, monitor["cursor"], now),
        )
        store.connection.execute(
            """
            UPDATE monitoring_schedules SET last_run_key = ?, last_started_at = ?,
                updated_at = ? WHERE release_id = ?
            """,
            (run_key, now, now, release_id),
        )
        sequence = store.event(
            entity_type="monitoring",
            entity_id=release_id,
            event_type="run_started",
            summary=f"Monitor run {run_key} started with the retained cursor.",
            actor=args.actor,
            metadata={"run_key": run_key, "cursor_before": monitor["cursor"]},
            created_at=now,
        )
    return {"ok": True, "status": "started", "release": release_id, "run_key": run_key, "event_sequence": sequence}


def command_monitor_run_finish(store: Store, args: argparse.Namespace) -> dict[str, object]:
    run_key = require_id(args.run_key, "monitor run key")
    run = store.connection.execute(
        "SELECT * FROM monitoring_runs WHERE run_key = ?", (run_key,)
    ).fetchone()
    if run is None:
        raise DeliveryStateError(f"unknown monitor run: {run_key}")
    if run["state"] != "running":
        raise DeliveryStateError(f"monitor run {run_key} is already {run['state']}")
    outcome = args.state
    summary = require_text(args.summary, "monitor run summary")
    evidence = require_text(args.evidence_ref, "monitor run evidence", optional=True)
    cursor = require_text(args.cursor, "retained cursor", optional=outcome == "failed")
    next_run = normalize_timestamp(args.next_run_at, "next scheduled run") if args.next_run_at else None
    if outcome == "completed" and (cursor is None or next_run is None):
        raise DeliveryStateError("a completed monitor run requires retained cursor and next scheduled run")
    monitor = monitoring_row(store, run["release_id"])
    if monitor is None:
        raise DeliveryStateError("monitoring schedule disappeared during its run")
    now = utc_now()
    schedule_state = "blocked" if outcome == "failed" else monitor["state"]
    blocker = summary if outcome == "failed" else None
    with store.connection:
        store.connection.execute(
            """
            UPDATE monitoring_runs SET state = ?, cursor_after = ?, summary = ?,
                evidence_ref = ?, completed_at = ? WHERE run_key = ?
            """,
            (outcome, cursor, summary, evidence, now, run_key),
        )
        store.connection.execute(
            """
            UPDATE monitoring_schedules SET state = ?, cursor = COALESCE(?, cursor),
                last_completed_at = ?, next_run_at = COALESCE(?, next_run_at),
                blocker_summary = ?, updated_at = ? WHERE release_id = ?
            """,
            (schedule_state, cursor, now, next_run, blocker, now, run["release_id"]),
        )
        sequence = store.event(
            entity_type="monitoring",
            entity_id=run["release_id"],
            event_type="run_finished",
            summary=summary or "Monitor run finished.",
            actor=args.actor,
            from_state=monitor["state"],
            to_state=schedule_state,
            evidence_ref=evidence,
            metadata={
                "run_key": run_key,
                "run_state": outcome,
                "cursor_before": run["cursor_before"],
                "cursor_after": cursor,
                "next_run_at": next_run,
            },
            created_at=now,
        )
    return {"ok": True, "release": run["release_id"], "run_key": run_key, "state": outcome, "event_sequence": sequence}


def command_monitor_verify_first_run(store: Store, args: argparse.Namespace) -> dict[str, object]:
    release_id = require_id(args.release, "release ID")
    run_key = require_id(args.run_key, "monitor run key")
    monitor = monitoring_row(store, release_id)
    if monitor is None or monitor["state"] != "arming":
        raise DeliveryStateError("monitoring must be arming before first-run verification")
    run = store.connection.execute(
        "SELECT * FROM monitoring_runs WHERE run_key = ? AND release_id = ?",
        (run_key, release_id),
    ).fetchone()
    if run is None or run["state"] != "completed" or not run["cursor_after"]:
        raise DeliveryStateError("first-run verification requires one completed run with retained cursor")
    evidence = require_text(args.evidence_ref, "first-run verification evidence")
    now = utc_now()
    with store.connection:
        store.connection.execute(
            """
            UPDATE monitoring_schedules SET state = 'armed', cursor = ?,
                first_run_verified_at = ?, blocker_summary = NULL, updated_at = ?
            WHERE release_id = ?
            """,
            (run["cursor_after"], now, now, release_id),
        )
        sequence = store.event(
            entity_type="monitoring",
            entity_id=release_id,
            event_type="first_run_verified",
            summary="The first same-chat scheduled monitoring run completed successfully.",
            actor=args.actor,
            from_state="arming",
            to_state="armed",
            evidence_ref=evidence,
            metadata={"run_key": run_key, "cursor": run["cursor_after"]},
            created_at=now,
        )
    return {"ok": True, "release": release_id, "state": "armed", "ready": True, "event_sequence": sequence}


def command_monitor_block(store: Store, args: argparse.Namespace) -> dict[str, object]:
    release_id = require_id(args.release, "release ID")
    monitor = monitoring_row(store, release_id)
    if monitor is None:
        raise DeliveryStateError("monitoring must be configured before it is blocked")
    reason = require_text(args.reason, "monitoring blocker")
    evidence = require_text(args.evidence_ref, "blocker evidence", optional=True)
    now = utc_now()
    with store.connection:
        store.connection.execute(
            "UPDATE monitoring_schedules SET state = 'blocked', blocker_summary = ?, updated_at = ? WHERE release_id = ?",
            (reason, now, release_id),
        )
        sequence = store.event(
            entity_type="monitoring",
            entity_id=release_id,
            event_type="blocked",
            summary=reason or "Monitoring is blocked.",
            actor=args.actor,
            from_state=monitor["state"],
            to_state="blocked",
            evidence_ref=evidence,
            created_at=now,
        )
    return {"ok": True, "release": release_id, "state": "blocked", "ready": False, "event_sequence": sequence}


def command_monitor_stop(store: Store, args: argparse.Namespace) -> dict[str, object]:
    release_id = require_id(args.release, "release ID")
    monitor = monitoring_row(store, release_id)
    if monitor is None:
        raise DeliveryStateError("monitoring is not configured")
    reason = require_text(args.reason, "monitoring stop reason")
    evidence = require_text(args.evidence_ref, "scheduled-task disable evidence")
    now = utc_now()
    with store.connection:
        store.connection.execute(
            """
            UPDATE monitoring_schedules SET state = 'stopped', automation_enabled = 0,
                next_run_at = NULL, blocker_summary = NULL, stop_reason = ?,
                updated_at = ? WHERE release_id = ?
            """,
            (reason, now, release_id),
        )
        sequence = store.event(
            entity_type="monitoring",
            entity_id=release_id,
            event_type="stopped",
            summary=reason or "Monitoring stopped.",
            actor=args.actor,
            from_state=monitor["state"],
            to_state="stopped",
            evidence_ref=evidence,
            created_at=now,
        )
    return {"ok": True, "release": release_id, "state": "stopped", "ready": False, "event_sequence": sequence}


def command_monitor_status(store: Store, args: argparse.Namespace) -> dict[str, object]:
    release_id = require_id(args.release, "release ID")
    store.row("releases", release_id)
    monitor = monitoring_row(store, release_id)
    if monitor is None:
        return {
            "ok": True,
            "release": release_id,
            "configured": False,
            "state": "unarmed",
            "ready": False,
            "reason": "no monitoring schedule is configured",
        }
    item = as_dict(monitor)
    item["local_files"] = bool(item["local_files"])
    item["automation_enabled"] = bool(item["automation_enabled"])
    item["ready"] = monitoring_ready(monitor)
    return {"ok": True, "release": release_id, "configured": True, "monitoring": item}


def issue_filter_states(selection: str) -> set[str] | None:
    if selection == "not-implemented":
        return NOT_IMPLEMENTED_STATES
    if selection == "outstanding":
        return OUTSTANDING_ISSUE_STATES
    if selection == "all":
        return None
    return {selection}


def command_issue_list(store: Store, args: argparse.Namespace) -> dict[str, object]:
    limit = require_limit(args.limit)
    states = issue_filter_states(args.state)
    clauses: list[str] = []
    parameters: list[object] = []
    if states is not None:
        placeholders = ",".join("?" for _ in states)
        clauses.append(f"issue.state IN ({placeholders})")
        parameters.extend(sorted(states))
    if args.release:
        clauses.append("issue.release_id = ?")
        parameters.append(require_id(args.release, "release ID"))
    if args.task:
        clauses.append(
            "EXISTS (SELECT 1 FROM completion_issue_tasks link "
            "WHERE link.issue_id = issue.id AND link.task_id = ?)"
        )
        parameters.append(require_id(args.task, "task ID"))
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    parameters.append(limit)
    rows = store.connection.execute(
        """
        SELECT issue.*, GROUP_CONCAT(link.task_id, ',') AS task_ids
        FROM completion_issues AS issue
        LEFT JOIN completion_issue_tasks AS link ON link.issue_id = issue.id
        """
        + where
        + " GROUP BY issue.id ORDER BY issue.updated_at DESC, issue.id LIMIT ?",
        parameters,
    ).fetchall()
    items = []
    for row in rows:
        item = as_dict(row)
        item["blocks_release"] = bool(item["blocks_release"])
        item["task_ids"] = item["task_ids"].split(",") if item["task_ids"] else []
        items.append(item)
    return {"ok": True, "selection": args.state, "count": len(items), "issues": items}


def command_issue_history(store: Store, args: argparse.Namespace) -> dict[str, object]:
    identifier = require_id(args.id, "completion issue ID")
    issue = store.row("completion_issues", identifier)
    limit = require_limit(args.limit)
    rows = store.connection.execute(
        """
        SELECT * FROM (
            SELECT * FROM events
            WHERE entity_type = 'completion_issue' AND entity_id = ?
            ORDER BY sequence DESC LIMIT ?
        ) ORDER BY sequence ASC
        """,
        (identifier, limit),
    ).fetchall()
    events = [as_dict(row) for row in rows]
    for event in events:
        event["metadata"] = json.loads(str(event.pop("metadata_json")))
    return {"ok": True, "issue": as_dict(issue), "event_count": len(events), "events": events}


def release_progress_rows(store: Store) -> list[dict[str, object]]:
    releases = store.connection.execute(
        "SELECT * FROM releases WHERE status <> 'cancelled' ORDER BY created_at, id"
    ).fetchall()
    result: list[dict[str, object]] = []
    for release in releases:
        task_stats = store.connection.execute(
            """
            SELECT
                COUNT(*) AS task_count,
                SUM(CASE WHEN state = 'done' THEN 1 ELSE 0 END) AS done_count,
                SUM(weight) AS total_weight,
                SUM(weight * completion) AS earned_weight
            FROM tasks WHERE release_id = ? AND state <> 'cancelled'
            """,
            (release["id"],),
        ).fetchone()
        issue_stats = store.connection.execute(
            """
            SELECT
                SUM(CASE WHEN state IN ('detected','planned','in_progress','blocked','reopened') THEN 1 ELSE 0 END) AS not_implemented,
                SUM(CASE WHEN state = 'implemented' THEN 1 ELSE 0 END) AS implemented_unverified,
                SUM(CASE WHEN state = 'verified' THEN 1 ELSE 0 END) AS verified,
                SUM(CASE WHEN blocks_release = 1 AND state NOT IN ('verified','superseded') THEN 1 ELSE 0 END) AS blocking
            FROM completion_issues WHERE release_id = ?
            """,
            (release["id"],),
        ).fetchone()
        total_weight = float(task_stats["total_weight"] or 0)
        progress = (
            round(float(task_stats["earned_weight"] or 0) / total_weight, 1)
            if total_weight
            else 0.0
        )
        open_tasks, open_issues = release_blockers(store, release["id"])
        monitor = monitoring_row(store, release["id"])
        result.append(
            {
                "id": release["id"],
                "name": release["name"],
                "status": release["status"],
                "scope_revision": release["scope_revision"],
                "weight": release["weight"],
                "progress_percent": progress,
                "task_count": int(task_stats["task_count"] or 0),
                "done_task_count": int(task_stats["done_count"] or 0),
                "requirement_count": int(
                    store.connection.execute(
                        "SELECT COUNT(*) AS value FROM requirements WHERE release_id = ? AND status = 'approved'",
                        (release["id"],),
                    ).fetchone()["value"]
                ),
                "not_implemented_issue_count": int(issue_stats["not_implemented"] or 0),
                "implemented_unverified_issue_count": int(issue_stats["implemented_unverified"] or 0),
                "verified_issue_count": int(issue_stats["verified"] or 0),
                "blocking_issue_count": int(issue_stats["blocking"] or 0),
                "monitoring_state": monitor["state"] if monitor is not None else "unarmed",
                "monitoring_ready": monitoring_ready(monitor),
                "monitoring_next_run_at": monitor["next_run_at"] if monitor is not None else None,
                "ready": bool(task_stats["task_count"])
                and not open_tasks
                and not open_issues
                and bool(
                    store.connection.execute(
                        "SELECT COUNT(*) AS value FROM requirements WHERE release_id = ? AND status = 'approved'",
                        (release["id"],),
                    ).fetchone()["value"]
                ),
            }
        )
    return result


def command_status(store: Store, args: argparse.Namespace) -> dict[str, object]:
    releases = release_progress_rows(store)
    if args.release:
        release_id = require_id(args.release, "release ID")
        releases = [item for item in releases if item["id"] == release_id]
        if not releases:
            store.row("releases", release_id)
    approved_releases = [item for item in releases if item["status"] != "draft"]
    total_release_weight = sum(float(item["weight"]) for item in approved_releases)
    overall = (
        round(
            sum(
                float(item["weight"]) * float(item["progress_percent"])
                for item in approved_releases
            )
            / total_release_weight,
            1,
        )
        if total_release_weight
        else 0.0
    )
    max_sequence = store.connection.execute("SELECT COALESCE(MAX(sequence), 0) AS value FROM events").fetchone()[
        "value"
    ]
    ledger = store.connection.execute(
        """
        SELECT
            SUM(CASE WHEN state IN ('detected','planned','in_progress','blocked','reopened') THEN 1 ELSE 0 END) AS not_implemented,
            SUM(CASE WHEN state = 'implemented' THEN 1 ELSE 0 END) AS implemented_unverified,
            SUM(CASE WHEN state = 'verified' THEN 1 ELSE 0 END) AS verified,
            SUM(CASE WHEN release_id IS NULL AND state NOT IN ('verified','superseded') THEN 1 ELSE 0 END) AS unassigned,
            SUM(CASE WHEN blocks_release = 1 AND state NOT IN ('verified','superseded') THEN 1 ELSE 0 END) AS blocking
        FROM completion_issues
        """
    ).fetchone()
    return {
        "ok": True,
        "database_id": store.database_id,
        "overall_progress_percent": overall,
        "approved_scope_baselines": [
            f"{item['id']}:r{item['scope_revision']}" for item in approved_releases
        ],
        "ledger": {
            "not_implemented": int(ledger["not_implemented"] or 0),
            "implemented_unverified": int(ledger["implemented_unverified"] or 0),
            "verified": int(ledger["verified"] or 0),
            "unassigned_outstanding": int(ledger["unassigned"] or 0),
            "blocking": int(ledger["blocking"] or 0),
        },
        "release_count": len(releases),
        "releases": releases,
        "latest_event_sequence": max_sequence,
    }


def command_release_show(store: Store, args: argparse.Namespace) -> dict[str, object]:
    release_id = require_id(args.release, "release ID")
    limit = require_limit(args.limit)
    release = store.row("releases", release_id)
    requirements = store.connection.execute(
        "SELECT * FROM requirements WHERE release_id = ? ORDER BY id LIMIT ?",
        (release_id, limit),
    ).fetchall()
    tasks = store.connection.execute(
        "SELECT * FROM tasks WHERE release_id = ? ORDER BY id LIMIT ?",
        (release_id, limit),
    ).fetchall()
    dependencies = store.connection.execute(
        """
        SELECT dependency.task_id, dependency.depends_on_task_id
        FROM task_dependencies AS dependency
        JOIN tasks AS task ON task.id = dependency.task_id
        WHERE task.release_id = ?
        ORDER BY dependency.task_id, dependency.depends_on_task_id
        LIMIT ?
        """,
        (release_id, limit),
    ).fetchall()
    issues = store.connection.execute(
        """
        SELECT issue.*, GROUP_CONCAT(link.task_id, ',') AS task_ids
        FROM completion_issues AS issue
        LEFT JOIN completion_issue_tasks AS link ON link.issue_id = issue.id
        WHERE issue.release_id = ? AND issue.state NOT IN ('verified', 'superseded')
        GROUP BY issue.id ORDER BY issue.updated_at DESC, issue.id LIMIT ?
        """,
        (release_id, limit),
    ).fetchall()
    issue_items: list[dict[str, object]] = []
    for row in issues:
        item = as_dict(row)
        item["blocks_release"] = bool(item["blocks_release"])
        item["task_ids"] = item["task_ids"].split(",") if item["task_ids"] else []
        issue_items.append(item)
    return {
        "ok": True,
        "scope_baseline": f"{release_id}:r{release['scope_revision']}",
        "release": as_dict(release),
        "monitoring": as_dict(monitoring_row(store, release_id))
        if monitoring_row(store, release_id) is not None
        else None,
        "requirements": [as_dict(row) for row in requirements],
        "tasks": [as_dict(row) for row in tasks],
        "dependencies": [as_dict(row) for row in dependencies],
        "outstanding_issues": issue_items,
        "truncated_at": limit,
    }


def command_task_show(store: Store, args: argparse.Namespace) -> dict[str, object]:
    task_id = require_id(args.task, "task ID")
    task = store.row("tasks", task_id)
    release = store.row("releases", task["release_id"])
    requirement = (
        as_dict(store.row("requirements", task["requirement_id"]))
        if task["requirement_id"]
        else None
    )
    dependencies = store.connection.execute(
        "SELECT depends_on_task_id FROM task_dependencies WHERE task_id = ? ORDER BY depends_on_task_id",
        (task_id,),
    ).fetchall()
    issues = store.connection.execute(
        """
        SELECT issue.* FROM completion_issues AS issue
        JOIN completion_issue_tasks AS link ON link.issue_id = issue.id
        WHERE link.task_id = ? AND issue.state NOT IN ('verified', 'superseded')
        ORDER BY issue.updated_at DESC, issue.id
        """,
        (task_id,),
    ).fetchall()
    return {
        "ok": True,
        "scope_baseline": f"{release['id']}:r{release['scope_revision']}",
        "release": as_dict(release),
        "requirement": requirement,
        "task": as_dict(task),
        "depends_on": [row["depends_on_task_id"] for row in dependencies],
        "outstanding_issues": [as_dict(row) for row in issues],
    }


def command_events(store: Store, args: argparse.Namespace) -> dict[str, object]:
    limit = require_limit(args.limit)
    if args.after < 0:
        raise DeliveryStateError("after sequence must not be negative")
    rows = store.connection.execute(
        """
        SELECT * FROM events WHERE sequence > ?
        ORDER BY sequence ASC LIMIT ?
        """,
        (args.after, limit),
    ).fetchall()
    events = [as_dict(row) for row in rows]
    for event in events:
        event["metadata"] = json.loads(str(event.pop("metadata_json")))
    latest = events[-1]["sequence"] if events else args.after
    return {"ok": True, "after": args.after, "latest": latest, "count": len(events), "events": events}


def command_monitor_snapshot(store: Store, args: argparse.Namespace) -> dict[str, object]:
    now = normalize_timestamp(args.now, "monitor time") if args.now else utc_now()
    stale = store.connection.execute(
        """
        SELECT id, release_id, state, completion, owner_thread_id, owner_host_id,
               expected_update_at, blocker_summary
        FROM tasks
        WHERE state NOT IN ('done', 'cancelled')
          AND expected_update_at IS NOT NULL
          AND expected_update_at <= ?
        ORDER BY expected_update_at, id
        """,
        (now,),
    ).fetchall()
    failed = store.connection.execute(
        "SELECT id, release_id, owner_thread_id, owner_host_id FROM tasks WHERE state = 'failed' ORDER BY id"
    ).fetchall()
    blocked = store.connection.execute(
        """
        SELECT id, release_id, owner_thread_id, owner_host_id, blocker_summary
        FROM tasks WHERE state = 'blocked' ORDER BY id
        """
    ).fetchall()
    blocking_issues = store.connection.execute(
        """
        SELECT id, release_id, state, remaining_outcome, impact
        FROM completion_issues
        WHERE blocks_release = 1 AND state NOT IN ('verified', 'superseded')
        ORDER BY release_id, id
        """
    ).fetchall()
    monitored_releases = store.connection.execute(
        """
        SELECT id, name, status FROM releases
        WHERE status IN ('approved', 'active', 'acceptance')
        ORDER BY id
        """
    ).fetchall()
    monitoring_gaps: list[dict[str, object]] = []
    for release in monitored_releases:
        monitor = monitoring_row(store, release["id"])
        if not monitoring_ready(monitor):
            monitoring_gaps.append(
                {
                    "release_id": release["id"],
                    "release_name": release["name"],
                    "release_state": release["status"],
                    "monitoring_state": monitor["state"] if monitor is not None else "unarmed",
                    "automation_enabled": bool(monitor["automation_enabled"])
                    if monitor is not None
                    else False,
                    "blocker_summary": monitor["blocker_summary"]
                    if monitor is not None
                    else "no monitoring schedule is configured",
                }
            )
    active_monitor_runs = store.connection.execute(
        """
        SELECT run_key, release_id, scheduled_for, started_at
        FROM monitoring_runs WHERE state = 'running'
        ORDER BY started_at, run_key
        """
    ).fetchall()
    max_sequence = store.connection.execute("SELECT COALESCE(MAX(sequence), 0) AS value FROM events").fetchone()[
        "value"
    ]
    return {
        "ok": True,
        "observed_at": now,
        "latest_event_sequence": max_sequence,
        "stale_tasks": [as_dict(row) for row in stale],
        "failed_tasks": [as_dict(row) for row in failed],
        "blocked_tasks": [as_dict(row) for row in blocked],
        "blocking_issues": [as_dict(row) for row in blocking_issues],
        "monitoring_gaps": monitoring_gaps,
        "active_monitor_runs": [as_dict(row) for row in active_monitor_runs],
    }


def command_gantt_data(store: Store, args: argparse.Namespace) -> dict[str, object]:
    release_id = require_id(args.release, "release ID")
    release = store.row("releases", release_id)
    tasks = store.connection.execute(
        """
        SELECT id, title, state, completion, duration_hours, planned_start,
               planned_end, owner_thread_id, owner_host_id, outcome, weight,
               blocker_summary, expected_update_at
        FROM tasks WHERE release_id = ? AND state <> 'cancelled'
        ORDER BY planned_start IS NULL, planned_start, id
        """,
        (release_id,),
    ).fetchall()
    dependencies = store.connection.execute(
        """
        SELECT dependency.task_id, dependency.depends_on_task_id
        FROM task_dependencies AS dependency
        JOIN tasks AS task ON task.id = dependency.task_id
        WHERE task.release_id = ?
        ORDER BY dependency.task_id, dependency.depends_on_task_id
        """,
        (release_id,),
    ).fetchall()
    return {
        "ok": True,
        "schema": "holyskills.product-delivery.gantt.v1",
        "release": {
            "id": release["id"],
            "name": release["name"],
            "outcome": release["outcome"],
            "planned_start": release["planned_start"],
            "planned_end": release["planned_end"],
            "scope_revision": release["scope_revision"],
        },
        "tasks": [as_dict(row) for row in tasks],
        "dependencies": [as_dict(row) for row in dependencies],
    }


def add_common_mutation_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--actor", required=True, help="stable agent, user, or thread identity")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--db", type=Path, help="explicit absolute database path")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="initialize or verify the project delivery database")

    command = subparsers.add_parser("release-create", help="create a draft release")
    command.add_argument("--id", required=True)
    command.add_argument("--name", required=True)
    command.add_argument("--outcome", required=True)
    command.add_argument("--weight", type=float, default=1.0)
    command.add_argument("--planned-start")
    command.add_argument("--planned-end")
    add_common_mutation_arguments(command)

    command = subparsers.add_parser("release-rebaseline", help="record an approved release scope revision")
    command.add_argument("--id", required=True)
    command.add_argument("--decision-ref", required=True)
    command.add_argument("--summary", required=True)
    command.add_argument("--name")
    command.add_argument("--outcome")
    command.add_argument("--weight", type=float)
    command.add_argument("--planned-start")
    command.add_argument("--planned-end")
    add_common_mutation_arguments(command)

    command = subparsers.add_parser("release-transition", help="change release lifecycle state")
    command.add_argument("--id", required=True)
    command.add_argument("--state", required=True, choices=sorted(RELEASE_STATES))
    command.add_argument("--summary", required=True)
    command.add_argument("--evidence-ref")
    add_common_mutation_arguments(command)

    command = subparsers.add_parser("requirement-create", help="add one approved release requirement")
    command.add_argument("--id", required=True)
    command.add_argument("--release", required=True)
    command.add_argument("--statement", required=True)
    command.add_argument("--acceptance", required=True)
    add_common_mutation_arguments(command)

    command = subparsers.add_parser("task-create", help="add one weighted work-graph task")
    command.add_argument("--id", required=True)
    command.add_argument("--release", required=True)
    command.add_argument("--requirement")
    command.add_argument("--title", required=True)
    command.add_argument("--outcome", required=True)
    command.add_argument("--weight", required=True, type=float)
    command.add_argument("--duration-hours", type=float)
    command.add_argument("--planned-start")
    command.add_argument("--planned-end")
    command.add_argument("--owner-thread")
    command.add_argument("--owner-host")
    command.add_argument("--expected-update-at")
    add_common_mutation_arguments(command)

    command = subparsers.add_parser("task-update", help="record task state and completion")
    command.add_argument("--id", required=True)
    command.add_argument("--state", choices=sorted(TASK_STATES))
    command.add_argument("--completion", type=int)
    command.add_argument("--weight", type=float)
    command.add_argument("--duration-hours", type=float)
    command.add_argument("--summary", required=True)
    command.add_argument("--owner-thread")
    command.add_argument("--owner-host")
    command.add_argument("--blocker")
    command.add_argument("--evidence-ref")
    command.add_argument("--planned-start")
    command.add_argument("--planned-end")
    command.add_argument("--expected-update-at")
    add_common_mutation_arguments(command)

    command = subparsers.add_parser("dependency-add", help="add an acyclic task dependency")
    command.add_argument("--task", required=True)
    command.add_argument("--depends-on", required=True)
    add_common_mutation_arguments(command)

    command = subparsers.add_parser("issue-create", help="record detected incomplete or compromised work")
    command.add_argument("--id", required=True)
    command.add_argument("--title", required=True)
    command.add_argument("--remaining-outcome", required=True)
    command.add_argument("--impact", required=True)
    command.add_argument("--release")
    command.add_argument("--requirement")
    command.add_argument("--task", action="append", default=[])
    command.add_argument("--detected-by", required=True)
    command.add_argument("--blocks-release", action="store_true")
    add_common_mutation_arguments(command)

    command = subparsers.add_parser("issue-link-task", help="link a permanent issue to a work task")
    command.add_argument("--issue", required=True)
    command.add_argument("--task", required=True)
    add_common_mutation_arguments(command)

    command = subparsers.add_parser("issue-transition", help="append an issue lifecycle transition")
    command.add_argument("--id", required=True)
    command.add_argument("--state", required=True, choices=sorted(ISSUE_STATES))
    command.add_argument("--summary", required=True)
    command.add_argument("--evidence-ref")
    add_common_mutation_arguments(command)

    command = subparsers.add_parser("issue-move", help="move an issue without erasing its history")
    command.add_argument("--id", required=True)
    command.add_argument("--release", required=True)
    command.add_argument("--decision-ref", required=True)
    command.add_argument("--summary", required=True)
    add_common_mutation_arguments(command)

    command = subparsers.add_parser("issue-note", help="append a permanent issue note")
    command.add_argument("--id", required=True)
    command.add_argument("--summary", required=True)
    command.add_argument("--evidence-ref")
    add_common_mutation_arguments(command)

    command = subparsers.add_parser("issue-import", help="transactionally import reviewed issues")
    command.add_argument("--input", required=True, type=Path)
    add_common_mutation_arguments(command)

    command = subparsers.add_parser("monitor-configure", help="configure durable same-chat monitoring")
    command.add_argument("--release", required=True)
    command.add_argument("--coordinator-thread", required=True)
    command.add_argument("--executor-thread", required=True)
    command.add_argument("--executor-host", required=True)
    command.add_argument("--cadence-minutes", type=int, default=60)
    command.add_argument("--local-files", action="store_true")
    command.add_argument("--availability-confirmed", action="store_true")
    add_common_mutation_arguments(command)

    command = subparsers.add_parser("monitor-arm", help="record an enabled same-chat scheduled task")
    command.add_argument("--release", required=True)
    command.add_argument("--automation-id", required=True)
    command.add_argument("--next-run-at", required=True)
    command.add_argument("--evidence-ref", required=True)
    add_common_mutation_arguments(command)

    command = subparsers.add_parser("monitor-run-start", help="start one idempotent monitoring run")
    command.add_argument("--release", required=True)
    command.add_argument("--run-key", required=True)
    command.add_argument("--scheduled-for", required=True)
    add_common_mutation_arguments(command)

    command = subparsers.add_parser("monitor-run-finish", help="finish one monitoring run")
    command.add_argument("--run-key", required=True)
    command.add_argument("--state", required=True, choices=["completed", "failed"])
    command.add_argument("--summary", required=True)
    command.add_argument("--cursor")
    command.add_argument("--next-run-at")
    command.add_argument("--evidence-ref")
    add_common_mutation_arguments(command)

    command = subparsers.add_parser(
        "monitor-verify-first-run",
        help="promote monitoring to armed after a completed first scheduled run",
    )
    command.add_argument("--release", required=True)
    command.add_argument("--run-key", required=True)
    command.add_argument("--evidence-ref", required=True)
    add_common_mutation_arguments(command)

    command = subparsers.add_parser("monitor-block", help="record that ongoing monitoring is unarmed")
    command.add_argument("--release", required=True)
    command.add_argument("--reason", required=True)
    command.add_argument("--evidence-ref")
    add_common_mutation_arguments(command)

    command = subparsers.add_parser("monitor-stop", help="record disabled terminal monitoring")
    command.add_argument("--release", required=True)
    command.add_argument("--reason", required=True)
    command.add_argument("--evidence-ref", required=True)
    add_common_mutation_arguments(command)

    command = subparsers.add_parser("monitor-status", help="read durable monitoring readiness")
    command.add_argument("--release", required=True)

    command = subparsers.add_parser("issue-list", help="query current completion issues")
    command.add_argument(
        "--state",
        default="not-implemented",
        choices=["not-implemented", "outstanding", "all", *sorted(ISSUE_STATES)],
    )
    command.add_argument("--release")
    command.add_argument("--task")
    command.add_argument("--limit", type=int, default=100)

    command = subparsers.add_parser("issue-history", help="read one issue's permanent story")
    command.add_argument("--id", required=True)
    command.add_argument("--limit", type=int, default=100)

    command = subparsers.add_parser("status", help="calculate weighted release and overall progress")
    command.add_argument("--release")

    command = subparsers.add_parser("release-show", help="read one bounded release work order")
    command.add_argument("--release", required=True)
    command.add_argument("--limit", type=int, default=100)

    command = subparsers.add_parser("task-show", help="read one task and its delivery context")
    command.add_argument("--task", required=True)

    command = subparsers.add_parser("events", help="read low-volume events after a sequence")
    command.add_argument("--after", type=int, default=0)
    command.add_argument("--limit", type=int, default=100)

    command = subparsers.add_parser("monitor-snapshot", help="return compact stale and blocked work")
    command.add_argument("--now")

    command = subparsers.add_parser("gantt-data", help="export renderer-neutral release schedule data")
    command.add_argument("--release", required=True)

    return parser


COMMANDS = {
    "init": command_init,
    "release-create": command_release_create,
    "release-rebaseline": command_release_rebaseline,
    "release-transition": command_release_transition,
    "requirement-create": command_requirement_create,
    "task-create": command_task_create,
    "task-update": command_task_update,
    "dependency-add": command_dependency_add,
    "issue-create": command_issue_create,
    "issue-link-task": command_issue_link_task,
    "issue-transition": command_issue_transition,
    "issue-move": command_issue_move,
    "issue-note": command_issue_note,
    "issue-import": command_issue_import,
    "monitor-configure": command_monitor_configure,
    "monitor-arm": command_monitor_arm,
    "monitor-run-start": command_monitor_run_start,
    "monitor-run-finish": command_monitor_run_finish,
    "monitor-verify-first-run": command_monitor_verify_first_run,
    "monitor-block": command_monitor_block,
    "monitor-stop": command_monitor_stop,
    "monitor-status": command_monitor_status,
    "issue-list": command_issue_list,
    "issue-history": command_issue_history,
    "status": command_status,
    "release-show": command_release_show,
    "task-show": command_task_show,
    "events": command_events,
    "monitor-snapshot": command_monitor_snapshot,
    "gantt-data": command_gantt_data,
}


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store: Store | None = None
    try:
        store = Store(args.project, args.db)
        store.initialize()
        payload = COMMANDS[args.command](store, args)
        json_output(payload)
        return 0
    except (DeliveryStateError, sqlite3.Error, OSError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, sort_keys=True), file=sys.stderr)
        return 2
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
