"""Shared, bounded agent declarations for facts a host cannot observe."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import ADAPTER_VERSION


TERMINAL_OUTCOMES = {
    "complete",
    "incomplete",
    "blocked",
    "cancelled",
    "superseded",
    "interrupted",
}
PHASES = {"planning", "implementation", "testing", "deployment", "reporting", "unattributed"}
ACTIVITIES = {"model-active", "tool-active", "external-wait", "user-wait", "blocked-wait", "unattributed"}
TASK_KINDS = {"primary", "continuation", "retry", "rollback", "defect-repair", "rework", "unknown"}
CAUSES = {"agent-caused-mistake", "changed-user-intent", "new-scope", "external-cause", "not-applicable", "unknown"}
TASK_TYPES = {"implementation", "diagnosis", "review", "audit", "research", "documentation", "operations", "mixed", "other", "not-applicable", "unknown"}
SCOPE_SIZES = {"small", "medium", "large", "extra-large", "not-applicable", "unknown"}
METHODS = {"direct", "delegated", "hybrid", "automated", "not-applicable", "unknown"}
VERIFICATION = {"verified", "partially-verified", "unverified", "not-applicable", "unknown"}
REQUIREMENT_STATUSES = {"satisfied", "partial", "blocked", "removed"}
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_REQUIREMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_REFERENCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,127}$")
_CONFIG_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+:-]{0,63}$")
_EVENT_ID = re.compile(r"^[0-9a-f]{32}$")

Emission = Tuple[Dict[str, Any], str]


class DeclarationError(ValueError):
    pass


def _source_key(kind: str, *values: Any) -> str:
    raw = json.dumps([kind] + list(values), separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return "agent-declaration:" + hashlib.sha256(raw).hexdigest()


def _tokens() -> Dict[str, None]:
    return {
        "input": None,
        "cached_input": None,
        "output": None,
        "reasoning_output": None,
        "tool": None,
        "other": None,
    }


def _identity(
    session: str,
    span: Optional[str] = None,
    agent: Optional[str] = None,
) -> Dict[str, Optional[str]]:
    if not isinstance(session, str) or _SAFE_ID.fullmatch(session) is None:
        raise DeclarationError("a bounded runtime session id is required")
    if span is not None and (not isinstance(span, str) or _SAFE_ID.fullmatch(span) is None):
        raise DeclarationError("span id is invalid")
    if agent is not None and (not isinstance(agent, str) or _SAFE_ID.fullmatch(agent) is None):
        raise DeclarationError("agent id is invalid")
    return {
        "lineage": None,
        "task": None,
        "project": None,
        "revision": None,
        "session": session,
        "turn": None,
        "agent": agent,
        "span": span,
    }


def _classification(phase: str, activity: str) -> Dict[str, str]:
    if phase not in PHASES or activity not in ACTIVITIES:
        raise DeclarationError("phase or activity is outside the stable vocabulary")
    return {
        "phase": phase,
        "phase_provenance": "agent-declared",
        "activity_state": activity,
        "activity_provenance": "agent-declared",
        "classifier_version": "declaration-v1",
    }


def _coverage(**updates: str) -> Dict[str, str]:
    value = {
        "request_receipt": "partial",
        "first_activity": "partial",
        "tokens": "partial",
        "tools": "partial",
        "subagents": "partial",
        "terminal_delivery": "partial",
        "scope": "unknown",
        "verification": "unknown",
    }
    value.update(updates)
    return value


def _payload(
    *,
    span_id: Optional[str] = None,
    outcome: str = "not-applicable",
    task_kind: str = "unknown",
    cause: str = "not-applicable",
    requirement_id: Optional[str] = None,
    requirement_status: str = "not-applicable",
    verification: str = "not-applicable",
    link_task_id: Optional[str] = None,
    link_lineage_id: Optional[str] = None,
    link_provenance: str = "not-applicable",
    correction_event_id: Optional[str] = None,
    correction_provenance: str = "not-applicable",
    acceptance_baseline_id: Optional[str] = None,
    acceptance_baseline_provenance: str = "unknown",
    approved_scope_change_ids: Sequence[str] = (),
    scope_change_provenance: str = "unknown",
    task_kind_provenance: str = "unknown",
    task_type: str = "unknown",
    task_type_provenance: str = "unknown",
    scope_size: str = "unknown",
    scope_size_provenance: str = "unknown",
    method: str = "unknown",
    method_provenance: str = "unknown",
    evidence_refs: Sequence[str] = (),
    evidence_provenance: str = "not-applicable",
    policy_version: Optional[str] = None,
    policy_provenance: str = "unknown",
    model_config_version: Optional[str] = None,
    model_config_provenance: str = "unknown",
    runtime_config_version: Optional[str] = None,
    runtime_config_provenance: str = "unknown",
    recorder_config_version: Optional[str] = None,
    recorder_config_provenance: str = "unknown",
) -> Dict[str, Any]:
    return {
        "source_event": "agent_declaration",
        "span_id": span_id,
        "parent_span_id": None,
        "duration_ns": None,
        "success": outcome == "complete" if outcome != "not-applicable" else None,
        "tool_category": "not-applicable",
        "outcome": outcome,
        "task_kind": task_kind,
        "cause": cause,
        "requirement_id": requirement_id,
        "requirement_status": requirement_status,
        "verification": verification,
        "gap_code": "none",
        "link": {
            "task_id": link_task_id,
            "lineage_id": link_lineage_id,
            "provenance": link_provenance,
        },
        "correction": {
            "event_id": correction_event_id,
            "provenance": correction_provenance,
        },
        "task_metadata": {
            "acceptance_baseline_id": acceptance_baseline_id,
            "acceptance_baseline_provenance": acceptance_baseline_provenance,
            "approved_scope_change_ids": list(approved_scope_change_ids),
            "scope_change_provenance": scope_change_provenance,
            "task_kind_provenance": task_kind_provenance,
            "task_type": task_type,
            "task_type_provenance": task_type_provenance,
            "scope_size": scope_size,
            "scope_size_provenance": scope_size_provenance,
            "method": method,
            "method_provenance": method_provenance,
            "classifier_version": "task-v1",
        },
        "evidence": {
            "refs": list(evidence_refs),
            "provenance": evidence_provenance,
        },
        "configuration": {
            "policy_version": policy_version,
            "policy_provenance": policy_provenance,
            "model_config_version": model_config_version,
            "model_config_provenance": model_config_provenance,
            "runtime_config_version": runtime_config_version,
            "runtime_config_provenance": runtime_config_provenance,
            "recorder_config_version": recorder_config_version,
            "recorder_config_provenance": recorder_config_provenance,
        },
    }


def _observation(
    *,
    session: str,
    runtime_family: str,
    surface: str,
    event: str,
    phase: str,
    activity: str,
    payload: Dict[str, Any],
    coverage: Dict[str, str],
    span: Optional[str] = None,
    agent: Optional[str] = None,
) -> Dict[str, Any]:
    if runtime_family not in {"codex", "claude"}:
        raise DeclarationError("runtime family must be codex or claude")
    if surface not in {"cli-interactive", "cli-exec", "desktop", "ide", "unknown"}:
        surface = "unknown"
    return {
        "runtime": {"family": runtime_family, "surface": surface, "version": None},
        "adapter": {"name": "agent-declaration", "version": ADAPTER_VERSION},
        "source_identity": _identity(session, span, agent),
        "classification": _classification(phase, activity),
        "measurement": {
            "provenance": "agent-declared",
            "counter_source": "not-applicable",
            "tokens": _tokens(),
            "recorder_overhead_ns": None,
        },
        "coverage": coverage,
        "event": event,
        "payload": payload,
    }


def phase_emission(
    *,
    session: str,
    runtime_family: str,
    surface: str,
    boundary: str,
    phase: str,
    activity: str,
    span: str,
    agent: Optional[str] = None,
) -> Emission:
    if boundary not in {"start", "end"}:
        raise DeclarationError("phase boundary must be start or end")
    observation = _observation(
        session=session,
        runtime_family=runtime_family,
        surface=surface,
        event="span." + boundary,
        phase=phase,
        activity=activity,
        payload=_payload(),
        coverage=_coverage(),
        span=span,
        agent=agent,
    )
    return observation, _source_key(
        "phase", session, boundary, phase, activity, span, agent
    )


def requirement_emission(
    *,
    session: str,
    runtime_family: str,
    surface: str,
    requirement_id: str,
    status: str,
    verification: str,
    evidence_refs: Sequence[str] = (),
) -> Emission:
    if not isinstance(requirement_id, str) or _REQUIREMENT_ID.fullmatch(requirement_id) is None:
        raise DeclarationError("requirement id is invalid")
    if status not in REQUIREMENT_STATUSES or verification not in VERIFICATION:
        raise DeclarationError("requirement status or verification is invalid")
    refs = _bounded_reference_list(evidence_refs, "requirement evidence")
    observation = _observation(
        session=session,
        runtime_family=runtime_family,
        surface=surface,
        event="requirement.status",
        phase="reporting",
        activity="model-active",
        payload=_payload(
            requirement_id=requirement_id,
            requirement_status=status,
            verification=verification,
            evidence_refs=refs,
            evidence_provenance="agent-declared" if refs else "unknown",
        ),
        coverage=_coverage(scope="partial", verification="complete"),
    )
    return observation, _source_key(
        "requirement", session, requirement_id, status, verification, refs
    )


def terminal_emissions(
    *,
    session: str,
    runtime_family: str,
    surface: str,
    outcome: str,
    verification: str,
    task_kind: str,
    cause: str,
    requirements: Sequence[Tuple[str, str, str]],
    requirement_evidence: Optional[Mapping[str, Sequence[str]]] = None,
    acceptance_baseline_id: Optional[str] = None,
    approved_scope_change_ids: Optional[Sequence[str]] = None,
    task_type: str = "unknown",
    scope_size: str = "unknown",
    method: str = "unknown",
    policy_version: Optional[str] = None,
    model_config_version: Optional[str] = None,
    runtime_config_version: Optional[str] = None,
    recorder_config_version: Optional[str] = None,
) -> List[Emission]:
    if outcome not in TERMINAL_OUTCOMES:
        raise DeclarationError("terminal outcome is invalid")
    if verification not in VERIFICATION or task_kind not in TASK_KINDS or cause not in CAUSES:
        raise DeclarationError("terminal classification is invalid")
    if task_type not in TASK_TYPES or scope_size not in SCOPE_SIZES or method not in METHODS:
        raise DeclarationError("terminal task type, scope size, or method is invalid")
    if acceptance_baseline_id is not None:
        _bounded_reference(acceptance_baseline_id, "acceptance baseline")
    scope_changes = (
        None
        if approved_scope_change_ids is None
        else _bounded_reference_list(approved_scope_change_ids, "approved scope changes")
    )
    configuration_values = {
        "policy_version": policy_version,
        "model_config_version": model_config_version,
        "runtime_config_version": runtime_config_version,
        "recorder_config_version": recorder_config_version,
    }
    for label, value in configuration_values.items():
        if value is not None and (
            not isinstance(value, str) or _CONFIG_VERSION.fullmatch(value) is None
        ):
            raise DeclarationError("{} is invalid".format(label))
    evidence_by_requirement = dict(requirement_evidence or {})
    if set(evidence_by_requirement) - {item[0] for item in requirements}:
        raise DeclarationError("evidence references an undeclared requirement")
    normalized_evidence = {
        requirement_id: _bounded_reference_list(refs, "requirement evidence")
        for requirement_id, refs in evidence_by_requirement.items()
    }
    requirement_events = [
        requirement_emission(
            session=session,
            runtime_family=runtime_family,
            surface=surface,
            requirement_id=item[0],
            status=item[1],
            verification=item[2],
            evidence_refs=normalized_evidence.get(item[0], ()),
        )
        for item in requirements
    ]
    all_resolved = bool(requirements) and all(item[1] in {"satisfied", "removed"} for item in requirements)
    if outcome == "complete" and not all_resolved:
        raise DeclarationError("complete requires at least one declared requirement and no unresolved status")
    if outcome == "complete":
        if acceptance_baseline_id is None:
            raise DeclarationError("complete requires an acceptance baseline id")
        if scope_changes is None:
            raise DeclarationError("complete requires an explicit approved scope-change set")
        if task_type in {"unknown", "not-applicable"} or scope_size in {
            "unknown",
            "not-applicable",
        } or method in {
            "unknown",
            "not-applicable",
        }:
            raise DeclarationError(
                "complete requires explicit task-type, scope-size, and method tags"
            )
        missing_evidence = [
            item[0] for item in requirements if not normalized_evidence.get(item[0])
        ]
        if missing_evidence:
            raise DeclarationError("complete requires evidence for every requirement")
    scope_coverage = "complete" if all_resolved else ("partial" if requirements else "unknown")
    terminal = _observation(
        session=session,
        runtime_family=runtime_family,
        surface=surface,
        event="task.terminal",
        phase="reporting",
        activity="model-active",
        payload=_payload(
            outcome=outcome,
            task_kind=task_kind,
            cause=cause,
            verification=verification,
            acceptance_baseline_id=acceptance_baseline_id,
            acceptance_baseline_provenance=(
                "agent-declared" if acceptance_baseline_id is not None else "unknown"
            ),
            approved_scope_change_ids=scope_changes or (),
            scope_change_provenance=(
                "agent-declared" if scope_changes is not None else "unknown"
            ),
            task_kind_provenance="agent-declared",
            task_type=task_type,
            task_type_provenance=(
                "agent-declared" if task_type not in {"unknown", "not-applicable"} else "unknown"
            ),
            scope_size=scope_size,
            scope_size_provenance=(
                "agent-declared" if scope_size not in {"unknown", "not-applicable"} else "unknown"
            ),
            method=method,
            method_provenance=(
                "agent-declared" if method not in {"unknown", "not-applicable"} else "unknown"
            ),
            policy_version=policy_version,
            policy_provenance="agent-declared" if policy_version is not None else "unknown",
            model_config_version=model_config_version,
            model_config_provenance=(
                "agent-declared" if model_config_version is not None else "unknown"
            ),
            runtime_config_version=runtime_config_version,
            runtime_config_provenance=(
                "agent-declared" if runtime_config_version is not None else "unknown"
            ),
            recorder_config_version=recorder_config_version,
            recorder_config_provenance=(
                "agent-declared" if recorder_config_version is not None else "unknown"
            ),
        ),
        coverage=_coverage(
            terminal_delivery="partial",
            scope=scope_coverage,
            verification="complete",
        ),
    )
    terminal_key = _source_key(
        "terminal",
        session,
        outcome,
        verification,
        task_kind,
        cause,
        list(requirements),
        normalized_evidence,
        acceptance_baseline_id,
        scope_changes,
        task_type,
        scope_size,
        method,
        configuration_values,
    )
    return requirement_events + [(terminal, terminal_key)]


def lineage_emission(
    *,
    session: str,
    runtime_family: str,
    surface: str,
    linked_task_binding: str,
    task_kind: str,
    cause: str,
) -> Emission:
    if task_kind not in TASK_KINDS - {"primary", "unknown"}:
        raise DeclarationError("lineage link requires a linked-work task kind")
    if cause not in CAUSES or cause == "not-applicable":
        raise DeclarationError("lineage link requires an explicit cause")
    if not isinstance(linked_task_binding, str) or not _SAFE_ID.fullmatch(
        linked_task_binding
    ):
        raise DeclarationError("linked task binding is invalid")
    observation = _observation(
        session=session,
        runtime_family=runtime_family,
        surface=surface,
        event="lineage.link",
        phase="planning",
        activity="model-active",
        payload=_payload(
            task_kind=task_kind,
            cause=cause,
            link_provenance="agent-declared",
            task_kind_provenance="agent-declared",
        ),
        coverage=_coverage(scope="partial"),
    )
    return observation, _source_key(
        "lineage", session, linked_task_binding, task_kind, cause
    )


def requirement_correction_emission(
    *,
    session: str,
    runtime_family: str,
    surface: str,
    target_event_id: str,
    requirement_id: str,
    status: str,
    verification: str,
    evidence_refs: Sequence[str] = (),
) -> Emission:
    if not isinstance(target_event_id, str) or _EVENT_ID.fullmatch(target_event_id) is None:
        raise DeclarationError("correction target event id is invalid")
    if not isinstance(requirement_id, str) or _REQUIREMENT_ID.fullmatch(requirement_id) is None:
        raise DeclarationError("requirement id is invalid")
    if status not in REQUIREMENT_STATUSES or verification not in VERIFICATION - {
        "unknown",
        "not-applicable",
    }:
        raise DeclarationError("requirement correction state is invalid")
    refs = _bounded_reference_list(evidence_refs, "requirement evidence")
    observation = _observation(
        session=session,
        runtime_family=runtime_family,
        surface=surface,
        event="correction",
        phase="reporting",
        activity="model-active",
        payload=_payload(
            requirement_id=requirement_id,
            requirement_status=status,
            verification=verification,
            correction_event_id=target_event_id,
            correction_provenance="agent-declared",
            evidence_refs=refs,
            evidence_provenance="agent-declared" if refs else "unknown",
        ),
        coverage=_coverage(scope="partial", verification="complete"),
    )
    return observation, _source_key(
        "correction-requirement",
        session,
        target_event_id,
        requirement_id,
        status,
        verification,
        refs,
    )


def terminal_correction_emission(
    *,
    session: str,
    runtime_family: str,
    surface: str,
    target_event_id: str,
    outcome: str,
    verification: str,
    task_kind: str,
    cause: str,
    acceptance_baseline_id: Optional[str] = None,
    approved_scope_change_ids: Optional[Sequence[str]] = None,
    task_type: str = "unknown",
    scope_size: str = "unknown",
    method: str = "unknown",
    policy_version: Optional[str] = None,
    model_config_version: Optional[str] = None,
    runtime_config_version: Optional[str] = None,
    recorder_config_version: Optional[str] = None,
) -> Emission:
    if not isinstance(target_event_id, str) or _EVENT_ID.fullmatch(target_event_id) is None:
        raise DeclarationError("correction target event id is invalid")
    if outcome not in TERMINAL_OUTCOMES or verification not in VERIFICATION - {
        "unknown",
        "not-applicable",
    }:
        raise DeclarationError("terminal correction state is invalid")
    if task_kind not in TASK_KINDS or cause not in CAUSES:
        raise DeclarationError("terminal correction classification is invalid")
    if task_type not in TASK_TYPES or scope_size not in SCOPE_SIZES or method not in METHODS:
        raise DeclarationError("terminal correction tags are invalid")
    if acceptance_baseline_id is not None:
        _bounded_reference(acceptance_baseline_id, "acceptance baseline")
    scope_changes = (
        None
        if approved_scope_change_ids is None
        else _bounded_reference_list(approved_scope_change_ids, "approved scope changes")
    )
    configuration_values = {
        "policy_version": policy_version,
        "model_config_version": model_config_version,
        "runtime_config_version": runtime_config_version,
        "recorder_config_version": recorder_config_version,
    }
    for label, value in configuration_values.items():
        if value is not None and (
            not isinstance(value, str) or _CONFIG_VERSION.fullmatch(value) is None
        ):
            raise DeclarationError("{} is invalid".format(label))
    if outcome == "complete" and (
        acceptance_baseline_id is None
        or scope_changes is None
        or task_type in {"unknown", "not-applicable"}
        or scope_size in {"unknown", "not-applicable"}
        or method in {"unknown", "not-applicable"}
    ):
        raise DeclarationError(
            "complete correction requires baseline, scope-change set, and explicit tags"
        )
    observation = _observation(
        session=session,
        runtime_family=runtime_family,
        surface=surface,
        event="correction",
        phase="reporting",
        activity="model-active",
        payload=_payload(
            outcome=outcome,
            task_kind=task_kind,
            cause=cause,
            verification=verification,
            correction_event_id=target_event_id,
            correction_provenance="agent-declared",
            acceptance_baseline_id=acceptance_baseline_id,
            acceptance_baseline_provenance=(
                "agent-declared" if acceptance_baseline_id is not None else "unknown"
            ),
            approved_scope_change_ids=scope_changes or (),
            scope_change_provenance=(
                "agent-declared" if scope_changes is not None else "unknown"
            ),
            task_kind_provenance="agent-declared",
            task_type=task_type,
            task_type_provenance=(
                "agent-declared" if task_type not in {"unknown", "not-applicable"} else "unknown"
            ),
            scope_size=scope_size,
            scope_size_provenance=(
                "agent-declared" if scope_size not in {"unknown", "not-applicable"} else "unknown"
            ),
            method=method,
            method_provenance=(
                "agent-declared" if method not in {"unknown", "not-applicable"} else "unknown"
            ),
            policy_version=policy_version,
            policy_provenance="agent-declared" if policy_version is not None else "unknown",
            model_config_version=model_config_version,
            model_config_provenance=(
                "agent-declared" if model_config_version is not None else "unknown"
            ),
            runtime_config_version=runtime_config_version,
            runtime_config_provenance=(
                "agent-declared" if runtime_config_version is not None else "unknown"
            ),
            recorder_config_version=recorder_config_version,
            recorder_config_provenance=(
                "agent-declared" if recorder_config_version is not None else "unknown"
            ),
        ),
        coverage=_coverage(
            terminal_delivery="partial",
            scope="complete" if outcome == "complete" else "partial",
            verification="complete",
        ),
    )
    return observation, _source_key(
        "correction-terminal",
        session,
        target_event_id,
        outcome,
        verification,
        task_kind,
        cause,
        acceptance_baseline_id,
        scope_changes,
        task_type,
        scope_size,
        method,
        configuration_values,
    )


def _bounded_reference(value: str, label: str) -> str:
    if not isinstance(value, str) or _REFERENCE_ID.fullmatch(value) is None:
        raise DeclarationError("{} id is invalid".format(label))
    return value


def _bounded_reference_list(values: Sequence[str], label: str) -> List[str]:
    if isinstance(values, (str, bytes)):
        raise DeclarationError("{} must be a list".format(label))
    result = list(values)
    if len(result) > 32 or len(set(result)) != len(result):
        raise DeclarationError("{} must be bounded and unique".format(label))
    return [_bounded_reference(item, label) for item in result]
