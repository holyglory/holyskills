#!/usr/bin/env python3
"""Prove the published adapter schema matches the dependency-free validator."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from delivery_efficiency import contract
from delivery_efficiency.declarations import (
    requirement_correction_emission,
    terminal_emissions,
)


def expect_contract_error(callback, label):
    try:
        callback()
    except contract.ContractValidationError:
        return
    raise AssertionError(label)


def durable_from_observation(observation, *, schema_version="1.1"):
    """Build one exact durable envelope without introducing private identity."""

    value = copy.deepcopy(observation)
    value.pop("source_identity")
    value.update(
        {
            "schema_version": schema_version,
            "recorder_version": "0.2.1",
            "event_id": "a" * 32,
            "sequence": "1",
            "observed_at_utc": "2026-07-29T00:00:00Z",
            "monotonic_ns": "1",
            "clock_domain": "clock_" + "b" * 32,
            "platform": {"os": "linux", "environment": "native"},
            "identity": {
                "lineage_id": "id_" + "c" * 32,
                "task_id": "id_" + "d" * 32,
                "project_id": None,
                "revision_id": None,
                "session_id": "id_" + "e" * 32,
                "turn_id": None,
                "agent_id": None,
            },
        }
    )
    return value


def assert_versioned_semantics_and_privacy():
    emissions = terminal_emissions(
        session="opaque-session-binding",
        runtime_family="claude",
        surface="cli-interactive",
        outcome="complete",
        verification="verified",
        task_kind="primary",
        cause="not-applicable",
        requirements=[("REQ-SCHEMA", "satisfied", "verified")],
        requirement_evidence={"REQ-SCHEMA": ["test:REQ-SCHEMA"]},
        acceptance_baseline_id="baseline:REQ-SCHEMA",
        approved_scope_change_ids=[],
        task_type="implementation",
        scope_size="small",
        method="direct",
    )
    requirement = emissions[0][0]
    terminal = emissions[-1][0]
    contract.validate_normalized_observation(requirement)
    contract.validate_normalized_observation(terminal)

    current = durable_from_observation(requirement)
    contract.validate_durable_event(current)

    legacy = copy.deepcopy(current)
    legacy["schema_version"] = "1.0"
    legacy["recorder_version"] = "0.1.3"
    legacy["adapter"]["version"] = "0.1.0"
    for field in ("link", "correction", "task_metadata", "evidence", "configuration"):
        legacy["payload"].pop(field)
    contract.validate_durable_event(legacy)

    legacy_with_current_field = copy.deepcopy(legacy)
    legacy_with_current_field["payload"]["evidence"] = {
        "refs": [],
        "provenance": "unknown",
    }
    expect_contract_error(
        lambda: contract.validate_durable_event(legacy_with_current_field),
        "v1.0 must reject v1.1 payload fields",
    )

    missing_nested = copy.deepcopy(current)
    missing_nested["payload"].pop("task_metadata")
    expect_contract_error(
        lambda: contract.validate_durable_event(missing_nested),
        "v1.1 must require every nested payload object",
    )

    unsupported = copy.deepcopy(current)
    unsupported["schema_version"] = "2.0"
    expect_contract_error(
        lambda: contract.validate_durable_event(unsupported),
        "unsupported schema versions must fail closed",
    )

    missing_baseline = copy.deepcopy(terminal)
    missing_baseline["payload"]["task_metadata"]["acceptance_baseline_id"] = None
    missing_baseline["payload"]["task_metadata"][
        "acceptance_baseline_provenance"
    ] = "unknown"
    expect_contract_error(
        lambda: contract.validate_normalized_observation(missing_baseline),
        "complete terminals require their acceptance baseline",
    )

    missing_classification = copy.deepcopy(terminal)
    missing_classification["payload"]["task_metadata"]["task_type"] = "unknown"
    missing_classification["payload"]["task_metadata"][
        "task_type_provenance"
    ] = "unknown"
    expect_contract_error(
        lambda: contract.validate_normalized_observation(missing_classification),
        "complete terminals require explicit task classifications",
    )

    for refs, label in (
        (["private/path"], "path-like evidence references must be rejected"),
        (["test:duplicate", "test:duplicate"], "duplicate evidence references must be rejected"),
        (["test:item-{}".format(index) for index in range(33)], "oversized evidence lists must be rejected"),
    ):
        malformed_evidence = copy.deepcopy(requirement)
        malformed_evidence["payload"]["evidence"] = {
            "refs": refs,
            "provenance": "agent-declared",
        }
        expect_contract_error(
            lambda value=malformed_evidence: contract.validate_normalized_observation(value),
            label,
        )

    correction = requirement_correction_emission(
        session="opaque-session-binding",
        runtime_family="claude",
        surface="cli-interactive",
        target_event_id="f" * 32,
        requirement_id="REQ-SCHEMA",
        status="satisfied",
        verification="verified",
        evidence_refs=["test:corrected"],
    )[0]
    contract.validate_normalized_observation(correction)

    missing_target = copy.deepcopy(correction)
    missing_target["payload"]["correction"] = {
        "event_id": None,
        "provenance": "unknown",
    }
    expect_contract_error(
        lambda: contract.validate_normalized_observation(missing_target),
        "corrections require an explicit target",
    )

    ambiguous_correction = copy.deepcopy(correction)
    ambiguous_correction["payload"]["outcome"] = "incomplete"
    expect_contract_error(
        lambda: contract.validate_normalized_observation(ambiguous_correction),
        "one correction cannot replace terminal and requirement state together",
    )


def enum(node, schema=None):
    if "enum" in node:
        return set(node["enum"])
    if schema is not None and node.get("$ref", "").startswith("#/$defs/"):
        return set(schema["$defs"][node["$ref"].rsplit("/", 1)[-1]]["enum"])
    raise AssertionError("schema node has no enum")


def main() -> int:
    schema = json.loads(
        (ROOT / "contract" / "adapter-event-v1.1.schema.json").read_text(encoding="utf-8")
    )
    legacy_schema = json.loads(
        (ROOT / "contract" / "adapter-event-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    properties = schema["properties"]
    assert properties["schema_version"]["const"] == contract.SCHEMA_VERSION == "1.1"
    assert legacy_schema["properties"]["schema_version"]["const"] == "1.0"
    assert enum(properties["runtime"]["properties"]["family"]) == contract.RUNTIME_FAMILIES
    assert enum(properties["runtime"]["properties"]["surface"]) == contract.RUNTIME_SURFACES
    assert enum(properties["adapter"]["properties"]["name"]) == contract.ADAPTER_NAMES
    assert enum(properties["platform"]["properties"]["os"]) == contract.OPERATING_SYSTEMS
    assert enum(properties["platform"]["properties"]["environment"]) == contract.PLATFORM_ENVIRONMENTS
    classification = properties["classification"]["properties"]
    assert enum(classification["phase"]) == contract.PHASES
    assert enum(classification["phase_provenance"], schema) == contract.PROVENANCE
    assert enum(classification["activity_state"]) == contract.ACTIVITY_STATES
    assert enum(classification["activity_provenance"], schema) == contract.PROVENANCE
    measurement = properties["measurement"]["properties"]
    assert enum(measurement["provenance"], schema) == contract.PROVENANCE
    assert enum(measurement["counter_source"]) == contract.COUNTER_SOURCES
    for node in properties["coverage"]["properties"].values():
        assert node["$ref"] == "#/$defs/coverage"
    assert set(schema["$defs"]["coverage"]["enum"]) == contract.COVERAGE
    assert enum(properties["event"]) == contract.EVENTS
    payload = properties["payload"]["properties"]
    assert enum(payload["source_event"]) == contract.SOURCE_EVENTS
    assert enum(payload["tool_category"]) == contract.TOOL_CATEGORIES
    assert enum(payload["outcome"]) == contract.OUTCOMES
    assert enum(payload["task_kind"]) == contract.TASK_KINDS
    metadata = payload["task_metadata"]["properties"]
    assert enum(metadata["task_type"]) == contract.TASK_TYPES
    assert enum(metadata["scope_size"]) == contract.SCOPE_SIZES
    assert enum(metadata["method"]) == contract.METHODS
    assert enum(payload["cause"]) == contract.CAUSES
    assert enum(payload["requirement_status"]) == contract.REQUIREMENT_STATUSES
    assert enum(payload["verification"]) == contract.VERIFICATION
    assert enum(payload["gap_code"]) == contract.GAP_CODES

    def objects(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                yield node
            for child in node.values():
                yield from objects(child)
        elif isinstance(node, list):
            for child in node:
                yield from objects(child)

    assert all(item.get("additionalProperties") is False for item in objects(schema))
    assert all(
        item.get("additionalProperties") is False for item in objects(legacy_schema)
    )
    assert_versioned_semantics_and_privacy()
    print("schema self-test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
