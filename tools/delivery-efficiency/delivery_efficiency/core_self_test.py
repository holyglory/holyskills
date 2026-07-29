#!/usr/bin/env python3
"""Deterministic self-tests for the portable recorder core."""

from __future__ import annotations

import copy
import hashlib
import json
import multiprocessing
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from delivery_efficiency import ADAPTER_VERSION, RECORDER_VERSION, SCHEMA_VERSION
from delivery_efficiency.contract import ContractValidationError, canonical_json, validate_durable_event
from delivery_efficiency.platforms import (
    PlatformConfigurationError,
    PlatformIdentity,
    default_state_path,
    detect_platform,
    validate_state_path,
)
from delivery_efficiency.storage import DedupeConflictError, LedgerIntegrityError, Recorder


def _observation(index: int = 0, *, event: str = "task.start") -> Dict[str, Any]:
    identity = {
        "lineage": "lineage-secret-{}".format(index),
        "task": "task-secret-{}".format(index),
        "project": "project-secret-{}".format(index),
        "revision": "revision-secret-{}".format(index),
        "session": "session-secret-{}".format(index),
        "turn": "turn-secret-{}".format(index),
        "agent": "agent-secret-{}".format(index),
        "span": None,
    }
    payload = {
        "source_event": "prompt_submit",
        "span_id": None,
        "parent_span_id": None,
        "duration_ns": None,
        "success": None,
        "tool_category": "not-applicable",
        "outcome": "not-applicable",
        "task_kind": "primary",
        "cause": "not-applicable",
        "requirement_id": None,
        "requirement_status": "not-applicable",
        "verification": "not-applicable",
        "gap_code": "none",
        "link": {
            "task_id": None,
            "lineage_id": None,
            "provenance": "not-applicable",
        },
        "correction": {"event_id": None, "provenance": "not-applicable"},
        "task_metadata": {
            "acceptance_baseline_id": None,
            "acceptance_baseline_provenance": "unknown",
            "approved_scope_change_ids": [],
            "scope_change_provenance": "unknown",
            "task_kind_provenance": "inferred",
            "task_type": "unknown",
            "task_type_provenance": "unknown",
            "scope_size": "unknown",
            "scope_size_provenance": "unknown",
            "method": "unknown",
            "method_provenance": "unknown",
            "classifier_version": "task-v1",
        },
        "evidence": {"refs": [], "provenance": "unknown"},
        "configuration": {
            "policy_version": None,
            "policy_provenance": "unknown",
            "model_config_version": None,
            "model_config_provenance": "unknown",
            "runtime_config_version": None,
            "runtime_config_provenance": "unknown",
            "recorder_config_version": None,
            "recorder_config_provenance": "unknown",
        },
    }
    if event in {"span.start", "span.end"}:
        identity["span"] = "span-secret-{}".format(index)
        payload["source_event"] = "pre_tool" if event == "span.start" else "post_tool"
        payload["tool_category"] = "shell"
        if event == "span.end":
            payload["duration_ns"] = "1234"
            payload["success"] = True
    return {
        "runtime": {"family": "codex", "surface": "cli-interactive", "version": "1.2.3"},
        "adapter": {"name": "codex-hooks", "version": ADAPTER_VERSION},
        "source_identity": identity,
        "classification": {
            "phase": "planning",
            "phase_provenance": "runtime-observed",
            "activity_state": "model-active",
            "activity_provenance": "runtime-observed",
            "classifier_version": "contract-v1",
        },
        "measurement": {
            "provenance": "runtime-observed",
            "counter_source": "unknown",
            "tokens": {
                "input": None,
                "cached_input": None,
                "output": None,
                "reasoning_output": None,
                "tool": None,
                "other": None,
            },
            "recorder_overhead_ns": None,
        },
        "coverage": {
            "request_receipt": "partial",
            "first_activity": "partial",
            "tokens": "unknown",
            "tools": "partial",
            "subagents": "unknown",
            "terminal_delivery": "unknown",
            "scope": "unknown",
            "verification": "unknown",
        },
        "event": event,
        "payload": payload,
    }


