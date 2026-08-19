"""Privacy-first Claude Code event translators for the delivery-efficiency recorder.

This module is deliberately storage-free, exactly like the Codex adapter: each
translator returns ``(observation, source_key)`` pairs for the shared recorder
core.  It shares the bounded-input helpers with :mod:`delivery_efficiency.codex`
so both adapters reject malformed and oversized source events identically, and
it never introduces a second schema, ledger writer, or store.

Claude Code documents hook ``prompt_id`` correlation from v2.1.196.  The
supported installation starts at v2.1.212 because Anthropic records that as
the release fixing OTLP/HTTP exports for receivers that reject chunked transfer
encoding.  It exposes one UUID ``prompt_id`` across the hooks for a prompt and
the matching OTLP ``prompt.id`` attributes.  The adapter uses
that value as the authoritative task/turn correlation key, including for usage
that flushes after Stop or a declared terminal.  Hosts that omit it retain an
explicitly partial, collision-safe core-owned session-generation fallback;
missing or malformed OTLP correlation never triggers heuristic token binding.

Raw runtime identifiers cross this boundary only inside the transient
``source_identity`` object.  Prompt and assistant text, transcript paths,
working directories, filenames, tool arguments and results, permission modes,
compaction instructions, notification text, model names, cost figures, and
account or organization identifiers never enter an observation or source key.
"""

from __future__ import annotations

import re
import secrets
from typing import Any, Dict, List, Optional, Sequence

from . import ADAPTER_VERSION
from .codex import (
    Emission,
    MAX_SOURCE_BYTES,
    MalformedSourceEvent,
    Observation,
    OversizedSourceEvent,
    SourceEventError,
    _load_source,
    _otlp_attributes,
    _otlp_body_attributes,
    _safe_identifier,
    _safe_version,
    _source_key,
    _surface,
    record_emissions,
)


_ADAPTER_NAME = "claude-runtime"
_CLASSIFIER_VERSION = "claude-v1"
_SAFE_OTLP_ID = re.compile(r"^[0-9A-Fa-f]{16,64}$")
_TIME_UNIX_NANO = re.compile(r"^(?:0|[1-9][0-9]{0,31})$")
_PROMPT_UUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)

# Hook events this adapter translates into observations.  ``SessionStart`` is a
# session boundary, never request receipt; a ``source=compact`` start resumes
# the same task and must not create a new one.  ``PreCompact`` and
# ``Notification`` are recognized host events with no efficiency semantics in
# the frozen schema, so they translate to nothing rather than to a gap.
_HOOK_EVENTS = {
    "SessionStart",
    "SessionEnd",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "SubagentStart",
    "SubagentStop",
    "Stop",
    "StopFailure",
    "MessageDisplay",
    "PreCompact",
    "Notification",
}
_SILENT_HOOK_EVENTS = {"SessionStart", "PreCompact", "Notification"}


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
        "target": None,
    }


