#!/usr/bin/env python3
"""Self-test the installation skill contract and bounded activation receipt."""

from __future__ import annotations

import copy
import hashlib
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
REPO_ROOT = ROOT.parents[1]
README_PATH = REPO_ROOT / "README.md"
DIRECT_INSTALL_ACTIONS = ("install apply", "install verify", "install rollback")


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


def validate_zero_terminal_skill(skill: str) -> list[str]:
    violations: list[str] = []
    recovery_heading = "## 8. Recovery only: direct installer commands"
    if recovery_heading not in skill:
        return ["missing recovery-only section"]
    normal, recovery = skill.split(recovery_heading, 1)
    for action in DIRECT_INSTALL_ACTIONS:
        if action in normal:
            violations.append(f"normal path exposes {action}")
        if action not in recovery:
            violations.append(f"recovery section omits {action}")
    normal_markers = {
        "deferred arm": "install defer",
        "exact target process input": "--target-pid",
        "ready handshake": "ready handshake",
        "armed filename receipt": "DEFERRED_INSTALL_ARMED",
        "saved status receipt": "DEFERRED_INSTALL_STATUS",
        "filename-bearing handoff": "status-report `filename`",
        "agent process discovery": "The agent owns target-process discovery",
        "one close and reopen": "approve/close/reopen cycle happens once",
        "short settling interval": "agent-announced short settling interval",
        "reopened status first": "before doing anything else",
        "optional observer": "never requires one",
        "normal path has no Terminal commands": (
            "The user never opens Terminal, watches a private file, or copies/runs "
            "installer commands in the normal path"
        ),
    }
    normalized = " ".join(normal.split())
    for label, marker in normal_markers.items():
        if marker not in normalized:
            violations.append(f"missing {label}")
    return violations


def validate_readme_zero_terminal(readme: str) -> list[str]:
    violations: list[str] = []
    install_heading = "## Install the delivery-efficiency recorder"
    recovery_heading = "### Recovery-only direct installer commands"
    runtime_heading = "### Runtime behavior after a verified install"
    if install_heading not in readme or recovery_heading not in readme:
        return ["README missing zero-Terminal or recovery section"]
    install = readme.split(install_heading, 1)[1]
    normal, remainder = install.split(recovery_heading, 1)
    recovery = remainder.split(runtime_heading, 1)[0] if runtime_heading in remainder else remainder
    for action in DIRECT_INSTALL_ACTIONS:
        if action in normal:
            violations.append(f"README normal path exposes {action}")
        if action not in recovery:
            violations.append(f"README recovery section omits {action}")
    normalized = " ".join(normal.split())
    for label, marker in {
        "deferred command": "install defer",
        "armed receipt": "DEFERRED_INSTALL_ARMED",
        "saved status": "DEFERRED_INSTALL_STATUS",
        "filename receipt": "status `filename`",
        "deferred wait bounds": (
            "defaults to 86400 seconds and is bounded to 1 through 604800 seconds"
        ),
        "one-shot nonpersistent worker": "one-shot and nonpersistent",
        "agent-owned reboot recovery": (
            "OS reboot ends it and requires an agent-owned fresh plan and rearm"
        ),
        "reboot user close/reopen only": (
            "The user only repeats the close/reopen boundary after a new armed receipt"
        ),
        "strict no-mutation fallback": (
            "strict receipt for the exact job and plan digest proves no mutation"
        ),
        "failure fallback authorization boundary": (
            "never authorizes apply, trust review, activation, or success"
        ),
        "no user Terminal": "The user never opens Terminal or copies/runs installer commands",
        "one reopen": "reopen those hosts once",
        "settling interval": "short settling interval",
        "reopened agent status gate": "reopened agent's first action is to read deferred status",
    }.items():
        if marker not in normalized:
            violations.append(f"README missing {label}")
    return violations