def _concurrent_worker(state_dir: str, index: int, same_source: bool) -> None:
    recorder = Recorder(Path(state_dir), busy_timeout_ms=10000)
    selected = 0 if same_source else index
    result = recorder.record(_observation(selected), source_key="dedupe-secret-{}".format(selected))
    if not result.projected:
        raise AssertionError("worker event was not projected")


def _first_activity_worker(state_dir: str, index: int) -> None:
    recorder = Recorder(Path(state_dir), busy_timeout_ms=10000)
    observation = _observation(900, event="task.first_activity")
    if index % 2:
        observation["adapter"] = {"name": "codex-otel", "version": ADAPTER_VERSION}
        observation["payload"]["source_event"] = "otel_api"
    result = recorder.record(observation, source_key="first-activity-source-{}".format(index))
    if not result.projected:
        raise AssertionError("first activity was not projected")


def _declaration_observation() -> Dict[str, Any]:
    observation = _observation(0, event="requirement.status")
    observation["adapter"] = {"name": "agent-declaration", "version": ADAPTER_VERSION}
    observation["source_identity"] = {key: None for key in observation["source_identity"]}
    observation["classification"]["phase_provenance"] = "agent-declared"
    observation["classification"]["activity_provenance"] = "agent-declared"
    observation["measurement"]["provenance"] = "agent-declared"
    observation["measurement"]["counter_source"] = "not-applicable"
    observation["payload"]["source_event"] = "agent_declaration"
    observation["payload"]["requirement_id"] = "REQ-1"
    observation["payload"]["requirement_status"] = "satisfied"
    observation["payload"]["verification"] = "verified"
    return observation


def _otel_usage_observation(session: str, index: int) -> Dict[str, Any]:
    observation = _observation(index, event="usage.observed")
    observation["adapter"] = {"name": "codex-otel", "version": ADAPTER_VERSION}
    observation["source_identity"] = {key: None for key in observation["source_identity"]}
    observation["source_identity"]["session"] = session
    observation["classification"]["phase"] = "unattributed"
    observation["classification"]["phase_provenance"] = "inferred"
    observation["classification"]["activity_provenance"] = "inferred"
    observation["measurement"]["counter_source"] = "provider-native"
    observation["measurement"]["tokens"]["input"] = "10"
    observation["payload"]["source_event"] = "otel_response_completed"
    return observation


def _read_events(state_dir: Path):
    raw = (state_dir / "EfficiencyLedger.jsonl").read_bytes()
    assert raw.endswith(b"\n")
    assert b"\r" not in raw
    events = []
    for line in raw.splitlines():
        event = json.loads(line.decode("utf-8"))
        validate_durable_event(event)
        assert line.decode("utf-8") == canonical_json(event)
        events.append(event)
    return events


def _assert_rejected(callable_value, exception_type=Exception) -> None:
    try:
        callable_value()
    except exception_type:
        return
    raise AssertionError("expected rejection did not occur")


def test_platform_matrix() -> None:
    windows = detect_platform(system="Windows", release="11", environ={})
    macos = detect_platform(system="Darwin", release="25", environ={})
    linux = detect_platform(system="Linux", release="6.8.0", environ={})
    wsl_release = detect_platform(system="Linux", release="6.6.87.2-microsoft-standard-WSL2", environ={})
    wsl_environment = detect_platform(system="Linux", release="6.8.0", environ={"WSL_DISTRO_NAME": "Ubuntu"})
    assert windows == PlatformIdentity("windows", "native")
    assert macos == PlatformIdentity("macos", "native")
    assert linux == PlatformIdentity("linux", "native")
    assert wsl_release == PlatformIdentity("linux", "wsl")
    assert wsl_environment == PlatformIdentity("linux", "wsl")
    assert default_state_path(windows, environ={"LOCALAPPDATA": r"C:\Users\fixture\AppData\Local"}) == (
        r"C:\Users\fixture\AppData\Local\HolySkills\DeliveryEfficiency"
    )
    assert default_state_path(macos, environ={"HOME": "/Users/fixture"}) == (
        "/Users/fixture/Library/Application Support/HolySkills/DeliveryEfficiency"
    )
    assert default_state_path(linux, environ={"HOME": "/home/fixture"}) == (
        "/home/fixture/.local/state/holyskills/delivery-efficiency"
    )
    assert default_state_path(linux, environ={"HOME": "/home/fixture", "XDG_STATE_HOME": "/state"}) == (
        "/state/holyskills/delivery-efficiency"
    )
    assert default_state_path(linux, environ={"HOME": "/home/fixture", "XDG_STATE_HOME": "relative"}) == (
        "/home/fixture/.local/state/holyskills/delivery-efficiency"
    )
    assert default_state_path(wsl_release, environ={"HOME": "/home/fixture"}) == (
        "/home/fixture/.local/state/holyskills/delivery-efficiency"
    )
    _assert_rejected(lambda: validate_state_path("/mnt/c/telemetry", wsl_release), PlatformConfigurationError)
    _assert_rejected(
        lambda: default_state_path(
            wsl_release,
            environ={"HOME": "/home/fixture", "HOLYSKILLS_DELIVERY_EFFICIENCY_STATE_DIR": "/mnt/d/state"},
        ),
        PlatformConfigurationError,
    )
    _assert_rejected(lambda: validate_state_path("relative/path", linux), PlatformConfigurationError)
    assert default_state_path(windows, environ={"LOCALAPPDATA": r"C:\State"}) != default_state_path(
        wsl_release, environ={"HOME": "/home/fixture"}
    )