def _classification(
    phase: str,
    phase_provenance: str,
    activity_state: str,
    activity_provenance: str,
) -> Dict[str, str]:
    return {
        "phase": phase,
        "phase_provenance": phase_provenance,
        "activity_state": activity_state,
        "activity_provenance": activity_provenance,
        "classifier_version": _CLASSIFIER_VERSION,
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


def _payload(
    source_event: str,
    *,
    duration_ns: Optional[str] = None,
    success: Optional[bool] = None,
    tool_category: str = "not-applicable",
    task_kind: str = "unknown",
    gap_code: str = "none",
) -> Dict[str, Any]:
    return {
        "source_event": source_event,
        "span_id": None,
        "parent_span_id": None,
        "duration_ns": duration_ns,
        "success": success,
        "tool_category": tool_category,
        "outcome": "not-applicable",
        "task_kind": task_kind,
        "cause": "not-applicable",
        "requirement_id": None,
        "requirement_status": "not-applicable",
        "verification": "not-applicable",
        "gap_code": gap_code,
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
            "task_kind_provenance": (
                "inferred" if task_kind != "unknown" else "unknown"
            ),
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


def _observation(
    *,
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
            "family": "claude",
            "surface": _surface(surface),
            "version": _safe_version(runtime_version),
        },
        "adapter": {"name": _ADAPTER_NAME, "version": ADAPTER_VERSION},
        "source_identity": source_identity,
        "classification": classification,
        "measurement": measurement,
        "coverage": coverage,
        "event": event,
        "payload": payload,
    }


def _tool_category(tool_name: Any) -> str:
    """Reduce a Claude Code tool name to the schema's low-cardinality set."""

    if not isinstance(tool_name, str) or not tool_name or len(tool_name) > 256:
        return "unknown"
    if tool_name.startswith("mcp__") or tool_name.startswith("mcp_"):
        return "mcp"
    name = tool_name.casefold().replace("-", "_").replace(".", "_").replace("/", "_")
    if name in {"bash", "bashoutput", "shell", "killshell", "killbash"}:
        return "shell"
    if name in {"edit", "write", "multiedit", "notebookedit", "apply_patch", "patch"}:
        return "patch"
    if name in {"webfetch", "websearch", "browser"} or name.startswith("web_"):
        return "web"
    if name in {"task", "agent", "sendmessage", "agentoutput"} or "subagent" in name:
        return "agent"
    if name in {
        "read",
        "grep",
        "glob",
        "ls",
        "notebookread",
        "todoread",
        "todowrite",
        "taskcreate",
        "taskupdate",
        "tasklist",
        "taskget",
        "taskoutput",
    }:
        return "local"
    return "other"


def _prompt_id(value: Any, *, reject_malformed: bool) -> Optional[str]:
    """Return one documented prompt UUID without accepting lookalike content."""

    if value is None:
        return None
    if isinstance(value, str) and _PROMPT_UUID.fullmatch(value):
        return value.lower()
    if reject_malformed:
        raise MalformedSourceEvent("Claude prompt correlation identifier is malformed")
    return None


def _prompt_task_identity(session: str, prompt: str) -> str:
    # The recorder combines this UUID with runtime family and the opaque
    # session namespace before persistence.  Keep only the documented raw
    # correlation value at the adapter boundary.
    return prompt


def _prompt_identity(session: str, prompt: Optional[str], **updates: Optional[str]):
    task = _prompt_task_identity(session, prompt) if prompt is not None else None
    return _identity(
        lineage=session,
        task=task,
        session=session,
        turn=task,
        **updates,
    )


def _prompt_candidate_identity(
    session: str, prompt: str, **updates: Optional[str]
) -> Dict[str, Optional[str]]:
    """Carry an exact prompt as a transient turn candidate, not a task claim."""

    return _identity(
        lineage=session,
        session=session,
        turn=_prompt_task_identity(session, prompt),
        **updates,
    )


def _duration_ns(value: Any) -> Optional[str]:
    """Convert one authoritative integer millisecond duration to nanoseconds."""

    if value is None:
        return None
    if isinstance(value, bool):
        raise MalformedSourceEvent("duration_ms must be a non-negative integer")
    if isinstance(value, float):
        if not value.is_integer():
            raise MalformedSourceEvent("duration_ms must be a non-negative integer")
        value = int(value)
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]{0,23}", value):
        number = int(value)
    else:
        raise MalformedSourceEvent("duration_ms must be a non-negative integer")
    if number < 0 or len(str(number)) > 24:
        raise MalformedSourceEvent("duration_ms must be a non-negative integer")
    return str(number * 1_000_000)


def _observed_bool(value: Any) -> Optional[bool]:
    """Accept Claude's documented JSON or OTLP boolean representation."""

    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if value == "true":
        return True
    if value == "false":
        return False
    raise MalformedSourceEvent("observed success must be true or false")


def _first_activity_emission(
    *,
    session: str,
    prompt: Optional[str],
    surface: str,
    runtime_version: Optional[str],
    marker: Sequence[Any],
) -> Emission:
    # Every candidate in a session produces the same normalized observation, so
    # the recorder's task-scoped and session-scoped first-activity dedupe keeps
    # exactly one durable row per task even though candidate keys differ.
    observation = _observation(
        surface=surface,
        runtime_version=runtime_version,
        source_identity=_prompt_identity(session, prompt),
        classification=_classification("unattributed", "unknown", "unattributed", "unknown"),
        measurement=_measurement(),
        coverage=_hook_coverage(first_activity="partial"),
        event="task.first_activity",
        payload=_payload("unknown", tool_category="unknown"),
    )
    return observation, _source_key(
        "claude-first-activity", session, prompt, *marker
    )