def optional_repository_readme(path: Path) -> Optional[str]:
    """Load repository-only documentation without making it a skill dependency."""

    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


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
        "agent-owned defer": "install defer",
        "deferred ready receipt": "DEFERRED_INSTALL_ARMED",
        "deferred status receipt": "DEFERRED_INSTALL_STATUS",
        "deferred filename": "status-report `filename`",
        "deferred process discovery": "The agent owns target-process discovery",
        "bounded deferred wait": (
            "defaults to 86400 seconds and accepts only 1 through 604800 seconds"
        ),
        "one-shot nonpersistent worker": "Keep the worker one-shot and nonpersistent",
        "agent-owned reboot recovery": (
            "OS reboot ends it and requires the agent to create a fresh plan and rearm"
        ),
        "strict no-mutation fallback": (
            "strict receipt for the exact job and plan digest proves that no mutation occurred"
        ),
        "failure fallback authorization boundary": (
            "never authorizes apply, trust review, activation, or success"
        ),
        "reboot user close/reopen only": (
            "ask the user only to repeat the required close/reopen boundary"
        ),
        "no normal Terminal": "The user never opens Terminal, watches a private file, or copies/runs installer commands in the normal path",
        "one reopen boundary": "approve/close/reopen cycle happens once",
        "reopened status first": "before doing anything else",
        "optional status observer": "never requires one",
        "recovery-only direct actions": "Recovery only: direct installer commands",
        "version-neutral launcher": "version-neutral `<state>/recorder.py` launcher",
        "compatible endpoint preservation": "preserves the same loopback host, bearer credential, and port",
        "one-time stable launcher migration": "`0.2.3` to `0.2.4` migration changes existing handler commands once",
        "later upgrade no restart": "require neither a host restart nor renewed hook trust",
        "manual Codex trust": "Codex requires the user to open `/hooks`",
        "fresh task proof": "same target and task",
        "explicit homes": "explicit absolute path",
        "explicit source": "--source-root <absolute-repo>/tools/delivery-efficiency",
        "explicit interpreter": "--python-executable <absolute-python>",
        "activation receipt": "activation_status.py",
        "exact installer boundary": "Installer apply, verify, and rollback remain exact",
        "activation-only config conformance": "For activation inspection only, a changed Codex `config.toml` action's whole-file hash drift may conform",
        "reviewed newline exactness": "byte-exact—including reviewed newline encoding",
        "outer multiline refusal": "Multiline-string syntax outside the block",
        "journal-bound receipt": "binds the current canonical recorder source to the reviewed journal",
        "agent-owned watch": "--watch",
        "all reviewed Codex targets": "without it the helper selects all reviewed Codex homes",
        "no manual sequence choreography": "Do not ask the user to open Terminal, copy a sequence, quit or isolate another Codex app",
        "bounded watch": "at most 900 seconds",
        "filename-bearing report receipt": "REPORT_SAVED",
        "private cold report": "private `activation-reports/` directory",
        "same-target usage": "same target and task",
        "null-target rejection": "null, legacy, or different target on usage cannot activate the home",
        "legacy family honesty": "marks every requested home unproven",
        "Claude target exclusion": "do not use or claim Codex target attribution for Claude",
        "target-aware version": "recorder `0.2.3` and schema `1.2`",
        "security assumptions": "security-assumptions.md",
        "security decision coverage": "A first recorder installation or retirement, Codex feature activation, hook trust, and credential generation or rotation can change security posture",
        "routine repair boundary": "verified non-rotating repair that preserves the same named homes, endpoint boundary, credential, controls, and documented posture is routine execution, not a new posture decision",
        "security question materiality": "wrong answer could select unnecessary controls, omit a necessary control, expand the work, or cause meaningful rework",
        "smallest security question": "smallest concise set of material questions",
        "conditional full baseline": "cover the full baseline only when that decision materially depends on every area",
        "user-wide assumption authority": "durable project root the user selected",
        "privacy-bounded discovery": "Never dump a complete environment or command line",
        "exact Python version proof": "raise SystemExit(sys.version_info < (3, 9))",
        "Codex preflight boundary": "installer journal does not bind a Codex executable",
        "mixed Claude executable blocker": "one plan cannot represent that set exactly",
        "unversioned source drift blocker": "Equal version with different source bytes",
        "rotation is not implicit": "never add it merely because the recorder version changes",
        "all-runtime rotation drain": "every live same-user Codex or Claude process",
        "restart": "reopens them once",
        "rollback verification": "Never reuse the rolled-back journal as activation proof",
        "feature rollback boundary": "Codex feature state changed before planning",
        "scoped feature reversal": "features disable hooks",
    }
    for label, marker in requirements.items():
        if marker not in normalized_skill:
            violations.append(f"missing {label}")
    violations.extend(validate_zero_terminal_skill(skill))
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
    for label, marker in {
        "platform agent-owned defer": "The normal install and upgrade path is software-owned",
        "platform ready handshake": "DEFERRED_INSTALL_ARMED",
        "platform optional observer": "is optional",
        "platform deferred wait bounds": (
            "1-through-604800-second wait (86400 seconds by default)"
        ),
        "platform one-shot nonpersistent worker": "It is one-shot and nonpersistent",
        "platform agent-owned reboot recovery": (
            "OS reboot ends it and requires agent-owned replan and rearm"
        ),
        "platform reboot user close/reopen only": (
            "the user only repeats the close/reopen boundary and never opens Terminal"
        ),
        "platform strict no-mutation fallback": (
            "strict receipt for the exact job and plan digest proves no mutation"
        ),
        "platform failure fallback authorization boundary": (
            "never authorizes apply, trust review, activation, or success"
        ),
        "macOS process identity": "libproc process-start identity",
        "Linux process identity": "`/proc/<pid>/stat` start time",
        "WSL process separation": "A native Windows PID or process image is never WSL process evidence",
        "Windows process identity": "process-creation FILETIME",
    }.items():
        if marker not in normalized_platform:
            violations.append(f"missing {label}")
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
    target_id: Optional[str] = None,
    schema_version: Optional[str] = None,
) -> Dict[str, Any]:
    task_id = None if task is None else "id_" + task * 32
    usage = name == "usage.observed"
    task_start = name == "task.start"
    gap = name == "coverage.gap"
    identity = {
        "lineage_id": "id_" + "b" * 32,
        "task_id": task_id,
        "project_id": None,
        "revision_id": None,
        "session_id": "id_" + "c" * 32,
        "turn_id": task_id,
        "agent_id": None,
    }
    selected_schema = schema_version or ("1.2" if target_id is not None else "1.1")
    if selected_schema == "1.2":
        identity["target_id"] = target_id
    return {
        "schema_version": selected_schema,
        "recorder_version": "0.2.3" if selected_schema == "1.2" else "0.2.2",
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
        "adapter": {"name": adapter, "version": "0.2.2"},
        "platform": {"os": "macos", "environment": "native"},
        "identity": identity,
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
            "target": None,
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
            yield api[:4] + (lambda _settings: True, api[5], api[6])

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

            watch_result, report_path, report_digest, report_size = module.watch(
                plan.journal_path,
                plan.plan_digest,
                selected_targets=["test-codex"],
                wait_seconds=0,
            )
            check(watch_result["status"] == "timeout", "zero-bound watch did not time out")
            check(watch_result["ok"] is False, "partial watch claimed completion")
            report_raw = report_path.read_bytes()
            check(hashlib.sha256(report_raw).hexdigest() == report_digest, "watch report digest mismatch")
            check(len(report_raw) == report_size, "watch report byte count mismatch")
            check(b"id_" not in report_raw and b"target_v1_" not in report_raw, "watch report leaked identities")
            report_value = json.loads(report_raw.decode("utf-8"))
            check(report_value["pending_target_count"] == 1, "timeout report lost pending target")

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


def check_codex_config_activation_conformance(module: Any) -> None:
    if not module.TOOL_ROOT.is_dir():
        return
    tool_text = str(module.TOOL_ROOT)
    if tool_text not in sys.path:
        sys.path.insert(0, tool_text)
    from delivery_efficiency import installer

    original_snapshot_api = module._snapshot_recorder_api

    @contextmanager
    def healthy_snapshot_api(install_root: Path, expected_digest: str):
        with original_snapshot_api(install_root, expected_digest) as api:
            yield api[:4] + (lambda _settings: True, api[5], api[6])

    def expect_rejected(plan: Any, label: str) -> None:
        with mock.patch.object(module, "_snapshot_recorder_api", healthy_snapshot_api):
            try:
                module.inspect(
                    plan.journal_path,
                    plan.plan_digest,
                    after_sequence=0,
                    selected_runtime="codex",
                )
            except module.ActivationStatusError:
                return
        raise AssertionError(f"activation accepted {label}")

    with tempfile.TemporaryDirectory(prefix="activation-config-conformance-") as raw:
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

        config = home / "config.toml"
        hooks = home / "hooks.json"
        exact_config = config.read_bytes()
        exact_hooks = hooks.read_bytes()

        def set_config(value: bytes) -> None:
            if config.is_symlink() or config.exists():
                config.unlink()
            config.write_bytes(value)
            if sys.platform != "win32":
                config.chmod(0o600)

        benign = (
            b'[features]\nhooks = true\n\n'
            + exact_config
            + b'\n[activation_fixture]\nvalue = "unrelated"\n'
        )
        set_config(benign)
        check(exact_config in benign, "benign fixture changed the managed block bytes")
        try:
            installer.verify_install(plan, plan_digest=plan.plan_digest)
        except installer.InstallerVerificationError:
            pass
        else:
            raise AssertionError("exact installer verification accepted whole-file drift")

        with mock.patch.object(module, "_snapshot_recorder_api", healthy_snapshot_api):
            conformed = module.inspect(
                plan.journal_path,
                plan.plan_digest,
                after_sequence=0,
                selected_runtime="codex",
            )
        check(
            conformed["verification"]
            == "journal-bound-reviewed-snapshot-and-double-activation-config-conformance",
            "activation did not report its narrow config conformance path",
        )

        managed_edit = exact_config.replace(
            b"log_user_prompt = false",
            b"log_user_prompt = true",
            1,
        )
        check(managed_edit != exact_config, "managed-edit fixture did not change the block")
        set_config(managed_edit)
        expect_rejected(plan, "an edited managed OTel block")

        set_config(exact_config + b"\n[otel.extra]\nenabled = true\n")
        expect_rejected(plan, "a competing OTel definition")

        escaped_otel = b'["ot\\u0065l"]\nenabled = true\n\n' + exact_config
        set_config(escaped_otel)
        expect_rejected(plan, "an escaped quoted competing OTel definition")

        multiline_wrapped = (
            b'blob = """\n'
            + exact_config
            + b'[features]\n"""\n'
        )
        set_config(multiline_wrapped)
        expect_rejected(plan, "a managed block hidden in a multiline TOML string")

        crlf_block = exact_config.replace(b"\n", b"\r\n")
        check(crlf_block != exact_config, "newline-transcode fixture did not change")
        set_config(crlf_block)
        expect_rejected(plan, "a newline-transcoded managed OTel block")

        set_config(exact_config + b"\nmanaged_extension = true\n")
        expect_rejected(plan, "a key extending the managed OTel table")

        set_config(b"[features]\nhooks = true\n")
        expect_rejected(plan, "a missing managed OTel block")

        malformed_markers = exact_config.replace(
            b"# END HOLYSKILLS DELIVERY EFFICIENCY v1\n",
            b"# END HOLYSKILLS DELIVERY EFFICIENCY v1 edited\n",
            1,
        )
        check(
            malformed_markers != exact_config,
            "malformed-marker fixture did not change the block",
        )
        set_config(malformed_markers)
        expect_rejected(plan, "malformed managed OTel markers")

        set_config(exact_config + b"\n" + exact_config)
        expect_rejected(plan, "duplicate managed OTel markers")

        set_config(exact_config)
        hooks.write_bytes(exact_hooks + b"\n")
        expect_rejected(plan, "drift in a non-config action")
        hooks.write_bytes(exact_hooks)

        config.unlink()
        config.mkdir()
        expect_rejected(plan, "a non-regular Codex config target")
        config.rmdir()
        set_config(exact_config)

        unsafe_target = root / "unsafe-config-target.toml"
        unsafe_target.write_bytes(exact_config)
        config.unlink()
        try:
            config.symlink_to(unsafe_target)
        except OSError:
            set_config(exact_config)
        else:
            expect_rejected(plan, "a linked Codex config target")

        set_config(exact_config)
        installer.verify_install(plan, plan_digest=plan.plan_digest)

        with mock.patch.object(installer, "_activate_receiver", return_value=None):
            upgrade_plan = installer.plan_install(
                module.TOOL_ROOT,
                state,
                {"test-codex": home},
                python_executable=Path(sys.executable).resolve(),
                rotate_auth_token=True,
            )
            installer.apply_install(upgrade_plan)
        unchanged_action = next(
            action
            for action in upgrade_plan.journal["actions"]
            if not action["changed"]
        )
        upgraded_config = config.read_bytes()
        set_config(
            b'[features]\nhooks = true\n\n'
            + upgraded_config
            + b'\n[activation_fixture]\nvalue = "unrelated"\n'
        )
        stray_stage = Path(unchanged_action["stage_path"])
        stray_stage.write_bytes(b"unexpected transaction artifact\n")
        expect_rejected(
            upgrade_plan,
            "a drifted auxiliary artifact for an otherwise unchanged action",
        )
        stray_stage.unlink()
        set_config(upgraded_config)
        installer.verify_install(
            upgrade_plan,
            plan_digest=upgrade_plan.plan_digest,
        )


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
                "recorder_version": "0.2.2",
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
        None,
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
                check(len(api) == 7, "canonicalized tool-owned snapshot failed")


def check_report_and_watch_cli(module: Any) -> None:
    report = {
        "schema_version": 1,
        "report_kind": "codex-target-activation",
        "status": "timeout",
        "attribution": "target-aware",
        "proof_scope": "configured-runtime-home-not-process-or-session",
        "targets": [{"name": "main", "status": "pending"}],
    }
    with tempfile.TemporaryDirectory(prefix="activation report Ω ") as raw:
        state = Path(raw).resolve()
        filename, digest, size = module._write_private_report(state, report)
        encoded = filename.read_bytes()
        check(filename.parent == state / "activation-reports", "report escaped recorder state")
        check(hashlib.sha256(encoded).hexdigest() == digest, "report digest is wrong")
        check(len(encoded) == size, "report byte count is wrong")
        check(b"id_" not in encoded and b"target_v1_" not in encoded, "report leaked raw identities")
        check(str(state).encode("utf-8") not in encoded, "report leaked a filesystem path")
        if sys.platform != "win32":
            check(filename.stat().st_mode & 0o077 == 0, "report is not private")

    with tempfile.TemporaryDirectory(prefix="activation-collision-") as raw:
        state = Path(raw).resolve()
        report_root = state / "activation-reports"
        report_root.mkdir()
        collision = report_root / "activation-fixed-aaaaaaaaaaaaaaaa.json"
        collision.write_bytes(b"preserve me\n")
        with mock.patch.object(module.time, "strftime", return_value="fixed"):
            with mock.patch.object(
                module.secrets,
                "token_hex",
                side_effect=["a" * 16, "b" * 16],
            ):
                filename, _digest, _size = module._write_private_report(state, report)
        check(collision.read_bytes() == b"preserve me\n", "report collision was overwritten")
        check(filename.name == "activation-fixed-bbbbbbbbbbbbbbbb.json", "collision retry failed")

    with tempfile.TemporaryDirectory(prefix="activation-report-link-") as raw:
        state = Path(raw).resolve()
        outside = state / "outside"
        outside.mkdir()
        link = state / "activation-reports"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            pass
        else:
            try:
                module._write_private_report(state, report)
            except module.ActivationStatusError:
                pass
            else:
                raise AssertionError("linked report directory was accepted")
            check(list(outside.iterdir()) == [], "linked report directory received output")

    with tempfile.TemporaryDirectory(prefix="activation-watch-cli-") as raw:
        report_path = Path(raw).resolve() / "report file.json"
        report_path.write_bytes(b"{}\n")
        fake_result = {
            "ok": False,
            "status": "timeout",
            "active": 1,
            "total": 2,
            "pending": 1,
            "report_sha256": "a" * 64,
            "report_bytes": 3,
        }
        output = io.StringIO()
        with mock.patch.object(
            module,
            "watch",
            return_value=(fake_result, report_path, "a" * 64, 3),
        ) as watched:
            with redirect_stdout(output):
                status = module.main(
                    [
                        "--journal",
                        str(Path(raw).resolve() / "journal.json"),
                        "--plan-digest",
                        "b" * 64,
                        "--runtime",
                        "codex",
                        "--watch",
                        "--target",
                        "main",
                        "--target",
                        "parall",
                        "--wait-seconds",
                        "0",
                    ]
                )
        check(status == 2, "watch timeout did not return the incomplete exit status")
        lines = output.getvalue().splitlines()
        check(len(lines) == 1 and lines[0].startswith("REPORT_SAVED "), "watch stdout was not one receipt")
        receipt = json.loads(lines[0].split(" ", 1)[1])
        check(receipt["filename"] == str(report_path), "receipt omitted the report filename")
        check(receipt["status"] == "timeout", "receipt status is wrong")
        check(receipt["active"] == "1/2" and receipt["pending"] == 1, "receipt counts are wrong")
        check("id_" not in lines[0] and "target_v1_" not in lines[0], "receipt leaked identities")
        check(
            watched.call_args.kwargs["selected_targets"] == ["main", "parall"],
            "repeatable target selection was not passed to the watch",
        )

        output = io.StringIO()
        with redirect_stdout(output):
            invalid = module.main(
                [
                    "--journal",
                    str(Path(raw).resolve() / "journal.json"),
                    "--plan-digest",
                    "b" * 64,
                    "--runtime",
                    "codex",
                    "--watch",
                    "--wait-seconds",
                    "901",
                ]
            )
        check(invalid == 1, "watch accepted an unbounded timeout")


def main() -> int:
    check(validate_contract(ROOT) == [], f"live contract failed: {validate_contract(ROOT)}")
    readme = optional_repository_readme(README_PATH)
    if readme is not None:
        check(
            validate_readme_zero_terminal(readme) == [],
            f"README zero-Terminal contract failed: {validate_readme_zero_terminal(readme)}",
        )

        unsafe_readme = readme.replace("install defer", "install apply", 1)
        check(
            "README normal path exposes install apply"
            in validate_readme_zero_terminal(unsafe_readme),
            "README normal-path direct apply fixture was missed",
        )
        manual_terminal_readme = readme.replace(
            "The user never opens Terminal",
            "The user opens Terminal",
            1,
        )
        check(
            "README missing no user Terminal"
            in validate_readme_zero_terminal(manual_terminal_readme),
            "README manual-Terminal fixture was missed",
        )
        filenameless_readme = readme.replace("`filename`", "artifact", 1)
        check(
            "README missing filename receipt"
            in validate_readme_zero_terminal(filenameless_readme),
            "README filename-bearing deferred receipt fixture was missed",
        )
        for old, new, expected in (
            (
                "86400 seconds and is bounded to 1 through 604800 seconds",
                "900 seconds and is bounded to 1 through 3600 seconds",
                "README missing deferred wait bounds",
            ),
            (
                "one-shot and nonpersistent",
                "persistent background service",
                "README missing one-shot nonpersistent worker",
            ),
            (
                "one-shot and nonpersistent: an OS reboot ends it and requires an agent-owned",
                "one-shot and nonpersistent: an OS reboot leaves the old plan reusable by the user",
                "README missing agent-owned reboot recovery",
            ),
            (
                "The user only repeats the close/reopen boundary after a",
                "The user replans and runs recovery commands after a",
                "README missing reboot user close/reopen only",
            ),
            (
                "strict receipt for the exact job and plan digest proves no mutation",
                "best-effort status suggests no mutation",
                "README missing strict no-mutation fallback",
            ),
            (
                "never authorizes apply, trust review, activation, or",
                "authorizes apply, trust review, activation, and",
                "README missing failure fallback authorization boundary",
            ),
        ):
            mutated = readme.replace(old, new, 1)
            check(
                mutated != readme,
                f"README deferred recovery mutation did not change source: {expected}",
            )
            check(
                expected in validate_readme_zero_terminal(mutated),
                f"README deferred recovery fixture was missed: {expected}",
            )

    temporary = Path(tempfile.mkdtemp(prefix="install-hooks-skill-self-test-"))
    try:
        check(
            optional_repository_readme(temporary / "standalone" / "README.md")
            is None,
            "standalone skill copy incorrectly required repository README",
        )
        fixture = temporary / "skill"
        shutil.copytree(ROOT, fixture)

        skill_path = fixture / "SKILL.md"
        original = skill_path.read_text(encoding="utf-8")
        skill_path.write_text(
            original.replace("install defer", "install apply", 1),
            encoding="utf-8",
        )
        check(
            "normal path exposes install apply" in validate_contract(fixture),
            "skill normal-path direct apply fixture was missed",
        )
        skill_path.write_text(
            original.replace(
                "user never opens Terminal",
                "user opens Terminal",
                1,
            ),
            encoding="utf-8",
        )
        check(
            "missing no normal Terminal" in validate_contract(fixture),
            "skill manual-Terminal fixture was missed",
        )
        skill_path.write_text(
            original.replace("status-report `filename`", "status artifact", 1),
            encoding="utf-8",
        )
        check(
            "missing deferred filename" in validate_contract(fixture),
            "skill filename-bearing deferred receipt fixture was missed",
        )
        for old, new, expected in (
            (
                "defaults to 86400 seconds and accepts only 1 through 604800 seconds",
                "defaults to 900 seconds and accepts only 1 through 3600 seconds",
                "missing bounded deferred wait",
            ),
            (
                "Keep the worker one-shot and nonpersistent",
                "Keep the worker as a persistent background service",
                "missing one-shot nonpersistent worker",
            ),
            (
                "the agent to create a fresh plan and rearm",
                "the user to reuse the old plan after reboot",
                "missing agent-owned reboot recovery",
            ),
            (
                "strict receipt for the exact job and plan digest proves that no",
                "best-effort status suggests that no",
                "missing strict no-mutation fallback",
            ),
            (
                "never authorizes apply, trust review, activation,",
                "authorizes apply, trust review, activation,",
                "missing failure fallback authorization boundary",
            ),
            (
                "ask the user only to repeat the",
                "ask the user to replan and run",
                "missing reboot user close/reopen only",
            ),
        ):
            mutated = original.replace(old, new, 1)
            check(
                mutated != original,
                f"skill deferred recovery mutation did not change source: {expected}",
            )
            skill_path.write_text(mutated, encoding="utf-8")
            check(
                expected in validate_contract(fixture),
                f"skill deferred recovery mutation missed: {expected}",
            )
        skill_path.write_text(original, encoding="utf-8")
        skill_path.write_text(
            original.replace("Never edit Codex's trust store", "Edit Codex's trust store"),
            encoding="utf-8",
        )
        check("missing no-auto-trust rule" in validate_contract(fixture), "auto-trust gap missed")
        skill_path.write_text(original, encoding="utf-8")

        proportional_security_mutations = (
            (
                "verified non-rotating repair",
                "every recorder repair",
                "missing routine repair boundary",
            ),
            (
                "wrong answer could select unnecessary controls",
                "the file is absent",
                "missing security question materiality",
            ),
            (
                "smallest concise set",
                "complete questionnaire",
                "missing smallest security question",
            ),
            (
                "baseline only when that decision materially depends on every area",
                "baseline whenever the file is absent",
                "missing conditional full baseline",
            ),
        )
        for old, new, expected in proportional_security_mutations:
            skill_path.write_text(original.replace(old, new, 1), encoding="utf-8")
            check(
                expected in validate_contract(fixture),
                f"proportional security mutation missed: {expected}",
            )
        skill_path.write_text(original, encoding="utf-8")

        reference = fixture / "references" / "platform-prerequisites.md"
        reference_original = reference.read_text(encoding="utf-8")
        reference.write_text(
            reference_original.replace("## WSL", "## Linux subsystem"),
            encoding="utf-8",
        )
        check("missing platform WSL" in validate_contract(fixture), "WSL coverage gap missed")
        for old, new, expected in (
            (
                "1-through-604800-second wait (86400 seconds by default)",
                "1-through-3600-second wait (900 seconds by default)",
                "missing platform deferred wait bounds",
            ),
            (
                "It is one-shot and nonpersistent",
                "It is a persistent background service",
                "missing platform one-shot nonpersistent worker",
            ),
            (
                "reboot ends it and requires agent-owned replan and rearm",
                "reboot leaves the old plan reusable by the user",
                "missing platform agent-owned reboot recovery",
            ),
            (
                "rearm; the user only repeats",
                "rearm; the user replans and runs recovery commands",
                "missing platform reboot user close/reopen only",
            ),
            (
                "the exact job and plan digest proves no mutation",
                "best-effort status suggests no mutation",
                "missing platform strict no-mutation fallback",
            ),
            (
                "never authorizes apply, trust review,",
                "authorizes apply, trust review,",
                "missing platform failure fallback authorization boundary",
            ),
        ):
            mutated = reference_original.replace(old, new, 1)
            check(
                mutated != reference_original,
                f"platform deferred recovery mutation did not change source: {expected}",
            )
            reference.write_text(mutated, encoding="utf-8")
            check(
                expected in validate_contract(fixture),
                f"platform deferred recovery mutation missed: {expected}",
            )
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

    target_a = "id_" + "d" * 32
    target_b = "id_" + "e" * 32
    targeted_events = [
        event(11, "codex", "codex-hooks", "task.start", "a", "prompt_submit", target_id=target_a),
        event(12, "codex", "codex-hooks", "task.start", "b", "prompt_submit", target_id=target_b),
        event(
            13,
            "codex",
            "codex-otel",
            "usage.observed",
            "b",
            "otel_response_completed",
            "provider-native",
            target_id=target_b,
        ),
        event(
            14,
            "codex",
            "codex-otel",
            "usage.observed",
            "a",
            "otel_response_completed",
            "provider-native",
            target_id=target_a,
        ),
    ]
    validate_realistic_events(targeted_events, module)
    targeted = module.summarize_events(
        targeted_events,
        after_sequence=10,
        selected_runtime="codex",
        expected_targets={"main": target_a, "parall": target_b},
    )
    check(targeted["targets"]["main"]["active"] is True, "main target was not activated")
    check(targeted["targets"]["parall"]["active"] is True, "Parall target was not activated")

    wrong_target_usage = module.summarize_events(
        [
            event(15, "codex", "codex-hooks", "task.start", "a", "prompt_submit", target_id=target_a),
            event(
                16,
                "codex",
                "codex-otel",
                "usage.observed",
                "a",
                "otel_response_completed",
                "provider-native",
                target_id=target_b,
            ),
        ],
        after_sequence=14,
        selected_runtime="codex",
        expected_targets={"main": target_a, "parall": target_b},
    )
    check(
        wrong_target_usage["targets"]["main"]["active"] is False,
        "cross-target usage activated main",
    )

    null_target_usage_event = event(
        18,
        "codex",
        "codex-otel",
        "usage.observed",
        "a",
        "otel_response_completed",
        "provider-native",
        schema_version="1.2",
    )
    null_target_events = [
        event(17, "codex", "codex-hooks", "task.start", "a", "prompt_submit", target_id=target_a),
        null_target_usage_event,
    ]
    validate_realistic_events(null_target_events, module)
    null_target_usage = module.summarize_events(
        null_target_events,
        after_sequence=16,
        selected_runtime="codex",
        expected_targets={"main": target_a},
    )
    check(
        null_target_usage["targets"]["main"]["active"] is False,
        "null-target usage activated main",
    )

    legacy_target = module.summarize_events(
        codex_events,
        after_sequence=0,
        selected_runtime="codex",
        expected_targets={"main": target_a},
    )
    check(legacy_target["runtimes"]["codex"]["active"] is True, "legacy family proof disappeared")
    check(legacy_target["targets"]["main"]["active"] is False, "legacy family proof activated a home")
    check(
        legacy_target["target_attribution"]["legacy_codex_hook_events"] == 1,
        "legacy hook evidence was not reported honestly",
    )

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
    check_report_and_watch_cli(module)
    check_codex_config_activation_conformance(module)
    check_journal_bound_integration(module)

    print("install-delivery-efficiency-hooks self-test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