def test_contract_privacy_dedupe_and_span() -> None:
    with tempfile.TemporaryDirectory(prefix="delivery-efficiency-core-") as temporary:
        state = Path(temporary).resolve()
        recorder = Recorder(state)
        observation = _observation(7)
        raw_canaries = [value for value in observation["source_identity"].values() if value is not None]
        raw_source_key = "dedupe-private-canary-7"
        first = recorder.record(observation, source_key=raw_source_key)
        second = recorder.record(observation, source_key=raw_source_key)
        assert first.event_id == second.event_id
        assert first.sequence == second.sequence == "1"
        assert first.deduplicated is False and second.deduplicated is True
        assert first.projected and second.projected

        events = _read_events(state)
        assert len(events) == 1
        event = events[0]
        assert set(event["identity"]) == {
            "lineage_id",
            "task_id",
            "project_id",
            "revision_id",
            "session_id",
            "turn_id",
            "agent_id",
        }
        assert all(value is None or value.startswith("id_") for value in event["identity"].values())
        latest = recorder.latest_task("project-secret-7")
        assert latest is not None and latest["event_id"] == first.event_id
        assert recorder.latest_task("different-project") is None
        assert recorder.opaque_id("project", "project-secret-7") == event["identity"]["project_id"]
        assert recorder.opaque_runtime_id(
            "session", "codex", "session-secret-7"
        ) == recorder.opaque_id("session", "session-secret-7")
        assert recorder.opaque_runtime_id(
            "session", "claude", "session-secret-7"
        ) != event["identity"]["session_id"]

        span_result = recorder.record(_observation(8, event="span.start"), source_key="span-dedupe-private-8")
        span_event = _read_events(state)[1]
        assert span_result.sequence == "2"
        assert span_event["payload"]["span_id"].startswith("id_")
        raw_canaries.append("span-secret-8")

        conflict = copy.deepcopy(observation)
        conflict["classification"]["phase"] = "testing"
        _assert_rejected(
            lambda: recorder.record(conflict, source_key=raw_source_key),
            DedupeConflictError,
        )
        extra = copy.deepcopy(observation)
        extra["prompt"] = "PROMPT-PRIVACY-CANARY"
        _assert_rejected(
            lambda: recorder.record(extra, source_key="never-persist-extra"),
            ContractValidationError,
        )
        huge = copy.deepcopy(observation)
        huge["source_identity"]["session"] = "S" * 4097
        _assert_rejected(lambda: recorder.record(huge, source_key="bounded"), ContractValidationError)
        _assert_rejected(lambda: recorder.record(observation, source_key="K" * 4097), ContractValidationError)
        malformed_span = _observation(9, event="span.start")
        malformed_span["source_identity"]["span"] = None
        _assert_rejected(
            lambda: recorder.record(malformed_span, source_key="malformed-span"),
            ContractValidationError,
        )
        durable_extra = copy.deepcopy(event)
        durable_extra["unknown"] = "x"
        _assert_rejected(lambda: validate_durable_event(durable_extra), ContractValidationError)

        connection = sqlite3.connect(str(state / "events.sqlite3"))
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        connection.close()
        assert mode == "wal"
        core_connection = recorder._connect()
        try:
            assert int(core_connection.execute("PRAGMA synchronous").fetchone()[0]) == 2
        finally:
            core_connection.close()
        forbidden = raw_canaries + [raw_source_key, "PROMPT-PRIVACY-CANARY", "never-persist-extra"]
        for child in state.iterdir():
            if child.is_file():
                content = child.read_bytes()
                for canary in forbidden:
                    assert canary.encode("utf-8") not in content, "private source value reached durable storage"
        status = recorder.status()
        assert status["healthy"] is True
        assert status["event_count"] == 2 and status["pending_count"] == 0


