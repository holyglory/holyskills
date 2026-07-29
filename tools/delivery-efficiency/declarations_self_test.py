#!/usr/bin/env python3
"""Shared declaration contract tests."""

from __future__ import annotations

import copy
import json
import multiprocessing
from pathlib import Path
import sys
import tempfile
import threading


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from delivery_efficiency.contract import ContractValidationError, validate_normalized_observation
from delivery_efficiency.claude import translate_hook
from delivery_efficiency.declarations import (
    DeclarationError,
    lineage_emission,
    phase_emission,
    requirement_correction_emission,
    requirement_emission,
    terminal_correction_emission,
    terminal_emissions,
)
from delivery_efficiency.storage import DedupeConflictError, Recorder


SESSION = "declaration-regression-session"
FIRST_PROMPT = "123e4567-e89b-42d3-a456-426614174000"
SECOND_PROMPT = "223e4567-e89b-42d3-a456-426614174001"


def _complete_metadata(requirement_id):
    return {
        "requirement_evidence": {
            requirement_id: ["test:{}".format(requirement_id)]
        },
        "acceptance_baseline_id": "baseline:{}".format(requirement_id),
        "approved_scope_change_ids": [],
        "task_type": "implementation",
        "scope_size": "small",
        "method": "direct",
    }


def _record_all(recorder, emissions, *, binding=None):
    if binding is not None:
        return recorder.record_declaration_batch(
            emissions,
            session_binding=binding,
        )
    return [
        recorder.record(observation, source_key=key)
        for observation, key in emissions
    ]


def _start_prompt(recorder, prompt_id):
    return _record_all(
        recorder,
        translate_hook(
            {
                "session_id": SESSION,
                "hook_event_name": "UserPromptSubmit",
                "prompt_id": prompt_id,
                "prompt": "private regression prompt",
            }
        ),
    )[0]


def _concurrent_terminal_worker(state_dir, binding):
    recorder = Recorder(Path(state_dir), busy_timeout_ms=10000)
    try:
        emissions = terminal_emissions(
            session=binding,
            runtime_family="claude",
            surface="cli-interactive",
            outcome="complete",
            verification="verified",
            task_kind="primary",
            cause="not-applicable",
            requirements=[("REQ-CONCURRENT", "satisfied", "verified")],
            **_complete_metadata("REQ-CONCURRENT"),
        )
        _record_all(recorder, emissions, binding=binding)
    finally:
        recorder.close()


def assert_task_scoped_declaration_dedupe() -> None:
    """A repeated declaration shape belongs to each resolved Claude task."""

    with tempfile.TemporaryDirectory(prefix="delivery-declaration-task-scope-") as raw:
        state = Path(raw).resolve()
        recorder = Recorder(state)
        binding = recorder.declaration_binding("claude", SESSION)
        terminal = terminal_emissions(
            session=binding,
            runtime_family="claude",
            surface="cli-interactive",
            outcome="complete",
            verification="verified",
            task_kind="primary",
            cause="not-applicable",
            requirements=[("REQ-SAME", "satisfied", "verified")],
            **_complete_metadata("REQ-SAME"),
        )
        phase = [
            phase_emission(
                session=binding,
                runtime_family="claude",
                surface="cli-interactive",
                boundary=boundary,
                phase="testing",
                activity="tool-active",
                span="reused-verification-span",
            )
            for boundary in ("start", "end")
        ]

        _start_prompt(recorder, FIRST_PROMPT)
        first_phase = _record_all(recorder, phase, binding=binding)
        first_phase_replay = _record_all(recorder, phase, binding=binding)
        assert all(result.deduplicated for result in first_phase_replay)
        assert [result.event_id for result in first_phase_replay] == [
            result.event_id for result in first_phase
        ]
        conflicting_observation = copy.deepcopy(phase[0][0])
        conflicting_observation["classification"]["activity_state"] = "model-active"
        try:
            recorder.record_declaration(
                conflicting_observation,
                source_key=phase[0][1],
                session_binding=binding,
            )
        except DedupeConflictError:
            pass
        else:
            raise AssertionError("same-task declaration source conflict must fail")
        first_terminal = _record_all(recorder, terminal, binding=binding)
        first_terminal_replay = _record_all(recorder, terminal, binding=binding)
        assert all(result.deduplicated for result in first_terminal_replay)
        assert [result.event_id for result in first_terminal_replay] == [
            result.event_id for result in first_terminal
        ]
        _start_prompt(recorder, SECOND_PROMPT)
        second_phase = _record_all(recorder, phase, binding=binding)
        second_terminal = _record_all(recorder, terminal, binding=binding)

        events = [
            json.loads(line)
            for line in (state / "EfficiencyLedger.jsonl").read_bytes().splitlines()
        ]
        starts = [event for event in events if event["event"] == "task.start"]
        requirements = [
            event for event in events if event["event"] == "requirement.status"
        ]
        terminals = [event for event in events if event["event"] == "task.terminal"]
        spans = [event for event in events if event["event"].startswith("span.")]
        assert len(starts) == 2
        assert len(requirements) == 2
        assert len(terminals) == 2
        assert len(spans) == 4
        task_ids = {event["identity"]["task_id"] for event in starts}
        assert len(task_ids) == 2
        assert {event["identity"]["task_id"] for event in requirements} == task_ids
        assert {event["identity"]["task_id"] for event in terminals} == task_ids
        assert {event["identity"]["task_id"] for event in spans} == task_ids
        assert not any(result.deduplicated for result in first_phase + first_terminal)
        assert not any(result.deduplicated for result in second_phase + second_terminal)
        recorder.close()


