"""Durable, privacy-preserving delivery-efficiency recorder core."""

from __future__ import annotations

import errno
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import stat
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import RECORDER_VERSION, SCHEMA_VERSION
from .contract import (
    ContractValidationError,
    MAX_CANONICAL_EVENT_BYTES,
    SOURCE_IDENTITY_KEYS,
    canonical_json,
    validate_durable_event,
    validate_normalized_observation,
    validate_source_key,
)
from .platforms import PlatformIdentity, detect_platform, state_directory


DATABASE_NAME = "events.sqlite3"
LEDGER_NAME = "EfficiencyLedger.jsonl"
KEY_NAME = "identity.key"
STORE_SCHEMA_VERSION = "2"
PROJECT_BATCH_SIZE = 512
MAX_PROJECT_BATCHES = 16
MAX_RECOVERY_TAIL_BYTES = PROJECT_BATCH_SIZE * (MAX_CANONICAL_EVENT_BYTES + 1)
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
_IDENTITY_FIELD_MAP = {
    "lineage": "lineage_id",
    "task": "task_id",
    "project": "project_id",
    "revision": "revision_id",
    "session": "session_id",
    "turn": "turn_id",
    "agent": "agent_id",
}
_OPAQUE_KINDS = set(SOURCE_IDENTITY_KEYS) | {"span", "parent-span"}
_RUNTIME_SCOPED_IDENTITY_KINDS = {"lineage", "task", "session", "turn", "agent", "span"}
_RUNTIME_FAMILIES = {"codex", "claude"}
_DECLARATION_BINDING_PREFIX = "binding_v1"
_DECLARATION_BINDING_HEX_LENGTH = 32
_TASK_BINDING_PREFIX = "task_v1"


class RecorderError(RuntimeError):
    """Base class for bounded recorder failures."""


class StorageUnavailableError(RecorderError):
    """The private spool could not be opened or committed."""


class LedgerIntegrityError(RecorderError):
    """The cold ledger differs from the authoritative projection state."""


class DedupeConflictError(RecorderError):
    """One source key was reused for two different normalized observations."""


class RecorderClosedError(RecorderError):
    """The recorder was used after close()."""


@dataclass(frozen=True)
class RecordResult:
    event_id: str
    sequence: str
    deduplicated: bool
    projected: bool
    task_binding: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "sequence": self.sequence,
            "deduplicated": self.deduplicated,
            "projected": self.projected,
        }