def test_concurrent_writers_and_cross_process_dedupe() -> None:
    context = multiprocessing.get_context("spawn")
    with tempfile.TemporaryDirectory(prefix="delivery-efficiency-concurrent-") as temporary:
        state = Path(temporary).resolve()
        Recorder(state).close()
        workers = [context.Process(target=_concurrent_worker, args=(str(state), index, False)) for index in range(12)]
        for process in workers:
            process.start()
        for process in workers:
            process.join(45)
            assert process.exitcode == 0
        events = _read_events(state)
        assert len(events) == 12
        assert [int(event["sequence"]) for event in events] == list(range(1, 13))
        assert len({event["event_id"] for event in events}) == 12

    with tempfile.TemporaryDirectory(prefix="delivery-efficiency-dedupe-") as temporary:
        state = Path(temporary).resolve()
        Recorder(state).close()
        workers = [context.Process(target=_concurrent_worker, args=(str(state), index, True)) for index in range(8)]
        for process in workers:
            process.start()
        for process in workers:
            process.join(45)
            assert process.exitcode == 0
        assert len(_read_events(state)) == 1

    with tempfile.TemporaryDirectory(prefix="delivery-efficiency-first-activity-") as temporary:
        state = Path(temporary).resolve()
        Recorder(state).close()
        workers = [context.Process(target=_first_activity_worker, args=(str(state), index)) for index in range(8)]
        for process in workers:
            process.start()
        for process in workers:
            process.join(45)
            assert process.exitcode == 0
        events = _read_events(state)
        assert len(events) == 1
        assert events[0]["event"] == "task.first_activity"


