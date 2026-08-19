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
from delivery_efficiency.codex import translate_transcript_usage
from delivery_efficiency.platforms import (
    PlatformConfigurationError,
    PlatformIdentity,
    default_state_path,
    detect_platform,
    validate_state_path,
)
from delivery_efficiency.storage import DedupeConflictError, LedgerIntegrityError, Recorder
from delivery_efficiency.reporting import summarize

TARGET_A = "target_v1_" + "a" * 32
TARGET_B = "target_v1_" + "b" * 32


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
        "target": None,
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


def _exact_otel_usage_observation(
    session: str, turn: str, index: int
) -> Dict[str, Any]:
    observation = _otel_usage_observation(session, index)
    observation["source_identity"]["task"] = turn
    observation["source_identity"]["turn"] = turn
    return observation


def _local_usage_observation(session: str, turn: str, index: int) -> Dict[str, Any]:
    observation = _exact_otel_usage_observation(session, turn, index)
    observation["adapter"] = {"name": "codex-hooks", "version": ADAPTER_VERSION}
    observation["payload"]["source_event"] = "unknown"
    observation["measurement"]["tokens"].update(
        {
            "cached_input": "4",
            "output": "3",
            "reasoning_output": "2",
        }
    )
    observation["coverage"]["tokens"] = "complete"
    return observation


def test_transcript_usage_is_task_bound_bounded_and_private() -> None:
    with tempfile.TemporaryDirectory(prefix="delivery-efficiency-rollout-") as temporary:
        root = Path(temporary).resolve()
        home = root / "codex"
        sessions = home / "sessions" / "2026" / "08" / "13"
        sessions.mkdir(parents=True)
        transcript = sessions / "rollout-fixture.jsonl"
        secret = "never-copy-this-prompt-or-response"
        records = [
            {"type": "event_msg", "timestamp": "2026-08-13T00:00:00Z", "payload": {"type": "task_started", "turn_id": "turn-a"}},
            {"type": "event_msg", "timestamp": "2026-08-13T00:00:01Z", "payload": {"type": "user_message", "message": secret}},
            {"type": "response_item", "payload": {"type": "message", "content": secret}},
            *(
                {"type": "response_item", "payload": {"type": "message", "content": secret * 64}}
                for _ in range(1_500)
            ),
            {"type": "event_msg", "timestamp": "2026-08-13T00:00:02Z", "payload": {"type": "token_count", "info": {"last_token_usage": {"input_tokens": 10, "cached_input_tokens": 4, "output_tokens": 3, "reasoning_output_tokens": 2, "total_tokens": 13}}}},
            {"type": "event_msg", "timestamp": "2026-08-13T00:00:03Z", "payload": {"type": "task_complete", "turn_id": "turn-a"}},
            {"type": "event_msg", "timestamp": "2026-08-13T00:00:04Z", "payload": {"type": "task_started", "turn_id": "turn-b"}},
            {"type": "event_msg", "timestamp": "2026-08-13T00:00:05Z", "payload": {"type": "token_count", "info": {"last_token_usage": {"input_tokens": 99, "cached_input_tokens": 90, "output_tokens": 8, "reasoning_output_tokens": 7}}}},
        ]
        transcript.write_text(
            "".join(json.dumps(item, separators=(",", ":")) + "\n" for item in records),
            encoding="utf-8",
        )
        emissions = translate_transcript_usage(
            str(transcript),
            codex_home=home,
            session="session-a",
            turn="turn-a",
            surface="desktop",
            runtime_version="0.147.0",
        )
        assert len(emissions) == 1
        usage, source_key = emissions[0]
        assert usage["adapter"]["name"] == "codex-hooks"
        assert usage["source_identity"]["task"] == "turn-a"
        assert usage["measurement"]["tokens"] == {
            "input": "10",
            "cached_input": "4",
            "output": "3",
            "reasoning_output": "2",
            "tool": None,
            "other": None,
        }
        encoded = canonical_json(usage) + source_key
        assert secret not in encoded
        assert str(transcript) not in encoded

        outside = root / "outside.jsonl"
        outside.write_text(transcript.read_text(encoding="utf-8"), encoding="utf-8")
        assert translate_transcript_usage(
            str(outside),
            codex_home=home,
            session="session-a",
            turn="turn-a",
        ) == []
        linked = sessions / "rollout-linked.jsonl"
        linked.symlink_to(outside)
        assert translate_transcript_usage(
            str(linked),
            codex_home=home,
            session="session-a",
            turn="turn-a",
        ) == []


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
            "target_id",
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