class Recorder:
    """Validate, de-identify, spool, and project normalized observations.

    ``state_dir`` is always explicit at this layer.  Installers and launchers
    select it through :mod:`delivery_efficiency.platforms`; tests can safely
    use an isolated temporary directory.
    """

    def __init__(
        self,
        state_dir: Path,
        *,
        busy_timeout_ms: int = 2500,
        platform_identity: Optional[PlatformIdentity] = None,
    ) -> None:
        if not isinstance(busy_timeout_ms, int) or isinstance(busy_timeout_ms, bool):
            raise ValueError("busy_timeout_ms must be an integer")
        if busy_timeout_ms < 50 or busy_timeout_ms > 10000:
            raise ValueError("busy_timeout_ms must be between 50 and 10000")
        self._platform = platform_identity or detect_platform()
        # The normal path uses current-host validation, including WSL realpath
        # checks.  An injected identity exists only for deterministic tests.
        if platform_identity is None:
            self.state_dir = state_directory(Path(state_dir))
        else:
            from .platforms import validate_state_path

            self.state_dir = Path(validate_state_path(str(state_dir), self._platform))
        self.busy_timeout_ms = busy_timeout_ms
        self.database_path = self.state_dir / DATABASE_NAME
        self.ledger_path = self.state_dir / LEDGER_NAME
        self.key_path = self.state_dir / KEY_NAME
        self.clock_domain = "clock_" + secrets.token_hex(16)
        self._closed = False
        self._prepare_state_directory()
        self._key = self._load_or_create_key()
        self._initialize_store()

    def __enter__(self) -> "Recorder":
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def close(self) -> None:
        # Connections are deliberately per-operation so no handle survives a
        # hook call or a fork.  Closing invalidates only this object instance.
        self._closed = True

    def opaque_id(self, kind: str, raw: str) -> str:
        """Derive a stable installation-local opaque identifier in memory."""

        self._ensure_open()
        if kind not in _OPAQUE_KINDS:
            raise ContractValidationError("opaque identity kind is outside the allowlist")
        _validate_private_source_value(raw)
        return "id_" + self._hmac_hex("identity:" + kind, raw.encode("utf-8"))[:32]

    def opaque_runtime_id(self, kind: str, runtime_family: str, raw: str) -> str:
        """Derive an opaque ID inside one provider-owned runtime namespace.

        Runtime task, session, turn, lineage, agent, and span identifiers are
        not globally unique.  Including the runtime family in the keyed domain
        prevents equal raw values from making two runtimes share task state.
        Project and revision identifiers intentionally remain installation-
        scoped so the same repository can be correlated across runtimes.
        """

        self._ensure_open()
        if kind not in _RUNTIME_SCOPED_IDENTITY_KINDS:
            raise ContractValidationError("opaque identity kind is not runtime-scoped")
        _validate_runtime_family(runtime_family)
        _validate_private_source_value(raw)
        if runtime_family == "codex":
            # The original identity domains are the established Codex
            # namespace.  Preserve them so an in-place recorder upgrade does
            # not split or dedupe-conflict active Codex tasks; Claude uses a
            # distinct explicit family domain below, so equal cross-runtime
            # source values still cannot collide.
            return self.opaque_id(kind, raw)
        domain_kind = "task-turn" if kind in {"task", "turn"} else kind
        return "id_" + self._hmac_hex(
            "identity:{}:runtime:{}".format(domain_kind, runtime_family),
            raw.encode("utf-8"),
        )[:32]

    def declaration_binding(self, runtime_family: str, source_session: str) -> str:
        """Issue a signed opaque handle without serializing the raw session.

        The handle is a bearer capability suitable for runtime-owned session
        context.  It contains only a keyed opaque session digest and a keyed
        integrity tag, and remains usable by later launcher processes and
        receiver restarts that share this installation identity key.
        """

        self._ensure_open()
        session_id = self.opaque_runtime_id("session", runtime_family, source_session)
        digest = session_id[3:]
        tag = self._declaration_binding_tag(runtime_family, digest)
        return "{}_{}_{}_{}".format(
            _DECLARATION_BINDING_PREFIX,
            runtime_family,
            digest,
            tag,
        )

    def _session_id_from_declaration_binding(
        self, runtime_family: str, binding: str
    ) -> str:
        _validate_runtime_family(runtime_family)
        if not isinstance(binding, str):
            raise ContractValidationError("declaration binding must be a string")
        expected_prefix = "{}_{}_".format(_DECLARATION_BINDING_PREFIX, runtime_family)
        if not binding.startswith(expected_prefix):
            raise ContractValidationError("declaration binding has the wrong runtime family")
        remainder = binding[len(expected_prefix) :]
        parts = remainder.split("_")
        if len(parts) != 2:
            raise ContractValidationError("declaration binding has an invalid shape")
        digest, supplied_tag = parts
        if not _is_lower_hex(digest, _DECLARATION_BINDING_HEX_LENGTH) or not _is_lower_hex(
            supplied_tag, _DECLARATION_BINDING_HEX_LENGTH
        ):
            raise ContractValidationError("declaration binding has an invalid shape")
        expected_tag = self._declaration_binding_tag(runtime_family, digest)
        if not hmac.compare_digest(supplied_tag, expected_tag):
            raise ContractValidationError("declaration binding failed authentication")
        return "id_" + digest

    def _declaration_binding_tag(self, runtime_family: str, digest: str) -> str:
        return self._hmac_hex(
            "declaration-binding:v1",
            "{}\x1f{}".format(runtime_family, digest).encode("ascii"),
        )[:_DECLARATION_BINDING_HEX_LENGTH]

    def _task_binding(self, runtime_family: str, task_id: str) -> str:
        _validate_runtime_family(runtime_family)
        if not isinstance(task_id, str) or not task_id.startswith("id_") or not _is_lower_hex(
            task_id[3:], _DECLARATION_BINDING_HEX_LENGTH
        ):
            raise ContractValidationError("task binding source identity is invalid")
        digest = task_id[3:]
        tag = self._hmac_hex(
            "task-binding:v1",
            "{}\x1f{}".format(runtime_family, digest).encode("ascii"),
        )[:_DECLARATION_BINDING_HEX_LENGTH]
        return "{}_{}_{}_{}".format(
            _TASK_BINDING_PREFIX,
            runtime_family,
            digest,
            tag,
        )

    def _task_id_from_binding(self, binding: str) -> Tuple[str, str]:
        if not isinstance(binding, str):
            raise ContractValidationError("linked task binding must be a string")
        parts = binding.split("_")
        if len(parts) != 5 or parts[0:2] != ["task", "v1"]:
            raise ContractValidationError("linked task binding has an invalid shape")
        runtime_family, digest, supplied_tag = parts[2], parts[3], parts[4]
        _validate_runtime_family(runtime_family)
        if not _is_lower_hex(digest, _DECLARATION_BINDING_HEX_LENGTH) or not _is_lower_hex(
            supplied_tag, _DECLARATION_BINDING_HEX_LENGTH
        ):
            raise ContractValidationError("linked task binding has an invalid shape")
        expected_tag = self._hmac_hex(
            "task-binding:v1",
            "{}\x1f{}".format(runtime_family, digest).encode("ascii"),
        )[:_DECLARATION_BINDING_HEX_LENGTH]
        if not hmac.compare_digest(supplied_tag, expected_tag):
            raise ContractValidationError("linked task binding failed authentication")
        return runtime_family, "id_" + digest

    def record(self, observation: Mapping[str, Any], *, source_key: str) -> RecordResult:
        """Record one exact normalized observation.

        Raw source identities and the adapter-provided deduplication key are
        HMACed before SQLite is touched and are never included in durable JSON.
        """

        self._ensure_open()
        observed_monotonic = time.monotonic_ns()
        observed_at = _utc_now()
        validate_normalized_observation(observation)
        validate_source_key(source_key)
        snapshot = json.loads(canonical_json(observation))
        if snapshot["adapter"]["name"] == "agent-declaration":
            raise ContractValidationError(
                "agent declarations require the task-bound atomic batch path"
            )
        identity = self._consume_source_identity(snapshot)
        source_key_hmac = self._hmac_hex(
            "source-key:" + snapshot["adapter"]["name"],
            source_key.encode("utf-8"),
        )
        event_id = self._hmac_hex("event-id", source_key_hmac.encode("ascii"))[:32]
        return self._record_internal(
            snapshot,
            identity,
            source_key_hmac=source_key_hmac,
            event_id=event_id,
            observed_monotonic=observed_monotonic,
            observed_at=observed_at,
        )

    def record_declaration(
        self,
        observation: Mapping[str, Any],
        *,
        source_key: str,
        source_session: Optional[str] = None,
        session_binding: Optional[str] = None,
    ) -> RecordResult:
        """Bind one agent declaration through the atomic batch path."""

        return self.record_declaration_batch(
            [(observation, source_key)],
            source_session=source_session,
            session_binding=session_binding,
        )[0]

    def record_declaration_batch(
        self,
        declarations: Sequence[Tuple[Mapping[str, Any], str]],
        *,
        source_session: Optional[str] = None,
        session_binding: Optional[str] = None,
        linked_task_binding: Optional[str] = None,
        target_task_binding: Optional[str] = None,
    ) -> List[RecordResult]:
        """Bind and commit one declaration batch to exactly one task.

        Declarations supply no raw task or project identifiers.  The receiver
        resolves the latest task once while holding one SQLite write
        transaction, then inserts or replays every item before committing.
        Therefore a concurrent prompt cannot split a requirement and its
        terminal across two tasks, and any conflict rolls back the whole
        batch.  Runtime hooks may provide a core-issued opaque
        ``session_binding`` so raw source identifiers never enter persistent
        model context.  Source keys are task-scoped after resolution: exact
        same-task delivery remains replay-safe while an identical declaration
        can recur on a later task in the same runtime session.
        """

        self._ensure_open()
        values = list(declarations)
        if not 1 <= len(values) <= 128:
            raise ContractValidationError(
                "declaration batch must contain between 1 and 128 events"
            )
        if (source_session is None) == (session_binding is None):
            raise ContractValidationError(
                "record_declaration_batch requires exactly one session binding source"
            )
        supplied_binding = source_session if source_session is not None else session_binding
        assert supplied_binding is not None
        _validate_private_source_value(supplied_binding)

        if linked_task_binding is not None:
            _validate_private_source_value(linked_task_binding)
        if target_task_binding is not None:
            _validate_private_source_value(target_task_binding)
        prepared: List[
            Tuple[Dict[str, Any], str, int, str, Optional[str]]
        ] = []
        runtime_family: Optional[str] = None
        for item in values:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                raise ContractValidationError(
                    "each declaration batch item must contain an observation and source key"
                )
            observation, source_key = item
            validate_normalized_observation(observation)
            validate_source_key(source_key)
            snapshot = json.loads(canonical_json(observation))
            item_runtime = snapshot["runtime"]["family"]
            if runtime_family is None:
                runtime_family = item_runtime
            elif item_runtime != runtime_family:
                raise ContractValidationError(
                    "one declaration batch cannot cross runtime families"
                )
            raw_identity = snapshot.pop("source_identity")
            if not isinstance(raw_identity["session"], str) or not hmac.compare_digest(
                raw_identity["session"].encode("utf-8"), supplied_binding.encode("utf-8")
            ):
                raise ContractValidationError(
                    "declaration observation and binding session differ"
                )
            forbidden_identity = {
                key: value
                for key, value in raw_identity.items()
                if key not in {"session", "span", "agent"} and value is not None
            }
            if forbidden_identity:
                raise ContractValidationError(
                    "agent declarations must obtain task identity from the bound session"
                )
            raw_span = raw_identity["span"]
            raw_agent = raw_identity["agent"]
            if snapshot["event"] in {"span.start", "span.end"}:
                if raw_span is None or snapshot["payload"]["span_id"] is not None:
                    raise ContractValidationError(
                        "declaration span must be derived from its raw source identity"
                    )
                snapshot["payload"]["span_id"] = self.opaque_runtime_id(
                    "span", item_runtime, raw_span
                )
            elif raw_span is not None:
                raise ContractValidationError(
                    "declaration span source is only valid for span events"
                )
            if raw_agent is not None and snapshot["event"] not in {
                "span.start",
                "span.end",
            }:
                raise ContractValidationError(
                    "declaration agent source is only valid for span events"
                )
            if snapshot["adapter"]["name"] != "agent-declaration":
                raise ContractValidationError(
                    "record_declaration_batch requires the agent-declaration adapter"
                )
            if snapshot["measurement"]["provenance"] != "agent-declared":
                raise ContractValidationError(
                    "record_declaration_batch requires agent-declared measurement provenance"
                )
            if snapshot["payload"]["source_event"] != "agent_declaration":
                raise ContractValidationError(
                    "record_declaration_batch requires the agent_declaration source event"
                )
            unscoped_key = self._hmac_hex(
                "source-key:" + snapshot["adapter"]["name"],
                source_key.encode("utf-8"),
            )
            agent_id = (
                self.opaque_runtime_id("agent", item_runtime, raw_agent)
                if raw_agent is not None
                else None
            )
            prepared.append(
                (snapshot, unscoped_key, time.monotonic_ns(), _utc_now(), agent_id)
            )

        assert runtime_family is not None
        has_lineage_link = any(item[0]["event"] == "lineage.link" for item in prepared)
        has_correction = any(item[0]["event"] == "correction" for item in prepared)
        if has_lineage_link != (linked_task_binding is not None):
            raise ContractValidationError(
                "lineage declarations require exactly one linked task binding"
            )
        if has_correction != (target_task_binding is not None):
            raise ContractValidationError(
                "correction declarations require exactly one target task binding"
            )
        if has_lineage_link and has_correction:
            raise ContractValidationError(
                "one declaration batch cannot mix lineage and correction events"
            )
        if has_correction and any(
            item[0]["event"] != "correction" for item in prepared
        ):
            raise ContractValidationError(
                "a correction batch cannot contain ordinary declarations"
            )
        session_id = (
            self.opaque_runtime_id("session", runtime_family, source_session)
            if source_session is not None
            else self._session_id_from_declaration_binding(runtime_family, session_binding)
        )

        committed: List[Tuple[str, int, bool]] = []
        try:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                identity = self._latest_task_identity_for_session(
                    connection,
                    session_id,
                    runtime_family,
                    include_terminal=True,
                )
                if identity is None:
                    raise ContractValidationError(
                        "no task.start exists for the requested declaration session"
                    )
                if target_task_binding is not None:
                    target_runtime, target_task_id = self._task_id_from_binding(
                        target_task_binding
                    )
                    target_identity = self._task_identity_by_id(
                        connection,
                        target_task_id,
                        target_runtime,
                    )
                    if target_identity is None:
                        raise ContractValidationError(
                            "target task binding does not identify a recorded task"
                        )
                    identity = target_identity
                task_id = identity.get("task_id")
                if task_id is None:
                    raise ContractValidationError(
                        "declaration task identity is unavailable"
                    )
                task_was_terminal = self._task_has_terminal(connection, task_id)
                linked_identity = None
                if linked_task_binding is not None:
                    linked_runtime, linked_task_id = self._task_id_from_binding(
                        linked_task_binding
                    )
                    linked_identity = self._task_identity_by_id(
                        connection,
                        linked_task_id,
                        linked_runtime,
                    )
                    if linked_identity is None:
                        raise ContractValidationError(
                            "linked task binding does not identify a recorded task"
                        )
                    if linked_task_id == task_id:
                        raise ContractValidationError("a task cannot link to itself")
                task_binding = self._task_binding(runtime_family, task_id)
                for (
                    snapshot,
                    unscoped_key,
                    observed_monotonic,
                    observed_at,
                    agent_id,
                ) in prepared:
                    bound_identity = dict(identity)
                    if agent_id is not None:
                        bound_identity["agent_id"] = agent_id
                    if snapshot["event"] == "lineage.link":
                        assert linked_identity is not None
                        snapshot["payload"]["link"]["task_id"] = linked_identity[
                            "task_id"
                        ]
                        snapshot["payload"]["link"]["lineage_id"] = linked_identity[
                            "lineage_id"
                        ]
                    committed.append(
                        self._record_bound_declaration_in_transaction(
                            connection,
                            snapshot,
                            bound_identity,
                            task_id=task_id,
                            unscoped_source_key_hmac=unscoped_key,
                            observed_monotonic=observed_monotonic,
                            observed_at=observed_at,
                            task_was_terminal=task_was_terminal,
                        )
                    )
                self._validate_task_completion_requirements(connection, task_id)
                connection.commit()
            except Exception:
                if connection.in_transaction:
                    connection.rollback()
                raise
            finally:
                connection.close()
        except (ContractValidationError, DedupeConflictError):
            raise
        except (sqlite3.Error, OSError) as exc:
            raise StorageUnavailableError(
                "authoritative recorder spool is unavailable"
            ) from exc

        self.project_pending()
        return [
            RecordResult(
                event_id,
                str(sequence),
                deduplicated,
                self._is_projected(sequence),
                task_binding,
            )
            for event_id, sequence, deduplicated in committed
        ]

    def _record_bound_declaration_in_transaction(
        self,
        connection: sqlite3.Connection,
        snapshot: Dict[str, Any],
        identity: Dict[str, Optional[str]],
        *,
        task_id: str,
        unscoped_source_key_hmac: str,
        observed_monotonic: int,
        observed_at: str,
        task_was_terminal: bool,
    ) -> Tuple[str, int, bool]:
        """Insert or replay one already-validated declaration without commit."""

        if snapshot["event"] == "correction":
            self._validate_correction_target(connection, snapshot, task_id)
        source_key_hmac = self._hmac_hex(
            "source-key:agent-declaration:bound-task",
            "{}\x1f{}".format(task_id, unscoped_source_key_hmac).encode("ascii"),
        )
        event_id = self._hmac_hex("event-id", source_key_hmac.encode("ascii"))[:32]
        stable_value = dict(snapshot)
        stable_value["identity"] = identity
        stable_value["platform"] = self._platform.as_event_value()
        observation_hmac = self._hmac_hex(
            "observation", canonical_json(stable_value).encode("utf-8")
        )
        existing = connection.execute(
            "SELECT sequence, event_id, observation_hmac, event_json, event_hmac "
            "FROM events WHERE source_key_hmac = ?",
            (source_key_hmac,),
        ).fetchone()
        if existing is None:
            # Preserve exact replay of a declaration written by the
            # pre-task-scoping recorder.  A legacy row owned by another task
            # is ignored so this task receives its own scoped declaration.
            legacy = connection.execute(
                "SELECT sequence, event_id, observation_hmac, event_json, event_hmac "
                "FROM events WHERE source_key_hmac = ?",
                (unscoped_source_key_hmac,),
            ).fetchone()
            if legacy is not None:
                legacy_event = self._verify_stored_row(legacy)
                if legacy_event["identity"]["task_id"] == task_id:
                    existing = legacy
        if (
            task_was_terminal
            and existing is None
            and snapshot["event"] != "correction"
        ):
            raise ContractValidationError(
                "the requested declaration task is already terminal"
            )
        if existing is not None:
            self._verify_stored_row(existing)
            if not hmac.compare_digest(existing["observation_hmac"], observation_hmac):
                raise DedupeConflictError(
                    "source_key was reused for a different observation"
                )
            return str(existing["event_id"]), int(existing["sequence"]), True

        sequence = self._next_sequence(connection)
        event = {
            "schema_version": SCHEMA_VERSION,
            "recorder_version": RECORDER_VERSION,
            "event_id": event_id,
            "sequence": str(sequence),
            "observed_at_utc": observed_at,
            "monotonic_ns": str(observed_monotonic),
            "clock_domain": self.clock_domain,
            "runtime": snapshot["runtime"],
            "adapter": snapshot["adapter"],
            "platform": self._platform.as_event_value(),
            "identity": identity,
            "classification": snapshot["classification"],
            "measurement": snapshot["measurement"],
            "coverage": snapshot["coverage"],
            "event": snapshot["event"],
            "payload": snapshot["payload"],
        }
        validate_durable_event(event)
        self._validate_completion_state(connection, event)
        event_json = canonical_json(event)
        event_hmac = self._hmac_hex("event-json", event_json.encode("utf-8"))
        connection.execute(
            "INSERT INTO events "
            "(sequence, event_id, source_key_hmac, observation_hmac, event_name, "
            "project_id, session_id, task_id, "
            "event_json, event_hmac, exported) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (
                sequence,
                event_id,
                source_key_hmac,
                observation_hmac,
                event["event"],
                identity["project_id"],
                identity["session_id"],
                task_id,
                event_json,
                event_hmac,
            ),
        )
        self._set_metadata(connection, "next_sequence", str(sequence + 1))
        return event_id, sequence, False

    def _validate_correction_target(
        self,
        connection: sqlite3.Connection,
        snapshot: Mapping[str, Any],
        task_id: str,
    ) -> None:
        target_id = snapshot["payload"]["correction"]["event_id"]
        row = connection.execute(
            "SELECT sequence, event_id, observation_hmac, event_json, event_hmac "
            "FROM events WHERE event_id = ?",
            (target_id,),
        ).fetchone()
        if row is None:
            raise ContractValidationError("correction target does not exist")
        target = self._verify_stored_row(row)
        if target["identity"]["task_id"] != task_id:
            raise ContractValidationError("correction target belongs to another task")
        corrects_requirement = snapshot["payload"]["requirement_id"] is not None
        expected_event = "requirement.status" if corrects_requirement else "task.terminal"
        if target["event"] != expected_event:
            raise ContractValidationError("correction target has the wrong event kind")
        if corrects_requirement and target["payload"]["requirement_id"] != snapshot[
            "payload"
        ]["requirement_id"]:
            raise ContractValidationError(
                "requirement correction cannot change the requirement identifier"
            )

    def _record_internal(
        self,
        snapshot: Dict[str, Any],
        identity: Dict[str, Optional[str]],
        *,
        source_key_hmac: str,
        event_id: str,
        observed_monotonic: int,
        observed_at: str,
    ) -> RecordResult:
        """Insert a source-deidentified snapshot and then project it."""

        try:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                identity = self._bind_exact_runtime_turn(connection, snapshot, identity)
                identity = self._bind_unique_active_otel_turn(connection, snapshot, identity)
                identity, collapse_row, source_key_hmac, event_id = self._bind_claude_session_task(
                    connection,
                    snapshot,
                    identity,
                    source_key_hmac=source_key_hmac,
                    event_id=event_id,
                )
                if collapse_row is not None:
                    self._verify_stored_row(collapse_row)
                    sequence = int(collapse_row["sequence"])
                    stored_event_id = str(collapse_row["event_id"])
                    connection.commit()
                    return self._finish_record(stored_event_id, sequence, True)
                stable_value = dict(snapshot)
                stable_value["identity"] = identity
                stable_value["platform"] = self._platform.as_event_value()
                observation_hmac = self._hmac_hex(
                    "observation", canonical_json(stable_value).encode("utf-8")
                )

                if snapshot["event"] == "task.first_activity" and identity["task_id"] is not None:
                    first_activity = connection.execute(
                        "SELECT sequence, event_id, observation_hmac, event_json, event_hmac "
                        "FROM events WHERE task_id = ? AND event_name = 'task.first_activity' "
                        "ORDER BY sequence LIMIT 1",
                        (identity["task_id"],),
                    ).fetchone()
                    if first_activity is not None:
                        self._verify_stored_row(first_activity)
                        sequence = int(first_activity["sequence"])
                        stored_event_id = str(first_activity["event_id"])
                        connection.commit()
                        deduplicated = True
                        return self._finish_record(stored_event_id, sequence, deduplicated)
                elif (
                    snapshot["event"] == "task.first_activity"
                    and snapshot["adapter"]["name"] == "claude-runtime"
                    and identity["session_id"] is not None
                ):
                    # No task exists for this session yet (hooks installed or
                    # resumed mid-session).  Keep at most one honest unbound
                    # first-activity row per session instead of one per tool.
                    orphan = connection.execute(
                        "SELECT sequence, event_id, observation_hmac, event_json, event_hmac "
                        "FROM events WHERE session_id = ? AND task_id IS NULL "
                        "AND event_name = 'task.first_activity' ORDER BY sequence LIMIT 1",
                        (identity["session_id"],),
                    ).fetchone()
                    if orphan is not None:
                        self._verify_stored_row(orphan)
                        sequence = int(orphan["sequence"])
                        stored_event_id = str(orphan["event_id"])
                        connection.commit()
                        return self._finish_record(stored_event_id, sequence, True)

                existing = connection.execute(
                    "SELECT sequence, event_id, observation_hmac, event_json, event_hmac "
                    "FROM events WHERE source_key_hmac = ?",
                    (source_key_hmac,),
                ).fetchone()
                if existing is not None:
                    self._verify_stored_row(existing)
                    if not hmac.compare_digest(existing["observation_hmac"], observation_hmac):
                        raise DedupeConflictError("source_key was reused for a different observation")
                    sequence = int(existing["sequence"])
                    stored_event_id = str(existing["event_id"])
                    connection.commit()
                    deduplicated = True
                else:
                    sequence = self._next_sequence(connection)
                    event = {
                        "schema_version": SCHEMA_VERSION,
                        "recorder_version": RECORDER_VERSION,
                        "event_id": event_id,
                        "sequence": str(sequence),
                        "observed_at_utc": observed_at,
                        "monotonic_ns": str(observed_monotonic),
                        "clock_domain": self.clock_domain,
                        "runtime": snapshot["runtime"],
                        "adapter": snapshot["adapter"],
                        "platform": self._platform.as_event_value(),
                        "identity": identity,
                        "classification": snapshot["classification"],
                        "measurement": snapshot["measurement"],
                        "coverage": snapshot["coverage"],
                        "event": snapshot["event"],
                        "payload": snapshot["payload"],
                    }
                    validate_durable_event(event)
                    self._validate_completion_state(connection, event)
                    event_json = canonical_json(event)
                    event_hmac = self._hmac_hex("event-json", event_json.encode("utf-8"))
                    connection.execute(
                        "INSERT INTO events "
                        "(sequence, event_id, source_key_hmac, observation_hmac, event_name, "
                        "project_id, session_id, task_id, "
                        "event_json, event_hmac, exported) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                        (
                            sequence,
                            event_id,
                            source_key_hmac,
                            observation_hmac,
                            event["event"],
                            identity["project_id"],
                            identity["session_id"],
                            identity["task_id"],
                            event_json,
                            event_hmac,
                        ),
                    )
                    self._set_metadata(connection, "next_sequence", str(sequence + 1))
                    connection.commit()
                    stored_event_id = event_id
                    deduplicated = False
            except Exception:
                if connection.in_transaction:
                    connection.rollback()
                raise
            finally:
                connection.close()
        except (ContractValidationError, DedupeConflictError):
            raise
        except (sqlite3.Error, OSError) as exc:
            raise StorageUnavailableError("authoritative recorder spool is unavailable") from exc

        return self._finish_record(stored_event_id, sequence, deduplicated)

    def _finish_record(self, event_id: str, sequence: int, deduplicated: bool) -> RecordResult:
        self.project_pending()
        projected = self._is_projected(sequence)
        return RecordResult(event_id, str(sequence), deduplicated, projected)

    def _consume_source_identity(self, snapshot: Dict[str, Any]) -> Dict[str, Optional[str]]:
        raw_identity = snapshot.pop("source_identity")
        runtime_family = snapshot["runtime"]["family"]
        identity: Dict[str, Optional[str]] = {}
        for source_name, durable_name in _IDENTITY_FIELD_MAP.items():
            raw_value = raw_identity[source_name]
            if raw_value is None:
                identity[durable_name] = None
            elif source_name in _RUNTIME_SCOPED_IDENTITY_KINDS:
                scoped_value = raw_value
                if (
                    source_name in {"task", "turn"}
                    and runtime_family == "claude"
                    and raw_identity["session"] is not None
                ):
                    scoped_value = "{}\x1f{}".format(
                        raw_identity["session"], raw_value
                    )
                identity[durable_name] = self.opaque_runtime_id(
                    source_name, runtime_family, scoped_value
                )
            else:
                identity[durable_name] = self.opaque_id(source_name, raw_value)
        raw_span = raw_identity["span"]
        if snapshot["event"] in {"span.start", "span.end"}:
            if raw_span is None:
                raise ContractValidationError("span events require a raw span source identity")
            if snapshot["payload"]["span_id"] is not None:
                raise ContractValidationError("adapters must not precompute durable span identifiers")
            snapshot["payload"]["span_id"] = self.opaque_runtime_id(
                "span", runtime_family, raw_span
            )
        elif raw_span is not None:
            raise ContractValidationError("raw span source identity is only valid for span events")
        return identity

    def _latest_task_identity_for_session(
        self,
        connection: sqlite3.Connection,
        session_id: str,
        runtime_family: str,
        *,
        include_terminal: bool = False,
    ) -> Optional[Dict[str, Optional[str]]]:
        row = connection.execute(
            "SELECT event_json, event_hmac FROM events "
            "WHERE event_name = 'task.start' AND session_id = ? "
            "ORDER BY sequence DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        event = self._verify_stored_event(row["event_json"], row["event_hmac"])
        if event["runtime"]["family"] != runtime_family:
            return None
        task_id = event["identity"]["task_id"]
        if task_id is None:
            return None
        if not include_terminal and self._task_has_terminal(connection, task_id):
            return None
        return dict(event["identity"])

    def _task_identity_by_id(
        self,
        connection: sqlite3.Connection,
        task_id: str,
        runtime_family: str,
    ) -> Optional[Dict[str, Optional[str]]]:
        row = connection.execute(
            "SELECT event_json, event_hmac FROM events "
            "WHERE event_name = 'task.start' AND task_id = ? "
            "ORDER BY sequence LIMIT 1",
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        event = self._verify_stored_event(row["event_json"], row["event_hmac"])
        if event["runtime"]["family"] != runtime_family:
            return None
        return dict(event["identity"])

    def _task_has_terminal(
        self, connection: sqlite3.Connection, task_id: str
    ) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM events WHERE task_id = ? "
                "AND event_name = 'task.terminal' LIMIT 1",
                (task_id,),
            ).fetchone()
            is not None
        )

    def _bind_unique_active_otel_turn(
        self,
        connection: sqlite3.Connection,
        snapshot: Mapping[str, Any],
        identity: Dict[str, Optional[str]],
    ) -> Dict[str, Optional[str]]:
        # Codex OTLP has no source field equivalent to Claude's prompt.id, so
        # it binds only while exactly one task is still active.  Claude usage
        # with a valid prompt.id arrives with an exact task identity already;
        # usage without it stays honestly session-scoped instead of relying on
        # a heuristic that would lose or misattribute late final counters.
        if not (
            snapshot["adapter"]["name"] == "codex-otel"
            and snapshot["event"] == "usage.observed"
            and identity["session_id"] is not None
            and identity["task_id"] is None
        ):
            return identity
        rows = connection.execute(
            "SELECT start.event_json, start.event_hmac FROM events AS start "
            "WHERE start.event_name = 'task.start' AND start.session_id = ? "
            "AND start.task_id IS NOT NULL "
            "AND NOT EXISTS ("
            "SELECT 1 FROM events AS terminal WHERE terminal.task_id = start.task_id "
            "AND terminal.event_name IN ('runtime.turn_stopped', 'task.terminal')) "
            "ORDER BY start.sequence DESC LIMIT 2",
            (identity["session_id"],),
        ).fetchall()
        if len(rows) != 1:
            return identity
        task_start = self._verify_stored_event(rows[0]["event_json"], rows[0]["event_hmac"])
        return dict(task_start["identity"])

    def _bind_exact_runtime_turn(
        self,
        connection: sqlite3.Connection,
        snapshot: Mapping[str, Any],
        identity: Dict[str, Optional[str]],
    ) -> Dict[str, Optional[str]]:
        """Bind provider activity only after its exact runtime turn is known.

        Claude prompt_id and Codex turn_id are carried transiently as a turn
        candidate.  Task and turn use one runtime-scoped HMAC domain, so a
        matching task.start can be found without persisting the raw value.  A
        missing, changed, early, or cross-runtime candidate remains unbound.
        """

        if not (
            snapshot["event"]
            in {"task.first_activity", "span.start", "span.end", "usage.observed"}
            and identity["task_id"] is None
            and identity["turn_id"] is not None
            and identity["session_id"] is not None
        ):
            return identity
        row = connection.execute(
            "SELECT event_json, event_hmac FROM events "
            "WHERE event_name = 'task.start' AND task_id = ? LIMIT 1",
            (identity["turn_id"],),
        ).fetchone()
        if row is None:
            return identity
        start = self._verify_stored_event(row["event_json"], row["event_hmac"])
        if (
            start["runtime"]["family"] != snapshot["runtime"]["family"]
            or start["identity"]["session_id"] != identity["session_id"]
            or start["identity"]["turn_id"] != identity["turn_id"]
        ):
            return identity
        bound = dict(identity)
        bound["task_id"] = start["identity"]["task_id"]
        return bound

    def _latest_claude_task_start(
        self, connection: sqlite3.Connection, session_id: str
    ) -> Optional[Dict[str, Any]]:
        """Return the latest verified Claude task.start row for one session."""

        row = connection.execute(
            "SELECT sequence, event_id, observation_hmac, event_json, event_hmac "
            "FROM events WHERE event_name = 'task.start' AND session_id = ? "
            "ORDER BY sequence DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        event = self._verify_stored_event(row["event_json"], row["event_hmac"])
        if (
            event["runtime"]["family"] != "claude"
            or event["identity"]["turn_id"] is not None
        ):
            return None
        return {"row": row, "event": event}

    def _task_is_closed(self, connection: sqlite3.Connection, task_id: str) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM events WHERE task_id = ? "
                "AND event_name IN ('runtime.turn_stopped', 'task.terminal') LIMIT 1",
                (task_id,),
            ).fetchone()
            is not None
        )

    def _bind_claude_session_task(
        self,
        connection: sqlite3.Connection,
        snapshot: Mapping[str, Any],
        identity: Dict[str, Optional[str]],
        *,
        source_key_hmac: str,
        event_id: str,
    ) -> Tuple[Dict[str, Optional[str]], Optional[sqlite3.Row], str, str]:
        """Bind current exact prompts or legacy session-owned generations.

        Current Claude events carry prompt correlation and take the exact-task
        path below.  Only a legacy hook with no prompt/turn identifier reaches
        the generation fallback: repeated starts collapse into the open
        session task, while a prior ``runtime.turn_stopped`` or
        ``task.terminal`` opens deterministic generation N.  Later legacy hook
        events inherit that latest task; uncorrelated usage deliberately does
        not, because a late counter cannot be assigned safely by session.
        """

        if snapshot["adapter"]["name"] != "claude-runtime":
            return identity, None, source_key_hmac, event_id
        if snapshot["event"] == "task.start" and identity["task_id"] is not None:
            # Current Claude hooks and OTLP user_prompt logs share prompt_id.
            # Whichever source arrives first owns the one task.start row; the
            # other collapses atomically by the runtime-scoped exact task ID.
            exact = connection.execute(
                "SELECT sequence, event_id, observation_hmac, event_json, event_hmac "
                "FROM events WHERE event_name = 'task.start' AND task_id = ? "
                "ORDER BY sequence LIMIT 1",
                (identity["task_id"],),
            ).fetchone()
            if exact is not None:
                event = self._verify_stored_row(exact)
                if (
                    event["runtime"]["family"] != "claude"
                    or event["identity"]["session_id"] != identity["session_id"]
                ):
                    raise ContractValidationError(
                        "Claude prompt task identity crossed a runtime or session boundary"
                    )
                return identity, exact, source_key_hmac, event_id
            return identity, None, source_key_hmac, event_id
        if (
            identity["session_id"] is None
            or identity["task_id"] is not None
            or identity["turn_id"] is not None
        ):
            return identity, None, source_key_hmac, event_id
        if snapshot["event"] == "usage.observed":
            return identity, None, source_key_hmac, event_id
        latest = self._latest_claude_task_start(connection, identity["session_id"])
        if snapshot["event"] == "task.start":
            if latest is not None:
                active_task = latest["event"]["identity"]["task_id"]
                if active_task is not None and not self._task_is_closed(connection, active_task):
                    return identity, latest["row"], source_key_hmac, event_id
            generation = int(
                connection.execute(
                    "SELECT COUNT(*) FROM events WHERE event_name = 'task.start' AND session_id = ?",
                    (identity["session_id"],),
                ).fetchone()[0]
            )
            identity = dict(identity)
            identity["task_id"] = "id_" + self._hmac_hex(
                "identity:session-task",
                "{}\x1f{}".format(identity["session_id"], generation).encode("utf-8"),
            )[:32]
            salted_key = self._hmac_hex(
                "source-key:claude-session-task",
                "{}\x1f{}".format(source_key_hmac, generation).encode("ascii"),
            )
            salted_event_id = self._hmac_hex("event-id", salted_key.encode("ascii"))[:32]
            return identity, None, salted_key, salted_event_id
        if latest is not None and latest["event"]["identity"]["task_id"] is not None:
            identity = dict(identity)
            identity["task_id"] = latest["event"]["identity"]["task_id"]
        return identity, None, source_key_hmac, event_id

    def project_pending(self) -> int:
        """Project committed spool rows to deterministic UTF-8/LF JSONL."""

        self._ensure_open()
        projected = 0
        try:
            for _ in range(MAX_PROJECT_BATCHES):
                count, remaining = self._project_batch()
                projected += count
                if not remaining:
                    return projected
            raise StorageUnavailableError("projection backlog exceeds the bounded attempt")
        except LedgerIntegrityError:
            raise
        except (sqlite3.Error, OSError) as exc:
            raise StorageUnavailableError("cold ledger projection is unavailable") from exc

    def read_verified_events(self) -> List[Dict[str, Any]]:
        """Return an integrity-checked authoritative reporting snapshot.

        Reporting must not treat a parseable JSONL file as authoritative.  This
        path first reconciles crash-safe pending projection, then holds the
        SQLite writer lock while it verifies every spool HMAC and compares each
        canonical row with the exact cold-ledger bytes.  A concurrent writer
        that lands between reconciliation and the snapshot causes a bounded
        retry rather than an incomplete or mixed report.
        """

        self._ensure_open()
        for _attempt in range(3):
            self.project_pending()
            connection = None
            ledger = None
            try:
                connection = self._connect()
                connection.execute("BEGIN IMMEDIATE")
                if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise LedgerIntegrityError("authoritative spool integrity check failed")
                if connection.execute("SELECT 1 FROM events WHERE exported = 0 LIMIT 1").fetchone():
                    continue
                state = self._validate_projection_state(connection, adopt=False)
                ledger = state["ledger"]
                if state["partial_tail"] or state["adopted_sequences"]:
                    raise LedgerIntegrityError("cold ledger has unreconciled projection state")

                rows = connection.execute(
                    "SELECT sequence, event_id, event_json, event_hmac, exported "
                    "FROM events ORDER BY sequence"
                ).fetchall()
                events: List[Dict[str, Any]] = []
                ledger.seek(0)
                expected_sequence = 1
                for row in rows:
                    if int(row["sequence"]) != expected_sequence or int(row["exported"]) != 1:
                        raise LedgerIntegrityError("authoritative spool sequence is not contiguous")
                    event = dict(self._verify_stored_row(row))
                    expected_line = (canonical_json(event) + "\n").encode("utf-8")
                    if ledger.read(len(expected_line)) != expected_line:
                        raise LedgerIntegrityError("cold ledger does not match the authoritative spool")
                    events.append(event)
                    expected_sequence += 1
                if ledger.read(1):
                    raise LedgerIntegrityError("cold ledger contains unowned trailing bytes")
                try:
                    next_sequence = int(self._get_metadata(connection, "next_sequence"))
                except (TypeError, ValueError) as exc:
                    raise LedgerIntegrityError("authoritative next sequence is invalid") from exc
                if next_sequence != expected_sequence:
                    raise LedgerIntegrityError("authoritative next sequence does not match the event history")
                return events
            except RecorderError:
                raise
            except (sqlite3.Error, OSError) as exc:
                raise StorageUnavailableError("authoritative reporting snapshot is unavailable") from exc
            finally:
                if ledger is not None:
                    ledger.close()
                if connection is not None:
                    if connection.in_transaction:
                        connection.rollback()
                    connection.close()
        raise StorageUnavailableError("authoritative reporting snapshot remained busy")

    def status(self) -> Dict[str, Any]:
        """Return bounded diagnostics without source identifiers or payloads."""

        self._ensure_open()
        result: Dict[str, Any] = {
            "healthy": False,
            "schema_version": SCHEMA_VERSION,
            "recorder_version": RECORDER_VERSION,
            "platform": self._platform.as_event_value(),
            "state_dir": str(self.state_dir),
            "event_count": None,
            "pending_count": None,
            "ledger_integrity": "unknown",
            "recovery_state": "unknown",
            "gap_code": "storage-unavailable",
        }
        try:
            connection = self._connect()
            try:
                quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
                if quick_check != "ok":
                    return result
                result["event_count"] = int(connection.execute("SELECT COUNT(*) FROM events").fetchone()[0])
                result["pending_count"] = int(
                    connection.execute("SELECT COUNT(*) FROM events WHERE exported = 0").fetchone()[0]
                )
                connection.execute("BEGIN IMMEDIATE")
                try:
                    state = self._validate_projection_state(connection, adopt=False)
                    result["recovery_state"] = (
                        "partial-tail"
                        if state["partial_tail"]
                        else ("complete-tail" if state["adopted_sequences"] else "none")
                    )
                    state["ledger"].close()
                finally:
                    connection.rollback()
                result["ledger_integrity"] = "valid"
                result["gap_code"] = "none"
                result["healthy"] = True
                return result
            finally:
                connection.close()
        except LedgerIntegrityError:
            result["ledger_integrity"] = "invalid"
            result["gap_code"] = "storage-unavailable"
            return result
        except (sqlite3.Error, OSError, RecorderError):
            return result

    def latest_task(
        self,
        source_project: Optional[str] = None,
        source_session: Optional[str] = None,
        runtime_family: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Return the latest safe task-start identity by at most one raw key.

        A project or session filter is HMACed in memory.  Only already-opaque
        durable identity and low-cardinality runtime metadata are returned.
        """

        self._ensure_open()
        if source_project is not None and source_session is not None:
            raise ContractValidationError("latest_task accepts at most one source identity filter")
        if source_session is not None and runtime_family is None:
            raise ContractValidationError(
                "latest_task requires runtime_family with a session filter"
            )
        if runtime_family is not None and source_session is None:
            raise ContractValidationError(
                "latest_task runtime_family is valid only with a session filter"
            )
        project_id = None
        session_id = None
        if source_project is not None:
            project_id = self.opaque_id("project", source_project)
        if source_session is not None:
            assert runtime_family is not None
            session_id = self.opaque_runtime_id("session", runtime_family, source_session)
        try:
            connection = self._connect()
            try:
                if project_id is not None:
                    row = connection.execute(
                        "SELECT event_json, event_hmac FROM events "
                        "WHERE event_name = 'task.start' AND project_id = ? ORDER BY sequence DESC LIMIT 1",
                        (project_id,),
                    ).fetchone()
                elif session_id is not None:
                    row = connection.execute(
                        "SELECT event_json, event_hmac FROM events "
                        "WHERE event_name = 'task.start' AND session_id = ? ORDER BY sequence DESC LIMIT 1",
                        (session_id,),
                    ).fetchone()
                else:
                    row = connection.execute(
                        "SELECT event_json, event_hmac FROM events WHERE event_name = 'task.start' "
                        "ORDER BY sequence DESC LIMIT 1"
                    ).fetchone()
                if row is None:
                    return None
                event = self._verify_stored_event(row["event_json"], row["event_hmac"])
                return {
                    "event_id": event["event_id"],
                    "sequence": event["sequence"],
                    "identity": dict(event["identity"]),
                    "runtime": dict(event["runtime"]),
                    "adapter": dict(event["adapter"]),
                }
            finally:
                connection.close()
        except (sqlite3.Error, OSError) as exc:
            raise StorageUnavailableError("authoritative recorder spool is unavailable") from exc

    def _prepare_state_directory(self) -> None:
        try:
            self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            if self.state_dir.is_symlink() or not self.state_dir.is_dir():
                raise StorageUnavailableError("state directory must be a real directory")
            if os.name != "nt":
                os.chmod(str(self.state_dir), 0o700)
        except OSError as exc:
            raise StorageUnavailableError("state directory is unavailable") from exc

    def _load_or_create_key(self) -> bytes:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        key = secrets.token_bytes(32)
        try:
            descriptor = os.open(str(self.key_path), flags, 0o600)
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                raise StorageUnavailableError("installation identity key is unavailable") from exc
        else:
            try:
                _write_all(descriptor, key)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            _fsync_directory(self.state_dir)
        return self._read_key()

    def _read_key(self) -> bytes:
        if self.key_path.is_symlink():
            raise StorageUnavailableError("installation identity key must not be a symlink")
        flags = os.O_RDONLY
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(str(self.key_path), flags)
            try:
                file_stat = os.fstat(descriptor)
                if not stat.S_ISREG(file_stat.st_mode):
                    raise StorageUnavailableError("installation identity key must be a regular file")
                key = os.read(descriptor, 33)
            finally:
                os.close(descriptor)
            if len(key) != 32:
                raise StorageUnavailableError("installation identity key has an invalid size")
            if os.name != "nt":
                os.chmod(str(self.key_path), 0o600)
            return key
        except OSError as exc:
            raise StorageUnavailableError("installation identity key is unavailable") from exc

    def _initialize_store(self) -> None:
        if self.database_path.is_symlink():
            raise StorageUnavailableError("authoritative spool must not be a symlink")
        try:
            connection = sqlite3.connect(
                str(self.database_path),
                timeout=self.busy_timeout_ms / 1000.0,
                isolation_level=None,
            )
            try:
                connection.execute("PRAGMA busy_timeout = {}".format(self.busy_timeout_ms))
                journal_mode = str(connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower()
                if journal_mode != "wal":
                    raise StorageUnavailableError("authoritative spool could not enable WAL")
                connection.execute("PRAGMA synchronous=FULL")
                synchronous = int(connection.execute("PRAGMA synchronous").fetchone()[0])
                if synchronous != 2:
                    raise StorageUnavailableError("authoritative spool could not enable FULL durability")
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS metadata ("
                    "key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL) WITHOUT ROWID"
                )
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS events ("
                    "sequence INTEGER PRIMARY KEY CHECK(sequence > 0),"
                    "event_id TEXT NOT NULL UNIQUE,"
                    "source_key_hmac TEXT NOT NULL UNIQUE,"
                    "observation_hmac TEXT NOT NULL,"
                    "event_name TEXT NOT NULL,"
                    "project_id TEXT,"
                    "session_id TEXT,"
                    "task_id TEXT,"
                    "event_json TEXT NOT NULL,"
                    "event_hmac TEXT NOT NULL,"
                    "exported INTEGER NOT NULL DEFAULT 0 CHECK(exported IN (0, 1)))"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS events_latest_task "
                    "ON events(event_name, project_id, sequence DESC)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS events_latest_session "
                    "ON events(event_name, session_id, sequence DESC)"
                )
                connection.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS events_one_first_activity "
                    "ON events(task_id, event_name) "
                    "WHERE event_name = 'task.first_activity' AND task_id IS NOT NULL"
                )
                defaults = {
                    "store_schema_version": STORE_SCHEMA_VERSION,
                    "next_sequence": "1",
                    "projected_size": "0",
                    "projected_sha256": _EMPTY_SHA256,
                }
                for key, value in defaults.items():
                    connection.execute("INSERT OR IGNORE INTO metadata(key, value) VALUES (?, ?)", (key, value))
                stored_schema = self._get_metadata(connection, "store_schema_version")
                if stored_schema != STORE_SCHEMA_VERSION:
                    raise StorageUnavailableError("unsupported authoritative spool schema")
                connection.commit()
            except Exception:
                if connection.in_transaction:
                    connection.rollback()
                raise
            finally:
                connection.close()
            if os.name != "nt":
                os.chmod(str(self.database_path), 0o600)
        except RecorderError:
            raise
        except (sqlite3.Error, OSError) as exc:
            raise StorageUnavailableError("authoritative recorder spool is unavailable") from exc

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.database_path),
            timeout=self.busy_timeout_ms / 1000.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = {}".format(self.busy_timeout_ms))
        connection.execute("PRAGMA synchronous=FULL")
        mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        if mode != "wal":
            connection.close()
            raise StorageUnavailableError("authoritative spool is not in WAL mode")
        return connection

    def _next_sequence(self, connection: sqlite3.Connection) -> int:
        raw = self._get_metadata(connection, "next_sequence")
        try:
            sequence = int(raw)
        except (TypeError, ValueError) as exc:
            raise StorageUnavailableError("authoritative sequence metadata is invalid") from exc
        if sequence < 1 or sequence >= 9223372036854775807:
            raise StorageUnavailableError("authoritative sequence is outside its safe bound")
        return sequence

    def _validate_completion_state(self, connection: sqlite3.Connection, event: Mapping[str, Any]) -> None:
        if event["event"] not in {"task.terminal", "correction"} or event[
            "payload"
        ]["outcome"] != "complete":
            return
        task_id = event["identity"]["task_id"]
        if task_id is None:
            return
        self._validate_complete_requirements(
            connection,
            task_id,
            require_evidence=event["schema_version"] != "1.0",
        )

    def _validate_task_completion_requirements(
        self, connection: sqlite3.Connection, task_id: str
    ) -> None:
        """Validate the final requirement state for any recorded completion."""

        rows = connection.execute(
            "SELECT event_json, event_hmac FROM events "
            "WHERE task_id = ? AND event_name IN ('task.terminal', 'correction') "
            "ORDER BY sequence",
            (task_id,),
        )
        effective_terminal = None
        for row in rows:
            event = self._verify_stored_event(row["event_json"], row["event_hmac"])
            if event["event"] == "task.terminal" or event["payload"]["outcome"] not in {
                "unknown",
                "not-applicable",
            }:
                effective_terminal = event
        if effective_terminal is not None and effective_terminal["payload"][
            "outcome"
        ] == "complete":
            self._validate_complete_requirements(
                connection,
                task_id,
                require_evidence=effective_terminal["schema_version"] != "1.0",
            )

    def _validate_complete_requirements(
        self,
        connection: sqlite3.Connection,
        task_id: str,
        *,
        require_evidence: bool,
    ) -> None:
        statuses: Dict[str, Tuple[str, bool]] = {}
        rows = connection.execute(
            "SELECT event_json, event_hmac FROM events "
            "WHERE task_id = ? AND event_name IN ('requirement.status', 'correction') "
            "ORDER BY sequence",
            (task_id,),
        )
        for row in rows:
            prior = self._verify_stored_event(row["event_json"], row["event_hmac"])
            requirement_id = prior["payload"]["requirement_id"]
            if requirement_id is None:
                continue
            evidence = prior["payload"].get("evidence", {})
            has_evidence = bool(evidence.get("refs")) and evidence.get(
                "provenance"
            ) not in {"unknown", "not-applicable"}
            if (
                prior["event"] == "correction"
                and not evidence.get("refs")
                and requirement_id in statuses
            ):
                # An evidence-free requirement correction changes status and
                # verification without erasing prior verification evidence.
                has_evidence = statuses[requirement_id][1]
            statuses[requirement_id] = (
                prior["payload"]["requirement_status"],
                has_evidence,
            )
        if not statuses:
            raise ContractValidationError(
                "a complete terminal event requires at least one recorded requirement"
            )
        unresolved = [
            status for status, _ in statuses.values() if status not in {"satisfied", "removed"}
        ]
        if unresolved:
            raise ContractValidationError("a complete terminal event has unresolved recorded requirements")
        if require_evidence and any(not has_evidence for _, has_evidence in statuses.values()):
            raise ContractValidationError(
                "a complete terminal event requires evidence for every recorded requirement"
            )

    def _project_batch(self) -> Tuple[int, bool]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                pending_rows = connection.execute(
                    "SELECT sequence, event_id, event_json, event_hmac FROM events "
                    "WHERE exported = 0 ORDER BY sequence LIMIT ?",
                    (PROJECT_BATCH_SIZE,),
                ).fetchall()
                state = self._validate_projection_state(connection, adopt=True, pending_rows=pending_rows)
                adopted_sequences = state["adopted_sequences"]
                adopted_set = set(adopted_sequences)
                to_append = [
                    row for row in pending_rows if int(row["sequence"]) not in adopted_set
                ]
                projected_sequences = list(adopted_sequences)
                projected_size = state["projected_size"]
                hasher = state["hasher"]
                ledger = state["ledger"]
                try:
                    ledger.seek(projected_size)
                    for row in to_append:
                        line = self._validated_line(row)
                        _write_all(ledger.fileno(), line)
                        hasher.update(line)
                        projected_size += len(line)
                        projected_sequences.append(int(row["sequence"]))
                    if to_append:
                        os.fsync(ledger.fileno())
                finally:
                    ledger.close()
                for sequence in projected_sequences:
                    connection.execute("UPDATE events SET exported = 1 WHERE sequence = ?", (sequence,))
                self._set_metadata(connection, "projected_size", str(projected_size))
                self._set_metadata(connection, "projected_sha256", hasher.hexdigest())
                remaining = connection.execute("SELECT 1 FROM events WHERE exported = 0 LIMIT 1").fetchone() is not None
                connection.commit()
                return len(projected_sequences), remaining
            except Exception:
                if connection.in_transaction:
                    connection.rollback()
                raise
        finally:
            connection.close()

    def _validate_projection_state(
        self,
        connection: sqlite3.Connection,
        *,
        adopt: bool,
        pending_rows: Optional[List[sqlite3.Row]] = None,
    ) -> Dict[str, Any]:
        expected_size_raw = self._get_metadata(connection, "projected_size")
        expected_digest = self._get_metadata(connection, "projected_sha256")
        try:
            expected_size = int(expected_size_raw)
        except (TypeError, ValueError) as exc:
            raise LedgerIntegrityError("ledger size metadata is invalid") from exc
        if (
            expected_size < 0
            or len(expected_digest) != 64
            or any(char not in "0123456789abcdef" for char in expected_digest)
        ):
            raise LedgerIntegrityError("ledger projection metadata is invalid")
        ledger = self._open_ledger()
        try:
            actual_size = os.fstat(ledger.fileno()).st_size
            if actual_size < expected_size:
                raise LedgerIntegrityError("ledger history was truncated")
            tail_size = actual_size - expected_size
            if tail_size > MAX_RECOVERY_TAIL_BYTES:
                raise LedgerIntegrityError("ledger recovery tail exceeds the safe bound")
            ledger.seek(0)
            hasher = hashlib.sha256()
            remaining_prefix = expected_size
            while remaining_prefix:
                chunk = ledger.read(min(1024 * 1024, remaining_prefix))
                if not chunk:
                    raise LedgerIntegrityError("ledger history ended unexpectedly")
                hasher.update(chunk)
                remaining_prefix -= len(chunk)
            if not hmac.compare_digest(hasher.hexdigest(), expected_digest):
                raise LedgerIntegrityError("ledger history digest does not match the spool")
            tail = ledger.read(tail_size + 1)
            if len(tail) != tail_size:
                raise LedgerIntegrityError("ledger changed during integrity validation")

            if pending_rows is None:
                pending_rows = connection.execute(
                    "SELECT sequence, event_id, event_json, event_hmac FROM events "
                    "WHERE exported = 0 ORDER BY sequence LIMIT ?",
                    (PROJECT_BATCH_SIZE,),
                ).fetchall()
            position = 0
            adopted_sequences: List[int] = []
            partial_tail = False
            for row in pending_rows:
                if position == len(tail):
                    break
                line = self._validated_line(row)
                remaining_tail = tail[position:]
                if len(remaining_tail) >= len(line):
                    if not remaining_tail.startswith(line):
                        raise LedgerIntegrityError("ledger has an unexpected recovery tail")
                    position += len(line)
                    adopted_sequences.append(int(row["sequence"]))
                    continue
                if remaining_tail and line.startswith(remaining_tail):
                    partial_tail = True
                    break
                raise LedgerIntegrityError("ledger has an unexpected recovery tail")
            if position != len(tail) and not partial_tail:
                raise LedgerIntegrityError("ledger recovery tail has no authoritative spool match")
            confirmed_tail = tail[:position]
            projected_size = expected_size + len(confirmed_tail)
            if partial_tail and adopt:
                os.ftruncate(ledger.fileno(), projected_size)
                os.fsync(ledger.fileno())
            hasher.update(confirmed_tail)
            return {
                "projected_size": projected_size,
                "hasher": hasher,
                "adopted_sequences": adopted_sequences,
                "partial_tail": partial_tail,
                "ledger": ledger,
            }
        except Exception:
            ledger.close()
            raise

    def _open_ledger(self):
        if self.ledger_path.is_symlink():
            raise LedgerIntegrityError("cold ledger must not be a symlink")
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(str(self.ledger_path), flags, 0o600)
            file_stat = os.fstat(descriptor)
            if not stat.S_ISREG(file_stat.st_mode):
                os.close(descriptor)
                raise LedgerIntegrityError("cold ledger must be a regular file")
            if os.name != "nt":
                os.chmod(str(self.ledger_path), 0o600)
            return os.fdopen(descriptor, "r+b", buffering=0)
        except LedgerIntegrityError:
            raise
        except OSError as exc:
            raise StorageUnavailableError("cold ledger is unavailable") from exc

    def _validated_line(self, row: sqlite3.Row) -> bytes:
        event = self._verify_stored_event(row["event_json"], row["event_hmac"])
        if event["sequence"] != str(row["sequence"]) or event["event_id"] != row["event_id"]:
            raise LedgerIntegrityError("spool row identity does not match its event")
        return (row["event_json"] + "\n").encode("utf-8")

    def _verify_stored_row(self, row: sqlite3.Row) -> Mapping[str, Any]:
        event = self._verify_stored_event(row["event_json"], row["event_hmac"])
        if event["sequence"] != str(row["sequence"]) or event["event_id"] != row["event_id"]:
            raise LedgerIntegrityError("spool row identity does not match its event")
        return event

    def _verify_stored_event(self, event_json: str, event_hmac: str) -> Mapping[str, Any]:
        if not isinstance(event_json, str) or not isinstance(event_hmac, str):
            raise LedgerIntegrityError("spool event encoding is invalid")
        expected_hmac = self._hmac_hex("event-json", event_json.encode("utf-8"))
        if not hmac.compare_digest(expected_hmac, event_hmac):
            raise LedgerIntegrityError("spool event authentication failed")
        try:
            event = json.loads(event_json)
            validate_durable_event(event)
            if canonical_json(event) != event_json:
                raise LedgerIntegrityError("spool event is not canonical")
            return event
        except (json.JSONDecodeError, ContractValidationError) as exc:
            raise LedgerIntegrityError("spool event violates the durable contract") from exc

    def _is_projected(self, sequence: int) -> bool:
        try:
            connection = self._connect()
            try:
                row = connection.execute("SELECT exported FROM events WHERE sequence = ?", (sequence,)).fetchone()
                return row is not None and int(row["exported"]) == 1
            finally:
                connection.close()
        except sqlite3.Error as exc:
            raise StorageUnavailableError("authoritative recorder spool is unavailable") from exc

    def _get_metadata(self, connection: sqlite3.Connection, key: str) -> str:
        row = connection.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        if row is None:
            raise StorageUnavailableError("authoritative spool metadata is incomplete")
        return str(row[0])

    @staticmethod
    def _set_metadata(connection: sqlite3.Connection, key: str, value: str) -> None:
        cursor = connection.execute("UPDATE metadata SET value = ? WHERE key = ?", (value, key))
        if cursor.rowcount != 1:
            raise StorageUnavailableError("authoritative spool metadata is incomplete")

    def _hmac_hex(self, domain: str, value: bytes) -> str:
        return hmac.new(self._key, domain.encode("ascii") + b"\x00" + value, hashlib.sha256).hexdigest()

    def _ensure_open(self) -> None:
        if self._closed:
            raise RecorderClosedError("recorder is closed")


def _validate_private_source_value(value: str) -> None:
    if not isinstance(value, str):
        raise ContractValidationError("source identity must be a string")
    encoded = value.encode("utf-8")
    if not encoded or len(encoded) > 4096 or "\x00" in value:
        raise ContractValidationError("source identity is empty or exceeds its safe bound")


def _validate_runtime_family(value: str) -> None:
    if value not in _RUNTIME_FAMILIES:
        raise ContractValidationError("runtime family is outside the supported identity namespace")


def _is_lower_hex(value: str, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    written = 0
    while written < len(view):
        count = os.write(descriptor, view[written:])
        if count <= 0:
            raise OSError("short write")
        written += count


def _fsync_directory(path: Path) -> None:
    if os.name == "nt" or not hasattr(os, "O_DIRECTORY"):
        return
    descriptor = None
    try:
        descriptor = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY)
        os.fsync(descriptor)
    except OSError:
        # The key itself has already been fsynced.  Some otherwise supported
        # filesystems reject directory fsync; do not pretend it succeeded, but
        # do not make telemetry block the agent solely for that limitation.
        return
    finally:
        if descriptor is not None:
            os.close(descriptor)
