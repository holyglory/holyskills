"""Outcome-aware summaries over the cold JSONL projection."""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import re
from typing import Any, DefaultDict, Dict, Iterable, List, Optional, Sequence, Tuple

from .contract import ContractValidationError, canonical_json, validate_durable_event


MAX_LEDGER_LINE = 256 * 1024
TOKEN_KEYS = ("input", "cached_input", "output", "reasoning_output", "tool", "other")
PHASES = ("planning", "implementation", "testing", "deployment", "reporting", "unattributed")
ACTIVITIES = ("model-active", "tool-active", "external-wait", "user-wait", "blocked-wait", "unattributed")
ACTIVE_ACTIVITIES = ("model-active", "tool-active")
MAX_STANDALONE_TASKS = 100
SUPPORTED_EVENT_SCHEMA_VERSIONS = ("1.0", "1.1", "1.2")
EXTENDED_EVENT_SCHEMA_VERSIONS = {"1.1", "1.2"}
_CLOCK_DOMAIN_RE = re.compile(r"^clock_[0-9a-f]{32}$")
_MONOTONIC_NS_RE = re.compile(r"^(0|[1-9][0-9]{0,29})$")
_AUTHORITATIVE_TIMING_PROVENANCE = "runtime-observed"


class ReportingError(RuntimeError):
    pass