def test_explicit_phase_attribution_is_balanced_and_nonoverlapping() -> None:
    with tempfile.TemporaryDirectory(prefix="delivery-efficiency-phase-") as temporary:
        state = Path(temporary).resolve()
        recorder = Recorder(state)
        session = "phase-session-private"
        start = _observation(350)
        start["source_identity"].update(
            {"session": session, "project": "/fixture/private/repository"}
        )
        recorder.record(start, source_key="phase-task-start")

        phase = _declaration_observation()
        phase["event"] = "span.start"
        phase["source_identity"].update(
            {"session": session, "span": "testing-phase-private"}
        )
        phase["classification"].update(
            {"phase": "testing", "activity_state": "model-active"}
        )
        phase["payload"].update(
            {
                "requirement_id": None,
                "requirement_status": "not-applicable",
                "verification": "not-applicable",
            }
        )
        recorder.record_declaration(
            phase, source_key="phase-start", source_session=session
        )

        overlap = copy.deepcopy(phase)
        overlap["source_identity"]["span"] = "overlap-private"
        _assert_rejected(
            lambda: recorder.record_declaration(
                overlap, source_key="phase-overlap", source_session=session
            ),
            ContractValidationError,
        )

        inside = recorder.record(
            _otel_usage_observation(session, 351), source_key="phase-usage-inside"
        )
        inside_event = next(
            event
            for event in _read_events(state)
            if event["event_id"] == inside.event_id
        )
        assert inside_event["classification"]["phase"] == "testing"
        assert inside_event["classification"]["phase_provenance"] == "agent-declared"

        phase_end = copy.deepcopy(phase)
        phase_end["event"] = "span.end"
        recorder.record_declaration(
            phase_end, source_key="phase-end", source_session=session
        )
        outside = recorder.record(
            _otel_usage_observation(session, 352), source_key="phase-usage-outside"
        )
        outside_event = next(
            event
            for event in _read_events(state)
            if event["event_id"] == outside.event_id
        )
        assert outside_event["classification"]["phase"] == "unattributed"
        assert outside_event["classification"]["phase_provenance"] == "inferred"

        unmatched = copy.deepcopy(phase_end)
        unmatched["source_identity"]["span"] = "unmatched-private"
        _assert_rejected(
            lambda: recorder.record_declaration(
                unmatched, source_key="phase-unmatched", source_session=session
            ),
            ContractValidationError,
        )
        durable = (state / "EfficiencyLedger.jsonl").read_bytes()
        assert b"/fixture/private/repository" not in durable
        assert b"testing-phase-private" not in durable
        recorder.close()