def translate_hook(
    source: Any,
    *,
    event_name: Optional[str] = None,
    surface: str = "unknown",
    runtime_version: Optional[str] = None,
    source_project: Optional[str] = None,
    max_bytes: int = MAX_SOURCE_BYTES,
) -> List[Emission]:
    """Translate one Claude Code hook JSON object into allowlisted observations.

    ``UserPromptSubmit`` is the closest observable request boundary.  A valid
    host ``prompt_id`` becomes the exact transient task/turn correlation for
    every task-specific hook; its absence selects the explicitly partial
    legacy session-generation fallback.  A present malformed value rejects
    the hook rather than falling back and risking cross-prompt attribution.
    ``Stop`` and ``StopFailure`` emit partial runtime boundaries and never
    ``task.terminal``.  Tool completion hooks carry the host's execution-only
    duration; the wider Pre-to-Post hook interval is deliberately unattributed
    because it can include permission and other-hook time.
    """

    if source_project is not None and (
        not isinstance(source_project, str)
        or not source_project
        or "\x00" in source_project
        or len(source_project.encode("utf-8")) > 4096
    ):
        raise MalformedSourceEvent("repository source identity is invalid")
    data = _load_source(source, max_bytes)
    payload_event = data.get("hook_event_name")
    if event_name is None:
        event_name = payload_event
    elif payload_event is not None and payload_event != event_name:
        raise MalformedSourceEvent("hook event name does not match the invocation")
    if event_name not in _HOOK_EVENTS:
        raise MalformedSourceEvent("unsupported hook event")
    session = _safe_identifier(data.get("session_id"), required=True)
    if event_name in _SILENT_HOOK_EVENTS:
        # Startup, resume, clear, compaction, and notifications never create
        # tasks; a compacted session continues its current task and lineage.
        return []

    version = _safe_version(runtime_version)
    resolved_surface = _surface(surface)
    prompt = _prompt_id(data.get("prompt_id"), reject_malformed=True)

    if event_name == "SessionEnd":
        observation = _observation(
            surface=resolved_surface,
            runtime_version=version,
            source_identity=_identity(lineage=session, session=session),
            classification=_classification("reporting", "inferred", "unattributed", "unknown"),
            measurement=_measurement(),
            coverage=_hook_coverage(terminal_delivery="partial"),
            event="coverage.gap",
            payload=_payload("session_end", gap_code="host-boundary-unavailable"),
        )
        return [
            (
                observation,
                _source_key("claude-hook", session, "session_end", resolved_surface),
            )
        ]

    if event_name == "UserPromptSubmit":
        observation = _observation(
            surface=resolved_surface,
            runtime_version=version,
            source_identity=_prompt_identity(
                session, prompt, project=source_project
            ),
            classification=_classification("planning", "inferred", "unattributed", "unknown"),
            measurement=_measurement(),
            coverage=_hook_coverage(request_receipt="partial"),
            event="task.start",
            payload=_payload("prompt_submit", task_kind="primary"),
        )
        return [
            (
                observation,
                _source_key(
                    "claude-hook",
                    session,
                    prompt,
                    "prompt_submit",
                    resolved_surface,
                ),
            )
        ]

    if event_name in {"PreToolUse", "PostToolUse", "PostToolUseFailure"}:
        tool_use_id = _safe_identifier(data.get("tool_use_id"))
        category = _tool_category(data.get("tool_name"))
        emissions: List[Emission] = []
        if event_name == "PreToolUse":
            marker: Sequence[Any] = (
                ("tool", tool_use_id)
                if tool_use_id is not None
                else ("invocation", secrets.token_hex(16))
            )
            emissions.append(
                _first_activity_emission(
                    session=session,
                    prompt=prompt,
                    surface=resolved_surface,
                    runtime_version=version,
                    marker=marker,
                )
            )
        if tool_use_id is None:
            # Without a host correlation identifier there is no safe span
            # identity; coverage for tools stays partial rather than invented.
            return emissions
        is_start = event_name == "PreToolUse"
        is_failure = event_name == "PostToolUseFailure"
        source_event = (
            "pre_tool"
            if is_start
            else "post_tool_failure" if is_failure else "post_tool"
        )
        completion_duration = None if is_start else _duration_ns(data.get("duration_ms"))
        span = _observation(
            surface=resolved_surface,
            runtime_version=version,
            source_identity=_prompt_identity(
                session, prompt, span=tool_use_id
            ),
            # PreToolUse happens before permission resolution and another hook
            # can deny the call, so it stays unattributed.  A completion hook's
            # native duration is execution-only and is tool-active.  The
            # classification mismatch deliberately prevents the wider
            # Pre-to-Post receipt interval from being reported as tool time.
            classification=_classification(
                "unattributed",
                "unknown",
                "unattributed" if is_start else "tool-active",
                "unknown" if is_start else "runtime-observed",
            ),
            measurement=_measurement(),
            coverage=_hook_coverage(),
            event="span.start" if is_start else "span.end",
            payload=_payload(
                source_event,
                duration_ns=completion_duration,
                success=None if is_start else not is_failure,
                tool_category=category,
            ),
        )
        emissions.append(
            (
                span,
                _source_key(
                    "claude-hook",
                    session,
                    prompt,
                    source_event,
                    tool_use_id,
                ),
            )
        )
        return emissions

    if event_name == "MessageDisplay":
        # This hook runs before Claude renders a text batch.  It proves model
        # output exists, but neither final=true nor hook receipt proves task
        # completion or even that the batch has become visible.  Delta content
        # and raw message/turn identifiers are never copied into observations.
        message = _safe_identifier(data.get("message_id"))
        marker = (
            ("message", message)
            if message is not None
            else ("invocation", secrets.token_hex(16))
        )
        observation, key = _first_activity_emission(
            session=session,
            prompt=prompt,
            surface=resolved_surface,
            runtime_version=version,
            marker=marker,
        )
        observation["classification"] = _classification(
            "unattributed", "unknown", "model-active", "runtime-observed"
        )
        observation["payload"] = _payload("message_display")
        return [(observation, key)]

    if event_name in {"SubagentStart", "SubagentStop"}:
        agent = _safe_identifier(data.get("agent_id"))
        emissions = []
        if event_name == "SubagentStart":
            marker = (
                ("agent", agent)
                if agent is not None
                else ("invocation", secrets.token_hex(16))
            )
            emissions.append(
                _first_activity_emission(
                    session=session,
                    prompt=prompt,
                    surface=resolved_surface,
                    runtime_version=version,
                    marker=marker,
                )
            )
        # SubagentStop is blockable by any matching peer hook, so neither it
        # nor SubagentStart establishes a completed lifecycle interval.  Keep
        # presence and per-instance identity as partial evidence only.
        lifecycle = _observation(
            surface=resolved_surface,
            runtime_version=version,
            source_identity=_prompt_identity(session, prompt, agent=agent),
            classification=_classification(
                "unattributed", "unknown", "unattributed", "unknown"
            ),
            measurement=_measurement(),
            coverage=_hook_coverage(),
            event="coverage.gap",
            payload=_payload(
                "subagent_start" if event_name == "SubagentStart" else "subagent_stop",
                tool_category="agent",
                gap_code="host-boundary-unavailable",
            ),
        )
        emissions.append(
            (
                lifecycle,
                _source_key(
                    "claude-hook",
                    session,
                    prompt,
                    "subagent_start" if event_name == "SubagentStart" else "subagent_stop",
                    agent,
                    secrets.token_hex(16),
                ),
            )
        )
        return emissions

    if event_name in {"Stop", "StopFailure"}:
        failed = event_name == "StopFailure"
        observation = _observation(
            surface=resolved_surface,
            runtime_version=version,
            source_identity=_prompt_identity(session, prompt),
            classification=_classification("reporting", "inferred", "unattributed", "unknown"),
            measurement=_measurement(),
            coverage=_hook_coverage(terminal_delivery="partial"),
            # Ordinary Stop is blockable by a peer hook and therefore proves
            # only that a stop was attempted.  StopFailure replaces Stop on a
            # terminal API error and cannot be blocked.
            event="runtime.turn_stopped" if failed else "coverage.gap",
            payload=_payload(
                "turn_failure" if failed else "turn_stop",
                success=False if failed else None,
                gap_code="none" if failed else "host-boundary-unavailable",
            ),
        )
        # Stop handlers run in parallel.  A peer can block the first stop and
        # cause another attempt for the same prompt, so each Stop invocation is
        # evidence of a distinct partial boundary.  StopFailure runs once in
        # place of Stop and can safely deduplicate a repeated delivery.
        invocation = (
            prompt
            if failed and prompt is not None
            else secrets.token_hex(16)
        )
        return [
            (
                observation,
                _source_key(
                    "claude-hook",
                    session,
                    prompt,
                    "turn_failure" if failed else "turn_stop",
                    invocation,
                ),
            )
        ]

    raise AssertionError("recognized hook event was not translated")


