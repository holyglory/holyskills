"""Privacy-first Codex event translators for the delivery-efficiency recorder.

This module is deliberately storage-free.  Each translator returns ``(event,
source_key)`` pairs.  ``event`` is a small, normalized observation and
``source_key`` is a duplicate-stable opaque digest.  A recorder sink consumes
the pair as ``sink.record(event, source_key=source_key)``.

Raw runtime identifiers cross this boundary only in the transient
``source_identity`` object, which may use one authenticated local loopback
handoff.  The shared recorder must HMAC those values with its
installation-local key and remove ``source_identity`` before persistence.
No prompt, response, transcript path, working directory, filename, source
content, tool argument/result, command, raw error, account, or email field is
copied into an observation or source key.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from . import ADAPTER_VERSION


MAX_SOURCE_BYTES = 1_048_576
_MAX_TREE_DEPTH = 16
_MAX_TREE_NODES = 16_384

_SURFACES = {"cli-interactive", "cli-exec", "desktop", "ide", "unknown"}
_PHASES = {
    "planning",
    "implementation",
    "testing",
    "deployment",
    "reporting",
    "unattributed",
}
_ACTIVITY_STATES = {
    "model-active",
    "tool-active",
    "external-wait",
    "user-wait",
    "blocked-wait",
    "unattributed",
}
_PROVENANCE = {
    "runtime-observed",
    "agent-declared",
    "inferred",
    "unknown",
    "not-applicable",
}
_OUTCOMES = {
    "complete",
    "incomplete",
    "blocked",
    "cancelled",
    "superseded",
    "interrupted",
}
_TASK_KINDS = {
    "primary",
    "continuation",
    "retry",
    "rollback",
    "defect-repair",
    "rework",
    "unknown",
}
_CAUSES = {
    "agent-caused-mistake",
    "changed-user-intent",
    "new-scope",
    "external-cause",
    "not-applicable",
    "unknown",
}
_VERIFICATION = {
    "verified",
    "partially-verified",
    "unverified",
    "not-applicable",
    "unknown",
}
_EXPLICIT_REQUIREMENT_STATUSES = {"satisfied", "partial", "blocked", "removed"}
_REQUIREMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_REFERENCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,127}$")
_SAFE_CONFIG_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+:-]{0,63}$")
_RUNTIME_TARGET = re.compile(r"^target_v1_[0-9a-f]{32}$")
_MAX_DECLARED_REFERENCES = 32
_SCOPE_SIZES = {
    "small",
    "medium",
    "large",
    "extra-large",
    "not-applicable",
    "unknown",
}
_METHODS = {
    "direct",
    "delegated",
    "hybrid",
    "automated",
    "not-applicable",
    "unknown",
}
_TASK_TYPES = {
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

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_SAFE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
_SAFE_OTLP_ID = re.compile(r"^[0-9A-Fa-f]{16,64}$")

Observation = Dict[str, Any]
Emission = Tuple[Observation, str]


class SourceEventError(ValueError):
    """A source event cannot safely cross the adapter boundary."""


class MalformedSourceEvent(SourceEventError):
    """A source event has an invalid shape or required field."""


class OversizedSourceEvent(SourceEventError):
    """A source event exceeds the adapter's bounded input size."""


def _load_source(source: Any, max_bytes: int = MAX_SOURCE_BYTES) -> Dict[str, Any]:
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")

    if isinstance(source, bytes):
        if len(source) > max_bytes:
            raise OversizedSourceEvent("source event exceeds the byte limit")
        try:
            text = source.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MalformedSourceEvent("source event is not UTF-8") from exc
        value = _parse_json(text)
    elif isinstance(source, str):
        if len(source.encode("utf-8")) > max_bytes:
            raise OversizedSourceEvent("source event exceeds the byte limit")
        value = _parse_json(source)
    elif type(source) is dict:
        value = source
    else:
        raise MalformedSourceEvent("source event must be a JSON object")

    if type(value) is not dict:
        raise MalformedSourceEvent("source event must be a JSON object")
    _validate_json_tree(value, max_bytes)
    return value


def _parse_json(text: str) -> Any:
    def reject_constant(_: str) -> None:
        raise ValueError("non-finite JSON number")

    try:
        return json.loads(text, parse_constant=reject_constant)
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise MalformedSourceEvent("source event is not valid bounded JSON") from exc


