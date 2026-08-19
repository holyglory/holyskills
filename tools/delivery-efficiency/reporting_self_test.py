#!/usr/bin/env python3
"""Focused reporting tests without importing repository code outside this tool."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from delivery_efficiency import ADAPTER_VERSION, RECORDER_VERSION
from delivery_efficiency.contract import canonical_json
from delivery_efficiency.reporting import (
    ReportingError,
    read_ledger,
    summarize,
    summarize_repositories,
    summarize_tasks,
)


def event(event_id: str, sequence: int, kind: str, mono: int, **overrides):
    value = {
        "schema_version": "1.0",
        "recorder_version": RECORDER_VERSION,
        "event_id": event_id,
        "sequence": str(sequence),
        "observed_at_utc": "2026-07-28T00:00:{:02d}Z".format(sequence),
        "monotonic_ns": str(mono),
        "clock_domain": "clock_" + "a" * 32,
        "adapter": {"name": "codex-exec", "version": ADAPTER_VERSION},
        "platform": {"os": "linux", "environment": "native"},
        "identity": {
            "task_id": "id_" + "1" * 32,
            "lineage_id": "id_" + "2" * 32,
            "project_id": None,
            "revision_id": None,
            "session_id": None,
            "turn_id": None,
            "agent_id": None,
        },
        "runtime": {"family": "codex", "surface": "cli-exec", "version": "1"},
        "classification": {
            "phase": "implementation",
            "phase_provenance": "runtime-observed",
            "activity_state": "tool-active",
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
            "tokens": "partial",
            "tools": "partial",
            "subagents": "partial",
            "terminal_delivery": "partial",
            "scope": "unknown",
            "verification": "unknown",
        },
        "event": kind,
        "payload": {
            "source_event": "exec_process",
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
        },
    }
    for key, item in overrides.items():
        if key == "payload":
            value["payload"].update(item)
        elif key == "measurement":
            value["measurement"].update(item)
        else:
            value[key] = item
    return value


def event_v11(event_id: str, sequence: int, kind: str, mono: int, **overrides):
    value = event(event_id, sequence, kind, mono, **overrides)
    value["schema_version"] = "1.1"
    value["payload"].update(
        {
            "link": {
                "task_id": None,
                "lineage_id": None,
                "provenance": "not-applicable",
            },
            "correction": {
                "event_id": None,
                "provenance": "not-applicable",
            },
            "task_metadata": {
                "acceptance_baseline_id": None,
                "acceptance_baseline_provenance": "unknown",
                "approved_scope_change_ids": [],
                "scope_change_provenance": "unknown",
                "task_kind_provenance": "unknown",
                "task_type": "unknown",
                "task_type_provenance": "unknown",
                "scope_size": "unknown",
                "scope_size_provenance": "unknown",
                "method": "unknown",
                "method_provenance": "unknown",
                "classifier_version": "task-v1",
            },
            "evidence": {"refs": [], "provenance": "not-applicable"},
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
    )
    return value


def event_v12(event_id: str, sequence: int, kind: str, mono: int, **overrides):
    value = event_v11(event_id, sequence, kind, mono, **overrides)
    value["schema_version"] = "1.2"
    value["identity"] = dict(value["identity"])
    value["identity"]["target_id"] = "id_" + "8" * 32
    return value


def set_task_identity(
    value, *, task_id: str, lineage_id: str, agent_id=None
):
    value["identity"] = dict(value["identity"])
    value["identity"].update(
        {
            "task_id": task_id,
            "lineage_id": lineage_id,
            "agent_id": agent_id,
        }
    )
    return value


def main() -> int:
    task = [
        event("a" * 32, 1, "task.start", 100),
        event("b" * 32, 2, "task.first_activity", 120),
        event("c" * 32, 3, "span.start", 130, payload={"span_id": "id_" + "3" * 32}),
        event("d" * 32, 4, "span.end", 180, payload={"span_id": "id_" + "3" * 32}),
        event(
            "e" * 32,
            5,
            "usage.observed",
            190,
            measurement={
                "counter_source": "provider-native",
                "tokens": {
                    "input": "10",
                    "cached_input": "4",
                    "output": "3",
                    "reasoning_output": "2",
                    "tool": None,
                    "other": None,
                }
            },
        ),
        event(
            "f" * 32,
            6,
            "requirement.status",
            195,
            payload={"requirement_id": "Q-1", "requirement_status": "satisfied", "verification": "verified"},
        ),
        event(
            "0" * 32,
            7,
            "task.terminal",
            200,
            adapter={"name": "agent-declaration", "version": ADAPTER_VERSION},
            measurement={"provenance": "agent-declared"},
            payload={"outcome": "complete"},
        ),
    ]
    report = summarize(task)
    assert report["task_count"] == 1
    summary = report["tasks"][0]
    assert summary["complete"] is True
    assert summary["tokens"]["input"] == "10"
    assert summary["tokens"]["tool"] is None
    assert summary["phase_interval_union_ns"]["implementation"] == "50"
    assert summary["phase_interval_union_ns"]["planning"] is None
    assert summary["activity_interval_union_ns"]["model-active"] is None
    assert summary["runtime_native_duration_sum"]["observed_span_count"] == "0"
    assert summary["request_to_delivery_ns"] is None
    assert summary["execution_to_delivery_ns"] is None
    assert summary["observed_task_start_to_terminal_declaration_ns"] == "100"
    assert summary["observed_first_activity_to_terminal_declaration_ns"] == "80"
    assert summary["timing_endpoints"]["terminal_delivery"]["coverage"] == "partial"
    assert summary["timing_endpoints"]["terminal_declaration"] == {
        "event": "task.terminal",
        "adapter": "agent-declaration",
        "coverage_dimension": None,
        "coverage": "not-applicable",
        "measurement_provenance": "agent-declared",
        "timing_basis": "receiver-monotonic-observation",
        "clock_domain": "clock_" + "a" * 32,
    }
    unknown_counter_source = deepcopy(task)
    unknown_counter_source[4]["measurement"]["counter_source"] = "unknown"
    assert (
        summarize(unknown_counter_source)["tasks"][0]["tokens"]["input"]
        is None
    )

    delivered_task = deepcopy(task)
    delivered_task[-1]["adapter"] = {
        "name": "codex-hooks",
        "version": ADAPTER_VERSION,
    }
    delivered_task[-1]["measurement"]["provenance"] = "runtime-observed"
    delivered_task[-1]["coverage"]["terminal_delivery"] = "complete"
    delivered = summarize(delivered_task)["tasks"][0]
    # A complete, runtime-observed delivery endpoint cannot upgrade partial
    # request-receipt or first-activity coverage into measured wall time.
    assert delivered["request_to_delivery_ns"] is None
    assert delivered["execution_to_delivery_ns"] is None
    assert delivered["observed_task_start_to_terminal_declaration_ns"] is None

    complete_boundaries = deepcopy(delivered_task)
    complete_boundaries[0]["coverage"]["request_receipt"] = "complete"
    complete_boundaries[1]["coverage"]["first_activity"] = "complete"
    complete = summarize(complete_boundaries)["tasks"][0]
    assert complete["request_to_delivery_ns"] == "100"
    assert complete["execution_to_delivery_ns"] == "80"
    assert complete["timing_endpoints"]["task_start"] == {
        "event": "task.start",
        "adapter": "codex-exec",
        "coverage_dimension": "request_receipt",
        "coverage": "complete",
        "measurement_provenance": "runtime-observed",
        "timing_basis": "receiver-monotonic-observation",
        "clock_domain": "clock_" + "a" * 32,
    }
    assert complete["timing_endpoints"]["first_activity"]["coverage"] == "complete"
    assert complete["timing_endpoints"]["terminal_delivery"]["coverage"] == "complete"
    assert (
        complete["timing_endpoints"]["terminal_delivery"]["measurement_provenance"]
        == "runtime-observed"
    )
    assert complete["timing_endpoints"]["terminal_declaration"] == {
        "event": None,
        "adapter": None,
        "coverage_dimension": None,
        "coverage": "not-applicable",
        "measurement_provenance": "unknown",
        "timing_basis": "unknown",
        "clock_domain": None,
    }

    partial_receipt = deepcopy(complete_boundaries)
    partial_receipt[0]["coverage"]["request_receipt"] = "partial"
    receipt_gap = summarize(partial_receipt)["tasks"][0]
    assert receipt_gap["request_to_delivery_ns"] is None
    assert receipt_gap["execution_to_delivery_ns"] == "80"

    partial_first_activity = deepcopy(complete_boundaries)
    partial_first_activity[1]["coverage"]["first_activity"] = "partial"
    activity_gap = summarize(partial_first_activity)["tasks"][0]
    assert activity_gap["request_to_delivery_ns"] == "100"
    assert activity_gap["execution_to_delivery_ns"] is None

    non_authoritative_starts = deepcopy(complete_boundaries)
    non_authoritative_starts[0]["measurement"]["provenance"] = "agent-declared"
    non_authoritative_starts[1]["measurement"]["provenance"] = "inferred"
    non_authoritative = summarize(non_authoritative_starts)["tasks"][0]
    assert non_authoritative["request_to_delivery_ns"] is None
    assert non_authoritative["execution_to_delivery_ns"] is None

    non_authoritative_terminal = deepcopy(complete_boundaries)
    non_authoritative_terminal[-1]["measurement"]["provenance"] = "agent-declared"
    non_authoritative_delivery = summarize(non_authoritative_terminal)["tasks"][0]
    assert non_authoritative_delivery["request_to_delivery_ns"] is None
    assert non_authoritative_delivery["execution_to_delivery_ns"] is None

    cross_receiver_delivery = deepcopy(complete_boundaries)
    cross_receiver_delivery[-1]["clock_domain"] = "clock_" + "b" * 32
    cross_receiver = summarize(cross_receiver_delivery)["tasks"][0]
    assert cross_receiver["request_to_delivery_ns"] is None
    assert cross_receiver["execution_to_delivery_ns"] is None
    assert (
        cross_receiver["timing_endpoints"]["task_start"]["clock_domain"]
        != cross_receiver["timing_endpoints"]["terminal_delivery"]["clock_domain"]
    )

    cross_receiver_declaration = deepcopy(task)
    cross_receiver_declaration[-1]["clock_domain"] = "clock_" + "b" * 32
    declaration_after_restart = summarize(cross_receiver_declaration)["tasks"][0]
    assert declaration_after_restart["observed_task_start_to_terminal_declaration_ns"] is None
    assert (
        declaration_after_restart["observed_first_activity_to_terminal_declaration_ns"]
        is None
    )

    early_usage = event(
        "b" * 32,
        1,
        "usage.observed",
        10,
        measurement={
            "counter_source": "provider-native",
            "tokens": {
                "input": "7",
                "cached_input": None,
                "output": None,
                "reasoning_output": None,
                "tool": None,
                "other": None,
            }
        },
    )
    early_usage["identity"] = dict(early_usage["identity"])
    early_usage["identity"].update(
        {
            "task_id": None,
            "session_id": "id_" + "4" * 32,
            "turn_id": "id_" + "5" * 32,
        }
    )
    later_start = event("c" * 32, 2, "task.start", 20)
    later_start["identity"] = dict(later_start["identity"])
    later_start["identity"].update(
        {
            "session_id": "id_" + "4" * 32,
            "turn_id": "id_" + "5" * 32,
        }
    )
    early_report = summarize([early_usage, later_start])
    assert early_report["unlinked_event_count"] == 0
    assert early_report["tasks"][0]["tokens"]["input"] == "7"

    mismatched_usage = dict(early_usage)
    mismatched_usage["event_id"] = "d" * 32
    mismatched_usage["identity"] = dict(early_usage["identity"])
    mismatched_usage["identity"]["turn_id"] = "id_" + "6" * 32
    mismatch_report = summarize([mismatched_usage, later_start])
    assert mismatch_report["unlinked_event_count"] == 1
    assert mismatch_report["tasks"][0]["tokens"]["input"] is None

    cross_domain = [
        event("1" * 32, 1, "span.start", 10, payload={"span_id": "id_" + "4" * 32}),
        event(
            "2" * 32,
            2,
            "span.end",
            20,
            clock_domain="clock_" + "b" * 32,
            payload={"span_id": "id_" + "4" * 32},
        ),
    ]
    cross_domain_summary = summarize(cross_domain)["tasks"][0]
    assert cross_domain_summary["phase_interval_union_ns"]["implementation"] is None
    assert cross_domain_summary["activity_interval_union_ns"]["tool-active"] is None

    two_complete_domains = [
        event("5" * 32, 1, "span.start", 10, payload={"span_id": "id_" + "6" * 32}),
        event("6" * 32, 2, "span.end", 20, payload={"span_id": "id_" + "6" * 32}),
        event(
            "7" * 32,
            3,
            "span.start",
            40,
            clock_domain="clock_" + "b" * 32,
            payload={"span_id": "id_" + "7" * 32},
        ),
        event(
            "8" * 32,
            4,
            "span.end",
            60,
            clock_domain="clock_" + "b" * 32,
            payload={"span_id": "id_" + "7" * 32},
        ),
    ]
    domain_total = summarize(two_complete_domains)["tasks"][0]
    assert domain_total["phase_interval_union_ns"]["implementation"] is None
    assert domain_total["activity_interval_union_ns"]["tool-active"] is None

    testing_class = dict(task[2]["classification"])
    testing_class["phase"] = "testing"
    independent_dimensions = [
        event("9" * 32, 1, "span.start", 70, payload={"span_id": "id_" + "8" * 32}),
        event(
            "a" * 32,
            2,
            "span.end",
            90,
            classification=testing_class,
            payload={"span_id": "id_" + "8" * 32},
        ),
    ]
    independent = summarize(independent_dimensions)["tasks"][0]
    assert independent["phase_interval_union_ns"]["implementation"] is None
    assert independent["phase_interval_union_ns"]["testing"] is None
    assert independent["activity_interval_union_ns"]["tool-active"] == "20"

    authoritative_zero = [
        event("3" * 32, 1, "span.start", 30, payload={"span_id": "id_" + "5" * 32}),
        event("4" * 32, 2, "span.end", 30, payload={"span_id": "id_" + "5" * 32}),
    ]
    zero_summary = summarize(authoritative_zero)["tasks"][0]
    assert zero_summary["phase_interval_union_ns"]["implementation"] == "0"

    native_end = event(
        "e" * 32,
        1,
        "span.end",
        30,
        runtime={"family": "claude", "surface": "cli-interactive", "version": "2.1.212"},
        adapter={"name": "claude-runtime", "version": ADAPTER_VERSION},
        payload={
            "source_event": "post_tool",
            "span_id": "id_" + "9" * 32,
            "duration_ns": "125",
            "success": True,
            "tool_category": "shell",
        },
    )
    native_end["classification"] = dict(native_end["classification"])
    native_end["classification"].update(
        {
            "phase": "unattributed",
            "phase_provenance": "unknown",
            "activity_state": "tool-active",
            "activity_provenance": "runtime-observed",
        }
    )
    native_end["identity"] = dict(native_end["identity"])
    native_end["identity"].update(
        {
            "session_id": "id_" + "4" * 32,
            "turn_id": "id_" + "5" * 32,
        }
    )
    native_summary = summarize([native_end])["tasks"][0]
    # A native duration does not repair a missing recorder-clock start.
    assert native_summary["phase_interval_union_ns"]["unattributed"] is None
    assert native_summary["activity_interval_union_ns"]["tool-active"] is None
    native_duration = native_summary["runtime_native_duration_sum"]
    assert native_duration["by_phase"]["unattributed"] == {
        "sum_ns": "125",
        "included_span_count": "1",
        "conflicting_span_count": "0",
        "measurement_provenance": ["runtime-observed"],
        "attribution_provenance": ["unknown"],
    }
    assert native_duration["by_activity"]["tool-active"] == {
        "sum_ns": "125",
        "included_span_count": "1",
        "conflicting_span_count": "0",
        "measurement_provenance": ["runtime-observed"],
        "attribution_provenance": ["runtime-observed"],
    }

    # Hook and OTLP can race while describing one runtime span.  Equal native
    # evidence is counted once regardless of arrival order.
    duplicate_native_end = event(
        "f" * 32,
        2,
        "span.end",
        31,
        runtime=dict(native_end["runtime"]),
        adapter={"name": "claude-runtime", "version": ADAPTER_VERSION},
        payload={
            "source_event": "otel_tool",
            "span_id": "id_" + "9" * 32,
            "duration_ns": "125",
            "success": True,
            "tool_category": "shell",
        },
        classification=dict(native_end["classification"]),
    )
    duplicate_native_end["identity"] = dict(native_end["identity"])
    duplicate_native_end["identity"]["task_id"] = None
    correlated_start = event(
        "6" * 32,
        0,
        "task.start",
        29,
        runtime=dict(native_end["runtime"]),
        adapter={"name": "claude-runtime", "version": ADAPTER_VERSION},
        payload={"source_event": "prompt_submit"},
    )
    correlated_start["identity"] = dict(native_end["identity"])
    forward = summarize([correlated_start, native_end, duplicate_native_end])["tasks"][0][
        "runtime_native_duration_sum"
    ]
    reverse = summarize([duplicate_native_end, native_end, correlated_start])["tasks"][0][
        "runtime_native_duration_sum"
    ]
    assert forward == reverse
    assert forward["by_activity"]["tool-active"]["sum_ns"] == "125"
    assert forward["observed_span_count"] == "1"
    assert forward["duplicate_observation_count"] == "1"
    assert forward["conflicting_span_count"] == "0"

    partial_payload_evidence = deepcopy(duplicate_native_end)
    partial_payload_evidence["event_id"] = "5" * 32
    partial_payload_evidence["payload"]["success"] = None
    partial_payload_evidence["payload"]["tool_category"] = "unknown"
    compatible_partial = summarize(
        [correlated_start, native_end, partial_payload_evidence]
    )["tasks"][0]["runtime_native_duration_sum"]
    assert compatible_partial["by_activity"]["tool-active"]["sum_ns"] == "125"
    assert compatible_partial["duplicate_observation_count"] == "1"
    assert compatible_partial["conflicting_span_count"] == "0"

    contradictory_success = deepcopy(duplicate_native_end)
    contradictory_success["event_id"] = "8" * 32
    contradictory_success["payload"]["success"] = False
    success_conflict = summarize(
        [correlated_start, native_end, contradictory_success]
    )["tasks"][0]["runtime_native_duration_sum"]
    assert success_conflict["by_phase"]["unattributed"]["sum_ns"] is None
    assert success_conflict["by_activity"]["tool-active"]["sum_ns"] is None
    assert success_conflict["conflicting_span_count"] == "1"

    contradictory_category = deepcopy(duplicate_native_end)
    contradictory_category["event_id"] = "9" * 32
    contradictory_category["payload"]["tool_category"] = "web"
    category_conflict = summarize(
        [correlated_start, native_end, contradictory_category]
    )["tasks"][0]["runtime_native_duration_sum"]
    assert category_conflict["by_phase"]["unattributed"]["sum_ns"] is None
    assert category_conflict["by_activity"]["tool-active"]["sum_ns"] is None
    assert category_conflict["conflicting_span_count"] == "1"

    conflicting_native_end = event(
        "7" * 32,
        3,
        "span.end",
        32,
        runtime=dict(native_end["runtime"]),
        adapter={"name": "claude-runtime", "version": ADAPTER_VERSION},
        payload={
            "source_event": "otel_tool",
            "span_id": "id_" + "9" * 32,
            "duration_ns": "126",
        },
        classification=dict(native_end["classification"]),
    )
    conflicting_native_end["identity"] = dict(native_end["identity"])
    conflict = summarize(
        [correlated_start, native_end, duplicate_native_end, conflicting_native_end]
    )["tasks"][0]["runtime_native_duration_sum"]
    assert conflict["by_phase"]["unattributed"]["sum_ns"] is None
    assert conflict["by_activity"]["tool-active"]["sum_ns"] is None
    assert conflict["by_phase"]["unattributed"]["conflicting_span_count"] == "1"
    assert conflict["by_activity"]["tool-active"]["conflicting_span_count"] == "1"
    assert conflict["by_activity"]["tool-active"]["measurement_provenance"] == [
        "runtime-observed"
    ]
    assert conflict["conflicting_span_count"] == "1"

    # Mixed immutable v1.0/v1.1 history and current v1.2 events remain
    # reportable. V1.1 adds exact lineage, terminal metadata, corrections, and
    # evidence; v1.2 adds target identity. Those fields remain explicitly
    # unavailable when their defining schema predates them.
    task_a = "id_" + "a" * 32
    lineage_a = "id_" + "b" * 32
    task_b = "id_" + "c" * 32
    lineage_b = "id_" + "d" * 32
    delegated_agent = "id_" + "9" * 32

    legacy_start = set_task_identity(
        event("10" * 16, 1, "task.start", 10),
        task_id=task_a,
        lineage_id=lineage_a,
    )
    legacy_start["measurement"]["recorder_overhead_ns"] = "2"
    legacy_terminal = set_task_identity(
        event(
            "11" * 16,
            2,
            "task.terminal",
            20,
            payload={"outcome": "incomplete"},
        ),
        task_id=task_a,
        lineage_id=lineage_a,
    )
    legacy_terminal["measurement"]["recorder_overhead_ns"] = "3"
    legacy_correction = set_task_identity(
        event("12" * 16, 3, "correction", 30),
        task_id=task_a,
        lineage_id=lineage_a,
    )
    legacy_correction["measurement"]["recorder_overhead_ns"] = "4"

    def current(item):
        set_task_identity(item, task_id=task_b, lineage_id=lineage_b)
        item["measurement"]["recorder_overhead_ns"] = "1"
        return item

    current_start = current(event_v12("20" * 16, 4, "task.start", 40))
    link = current(
        event_v12(
            "21" * 16,
            5,
            "lineage.link",
            50,
            adapter={"name": "agent-declaration", "version": ADAPTER_VERSION},
            measurement={"provenance": "agent-declared", "recorder_overhead_ns": None},
            payload={"task_kind": "continuation", "cause": "new-scope"},
        )
    )
    link["payload"]["link"] = {
        "task_id": task_a,
        "lineage_id": lineage_a,
        "provenance": "agent-declared",
    }

    def usage(
        event_id: str,
        sequence: int,
        phase: str,
        phase_provenance: str,
        input_tokens: str,
        *,
        measurement_provenance: str = "runtime-observed",
    ):
        item = current(
            event_v12(
                event_id,
                sequence,
                "usage.observed",
                sequence * 10,
                measurement={
                    "provenance": measurement_provenance,
                    "counter_source": "provider-native",
                    "tokens": {
                        "input": input_tokens,
                        "cached_input": "0",
                        "output": "1",
                        "reasoning_output": "0",
                        "tool": None,
                        "other": None,
                    },
                },
            )
        )
        item["classification"] = dict(item["classification"])
        item["classification"].update(
            {"phase": phase, "phase_provenance": phase_provenance}
        )
        return item

    phase_usage = [
        usage("22" * 16, 6, "implementation", "runtime-observed", "10"),
        usage("23" * 16, 7, "testing", "agent-declared", "4"),
        usage("24" * 16, 8, "planning", "inferred", "7"),
        usage(
            "25" * 16,
            9,
            "deployment",
            "runtime-observed",
            "3",
            measurement_provenance="agent-declared",
        ),
    ]

    def active_span(
        event_id: str,
        sequence: int,
        kind: str,
        mono: int,
        span_id: str,
        activity: str,
        *,
        agent_id=None,
    ):
        item = current(
            event_v12(
                event_id,
                sequence,
                kind,
                mono,
                payload={"span_id": span_id},
            )
        )
        item["identity"]["agent_id"] = agent_id
        item["classification"] = dict(item["classification"])
        item["classification"].update(
            {
                "activity_state": activity,
                "activity_provenance": "runtime-observed",
            }
        )
        return item

    root_span = "id_" + "1" * 32
    agent_span = "id_" + "2" * 32
    nested_agent_span = "id_" + "3" * 32
    active_spans = [
        active_span("30" * 16, 10, "span.start", 100, root_span, "tool-active"),
        active_span(
            "31" * 16,
            11,
            "span.start",
            120,
            agent_span,
            "model-active",
            agent_id=delegated_agent,
        ),
        active_span(
            "32" * 16,
            12,
            "span.start",
            130,
            nested_agent_span,
            "model-active",
            agent_id=delegated_agent,
        ),
        active_span(
            "33" * 16,
            13,
            "span.end",
            170,
            nested_agent_span,
            "model-active",
            agent_id=delegated_agent,
        ),
        active_span(
            "34" * 16,
            14,
            "span.end",
            180,
            agent_span,
            "model-active",
            agent_id=delegated_agent,
        ),
        active_span("35" * 16, 15, "span.end", 200, root_span, "tool-active"),
    ]

    requirement = current(
        event_v12(
            "40" * 16,
            16,
            "requirement.status",
            210,
            adapter={"name": "agent-declaration", "version": ADAPTER_VERSION},
            measurement={"provenance": "agent-declared", "recorder_overhead_ns": None},
            payload={
                "requirement_id": "REQ-MIXED",
                "requirement_status": "partial",
                "verification": "partially-verified",
            },
        )
    )
    requirement["payload"]["evidence"] = {
        "refs": ["test:acceptance"],
        "provenance": "agent-declared",
    }
    original_terminal = current(
        event_v11(
            "41" * 16,
            17,
            "task.terminal",
            220,
            adapter={"name": "agent-declaration", "version": ADAPTER_VERSION},
            measurement={"provenance": "agent-declared", "recorder_overhead_ns": None},
            payload={
                "outcome": "incomplete",
                "task_kind": "continuation",
                "cause": "new-scope",
                "verification": "partially-verified",
            },
        )
    )
    requirement_correction = current(
        event_v12(
            "42" * 16,
            18,
            "correction",
            230,
            adapter={"name": "agent-declaration", "version": ADAPTER_VERSION},
            measurement={"provenance": "agent-declared", "recorder_overhead_ns": None},
            payload={
                "requirement_id": "REQ-MIXED",
                "requirement_status": "satisfied",
                "verification": "verified",
            },
        )
    )
    requirement_correction["payload"]["correction"] = {
        "event_id": requirement["event_id"],
        "provenance": "agent-declared",
    }
    terminal_correction = current(
        event_v12(
            "43" * 16,
            19,
            "correction",
            240,
            adapter={"name": "agent-declaration", "version": ADAPTER_VERSION},
            measurement={"provenance": "agent-declared", "recorder_overhead_ns": None},
            payload={
                "outcome": "complete",
                "task_kind": "continuation",
                "cause": "new-scope",
                "verification": "verified",
            },
        )
    )
    terminal_correction["coverage"].update(
        {"scope": "complete", "verification": "complete"}
    )
    terminal_correction["payload"]["correction"] = {
        "event_id": original_terminal["event_id"],
        "provenance": "agent-declared",
    }
    terminal_correction["payload"]["task_metadata"].update(
        {
            "acceptance_baseline_id": "baseline:1",
            "acceptance_baseline_provenance": "agent-declared",
            "approved_scope_change_ids": ["scope:approved-1"],
            "scope_change_provenance": "agent-declared",
            "task_kind_provenance": "agent-declared",
            "task_type": "implementation",
            "task_type_provenance": "agent-declared",
            "scope_size": "medium",
            "scope_size_provenance": "agent-declared",
            "method": "hybrid",
            "method_provenance": "agent-declared",
        }
    )
    terminal_correction["payload"]["configuration"] = {
        "policy_version": "policy-v1",
        "policy_provenance": "agent-declared",
        "model_config_version": "model-v1",
        "model_config_provenance": "agent-declared",
        "runtime_config_version": "runtime-v1",
        "runtime_config_provenance": "agent-declared",
        "recorder_config_version": "recorder-v1",
        "recorder_config_provenance": "agent-declared",
    }

    mixed_events = [
        legacy_start,
        legacy_terminal,
        legacy_correction,
        current_start,
        link,
        *phase_usage,
        *active_spans,
        requirement,
        original_terminal,
        requirement_correction,
        terminal_correction,
    ]
    mixed_report = summarize(mixed_events)
    assert mixed_report["schema_version"] == "1.2"
    assert mixed_report["event_schema_compatibility"] == "mixed-v1.0-current-compatible"
    assert mixed_report["event_schema_versions"] == {"1.0": 3, "1.1": 1, "1.2": 15}
    by_task = {item["task_id"]: item for item in mixed_report["tasks"]}
    legacy_summary = by_task[task_a]
    current_summary = by_task[task_b]
    assert legacy_summary["terminal_metadata"]["availability"] == "unavailable-v1.0"
    assert legacy_summary["corrections"]["legacy_unsupported_count"] == 1
    assert legacy_summary["recorder_overhead"]["total_ns"] == "9"

    assert current_summary["resolved_lineage_id"] == lineage_a
    assert current_summary["target_id"] == "id_" + "8" * 32
    assert current_summary["linked_work"] == {
        "availability": "available-v1.1",
        "link_event_id": link["event_id"],
        "target_task_id": task_a,
        "declared_target_lineage_id": lineage_a,
        "resolved_target_lineage_id": lineage_a,
        "task_kind": "continuation",
        "cause": "new-scope",
        "provenance": "agent-declared",
        "resolution": "resolved",
    }
    assert current_summary["terminal_outcome"] == "complete"
    assert current_summary["complete"] is True
    assert current_summary["requirements"]["REQ-MIXED"]["status"] == "satisfied"
    assert current_summary["requirements"]["REQ-MIXED"]["verification"] == "verified"
    assert current_summary["requirements"]["REQ-MIXED"]["evidence_refs"] == [
        "test:acceptance"
    ]
    assert current_summary["requirements"]["REQ-MIXED"][
        "evidence_provenance"
    ] == "agent-declared"
    assert current_summary["requirements"]["REQ-MIXED"]["corrected_by_event_id"] == requirement_correction["event_id"]
    assert current_summary["corrections"]["applied_count"] == 2
    assert all(
        item["status"] == "applied"
        for item in current_summary["corrections"]["items"]
    )
    terminal_metadata = current_summary["terminal_metadata"]
    assert terminal_metadata["availability"] == "available-v1.1"
    assert terminal_metadata["task_metadata"]["acceptance_baseline_id"] == "baseline:1"
    assert terminal_metadata["task_metadata"]["task_type"] == "implementation"
    assert terminal_metadata["task_metadata"]["scope_size"] == "medium"
    assert terminal_metadata["task_metadata"]["method"] == "hybrid"
    assert terminal_metadata["configuration"]["model_config_version"] == "model-v1"
    assert all(value is None for value in current_summary["tokens"].values())

    phase_tokens = current_summary["tokens_by_phase"]
    assert phase_tokens["implementation"]["tokens"]["input"] == "10"
    assert phase_tokens["implementation"]["phase_attribution_provenance"] == [
        "runtime-observed"
    ]
    assert phase_tokens["testing"]["tokens"]["input"] == "4"
    assert phase_tokens["testing"]["phase_attribution_provenance"] == [
        "agent-declared"
    ]
    assert phase_tokens["planning"]["usage_event_count"] == 0
    assert phase_tokens["unattributed"]["tokens"]["input"] == "7"
    assert phase_tokens["unattributed"]["phase_attribution_provenance"] == [
        "inferred"
    ]
    assert phase_tokens["deployment"]["tokens"]["input"] is None
    assert phase_tokens["deployment"]["measurement_provenance"] == ["agent-declared"]

    per_agent = current_summary["per_agent_active_time"]
    assert per_agent["root_or_unidentified"]["active_interval_union_ns"] == "100"
    assert per_agent["by_agent"][delegated_agent]["active_interval_union_ns"] == "60"
    # Concurrent agents are deliberately summed, while overlapping spans for
    # the same delegated agent are unioned once.
    assert per_agent["summed_per_agent_active_ns"] == "160"
    assert current_summary["recorder_overhead"]["total_ns"] is None
    assert current_summary["recorder_overhead"]["coverage"] == "partial"

    # An evidence-free requirement correction retains the original evidence,
    # while a later correction carrying evidence replaces it as part of the
    # effective corrected state.
    evidence_replacing_correction = deepcopy(requirement_correction)
    evidence_replacing_correction["event_id"] = "48" * 16
    evidence_replacing_correction["sequence"] = "20"
    evidence_replacing_correction["observed_at_utc"] = "2026-07-28T00:00:20Z"
    evidence_replacing_correction["monotonic_ns"] = "250"
    evidence_replacing_correction["payload"]["evidence"] = {
        "refs": ["test:corrected-acceptance"],
        "provenance": "agent-declared",
    }
    corrected_evidence_summary = {
        item["task_id"]: item
        for item in summarize([*mixed_events, evidence_replacing_correction])["tasks"]
    }[task_b]
    corrected_requirement = corrected_evidence_summary["requirements"]["REQ-MIXED"]
    assert corrected_requirement["evidence_refs"] == ["test:corrected-acceptance"]
    assert corrected_requirement["evidence_provenance"] == "agent-declared"
    assert corrected_requirement["source_event_id"] == requirement["event_id"]
    assert corrected_requirement["corrected_by_event_id"] == (
        evidence_replacing_correction["event_id"]
    )

    # A later link declaration cannot silently override the target's actual
    # resolved lineage with a mismatched declaration.
    mismatched_link = deepcopy(link)
    mismatched_link["event_id"] = "44" * 16
    mismatched_link["sequence"] = "20"
    mismatched_link["observed_at_utc"] = "2026-07-28T00:00:20Z"
    mismatched_link["monotonic_ns"] = "250"
    mismatched_link["payload"]["link"]["lineage_id"] = "id_" + "e" * 32
    mismatched_summary = {
        item["task_id"]: item
        for item in summarize([*mixed_events, mismatched_link])["tasks"]
    }[task_b]
    assert mismatched_summary["resolved_lineage_id"] is None
    assert mismatched_summary["linked_work"]["resolution"] == "lineage-mismatch"

    # Correction targets are task-local and must predate the correction.  A
    # cross-task target remains visible as unresolved and cannot mutate state.
    cross_task_correction = deepcopy(terminal_correction)
    cross_task_correction["event_id"] = "45" * 16
    cross_task_correction["sequence"] = "20"
    cross_task_correction["observed_at_utc"] = "2026-07-28T00:00:20Z"
    cross_task_correction["monotonic_ns"] = "250"
    cross_task_correction["payload"]["correction"]["event_id"] = legacy_terminal[
        "event_id"
    ]
    cross_task_summary = {
        item["task_id"]: item
        for item in summarize([*mixed_events, cross_task_correction])["tasks"]
    }[task_b]
    assert cross_task_summary["corrections"]["unresolved_count"] == 1
    assert cross_task_summary["corrections"]["items"][-1]["status"] == (
        "target-missing-or-cross-task"
    )
    assert cross_task_summary["terminal_outcome"] == "complete"

    # Active intervals from distinct receiver clocks are never arithmetically
    # combined, even when they belong to the same delegated agent.
    other_clock_start = active_span(
        "46" * 16,
        20,
        "span.start",
        10,
        "id_" + "4" * 32,
        "model-active",
        agent_id=delegated_agent,
    )
    other_clock_end = active_span(
        "47" * 16,
        21,
        "span.end",
        30,
        "id_" + "4" * 32,
        "model-active",
        agent_id=delegated_agent,
    )
    other_clock_start["clock_domain"] = "clock_" + "f" * 32
    other_clock_end["clock_domain"] = "clock_" + "f" * 32
    cross_clock_summary = {
        item["task_id"]: item
        for item in summarize([*mixed_events, other_clock_start, other_clock_end])[
            "tasks"
        ]
    }[task_b]
    cross_clock_agents = cross_clock_summary["per_agent_active_time"]
    assert cross_clock_agents["by_agent"][delegated_agent][
        "active_interval_union_ns"
    ] is None
    assert cross_clock_agents["summed_per_agent_active_ns"] is None

    # Repository projection keeps opaque identity and exact known/unknown
    # counter coverage. Automation stays conservative until three comparable
    # non-automated terminal declarations exist.
    repeated = []
    for index in range(3):
        task_id = "id_" + str(index + 4) * 32
        lineage_id = "id_" + str(index + 5) * 32
        project_id = "id_" + "9" * 32
        start = set_task_identity(
            event_v12(("8{}".format(index)) * 16, 30 + index * 3, "task.start", 300 + index * 30),
            task_id=task_id,
            lineage_id=lineage_id,
        )
        start["identity"]["project_id"] = project_id
        measured = set_task_identity(
            usage(("9{}".format(index)) * 16, 31 + index * 3, "implementation", "agent-declared", "5"),
            task_id=task_id,
            lineage_id=lineage_id,
        )
        measured["identity"]["project_id"] = project_id
        terminal = set_task_identity(
            event_v12(("a{}".format(index)) * 16, 32 + index * 3, "task.terminal", 320 + index * 30,
                payload={"outcome": "complete"}),
            task_id=task_id,
            lineage_id=lineage_id,
        )
        terminal["identity"]["project_id"] = project_id
        terminal["payload"]["task_metadata"].update(
            {"task_type": "implementation", "scope_size": "small", "method": "direct"}
        )
        repeated.extend([start, measured, terminal])
    repository_report = summarize_repositories(repeated)
    assert repository_report["repository_count"] == 1
    repository = repository_report["repositories"][0]
    assert repository["project_id"] == "id_" + "9" * 32
    assert "display_name" not in repository
    assert repository["tokens"]["input"] == {
        "known_sum": "15", "known_task_count": 3, "task_count": 3, "coverage": "complete"
    }
    assert repository["tokens_by_phase"]["implementation"]["input"]["known_sum"] == "15"
    assert len(repository["automation_opportunities"]) == 1
    assert repository["automation_opportunities"][0]["occurrence_count"] == 3
    two_task_report = summarize_repositories(repeated[:6])
    assert two_task_report["repositories"][0]["automation_opportunities"] == []
    labels = {project_id: "example-repository"}
    labeled_repository = summarize_repositories(repeated, labels)["repositories"][0]
    assert labeled_repository["display_name"] == "example-repository"
    task_index = summarize_tasks(repeated, labels)
    assert [item["display_name"] for item in task_index["tasks"]] == [
        "example-repository task 1",
        "example-repository task 2",
        "example-repository task 3",
    ]
    assert all(item["repository"] == "example-repository" for item in task_index["tasks"])

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        ledger = root / "EfficiencyLedger.jsonl"
        ledger.write_bytes(
            b"".join(
                (canonical_json(item) + "\n").encode("utf-8")
                for item in mixed_events
            )
        )
        assert len(read_ledger(ledger)) == len(mixed_events)
        ledger.write_bytes(b"{}\r\n")
        try:
            read_ledger(ledger)
        except ReportingError:
            pass
        else:
            raise AssertionError("CRLF ledger must be rejected")
        noncanonical = (json.dumps(task[0], sort_keys=True) + "\n").encode("utf-8")
        ledger.write_bytes(noncanonical)
        try:
            read_ledger(ledger)
        except ReportingError:
            pass
        else:
            raise AssertionError("noncanonical durable JSON must be rejected")
        invalid = dict(task[0])
        invalid["unexpected"] = "field"
        ledger.write_bytes((canonical_json(invalid) + "\n").encode("utf-8"))
        try:
            read_ledger(ledger)
        except ReportingError:
            pass
        else:
            raise AssertionError("schema-invalid durable events must be rejected")
        ledger.write_bytes((canonical_json(task[0]) + "\n").encode("utf-8"))
        assert len(read_ledger(ledger)) == 1
    print("reporting self-test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