def test_realistic_final_usage_and_runtime_phase_close() -> None:
    with tempfile.TemporaryDirectory(prefix="delivery-efficiency-final-phase-") as temporary:
        state = Path(temporary).resolve()
        recorder = Recorder(state)
        session = "final-session-private"
        turn = "final-turn-private"
        start = _observation(370)
        start["source_identity"].update(
            {"session": session, "task": turn, "turn": turn, "project": "/fixture/private/standalone"}
        )
        recorder.record(start, source_key="final-task-start")

        phase = _declaration_observation()
        phase["event"] = "span.start"
        phase["source_identity"].update({"session": session, "span": "reporting-final"})
        phase["classification"].update(
            {"phase": "reporting", "activity_state": "model-active"}
        )
        phase["payload"].update(
            {"requirement_id": None, "requirement_status": "not-applicable", "verification": "not-applicable"}
        )
        recorder.record_declaration(
            phase, source_key="reporting-open", source_session=session
        )

        before = recorder.record(
            _local_usage_observation(session, turn, 371),
            source_key="local-before-final",
        )
        duplicate = _exact_otel_usage_observation(session, turn, 371)
        duplicate["measurement"]["tokens"].update(
            {"cached_input": "4", "output": "3", "reasoning_output": "2"}
        )
        duplicate["coverage"]["tokens"] = "complete"
        recorder.record(duplicate, source_key="duplicate-exporter-before-final")

        terminal = _declaration_observation()
        terminal["event"] = "task.terminal"
        terminal["source_identity"]["session"] = session
        terminal["payload"].update(
            {
                "outcome": "incomplete",
                "requirement_id": None,
                "requirement_status": "not-applicable",
                "verification": "partially-verified",
            }
        )
        terminal["coverage"]["scope"] = "partial"
        terminal["coverage"]["verification"] = "partial"
        recorder.record_declaration(
            terminal, source_key="terminal-before-final", source_session=session
        )

        after = recorder.record(
            _local_usage_observation(session, turn, 372),
            source_key="local-final-response",
        )
        active_task = summarize(
            recorder.read_verified_events(), recorder.read_private_project_labels()
        )["tasks"][0]
        assert active_task["token_coverage"] == "partial"
        stop = _observation(373, event="runtime.turn_stopped")
        stop["source_identity"].update(
            {"session": session, "task": turn, "turn": turn, "project": None}
        )
        stop["payload"]["source_event"] = "turn_stop"
        stop["classification"].update(
            {"phase": "reporting", "phase_provenance": "inferred"}
        )
        recorder.record(stop, source_key="runtime-stop-after-final")

        events = _read_events(state)
        before_event = next(event for event in events if event["event_id"] == before.event_id)
        after_event = next(event for event in events if event["event_id"] == after.event_id)
        assert before_event["classification"]["phase"] == "reporting"
        assert after_event["classification"]["phase"] == "reporting"
        runtime_closes = [
            event for event in events
            if event["event"] == "span.end"
            and event["adapter"]["name"] == "codex-hooks"
            and event["payload"]["source_event"] == "unknown"
        ]
        assert len(runtime_closes) == 1
        task = summarize(events, recorder.read_private_project_labels())["tasks"][0]
        assert task["token_source"] == "task-bound-local-runtime"
        assert task["token_coverage"] == "complete"
        assert task["tokens"]["input"] == "20"
        assert task["tokens_by_phase"]["reporting"]["tokens"]["input"] == "20"
        assert task["tokens_by_phase"]["reporting"]["usage_event_count"] == 2
        assert task["phase_interval_union_ns"]["reporting"] is not None
        assert task["repository_display_name"] == "standalone"
        recorder.close()