def read_ledger(path: Path) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    seen = set()
    try:
        stream = path.open("rb")
    except OSError as error:
        raise ReportingError("cannot open the efficiency ledger") from error
    with stream:
        for number, raw in enumerate(stream, start=1):
            if len(raw) > MAX_LEDGER_LINE:
                raise ReportingError("ledger line {} exceeds the size limit".format(number))
            if not raw.endswith(b"\n") or raw.endswith(b"\r\n"):
                raise ReportingError("ledger line {} is not canonical LF JSONL".format(number))
            try:
                event = json.loads(raw[:-1].decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ReportingError("ledger line {} is not valid UTF-8 JSON".format(number)) from error
            try:
                validate_durable_event(event)
                canonical = canonical_json(event).encode("utf-8")
            except (ContractValidationError, TypeError) as error:
                raise ReportingError(
                    "ledger line {} violates the durable event contract".format(number)
                ) from error
            if raw[:-1] != canonical:
                raise ReportingError("ledger line {} is not canonical JSON".format(number))
            if event["event_id"] in seen:
                raise ReportingError("ledger contains a duplicate event_id")
            seen.add(event["event_id"])
            events.append(event)
    return events


def _union(intervals: Sequence[Tuple[int, int]]) -> int:
    if not intervals:
        return 0
    total = 0
    start, end = sorted(intervals)[0]
    for next_start, next_end in sorted(intervals)[1:]:
        if next_start <= end:
            end = max(end, next_end)
        else:
            total += end - start
            start, end = next_start, next_end
    return total + end - start


def _span_intervals(events: Sequence[Dict[str, Any]]) -> Tuple[Dict[str, Optional[str]], Dict[str, Optional[str]]]:
    starts: Dict[Tuple[str, str], Dict[str, Any]] = {}
    invalid_keys = set()
    phase_intervals: DefaultDict[str, DefaultDict[str, List[Tuple[int, int]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    activity_intervals: DefaultDict[str, DefaultDict[str, List[Tuple[int, int]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    unknown_phase = set()
    unknown_activity = set()

    def mark_phase_unknown(event: Dict[str, Any]) -> None:
        classification = event.get("classification", {})
        phase = classification.get("phase")
        if phase in PHASES:
            unknown_phase.add(phase)

    def mark_activity_unknown(event: Dict[str, Any]) -> None:
        classification = event.get("classification", {})
        activity = classification.get("activity_state")
        if activity in ACTIVITIES:
            unknown_activity.add(activity)

    def mark_unknown(event: Dict[str, Any]) -> None:
        mark_phase_unknown(event)
        mark_activity_unknown(event)

    for event in events:
        payload = event.get("payload", {})
        span_id = payload.get("span_id")
        domain = event.get("clock_domain")
        if not span_id or not domain:
            continue
        key = (domain, span_id)
        if key in invalid_keys:
            mark_unknown(event)
            continue
        if event.get("event") == "span.start":
            prior = starts.pop(key, None)
            if prior is not None:
                mark_unknown(prior)
                mark_unknown(event)
                invalid_keys.add(key)
                continue
            starts[key] = event
            continue
        if event.get("event") != "span.end":
            continue
        start_event = starts.pop(key, None)
        if start_event is None:
            mark_unknown(event)
            invalid_keys.add(key)
            continue
        try:
            start = int(start_event["monotonic_ns"])
            end = int(event["monotonic_ns"])
        except (KeyError, TypeError, ValueError):
            mark_unknown(start_event)
            mark_unknown(event)
            continue
        if end < start:
            mark_unknown(start_event)
            mark_unknown(event)
            continue
        start_class = start_event.get("classification", {})
        end_class = event.get("classification", {})
        phase = start_class.get("phase")
        activity = start_class.get("activity_state")
        if phase == end_class.get("phase") and phase in PHASES:
            phase_intervals[phase][domain].append((start, end))
        else:
            mark_phase_unknown(start_event)
            mark_phase_unknown(event)
        if activity == end_class.get("activity_state") and activity in ACTIVITIES:
            activity_intervals[activity][domain].append((start, end))
        else:
            mark_activity_unknown(start_event)
            mark_activity_unknown(event)

    for start_event in starts.values():
        mark_unknown(start_event)

    phase_result: Dict[str, Optional[str]] = {}
    for phase in PHASES:
        domains = phase_intervals.get(phase, {})
        phase_result[phase] = None
        if phase not in unknown_phase and len(domains) == 1:
            phase_result[phase] = str(_union(next(iter(domains.values()))))
    activity_result: Dict[str, Optional[str]] = {}
    for activity in ACTIVITIES:
        domains = activity_intervals.get(activity, {})
        activity_result[activity] = None
        if activity not in unknown_activity and len(domains) == 1:
            activity_result[activity] = str(_union(next(iter(domains.values()))))
    return phase_result, activity_result


_ROOT_OR_UNIDENTIFIED = "__root_or_unidentified__"


def _agent_group(event: Dict[str, Any]) -> str:
    agent_id = event.get("identity", {}).get("agent_id")
    return agent_id if isinstance(agent_id, str) else _ROOT_OR_UNIDENTIFIED


def _per_agent_active_time(events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Union matched active spans per agent without collapsing concurrency."""

    starts: Dict[Tuple[str, str], Dict[str, Any]] = {}
    invalid_keys = set()
    intervals: DefaultDict[
        str, DefaultDict[str, DefaultDict[str, List[Tuple[int, int]]]]
    ] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    all_active: DefaultDict[str, DefaultDict[str, List[Tuple[int, int]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    uncertain_groups = set()
    uncertain_activities: DefaultDict[str, set] = defaultdict(set)
    activity_provenance: DefaultDict[str, set] = defaultdict(set)
    measurement_provenance: DefaultDict[str, set] = defaultdict(set)
    seen_groups = set()

    def mark_uncertain(event: Dict[str, Any]) -> None:
        classification = event.get("classification", {})
        activity = classification.get("activity_state")
        if activity not in ACTIVE_ACTIVITIES:
            return
        group = _agent_group(event)
        seen_groups.add(group)
        uncertain_groups.add(group)
        uncertain_activities[group].add(activity)
        activity_provenance[group].add(
            classification.get("activity_provenance", "unknown")
        )
        measurement_provenance[group].add(
            event.get("measurement", {}).get("provenance", "unknown")
        )

    for event in events:
        if event.get("event") not in {"span.start", "span.end"}:
            continue
        span_id = event.get("payload", {}).get("span_id")
        domain = event.get("clock_domain")
        if not isinstance(span_id, str) or not isinstance(domain, str):
            mark_uncertain(event)
            continue
        key = (domain, span_id)
        if key in invalid_keys:
            mark_uncertain(event)
            continue
        if event.get("event") == "span.start":
            prior = starts.pop(key, None)
            if prior is not None:
                mark_uncertain(prior)
                mark_uncertain(event)
                invalid_keys.add(key)
            else:
                starts[key] = event
            continue
        start_event = starts.pop(key, None)
        if start_event is None:
            mark_uncertain(event)
            invalid_keys.add(key)
            continue

        start_group = _agent_group(start_event)
        end_group = _agent_group(event)
        start_class = start_event.get("classification", {})
        end_class = event.get("classification", {})
        start_activity = start_class.get("activity_state")
        end_activity = end_class.get("activity_state")
        if start_group != end_group or start_activity != end_activity:
            mark_uncertain(start_event)
            mark_uncertain(event)
            continue
        if start_activity not in ACTIVE_ACTIVITIES:
            continue
        try:
            start = int(start_event["monotonic_ns"])
            end = int(event["monotonic_ns"])
        except (KeyError, TypeError, ValueError):
            mark_uncertain(start_event)
            mark_uncertain(event)
            continue
        if end < start:
            mark_uncertain(start_event)
            mark_uncertain(event)
            continue
        seen_groups.add(start_group)
        intervals[start_group][start_activity][domain].append((start, end))
        all_active[start_group][domain].append((start, end))
        activity_provenance[start_group].update(
            {
                start_class.get("activity_provenance", "unknown"),
                end_class.get("activity_provenance", "unknown"),
            }
        )
        measurement_provenance[start_group].update(
            {
                start_event.get("measurement", {}).get("provenance", "unknown"),
                event.get("measurement", {}).get("provenance", "unknown"),
            }
        )

    for start_event in starts.values():
        mark_uncertain(start_event)

    def summarize_group(group: str) -> Dict[str, Any]:
        domains = all_active.get(group, {})
        by_clock_domain = {
            domain: str(_union(values)) for domain, values in sorted(domains.items())
        }
        total = None
        if group not in uncertain_groups and len(domains) == 1:
            total = next(iter(by_clock_domain.values()))
        by_activity: Dict[str, Optional[str]] = {}
        for activity in ACTIVE_ACTIVITIES:
            activity_domains = intervals.get(group, {}).get(activity, {})
            by_activity[activity] = None
            if (
                activity not in uncertain_activities[group]
                and len(activity_domains) == 1
            ):
                by_activity[activity] = str(
                    _union(next(iter(activity_domains.values())))
                )
        return {
            "active_interval_union_ns": total,
            "by_activity": by_activity,
            "by_clock_domain": by_clock_domain,
            "coverage": (
                "unknown"
                if group in uncertain_groups or not domains
                else "partial"
            ),
            "measurement_provenance": sorted(measurement_provenance[group]),
            "activity_attribution_provenance": sorted(
                activity_provenance[group]
            ),
        }

    by_agent = {
        group: summarize_group(group)
        for group in sorted(seen_groups)
        if group != _ROOT_OR_UNIDENTIFIED
    }
    root_or_unidentified = (
        summarize_group(_ROOT_OR_UNIDENTIFIED)
        if _ROOT_OR_UNIDENTIFIED in seen_groups
        else None
    )
    included = list(by_agent.values())
    if root_or_unidentified is not None:
        included.append(root_or_unidentified)
    values = [item["active_interval_union_ns"] for item in included]
    summed = None
    if values and all(value is not None for value in values):
        summed = str(sum(int(value) for value in values if value is not None))
    return {
        "by_agent": by_agent,
        "root_or_unidentified": root_or_unidentified,
        "summed_per_agent_active_ns": summed,
        "included_group_count": len(included),
    }


def _effective_usage_events(events: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Prefer exact hook-correlated rollout counters over duplicate OTLP rows."""

    usage = [event for event in events if event.get("event") == "usage.observed"]
    task_local = [
        event
        for event in usage
        if event.get("runtime", {}).get("family") == "codex"
        and event.get("adapter", {}).get("name") == "codex-hooks"
        and event.get("payload", {}).get("source_event") == "unknown"
    ]
    if not task_local:
        return usage
    return task_local + [
        event
        for event in usage
        if event.get("adapter", {}).get("name") not in {"codex-hooks", "codex-otel"}
    ]


def _token_totals(events: Sequence[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    usage = _effective_usage_events(events)
    totals: Dict[str, Optional[str]] = {}
    for key in TOKEN_KEYS:
        values = []
        authoritative = True
        for event in usage:
            measurement = event.get("measurement", {})
            if measurement.get("provenance") != "runtime-observed" or measurement.get(
                "counter_source"
            ) not in {"provider-native", "runtime-native"}:
                authoritative = False
            values.append(measurement.get("tokens", {}).get(key))
        if not values or not authoritative or any(value is None for value in values):
            totals[key] = None
            continue
        try:
            totals[key] = str(sum(int(value) for value in values))
        except (TypeError, ValueError):
            totals[key] = None
    return totals


def _schema_version_counts(events: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    counts: DefaultDict[str, int] = defaultdict(int)
    for event in events:
        version = event.get("schema_version")
        counts[version if isinstance(version, str) else "unknown"] += 1
    return dict(sorted(counts.items()))


def _schema_compatibility(counts: Dict[str, int]) -> str:
    versions = {version for version, count in counts.items() if count}
    if not versions:
        return "empty"
    if not versions.issubset(set(SUPPORTED_EVENT_SCHEMA_VERSIONS)):
        return "unsupported"
    if versions == {"1.0"}:
        return "v1.0-compatible-metadata-unavailable"
    if versions == {"1.1"}:
        return "v1.1"
    if versions == {"1.2"}:
        return "v1.2"
    if versions == {"1.1", "1.2"}:
        return "mixed-v1.1-v1.2-compatible"
    return "mixed-v1.0-current-compatible"


def _tokens_by_phase(events: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Aggregate only an observation's explicit, non-inferred phase label."""

    grouped: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
    for event in _effective_usage_events(events):
        classification = event.get("classification", {})
        phase = classification.get("phase")
        phase_provenance = classification.get("phase_provenance")
        if (
            phase not in PHASES
            or phase == "unattributed"
            or phase_provenance not in {"runtime-observed", "agent-declared"}
        ):
            phase = "unattributed"
        grouped[phase].append(event)

    result: Dict[str, Dict[str, Any]] = {}
    for phase in PHASES:
        usage = grouped.get(phase, [])
        tokens: Dict[str, Optional[str]] = {}
        for key in TOKEN_KEYS:
            values: List[Any] = []
            authoritative = True
            for event in usage:
                measurement = event.get("measurement", {})
                if measurement.get("provenance") != "runtime-observed":
                    authoritative = False
                values.append(measurement.get("tokens", {}).get(key))
            if not values or not authoritative or any(value is None for value in values):
                tokens[key] = None
                continue
            try:
                tokens[key] = str(sum(int(value) for value in values))
            except (TypeError, ValueError):
                tokens[key] = None
        result[phase] = {
            "tokens": tokens,
            "usage_event_count": len(usage),
            "measurement_provenance": sorted(
                {
                    event.get("measurement", {}).get("provenance", "unknown")
                    for event in usage
                }
            ),
            "phase_attribution_provenance": sorted(
                {
                    event.get("classification", {}).get(
                        "phase_provenance", "unknown"
                    )
                    for event in usage
                }
            ),
        }
    return result


def _recorder_overhead(events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    observed: List[int] = []
    provenances = set()
    authoritative_count = 0
    for event in events:
        measurement = event.get("measurement", {})
        provenance = measurement.get("provenance", "unknown")
        provenances.add(provenance)
        value = measurement.get("recorder_overhead_ns")
        if provenance != "runtime-observed" or value is None:
            continue
        try:
            observed.append(int(value))
            authoritative_count += 1
        except (TypeError, ValueError):
            continue
    applicable_count = len(events)
    if authoritative_count == applicable_count and applicable_count:
        coverage = "complete"
        total: Optional[str] = str(sum(observed))
    else:
        coverage = "partial" if authoritative_count else "unknown"
        total = None
    return {
        "total_ns": total,
        "observed_sum_ns": str(sum(observed)) if observed else None,
        "applicable_event_count": applicable_count,
        "authoritative_observation_count": authoritative_count,
        "coverage": coverage,
        "measurement_provenance": sorted(provenances),
    }


def _runtime_native_duration_sums(events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Sum authoritative host durations without calling them elapsed time.

    Claude can report an execution-only duration on ``span.end`` without a
    matching recorder-clock ``span.start``.  That value is useful, but it is
    neither a monotonic interval union nor wall time.  Hook and OTLP delivery
    can also describe the same host span, so observations are collapsed by the
    already-opaque runtime/task/span identity before summing.  A conflicting
    duplicate makes the affected attribution bucket unknown instead of
    selecting whichever source happened to arrive first.  Definite success
    and tool-category values are part of that consistency check; an unknown
    value may coexist with one definite observation but cannot overrule it.
    """

    grouped: DefaultDict[Tuple[str, Optional[str], str], List[Dict[str, Any]]] = (
        defaultdict(list)
    )
    for event in events:
        if event.get("event") != "span.end":
            continue
        duration = event.get("payload", {}).get("duration_ns")
        if duration is None or event.get("measurement", {}).get("provenance") != "runtime-observed":
            continue
        span_id = event.get("payload", {}).get("span_id")
        runtime_family = event.get("runtime", {}).get("family")
        if not isinstance(span_id, str) or not isinstance(runtime_family, str):
            continue
        identity = event.get("identity", {})
        grouped[
            (
                runtime_family,
                identity.get("session_id"),
                span_id,
            )
        ].append(event)

    phase_totals: DefaultDict[str, int] = defaultdict(int)
    activity_totals: DefaultDict[str, int] = defaultdict(int)
    phase_counts: DefaultDict[str, int] = defaultdict(int)
    activity_counts: DefaultDict[str, int] = defaultdict(int)
    phase_conflicts: DefaultDict[str, int] = defaultdict(int)
    activity_conflicts: DefaultDict[str, int] = defaultdict(int)
    phase_provenance: DefaultDict[str, set] = defaultdict(set)
    activity_provenance: DefaultDict[str, set] = defaultdict(set)
    uncertain_phases = set()
    uncertain_activities = set()
    observed_spans = 0
    duplicate_observations = 0
    conflicting_spans = 0

    for observations in grouped.values():
        duplicate_observations += max(0, len(observations) - 1)
        durations = set()
        successes = set()
        tool_categories = set()
        phase_attributions = set()
        activity_attributions = set()
        for event in observations:
            payload = event.get("payload", {})
            try:
                durations.add(int(payload["duration_ns"]))
            except (KeyError, TypeError, ValueError):
                durations.add(None)
            success = payload.get("success")
            if isinstance(success, bool):
                successes.add(success)
            tool_category = payload.get("tool_category")
            if isinstance(tool_category, str) and tool_category != "unknown":
                tool_categories.add(tool_category)
            classification = event.get("classification", {})
            phase = classification.get("phase")
            activity = classification.get("activity_state")
            if phase in PHASES:
                phase_attributions.add((phase, classification.get("phase_provenance", "unknown")))
            if activity in ACTIVITIES:
                activity_attributions.add(
                    (activity, classification.get("activity_provenance", "unknown"))
                )

        conflicting = (
            len(durations) != 1
            or None in durations
            or len(successes) > 1
            or len(tool_categories) > 1
        )
        if conflicting:
            conflicting_spans += 1
            uncertain_phases.update(item[0] for item in phase_attributions)
            uncertain_activities.update(item[0] for item in activity_attributions)
            for phase in {item[0] for item in phase_attributions}:
                phase_conflicts[phase] += 1
            for activity in {item[0] for item in activity_attributions}:
                activity_conflicts[activity] += 1
            for phase, provenance in phase_attributions:
                phase_provenance[phase].add(provenance)
            for activity, provenance in activity_attributions:
                activity_provenance[activity].add(provenance)
            continue

        duration = next(iter(durations))
        observed_spans += 1
        if len(phase_attributions) == 1:
            phase, provenance = next(iter(phase_attributions))
            phase_totals[phase] += duration
            phase_counts[phase] += 1
            phase_provenance[phase].add(provenance)
        else:
            uncertain_phases.update(item[0] for item in phase_attributions)
            for phase in {item[0] for item in phase_attributions}:
                phase_conflicts[phase] += 1
            for phase, provenance in phase_attributions:
                phase_provenance[phase].add(provenance)
        if len(activity_attributions) == 1:
            activity, provenance = next(iter(activity_attributions))
            activity_totals[activity] += duration
            activity_counts[activity] += 1
            activity_provenance[activity].add(provenance)
        else:
            uncertain_activities.update(item[0] for item in activity_attributions)
            for activity in {item[0] for item in activity_attributions}:
                activity_conflicts[activity] += 1
            for activity, provenance in activity_attributions:
                activity_provenance[activity].add(provenance)

    by_phase: Dict[str, Dict[str, Any]] = {}
    for phase in PHASES:
        by_phase[phase] = {
            "sum_ns": (
                None
                if phase in uncertain_phases or phase_counts[phase] == 0
                else str(phase_totals[phase])
            ),
            "included_span_count": str(phase_counts[phase]),
            "conflicting_span_count": str(phase_conflicts[phase]),
            "measurement_provenance": (
                ["runtime-observed"]
                if phase_counts[phase] or phase_conflicts[phase]
                else []
            ),
            "attribution_provenance": sorted(phase_provenance[phase]),
        }
    by_activity: Dict[str, Dict[str, Any]] = {}
    for activity in ACTIVITIES:
        by_activity[activity] = {
            "sum_ns": (
                None
                if activity in uncertain_activities or activity_counts[activity] == 0
                else str(activity_totals[activity])
            ),
            "included_span_count": str(activity_counts[activity]),
            "conflicting_span_count": str(activity_conflicts[activity]),
            "measurement_provenance": (
                ["runtime-observed"]
                if activity_counts[activity] or activity_conflicts[activity]
                else []
            ),
            "attribution_provenance": sorted(activity_provenance[activity]),
        }
    return {
        "by_phase": by_phase,
        "by_activity": by_activity,
        "observed_span_count": str(observed_spans),
        "duplicate_observation_count": str(duplicate_observations),
        "conflicting_span_count": str(conflicting_spans),
    }


def _timing_point(event: Optional[Dict[str, Any]]) -> Optional[Tuple[str, int]]:
    if event is None:
        return None
    clock_domain = event.get("clock_domain")
    monotonic_ns = event.get("monotonic_ns")
    if (
        not isinstance(clock_domain, str)
        or _CLOCK_DOMAIN_RE.fullmatch(clock_domain) is None
        or not isinstance(monotonic_ns, str)
        or _MONOTONIC_NS_RE.fullmatch(monotonic_ns) is None
    ):
        return None
    return clock_domain, int(monotonic_ns)


def _elapsed(first: Optional[Dict[str, Any]], last: Optional[Dict[str, Any]]) -> Optional[str]:
    if first is None or last is None:
        return None
    first_point = _timing_point(first)
    last_point = _timing_point(last)
    if first_point is None or last_point is None or first_point[0] != last_point[0]:
        return None
    value = last_point[1] - first_point[1]
    return str(value) if value >= 0 else None


def _complete_authoritative_boundary(
    event: Optional[Dict[str, Any]], coverage_dimension: str
) -> Optional[Dict[str, Any]]:
    """Return an endpoint only when the runtime measured its exact boundary.

    Receiver-assigned timestamps do not make an agent declaration or inferred
    source boundary authoritative.  The relevant coverage dimension must be
    complete and the source measurement itself must be runtime-observed.
    """

    if event is None:
        return None
    if event.get("coverage", {}).get(coverage_dimension) != "complete":
        return None
    if event.get("measurement", {}).get("provenance") != _AUTHORITATIVE_TIMING_PROVENANCE:
        return None
    return event


def _timing_endpoint_evidence(
    event: Optional[Dict[str, Any]], coverage_dimension: Optional[str]
) -> Dict[str, Any]:
    point = _timing_point(event)
    coverage = (
        event.get("coverage", {}).get(coverage_dimension, "unknown")
        if event is not None and coverage_dimension is not None
        else "not-applicable"
    )
    return {
        "event": event.get("event") if event is not None else None,
        "adapter": event.get("adapter", {}).get("name") if event is not None else None,
        "coverage_dimension": coverage_dimension,
        "coverage": coverage,
        "measurement_provenance": (
            event.get("measurement", {}).get("provenance", "unknown")
            if event is not None
            else "unknown"
        ),
        "timing_basis": "receiver-monotonic-observation" if point is not None else "unknown",
        "clock_domain": point[0] if point is not None else None,
    }


def _event_sequence(event: Dict[str, Any]) -> int:
    try:
        return int(event.get("sequence", "0"))
    except (TypeError, ValueError):
        return 0


def _task_state_with_corrections(
    task_events: Sequence[Dict[str, Any]],
) -> Tuple[Dict[str, Dict[str, Any]], Optional[Tuple[Dict[str, Any], Dict[str, Any]]], Dict[str, Any]]:
    targetable = {
        event.get("event_id"): event
        for event in task_events
        if event.get("event") in {"requirement.status", "task.terminal"}
        and isinstance(event.get("event_id"), str)
    }
    valid_corrections: Dict[str, Tuple[Dict[str, Any], Dict[str, Any]]] = {}
    correction_items: List[Dict[str, Any]] = []
    legacy_unsupported = 0
    unresolved = 0
    for event in task_events:
        if event.get("event") != "correction":
            continue
        correction = event.get("payload", {}).get("correction")
        if (
            event.get("schema_version") not in EXTENDED_EVENT_SCHEMA_VERSIONS
            or not isinstance(correction, dict)
        ):
            legacy_unsupported += 1
            correction_items.append(
                {
                    "event_id": event.get("event_id"),
                    "target_event_id": None,
                    "target_event": None,
                    "provenance": "unknown",
                    "status": "unsupported-v1.0",
                }
            )
            continue
        target_id = correction.get("event_id")
        target = targetable.get(target_id)
        status = "applied"
        if target is None:
            status = "target-missing-or-cross-task"
        elif _event_sequence(target) >= _event_sequence(event):
            status = "target-not-earlier"
        elif target.get("event") == "requirement.status":
            target_requirement = target.get("payload", {}).get("requirement_id")
            corrected_requirement = event.get("payload", {}).get("requirement_id")
            if target_requirement != corrected_requirement:
                status = "requirement-id-mismatch"
        if status == "applied":
            valid_corrections[event["event_id"]] = (target, event)
        else:
            unresolved += 1
        correction_items.append(
            {
                "event_id": event.get("event_id"),
                "target_event_id": target_id,
                "target_event": target.get("event") if target is not None else None,
                "provenance": correction.get("provenance", "unknown"),
                "status": status,
            }
        )

    requirements: Dict[str, Dict[str, Any]] = {}
    terminal_state: Optional[Tuple[Dict[str, Any], Dict[str, Any]]] = None

    def apply_requirement(
        boundary_event: Dict[str, Any], payload_event: Dict[str, Any]
    ) -> None:
        payload = payload_event.get("payload", {})
        boundary_payload = boundary_event.get("payload", {})
        requirement_id = payload.get("requirement_id")
        if not isinstance(requirement_id, str):
            return
        # Requirement corrections replace status and verification.  A
        # correction carrying evidence replaces the original evidence as part
        # of the corrected state; an evidence-free correction retains the
        # original references rather than erasing useful verification history.
        boundary_evidence = boundary_payload.get("evidence")
        corrected_evidence = payload.get("evidence")
        evidence = boundary_evidence
        if (
            payload_event is not boundary_event
            and isinstance(corrected_evidence, dict)
            and corrected_evidence.get("refs")
        ):
            evidence = corrected_evidence
        requirements[requirement_id] = {
            "status": payload.get("requirement_status"),
            "verification": payload.get("verification"),
            "provenance": payload_event.get("measurement", {}).get(
                "provenance", "unknown"
            ),
            "evidence_refs": (
                list(evidence.get("refs", [])) if isinstance(evidence, dict) else None
            ),
            "evidence_provenance": (
                evidence.get("provenance", "unknown")
                if isinstance(evidence, dict)
                else "unavailable-v1.0"
            ),
            "source_event_id": boundary_event.get("event_id"),
            "corrected_by_event_id": (
                payload_event.get("event_id")
                if payload_event is not boundary_event
                else None
            ),
        }

    for event in task_events:
        if event.get("event") == "requirement.status":
            apply_requirement(event, event)
        elif event.get("event") == "task.terminal":
            terminal_state = (event, event)
        elif event.get("event") == "correction" and event.get("event_id") in valid_corrections:
            target, correction_event = valid_corrections[event["event_id"]]
            if target.get("event") == "requirement.status":
                apply_requirement(target, correction_event)
            else:
                terminal_state = (target, correction_event)

    versions = _schema_version_counts(task_events)
    correction_support = _schema_compatibility(versions)
    return requirements, terminal_state, {
        "schema_support": correction_support,
        "applied_count": len(valid_corrections),
        "unresolved_count": unresolved,
        "legacy_unsupported_count": legacy_unsupported,
        "items": correction_items,
    }


def _terminal_extensions(
    terminal_state: Optional[Tuple[Dict[str, Any], Dict[str, Any]]]
) -> Dict[str, Any]:
    if terminal_state is None:
        return {
            "availability": "unavailable-no-terminal",
            "task_metadata": None,
            "configuration": None,
            "evidence": None,
        }
    _, payload_event = terminal_state
    if payload_event.get("schema_version") not in EXTENDED_EVENT_SCHEMA_VERSIONS:
        return {
            "availability": "unavailable-v1.0",
            "task_metadata": None,
            "configuration": None,
            "evidence": None,
        }
    payload = payload_event.get("payload", {})
    return {
        "availability": "available-v1.1",
        "task_metadata": payload.get("task_metadata"),
        "configuration": payload.get("configuration"),
        "evidence": payload.get("evidence"),
    }


def _lineage_link(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if (
        event.get("event") != "lineage.link"
        or event.get("schema_version") not in EXTENDED_EVENT_SCHEMA_VERSIONS
    ):
        return None
    payload = event.get("payload", {})
    link = payload.get("link")
    if not isinstance(link, dict):
        return None
    return {
        "event_id": event.get("event_id"),
        "target_task_id": link.get("task_id"),
        "target_lineage_id": link.get("lineage_id"),
        "provenance": link.get("provenance", "unknown"),
        "task_kind": payload.get("task_kind", "unknown"),
        "cause": payload.get("cause", "unknown"),
    }


def summarize(
    events: Iterable[Dict[str, Any]],
    project_labels: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    unique: Dict[str, Dict[str, Any]] = {}
    for event in events:
        event_id = event.get("event_id")
        if isinstance(event_id, str):
            unique.setdefault(event_id, event)

    # A provider event may arrive before its exact task.start and immutable
    # ledger history is never rewritten.  Correlate only an unambiguous
    # runtime/session/turn triple at report time so early prompt-correlated
    # usage is included after the boundary arrives; changed or unmatched turns
    # remain honestly unlinked.
    turn_tasks: DefaultDict[Tuple[str, str, str], set] = defaultdict(set)
    for event in unique.values():
        if event.get("event") != "task.start":
            continue
        identity = event.get("identity", {})
        runtime_family = event.get("runtime", {}).get("family")
        session_id = identity.get("session_id")
        turn_id = identity.get("turn_id")
        task_id = identity.get("task_id")
        if all(isinstance(value, str) for value in (runtime_family, session_id, turn_id, task_id)):
            turn_tasks[(runtime_family, session_id, turn_id)].add(task_id)
    exact_turn_tasks = {
        key: next(iter(task_ids))
        for key, task_ids in turn_tasks.items()
        if len(task_ids) == 1
    }

    grouped: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
    unlinked = 0
    for event in unique.values():
        task_id = event.get("identity", {}).get("task_id")
        if task_id is None:
            identity = event.get("identity", {})
            key = (
                event.get("runtime", {}).get("family"),
                identity.get("session_id"),
                identity.get("turn_id"),
            )
            if all(isinstance(value, str) for value in key):
                task_id = exact_turn_tasks.get(key)
        if task_id is None:
            unlinked += 1
        else:
            grouped[task_id].append(event)

    native_lineages: Dict[str, Optional[str]] = {}
    lineage_links: Dict[str, Dict[str, Any]] = {}
    for task_id, task_events in grouped.items():
        ordered = sorted(task_events, key=_event_sequence)
        starts = [event for event in ordered if event.get("event") == "task.start"]
        identity_event = starts[0] if starts else ordered[-1]
        native_lineages[task_id] = identity_event.get("identity", {}).get(
            "lineage_id"
        )
        links = [link for event in ordered if (link := _lineage_link(event)) is not None]
        if links:
            lineage_links[task_id] = links[-1]

    lineage_cache: Dict[str, Tuple[Optional[str], str]] = {}

    def resolve_lineage(
        task_id: str, trail: Optional[set] = None
    ) -> Tuple[Optional[str], str]:
        if task_id in lineage_cache:
            return lineage_cache[task_id]
        visited = set() if trail is None else set(trail)
        if task_id in visited:
            return None, "cycle"
        visited.add(task_id)
        link = lineage_links.get(task_id)
        if link is None:
            result = (native_lineages.get(task_id), "not-linked")
            lineage_cache[task_id] = result
            return result
        target_task = link.get("target_task_id")
        if not isinstance(target_task, str) or target_task not in grouped:
            result = (None, "target-missing")
            lineage_cache[task_id] = result
            return result
        target_lineage, target_status = resolve_lineage(target_task, visited)
        if target_lineage is None:
            result = (None, "target-{}".format(target_status))
            lineage_cache[task_id] = result
            return result
        declared_lineage = link.get("target_lineage_id")
        if declared_lineage != target_lineage:
            result = (None, "lineage-mismatch")
            lineage_cache[task_id] = result
            return result
        result = (target_lineage, "resolved")
        lineage_cache[task_id] = result
        return result

    tasks: List[Dict[str, Any]] = []
    for task_id, task_events in grouped.items():
        task_events.sort(key=_event_sequence)
        starts = [event for event in task_events if event.get("event") == "task.start"]
        identity_event = starts[0] if starts else task_events[-1]
        first_activities = [event for event in task_events if event.get("event") == "task.first_activity"]
        terminals = [event for event in task_events if event.get("event") == "task.terminal"]
        requirements, terminal_state, corrections = _task_state_with_corrections(
            task_events
        )
        phase_ns, activity_ns = _span_intervals(task_events)
        runtime_native_duration = _runtime_native_duration_sums(task_events)
        terminal = terminal_state[0] if terminal_state is not None else None
        terminal_payload_event = (
            terminal_state[1] if terminal_state is not None else None
        )
        terminal_payload = (
            terminal_payload_event.get("payload", {})
            if terminal_payload_event is not None
            else {}
        )
        task_start = starts[0] if starts else None
        first_activity = first_activities[0] if first_activities else None
        terminal_declaration = next(
            (
                event
                for event in reversed(terminals)
                if event.get("adapter", {}).get("name") == "agent-declaration"
            ),
            None,
        )
        delivery_boundary = next(
            (
                event
                for event in reversed(terminals)
                if event.get("coverage", {}).get("terminal_delivery") == "complete"
            ),
            None,
        )
        if delivery_boundary is None:
            delivery_boundary = terminal
        authoritative_request = _complete_authoritative_boundary(
            task_start, "request_receipt"
        )
        authoritative_first_activity = _complete_authoritative_boundary(
            first_activity, "first_activity"
        )
        authoritative_delivery = _complete_authoritative_boundary(
            delivery_boundary, "terminal_delivery"
        )
        task_schema_versions = _schema_version_counts(task_events)
        terminal_extensions = _terminal_extensions(terminal_state)
        effective_lineage_id, lineage_resolution = resolve_lineage(task_id)
        link = lineage_links.get(task_id)
        task_metadata = terminal_extensions.get("task_metadata")
        task_kind_provenance = (
            task_metadata.get("task_kind_provenance", "unknown")
            if isinstance(task_metadata, dict)
            else "unavailable-v1.0"
        )
        effective_usage = _effective_usage_events(task_events)
        has_task_local_usage = any(
            item.get("adapter", {}).get("name") == "codex-hooks"
            and item.get("payload", {}).get("source_event") == "unknown"
            for item in effective_usage
        )
        has_runtime_stop = any(
            item.get("event") == "runtime.turn_stopped" for item in task_events
        )
        tasks.append(
            {
                "task_id": task_id,
                "project_id": identity_event.get("identity", {}).get("project_id"),
                "revision_id": identity_event.get("identity", {}).get("revision_id"),
                "lineage_id": native_lineages.get(task_id),
                "target_id": identity_event.get("identity", {}).get("target_id"),
                "resolved_lineage_id": effective_lineage_id,
                "linked_work": {
                    "availability": (
                        "available-v1.1"
                        if link is not None
                        else (
                            "unavailable-v1.0"
                            if not EXTENDED_EVENT_SCHEMA_VERSIONS.intersection(
                                task_schema_versions
                            )
                            else "available-v1.1-no-link"
                        )
                    ),
                    "link_event_id": link.get("event_id") if link else None,
                    "target_task_id": link.get("target_task_id") if link else None,
                    "declared_target_lineage_id": (
                        link.get("target_lineage_id") if link else None
                    ),
                    "resolved_target_lineage_id": (
                        effective_lineage_id if link else None
                    ),
                    "task_kind": (
                        link.get("task_kind")
                        if link is not None
                        else terminal_payload.get("task_kind", "unknown")
                    ),
                    "cause": (
                        link.get("cause")
                        if link is not None
                        else terminal_payload.get("cause", "unknown")
                    ),
                    "provenance": (
                        link.get("provenance")
                        if link is not None
                        else task_kind_provenance
                    ),
                    "resolution": lineage_resolution,
                },
                "runtime": task_events[-1].get("runtime"),
                "started_at_utc": task_start.get("observed_at_utc") if task_start else None,
                "event_count": len(task_events),
                "event_schema_versions": task_schema_versions,
                "event_schema_compatibility": _schema_compatibility(
                    task_schema_versions
                ),
                "terminal_outcome": terminal_payload.get("outcome") if terminal else None,
                "request_to_delivery_ns": _elapsed(
                    authoritative_request,
                    authoritative_delivery,
                ),
                "execution_to_delivery_ns": _elapsed(
                    authoritative_first_activity,
                    authoritative_delivery,
                ),
                "observed_task_start_to_terminal_declaration_ns": _elapsed(
                    task_start,
                    terminal_declaration,
                ),
                "observed_first_activity_to_terminal_declaration_ns": _elapsed(
                    first_activity,
                    terminal_declaration,
                ),
                "timing_endpoints": {
                    "task_start": _timing_endpoint_evidence(
                        task_start, "request_receipt"
                    ),
                    "first_activity": _timing_endpoint_evidence(
                        first_activity, "first_activity"
                    ),
                    "terminal_delivery": _timing_endpoint_evidence(
                        delivery_boundary, "terminal_delivery"
                    ),
                    "terminal_declaration": _timing_endpoint_evidence(
                        terminal_declaration, None
                    ),
                },
                "tokens": _token_totals(task_events),
                "tokens_by_phase": _tokens_by_phase(task_events),
                "token_coverage": (
                    "complete"
                    if effective_usage
                    and (not has_task_local_usage or has_runtime_stop)
                    and all(
                        item.get("coverage", {}).get("tokens") == "complete"
                        for item in effective_usage
                    )
                    else "partial"
                    if effective_usage
                    else "unknown"
                ),
                "token_source": (
                    "task-bound-local-runtime"
                    if has_task_local_usage
                    else "exported-runtime"
                    if effective_usage
                    else "unavailable"
                ),
                "tool_category_counts": dict(
                    sorted(
                        {
                            category: sum(
                                1
                                for event in task_events
                                if event.get("event") == "span.end"
                                and event.get("payload", {}).get("tool_category")
                                == category
                            )
                            for category in (
                                "shell",
                                "patch",
                                "mcp",
                                "web",
                                "agent",
                                "local",
                                "other",
                            )
                        }.items()
                    )
                ),
                "phase_interval_union_ns": phase_ns,
                "activity_interval_union_ns": activity_ns,
                "per_agent_active_time": _per_agent_active_time(task_events),
                "runtime_native_duration_sum": runtime_native_duration,
                "recorder_overhead": _recorder_overhead(task_events),
                "requirements": requirements,
                "terminal_metadata": terminal_extensions,
                "corrections": corrections,
                "coverage": terminal.get("coverage") if terminal else task_events[-1].get("coverage"),
                "complete": bool(
                    terminal
                    and terminal_payload.get("outcome") == "complete"
                    and requirements
                    and all(item["status"] in {"satisfied", "removed"} for item in requirements.values())
                ),
            }
        )
    tasks.sort(
        key=lambda item: (
            item.get("started_at_utc") or "",
            item["task_id"],
        )
    )
    labels = project_labels or {}
    label_counts: DefaultDict[str, int] = defaultdict(int)
    for label in labels.values():
        label_counts[label] += 1
    ordinals: DefaultDict[Optional[str], int] = defaultdict(int)
    for task in tasks:
        project_id = task.get("project_id")
        ordinals[project_id] += 1
        repository_name = labels.get(project_id) if isinstance(project_id, str) else None
        if (
            repository_name is not None
            and label_counts[repository_name] > 1
            and isinstance(project_id, str)
        ):
            repository_name = "{} [{}]".format(repository_name, project_id[-8:])
        if repository_name is None:
            repository_name = (
                "Repository {}".format(project_id[-8:])
                if isinstance(project_id, str)
                else "Unattributed repository"
            )
        task["repository_display_name"] = repository_name
        task["task_number"] = ordinals[project_id]
        task["display_name"] = "{} task {}".format(
            repository_name, task["task_number"]
        )
    all_schema_versions = _schema_version_counts(list(unique.values()))
    return {
        "schema_version": "1.2",
        "event_schema_versions": all_schema_versions,
        "event_schema_compatibility": _schema_compatibility(all_schema_versions),
        "task_count": len(tasks),
        "unlinked_event_count": unlinked,
        "tasks": tasks,
        "semantics": {
            "wall_time": "same-clock receiver-monotonic interval; unavailable unless both endpoints have complete runtime-observed boundary coverage",
            "terminal_declaration_time": "same-clock receiver-observed task-start/first-activity to agent declaration; diagnostic only, not request receipt, execution, or user-visible delivery",
            "phase_time": "monotonic interval union within one receiver clock domain",
            "phase_tokens": "sum only runtime-observed counters carrying their own runtime-observed or agent-declared phase; inferred or unknown phase claims remain unattributed and tokens are never allocated by elapsed time",
            "runtime_native_duration_sum": "arithmetic sum of runtime-observed host duration_ns values after same-span hook/OTLP deduplication; contradictory duration, definite success, definite tool category, or attribution makes affected sums unknown; not wall time or an interval union",
            "agent_active_time": "same-clock active-span unions per opaque agent plus a separate root-or-unidentified bucket; the summed per-agent value preserves concurrent work and is not interchangeable with wall time",
            "corrections": "append-only later v1.1+ corrections alter effective terminal or requirement state while retaining original and correction event references; v1.0 correction events lack target metadata and are unavailable",
            "recorder_overhead": "complete total only when every task event has an authoritative runtime-observed recorder_overhead_ns; otherwise total is null and observed coverage remains explicit",
            "unknown": "null; never reconstructed or zero-filled",
        },
    }


def _known_counter(values: Sequence[Optional[str]]) -> Dict[str, Any]:
    known = [int(value) for value in values if value is not None]
    return {
        "known_sum": str(sum(known)) if known else None,
        "known_task_count": len(known),
        "task_count": len(values),
        "coverage": "complete" if values and len(known) == len(values) else "partial" if known else "unknown",
    }


def summarize_repositories(
    events: Iterable[Dict[str, Any]],
    project_labels: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Build a bounded privacy-safe repository projection for optional UIs."""

    task_report = summarize(events, project_labels)
    grouped: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
    unattributed = 0
    for task in task_report["tasks"]:
        project_id = task.get("project_id")
        if isinstance(project_id, str):
            grouped[project_id].append(task)
        else:
            unattributed += 1

    repositories: List[Dict[str, Any]] = []
    for project_id, tasks in sorted(grouped.items()):
        tokens = {
            key: _known_counter([task["tokens"].get(key) for task in tasks])
            for key in TOKEN_KEYS
        }
        phase_tokens: Dict[str, Dict[str, Any]] = {}
        for phase in PHASES:
            phase_tokens[phase] = {
                key: _known_counter(
                    [
                        task["tokens_by_phase"][phase]["tokens"].get(key)
                        for task in tasks
                    ]
                )
                for key in TOKEN_KEYS
            }
            phase_tokens[phase]["usage_event_count"] = sum(
                task["tokens_by_phase"][phase]["usage_event_count"]
                for task in tasks
            )

        signatures: DefaultDict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)
        for task in tasks:
            metadata = task.get("terminal_metadata", {}).get("task_metadata")
            if not isinstance(metadata, dict):
                continue
            signature = (
                metadata.get("task_type"),
                metadata.get("scope_size"),
                metadata.get("method"),
            )
            if (
                all(isinstance(value, str) for value in signature)
                and "unknown" not in signature
                and "not-applicable" not in signature
                and signature[2] != "automated"
            ):
                signatures[signature].append(task)

        opportunities = []
        for signature, comparable in sorted(signatures.items()):
            if len(opportunities) >= 32:
                break
            if len(comparable) < 3:
                continue
            input_counter = _known_counter(
                [task["tokens"].get("input") for task in comparable]
            )
            tool_counts: DefaultDict[str, int] = defaultdict(int)
            for task in comparable:
                for category, count in task["tool_category_counts"].items():
                    tool_counts[category] += int(count)
            opportunities.append(
                {
                    "kind": "deterministic-workflow-candidate",
                    "task_type": signature[0],
                    "scope_size": signature[1],
                    "current_method": signature[2],
                    "occurrence_count": len(comparable),
                    "input_tokens": input_counter,
                    "tool_category_counts": dict(sorted(tool_counts.items())),
                    "basis": "at least three comparable non-automated terminal declarations",
                    "recommendation": "review the repeated sequence for a script, harness, verifier, or reusable tool boundary",
                }
            )

        outcomes: DefaultDict[str, int] = defaultdict(int)
        causes: DefaultDict[str, int] = defaultdict(int)
        for task in tasks:
            outcomes[task.get("terminal_outcome") or "unterminated"] += 1
            causes[task.get("linked_work", {}).get("cause", "unknown")] += 1
        repository = {
                "project_id": project_id,
                "task_count": len(tasks),
                "complete_task_count": sum(bool(task.get("complete")) for task in tasks),
                "outcomes": dict(sorted(outcomes.items())),
                "causes": dict(sorted(causes.items())),
                "tokens": tokens,
                "tokens_by_phase": phase_tokens,
                "request_to_delivery_ns": _known_counter(
                    [task.get("request_to_delivery_ns") for task in tasks]
                ),
                "execution_to_delivery_ns": _known_counter(
                    [task.get("execution_to_delivery_ns") for task in tasks]
                ),
                "automation_opportunities": opportunities,
            }
        if project_labels is not None:
            repository["display_name"] = tasks[0]["repository_display_name"]
        repositories.append(repository)
    return {
        "schema_version": "1.0",
        "repository_count": len(repositories),
        "unattributed_task_count": unattributed,
        "repositories": repositories,
        "semantics": {
            "identity": "installation-local opaque repository identity; no path is retained",
            "known_sum": "sum of observed authoritative values only; coverage states whether it is a complete total",
            "automation_opportunities": "conservative repeated-pattern candidates, not proof that automation is beneficial",
        },
    }


def summarize_tasks(
    events: Iterable[Dict[str, Any]],
    project_labels: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Return a bounded standalone task index with human-readable labels."""

    report = summarize(events, project_labels)
    selected = report["tasks"][-MAX_STANDALONE_TASKS:]
    tasks = []
    for task in selected:
        tasks.append(
            {
                "display_name": task["display_name"],
                "repository": task["repository_display_name"],
                "task_number": task["task_number"],
                "task_ref": task["task_id"][-8:],
                "started_at_utc": task["started_at_utc"],
                "status": task.get("terminal_outcome") or "active",
                "complete": bool(task.get("complete")),
                "token_source": task["token_source"],
                "token_coverage": task["token_coverage"],
                "tokens": task["tokens"],
                "tokens_by_phase": task["tokens_by_phase"],
                "coverage": task.get("coverage"),
            }
        )
    return {
        "schema_version": "1.0",
        "task_count": len(tasks),
        "total_task_count": len(report["tasks"]),
        "truncated": len(report["tasks"]) > len(tasks),
        "tasks": tasks,
        "semantics": {
            "identity": "private local repository basename plus chronological task number; no path or prompt is retained",
            "task_ref": "short installation-local opaque suffix for disambiguation only",
            "unknown": "null; never reconstructed or zero-filled",
            "window": "the most recent {} tasks ordered by observed task start".format(
                MAX_STANDALONE_TASKS
            ),
        },
    }