def assert_concurrent_terminal_replay_is_task_scoped() -> None:
    """Concurrent identical terminal delivery produces one event pair."""

    context = multiprocessing.get_context("spawn")
    with tempfile.TemporaryDirectory(prefix="delivery-declaration-concurrent-") as raw:
        state = Path(raw).resolve()
        recorder = Recorder(state)
        _start_prompt(recorder, FIRST_PROMPT)
        binding = recorder.declaration_binding("claude", SESSION)
        recorder.close()
        workers = [
            context.Process(
                target=_concurrent_terminal_worker,
                args=(str(state), binding),
            )
            for _ in range(8)
        ]
        for process in workers:
            process.start()
        for process in workers:
            process.join(45)
            assert process.exitcode == 0
        events = [
            json.loads(line)
            for line in (state / "EfficiencyLedger.jsonl").read_bytes().splitlines()
        ]
        assert len([event for event in events if event["event"] == "task.start"]) == 1
        assert len(
            [event for event in events if event["event"] == "requirement.status"]
        ) == 1
        assert len([event for event in events if event["event"] == "task.terminal"]) == 1

        # Exact replay is allowed after closure, but a new declaration on the
        # already-terminal task remains forbidden.
        recorder = Recorder(state)
        new_phase = phase_emission(
            session=binding,
            runtime_family="claude",
            surface="cli-interactive",
            boundary="start",
            phase="reporting",
            activity="model-active",
            span="new-after-terminal",
        )
        try:
            _record_all(recorder, [new_phase], binding=binding)
        except ContractValidationError:
            pass
        else:
            raise AssertionError("new declaration after terminal must fail")
        recorder.close()