def _validate_json_tree(value: Any, max_bytes: int) -> None:
    nodes = 0

    def walk(item: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > _MAX_TREE_NODES or depth > _MAX_TREE_DEPTH:
            raise OversizedSourceEvent("source event exceeds structural limits")
        if item is None or isinstance(item, (bool, str)):
            if isinstance(item, str) and len(item.encode("utf-8")) > max_bytes:
                raise OversizedSourceEvent("source string exceeds the byte limit")
            return
        if isinstance(item, int) and not isinstance(item, bool):
            if len(str(abs(item))) > 64:
                raise MalformedSourceEvent("source integer is outside the accepted range")
            return
        if isinstance(item, float):
            if not math.isfinite(item):
                raise MalformedSourceEvent("source number must be finite")
            return
        if type(item) is list:
            for child in item:
                walk(child, depth + 1)
            return
        if type(item) is dict:
            for key, child in item.items():
                if not isinstance(key, str):
                    raise MalformedSourceEvent("source object keys must be strings")
                walk(key, depth + 1)
                walk(child, depth + 1)
            return
        raise MalformedSourceEvent("source event contains a non-JSON value")

    walk(value, 0)
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise MalformedSourceEvent("source event is not serializable JSON") from exc
    if len(encoded) > max_bytes:
        raise OversizedSourceEvent("source event exceeds the byte limit")


def _safe_identifier(value: Any, *, required: bool = False) -> Optional[str]:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not _SAFE_IDENTIFIER.fullmatch(value):
        if required:
            raise MalformedSourceEvent("required runtime identifier is invalid")
        return None
    return value


def _safe_version(value: Any) -> Optional[str]:
    if isinstance(value, str) and _SAFE_VERSION.fullmatch(value):
        return value
    return None


def _declared_reference(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _REFERENCE_ID.fullmatch(value):
        raise MalformedSourceEvent("{} is invalid".format(label))
    return value


def _declared_reference_list(value: Any, label: str) -> List[str]:
    if type(value) is not list or len(value) > _MAX_DECLARED_REFERENCES:
        raise MalformedSourceEvent("{} must be a bounded list".format(label))
    result: List[str] = []
    seen: Set[str] = set()
    for raw_reference in value:
        reference = _declared_reference(raw_reference, label)
        if reference in seen:
            raise MalformedSourceEvent("{} must contain unique values".format(label))
        seen.add(reference)
        result.append(reference)
    return result


def _declared_config_version(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_CONFIG_VERSION.fullmatch(value):
        raise MalformedSourceEvent("{} is invalid".format(label))
    return value


def _surface(value: str) -> str:
    return value if value in _SURFACES else "unknown"


def _source_key(domain: str, *parts: Any) -> str:
    # Only callers selecting already-allowlisted identifiers, enums, counters,
    # and timestamps may call this helper.  Content-bearing fields never do.
    canonical = json.dumps(
        [domain] + list(parts),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=False,
    ).encode("ascii")
    return "%s:%s" % (domain, hashlib.sha256(canonical).hexdigest())


def _identity(
    *,
    lineage: Optional[str] = None,
    task: Optional[str] = None,
    project: Optional[str] = None,
    revision: Optional[str] = None,
    session: Optional[str] = None,
    turn: Optional[str] = None,
    agent: Optional[str] = None,
    span: Optional[str] = None,
    target: Optional[str] = None,
) -> Dict[str, Optional[str]]:
    return {
        "lineage": lineage,
        "task": task,
        "project": project,
        "revision": revision,
        "session": session,
        "turn": turn,
        "agent": agent,
        "span": span,
        "target": target,
    }


def _classification(
    phase: str,
    phase_provenance: str,
    activity_state: str,
    activity_provenance: str,
) -> Dict[str, str]:
    if phase not in _PHASES or activity_state not in _ACTIVITY_STATES:
        raise AssertionError("adapter classification constant is invalid")
    if phase_provenance not in _PROVENANCE or activity_provenance not in _PROVENANCE:
        raise AssertionError("adapter provenance constant is invalid")
    return {
        "phase": phase,
        "phase_provenance": phase_provenance,
        "activity_state": activity_state,
        "activity_provenance": activity_provenance,
        "classifier_version": "codex-v1",
    }


def _tokens(**updates: Optional[str]) -> Dict[str, Optional[str]]:
    result: Dict[str, Optional[str]] = {
        "input": None,
        "cached_input": None,
        "output": None,
        "reasoning_output": None,
        "tool": None,
        "other": None,
    }
    result.update(updates)
    return result


def _measurement(
    *,
    provenance: str = "runtime-observed",
    counter_source: str = "not-applicable",
    tokens: Optional[Dict[str, Optional[str]]] = None,
) -> Dict[str, Any]:
    return {
        "provenance": provenance,
        "counter_source": counter_source,
        "tokens": tokens if tokens is not None else _tokens(),
        "recorder_overhead_ns": None,
    }


def _coverage(**updates: str) -> Dict[str, str]:
    result = {
        "request_receipt": "unknown",
        "first_activity": "unknown",
        "tokens": "unknown",
        "tools": "unknown",
        "subagents": "unknown",
        "terminal_delivery": "unknown",
        "scope": "unknown",
        "verification": "unknown",
    }
    result.update(updates)
    return result


def _payload(
    source_event: str,
    *,
    success: Optional[bool] = None,
    tool_category: str = "not-applicable",
    outcome: str = "not-applicable",
    task_kind: str = "unknown",
    cause: str = "not-applicable",
    requirement_id: Optional[str] = None,
    requirement_status: str = "not-applicable",
    verification: str = "not-applicable",
    gap_code: str = "none",
    link: Optional[Dict[str, Any]] = None,
    task_metadata: Optional[Dict[str, Any]] = None,
    evidence: Optional[Dict[str, Any]] = None,
    configuration: Optional[Dict[str, Any]] = None,
    correction: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    normalized_link = {
        "task_id": None,
        "lineage_id": None,
        "provenance": "not-applicable",
    }
    if link is not None:
        normalized_link.update(link)

    normalized_task_metadata = {
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
    }
    if task_metadata is not None:
        normalized_task_metadata.update(task_metadata)
    normalized_task_metadata["approved_scope_change_ids"] = list(
        normalized_task_metadata["approved_scope_change_ids"]
    )

    normalized_evidence = {"refs": [], "provenance": "unknown"}
    if evidence is not None:
        normalized_evidence.update(evidence)
    normalized_evidence["refs"] = list(normalized_evidence["refs"])

    normalized_configuration = {
        "policy_version": None,
        "policy_provenance": "unknown",
        "model_config_version": None,
        "model_config_provenance": "unknown",
        "runtime_config_version": None,
        "runtime_config_provenance": "unknown",
        "recorder_config_version": None,
        "recorder_config_provenance": "unknown",
    }
    if configuration is not None:
        normalized_configuration.update(configuration)

    normalized_correction = {
        "event_id": None,
        "provenance": "not-applicable",
    }
    if correction is not None:
        normalized_correction.update(correction)

    return {
        "source_event": source_event,
        "span_id": None,
        "parent_span_id": None,
        "duration_ns": None,
        "success": success,
        "tool_category": tool_category,
        "outcome": outcome,
        "task_kind": task_kind,
        "cause": cause,
        "requirement_id": requirement_id,
        "requirement_status": requirement_status,
        "verification": verification,
        "gap_code": gap_code,
        "link": normalized_link,
        "task_metadata": normalized_task_metadata,
        "evidence": normalized_evidence,
        "configuration": normalized_configuration,
        "correction": normalized_correction,
    }


def _observation(
    *,
    adapter: str,
    surface: str,
    runtime_version: Optional[str],
    source_identity: Dict[str, Optional[str]],
    classification: Dict[str, str],
    measurement: Dict[str, Any],
    coverage: Dict[str, str],
    event: str,
    payload: Dict[str, Any],
) -> Observation:
    return {
        "runtime": {
            "family": "codex",
            "surface": _surface(surface),
            "version": _safe_version(runtime_version),
        },
        "adapter": {"name": adapter, "version": ADAPTER_VERSION},
        "source_identity": source_identity,
        "classification": classification,
        "measurement": measurement,
        "coverage": coverage,
        "event": event,
        "payload": payload,
    }


def _hook_coverage(**updates: str) -> Dict[str, str]:
    values = {
        "request_receipt": "partial",
        "first_activity": "partial",
        "tokens": "unknown",
        "tools": "partial",
        "subagents": "partial",
        "terminal_delivery": "partial",
        "scope": "unknown",
        "verification": "unknown",
    }
    values.update(updates)
    return _coverage(**values)


def _tool_category(tool_name: Any) -> str:
    if not isinstance(tool_name, str) or not tool_name or len(tool_name) > 256:
        return "unknown"
    name = tool_name.casefold().replace("-", "_").replace(".", "_").replace("/", "_")
    if name in {"bash", "shell", "powershell", "cmd", "exec", "exec_command", "write_stdin"}:
        return "shell"
    if name in {"apply_patch", "patch", "edit", "write", "multiedit"}:
        return "patch"
    if name.startswith("mcp_") or name.startswith("mcp__"):
        return "mcp"
    if name.startswith("web_") or name in {"websearch", "webfetch", "search", "browser"}:
        return "web"
    if (
        name.startswith("collaboration_")
        or name in {"task", "spawn_agent", "send_message", "followup_task", "wait_agent"}
        or "subagent" in name
    ):
        return "agent"
    if name in {
        "read",
        "grep",
        "rg",
        "glob",
        "ls",
        "list",
        "find",
        "view_image",
        "read_file",
    }:
        return "local"
    return "other"


_HOOK_EVENTS = {
    "SessionStart": "session_start",
    "SessionEnd": "session_end",
    "UserPromptSubmit": "prompt_submit",
    "PreToolUse": "pre_tool",
    "PostToolUse": "post_tool",
    "SubagentStart": "subagent_start",
    "SubagentStop": "subagent_stop",
    "Stop": "turn_stop",
}


def translate_hook(
    source: Any,
    *,
    event_name: Optional[str] = None,
    surface: str = "unknown",
    runtime_version: Optional[str] = None,
    runtime_target: Optional[str] = None,
    max_bytes: int = MAX_SOURCE_BYTES,
) -> List[Emission]:
    """Translate one Codex hook JSON object into allowlisted observations.

    ``SessionStart`` is recognized but does not create a task.  In particular,
    a ``source=compact`` start is a continuation of the current task.
    ``SessionEnd`` emits only a terminal-coverage gap.  ``Stop`` emits
    ``runtime.turn_stopped`` and never ``task.terminal``.
    """

    if runtime_target is not None and (
        not isinstance(runtime_target, str)
        or _RUNTIME_TARGET.fullmatch(runtime_target) is None
    ):
        raise MalformedSourceEvent("runtime target is not an installer-assigned opaque reference")
    data = _load_source(source, max_bytes)
    payload_event = data.get("hook_event_name")
    if event_name is None:
        event_name = payload_event
    elif payload_event is not None and payload_event != event_name:
        raise MalformedSourceEvent("hook event name does not match the invocation")
    if event_name not in _HOOK_EVENTS:
        raise MalformedSourceEvent("unsupported hook event")

    source_event = _HOOK_EVENTS[event_name]
    session = _safe_identifier(data.get("session_id"), required=True)
    turn = _safe_identifier(data.get("turn_id"))
    version = _safe_version(runtime_version if runtime_version is not None else data.get("version"))

    def hook_source_key(domain: str, *parts: Any) -> str:
        return _source_key(domain, runtime_target, *parts)

    if event_name == "SessionStart":
        # Startup is a session boundary, not request receipt.  Compaction is
        # explicitly a continuation and must never create a new task.
        return []

    if event_name == "SessionEnd":
        identity = _identity(lineage=session, session=session, target=runtime_target)
        observation = _observation(
            adapter="codex-hooks",
            surface=surface,
            runtime_version=version,
            source_identity=identity,
            classification=_classification(
                "reporting", "inferred", "unattributed", "unknown"
            ),
            measurement=_measurement(),
            coverage=_hook_coverage(terminal_delivery="partial"),
            event="coverage.gap",
            payload=_payload(
                source_event,
                gap_code="host-boundary-unavailable",
            ),
        )
        return [(observation, hook_source_key("codex-hook", session, source_event))]

    if turn is None:
        raise MalformedSourceEvent("turn hook is missing a valid turn identifier")
    identity = _identity(
        lineage=session,
        task=turn,
        session=session,
        turn=turn,
        target=runtime_target,
    )

    if event_name == "UserPromptSubmit":
        observation = _observation(
            adapter="codex-hooks",
            surface=surface,
            runtime_version=version,
            source_identity=identity,
            classification=_classification(
                "planning", "inferred", "unattributed", "unknown"
            ),
            measurement=_measurement(),
            coverage=_hook_coverage(request_receipt="partial"),
            event="task.start",
            payload=_payload(source_event, task_kind="primary"),
        )
        return [(observation, hook_source_key("codex-hook", session, turn, source_event))]

    if event_name in {"PreToolUse", "PostToolUse"}:
        tool_use_id = _safe_identifier(data.get("tool_use_id"), required=True)
        category = _tool_category(data.get("tool_name"))
        tool_identity = _identity(
            lineage=session,
            task=turn,
            session=session,
            turn=turn,
            span=tool_use_id,
            target=runtime_target,
        )
        activity = _classification(
            "unattributed", "unknown", "tool-active", "runtime-observed"
        )
        emissions: List[Emission] = []
        if event_name == "PreToolUse":
            # Every candidate in the task produces the same normalized first-
            # activity observation and source key.  The recorder therefore
            # retains the earliest arrival without a dedupe conflict even when
            # later tools use a different category.
            first = _observation(
                adapter="codex-hooks",
                surface=surface,
                runtime_version=version,
                source_identity=identity,
                classification=_classification(
                    "unattributed", "unknown", "unattributed", "unknown"
                ),
                measurement=_measurement(),
                coverage=_hook_coverage(first_activity="partial"),
                event="task.first_activity",
                payload=_payload("unknown", tool_category="unknown"),
            )
            emissions.append(
                (first, hook_source_key("codex-first-activity", session, turn))
            )
        span = _observation(
            adapter="codex-hooks",
            surface=surface,
            runtime_version=version,
            source_identity=tool_identity,
            classification=activity,
            measurement=_measurement(),
            coverage=_hook_coverage(),
            event="span.start" if event_name == "PreToolUse" else "span.end",
            payload=_payload(source_event, tool_category=category),
        )
        emissions.append(
            (
                span,
                hook_source_key("codex-hook", session, turn, source_event, tool_use_id),
            )
        )
        return emissions

    if event_name in {"SubagentStart", "SubagentStop"}:
        agent = _safe_identifier(data.get("agent_id"), required=True)
        agent_identity = _identity(
            lineage=session,
            task=turn,
            session=session,
            turn=turn,
            agent=agent,
            span=agent,
            target=runtime_target,
        )
        activity = _classification(
            "unattributed", "unknown", "model-active", "runtime-observed"
        )
        emissions = []
        if event_name == "SubagentStart":
            first = _observation(
                adapter="codex-hooks",
                surface=surface,
                runtime_version=version,
                source_identity=identity,
                classification=_classification(
                    "unattributed", "unknown", "unattributed", "unknown"
                ),
                measurement=_measurement(),
                coverage=_hook_coverage(first_activity="partial"),
                event="task.first_activity",
                payload=_payload("unknown", tool_category="unknown"),
            )
            emissions.append(
                (first, hook_source_key("codex-first-activity", session, turn))
            )
        span = _observation(
            adapter="codex-hooks",
            surface=surface,
            runtime_version=version,
            source_identity=agent_identity,
            classification=activity,
            measurement=_measurement(),
            coverage=_hook_coverage(),
            event="span.start" if event_name == "SubagentStart" else "span.end",
            payload=_payload(source_event, tool_category="agent"),
        )
        emissions.append(
            (
                span,
                hook_source_key("codex-hook", session, turn, source_event, agent),
            )
        )
        return emissions

    if event_name == "Stop":
        observation = _observation(
            adapter="codex-hooks",
            surface=surface,
            runtime_version=version,
            source_identity=identity,
            classification=_classification(
                "reporting", "inferred", "unattributed", "unknown"
            ),
            measurement=_measurement(),
            coverage=_hook_coverage(terminal_delivery="partial"),
            event="runtime.turn_stopped",
            payload=_payload(source_event),
        )
        return [(observation, hook_source_key("codex-hook", session, turn, source_event))]

    raise AssertionError("recognized hook event was not translated")


_OTLP_ALLOWED_ATTRIBUTES = {
    "event.name",
    "event_name",
    "name",
    "event.kind",
    "event_kind",
    "kind",
    "conversation.id",
    "conversation_id",
    "session.id",
    "turn.id",
    "turn_id",
    "app.version",
    "service.version",
    "originator",
    "success",
    "input_token_count",
    "input_tokens",
    "cached_input_token_count",
    "cached_token_count",
    "cached_input_tokens",
    "output_token_count",
    "output_tokens",
    "reasoning_output_token_count",
    "reasoning_token_count",
    "reasoning_output_tokens",
    "tool_token_count",
    "tool_tokens",
}


def _otlp_scalar(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if type(value) is not dict or len(value) != 1:
        return None
    key, wrapped = next(iter(value.items()))
    if key in {"stringValue", "intValue", "doubleValue", "boolValue"}:
        if isinstance(wrapped, (str, int, float, bool)) and not (
            isinstance(wrapped, float) and not math.isfinite(wrapped)
        ):
            return wrapped
    return None


def _otlp_attributes(node: Any, allowed: Optional[Set[str]] = None) -> Dict[str, Any]:
    permitted = _OTLP_ALLOWED_ATTRIBUTES if allowed is None else allowed
    if type(node) is not dict:
        return {}
    raw = node.get("attributes")
    result: Dict[str, Any] = {}
    if type(raw) is dict:
        for key in permitted:
            if key in raw:
                result[key] = _otlp_scalar(raw[key])
        return result
    if type(raw) is not list:
        return result
    for entry in raw:
        if type(entry) is not dict:
            continue
        key = entry.get("key")
        if key not in permitted:
            continue
        result[key] = _otlp_scalar(entry.get("value"))
    return result


def _otlp_body_attributes(
    body: Any,
    allowed: Optional[Set[str]] = None,
    body_event_names: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    if type(body) is not dict:
        return {}
    names = {"codex.sse_event"} if body_event_names is None else body_event_names
    if body.get("stringValue") in names:
        return {"event.name": body["stringValue"]}
    kvlist = body.get("kvlistValue")
    if type(kvlist) is not dict or type(kvlist.get("values")) is not list:
        return {}
    return _otlp_attributes({"attributes": kvlist["values"]}, allowed)


def _first_present(mapping: Dict[str, Any], names: Sequence[str]) -> Any:
    for name in names:
        if name in mapping:
            return mapping[name]
    return None


def _counter(mapping: Dict[str, Any], names: Sequence[str]) -> Optional[str]:
    value = _first_present(mapping, names)
    if value is None:
        return None
    if isinstance(value, bool):
        raise MalformedSourceEvent("token counter must be a non-negative integer")
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]{0,29}", value):
        number = int(value)
    else:
        raise MalformedSourceEvent("token counter must be a non-negative integer")
    if number < 0 or len(str(number)) > 30:
        raise MalformedSourceEvent("token counter must be a non-negative integer")
    return str(number)


def _known_otlp_surface(value: Any, fallback: str) -> str:
    known = {
        "codex_cli_rs": "cli-interactive",
        "codex-cli": "cli-interactive",
        "codex_exec": "cli-exec",
        "codex-exec": "cli-exec",
        "codex_desktop": "desktop",
        "codex-desktop": "desktop",
        "codex_vscode": "ide",
        "codex-ide": "ide",
    }
    return known.get(value, _surface(fallback))


def _iter_otlp_records(data: Dict[str, Any]) -> Iterable[Tuple[Dict[str, Any], int]]:
    resource_logs = data.get("resourceLogs")
    if type(resource_logs) is not list:
        raise MalformedSourceEvent("OTLP JSON is missing resourceLogs")
    sequence = 0
    for resource_log in resource_logs:
        if type(resource_log) is not dict:
            raise MalformedSourceEvent("OTLP resource log must be an object")
        resource_attrs = _otlp_attributes(resource_log.get("resource"))
        scope_logs = resource_log.get("scopeLogs")
        if scope_logs is None:
            scope_logs = resource_log.get("instrumentationLibraryLogs")
        if type(scope_logs) is not list:
            raise MalformedSourceEvent("OTLP resource log is missing scopeLogs")
        for scope_log in scope_logs:
            if type(scope_log) is not dict or type(scope_log.get("logRecords")) is not list:
                raise MalformedSourceEvent("OTLP scope log is malformed")
            for record in scope_log["logRecords"]:
                if type(record) is not dict:
                    raise MalformedSourceEvent("OTLP log record must be an object")
                attrs = dict(resource_attrs)
                attrs.update(_otlp_body_attributes(record.get("body")))
                attrs.update(_otlp_attributes(record))
                copied = {
                    "attributes": attrs,
                    "timeUnixNano": record.get("timeUnixNano"),
                    "observedTimeUnixNano": record.get("observedTimeUnixNano"),
                    "traceId": record.get("traceId"),
                    "spanId": record.get("spanId"),
                }
                yield copied, sequence
                sequence += 1


def translate_otlp(
    source: Any,
    *,
    surface: str = "unknown",
    runtime_version: Optional[str] = None,
    max_bytes: int = MAX_SOURCE_BYTES,
) -> List[Emission]:
    """Translate relevant Codex OTLP/HTTP JSON response-completion logs.

    Prompt and tool-result event classes are ignored wholesale.  Only
    ``codex.sse_event`` records whose kind is ``response.completed`` and their
    provider-native token counters cross the adapter boundary.
    """

    data = _load_source(source, max_bytes)
    emissions: List[Emission] = []
    for record, _record_index in _iter_otlp_records(data):
        attrs = record["attributes"]
        event_name = _first_present(attrs, ("event.name", "event_name", "name"))
        event_kind = _first_present(attrs, ("event.kind", "event_kind", "kind"))
        if event_name != "codex.sse_event" or event_kind != "response.completed":
            continue

        token_values = _tokens(
            input=_counter(attrs, ("input_token_count", "input_tokens")),
            cached_input=_counter(
                attrs,
                (
                    "cached_input_token_count",
                    "cached_token_count",
                    "cached_input_tokens",
                ),
            ),
            output=_counter(attrs, ("output_token_count", "output_tokens")),
            reasoning_output=_counter(
                attrs,
                (
                    "reasoning_output_token_count",
                    "reasoning_token_count",
                    "reasoning_output_tokens",
                ),
            ),
            tool=_counter(attrs, ("tool_token_count", "tool_tokens")),
        )
        if all(value is None for value in token_values.values()):
            continue

        session = _safe_identifier(
            _first_present(attrs, ("conversation.id", "conversation_id", "session.id"))
        )
        turn = _safe_identifier(_first_present(attrs, ("turn.id", "turn_id")))
        version = _safe_version(
            runtime_version
            if runtime_version is not None
            else _first_present(attrs, ("app.version", "service.version"))
        )
        chosen_surface = _known_otlp_surface(attrs.get("originator"), surface)
        identity = _identity(
            lineage=session,
            task=turn,
            session=session,
            turn=turn,
        )

        time_marker = record.get("timeUnixNano") or record.get("observedTimeUnixNano")
        if not (
            isinstance(time_marker, str)
            and re.fullmatch(r"0|[1-9][0-9]{0,31}", time_marker)
        ):
            raise MalformedSourceEvent("OTLP response completion lacks a valid timestamp")
        trace_marker = record.get("traceId")
        span_marker = record.get("spanId")
        if not (isinstance(trace_marker, str) and _SAFE_OTLP_ID.fullmatch(trace_marker)):
            trace_marker = None
        if not (isinstance(span_marker, str) and _SAFE_OTLP_ID.fullmatch(span_marker)):
            span_marker = None
        success_value = attrs.get("success")
        success = success_value if isinstance(success_value, bool) else None

        complete_native_counts = all(
            token_values[name] is not None
            for name in ("input", "cached_input", "output", "reasoning_output")
        )
        usage = _observation(
            adapter="codex-otel",
            surface=chosen_surface,
            runtime_version=version,
            source_identity=identity,
            classification=_classification(
                "unattributed", "unknown", "model-active", "inferred"
            ),
            measurement=_measurement(
                provenance="runtime-observed",
                counter_source="provider-native",
                tokens=token_values,
            ),
            coverage=_coverage(
                request_receipt="partial",
                first_activity="partial",
                tokens="complete" if complete_native_counts else "partial",
                tools="partial",
                subagents="partial",
                terminal_delivery="partial",
                scope="unknown",
                verification="unknown",
            ),
            event="usage.observed",
            payload=_payload("otel_response_completed", success=success),
        )
        usage_key = _source_key(
            "codex-otel",
            session,
            turn,
            time_marker,
            trace_marker,
            span_marker,
            token_values["input"],
            token_values["cached_input"],
            token_values["output"],
            token_values["reasoning_output"],
            token_values["tool"],
        )
        emissions.append((usage, usage_key))
    return emissions


_EXEC_ITEM_CATEGORIES = {
    "command_execution": "shell",
    "commandExecution": "shell",
    "file_change": "patch",
    "fileChange": "patch",
    "mcp_tool_call": "mcp",
    "mcpToolCall": "mcp",
    "dynamic_tool_call": "other",
    "dynamicToolCall": "other",
    "web_search": "web",
    "webSearch": "web",
}
_EXEC_MODEL_ITEMS = {"agent_message", "agentMessage", "reasoning", "plan"}


@dataclass
class CodexExecTranslator:
    """Stateful translator for one wrapped ``codex exec --json`` process."""

    invocation_id: str
    runtime_version: Optional[str] = None
    session_id: Optional[str] = None
    turn_id: Optional[str] = None
    max_bytes: int = MAX_SOURCE_BYTES

    def __post_init__(self) -> None:
        self.invocation_id = _safe_identifier(self.invocation_id, required=True)  # type: ignore[assignment]
        self.runtime_version = _safe_version(self.runtime_version)
        self.session_id = _safe_identifier(self.session_id)
        self.turn_id = _safe_identifier(self.turn_id)
        if isinstance(self.max_bytes, bool) or not isinstance(self.max_bytes, int) or self.max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")
        self._receipt_emitted = False
        self._first_activity_emitted = False
        self._runtime_terminal_emitted = False

    def _identity(self, *, span: Optional[str] = None) -> Dict[str, Optional[str]]:
        return _identity(
            lineage=self.invocation_id,
            task=self.invocation_id,
            session=self.session_id,
            turn=self.turn_id,
            span=span,
        )

    def receipt(self) -> List[Emission]:
        """Record wrapper receipt before starting the Codex child process."""

        if self._receipt_emitted:
            return []
        self._receipt_emitted = True
        observation = _observation(
            adapter="codex-exec",
            surface="cli-exec",
            runtime_version=self.runtime_version,
            source_identity=self._identity(),
            classification=_classification(
                "planning", "inferred", "unattributed", "unknown"
            ),
            measurement=_measurement(),
            coverage=_coverage(
                request_receipt="complete",
                first_activity="partial",
                tokens="partial",
                tools="partial",
                subagents="partial",
                terminal_delivery="partial",
                scope="unknown",
                verification="unknown",
            ),
            event="task.start",
            payload=_payload("exec_process", task_kind="primary"),
        )
        return [
            (
                observation,
                _source_key("codex-exec", self.invocation_id, "process-receipt"),
            )
        ]

    def _first_activity(
        self, *, activity_state: str, tool_category: str = "not-applicable"
    ) -> List[Emission]:
        if self._first_activity_emitted:
            return []
        self._first_activity_emitted = True
        observation = _observation(
            adapter="codex-exec",
            surface="cli-exec",
            runtime_version=self.runtime_version,
            source_identity=self._identity(),
            classification=_classification(
                "unattributed", "unknown", activity_state, "runtime-observed"
            ),
            measurement=_measurement(),
            coverage=_coverage(
                request_receipt="complete",
                first_activity="partial",
                tokens="partial",
                tools="partial",
                subagents="partial",
                terminal_delivery="partial",
                scope="unknown",
                verification="unknown",
            ),
            event="task.first_activity",
            payload=_payload("exec_turn", tool_category=tool_category),
        )
        return [
            (
                observation,
                _source_key("codex-first-activity", self.invocation_id),
            )
        ]

    def translate(self, source: Any) -> List[Emission]:
        """Translate one JSONL event without retaining content-bearing fields."""

        data = _load_source(source, self.max_bytes)
        event_type = data.get("type")
        if not isinstance(event_type, str) or len(event_type) > 64:
            raise MalformedSourceEvent("exec event type is missing or invalid")

        if event_type == "thread.started":
            self.session_id = _safe_identifier(data.get("thread_id"), required=True)
            return []

        event_turn = _safe_identifier(data.get("turn_id"))
        if event_turn is not None:
            self.turn_id = event_turn

        if event_type == "turn.started":
            return self._first_activity(activity_state="model-active")

        if event_type in {"item.started", "item.completed"}:
            item = data.get("item")
            if type(item) is not dict:
                raise MalformedSourceEvent("exec item event is missing its item object")
            item_type = item.get("type")
            if not isinstance(item_type, str) or len(item_type) > 64:
                raise MalformedSourceEvent("exec item type is missing or invalid")
            if item_type in _EXEC_MODEL_ITEMS:
                return self._first_activity(activity_state="model-active")
            category = _EXEC_ITEM_CATEGORIES.get(item_type)
            if category is None:
                return []
            item_id = _safe_identifier(item.get("id"), required=True)
            emissions = self._first_activity(
                activity_state="tool-active", tool_category=category
            )
            status = item.get("status")
            success: Optional[bool] = None
            if isinstance(status, str) and status == "completed":
                success = True
            elif isinstance(status, str) and status in {"failed", "declined"}:
                success = False
            observation = _observation(
                adapter="codex-exec",
                surface="cli-exec",
                runtime_version=self.runtime_version,
                source_identity=self._identity(span=item_id),
                classification=_classification(
                    "unattributed", "unknown", "tool-active", "runtime-observed"
                ),
                measurement=_measurement(),
                coverage=_coverage(
                    request_receipt="complete",
                    first_activity="partial",
                    tokens="partial",
                    tools="partial",
                    subagents="partial",
                    terminal_delivery="partial",
                    scope="unknown",
                    verification="unknown",
                ),
                event="span.start" if event_type == "item.started" else "span.end",
                payload=_payload(
                    "exec_turn", success=success, tool_category=category
                ),
            )
            emissions.append(
                (
                    observation,
                    _source_key(
                        "codex-exec", self.invocation_id, event_type, item_id
                    ),
                )
            )
            return emissions

        if event_type in {"turn.completed", "turn.failed", "turn.interrupted"}:
            emissions = self._first_activity(activity_state="model-active")
            usage = data.get("usage")
            if usage is not None:
                if type(usage) is not dict:
                    raise MalformedSourceEvent("exec usage must be an object")
                token_values = _tokens(
                    input=_counter(usage, ("input_tokens", "input_token_count")),
                    cached_input=_counter(
                        usage,
                        ("cached_input_tokens", "cached_input_token_count"),
                    ),
                    output=_counter(usage, ("output_tokens", "output_token_count")),
                    reasoning_output=_counter(
                        usage,
                        (
                            "reasoning_output_tokens",
                            "reasoning_output_token_count",
                        ),
                    ),
                    tool=_counter(usage, ("tool_tokens", "tool_token_count")),
                )
                if any(value is not None for value in token_values.values()):
                    native_complete = all(
                        token_values[name] is not None
                        for name in (
                            "input",
                            "cached_input",
                            "output",
                            "reasoning_output",
                        )
                    )
                    usage_observation = _observation(
                        adapter="codex-exec",
                        surface="cli-exec",
                        runtime_version=self.runtime_version,
                        source_identity=self._identity(),
                        classification=_classification(
                            "unattributed", "unknown", "model-active", "inferred"
                        ),
                        measurement=_measurement(
                            provenance="runtime-observed",
                            counter_source="runtime-native",
                            tokens=token_values,
                        ),
                        coverage=_coverage(
                            request_receipt="complete",
                            first_activity="partial",
                            tokens="complete" if native_complete else "partial",
                            tools="partial",
                            subagents="partial",
                            terminal_delivery="partial",
                            scope="unknown",
                            verification="unknown",
                        ),
                        event="usage.observed",
                        payload=_payload("exec_turn"),
                    )
                    emissions.append(
                        (
                            usage_observation,
                            _source_key(
                                "codex-exec",
                                self.invocation_id,
                                event_type,
                                "usage",
                                token_values["input"],
                                token_values["cached_input"],
                                token_values["output"],
                                token_values["reasoning_output"],
                                token_values["tool"],
                            ),
                        )
                    )
            stopped = _observation(
                adapter="codex-exec",
                surface="cli-exec",
                runtime_version=self.runtime_version,
                source_identity=self._identity(),
                classification=_classification(
                    "reporting", "inferred", "unattributed", "unknown"
                ),
                measurement=_measurement(),
                coverage=_coverage(
                    request_receipt="complete",
                    first_activity="partial",
                    tokens="partial",
                    tools="partial",
                    subagents="partial",
                    terminal_delivery="partial",
                    scope="unknown",
                    verification="unknown",
                ),
                event="runtime.turn_stopped",
                payload=_payload(
                    "exec_turn",
                    success=True if event_type == "turn.completed" else False,
                ),
            )
            emissions.append(
                (
                    stopped,
                    _source_key(
                        "codex-exec", self.invocation_id, event_type, "turn-boundary"
                    ),
                )
            )
            if event_type in {"turn.failed", "turn.interrupted"}:
                outcome = "incomplete" if event_type == "turn.failed" else "interrupted"
                if not self._runtime_terminal_emitted:
                    emissions.append(
                        self._runtime_terminal(
                            outcome, event_type, source_event="exec_turn"
                        )
                    )
            return emissions

        # Content-bearing item variants, errors, and future events are ignored.
        # Process exit or a later recognized runtime event supplies truthful
        # terminal state; an unknown event is never copied as a generic blob.
        return []

    def _runtime_terminal(
        self,
        outcome: str,
        marker: Any,
        *,
        source_event: str = "exec_process",
    ) -> Emission:
        self._runtime_terminal_emitted = True
        observation = _observation(
            adapter="codex-exec",
            surface="cli-exec",
            runtime_version=self.runtime_version,
            source_identity=self._identity(),
            classification=_classification(
                "reporting", "inferred", "unattributed", "unknown"
            ),
            measurement=_measurement(),
            coverage=_coverage(
                request_receipt="complete",
                first_activity="partial",
                tokens="partial",
                tools="partial",
                subagents="partial",
                terminal_delivery="complete",
                scope="unknown",
                verification="unknown",
            ),
            event="task.terminal",
            payload=_payload(
                source_event,
                success=False,
                outcome=outcome,
                task_kind="primary",
                cause="unknown",
                verification="unknown",
            ),
        )
        return (
            observation,
            _source_key("codex-exec", self.invocation_id, "terminal", marker, outcome),
        )

    def _declared_terminal(self, declaration: Any) -> List[Emission]:
        data = _load_source(declaration, self.max_bytes)
        outcome = data.get("outcome")
        verification = data.get("verification")
        task_kind = data.get("task_kind", "unknown")
        task_type = data.get("task_type", "unknown")
        scope_size = data.get("scope_size", "unknown")
        method = data.get("method", "unknown")
        cause = data.get("cause", "not-applicable")
        if outcome not in _OUTCOMES:
            raise MalformedSourceEvent("terminal declaration has an invalid outcome")
        if verification not in _VERIFICATION:
            raise MalformedSourceEvent("terminal declaration must state verification")
        if task_kind not in _TASK_KINDS or cause not in _CAUSES:
            raise MalformedSourceEvent("terminal declaration classification is invalid")
        if task_type not in _TASK_TYPES:
            raise MalformedSourceEvent("terminal declaration task_type is invalid")
        if scope_size not in _SCOPE_SIZES:
            raise MalformedSourceEvent("terminal declaration scope_size is invalid")
        if method not in _METHODS:
            raise MalformedSourceEvent("terminal declaration method is invalid")
        if outcome == "complete" and verification in {"unknown", "not-applicable"}:
            raise MalformedSourceEvent("complete requires explicit verification")

        acceptance_baseline_id: Optional[str] = None
        acceptance_baseline_provenance = "unknown"
        if "acceptance_baseline_id" in data:
            acceptance_baseline_id = _declared_reference(
                data["acceptance_baseline_id"],
                "terminal acceptance_baseline_id",
            )
            acceptance_baseline_provenance = "agent-declared"

        approved_scope_change_ids: List[str] = []
        scope_change_provenance = "unknown"
        if "approved_scope_change_ids" in data:
            approved_scope_change_ids = _declared_reference_list(
                data["approved_scope_change_ids"],
                "terminal approved_scope_change_ids",
            )
            scope_change_provenance = "agent-declared"

        task_kind_provenance = (
            "agent-declared" if "task_kind" in data else "unknown"
        )
        task_type_provenance = (
            "agent-declared" if "task_type" in data else "unknown"
        )
        scope_size_provenance = (
            "agent-declared" if "scope_size" in data else "unknown"
        )
        method_provenance = "agent-declared" if "method" in data else "unknown"

        configuration: Dict[str, Any] = {}
        for version_field, provenance_field in (
            ("policy_version", "policy_provenance"),
            ("model_config_version", "model_config_provenance"),
            ("runtime_config_version", "runtime_config_provenance"),
            ("recorder_config_version", "recorder_config_provenance"),
        ):
            if version_field in data:
                configuration[version_field] = _declared_config_version(
                    data[version_field], "terminal {}".format(version_field)
                )
                configuration[provenance_field] = "agent-declared"

        if outcome == "complete":
            if acceptance_baseline_id is None:
                raise MalformedSourceEvent(
                    "complete requires an explicit acceptance baseline"
                )
            if "approved_scope_change_ids" not in data:
                raise MalformedSourceEvent(
                    "complete requires an explicit approved scope-change list"
                )
            if task_kind_provenance != "agent-declared":
                raise MalformedSourceEvent(
                    "complete requires an explicit task_kind"
                )
            if task_type in {"unknown", "not-applicable"}:
                raise MalformedSourceEvent(
                    "complete requires an explicit task_type"
                )
            if scope_size in {"unknown", "not-applicable"}:
                raise MalformedSourceEvent(
                    "complete requires an explicit scope_size"
                )
            if method in {"unknown", "not-applicable"}:
                raise MalformedSourceEvent("complete requires an explicit method")

        if "requirements_resolved" in data:
            raise MalformedSourceEvent(
                "requirements_resolved is obsolete; declare each requirement"
            )
        raw_requirements = data.get("requirements")
        if raw_requirements is None:
            raw_requirements = []
        if type(raw_requirements) is not list:
            raise MalformedSourceEvent("terminal requirements must be a list")
        if outcome == "complete" and not raw_requirements:
            raise MalformedSourceEvent(
                "complete requires a nonempty explicit requirements list"
            )

        requirements: List[Tuple[str, str, str, Tuple[str, ...], str]] = []
        seen_ids = set()
        for raw_requirement in raw_requirements:
            if type(raw_requirement) is not dict:
                raise MalformedSourceEvent("each terminal requirement must be an object")
            requirement_id = raw_requirement.get("id")
            requirement_status = raw_requirement.get("status")
            requirement_verification = raw_requirement.get("verification")
            if not isinstance(requirement_id, str) or not _REQUIREMENT_ID.fullmatch(
                requirement_id
            ):
                raise MalformedSourceEvent("terminal requirement id is invalid")
            if requirement_id in seen_ids:
                raise MalformedSourceEvent("terminal requirement ids must be unique")
            seen_ids.add(requirement_id)
            if requirement_status not in _EXPLICIT_REQUIREMENT_STATUSES:
                raise MalformedSourceEvent("terminal requirement status is not explicit")
            if (
                requirement_verification not in _VERIFICATION
                or requirement_verification == "unknown"
            ):
                raise MalformedSourceEvent(
                    "terminal requirement verification is not explicit"
                )
            if requirement_verification == "not-applicable" and requirement_status != "removed":
                raise MalformedSourceEvent(
                    "verification may be not-applicable only for a removed requirement"
                )
            evidence_provenance = "unknown"
            evidence_refs: List[str] = []
            if "evidence_refs" in raw_requirement:
                evidence_refs = _declared_reference_list(
                    raw_requirement["evidence_refs"],
                    "terminal requirement evidence_refs",
                )
                evidence_provenance = "agent-declared"
            if (
                outcome == "complete"
                and requirement_status in {"satisfied", "removed"}
                and not evidence_refs
            ):
                raise MalformedSourceEvent(
                    "complete requires evidence for every satisfied or removed requirement"
                )
            requirements.append(
                (
                    requirement_id,
                    requirement_status,
                    requirement_verification,
                    tuple(evidence_refs),
                    evidence_provenance,
                )
            )

        if outcome == "complete" and any(
            status not in {"satisfied", "removed"}
            for _, status, _, _, _ in requirements
        ):
            raise MalformedSourceEvent(
                "complete cannot contain an unresolved requirement"
            )

        declared_classification = {
            "task_kind_provenance": task_kind_provenance,
            "task_type": task_type,
            "task_type_provenance": task_type_provenance,
            "scope_size": scope_size,
            "scope_size_provenance": scope_size_provenance,
            "method": method,
            "method_provenance": method_provenance,
        }
        terminal_task_metadata = dict(declared_classification)
        terminal_task_metadata.update(
            {
                "acceptance_baseline_id": acceptance_baseline_id,
                "acceptance_baseline_provenance": acceptance_baseline_provenance,
                "approved_scope_change_ids": approved_scope_change_ids,
                "scope_change_provenance": scope_change_provenance,
            }
        )

        emissions: List[Emission] = []
        for (
            requirement_id,
            requirement_status,
            requirement_verification,
            evidence_refs,
            evidence_provenance,
        ) in requirements:
            requirement = _observation(
                adapter="codex-exec",
                surface="cli-exec",
                runtime_version=self.runtime_version,
                source_identity=self._identity(),
                classification=_classification(
                    "reporting", "inferred", "unattributed", "unknown"
                ),
                measurement=_measurement(provenance="agent-declared"),
                coverage=_coverage(
                    request_receipt="complete",
                    first_activity="partial",
                    tokens="partial",
                    tools="partial",
                    subagents="partial",
                    terminal_delivery="partial",
                    scope="partial",
                    verification="complete",
                ),
                event="requirement.status",
                payload=_payload(
                    "agent_declaration",
                    task_kind=task_kind,
                    cause=cause,
                    requirement_id=requirement_id,
                    requirement_status=requirement_status,
                    verification=requirement_verification,
                    task_metadata=declared_classification,
                    evidence={
                        "refs": list(evidence_refs),
                        "provenance": evidence_provenance,
                    },
                ),
            )
            emissions.append(
                (
                    requirement,
                    _source_key(
                        "codex-exec",
                        self.invocation_id,
                        "requirement",
                        requirement_id,
                        requirement_status,
                        requirement_verification,
                        evidence_refs,
                        evidence_provenance,
                        declared_classification,
                    ),
                )
            )

        observation = _observation(
            adapter="codex-exec",
            surface="cli-exec",
            runtime_version=self.runtime_version,
            source_identity=self._identity(),
            classification=_classification(
                "reporting", "inferred", "unattributed", "unknown"
            ),
            measurement=_measurement(provenance="agent-declared"),
            coverage=_coverage(
                request_receipt="complete",
                first_activity="partial",
                tokens="partial",
                tools="partial",
                subagents="partial",
                terminal_delivery="complete",
                scope="complete" if outcome == "complete" else "partial",
                verification="complete",
            ),
            event="task.terminal",
            payload=_payload(
                "agent_declaration",
                success=outcome == "complete",
                outcome=outcome,
                task_kind=task_kind,
                cause=cause,
                verification=verification,
                task_metadata=terminal_task_metadata,
                configuration=configuration,
            ),
        )
        emissions.append(
            (
                observation,
                _source_key(
                    "codex-exec",
                    self.invocation_id,
                    "declared-terminal",
                    outcome,
                    task_kind,
                    cause,
                    verification,
                    requirements,
                    terminal_task_metadata,
                    configuration,
                ),
            )
        )
        return emissions

    def process_exit(
        self,
        exit_code: int,
        *,
        interrupted: bool = False,
        terminal_declaration: Optional[Any] = None,
    ) -> List[Emission]:
        """Translate process exit without equating exit zero with completion."""

        if isinstance(exit_code, bool) or not isinstance(exit_code, int):
            raise MalformedSourceEvent("process exit code must be an integer")
        if not isinstance(interrupted, bool):
            raise MalformedSourceEvent("interrupted must be boolean")
        stopped = _observation(
            adapter="codex-exec",
            surface="cli-exec",
            runtime_version=self.runtime_version,
            source_identity=self._identity(),
            classification=_classification(
                "reporting", "inferred", "unattributed", "unknown"
            ),
            measurement=_measurement(),
            coverage=_coverage(
                request_receipt="complete",
                first_activity="partial",
                tokens="partial",
                tools="partial",
                subagents="partial",
                terminal_delivery="partial",
                scope="unknown",
                verification="unknown",
            ),
            event="runtime.turn_stopped",
            payload=_payload("exec_process", success=exit_code == 0 and not interrupted),
        )
        emissions: List[Emission] = [
            (
                stopped,
                _source_key(
                    "codex-exec",
                    self.invocation_id,
                    "process-exit",
                    exit_code,
                    interrupted,
                ),
            )
        ]
        if terminal_declaration is not None:
            emissions.extend(self._declared_terminal(terminal_declaration))
        elif interrupted or exit_code != 0:
            if not self._runtime_terminal_emitted:
                emissions.append(
                    self._runtime_terminal(
                        "interrupted" if interrupted else "incomplete",
                        ("process-exit", exit_code, interrupted),
                    )
                )
        else:
            gap = _observation(
                adapter="codex-exec",
                surface="cli-exec",
                runtime_version=self.runtime_version,
                source_identity=self._identity(),
                classification=_classification(
                    "reporting", "inferred", "unattributed", "unknown"
                ),
                measurement=_measurement(),
                coverage=_coverage(
                    request_receipt="complete",
                    first_activity="partial",
                    tokens="partial",
                    tools="partial",
                    subagents="partial",
                    terminal_delivery="partial",
                    scope="unknown",
                    verification="unknown",
                ),
                event="coverage.gap",
                payload=_payload(
                    "exec_process", gap_code="host-boundary-unavailable"
                ),
            )
            emissions.append(
                (
                    gap,
                    _source_key(
                        "codex-exec",
                        self.invocation_id,
                        "successful-exit-not-terminal",
                    ),
                )
            )
        return emissions


def translate_exec_event(
    source: Any,
    *,
    invocation_id: str,
    session_id: Optional[str] = None,
    turn_id: Optional[str] = None,
    runtime_version: Optional[str] = None,
    max_bytes: int = MAX_SOURCE_BYTES,
) -> List[Emission]:
    """Stateless convenience wrapper for one exec JSON event."""

    translator = CodexExecTranslator(
        invocation_id=invocation_id,
        runtime_version=runtime_version,
        session_id=session_id,
        turn_id=turn_id,
        max_bytes=max_bytes,
    )
    return translator.translate(source)


def record_emissions(sink: Any, emissions: Iterable[Emission]) -> int:
    """Best-effort bounded handoff; recorder failures never block delivery."""

    recorder = getattr(sink, "record", None)
    if not callable(recorder):
        return 0
    recorded = 0
    for observation, source_key in emissions:
        try:
            recorder(observation, source_key=source_key)
        except Exception:
            continue
        recorded += 1
    return recorded


def record_hook(source: Any, sink: Any, **kwargs: Any) -> int:
    try:
        return record_emissions(sink, translate_hook(source, **kwargs))
    except SourceEventError:
        return 0


def record_otlp(source: Any, sink: Any, **kwargs: Any) -> int:
    try:
        return record_emissions(sink, translate_otlp(source, **kwargs))
    except SourceEventError:
        return 0


def safe_session_id(value: Any) -> Optional[str]:
    """Validate a Codex session identifier for opaque context binding."""

    return _safe_identifier(value)


__all__ = [
    "CodexExecTranslator",
    "Emission",
    "MAX_SOURCE_BYTES",
    "MalformedSourceEvent",
    "Observation",
    "OversizedSourceEvent",
    "SourceEventError",
    "record_emissions",
    "record_hook",
    "record_otlp",
    "safe_session_id",
    "translate_exec_event",
    "translate_hook",
    "translate_otlp",
]