_OTLP_CLAUDE_ATTRIBUTES = {
    "event.name",
    "event_name",
    "name",
    "session.id",
    "session_id",
    "prompt.id",
    "prompt_id",
    "agent.name",
    "app.entrypoint",
    "app.version",
    "service.name",
    "service.version",
    "duration_ms",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "tool_name",
    "tool_use_id",
    "success",
    "decision",
    "client_request_id",
    "request_id",
}
_OTLP_CLAUDE_BODY_EVENTS = {
    "claude_code.api_request",
    "api_request",
    "claude_code.api_error",
    "api_error",
    "claude_code.user_prompt",
    "user_prompt",
    "claude_code.tool_result",
    "tool_result",
    "claude_code.tool_decision",
    "tool_decision",
}
_API_REQUEST_NAMES = {"claude_code.api_request", "api_request"}
_API_ERROR_NAMES = {"claude_code.api_error", "api_error"}
_USER_PROMPT_NAMES = {"claude_code.user_prompt", "user_prompt"}
_TOOL_RESULT_NAMES = {"claude_code.tool_result", "tool_result"}
_TOOL_DECISION_NAMES = {"claude_code.tool_decision", "tool_decision"}
_KNOWN_OTLP_EVENTS = (
    _API_REQUEST_NAMES
    | _API_ERROR_NAMES
    | _USER_PROMPT_NAMES
    | _TOOL_RESULT_NAMES
    | _TOOL_DECISION_NAMES
)