def assert_declaration_batch_cannot_split_across_prompts() -> None:
    """A prompt racing between requirement and terminal waits for commit."""

    with tempfile.TemporaryDirectory(prefix="delivery-declaration-batch-race-") as raw:
        state = Path(raw).resolve()
        recorder = Recorder(state, busy_timeout_ms=10000)
        contender = Recorder(state, busy_timeout_ms=10000)
        first_start = _start_prompt(recorder, FIRST_PROMPT)
        binding = recorder.declaration_binding("claude", SESSION)
        emissions = terminal_emissions(
            session=binding,
            runtime_family="claude",
            surface="cli-interactive",
            outcome="complete",
            verification="verified",
            task_kind="primary",
            cause="not-applicable",
            requirements=[("REQ-ATOMIC", "satisfied", "verified")],
            **_complete_metadata("REQ-ATOMIC"),
        )

        first_batch_insert = threading.Event()
        competing_write_attempted = threading.Event()
        competing_lock_acquired = threading.Event()
        competing_prompt_finished = threading.Event()
        errors = []
        original_set_metadata = recorder._set_metadata
        paused = [False]

        def pause_after_first_insert(connection, key, value):
            original_set_metadata(connection, key, value)
            if key == "next_sequence" and not paused[0]:
                paused[0] = True
                first_batch_insert.set()
                assert competing_write_attempted.wait(5)
                # The competing writer has attempted BEGIN IMMEDIATE, but it
                # cannot acquire the lock while this batch is between its
                # requirement and terminal insertions.
                assert not competing_lock_acquired.wait(0.2)

        recorder._set_metadata = pause_after_first_insert

        def record_competing_prompt():
            connection = None
            try:
                assert first_batch_insert.wait(5)
                connection = contender._connect()
                competing_write_attempted.set()
                connection.execute("BEGIN IMMEDIATE")
                competing_lock_acquired.set()
                connection.rollback()
                connection.close()
                connection = None
                _start_prompt(contender, SECOND_PROMPT)
            except BaseException as error:
                errors.append(error)
            finally:
                if connection is not None:
                    connection.close()
                competing_prompt_finished.set()

        thread = threading.Thread(target=record_competing_prompt, daemon=True)
        thread.start()
        results = recorder.record_declaration_batch(
            emissions,
            session_binding=binding,
        )
        assert len(results) == 2 and not any(result.deduplicated for result in results)
        assert competing_prompt_finished.wait(10)
        thread.join(1)
        assert not thread.is_alive()
        if errors:
            raise errors[0]

        events = recorder.read_verified_events()
        starts = [event for event in events if event["event"] == "task.start"]
        requirement = next(
            event
            for event in events
            if event["event"] == "requirement.status"
            and event["payload"]["requirement_id"] == "REQ-ATOMIC"
        )
        terminal = next(
            event
            for event in events
            if event["event"] == "task.terminal"
            and event["payload"]["outcome"] == "complete"
        )
        assert len(starts) == 2
        first_task = starts[0]["identity"]["task_id"]
        assert first_start.event_id == starts[0]["event_id"]
        assert requirement["identity"]["task_id"] == first_task
        assert terminal["identity"]["task_id"] == first_task
        assert int(requirement["sequence"]) < int(terminal["sequence"])
        assert int(terminal["sequence"]) < int(starts[1]["sequence"])
        recorder.close()
        contender.close()


def assert_declaration_batch_rolls_back_every_item() -> None:
    """A late dedupe or completion conflict leaves no batch prefix."""

    with tempfile.TemporaryDirectory(prefix="delivery-declaration-batch-rollback-") as raw:
        state = Path(raw).resolve()
        recorder = Recorder(state)
        _start_prompt(recorder, FIRST_PROMPT)
        binding = recorder.declaration_binding("claude", SESSION)
        phase = phase_emission(
            session=binding,
            runtime_family="claude",
            surface="cli-interactive",
            boundary="start",
            phase="testing",
            activity="tool-active",
            span="rollback-conflict-span",
        )
        recorder.record_declaration_batch([phase], session_binding=binding)
        baseline = recorder.read_verified_events()

        requirement = requirement_emission(
            session=binding,
            runtime_family="claude",
            surface="cli-interactive",
            requirement_id="REQ-ROLLBACK",
            status="satisfied",
            verification="verified",
        )
        conflicting_observation = copy.deepcopy(phase[0])
        conflicting_observation["classification"]["activity_state"] = "model-active"
        try:
            recorder.record_declaration_batch(
                [requirement, (conflicting_observation, phase[1])],
                session_binding=binding,
            )
        except DedupeConflictError:
            pass
        else:
            raise AssertionError("a late declaration conflict must reject the whole batch")
        assert recorder.read_verified_events() == baseline

        complete = terminal_emissions(
            session=binding,
            runtime_family="claude",
            surface="cli-interactive",
            outcome="complete",
            verification="verified",
            task_kind="primary",
            cause="not-applicable",
            requirements=[("REQ-ROLLBACK", "satisfied", "verified")],
            **_complete_metadata("REQ-ROLLBACK"),
        )
        late_unresolved = requirement_emission(
            session=binding,
            runtime_family="claude",
            surface="cli-interactive",
            requirement_id="REQ-LATE",
            status="partial",
            verification="partially-verified",
        )
        try:
            recorder.record_declaration_batch(
                complete + [late_unresolved],
                session_binding=binding,
            )
        except ContractValidationError:
            pass
        else:
            raise AssertionError(
                "a complete terminal followed by unresolved scope must reject the whole batch"
            )
        assert recorder.read_verified_events() == baseline
        recorder.close()