def test_codex_runtime_target_correlation_and_privacy() -> None:
    with tempfile.TemporaryDirectory(prefix="delivery-efficiency-target-") as temporary:
        state = Path(temporary).resolve()
        recorder = Recorder(state)

        starts = []
        for index, session, turn, target in (
            (410, "target-session-a", "target-turn-a", TARGET_A),
            (420, "target-session-b", "target-turn-b", TARGET_B),
        ):
            start = _observation(index)
            start["source_identity"].update(
                {
                    "lineage": session,
                    "task": turn,
                    "session": session,
                    "turn": turn,
                    "target": target,
                }
            )
            starts.append(recorder.record(start, source_key="target-start-{}".format(index)))

        usage_b = recorder.record(
            _exact_otel_usage_observation("target-session-b", "target-turn-b", 421),
            source_key="target-usage-b",
        )
        usage_a = recorder.record(
            _exact_otel_usage_observation("target-session-a", "target-turn-a", 411),
            source_key="target-usage-a",
        )
        events = _read_events(state)
        by_id = {event["event_id"]: event for event in events}
        start_a = by_id[starts[0].event_id]
        start_b = by_id[starts[1].event_id]
        assert by_id[usage_a.event_id]["identity"]["target_id"] == start_a["identity"]["target_id"]
        assert by_id[usage_b.event_id]["identity"]["target_id"] == start_b["identity"]["target_id"]
        assert start_a["identity"]["target_id"] != start_b["identity"]["target_id"]

        declaration_observation = _declaration_observation()
        declaration_observation["source_identity"]["session"] = "target-session-a"
        declaration = recorder.record_declaration(
            declaration_observation,
            source_key="target-declaration-a",
            source_session="target-session-a",
        )
        declaration_event = next(
            event
            for event in _read_events(state)
            if event["event_id"] == declaration.event_id
        )
        assert declaration_event["identity"]["target_id"] == start_a["identity"]["target_id"]

        forged_declaration = _declaration_observation()
        forged_declaration["source_identity"].update(
            {"session": "target-session-a", "target": TARGET_A}
        )
        _assert_rejected(
            lambda: recorder.record_declaration(
                forged_declaration,
                source_key="target-declaration-forged",
                source_session="target-session-a",
            ),
            ContractValidationError,
        )

        mismatched = recorder.record(
            _exact_otel_usage_observation("target-session-a", "target-turn-b", 430),
            source_key="target-usage-mismatch",
        )
        mismatch_event = next(
            event for event in _read_events(state) if event["event_id"] == mismatched.event_id
        )
        assert mismatch_event["identity"]["target_id"] is None

        conflicting = _observation(431, event="runtime.turn_stopped")
        conflicting["source_identity"].update(
            {
                "lineage": "target-session-a",
                "task": "target-turn-a",
                "session": "target-session-a",
                "turn": "target-turn-a",
                "target": TARGET_B,
            }
        )
        conflicting["payload"]["source_event"] = "turn_stop"
        _assert_rejected(
            lambda: recorder.record(conflicting, source_key="target-conflict"),
            ContractValidationError,
        )

        recorder.close()
        for path in state.iterdir():
            if path.is_file():
                raw = path.read_bytes()
                assert TARGET_A.encode("ascii") not in raw
                assert TARGET_B.encode("ascii") not in raw


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
        / "adapter-event-v1.2.schema.json"
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
    """Immutable v1.0 and v1.1 rows remain readable beside new v1.2 rows."""

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

        previous = copy.deepcopy(legacy)
        previous.update(
            {
                "schema_version": "1.1",
                "recorder_version": "0.2.2",
                "event_id": "6" * 32,
                "sequence": "2",
                "adapter": {"name": "codex-hooks", "version": "0.2.2"},
                "payload": copy.deepcopy(observation["payload"]),
            }
        )
        validate_durable_event(previous)
        assert recorder._current_identity(previous["identity"])["target_id"] is None
        previous_encoded = canonical_json(previous)
        connection = recorder._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO events "
                "(sequence, event_id, source_key_hmac, observation_hmac, event_name, "
                "project_id, session_id, task_id, event_json, event_hmac, exported) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                (
                    2,
                    previous["event_id"],
                    recorder._hmac_hex("source-key:previous-fixture", b"previous"),
                    recorder._hmac_hex("observation", b"previous"),
                    previous["event"],
                    opaque,
                    opaque,
                    opaque,
                    previous_encoded,
                    recorder._hmac_hex(
                        "event-json", previous_encoded.encode("utf-8")
                    ),
                ),
            )
            recorder._set_metadata(connection, "next_sequence", "3")
            connection.commit()
        finally:
            connection.close()
        recorder.project_pending()

        recorder.record(_observation(981), source_key="post-upgrade-v1.2")
        events = recorder.read_verified_events()
        assert [event["schema_version"] for event in events] == [
            "1.0",
            "1.1",
            SCHEMA_VERSION,
        ]
        assert events[0] == legacy
        assert events[1] == previous
        assert events[2]["recorder_version"] == RECORDER_VERSION
        assert (state / "EfficiencyLedger.jsonl").read_bytes().startswith(legacy_line)
        recorder.close()


def main() -> int:
    tests = [
        test_platform_matrix,
        test_contract_privacy_dedupe_and_span,
        test_concurrent_writers_and_cross_process_dedupe,
        test_declaration_binding_and_otel_correlation,
        test_transcript_usage_is_task_bound_bounded_and_private,
        test_explicit_phase_attribution_is_balanced_and_nonoverlapping,
        test_realistic_final_usage_and_runtime_phase_close,
        test_codex_runtime_target_correlation_and_privacy,
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
