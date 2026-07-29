"""Command-line interface for installation, runtime hooks, declarations, and reports."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError

from . import (
    CLAUDE_ORDINARY_HOOK_TELEMETRY_BUDGET_SECONDS,
    CLAUDE_HOOK_TELEMETRY_BUDGET_SECONDS,
    CLAUDE_PROMPT_HOOK_TELEMETRY_BUDGET_SECONDS,
    CLAUDE_PROMPT_HOOK_TIMEOUT_SECONDS,
    CODEX_HOOK_RUNTIME_MARGIN_SECONDS,
    CODEX_HOOK_TELEMETRY_BUDGET_SECONDS,
    CODEX_HOOK_TIMEOUT_SECONDS,
)
from .platforms import state_directory
from .runtime import (
    RuntimeConfigurationError,
    ensure_receiver,
    load_settings,
    receiver_is_healthy,
    record_local_gap,
)


TOOL_ROOT = Path(__file__).resolve().parents[1]
MAX_HOOK_BYTES = 1024 * 1024
MANAGED_ID = "holyskills-delivery-efficiency-v1"


class UnsupportedHookRuntime(RuntimeError):
    pass


def _json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True))


def _state(value: Optional[str]) -> Path:
    return state_directory(None if value is None else Path(value))


def _named_paths(values: Sequence[str], label: str) -> Dict[str, Path]:
    result: Dict[str, Path] = {}
    for raw in values:
        if "=" not in raw:
            raise ValueError("{} must use NAME=ABSOLUTE_PATH".format(label))
        name, path = raw.split("=", 1)
        if not name or name in result or not Path(path).is_absolute():
            raise ValueError("{} names must be unique and paths absolute".format(label))
        result[name] = Path(path)
    return result


def _surface(runtime_family: str) -> str:
    override = os.environ.get("HOLYSKILLS_AGENT_SURFACE")
    if override in {"cli-interactive", "cli-exec", "desktop", "ide", "unknown"}:
        return override
    if runtime_family == "codex":
        origin = os.environ.get("CODEX_INTERNAL_ORIGINATOR_OVERRIDE", "").casefold()
        if "desktop" in origin:
            return "desktop"
        if os.environ.get("TERM_PROGRAM", "").casefold() in {"vscode", "cursor"}:
            return "ide"
        return "cli-interactive"
    if runtime_family == "claude":
        entrypoint = os.environ.get("CLAUDE_CODE_ENTRYPOINT", "").casefold()
        if entrypoint.startswith("sdk") or entrypoint == "print":
            return "cli-exec"
        if os.environ.get("TERM_PROGRAM", "").casefold() in {"vscode", "cursor"}:
            return "ide"
        return "cli-interactive"
    return "cli-interactive"


def _session(runtime_family: str, explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    names = (
        ("CODEX_THREAD_ID",)
        if runtime_family == "codex"
        else ("CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID")
    )
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    raise ValueError("runtime session id is unavailable; pass --session explicitly")


def _read_hook_input() -> bytes:
    raw = sys.stdin.buffer.read(MAX_HOOK_BYTES + 1)
    if len(raw) > MAX_HOOK_BYTES:
        raise ValueError("hook payload exceeds the bounded input limit")
    return raw


def _remaining_hook_budget(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RuntimeConfigurationError("runtime hook telemetry budget was exhausted")
    return remaining


def _hook_gap_code(error: BaseException) -> str:
    """Reduce a hook failure to one truthful, nonsensitive diagnostic code."""

    from .codex import SourceEventError
    from .storage import RecorderError

    if isinstance(error, UnsupportedHookRuntime):
        return "unsupported-runtime-event"
    if isinstance(error, SourceEventError):
        return "malformed-source-event"
    if isinstance(error, RecorderError):
        return "storage-unavailable"
    if isinstance(error, HTTPError):
        return "storage-unavailable" if error.code == 503 else "receiver-unavailable"
    if isinstance(error, (RuntimeConfigurationError, URLError, TimeoutError, OSError)):
        return "receiver-unavailable"
    # JSON decoding here is a malformed receiver response: Codex source JSON is
    # parsed by translate_hook and surfaces as SourceEventError above.
    if isinstance(error, json.JSONDecodeError):
        return "receiver-unavailable"
    if isinstance(error, (UnicodeError, ValueError)):
        return "malformed-source-event"
    return "unknown"


def _hook(args: argparse.Namespace) -> int:
    started = time.monotonic()
    state = _state(args.state_dir)
    response: Optional[Dict[str, Any]] = None
    try:
        raw = _read_hook_input()
        from .codex import MalformedSourceEvent, translate_hook

        try:
            source = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise MalformedSourceEvent("hook source is not valid UTF-8 JSON") from error
        if not isinstance(source, dict):
            raise MalformedSourceEvent("hook source must be a JSON object")
        event_name = source.get("hook_event_name")
        budget = CODEX_HOOK_TELEMETRY_BUDGET_SECONDS
        if args.runtime == "claude":
            if event_name == "SessionStart":
                budget = CLAUDE_HOOK_TELEMETRY_BUDGET_SECONDS
            elif event_name == "UserPromptSubmit":
                budget = CLAUDE_PROMPT_HOOK_TELEMETRY_BUDGET_SECONDS
            else:
                budget = CLAUDE_ORDINARY_HOOK_TELEMETRY_BUDGET_SECONDS
        deadline = started + budget
        # Codex requires JSON output from successful Stop and SubagentStop
        # hooks.  Establish the no-op response before telemetry work so an
        # unavailable receiver never turns an observational hook into a host
        # integration failure.
        if event_name in {"Stop", "SubagentStop"}:
            response = {}
        if args.managed_id is not None and args.managed_id != MANAGED_ID:
            raise ValueError("unknown managed hook id")
        if args.runtime == "codex" and args.managed_id == MANAGED_ID:
            from .exec_runner import WRAPPED_CODEX_EXEC_ENV

            if os.environ.get(WRAPPED_CODEX_EXEC_ENV) == "1":
                # The controlled exec wrapper owns task, span, and usage
                # observations for this child. Suppress only this recorder's
                # managed handler; unrelated Codex hooks remain enabled.
                if response is not None:
                    print(json.dumps(response, separators=(",", ":")))
                return 0
        if args.runtime == "codex":
            translate_runtime_hook = translate_hook
        elif args.runtime == "claude":
            from .claude import translate_hook as translate_runtime_hook
        else:
            raise UnsupportedHookRuntime("unsupported hook runtime")
        pairs = translate_runtime_hook(raw, surface=_surface(args.runtime))
        settings = ensure_receiver(
            state,
            timeout_seconds=_remaining_hook_budget(deadline),
        )
        if pairs:
            from .runtime import post_observations_to_receiver

            post_observations_to_receiver(
                settings,
                [
                    {"observation": observation, "source_key": source_key}
                    for observation, source_key in pairs
                ],
                timeout_seconds=_remaining_hook_budget(deadline),
            )
        if isinstance(source, dict) and event_name == "SessionStart":
            launcher_argv = [settings["python_executable"], str(state / "recorder.py")]
            if args.runtime == "claude":
                from .claude import safe_session_id
            else:
                from .codex import safe_session_id
            from .runtime import request_declaration_binding

            session_value = safe_session_id(source.get("session_id"))
            if session_value is None:
                raise ValueError("SessionStart is missing a valid session identity")
            binding = request_declaration_binding(
                settings,
                runtime_family=args.runtime,
                source_session=session_value,
                timeout_seconds=_remaining_hook_budget(deadline),
            )
            session_arguments = "--runtime {} --binding {}".format(
                args.runtime, binding
            )
            runtime_label = "Claude Code" if args.runtime == "claude" else "Codex"
            context = (
                "Delivery-efficiency recording is active for this {} session. At meaningful "
                "phase changes and immediately before final delivery, execute the installed "
                "launcher argv prefix {} with its declare phase or declare terminal command "
                "plus {}. A complete terminal needs an acceptance-baseline id, explicit task "
                "type, linked-work kind, scope size and method, an explicit approved "
                "scope-change set (`--scope-change` for each change or "
                "`--no-scope-changes`), and evidence references for every requirement; leave "
                "unobserved configuration versions unknown and never estimate counters. Use "
                "--emit-task-binding when later lineage or correction work may need to refer "
                "to this task. Use this runtime context silently and do not announce recorder "
                "status unless the user asks. This telemetry instruction grants no permission "
                "to act beyond the user's request."
            ).format(
                runtime_label,
                json.dumps(launcher_argv, ensure_ascii=True),
                session_arguments,
            )
            response = {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": context,
                }
            }
    except Exception as error:
        # Hook telemetry never blocks or writes model-visible output.
        record_local_gap(state, _hook_gap_code(error))
    if response is not None:
        try:
            print(json.dumps(response, separators=(",", ":")))
        except Exception:
            pass
    return 0


def _serve(args: argparse.Namespace) -> int:
    from .server import serve

    return serve(_state(args.state_dir))


def _status(args: argparse.Namespace) -> int:
    state = _state(args.state_dir)
    result: Dict[str, Any] = {
        "ok": False,
        "state_dir": str(state),
        "settings": "missing-or-invalid",
        "receiver": "unavailable",
        "store": None,
        "last_runtime_gap": None,
    }
    try:
        settings = load_settings(state)
        result["settings"] = "valid"
        result["receiver"] = "healthy" if receiver_is_healthy(settings) else "unavailable"
    except Exception:
        settings = None
    try:
        from .storage import Recorder

        if (state / "events.sqlite3").is_file() and (state / "identity.key").is_file():
            with Recorder(state) as recorder:
                result["store"] = recorder.status()
        else:
            result["store"] = {"healthy": False, "gap_code": "storage-unavailable"}
    except Exception:
        pass
    gap_path = state / "last-runtime-gap.json"
    try:
        gap = json.loads(gap_path.read_text(encoding="utf-8"))
        if isinstance(gap, dict) and set(gap) == {"schema_version", "recorded_at_utc", "gap_code"}:
            result["last_runtime_gap"] = gap
    except (OSError, ValueError):
        pass
    result["ok"] = bool(
        settings
        and result["receiver"] == "healthy"
        and isinstance(result["store"], dict)
        and result["store"].get("healthy") is True
    )
    _json(result)
    return 0 if result["ok"] else 1


def _report(args: argparse.Namespace) -> int:
    from .reporting import summarize
    from .storage import Recorder

    state = _state(args.state_dir)
    with Recorder(state) as recorder:
        events = recorder.read_verified_events()
    _json(summarize(events))
    return 0


def _install_plan(args: argparse.Namespace) -> int:
    from .installer import plan_install

    state = _state(args.state_dir)
    homes = _named_paths(args.codex_home, "--codex-home")
    claude_homes = _named_paths(args.claude_home, "--claude-home")
    retired_codex_homes = _named_paths(args.retire_codex_home, "--retire-codex-home")
    retired_claude_homes = _named_paths(args.retire_claude_home, "--retire-claude-home")
    plan = plan_install(
        Path(args.source_root),
        state,
        homes,
        claude_homes=claude_homes,
        retire_codex_homes=retired_codex_homes,
        retire_claude_homes=retired_claude_homes,
        claude_executable=Path(args.claude_executable) if args.claude_executable else None,
        python_executable=Path(args.python_executable) if args.python_executable else None,
        listen_port=args.listen_port,
        rotate_auth_token=args.rotate_auth_token,
        persist=True,
    )
    # The journal deliberately contains only the token digest.
    _json(plan.journal)
    return 0


def _install_action(args: argparse.Namespace) -> int:
    from .installer import apply_install, load_plan, rollback_install, verify_install

    plan = load_plan(
        Path(args.journal),
        expected_plan_digest=args.plan_digest,
    )
    if args.install_action == "apply":
        result = apply_install(plan)
    elif args.install_action == "verify":
        result = verify_install(plan)
    else:
        result = rollback_install(plan)
    if args.install_action == "verify":
        state = Path(plan.journal["target"]["state_root"])
        try:
            settings = ensure_receiver(state)
            result["receiver_healthy"] = receiver_is_healthy(settings)
        except Exception:
            result["receiver_healthy"] = False
    if args.install_action in {"apply", "verify"}:
        result["hook_trust"] = "requires-review-or-observed-hook"
    _json(result)
    return 0 if result.get("receiver_healthy", True) else 1


def _parse_requirement(raw: str) -> Tuple[str, str, str]:
    if "=" not in raw:
        raise ValueError("--requirement must use ID=STATUS:VERIFICATION")
    requirement_id, remainder = raw.split("=", 1)
    if ":" not in remainder:
        raise ValueError("--requirement must include verification")
    status, verification = remainder.split(":", 1)
    return requirement_id, status, verification


def _parse_reference_assignment(raw: str, option: str) -> Tuple[str, str]:
    if "=" not in raw:
        raise ValueError("{} must use ID=REFERENCE".format(option))
    owner, reference = raw.split("=", 1)
    if not owner or not reference:
        raise ValueError("{} must use nonempty ID=REFERENCE".format(option))
    return owner, reference


def _evidence_by_requirement(values: Sequence[str]) -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = {}
    for raw in values:
        requirement_id, reference = _parse_reference_assignment(raw, "--evidence")
        result.setdefault(requirement_id, []).append(reference)
    return result


def _terminal_metadata(args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "acceptance_baseline_id": args.acceptance_baseline,
        "approved_scope_change_ids": (
            [] if args.no_scope_changes else args.scope_change
        ),
        "task_type": args.task_type or "unknown",
        "scope_size": args.scope_size or "unknown",
        "method": args.method or "unknown",
        "policy_version": args.policy_version,
        "model_config_version": args.model_config_version,
        "runtime_config_version": args.runtime_config_version,
        "recorder_config_version": args.recorder_config_version,
    }


def _codex_terminal_metadata(args: argparse.Namespace) -> Dict[str, Any]:
    """Keep omitted exec metadata absent so provenance remains truthful."""

    values: Dict[str, Any] = {}
    if args.acceptance_baseline is not None:
        values["acceptance_baseline_id"] = args.acceptance_baseline
    scope_changes = [] if args.no_scope_changes else args.scope_change
    if scope_changes is not None:
        values["approved_scope_change_ids"] = scope_changes
    for argument, field in (
        ("task_type", "task_type"),
        ("scope_size", "scope_size"),
        ("method", "method"),
        ("policy_version", "policy_version"),
        ("model_config_version", "model_config_version"),
        ("runtime_config_version", "runtime_config_version"),
        ("recorder_config_version", "recorder_config_version"),
    ):
        value = getattr(args, argument)
        if value is not None:
            values[field] = value
    return values


def _record_declarations(
    state: Path,
    session_or_binding: str,
    uses_binding: bool,
    emissions: Sequence[Tuple[Dict[str, Any], str]],
    *,
    linked_task_binding: Optional[str] = None,
    target_task_binding: Optional[str] = None,
) -> Dict[str, Any]:
    from .runtime import post_declarations

    return post_declarations(
        state,
        [
            {"observation": observation, "source_key": source_key}
            for observation, source_key in emissions
        ],
        source_session=None if uses_binding else session_or_binding,
        session_binding=session_or_binding if uses_binding else None,
        linked_task_binding=linked_task_binding,
        target_task_binding=target_task_binding,
    )


def _declaration_identity(args: argparse.Namespace) -> Tuple[str, bool]:
    binding = getattr(args, "binding", None)
    if binding is not None:
        return binding, True
    return _session(args.runtime, args.session), False


def _declare_phase(args: argparse.Namespace) -> int:
    from .declarations import phase_emission

    session, uses_binding = _declaration_identity(args)
    emission = phase_emission(
        session=session,
        runtime_family=args.runtime,
        surface=_surface(args.runtime),
        boundary=args.boundary,
        phase=args.phase,
        activity=args.activity,
        span=args.span,
        agent=args.agent,
    )
    _record_declarations(
        _state(args.state_dir), session, uses_binding, [emission]
    )
    return 0


def _declare_terminal(args: argparse.Namespace) -> int:
    from .declarations import terminal_emissions

    session, uses_binding = _declaration_identity(args)
    requirements = [_parse_requirement(value) for value in args.requirement]
    evidence = _evidence_by_requirement(args.evidence)
    emissions = terminal_emissions(
        session=session,
        runtime_family=args.runtime,
        surface=_surface(args.runtime),
        outcome=args.outcome,
        verification=args.verification,
        task_kind=args.task_kind,
        cause=args.cause,
        requirements=requirements,
        requirement_evidence=evidence,
        **_terminal_metadata(args),
    )
    result = _record_declarations(
        _state(args.state_dir), session, uses_binding, emissions
    )
    if args.emit_task_binding:
        _json({"task_binding": result["task_binding"]})
    return 0


def _declare_lineage(args: argparse.Namespace) -> int:
    from .declarations import lineage_emission

    session, uses_binding = _declaration_identity(args)
    emission = lineage_emission(
        session=session,
        runtime_family=args.runtime,
        surface=_surface(args.runtime),
        linked_task_binding=args.linked_task_binding,
        task_kind=args.task_kind,
        cause=args.cause,
    )
    _record_declarations(
        _state(args.state_dir),
        session,
        uses_binding,
        [emission],
        linked_task_binding=args.linked_task_binding,
    )
    return 0


def _declare_requirement_correction(args: argparse.Namespace) -> int:
    from .declarations import requirement_correction_emission

    session, uses_binding = _declaration_identity(args)
    emission = requirement_correction_emission(
        session=session,
        runtime_family=args.runtime,
        surface=_surface(args.runtime),
        target_event_id=args.target_event,
        requirement_id=args.requirement_id,
        status=args.status,
        verification=args.verification,
        evidence_refs=args.evidence_ref,
    )
    _record_declarations(
        _state(args.state_dir),
        session,
        uses_binding,
        [emission],
        target_task_binding=args.target_task_binding,
    )
    return 0


def _declare_terminal_correction(args: argparse.Namespace) -> int:
    from .declarations import terminal_correction_emission

    session, uses_binding = _declaration_identity(args)
    emission = terminal_correction_emission(
        session=session,
        runtime_family=args.runtime,
        surface=_surface(args.runtime),
        target_event_id=args.target_event,
        outcome=args.outcome,
        verification=args.verification,
        task_kind=args.task_kind,
        cause=args.cause,
        **_terminal_metadata(args),
    )
    result = _record_declarations(
        _state(args.state_dir),
        session,
        uses_binding,
        [emission],
        target_task_binding=args.target_task_binding,
    )
    if args.emit_task_binding:
        _json({"task_binding": result["task_binding"]})
    return 0


def _codex_exec(args: argparse.Namespace) -> int:
    from .exec_runner import run_codex_exec

    declaration = None
    if args.outcome:
        requirements = [_parse_requirement(value) for value in args.requirement]
        evidence = _evidence_by_requirement(args.evidence)
        declaration = {
            "outcome": args.outcome,
            "verification": args.verification,
            "task_kind": args.task_kind,
            "cause": args.cause,
            "requirements": [
                {
                    "id": item[0],
                    "status": item[1],
                    "verification": item[2],
                    "evidence_refs": evidence.get(item[0], []),
                }
                for item in requirements
            ],
            **_codex_terminal_metadata(args),
        }
    return run_codex_exec(
        _state(args.state_dir),
        codex_binary=args.codex_binary,
        arguments=args.codex_arguments,
        terminal_declaration=declaration,
    )


def _add_declaration_identity_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--runtime", choices=("codex", "claude"), default="codex")
    identity = parser.add_mutually_exclusive_group()
    identity.add_argument("--session")
    identity.add_argument("--binding")
    parser.add_argument("--state-dir")


def _add_terminal_metadata_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--acceptance-baseline")
    scope_changes = parser.add_mutually_exclusive_group()
    scope_changes.add_argument(
        "--scope-change",
        action="append",
        default=None,
        metavar="APPROVED_CHANGE_ID",
    )
    scope_changes.add_argument("--no-scope-changes", action="store_true")
    parser.add_argument(
        "--task-type",
        default=None,
        choices=(
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
        ),
    )
    parser.add_argument(
        "--scope-size",
        default=None,
        choices=("small", "medium", "large", "extra-large", "not-applicable", "unknown"),
    )
    parser.add_argument(
        "--method",
        default=None,
        choices=("direct", "delegated", "hybrid", "automated", "not-applicable", "unknown"),
    )
    parser.add_argument("--policy-version")
    parser.add_argument("--model-config-version")
    parser.add_argument("--runtime-config-version")
    parser.add_argument("--recorder-config-version")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Holy Skills delivery-efficiency recorder")
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="run the authenticated loopback receiver")
    serve.add_argument("--state-dir")
    serve.set_defaults(handler=_serve)

    hook = commands.add_parser("hook", help="consume one runtime hook from stdin")
    hook.add_argument("runtime", choices=("codex", "claude"))
    hook.add_argument("--state-dir")
    hook.add_argument("--managed-id")
    hook.set_defaults(handler=_hook)

    status = commands.add_parser("status", help="report settings, receiver, and store health")
    status.add_argument("--state-dir")
    status.set_defaults(handler=_status)

    report = commands.add_parser("report", help="summarize outcome-aware efficiency events")
    report.add_argument("--state-dir")
    report.set_defaults(handler=_report)

    install = commands.add_parser("install", help="transactional copied-runtime installation")
    install_commands = install.add_subparsers(dest="install_action", required=True)
    plan = install_commands.add_parser("plan")
    plan.add_argument("--source-root", default=str(TOOL_ROOT))
    plan.add_argument("--state-dir")
    plan.add_argument("--codex-home", action="append", default=[], metavar="NAME=ABSOLUTE_PATH")
    plan.add_argument("--claude-home", action="append", default=[], metavar="NAME=ABSOLUTE_PATH")
    plan.add_argument(
        "--retire-codex-home",
        action="append",
        default=[],
        metavar="NAME=ABSOLUTE_PATH",
        help="remove only the exact installer-owned integration from a previously managed Codex home",
    )
    plan.add_argument(
        "--retire-claude-home",
        action="append",
        default=[],
        metavar="NAME=ABSOLUTE_PATH",
        help="remove only the exact installer-owned integration from a previously managed Claude home",
    )
    plan.add_argument("--python-executable")
    plan.add_argument(
        "--claude-executable",
        help="absolute Claude Code executable to verify when configuring a Claude home",
    )
    plan.add_argument("--listen-port", type=int)
    plan.add_argument(
        "--rotate-auth-token",
        action="store_true",
        help="generate and transactionally install a fresh receiver secret",
    )
    plan.set_defaults(handler=_install_plan)
    for action in ("apply", "verify", "rollback"):
        child = install_commands.add_parser(action)
        child.add_argument("--journal", required=True)
        child.add_argument(
            "--plan-digest",
            required=True,
            help="reviewed SHA-256 printed by install plan",
        )
        child.set_defaults(handler=_install_action)

    declare = commands.add_parser(
        "declare", help="append bounded agent-known phase, lineage, correction, or terminal facts"
    )
    declare_commands = declare.add_subparsers(dest="declare_action", required=True)
    phase = declare_commands.add_parser("phase")
    phase.add_argument("boundary", choices=("start", "end"))
    phase.add_argument("--phase", required=True, choices=tuple(sorted({"planning", "implementation", "testing", "deployment", "reporting", "unattributed"})))
    phase.add_argument("--activity", required=True, choices=tuple(sorted({"model-active", "tool-active", "external-wait", "user-wait", "blocked-wait", "unattributed"})))
    phase.add_argument("--span", required=True)
    phase.add_argument("--agent")
    _add_declaration_identity_arguments(phase)
    phase.set_defaults(handler=_declare_phase)
    terminal = declare_commands.add_parser("terminal")
    terminal.add_argument("--outcome", required=True, choices=("complete", "incomplete", "blocked", "cancelled", "superseded", "interrupted"))
    terminal.add_argument("--verification", required=True, choices=("verified", "partially-verified", "unverified", "not-applicable", "unknown"))
    terminal.add_argument("--task-kind", default="primary", choices=("primary", "continuation", "retry", "rollback", "defect-repair", "rework", "unknown"))
    terminal.add_argument("--cause", default="not-applicable", choices=("agent-caused-mistake", "changed-user-intent", "new-scope", "external-cause", "not-applicable", "unknown"))
    terminal.add_argument("--requirement", action="append", default=[], metavar="ID=STATUS:VERIFICATION")
    terminal.add_argument("--evidence", action="append", default=[], metavar="REQUIREMENT_ID=EVIDENCE_REF")
    terminal.add_argument("--emit-task-binding", action="store_true")
    _add_terminal_metadata_arguments(terminal)
    _add_declaration_identity_arguments(terminal)
    terminal.set_defaults(handler=_declare_terminal)

    lineage = declare_commands.add_parser("lineage")
    lineage.add_argument("--linked-task-binding", required=True)
    lineage.add_argument(
        "--task-kind",
        required=True,
        choices=("continuation", "retry", "rollback", "defect-repair", "rework"),
    )
    lineage.add_argument(
        "--cause",
        required=True,
        choices=(
            "agent-caused-mistake",
            "changed-user-intent",
            "new-scope",
            "external-cause",
            "unknown",
        ),
    )
    _add_declaration_identity_arguments(lineage)
    lineage.set_defaults(handler=_declare_lineage)

    correction = declare_commands.add_parser("correction")
    correction_commands = correction.add_subparsers(
        dest="correction_kind", required=True
    )
    correction_requirement = correction_commands.add_parser("requirement")
    correction_requirement.add_argument("--target-event", required=True)
    correction_requirement.add_argument("--target-task-binding", required=True)
    correction_requirement.add_argument("--requirement-id", required=True)
    correction_requirement.add_argument(
        "--status", required=True, choices=("satisfied", "partial", "blocked", "removed")
    )
    correction_requirement.add_argument(
        "--verification",
        required=True,
        choices=("verified", "partially-verified", "unverified"),
    )
    correction_requirement.add_argument(
        "--evidence-ref", action="append", default=[]
    )
    _add_declaration_identity_arguments(correction_requirement)
    correction_requirement.set_defaults(handler=_declare_requirement_correction)

    correction_terminal = correction_commands.add_parser("terminal")
    correction_terminal.add_argument("--target-event", required=True)
    correction_terminal.add_argument("--target-task-binding", required=True)
    correction_terminal.add_argument("--outcome", required=True, choices=("complete", "incomplete", "blocked", "cancelled", "superseded", "interrupted"))
    correction_terminal.add_argument("--verification", required=True, choices=("verified", "partially-verified", "unverified"))
    correction_terminal.add_argument("--task-kind", default="primary", choices=("primary", "continuation", "retry", "rollback", "defect-repair", "rework", "unknown"))
    correction_terminal.add_argument("--cause", default="not-applicable", choices=("agent-caused-mistake", "changed-user-intent", "new-scope", "external-cause", "not-applicable", "unknown"))
    correction_terminal.add_argument("--emit-task-binding", action="store_true")
    _add_terminal_metadata_arguments(correction_terminal)
    _add_declaration_identity_arguments(correction_terminal)
    correction_terminal.set_defaults(handler=_declare_terminal_correction)

    execute = commands.add_parser("codex-exec", help="wrap codex exec --json")
    execute.add_argument("--state-dir")
    execute.add_argument("--codex-binary", default="codex")
    execute.add_argument("--outcome", choices=("complete", "incomplete", "blocked", "cancelled", "superseded", "interrupted"))
    execute.add_argument("--verification", default="unknown", choices=("verified", "partially-verified", "unverified", "not-applicable", "unknown"))
    execute.add_argument("--task-kind", default="primary", choices=("primary", "continuation", "retry", "rollback", "defect-repair", "rework", "unknown"))
    execute.add_argument("--cause", default="not-applicable", choices=("agent-caused-mistake", "changed-user-intent", "new-scope", "external-cause", "not-applicable", "unknown"))
    execute.add_argument("--requirement", action="append", default=[], metavar="ID=STATUS:VERIFICATION")
    execute.add_argument("--evidence", action="append", default=[], metavar="REQUIREMENT_ID=EVIDENCE_REF")
    _add_terminal_metadata_arguments(execute)
    execute.add_argument("codex_arguments", nargs=argparse.REMAINDER)
    execute.set_defaults(handler=_codex_exec)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        return int(args.handler(args))
    except (ValueError, OSError, RuntimeError) as error:
        # Errors are intentionally type-only: source/config payloads and paths
        # are never reflected from deep exceptions.
        print("delivery-efficiency error: {}".format(type(error).__name__), file=sys.stderr)
        return 2