def test_declaration_binding_and_otel_correlation() -> None:
    with tempfile.TemporaryDirectory(prefix="delivery-efficiency-binding-") as temporary:
        state = Path(temporary).resolve()
        recorder = Recorder(state)
        first_start = _observation(100)
        first_start["source_identity"]["session"] = "session-A-private"
        first = recorder.record(first_start, source_key="start-A")
        second_start = _observation(200)
        second_start["source_identity"]["session"] = "session-B-private"
        second = recorder.record(second_start, source_key="start-B")
        assert recorder.latest_task(
            source_session="session-A-private", runtime_family="codex"
        )["event_id"] == first.event_id
        assert recorder.latest_task(
            source_session="session-B-private", runtime_family="codex"
        )["event_id"] == second.event_id
        _assert_rejected(
            lambda: recorder.latest_task(
                source_project="project-secret-100", source_session="session-A-private"
            ),
            ContractValidationError,
        )

        declaration_observation = _declaration_observation()
        declaration_observation["source_identity"]["session"] = "session-A-private"
        declaration = recorder.record_declaration(
            declaration_observation,
            source_key="declaration-A",
            source_session="session-A-private",
        )
        events = _read_events(state)
        first_event = events[0]
        declaration_event = next(event for event in events if event["event_id"] == declaration.event_id)
        assert declaration_event["identity"] == first_event["identity"]
        assert declaration_event["identity"] != events[1]["identity"]
        _assert_rejected(
            lambda: recorder.record_declaration(
                _declaration_observation(),
                source_key="declaration-missing",
                source_session="session-does-not-exist",
            ),
            ContractValidationError,
        )
        forged = _declaration_observation()
        forged["source_identity"]["task"] = "forged-cross-session-task"
        _assert_rejected(
            lambda: recorder.record_declaration(
                forged, source_key="declaration-forged", source_session="session-A-private"
            ),
            ContractValidationError,
        )
        wrong_session = _declaration_observation()
        wrong_session["source_identity"]["session"] = "session-B-private"
        _assert_rejected(
            lambda: recorder.record_declaration(
                wrong_session, source_key="declaration-wrong-session", source_session="session-A-private"
            ),
            ContractValidationError,
        )
        phase = _declaration_observation()
        phase["event"] = "span.start"
        phase["payload"]["requirement_id"] = None
        phase["payload"]["requirement_status"] = "not-applicable"
        phase["payload"]["verification"] = "not-applicable"
        phase["source_identity"]["session"] = "session-A-private"
        phase["source_identity"]["span"] = "phase-span-private"
        phase_result = recorder.record_declaration(
            phase, source_key="declaration-phase", source_session="session-A-private"
        )
        phase_event = next(event for event in _read_events(state) if event["event_id"] == phase_result.event_id)
        assert phase_event["payload"]["span_id"].startswith("id_")
        assert b"phase-span-private" not in (state / "EfficiencyLedger.jsonl").read_bytes()
        terminal = _declaration_observation()
        terminal["event"] = "task.terminal"
        terminal["source_identity"]["session"] = "session-A-private"
        terminal["payload"]["requirement_id"] = None
        terminal["payload"]["requirement_status"] = "not-applicable"
        terminal["payload"]["verification"] = "unverified"
        terminal["payload"]["outcome"] = "incomplete"
        terminal["coverage"]["scope"] = "partial"
        terminal["coverage"]["verification"] = "partial"
        terminal_result = recorder.record_declaration(
            terminal, source_key="declaration-terminal", source_session="session-A-private"
        )
        terminal_replay = recorder.record_declaration(
            terminal, source_key="declaration-terminal", source_session="session-A-private"
        )
        assert terminal_replay.deduplicated is True
        assert terminal_replay.event_id == terminal_result.event_id
        _assert_rejected(
            lambda: recorder.record_declaration(
                _declaration_observation(),
                source_key="declaration-after-terminal",
                source_session="session-A-private",
            ),
            ContractValidationError,
        )

    with tempfile.TemporaryDirectory(prefix="delivery-efficiency-otel-bind-") as temporary:
        state = Path(temporary).resolve()
        recorder = Recorder(state)
        start = _observation(300)
        start["source_identity"]["session"] = "otel-session-private"
        recorder.record(start, source_key="otel-start-1")
        usage = recorder.record(
            _otel_usage_observation("otel-session-private", 301),
            source_key="otel-usage-1",
        )
        events = _read_events(state)
        start_event = events[0]
        usage_event = next(event for event in events if event["event_id"] == usage.event_id)
        assert usage_event["identity"] == start_event["identity"]

        # Two starts without a stop are detectably ambiguous.  The recorder
        # retains the observed session but does not fabricate a task binding.
        ambiguous_start = _observation(302)
        ambiguous_start["source_identity"]["session"] = "otel-session-private"
        recorder.record(ambiguous_start, source_key="otel-start-2")
        ambiguous_usage = recorder.record(
            _otel_usage_observation("otel-session-private", 303),
            source_key="otel-usage-ambiguous",
        )
        events = _read_events(state)
        ambiguous_event = next(event for event in events if event["event_id"] == ambiguous_usage.event_id)
        assert ambiguous_event["identity"]["session_id"] is not None
        assert ambiguous_event["identity"]["task_id"] is None


def test_crash_recovery_without_duplicate() -> None:
    with tempfile.TemporaryDirectory(prefix="delivery-efficiency-recovery-") as temporary:
        state = Path(temporary).resolve()
        recorder = Recorder(state)
        recorder.record(_observation(1), source_key="recovery-source")
        ledger = state / "EfficiencyLedger.jsonl"
        original = ledger.read_bytes()
        assert original.count(b"\n") == 1

        # Simulate process death after the fsynced append but before the SQLite
        # transaction that marks it exported and advances projection metadata.
        connection = sqlite3.connect(str(state / "events.sqlite3"))
        connection.execute("UPDATE events SET exported = 0 WHERE sequence = 1")
        connection.execute("UPDATE metadata SET value = '0' WHERE key = 'projected_size'")
        connection.execute(
            "UPDATE metadata SET value = ? WHERE key = 'projected_sha256'",
            (hashlib.sha256(b"").hexdigest(),),
        )
        connection.commit()
        connection.close()

        status = recorder.status()
        assert status["healthy"] is True and status["recovery_state"] == "complete-tail"
        assert ledger.read_bytes() == original
        projected = recorder.project_pending()
        assert projected == 1
        assert ledger.read_bytes() == original
        assert len(_read_events(state)) == 1
        assert recorder.status()["healthy"] is True


