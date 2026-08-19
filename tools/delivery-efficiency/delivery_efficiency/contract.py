"""Strict, dependency-free validation for delivery-efficiency events.

The recorder intentionally accepts a much smaller object than an arbitrary
runtime event.  Runtime adapters must translate into this positive allowlist
before calling the core; unknown fields are rejected instead of redacted.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, Mapping, Optional, Set

from . import ADAPTER_VERSION, RECORDER_VERSION, SCHEMA_VERSION


MAX_CANONICAL_EVENT_BYTES = 32 * 1024
MAX_SOURCE_VALUE_BYTES = 4096
MAX_SOURCE_KEY_BYTES = 4096
MAX_DECIMAL_DIGITS = 30


class ContractValidationError(ValueError):
    """Raised when an adapter observation is outside the frozen contract."""


_DECIMAL_RE = re.compile(r"^(0|[1-9][0-9]*)$")
_OPAQUE_RE = re.compile(r"^id_[0-9a-f]{32}$")
_EVENT_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_CLOCK_RE = re.compile(r"^clock_[0-9a-f]{32}$")
_SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_REQUIREMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_REFERENCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,127}$")
_SAFE_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+ -]{0,63}$")
_SAFE_CONFIG_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+:-]{0,63}$")
_SAFE_CLASSIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,31}$")
_TARGET_SOURCE_RE = re.compile(r"^target_v1_[0-9a-f]{32}$")

LEGACY_SCHEMA_VERSION = "1.0"
PREVIOUS_SCHEMA_VERSION = "1.1"
SUPPORTED_SCHEMA_VERSIONS = {
    LEGACY_SCHEMA_VERSION,
    PREVIOUS_SCHEMA_VERSION,
    SCHEMA_VERSION,
}

RUNTIME_FAMILIES = {"codex", "claude"}
RUNTIME_SURFACES = {"cli-interactive", "cli-exec", "desktop", "ide", "unknown"}
ADAPTER_NAMES = {"codex-hooks", "codex-otel", "codex-exec", "claude-runtime", "agent-declaration"}
OPERATING_SYSTEMS = {"windows", "linux", "macos"}
PLATFORM_ENVIRONMENTS = {"native", "wsl"}
PHASES = {"planning", "implementation", "testing", "deployment", "reporting", "unattributed"}
ACTIVITY_STATES = {
    "model-active",
    "tool-active",
    "external-wait",
    "user-wait",
    "blocked-wait",
    "unattributed",
}
PROVENANCE = {"runtime-observed", "agent-declared", "inferred", "unknown", "not-applicable"}
COUNTER_SOURCES = {"provider-native", "runtime-native", "not-applicable", "unknown"}
COVERAGE = {"complete", "partial", "unknown", "not-applicable"}
EVENTS = {
    "task.start",
    "task.first_activity",
    "span.start",
    "span.end",
    "usage.observed",
    "requirement.status",
    "runtime.turn_stopped",
    "task.terminal",
    "lineage.link",
    "coverage.gap",
    "correction",
}
SOURCE_EVENTS = {
    "session_start",
    "session_end",
    "prompt_submit",
    "pre_tool",
    "post_tool",
    "post_tool_failure",
    "subagent_start",
    "subagent_stop",
    "turn_stop",
    "turn_failure",
    "message_display",
    "otel_response_completed",
    "otel_api",
    "otel_api_error",
    "otel_tool",
    "otel_tool_decision",
    "exec_process",
    "exec_turn",
    "agent_declaration",
    "unknown",
}
TOOL_CATEGORIES = {"shell", "patch", "mcp", "web", "agent", "local", "other", "not-applicable", "unknown"}
OUTCOMES = {
    "complete",
    "incomplete",
    "blocked",
    "cancelled",
    "superseded",
    "interrupted",
    "not-applicable",
    "unknown",
}
TASK_KINDS = {"primary", "continuation", "retry", "rollback", "defect-repair", "rework", "unknown"}
TASK_TYPES = {
    "implementation",
    "diagnosis",
    "review",
    "audit",
    "research",
    "documentation",
    "operations",
    "mixed",
    "other",
    "not-applicable",
    "unknown",
}
SCOPE_SIZES = {"small", "medium", "large", "extra-large", "not-applicable", "unknown"}
METHODS = {"direct", "delegated", "hybrid", "automated", "not-applicable", "unknown"}
CAUSES = {
    "agent-caused-mistake",
    "changed-user-intent",
    "new-scope",
    "external-cause",
    "not-applicable",
    "unknown",
}
REQUIREMENT_STATUSES = {"satisfied", "partial", "blocked", "removed", "not-applicable", "unknown"}
VERIFICATION = {"verified", "partially-verified", "unverified", "not-applicable", "unknown"}
GAP_CODES = {
    "none",
    "hooks-untrusted",
    "hooks-disabled",
    "host-boundary-unavailable",
    "hosted-tool-unobserved",
    "token-source-unavailable",
    "otel-conflict",
    "receiver-unavailable",
    "clock-domain-changed",
    "storage-unavailable",
    "malformed-source-event",
    "unsupported-runtime-event",
    "unknown",
}

SOURCE_IDENTITY_KEYS = {
    "lineage",
    "task",
    "project",
    "revision",
    "session",
    "turn",
    "agent",
    "span",
    "target",
}
LEGACY_IDENTITY_KEYS = {
    "lineage_id",
    "task_id",
    "project_id",
    "revision_id",
    "session_id",
    "turn_id",
    "agent_id",
}
IDENTITY_KEYS = LEGACY_IDENTITY_KEYS | {"target_id"}
OBSERVATION_KEYS = {
    "runtime",
    "adapter",
    "source_identity",
    "classification",
    "measurement",
    "coverage",
    "event",
    "payload",
}


def canonical_json(value: Mapping[str, Any]) -> str:
    """Return the one permitted JSON representation for durable records."""

    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ContractValidationError("value is not canonical JSON") from exc
    if len(encoded.encode("utf-8")) > MAX_CANONICAL_EVENT_BYTES:
        raise ContractValidationError("canonical event exceeds the size limit")
    return encoded


def validate_source_key(source_key: str) -> None:
    if not isinstance(source_key, str):
        raise ContractValidationError("source_key must be a string")
    size = len(source_key.encode("utf-8"))
    if size == 0 or size > MAX_SOURCE_KEY_BYTES or "\x00" in source_key:
        raise ContractValidationError("source_key is empty or exceeds its safe bound")


def validate_normalized_observation(observation: Mapping[str, Any]) -> None:
    """Validate the adapter-to-core allowlist, including exact properties."""

    _mapping(observation, "observation")
    _exact_keys(observation, OBSERVATION_KEYS, "observation")
    _validate_runtime(observation["runtime"])
    _validate_adapter(observation["adapter"])
    _validate_source_identity(observation["source_identity"])
    _validate_classification(observation["classification"])
    _validate_measurement(observation["measurement"])
    _validate_coverage(observation["coverage"])
    _enum(observation["event"], EVENTS, "event")
    _validate_payload(observation["payload"])
    if observation["event"] in {"span.start", "span.end"}:
        if observation["source_identity"]["span"] is None:
            raise ContractValidationError("span events require a raw span source identity")
        if observation["payload"]["span_id"] is not None:
            raise ContractValidationError("adapters must not precompute durable span identifiers")
    elif observation["source_identity"]["span"] is not None:
        raise ContractValidationError("raw span source identity is only valid for span events")
    _validate_event_semantics(
        observation["event"], observation["payload"], observation["coverage"], require_span=False
    )
    canonical_json(observation)


def validate_durable_event(event: Mapping[str, Any]) -> None:
    """Validate current events and immutable legacy v1.0 ledger rows."""

    _mapping(event, "durable event")
    envelope = {
        "schema_version",
        "recorder_version",
        "event_id",
        "sequence",
        "observed_at_utc",
        "monotonic_ns",
        "clock_domain",
        "runtime",
        "adapter",
        "platform",
        "identity",
        "classification",
        "measurement",
        "coverage",
        "event",
        "payload",
    }
    _exact_keys(event, envelope, "durable event")
    schema_version = event["schema_version"]
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ContractValidationError("unsupported schema_version")
    _semver(event["recorder_version"], "recorder_version")
    _pattern(event["event_id"], _EVENT_ID_RE, "event_id")
    _decimal(event["sequence"], "sequence")
    _date_time(event["observed_at_utc"])
    _decimal(event["monotonic_ns"], "monotonic_ns")
    _pattern(event["clock_domain"], _CLOCK_RE, "clock_domain")
    _validate_runtime(event["runtime"])
    _validate_adapter(event["adapter"])
    _validate_platform(event["platform"])
    _validate_identity(event["identity"], schema_version=schema_version)
    _validate_classification(event["classification"])
    _validate_measurement(event["measurement"])
    _validate_coverage(event["coverage"])
    _enum(event["event"], EVENTS, "event")
    if schema_version == LEGACY_SCHEMA_VERSION:
        _validate_payload_v1_0(event["payload"])
        _validate_event_semantics_v1_0(
            event["event"], event["payload"], event["coverage"], require_span=True
        )
    else:
        _validate_payload(event["payload"])
        _validate_event_semantics(
            event["event"], event["payload"], event["coverage"], require_span=True
        )
    canonical_json(event)


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractValidationError("{} must be an object".format(label))
    for key in value.keys():
        if not isinstance(key, str):
            raise ContractValidationError("{} has a non-string property".format(label))
    return value


def _exact_keys(value: Mapping[str, Any], expected: Set[str], label: str) -> None:
    actual = set(value.keys())
    if actual != expected:
        raise ContractValidationError("{} properties do not match the allowlist".format(label))


def _enum(value: Any, permitted: Set[str], label: str) -> None:
    if not isinstance(value, str) or value not in permitted:
        raise ContractValidationError("{} is outside the allowlist".format(label))


def _pattern(value: Any, pattern: re.Pattern, label: str) -> None:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ContractValidationError("{} has an invalid format".format(label))


def _semver(value: Any, label: str) -> None:
    _pattern(value, _SEMVER_RE, label)


def _decimal(value: Any, label: str) -> None:
    if not isinstance(value, str) or len(value) > MAX_DECIMAL_DIGITS or _DECIMAL_RE.fullmatch(value) is None:
        raise ContractValidationError("{} must be a bounded non-negative decimal string".format(label))


def _decimal_or_null(value: Any, label: str) -> None:
    if value is not None:
        _decimal(value, label)


def _date_time(value: Any) -> None:
    if not isinstance(value, str) or len(value) > 40 or not value.endswith("Z"):
        raise ContractValidationError("observed_at_utc must be a bounded UTC date-time")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ContractValidationError("observed_at_utc must be a valid UTC date-time") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ContractValidationError("observed_at_utc must use UTC")


def _validate_runtime(value: Any) -> None:
    value = _mapping(value, "runtime")
    _exact_keys(value, {"family", "surface", "version"}, "runtime")
    _enum(value["family"], RUNTIME_FAMILIES, "runtime.family")
    _enum(value["surface"], RUNTIME_SURFACES, "runtime.surface")
    version = value["version"]
    if version is not None and (not isinstance(version, str) or _SAFE_VERSION_RE.fullmatch(version) is None):
        raise ContractValidationError("runtime.version has an invalid format")


def _validate_adapter(value: Any) -> None:
    value = _mapping(value, "adapter")
    _exact_keys(value, {"name", "version"}, "adapter")
    _enum(value["name"], ADAPTER_NAMES, "adapter.name")
    _semver(value["version"], "adapter.version")


def _validate_source_identity(value: Any) -> None:
    value = _mapping(value, "source_identity")
    _exact_keys(value, SOURCE_IDENTITY_KEYS, "source_identity")
    for field in sorted(SOURCE_IDENTITY_KEYS):
        raw = value[field]
        if raw is None:
            continue
        if not isinstance(raw, str):
            raise ContractValidationError("source identity values must be strings or null")
        size = len(raw.encode("utf-8"))
        if size == 0 or size > MAX_SOURCE_VALUE_BYTES or "\x00" in raw:
            raise ContractValidationError("source identity value is empty or exceeds its safe bound")
        if field == "target" and _TARGET_SOURCE_RE.fullmatch(raw) is None:
            raise ContractValidationError(
                "source identity target is not an installer-assigned opaque reference"
            )


def _validate_identity(value: Any, *, schema_version: str) -> None:
    value = _mapping(value, "identity")
    keys = (
        LEGACY_IDENTITY_KEYS
        if schema_version in {LEGACY_SCHEMA_VERSION, PREVIOUS_SCHEMA_VERSION}
        else IDENTITY_KEYS
    )
    _exact_keys(value, keys, "identity")
    for field in sorted(keys):
        if value[field] is not None:
            _pattern(value[field], _OPAQUE_RE, "identity." + field)


def _validate_platform(value: Any) -> None:
    value = _mapping(value, "platform")
    _exact_keys(value, {"os", "environment"}, "platform")
    _enum(value["os"], OPERATING_SYSTEMS, "platform.os")
    _enum(value["environment"], PLATFORM_ENVIRONMENTS, "platform.environment")
    if value["environment"] == "wsl" and value["os"] != "linux":
        raise ContractValidationError("WSL must report the Linux operating system")


def _validate_classification(value: Any) -> None:
    value = _mapping(value, "classification")
    keys = {"phase", "phase_provenance", "activity_state", "activity_provenance", "classifier_version"}
    _exact_keys(value, keys, "classification")
    _enum(value["phase"], PHASES, "classification.phase")
    _enum(value["phase_provenance"], PROVENANCE, "classification.phase_provenance")
    _enum(value["activity_state"], ACTIVITY_STATES, "classification.activity_state")
    _enum(value["activity_provenance"], PROVENANCE, "classification.activity_provenance")
    if (
        not isinstance(value["classifier_version"], str)
        or _SAFE_CLASSIFIER_RE.fullmatch(value["classifier_version"]) is None
    ):
        raise ContractValidationError("classification.classifier_version has an invalid format")


def _validate_measurement(value: Any) -> None:
    value = _mapping(value, "measurement")
    _exact_keys(value, {"provenance", "counter_source", "tokens", "recorder_overhead_ns"}, "measurement")
    _enum(value["provenance"], PROVENANCE, "measurement.provenance")
    _enum(value["counter_source"], COUNTER_SOURCES, "measurement.counter_source")
    tokens = _mapping(value["tokens"], "measurement.tokens")
    token_keys = {"input", "cached_input", "output", "reasoning_output", "tool", "other"}
    _exact_keys(tokens, token_keys, "measurement.tokens")
    for field in sorted(token_keys):
        _decimal_or_null(tokens[field], "measurement.tokens." + field)
    _decimal_or_null(value["recorder_overhead_ns"], "measurement.recorder_overhead_ns")


def _validate_coverage(value: Any) -> None:
    value = _mapping(value, "coverage")
    keys = {
        "request_receipt",
        "first_activity",
        "tokens",
        "tools",
        "subagents",
        "terminal_delivery",
        "scope",
        "verification",
    }
    _exact_keys(value, keys, "coverage")
    for field in sorted(keys):
        _enum(value[field], COVERAGE, "coverage." + field)


_PAYLOAD_V1_0_KEYS = {
    "source_event",
    "span_id",
    "parent_span_id",
    "duration_ns",
    "success",
    "tool_category",
    "outcome",
    "task_kind",
    "cause",
    "requirement_id",
    "requirement_status",
    "verification",
    "gap_code",
}


def _validate_payload_v1_0(value: Any) -> None:
    value = _mapping(value, "payload")
    _exact_keys(value, _PAYLOAD_V1_0_KEYS, "payload")
    _validate_payload_v1_0_values(value)


def _validate_payload(value: Any) -> None:
    value = _mapping(value, "payload")
    _exact_keys(
        value,
        _PAYLOAD_V1_0_KEYS
        | {"link", "correction", "task_metadata", "evidence", "configuration"},
        "payload",
    )
    _validate_payload_v1_0_values(value)
    _validate_link(value["link"])
    _validate_correction(value["correction"])
    _validate_task_metadata(value["task_metadata"])
    _validate_evidence(value["evidence"])
    _validate_configuration(value["configuration"])


def _validate_payload_v1_0_values(value: Mapping[str, Any]) -> None:
    _enum(value["source_event"], SOURCE_EVENTS, "payload.source_event")
    for field in ("span_id", "parent_span_id"):
        if value[field] is not None:
            _pattern(value[field], _OPAQUE_RE, "payload." + field)
    _decimal_or_null(value["duration_ns"], "payload.duration_ns")
    if value["success"] is not None and not isinstance(value["success"], bool):
        raise ContractValidationError("payload.success must be boolean or null")
    _enum(value["tool_category"], TOOL_CATEGORIES, "payload.tool_category")
    _enum(value["outcome"], OUTCOMES, "payload.outcome")
    _enum(value["task_kind"], TASK_KINDS, "payload.task_kind")
    _enum(value["cause"], CAUSES, "payload.cause")
    requirement_id = value["requirement_id"]
    if requirement_id is not None:
        _pattern(requirement_id, _REQUIREMENT_RE, "payload.requirement_id")
    _enum(value["requirement_status"], REQUIREMENT_STATUSES, "payload.requirement_status")
    _enum(value["verification"], VERIFICATION, "payload.verification")
    _enum(value["gap_code"], GAP_CODES, "payload.gap_code")


def _validate_link(value: Any) -> None:
    value = _mapping(value, "payload.link")
    _exact_keys(value, {"task_id", "lineage_id", "provenance"}, "payload.link")
    for field in ("task_id", "lineage_id"):
        if value[field] is not None:
            _pattern(value[field], _OPAQUE_RE, "payload.link." + field)
    _enum(value["provenance"], PROVENANCE, "payload.link.provenance")


def _validate_correction(value: Any) -> None:
    value = _mapping(value, "payload.correction")
    _exact_keys(value, {"event_id", "provenance"}, "payload.correction")
    if value["event_id"] is not None:
        _pattern(value["event_id"], _EVENT_ID_RE, "payload.correction.event_id")
    _enum(value["provenance"], PROVENANCE, "payload.correction.provenance")


def _validate_reference(value: Any, label: str) -> None:
    _pattern(value, _REFERENCE_RE, label)


def _validate_reference_list(value: Any, label: str) -> None:
    if not isinstance(value, list) or len(value) > 32:
        raise ContractValidationError("{} must be a bounded array".format(label))
    seen = set()
    for item in value:
        _validate_reference(item, label)
        if item in seen:
            raise ContractValidationError("{} must not contain duplicates".format(label))
        seen.add(item)


def _validate_task_metadata(value: Any) -> None:
    value = _mapping(value, "payload.task_metadata")
    keys = {
        "acceptance_baseline_id",
        "acceptance_baseline_provenance",
        "approved_scope_change_ids",
        "scope_change_provenance",
        "task_kind_provenance",
        "task_type",
        "task_type_provenance",
        "scope_size",
        "scope_size_provenance",
        "method",
        "method_provenance",
        "classifier_version",
    }
    _exact_keys(value, keys, "payload.task_metadata")
    if value["acceptance_baseline_id"] is not None:
        _validate_reference(
            value["acceptance_baseline_id"],
            "payload.task_metadata.acceptance_baseline_id",
        )
    _enum(
        value["acceptance_baseline_provenance"],
        PROVENANCE,
        "payload.task_metadata.acceptance_baseline_provenance",
    )
    _validate_reference_list(
        value["approved_scope_change_ids"],
        "payload.task_metadata.approved_scope_change_ids",
    )
    _enum(
        value["scope_change_provenance"],
        PROVENANCE,
        "payload.task_metadata.scope_change_provenance",
    )
    _enum(
        value["task_kind_provenance"],
        PROVENANCE,
        "payload.task_metadata.task_kind_provenance",
    )
    _enum(value["task_type"], TASK_TYPES, "payload.task_metadata.task_type")
    _enum(
        value["task_type_provenance"],
        PROVENANCE,
        "payload.task_metadata.task_type_provenance",
    )
    _enum(value["scope_size"], SCOPE_SIZES, "payload.task_metadata.scope_size")
    _enum(
        value["scope_size_provenance"],
        PROVENANCE,
        "payload.task_metadata.scope_size_provenance",
    )
    _enum(value["method"], METHODS, "payload.task_metadata.method")
    _enum(
        value["method_provenance"],
        PROVENANCE,
        "payload.task_metadata.method_provenance",
    )
    if (
        not isinstance(value["classifier_version"], str)
        or _SAFE_CLASSIFIER_RE.fullmatch(value["classifier_version"]) is None
    ):
        raise ContractValidationError(
            "payload.task_metadata.classifier_version has an invalid format"
        )


def _validate_evidence(value: Any) -> None:
    value = _mapping(value, "payload.evidence")
    _exact_keys(value, {"refs", "provenance"}, "payload.evidence")
    _validate_reference_list(value["refs"], "payload.evidence.refs")
    _enum(value["provenance"], PROVENANCE, "payload.evidence.provenance")


def _validate_configuration(value: Any) -> None:
    value = _mapping(value, "payload.configuration")
    fields = (
        "policy_version",
        "model_config_version",
        "runtime_config_version",
        "recorder_config_version",
    )
    keys = set(fields) | {
        "policy_provenance",
        "model_config_provenance",
        "runtime_config_provenance",
        "recorder_config_provenance",
    }
    _exact_keys(value, keys, "payload.configuration")
    for field in fields:
        item = value[field]
        if item is not None and (
            not isinstance(item, str) or _SAFE_CONFIG_VERSION_RE.fullmatch(item) is None
        ):
            raise ContractValidationError(
                "payload.configuration.{} has an invalid format".format(field)
            )
    for field in (
        "policy_provenance",
        "model_config_provenance",
        "runtime_config_provenance",
        "recorder_config_provenance",
    ):
        _enum(value[field], PROVENANCE, "payload.configuration." + field)


def _validate_event_semantics_v1_0(
    event: str,
    payload: Mapping[str, Any],
    coverage: Mapping[str, Any],
    *,
    require_span: bool,
) -> None:
    if require_span and event in {"span.start", "span.end"} and payload["span_id"] is None:
        raise ContractValidationError("span events require a core-derived span_id")
    if event == "task.terminal":
        if payload["outcome"] in {"unknown", "not-applicable"}:
            raise ContractValidationError("task.terminal requires an explicit outcome")
        if payload["outcome"] == "complete":
            if coverage["scope"] in {"unknown", "not-applicable"}:
                raise ContractValidationError("a complete terminal event requires stated scope coverage")
            if coverage["verification"] in {"unknown", "not-applicable"}:
                raise ContractValidationError("a complete terminal event requires stated verification coverage")
    is_requirement_correction = (
        event == "correction" and payload["requirement_id"] is not None
    )
    if event == "requirement.status" or is_requirement_correction:
        if payload["requirement_id"] is None or payload["requirement_status"] in {"unknown", "not-applicable"}:
            raise ContractValidationError("requirement.status requires an identifier and explicit status")
    if event == "coverage.gap" and payload["gap_code"] == "none":
        raise ContractValidationError("coverage.gap requires an explicit gap_code")


def _validate_event_semantics(
    event: str,
    payload: Mapping[str, Any],
    coverage: Mapping[str, Any],
    *,
    require_span: bool,
) -> None:
    _validate_event_semantics_v1_0(
        event, payload, coverage, require_span=require_span
    )
    link = payload["link"]
    correction = payload["correction"]
    task_metadata = payload["task_metadata"]
    evidence = payload["evidence"]
    configuration = payload["configuration"]

    if event == "lineage.link":
        if link["task_id"] is None or link["lineage_id"] is None:
            if require_span:
                raise ContractValidationError(
                    "lineage.link requires recorder-resolved task and lineage targets"
                )
        if link["provenance"] in {"unknown", "not-applicable"}:
            raise ContractValidationError("lineage.link requires explicit provenance")
        if payload["task_kind"] not in {
            "continuation",
            "retry",
            "rollback",
            "defect-repair",
            "rework",
        }:
            raise ContractValidationError("lineage.link requires a linked-work task kind")
    elif (
        link["task_id"] is not None
        or link["lineage_id"] is not None
        or link["provenance"] != "not-applicable"
    ):
        raise ContractValidationError("link metadata is valid only on lineage.link")

    if event == "correction":
        if correction["event_id"] is None or correction["provenance"] in {
            "unknown",
            "not-applicable",
        }:
            raise ContractValidationError(
                "correction requires an explicit target and provenance"
            )
        corrects_terminal = payload["outcome"] not in {
            "unknown",
            "not-applicable",
        }
        corrects_requirement = (
            payload["requirement_id"] is not None
            and payload["requirement_status"] not in {"unknown", "not-applicable"}
        )
        if corrects_terminal == corrects_requirement:
            raise ContractValidationError(
                "correction must replace exactly one terminal or requirement state"
            )
        if payload["verification"] in {"unknown", "not-applicable"}:
            raise ContractValidationError("correction requires explicit verification")
    elif (
        correction["event_id"] is not None
        or correction["provenance"] != "not-applicable"
    ):
        raise ContractValidationError(
            "correction metadata is valid only on correction"
        )

    carries_requirement_evidence = event == "requirement.status" or (
        event == "correction"
        and payload["requirement_id"] is not None
        and payload["requirement_status"] not in {"unknown", "not-applicable"}
    )
    if carries_requirement_evidence:
        if evidence["refs"] and evidence["provenance"] in {
            "unknown",
            "not-applicable",
        }:
            raise ContractValidationError(
                "requirement evidence references require explicit provenance"
            )
    elif evidence["refs"]:
        raise ContractValidationError(
            "evidence references are valid only on requirement status or correction"
        )

    if event not in {"task.terminal", "correction"}:
        if (
            task_metadata["acceptance_baseline_id"] is not None
            or task_metadata["approved_scope_change_ids"]
            or any(configuration[field] is not None for field in (
                "policy_version",
                "model_config_version",
                "runtime_config_version",
                "recorder_config_version",
            ))
        ):
            raise ContractValidationError(
                "terminal baseline, scope-change, and configuration metadata "
                "is valid only on task.terminal"
            )

    if event in {"task.terminal", "correction"} and payload["outcome"] == "complete":
        if task_metadata["acceptance_baseline_id"] is None or task_metadata[
            "acceptance_baseline_provenance"
        ] in {"unknown", "not-applicable"}:
            raise ContractValidationError(
                "a complete terminal requires an explicit acceptance baseline"
            )
        if task_metadata["scope_change_provenance"] in {
            "unknown",
            "not-applicable",
        }:
            raise ContractValidationError(
                "a complete terminal requires an explicit approved scope-change set"
            )
        if task_metadata["task_kind_provenance"] in {
            "unknown",
            "not-applicable",
        }:
            raise ContractValidationError(
                "a complete terminal requires task-kind provenance"
            )
        if task_metadata["task_type"] in {"unknown", "not-applicable"} or task_metadata[
            "task_type_provenance"
        ] in {"unknown", "not-applicable"}:
            raise ContractValidationError(
                "a complete terminal requires an explicit task-type classification"
            )
        if task_metadata["scope_size"] in {"unknown", "not-applicable"} or task_metadata[
            "scope_size_provenance"
        ] in {"unknown", "not-applicable"}:
            raise ContractValidationError(
                "a complete terminal requires an explicit scope-size classification"
            )
        if task_metadata["method"] in {"unknown", "not-applicable"} or task_metadata[
            "method_provenance"
        ] in {"unknown", "not-applicable"}:
            raise ContractValidationError(
                "a complete terminal requires an explicit method classification"
            )


def adapter_versions_are_current(observation: Mapping[str, Any]) -> bool:
    """Small helper for installation diagnostics; older data remains valid."""

    return (
        observation.get("adapter", {}).get("version") == ADAPTER_VERSION
        and RECORDER_VERSION == "0.2.9"
    )