def _claude_counter(mapping: Dict[str, Any], name: str) -> Optional[str]:
    """Accept int, decimal-string, and integral-float OTLP counter encodings."""

    if name not in mapping:
        return None
    value = mapping[name]
    if value is None:
        return None
    if isinstance(value, bool):
        raise MalformedSourceEvent("token counter must be a non-negative integer")
    if isinstance(value, float):
        if not value.is_integer():
            raise MalformedSourceEvent("token counter must be a non-negative integer")
        value = int(value)
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]{0,29}", value):
        number = int(value)
    else:
        raise MalformedSourceEvent("token counter must be a non-negative integer")
    if number < 0 or len(str(number)) > 30:
        raise MalformedSourceEvent("token counter must be a non-negative integer")
    return str(number)


def _iter_claude_otlp_records(data: Dict[str, Any]):
    resource_logs = data.get("resourceLogs")
    if type(resource_logs) is not list:
        raise MalformedSourceEvent("OTLP JSON is missing resourceLogs")
    for resource_log in resource_logs:
        if type(resource_log) is not dict:
            raise MalformedSourceEvent("OTLP resource log must be an object")
        resource_attrs = _otlp_attributes(resource_log.get("resource"), _OTLP_CLAUDE_ATTRIBUTES)
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
                attrs.update(
                    _otlp_body_attributes(
                        record.get("body"),
                        _OTLP_CLAUDE_ATTRIBUTES,
                        _OTLP_CLAUDE_BODY_EVENTS,
                    )
                )
                attrs.update(_otlp_attributes(record, _OTLP_CLAUDE_ATTRIBUTES))
                yield {
                    "attributes": attrs,
                    "timeUnixNano": record.get("timeUnixNano"),
                    "observedTimeUnixNano": record.get("observedTimeUnixNano"),
                    "traceId": record.get("traceId"),
                    "spanId": record.get("spanId"),
                }


def _otlp_time_marker(record: Dict[str, Any]) -> str:
    time_marker = record.get("timeUnixNano")
    if time_marker is None:
        time_marker = record.get("observedTimeUnixNano")
    # proto3 JSON encodes int64 as a string, but some OTLP/JSON exporters emit
    # plain numbers; accept both without losing precision.
    if isinstance(time_marker, int) and not isinstance(time_marker, bool) and time_marker >= 0:
        time_marker = str(time_marker)
    if not (isinstance(time_marker, str) and _TIME_UNIX_NANO.fullmatch(time_marker)):
        raise MalformedSourceEvent("Claude OTLP record lacks a valid timestamp")
    return time_marker


def _known_claude_surface(attrs: Dict[str, Any], fallback: str) -> str:
    """Map documented Claude entrypoints without persisting raw host labels."""

    entrypoints = {
        "cli": "cli-interactive",
        "sdk-cli": "cli-exec",
        "sdk-ts": "cli-exec",
        "sdk-py": "cli-exec",
        "claude-vscode": "ide",
        "claude-desktop": "desktop",
        "claude-desktop-3p": "desktop",
        "local-agent": "desktop",
    }
    entrypoint = attrs.get("app.entrypoint")
    if entrypoint in entrypoints:
        return entrypoints[entrypoint]
    if attrs.get("service.name") == "claude-code-desktop":
        return "desktop"
    return _surface(fallback)