def test_partial_line_crash_recovery() -> None:
    with tempfile.TemporaryDirectory(prefix="delivery-efficiency-partial-") as temporary:
        state = Path(temporary).resolve()
        recorder = Recorder(state)
        recorder.record(_observation(1), source_key="partial-source")
        ledger = state / "EfficiencyLedger.jsonl"
        full_line = ledger.read_bytes()
        assert len(full_line) > 20

        connection = sqlite3.connect(str(state / "events.sqlite3"))
        connection.execute("UPDATE events SET exported = 0 WHERE sequence = 1")
        connection.execute("UPDATE metadata SET value = '0' WHERE key = 'projected_size'")
        connection.execute(
            "UPDATE metadata SET value = ? WHERE key = 'projected_sha256'",
            (hashlib.sha256(b"").hexdigest(),),
        )
        connection.commit()
        connection.close()
        partial = full_line[: len(full_line) // 2]
        ledger.write_bytes(partial)

        status = recorder.status()
        assert status["healthy"] is True
        assert status["recovery_state"] == "partial-tail"
        assert ledger.read_bytes() == partial
        assert recorder.project_pending() == 1
        assert ledger.read_bytes() == full_line
        assert len(_read_events(state)) == 1


def test_corrupt_tail_and_history_fail_closed() -> None:
    with tempfile.TemporaryDirectory(prefix="delivery-efficiency-tail-") as temporary:
        state = Path(temporary).resolve()
        recorder = Recorder(state)
        recorder.record(_observation(1), source_key="tail-source")
        ledger = state / "EfficiencyLedger.jsonl"
        with ledger.open("ab") as stream:
            stream.write(b'{"unexpected":')
            stream.flush()
            os.fsync(stream.fileno())
        corrupted = ledger.read_bytes()
        _assert_rejected(recorder.project_pending, LedgerIntegrityError)
        assert ledger.read_bytes() == corrupted
        assert recorder.status()["healthy"] is False

    with tempfile.TemporaryDirectory(prefix="delivery-efficiency-history-") as temporary:
        state = Path(temporary).resolve()
        recorder = Recorder(state)
        recorder.record(_observation(1), source_key="history-source")
        ledger = state / "EfficiencyLedger.jsonl"
        content = bytearray(ledger.read_bytes())
        content[0] = ord("[") if content[0] != ord("[") else ord("{")
        ledger.write_bytes(bytes(content))
        mutated = ledger.read_bytes()
        _assert_rejected(recorder.project_pending, LedgerIntegrityError)
        assert ledger.read_bytes() == mutated
        assert recorder.status()["ledger_integrity"] == "invalid"


def test_verified_report_snapshot_fails_closed() -> None:
    with tempfile.TemporaryDirectory(prefix="delivery-efficiency-report-snapshot-") as temporary:
        state = Path(temporary).resolve()
        recorder = Recorder(state)
        recorder.record(_observation(1), source_key="report-source")
        verified = recorder.read_verified_events()
        assert len(verified) == 1 and verified[0]["event"] == "task.start"

        ledger = state / "EfficiencyLedger.jsonl"
        original = ledger.read_bytes()
        event = json.loads(original.decode("utf-8"))
        ledger.write_bytes((json.dumps(event, sort_keys=True) + "\n").encode("utf-8"))
        _assert_rejected(recorder.read_verified_events, LedgerIntegrityError)

        ledger.write_bytes(original)
        connection = sqlite3.connect(str(state / "events.sqlite3"))
        connection.execute("UPDATE events SET event_hmac = ? WHERE sequence = 1", ("0" * 64,))
        connection.commit()
        connection.close()
        _assert_rejected(recorder.read_verified_events, LedgerIntegrityError)


def test_schema_file_alignment() -> None:
    schema_path = (
        Path(__file__).resolve().parent.parent
        / "contract"
        / "adapter-event-v1.1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="delivery-efficiency-schema-") as temporary:
        state = Path(temporary).resolve()
        recorder = Recorder(state)
        recorder.record(_observation(1), source_key="schema-source")
        event = _read_events(state)[0]
        assert set(schema["required"]) == set(event)
        assert set(schema["properties"]) == set(event)
        assert schema["additionalProperties"] is False
    source = (Path(__file__).resolve().parent / "storage.py").read_text(encoding="utf-8")
    assert "import fcntl" not in source


def test_mixed_schema_upgrade_preserves_legacy_rows() -> None:
    """An immutable v1.0 row remains readable beside newly written v1.1."""

    with tempfile.TemporaryDirectory(prefix="delivery-efficiency-mixed-schema-") as temporary:
        state = Path(temporary).resolve()
        recorder = Recorder(state)
        observation = _observation(980)
        legacy_payload = copy.deepcopy(observation["payload"])
        for field in ("link", "correction", "task_metadata", "evidence", "configuration"):
            legacy_payload.pop(field)
        opaque = "id_" + "9" * 32
        legacy = {
            "schema_version": "1.0",
            "recorder_version": "0.1.3",
            "event_id": "8" * 32,
            "sequence": "1",
            "observed_at_utc": "2026-07-29T00:00:00.000000Z",
            "monotonic_ns": "1",
            "clock_domain": "clock_" + "7" * 32,
            "runtime": observation["runtime"],
            "adapter": {"name": "codex-hooks", "version": "0.1.0"},
            "platform": recorder._platform.as_event_value(),
            "identity": {
                "lineage_id": opaque,
                "task_id": opaque,
                "project_id": opaque,
                "revision_id": opaque,
                "session_id": opaque,
                "turn_id": opaque,
                "agent_id": opaque,
            },
            "classification": observation["classification"],
            "measurement": observation["measurement"],
            "coverage": observation["coverage"],
            "event": "task.start",
            "payload": legacy_payload,
        }
        validate_durable_event(legacy)
        encoded = canonical_json(legacy)
        connection = recorder._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO events "
                "(sequence, event_id, source_key_hmac, observation_hmac, event_name, "
                "project_id, session_id, task_id, event_json, event_hmac, exported) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                (
                    1,
                    legacy["event_id"],
                    recorder._hmac_hex("source-key:legacy-fixture", b"legacy"),
                    recorder._hmac_hex("observation", b"legacy"),
                    legacy["event"],
                    opaque,
                    opaque,
                    opaque,
                    encoded,
                    recorder._hmac_hex("event-json", encoded.encode("utf-8")),
                ),
            )
            recorder._set_metadata(connection, "next_sequence", "2")
            connection.commit()
        finally:
            connection.close()
        recorder.project_pending()
        legacy_line = (encoded + "\n").encode("utf-8")
        assert (state / "EfficiencyLedger.jsonl").read_bytes() == legacy_line

        recorder.record(_observation(981), source_key="post-upgrade-v1.1")
        events = recorder.read_verified_events()
        assert [event["schema_version"] for event in events] == ["1.0", SCHEMA_VERSION]
        assert events[0] == legacy
        assert events[1]["recorder_version"] == RECORDER_VERSION
        assert (state / "EfficiencyLedger.jsonl").read_bytes().startswith(legacy_line)
        recorder.close()


def main() -> int:
    tests = [
        test_platform_matrix,
        test_contract_privacy_dedupe_and_span,
        test_concurrent_writers_and_cross_process_dedupe,
        test_declaration_binding_and_otel_correlation,
        test_crash_recovery_without_duplicate,
        test_partial_line_crash_recovery,
        test_corrupt_tail_and_history_fail_closed,
        test_verified_report_snapshot_fails_closed,
        test_schema_file_alignment,
        test_mixed_schema_upgrade_preserves_legacy_rows,
    ]
    for test in tests:
        test()
        print("PASS {}".format(test.__name__))
    print("PASS delivery-efficiency recorder core ({} tests)".format(len(tests)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