def assert_later_task_lineage_and_correction_bindings() -> None:
    """Signed task handles target earlier work after a later prompt exists."""

    with tempfile.TemporaryDirectory(prefix="delivery-declaration-links-") as raw:
        state = Path(raw).resolve()
        recorder = Recorder(state)
        _start_prompt(recorder, FIRST_PROMPT)
        session_binding = recorder.declaration_binding("claude", SESSION)
        first_terminal = terminal_emissions(
            session=session_binding,
            runtime_family="claude",
            surface="cli-interactive",
            outcome="incomplete",
            verification="partially-verified",
            task_kind="primary",
            cause="external-cause",
            requirements=[("REQ-LATER", "partial", "partially-verified")],
        )
        first_results = recorder.record_declaration_batch(
            first_terminal,
            session_binding=session_binding,
        )
        first_task_binding = first_results[-1].task_binding
        assert isinstance(first_task_binding, str)
        first_terminal_id = first_results[-1].event_id

        _start_prompt(recorder, SECOND_PROMPT)
        link = lineage_emission(
            session=session_binding,
            runtime_family="claude",
            surface="cli-interactive",
            linked_task_binding=first_task_binding,
            task_kind="defect-repair",
            cause="agent-caused-mistake",
        )
        recorder.record_declaration_batch(
            [link],
            session_binding=session_binding,
            linked_task_binding=first_task_binding,
        )
        correction = terminal_correction_emission(
            session=session_binding,
            runtime_family="claude",
            surface="cli-interactive",
            target_event_id=first_terminal_id,
            outcome="blocked",
            verification="verified",
            task_kind="primary",
            cause="external-cause",
        )
        recorder.record_declaration_batch(
            [correction],
            session_binding=session_binding,
            target_task_binding=first_task_binding,
        )
        requirement_correction = requirement_correction_emission(
            session=session_binding,
            runtime_family="claude",
            surface="cli-interactive",
            target_event_id=first_results[0].event_id,
            requirement_id="REQ-LATER",
            status="satisfied",
            verification="verified",
            evidence_refs=["test:REQ-LATER-corrected"],
        )
        recorder.record_declaration_batch(
            [requirement_correction],
            session_binding=session_binding,
            target_task_binding=first_task_binding,
        )

        events = recorder.read_verified_events()
        starts = [event for event in events if event["event"] == "task.start"]
        assert len(starts) == 2
        first_task = starts[0]["identity"]["task_id"]
        second_task = starts[1]["identity"]["task_id"]
        link_event = next(event for event in events if event["event"] == "lineage.link")
        correction_events = [
            event for event in events if event["event"] == "correction"
        ]
        correction_event = next(
            event
            for event in correction_events
            if event["payload"]["outcome"] == "blocked"
        )
        requirement_correction_event = next(
            event
            for event in correction_events
            if event["payload"]["requirement_id"] == "REQ-LATER"
        )
        assert link_event["identity"]["task_id"] == second_task
        assert link_event["payload"]["link"]["task_id"] == first_task
        assert link_event["payload"]["link"]["lineage_id"] == starts[0]["identity"][
            "lineage_id"
        ]
        assert correction_event["identity"]["task_id"] == first_task
        assert correction_event["payload"]["correction"]["event_id"] == first_terminal_id
        assert requirement_correction_event["identity"]["task_id"] == first_task
        assert requirement_correction_event["payload"]["evidence"] == {
            "refs": ["test:REQ-LATER-corrected"],
            "provenance": "agent-declared",
        }
        durable = (state / "EfficiencyLedger.jsonl").read_text(encoding="utf-8")
        assert first_task_binding not in durable
        assert session_binding not in durable
        recorder.close()