def _otlp_record_span(
    event_value: str,
    record: Dict[str, Any],
    attrs: Dict[str, Any],
    time_marker: str,
    *,
    preferred: Optional[str] = None,
) -> str:
    """Build a bounded transient span identity from content-free host IDs."""

    components = [event_value]
    for candidate in (
        preferred,
        attrs.get("client_request_id"),
        attrs.get("request_id"),
    ):
        safe = _safe_identifier(candidate)
        if safe is not None and safe not in components:
            components.append(safe)
    for name in ("traceId", "spanId"):
        value = record.get(name)
        if isinstance(value, str) and _SAFE_OTLP_ID.fullmatch(value):
            components.append(value)
    components.append(time_marker)
    return ":".join(components)


def _otlp_first_activity(
    *,
    session: str,
    prompt: str,
    surface: str,
    runtime_version: Optional[str],
    source_event: str,
    marker: str,
    activity_state: str,
    activity_provenance: str,
    tool_category: str = "not-applicable",
    agent: Optional[str] = None,
) -> Emission:
    """Emit an exact-prompt candidate without claiming a task already exists."""

    observation = _observation(
        surface=surface,
        runtime_version=runtime_version,
        source_identity=_prompt_candidate_identity(session, prompt, agent=agent),
        classification=_classification(
            "unattributed", "unknown", activity_state, activity_provenance
        ),
        measurement=_measurement(),
        coverage=_coverage(
            request_receipt="partial",
            first_activity="partial",
            tokens="partial",
            tools="partial",
            subagents="partial",
            terminal_delivery="partial",
            scope="unknown",
            verification="unknown",
        ),
        event="task.first_activity",
        payload=_payload(source_event, tool_category=tool_category),
    )
    return observation, _source_key(
        "claude-otel-first-activity",
        session,
        prompt,
        source_event,
        marker,
    )


def _otlp_span_end(
    *,
    session: str,
    prompt: str,
    surface: str,
    runtime_version: Optional[str],
    source_event: str,
    span: str,
    duration_ns: Optional[str],
    success: Optional[bool],
    activity_state: str,
    activity_provenance: str,
    tool_category: str = "not-applicable",
    agent: Optional[str] = None,
) -> Emission:
    observation = _observation(
        surface=surface,
        runtime_version=runtime_version,
        source_identity=_prompt_candidate_identity(
            session, prompt, agent=agent, span=span
        ),
        classification=_classification(
            "unattributed", "unknown", activity_state, activity_provenance
        ),
        measurement=_measurement(),
        coverage=_coverage(
            request_receipt="partial",
            first_activity="partial",
            tokens="partial",
            tools="partial",
            subagents="partial",
            terminal_delivery="partial",
            scope="unknown",
            verification="unknown",
        ),
        event="span.end",
        payload=_payload(
            source_event,
            duration_ns=duration_ns,
            success=success,
            tool_category=tool_category,
        ),
    )
    return observation, _source_key(
        "claude-otel-span",
        session,
        prompt,
        source_event,
        span,
    )


