#!/usr/bin/env python3
"""Self-test the installation skill contract and bounded activation receipt."""

from __future__ import annotations

import copy
import importlib.util
import io
import json
import shutil
import sys
import tempfile
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
STATUS_SCRIPT = ROOT / "scripts" / "activation_status.py"


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load_status_module():
    spec = importlib.util.spec_from_file_location("activation_status", STATUS_SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load activation status script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_contract(root: Path) -> list[str]:
    skill = (root / "SKILL.md").read_text(encoding="utf-8")
    platform = (root / "references" / "platform-prerequisites.md").read_text(
        encoding="utf-8"
    )
    metadata = (root / "agents" / "openai.yaml").read_text(encoding="utf-8")
    normalized_skill = " ".join(skill.split())
    normalized_platform = " ".join(platform.split())
    violations: list[str] = []
    requirements = {
        "canonical recorder": "tools/delivery-efficiency/recorder.py",
        "reviewed plan": "install plan",
        "digest-bound apply": "install apply",
        "post-apply verify": "install verify",
        "manual Codex trust": "Codex requires the user to open `/hooks`",
        "fresh task proof": "hook-only lifecycle evidence bound to the same task",
        "explicit homes": "explicit absolute path",
        "explicit source": "--source-root <absolute-repo>/tools/delivery-efficiency",
        "explicit interpreter": "--python-executable <absolute-python>",
        "activation receipt": "activation_status.py",
        "journal-bound receipt": "binds the current canonical recorder source to the reviewed journal",
        "per-home isolation": "Durable events identify runtime family, not the configured home",
        "security assumptions": "security-assumptions.md",
        "security decision coverage": "recorder installation or retirement, Codex feature activation, hook trust, and credential generation or rotation",
        "user-wide assumption authority": "durable project root the user selected",
        "privacy-bounded discovery": "Never dump a complete environment or command line",
        "exact Python version proof": "raise SystemExit(sys.version_info < (3, 9))",
        "Codex preflight boundary": "installer journal does not bind a Codex executable",
        "mixed Claude executable blocker": "one plan cannot represent that set exactly",
        "unversioned source drift blocker": "Equal version with different source bytes",
        "rotation is not implicit": "never add it merely because the recorder version changes",
        "all-runtime rotation drain": "every affected Codex and Claude process",
        "restart": "Fully exit every configured runtime process",
        "rollback verification": "Never reuse the rolled-back journal as activation proof",
        "feature rollback boundary": "Codex feature state changed before planning",
        "scoped feature reversal": "features disable hooks",
    }
    for label, marker in requirements.items():
        if marker not in normalized_skill:
            violations.append(f"missing {label}")
    if "Never edit Codex's trust store" not in normalized_skill:
        violations.append("missing no-auto-trust rule")
    if "Never" not in skill or "--dangerously-bypass-hook-trust" not in skill:
        violations.append("missing bypass prohibition")
    lowered = skill.casefold()
    if "automatically trust codex hooks" in lowered or "edit codex trust" in lowered:
        violations.append("unsafe automatic trust wording")
    for platform_name in ("macOS", "Linux", "WSL", "Native Windows"):
        if f"## {platform_name}" not in platform:
            violations.append(f"missing platform {platform_name}")
    if "Python 3.9" not in platform or "Claude Code 2.1.212" not in platform:
        violations.append("missing version prerequisites")
    if "/mnt/*" not in normalized_platform or "\\\\wsl$" not in normalized_platform:
        violations.append("missing WSL state separation")
    if "Windows-mounted path may be the explicit `--source-root` only" not in normalized_platform:
        violations.append("missing WSL source-root boundary")
    if "display_name: \"Install Delivery Efficiency Hooks\"" not in metadata:
        violations.append("stale display metadata")
    if "$install-delivery-efficiency-hooks" not in metadata:
        violations.append("default prompt does not invoke the skill")
    return violations


def event(
    sequence: int,
    runtime: str,
    adapter: str,
    name: str,
    task: Optional[str],
    source_event: str = "unknown",
    counter_source: str = "not-applicable",
    measurement_provenance: str = "runtime-observed",
    with_tokens: bool = True,
) -> Dict[str, Any]:
    task_id = None if task is None else "id_" + task * 32
    usage = name == "usage.observed"
    task_start = name == "task.start"
    gap = name == "coverage.gap"
    return {
        "schema_version": "1.1",
        "recorder_version": "0.2.1",
        "event_id": "{:032x}".format(sequence),
        "sequence": str(sequence),
        "observed_at_utc": "2026-08-01T00:00:{:02d}Z".format(sequence),
        "monotonic_ns": str(sequence * 1000),
        "clock_domain": "clock_" + "a" * 32,
        "runtime": {
            "family": runtime,
            "surface": "cli-interactive",
            "version": "1.0.0",
        },
        "adapter": {"name": adapter, "version": "0.2.1"},
        "platform": {"os": "macos", "environment": "native"},
        "identity": {
            "lineage_id": "id_" + "b" * 32,
            "task_id": task_id,
            "project_id": None,
            "revision_id": None,
            "session_id": "id_" + "c" * 32,
            "turn_id": task_id,
            "agent_id": None,
        },
        "classification": {
            "phase": "unattributed",
            "phase_provenance": "unknown",
            "activity_state": "model-active" if usage else "unattributed",
            "activity_provenance": "runtime-observed" if usage else "unknown",
            "classifier_version": "contract-v1",
        },
        "measurement": {
            "provenance": measurement_provenance,
            "counter_source": counter_source,
            "tokens": {
                "input": "1" if usage and with_tokens else None,
                "cached_input": "0" if usage and with_tokens else None,
                "output": "1" if usage and with_tokens else None,
                "reasoning_output": (
                    "0" if usage and with_tokens and runtime == "codex" else None
                ),
                "tool": "0" if usage and with_tokens and runtime == "codex" else None,
                "other": "0" if usage and with_tokens and runtime == "claude" else None,
            },
            "recorder_overhead_ns": None,
        },
        "coverage": {
            "request_receipt": "partial",
            "first_activity": "partial",
            "tokens": "complete" if usage and with_tokens else "unknown",
            "tools": "partial",
            "subagents": "partial",
            "terminal_delivery": "partial",
            "scope": "unknown",
            "verification": "unknown",
        },
        "event": name,
        "payload": {
            "source_event": source_event,
            "span_id": None,
            "parent_span_id": None,
            "duration_ns": None,
            "success": None,
            "tool_category": "not-applicable",
            "outcome": "not-applicable",
            "task_kind": "primary" if task_start else "unknown",
            "cause": "not-applicable",
            "requirement_id": None,
            "requirement_status": "not-applicable",
            "verification": "not-applicable",
            "gap_code": "host-boundary-unavailable" if gap else "none",
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
                "task_kind_provenance": "inferred" if task_start else "unknown",
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
        },
    }


def validate_realistic_events(events: list[Dict[str, Any]], module: Any) -> None:
    tool_root = module.TOOL_ROOT
    if not tool_root.is_dir():
        return
    tool_text = str(tool_root)
    if tool_text not in sys.path:
        sys.path.insert(0, tool_text)
    from delivery_efficiency.contract import validate_durable_event

    for item in events:
        validate_durable_event(item)


def observation(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "runtime": copy.deepcopy(item["runtime"]),
        "adapter": copy.deepcopy(item["adapter"]),
        "source_identity": {
            "lineage": "lineage",
            "task": "task",
            "project": None,
            "revision": None,
            "session": "session",
            "turn": "task",
            "agent": None,
            "span": None,
        },
        "classification": copy.deepcopy(item["classification"]),
        "measurement": copy.deepcopy(item["measurement"]),
        "coverage": copy.deepcopy(item["coverage"]),
        "event": item["event"],
        "payload": copy.deepcopy(item["payload"]),
    }


def check_journal_bound_integration(module: Any) -> None:
    if not module.TOOL_ROOT.is_dir():
        return
    tool_text = str(module.TOOL_ROOT)
    if tool_text not in sys.path:
        sys.path.insert(0, tool_text)
    from delivery_efficiency import installer
    from delivery_efficiency.storage import Recorder

    original_snapshot_api = module._snapshot_recorder_api

    @contextmanager
    def healthy_snapshot_api(install_root: Path, expected_digest: str):
        with original_snapshot_api(install_root, expected_digest) as api:
            yield api[:4] + (lambda _settings: True, api[5])

    with tempfile.TemporaryDirectory(prefix="activation-status-integration-") as raw:
        root = Path(raw).resolve()
        state = root / "state"
        home = root / "codex-home"
        home.mkdir()
        with mock.patch.object(installer, "_activate_receiver", return_value=None):
            plan = installer.plan_install(
                module.TOOL_ROOT,
                state,
                {"test-codex": home},
                python_executable=Path(sys.executable).resolve(),
            )
            installer.apply_install(plan)
        check(isinstance(plan.plan_digest, str), "installer omitted the reviewed digest")

        start = event(1, "codex", "codex-hooks", "task.start", "a", "prompt_submit")
        usage = event(
            2,
            "codex",
            "codex-otel",
            "usage.observed",
            "a",
            "otel_response_completed",
            "provider-native",
        )
        with Recorder(state) as recorder:
            recorder.record(observation(start), source_key="activation-start")
            recorder.record(observation(usage), source_key="activation-usage")

        with mock.patch.object(module, "_snapshot_recorder_api", healthy_snapshot_api):
            result = module.inspect(
                plan.journal_path,
                plan.plan_digest,
                after_sequence=0,
                selected_runtime="codex",
            )
            check(result["runtimes"]["codex"]["active"] is True, "verified store was rejected")
            check("id_" not in json.dumps(result), "journal-bound receipt leaked identities")

            output = io.StringIO()
            with redirect_stdout(output):
                status = module.main(
                    [
                        "--journal",
                        str(plan.journal_path),
                        "--plan-digest",
                        plan.plan_digest,
                        "--runtime",
                        "codex",
                        "--require-active",
                    ]
                )
            check(status == 0, "journal-bound CLI did not report active")
            check(output.getvalue().startswith("ACTIVATION_STATUS {"), "receipt marker missing")

        with (state / "EfficiencyLedger.jsonl").open("ab") as stream:
            stream.write(b"{}\n")
        with mock.patch.object(module, "_snapshot_recorder_api", healthy_snapshot_api):
            try:
                module.inspect(
                    plan.journal_path,
                    plan.plan_digest,
                    after_sequence=0,
                    selected_runtime="codex",
                )
            except module.ActivationStatusError:
                pass
            else:
                raise AssertionError("tampered cold ledger was accepted")


def check_preimport_drift_rejection(module: Any) -> None:
    if not module.TOOL_ROOT.is_dir():
        return
    tool_text = str(module.TOOL_ROOT)
    if tool_text not in sys.path:
        sys.path.insert(0, tool_text)
    from delivery_efficiency import installer

    with tempfile.TemporaryDirectory(prefix="activation-preimport-drift-") as raw:
        root = Path(raw).resolve()
        source = root / "delivery-efficiency"
        shutil.copytree(module.TOOL_ROOT, source)
        home = root / "codex-home"
        home.mkdir()
        plan = installer.plan_install(
            source,
            root / "state",
            {"test-codex": home},
            python_executable=Path(sys.executable).resolve(),
        )

        with mock.patch.object(module, "TOOL_ROOT", source):
            with mock.patch.object(
                module,
                "_snapshot_recorder_api",
                side_effect=AssertionError("unreviewed recorder code import attempted"),
            ) as snapshot_api:
                try:
                    module.inspect(
                        plan.journal_path,
                        "0" * 64,
                        after_sequence=0,
                        selected_runtime="codex",
                    )
                except module.ActivationStatusError:
                    pass
                else:
                    raise AssertionError("unreviewed plan digest was accepted")
                check(not snapshot_api.called, "invalid plan reached recorder import")

                entry = source / "recorder.py"
                entry.write_bytes(entry.read_bytes() + b"\n# drift fixture\n")
                try:
                    module.inspect(
                        plan.journal_path,
                        plan.plan_digest,
                        after_sequence=0,
                        selected_runtime="codex",
                    )
                except module.ActivationStatusError:
                    pass
                else:
                    raise AssertionError("drifted recorder source was accepted")
                check(not snapshot_api.called, "drifted source reached recorder import")


def check_post_snapshot_reverification(module: Any) -> None:
    if not module.TOOL_ROOT.is_dir():
        return
    expected_digest = module._payload_digest(module.TOOL_ROOT.resolve(strict=True))
    plan = SimpleNamespace(
        journal={
            "source": {
                "root": str(module.TOOL_ROOT.resolve(strict=True)),
                "payload_sha256": expected_digest,
            },
            "target": {"state_root": str(module.TOOL_ROOT.parent)},
        }
    )
    verification_calls = []

    def verify_install(_plan: Any, *, plan_digest: str) -> None:
        verification_calls.append(plan_digest)
        if len(verification_calls) == 2:
            raise RuntimeError("concurrent transaction fixture")

    class FakeRecorder:
        def __init__(self, _state: Path) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def status(self) -> Dict[str, Any]:
            return {
                "healthy": True,
                "recorder_version": "0.2.1",
                "schema_version": "1.1",
            }

        def read_verified_events(self) -> list[Dict[str, Any]]:
            return []

    api = (
        lambda _journal, expected_plan_digest: plan,
        lambda _source: expected_digest,
        verify_install,
        lambda _state: {"stable": True},
        lambda _settings: True,
        FakeRecorder,
    )
    try:
        module._inspect_with_api(
            api,
            Path("/absolute/journal.json"),
            "a" * 64,
            after_sequence=0,
            selected_runtime="codex",
        )
    except module.ActivationStatusError:
        pass
    else:
        raise AssertionError("post-snapshot transaction drift was accepted")
    check(len(verification_calls) == 2, "receipt was not bracketed by verification")


def check_tool_owned_temp_alias(module: Any) -> None:
    if not module.TOOL_ROOT.is_dir():
        return
    with tempfile.TemporaryDirectory(prefix="activation-temp-alias-parent-") as raw:
        root = Path(raw).resolve()
        real = root / "real-temp"
        alias = root / "temp-alias"
        real.mkdir()
        try:
            alias.symlink_to(real, target_is_directory=True)
        except OSError:
            return

        class AliasTemporaryDirectory:
            def __init__(self, *_args: Any, **_kwargs: Any) -> None:
                pass

            def __enter__(self) -> str:
                return str(alias)

            def __exit__(self, *_args: Any) -> None:
                return None

        expected_digest = module._payload_digest(module.TOOL_ROOT.resolve(strict=True))
        with mock.patch.object(
            module.tempfile,
            "TemporaryDirectory",
            AliasTemporaryDirectory,
        ):
            with module._snapshot_recorder_api(
                module.TOOL_ROOT.resolve(strict=True),
                expected_digest,
            ) as api:
                check(len(api) == 6, "canonicalized tool-owned snapshot failed")


def main() -> int:
    check(validate_contract(ROOT) == [], f"live contract failed: {validate_contract(ROOT)}")

    temporary = Path(tempfile.mkdtemp(prefix="install-hooks-skill-self-test-"))
    try:
        fixture = temporary / "skill"
        shutil.copytree(ROOT, fixture)

        skill_path = fixture / "SKILL.md"
        original = skill_path.read_text(encoding="utf-8")
        skill_path.write_text(
            original.replace("Never edit Codex's trust store", "Edit Codex's trust store"),
            encoding="utf-8",
        )
        check("missing no-auto-trust rule" in validate_contract(fixture), "auto-trust gap missed")
        skill_path.write_text(original, encoding="utf-8")

        reference = fixture / "references" / "platform-prerequisites.md"
        reference_original = reference.read_text(encoding="utf-8")
        reference.write_text(
            reference_original.replace("## WSL", "## Linux subsystem"),
            encoding="utf-8",
        )
        check("missing platform WSL" in validate_contract(fixture), "WSL coverage gap missed")
        reference.write_text(reference_original, encoding="utf-8")

        skill_path.write_text(
            original.replace(
                "different source bytes",
                "altered source material",
            ),
            encoding="utf-8",
        )
        check(
            "missing unversioned source drift blocker" in validate_contract(fixture),
            "same-version source drift gap missed",
        )
        skill_path.write_text(original, encoding="utf-8")

        reference.write_text(
            reference_original.replace(
                "Windows-mounted path may be the explicit `--source-root` only",
                "Windows-mounted path may be selected as a source",
            ),
            encoding="utf-8",
        )
        check(
            "missing WSL source-root boundary" in validate_contract(fixture),
            "WSL source-root gap missed",
        )
        reference.write_text(reference_original, encoding="utf-8")
        check(validate_contract(fixture) == [], "restored valid fixture was rejected")
    finally:
        shutil.rmtree(temporary, ignore_errors=True)

    module = load_status_module()
    unbound_events = [
        event(
            1,
            "codex",
            "codex-otel",
            "usage.observed",
            None,
            "otel_response_completed",
            "provider-native",
        )
    ]
    validate_realistic_events(unbound_events, module)
    unbound = module.summarize_events(
        unbound_events,
        after_sequence=0,
        selected_runtime="codex",
    )
    check(unbound["runtimes"]["codex"]["active"] is False, "unbound usage must not activate")

    mismatched_events = [
        event(1, "codex", "codex-hooks", "task.start", "a", "prompt_submit"),
        event(
            2,
            "codex",
            "codex-otel",
            "usage.observed",
            "b",
            "otel_response_completed",
            "provider-native",
        ),
    ]
    validate_realistic_events(mismatched_events, module)
    mismatched = module.summarize_events(
        mismatched_events,
        after_sequence=0,
        selected_runtime="codex",
    )
    check(
        mismatched["runtimes"]["codex"]["active"] is False,
        "different task identities must not satisfy correlation",
    )

    wrong_adapter_events = [
            event(1, "codex", "codex-hooks", "task.start", "a", "prompt_submit"),
            event(
                2,
                "codex",
                "claude-runtime",
                "usage.observed",
                "a",
                "otel_api",
                "runtime-native",
            ),
        ]
    validate_realistic_events(wrong_adapter_events, module)
    wrong_adapter = module.summarize_events(
        wrong_adapter_events,
        after_sequence=0,
        selected_runtime="codex",
    )
    check(wrong_adapter["runtimes"]["codex"]["active"] is False, "wrong adapter activated Codex")

    codex_exec_events = [
            event(1, "codex", "codex-hooks", "task.start", "a", "prompt_submit"),
            event(
                2,
                "codex",
                "codex-exec",
                "usage.observed",
                "a",
                "exec_turn",
                "provider-native",
            ),
        ]
    validate_realistic_events(codex_exec_events, module)
    codex_exec = module.summarize_events(
        codex_exec_events,
        after_sequence=0,
        selected_runtime="codex",
    )
    check(codex_exec["runtimes"]["codex"]["active"] is False, "codex-exec activated hooks")

    no_counter_events = [
        event(1, "codex", "codex-hooks", "task.start", "a", "prompt_submit"),
        event(
            2,
            "codex",
            "codex-otel",
            "usage.observed",
            "a",
            "otel_response_completed",
            "provider-native",
            with_tokens=False,
        ),
    ]
    validate_realistic_events(no_counter_events, module)
    no_counter = module.summarize_events(
        no_counter_events,
        after_sequence=0,
        selected_runtime="codex",
    )
    check(no_counter["runtimes"]["codex"]["active"] is False, "null counters activated hooks")

    unknown_provenance_events = [
        event(1, "codex", "codex-hooks", "task.start", "a", "prompt_submit"),
        event(
            2,
            "codex",
            "codex-otel",
            "usage.observed",
            "a",
            "otel_response_completed",
            "provider-native",
            measurement_provenance="unknown",
        ),
    ]
    validate_realistic_events(unknown_provenance_events, module)
    unknown_provenance = module.summarize_events(
        unknown_provenance_events,
        after_sequence=0,
        selected_runtime="codex",
    )
    check(
        unknown_provenance["runtimes"]["codex"]["active"] is False,
        "unknown measurement provenance activated hooks",
    )

    codex_events = [
        event(1, "codex", "codex-hooks", "task.start", "a", "prompt_submit"),
        event(
            2,
            "codex",
            "codex-otel",
            "usage.observed",
            "a",
            "otel_response_completed",
            "provider-native",
        ),
    ]
    validate_realistic_events(codex_events, module)
    codex = module.summarize_events(
        codex_events,
        after_sequence=0,
        selected_runtime="codex",
    )
    check(codex["runtimes"]["codex"]["active"] is True, "Codex activation proof rejected")
    check(codex["runtimes"]["codex"]["correlated_tasks"] == 1, "correlation count is wrong")

    claude_otel_only = module.summarize_events(
        [
            event(3, "claude", "claude-runtime", "task.start", "a", "prompt_submit"),
            event(
                4,
                "claude",
                "claude-runtime",
                "usage.observed",
                "a",
                "otel_api",
                "runtime-native",
            ),
        ],
        after_sequence=2,
        selected_runtime="claude",
    )
    check(
        claude_otel_only["runtimes"]["claude"]["active"] is False,
        "Claude OTLP-only evidence activated hooks",
    )

    false_claude_hook_events = [
        event(3, "claude", "claude-runtime", "task.start", "a", "prompt_submit"),
        event(
            4,
            "claude",
            "claude-runtime",
            "usage.observed",
            "a",
            "otel_api",
            "runtime-native",
        ),
        event(5, "claude", "claude-runtime", "task.first_activity", "a", "turn_stop"),
    ]
    validate_realistic_events(false_claude_hook_events, module)
    false_claude_hook = module.summarize_events(
        false_claude_hook_events,
        after_sequence=2,
        selected_runtime="claude",
    )
    check(
        false_claude_hook["runtimes"]["claude"]["active"] is False,
        "noncanonical Claude hook tuple activated hooks",
    )

    claude_events = [
        event(3, "claude", "claude-runtime", "task.start", "a", "prompt_submit"),
        event(
            4,
            "claude",
            "claude-runtime",
            "usage.observed",
            "a",
            "otel_api",
            "runtime-native",
        ),
        event(
            5,
            "claude",
            "claude-runtime",
            "coverage.gap",
            "a",
            "turn_stop",
        ),
    ]
    validate_realistic_events(claude_events, module)
    claude = module.summarize_events(
        claude_events,
        after_sequence=2,
        selected_runtime="claude",
    )
    check(claude["runtimes"]["claude"]["active"] is True, "Claude activation proof rejected")
    check(claude["runtimes"]["codex"]["events"] == 0, "runtime filter leaked Codex events")

    after = module.summarize_events(
        [
            event(1, "codex", "codex-hooks", "task.start", "a", "prompt_submit"),
            event(
                2,
                "codex",
                "codex-otel",
                "usage.observed",
                "a",
                "otel_response_completed",
                "provider-native",
            ),
        ],
        after_sequence=2,
        selected_runtime="codex",
    )
    check(after["runtimes"]["codex"]["active"] is False, "historical events satisfied fresh proof")

    receipt_text = json.dumps(codex, sort_keys=True)
    check("id_" not in receipt_text, "opaque task identity leaked into receipt")

    output = io.StringIO()
    with redirect_stdout(output):
        relative_status = module.main(
            ["--journal", "relative.json", "--plan-digest", "0" * 64]
        )
    check(relative_status == 1, "relative journal was accepted")
    check(
        output.getvalue().strip() == "ACTIVATION_STATUS error=journal-must-be-absolute",
        "relative-journal failure was not bounded",
    )

    with tempfile.TemporaryDirectory(prefix="activation-status-missing-") as raw:
        output = io.StringIO()
        with redirect_stdout(output):
            missing_status = module.main(
                [
                    "--journal",
                    str(Path(raw) / "missing.json"),
                    "--plan-digest",
                    "0" * 64,
                ]
            )
        check(missing_status == 1, "missing reviewed journal was accepted")
        check(
            output.getvalue().strip() == "ACTIVATION_STATUS error=inspection-failed",
            "inspection failure was not bounded",
        )

    check_preimport_drift_rejection(module)
    check_post_snapshot_reverification(module)
    check_tool_owned_temp_alias(module)
    check_journal_bound_integration(module)

    print("install-delivery-efficiency-hooks self-test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