def assert_declarations_cannot_bypass_or_mix_target_paths() -> None:
    """Declarations use only the task-bound API; correction batches are pure."""

    with tempfile.TemporaryDirectory(prefix="delivery-declaration-boundary-") as raw:
        state = Path(raw).resolve()
        recorder = Recorder(state)
        _start_prompt(recorder, FIRST_PROMPT)
        binding = recorder.declaration_binding("claude", SESSION)
        phase = phase_emission(
            session=binding,
            runtime_family="claude",
            surface="cli-interactive",
            boundary="start",
            phase="implementation",
            activity="tool-active",
            span="must-use-batch",
        )
        try:
            recorder.record(phase[0], source_key=phase[1])
        except ContractValidationError:
            pass
        else:
            raise AssertionError("generic recording must reject agent declarations")

        terminal = terminal_emissions(
            session=binding,
            runtime_family="claude",
            surface="cli-interactive",
            outcome="incomplete",
            verification="partially-verified",
            task_kind="primary",
            cause="external-cause",
            requirements=[("REQ-MIX", "partial", "partially-verified")],
        )
        terminal_results = recorder.record_declaration_batch(
            terminal,
            session_binding=binding,
        )
        correction = terminal_correction_emission(
            session=binding,
            runtime_family="claude",
            surface="cli-interactive",
            target_event_id=terminal_results[-1].event_id,
            outcome="blocked",
            verification="verified",
            task_kind="primary",
            cause="external-cause",
        )
        before = recorder.read_verified_events()
        try:
            recorder.record_declaration_batch(
                [correction, phase],
                session_binding=binding,
                target_task_binding=terminal_results[-1].task_binding,
            )
        except ContractValidationError:
            pass
        else:
            raise AssertionError(
                "a correction batch must not contain ordinary declarations"
            )
        assert recorder.read_verified_events() == before
        recorder.close()


def assert_evidence_free_correction_retains_completion_evidence() -> None:
    """A status correction does not silently erase earlier evidence."""

    with tempfile.TemporaryDirectory(prefix="delivery-correction-evidence-") as raw:
        state = Path(raw).resolve()
        recorder = Recorder(state)
        _start_prompt(recorder, FIRST_PROMPT)
        binding = recorder.declaration_binding("claude", SESSION)
        completed = terminal_emissions(
            session=binding,
            runtime_family="claude",
            surface="cli-interactive",
            outcome="complete",
            verification="verified",
            task_kind="primary",
            cause="not-applicable",
            requirements=[("REQ-EVIDENCE", "satisfied", "verified")],
            **_complete_metadata("REQ-EVIDENCE"),
        )
        results = recorder.record_declaration_batch(
            completed,
            session_binding=binding,
        )
        evidence_free = requirement_correction_emission(
            session=binding,
            runtime_family="claude",
            surface="cli-interactive",
            target_event_id=results[0].event_id,
            requirement_id="REQ-EVIDENCE",
            status="satisfied",
            verification="verified",
        )
        recorder.record_declaration_batch(
            [evidence_free],
            session_binding=binding,
            target_task_binding=results[-1].task_binding,
        )
        correction = recorder.read_verified_events()[-1]
        assert correction["event"] == "correction"
        assert correction["payload"]["evidence"] == {
            "refs": [],
            "provenance": "unknown",
        }
        recorder.close()


def main() -> int:
    phase, _ = phase_emission(
        session="session-1",
        runtime_family="codex",
        surface="desktop",
        boundary="start",
        phase="implementation",
        activity="model-active",
        span="phase-1",
    )
    validate_normalized_observation(phase)
    assert phase["source_identity"]["span"] == "phase-1"
    values = terminal_emissions(
        session="session-1",
        runtime_family="codex",
        surface="desktop",
        outcome="complete",
        verification="verified",
        task_kind="primary",
        cause="not-applicable",
        requirements=[("Q-1", "satisfied", "verified")],
        **_complete_metadata("Q-1"),
    )
    assert [item[0]["event"] for item in values] == ["requirement.status", "task.terminal"]
    for observation, _ in values:
        validate_normalized_observation(observation)
    try:
        terminal_emissions(
            session="session-1",
            runtime_family="codex",
            surface="desktop",
            outcome="complete",
            verification="verified",
            task_kind="primary",
            cause="not-applicable",
            requirements=[],
        )
    except DeclarationError:
        pass
    else:
        raise AssertionError("complete without requirement coverage must fail")
    assert_task_scoped_declaration_dedupe()
    assert_concurrent_terminal_replay_is_task_scoped()
    assert_declaration_batch_cannot_split_across_prompts()
    assert_declaration_batch_rolls_back_every_item()
    assert_later_task_lineage_and_correction_bindings()
    assert_declarations_cannot_bypass_or_mix_target_paths()
    assert_evidence_free_correction_retains_completion_evidence()
    print("declarations self-test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