def translate_otlp(
    source: Any,
    *,
    surface: str = "unknown",
    runtime_version: Optional[str] = None,
    max_bytes: int = MAX_SOURCE_BYTES,
) -> List[Emission]:
    """Translate Claude Code's content-free OTLP efficiency observations.

    ``user_prompt`` is a request boundary; ``api_request``, ``api_error``,
    ``tool_result``, and rejected ``tool_decision`` records provide native
    activity, duration, and outcome evidence.  API counters bind by the shared
    prompt UUID even after Stop or terminal delivery.  Missing or malformed
    correlation leaves only usage session-scoped: it never enables heuristic
    binding of activity or span candidates.  Content, errors, tool inputs and
    results, account data, cost, and model attributes remain outside the
    positive allowlist.
    """

    data = _load_source(source, max_bytes)
    task_starts: List[Emission] = []
    activity_events: List[Emission] = []
    usage_events: List[Emission] = []
    for record in _iter_claude_otlp_records(data):
        attrs = record["attributes"]
        event_value = None
        for name in ("event.name", "event_name", "name"):
            if attrs.get(name) is not None:
                event_value = attrs[name]
                break
        if event_value not in _KNOWN_OTLP_EVENTS:
            continue

        session = _safe_identifier(attrs.get("session.id"))
        if session is None:
            session = _safe_identifier(attrs.get("session_id"))
        prompt_value = attrs.get("prompt.id")
        if prompt_value is None:
            prompt_value = attrs.get("prompt_id")
        prompt = _prompt_id(prompt_value, reject_malformed=False)
        version = _safe_version(
            runtime_version
            if runtime_version is not None
            else attrs.get("app.version") or attrs.get("service.version")
        )
        time_marker = _otlp_time_marker(record)
        resolved_surface = _known_claude_surface(attrs, surface)
        delegated_agent = (
            "delegated"
            if isinstance(attrs.get("agent.name"), str) and attrs.get("agent.name")
            else None
        )

        if event_value in _USER_PROMPT_NAMES:
            if session is None or prompt is None:
                # A user_prompt without both documented correlation fields is
                # not a safe task boundary and carries no other needed metric.
                continue
            start = _observation(
                surface=resolved_surface,
                runtime_version=version,
                source_identity=_prompt_identity(session, prompt),
                classification=_classification(
                    "planning", "inferred", "unattributed", "unknown"
                ),
                measurement=_measurement(),
                coverage=_coverage(
                    request_receipt="partial",
                    first_activity="partial",
                    tokens="partial",
                    tools="partial",
                    subagents="partial",
                    terminal_delivery="partial",
                    scope="unknown",
                    verification="unknown",
                ),
                event="task.start",
                payload=_payload("prompt_submit", task_kind="primary"),
            )
            task_starts.append(
                (
                    start,
                    _source_key(
                        "claude-otel-user-prompt",
                        session,
                        prompt,
                        time_marker,
                    ),
                )
            )
            continue

        # Unlike token counters, activity and span observations require exact
        # prompt correlation.  Skipping them when prompt.id is absent or
        # malformed prevents the core's legacy session fallback from binding
        # an unrelated prompt heuristically.
        exact_prompt = session is not None and prompt is not None

        if event_value in _TOOL_RESULT_NAMES:
            if not exact_prompt:
                continue
            tool_use_id = _safe_identifier(attrs.get("tool_use_id"))
            marker = _otlp_record_span(
                event_value,
                record,
                attrs,
                time_marker,
                preferred=tool_use_id,
            )
            category = _tool_category(attrs.get("tool_name"))
            activity_events.append(
                _otlp_first_activity(
                    session=session,
                    prompt=prompt,
                    surface=resolved_surface,
                    runtime_version=version,
                    source_event="otel_tool",
                    marker=marker,
                    activity_state="tool-active",
                    activity_provenance="runtime-observed",
                    tool_category=category,
                    agent=delegated_agent,
                )
            )
            if tool_use_id is not None:
                activity_events.append(
                    _otlp_span_end(
                        session=session,
                        prompt=prompt,
                        surface=resolved_surface,
                        runtime_version=version,
                        source_event="otel_tool",
                        # Hook fallback and OTLP use the same documented raw
                        # tool identity, allowing reporting to deduplicate the
                        # same native duration regardless of arrival order.
                        span=tool_use_id,
                        duration_ns=_duration_ns(attrs.get("duration_ms")),
                        success=_observed_bool(attrs.get("success")),
                        activity_state="tool-active",
                        activity_provenance="runtime-observed",
                        tool_category=category,
                        agent=delegated_agent,
                    )
                )
            continue

        if event_value in _TOOL_DECISION_NAMES:
            # Accepted tools are represented by tool_result after execution.
            # A rejection has no tool_result and represents a decision, not
            # executed tool-active time.
            if not exact_prompt or attrs.get("decision") != "reject":
                continue
            tool_use_id = _safe_identifier(attrs.get("tool_use_id"))
            if tool_use_id is None:
                continue
            marker = _otlp_record_span(
                event_value,
                record,
                attrs,
                time_marker,
                preferred=tool_use_id,
            )
            category = _tool_category(attrs.get("tool_name"))
            activity_events.extend(
                [
                    _otlp_first_activity(
                        session=session,
                        prompt=prompt,
                        surface=resolved_surface,
                        runtime_version=version,
                        source_event="otel_tool_decision",
                        marker=marker,
                        activity_state="unattributed",
                        activity_provenance="unknown",
                        tool_category=category,
                        agent=delegated_agent,
                    ),
                    _otlp_span_end(
                        session=session,
                        prompt=prompt,
                        surface=resolved_surface,
                        runtime_version=version,
                        source_event="otel_tool_decision",
                        span=tool_use_id,
                        duration_ns=None,
                        success=False,
                        activity_state="unattributed",
                        activity_provenance="unknown",
                        tool_category=category,
                        agent=delegated_agent,
                    ),
                ]
            )
            continue

        if event_value in _API_ERROR_NAMES:
            if not exact_prompt:
                continue
            marker = _otlp_record_span(event_value, record, attrs, time_marker)
            activity_events.extend(
                [
                    _otlp_first_activity(
                        session=session,
                        prompt=prompt,
                        surface=resolved_surface,
                        runtime_version=version,
                        source_event="otel_api_error",
                        marker=marker,
                        activity_state="unattributed",
                        activity_provenance="unknown",
                        agent=delegated_agent,
                    ),
                    _otlp_span_end(
                        session=session,
                        prompt=prompt,
                        surface=resolved_surface,
                        runtime_version=version,
                        source_event="otel_api_error",
                        span=marker,
                        duration_ns=_duration_ns(attrs.get("duration_ms")),
                        success=False,
                        activity_state="unattributed",
                        activity_provenance="unknown",
                        agent=delegated_agent,
                    ),
                ]
            )
            continue

        # The only remaining recognized event is api_request.  Its native
        # request duration and counters are independent observations.
        if exact_prompt:
            marker = _otlp_record_span(event_value, record, attrs, time_marker)
            activity_events.extend(
                [
                    _otlp_first_activity(
                        session=session,
                        prompt=prompt,
                        surface=resolved_surface,
                        runtime_version=version,
                        source_event="otel_api",
                        marker=marker,
                        activity_state="unattributed",
                        activity_provenance="unknown",
                        agent=delegated_agent,
                    ),
                    _otlp_span_end(
                        session=session,
                        prompt=prompt,
                        surface=resolved_surface,
                        runtime_version=version,
                        source_event="otel_api",
                        span=marker,
                        duration_ns=_duration_ns(attrs.get("duration_ms")),
                        success=True,
                        activity_state="unattributed",
                        activity_provenance="unknown",
                        agent=delegated_agent,
                    ),
                ]
            )

        token_values = _tokens(
            input=_claude_counter(attrs, "input_tokens"),
            cached_input=_claude_counter(attrs, "cache_read_tokens"),
            output=_claude_counter(attrs, "output_tokens"),
            other=_claude_counter(attrs, "cache_creation_tokens"),
        )
        if all(value is None for value in token_values.values()):
            continue

        trace_marker = record.get("traceId")
        span_marker = record.get("spanId")
        if not (isinstance(trace_marker, str) and _SAFE_OTLP_ID.fullmatch(trace_marker)):
            trace_marker = None
        if not (isinstance(span_marker, str) and _SAFE_OTLP_ID.fullmatch(span_marker)):
            span_marker = None

        native_complete = all(
            token_values[name] is not None
            for name in ("input", "cached_input", "output", "other")
        )
        usage = _observation(
            surface=resolved_surface,
            runtime_version=version,
            source_identity=_identity(
                lineage=session,
                session=session,
                turn=(
                    _prompt_task_identity(session, prompt)
                    if session is not None and prompt is not None
                    else None
                ),
            ),
            classification=_classification(
                "unattributed", "unknown", "model-active", "runtime-observed"
            ),
            measurement=_measurement(
                provenance="runtime-observed",
                counter_source="runtime-native",
                tokens=token_values,
            ),
            coverage=_coverage(
                request_receipt="partial",
                first_activity="partial",
                tokens="complete" if native_complete else "partial",
                tools="partial",
                subagents="partial",
                terminal_delivery="partial",
                scope="unknown",
                verification="unknown",
            ),
            event="usage.observed",
            payload=_payload("otel_api"),
        )
        usage_events.append(
            (
                usage,
                _source_key(
                    "claude-otel",
                    session,
                    prompt,
                    time_marker,
                    trace_marker,
                    span_marker,
                    token_values["input"],
                    token_values["cached_input"],
                    token_values["output"],
                    token_values["other"],
                ),
            )
        )
    # Process content-free prompt boundaries before exact candidates and usage
    # even when an exporter serializes records out of order.  The core can then
    # bind every candidate by prompt.id without mutable adapter state.
    return task_starts + activity_events + usage_events


def safe_session_id(value: Any) -> Optional[str]:
    """Validate a host session identifier for context reinjection, or None."""

    return _safe_identifier(value)


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


__all__ = [
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
    "translate_hook",
    "translate_otlp",
]
