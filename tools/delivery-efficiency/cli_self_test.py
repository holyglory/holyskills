#!/usr/bin/env python3
"""CLI failure classification and authoritative reporting tests."""

from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
from io import BytesIO, StringIO
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest import mock
from urllib.error import HTTPError


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from delivery_efficiency import cli as cli_module
from delivery_efficiency.cli import MANAGED_ID, UnsupportedHookRuntime, _hook, _hook_gap_code, main
from delivery_efficiency.codex import MalformedSourceEvent, translate_hook
from delivery_efficiency.runtime import RuntimeConfigurationError
from delivery_efficiency.storage import Recorder, StorageUnavailableError


class FakeMonotonic:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def assert_hook_deadline_budget(root: Path) -> None:
    """Exercise delayed receiver startup and posting without wall-clock sleeps."""

    host_timeout = cli_module.CODEX_HOOK_TIMEOUT_SECONDS
    telemetry_budget = cli_module.CODEX_HOOK_TELEMETRY_BUDGET_SECONDS
    runtime_margin = cli_module.CODEX_HOOK_RUNTIME_MARGIN_SECONDS
    assert host_timeout == 3
    assert telemetry_budget == 2.25
    assert runtime_margin == 0.75
    assert telemetry_budget + runtime_margin <= host_timeout
    assert runtime_margin > 0

    state = root / "bounded hook timing"
    arguments = argparse.Namespace(
        state_dir=str(state),
        managed_id=MANAGED_ID,
        runtime="codex",
    )
    source = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "session-budget",
        "turn_id": "turn-budget",
        "prompt": "PROMPT-BUDGET-CANARY",
    }
    encoded = json.dumps(source, separators=(",", ":")).encode("utf-8")
    ready_settings = {"receiver": "already-authenticated"}

    clock = FakeMonotonic()
    ensure_timeouts = []
    post_timeouts = []

    def delayed_ensure(_state, *, timeout_seconds):
        ensure_timeouts.append(timeout_seconds)
        clock.advance(1.5)
        return ready_settings

    def delayed_post(settings, envelopes, *, timeout_seconds):
        assert settings is ready_settings
        serialized = json.dumps(list(envelopes), sort_keys=True)
        assert "PROMPT-BUDGET-CANARY" not in serialized
        post_timeouts.append(timeout_seconds)
        clock.advance(timeout_seconds)
        return {"ok": True, "recorded": 1}

    with (
        mock.patch.object(sys, "stdin", SimpleNamespace(buffer=BytesIO(encoded))),
        mock.patch("time.monotonic", side_effect=clock),
        mock.patch.object(cli_module, "ensure_receiver", side_effect=delayed_ensure),
        mock.patch(
            "delivery_efficiency.runtime.post_observations_to_receiver",
            side_effect=delayed_post,
            create=True,
        ),
        mock.patch(
            "delivery_efficiency.runtime.post_observations",
            side_effect=AssertionError("hook must not repeat receiver startup"),
        ),
        mock.patch.object(cli_module, "record_local_gap") as record_gap,
    ):
        assert _hook(arguments) == 0
    assert not record_gap.called
    assert ensure_timeouts == [telemetry_budget]
    assert len(post_timeouts) == 1
    assert 0 < post_timeouts[0] <= telemetry_budget - 1.5
    assert clock.value - 100.0 <= telemetry_budget

    exhausted_clock = FakeMonotonic()

    def exhausting_ensure(_state, *, timeout_seconds):
        exhausted_clock.advance(timeout_seconds)
        return ready_settings

    with (
        mock.patch.object(sys, "stdin", SimpleNamespace(buffer=BytesIO(encoded))),
        mock.patch("time.monotonic", side_effect=exhausted_clock),
        mock.patch.object(cli_module, "ensure_receiver", side_effect=exhausting_ensure),
        mock.patch(
            "delivery_efficiency.runtime.post_observations_to_receiver",
            create=True,
        ) as post,
        mock.patch.object(cli_module, "record_local_gap") as record_gap,
    ):
        assert _hook(arguments) == 0
    assert not post.called
    record_gap.assert_called_once_with(state, "receiver-unavailable")
    assert exhausted_clock.value - 100.0 == telemetry_budget


def assert_claude_prompt_deadline_budget(root: Path) -> None:
    """Prove prompt telemetry cannot consume Claude's one-second host limit."""

    host_timeout = cli_module.CLAUDE_PROMPT_HOOK_TIMEOUT_SECONDS
    telemetry_budget = cli_module.CLAUDE_PROMPT_HOOK_TELEMETRY_BUDGET_SECONDS
    assert host_timeout == 1
    assert telemetry_budget == 0.75
    assert 0 < telemetry_budget < host_timeout

    state = root / "bounded claude prompt timing"
    arguments = argparse.Namespace(
        state_dir=str(state),
        managed_id=MANAGED_ID,
        runtime="claude",
    )
    source = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "session-claude-budget",
        "prompt_id": "123e4567-e89b-42d3-a456-426614174000",
        "prompt": "CLAUDE-PROMPT-BUDGET-CANARY",
    }
    encoded = json.dumps(source, separators=(",", ":")).encode("utf-8")
    ready_settings = {"receiver": "already-authenticated"}
    clock = FakeMonotonic()
    ensure_timeouts = []
    post_timeouts = []

    def delayed_ensure(_state, *, timeout_seconds):
        ensure_timeouts.append(timeout_seconds)
        clock.advance(0.5)
        return ready_settings

    def delayed_post(settings, envelopes, *, timeout_seconds):
        assert settings is ready_settings
        serialized = json.dumps(list(envelopes), sort_keys=True)
        assert "CLAUDE-PROMPT-BUDGET-CANARY" not in serialized
        post_timeouts.append(timeout_seconds)
        clock.advance(timeout_seconds)
        return {"ok": True, "recorded": 1}

    with (
        mock.patch.object(sys, "stdin", SimpleNamespace(buffer=BytesIO(encoded))),
        mock.patch("time.monotonic", side_effect=clock),
        mock.patch.object(cli_module, "ensure_receiver", side_effect=delayed_ensure),
        mock.patch(
            "delivery_efficiency.runtime.post_observations_to_receiver",
            side_effect=delayed_post,
            create=True,
        ),
        mock.patch.object(cli_module, "record_local_gap") as record_gap,
    ):
        assert _hook(arguments) == 0
    assert not record_gap.called
    assert ensure_timeouts == [telemetry_budget]
    assert len(post_timeouts) == 1
    assert 0 < post_timeouts[0] <= telemetry_budget - 0.5
    assert clock.value - 100.0 <= telemetry_budget

    exhausted_clock = FakeMonotonic()

    def exhausting_ensure(_state, *, timeout_seconds):
        exhausted_clock.advance(timeout_seconds)
        return ready_settings

    with (
        mock.patch.object(sys, "stdin", SimpleNamespace(buffer=BytesIO(encoded))),
        mock.patch("time.monotonic", side_effect=exhausted_clock),
        mock.patch.object(cli_module, "ensure_receiver", side_effect=exhausting_ensure),
        mock.patch(
            "delivery_efficiency.runtime.post_observations_to_receiver",
            create=True,
        ) as post,
        mock.patch.object(cli_module, "record_local_gap") as record_gap,
    ):
        assert _hook(arguments) == 0
    assert not post.called
    record_gap.assert_called_once_with(state, "receiver-unavailable")
    assert exhausted_clock.value - 100.0 == telemetry_budget


def assert_runtime_target_validation(root: Path) -> None:
    source = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "runtime-target-session",
        "turn_id": "runtime-target-turn",
    }
    encoded = json.dumps(source, separators=(",", ":")).encode("utf-8")
    valid = "target_v1_" + "a" * 32
    parsed = cli_module.build_parser().parse_args(
        ["hook", "codex", "--runtime-target", valid]
    )
    assert parsed.runtime_target == valid

    for supplied in (valid, None):
        state = root / ("runtime target " + ("present" if supplied else "legacy missing"))
        arguments = argparse.Namespace(
            state_dir=str(state),
            managed_id=MANAGED_ID,
            runtime="codex",
            runtime_target=supplied,
        )
        with (
            mock.patch.object(sys, "stdin", SimpleNamespace(buffer=BytesIO(encoded))),
            mock.patch(
                "delivery_efficiency.codex.translate_hook",
                return_value=[],
            ) as translated,
            mock.patch.object(cli_module, "ensure_receiver", return_value={}),
            mock.patch.object(cli_module, "record_local_gap") as record_gap,
        ):
            assert _hook(arguments) == 0
        assert not record_gap.called
        assert translated.call_args.kwargs["runtime_target"] == supplied

    invalid_values = (
        "target_v1_short",
        "target_v1_" + "A" * 32,
        "target_v1_" + "g" * 32,
        "/private/runtime/home",
        "a" * 64,
    )
    for index, supplied in enumerate(invalid_values):
        state = root / "invalid runtime target {}".format(index)
        arguments = argparse.Namespace(
            state_dir=str(state),
            managed_id=MANAGED_ID,
            runtime="codex",
            runtime_target=supplied,
        )
        with (
            mock.patch.object(sys, "stdin", SimpleNamespace(buffer=BytesIO(encoded))),
            mock.patch("delivery_efficiency.codex.translate_hook") as translated,
            mock.patch.object(cli_module, "ensure_receiver") as ensure,
            mock.patch.object(cli_module, "record_local_gap") as record_gap,
        ):
            assert _hook(arguments) == 0
        assert not translated.called
        assert not ensure.called
        record_gap.assert_called_once_with(state, "malformed-source-event")

    claude_arguments = argparse.Namespace(
        state_dir=str(root / "Claude runtime target refusal"),
        managed_id=MANAGED_ID,
        runtime="claude",
        runtime_target=valid,
    )
    with (
        mock.patch.object(sys, "stdin", SimpleNamespace(buffer=BytesIO(encoded))),
        mock.patch("delivery_efficiency.claude.translate_hook") as translated,
        mock.patch.object(cli_module, "ensure_receiver") as ensure,
        mock.patch.object(cli_module, "record_local_gap") as record_gap,
    ):
        assert _hook(claude_arguments) == 0
    assert not translated.called
    assert not ensure.called
    record_gap.assert_called_once_with(
        Path(claude_arguments.state_dir), "malformed-source-event"
    )


def assert_install_apply_uses_transactional_activation(root: Path) -> None:
    """Apply must not repeat health activation after the installer commits."""

    plan = SimpleNamespace(
        journal={"target": {"state_root": str(root / "installer state")}}
    )
    arguments = argparse.Namespace(
        journal=str(root / "transaction" / "journal.json"),
        plan_digest="a" * 64,
        install_action="apply",
    )
    result = {
        "ok": True,
        "status": "applied",
        "receiver_healthy": True,
    }
    stdout = StringIO()
    with (
        mock.patch("delivery_efficiency.installer.load_plan", return_value=plan) as load_plan,
        mock.patch("delivery_efficiency.installer.apply_install", return_value=result),
        mock.patch.object(
            cli_module,
            "ensure_receiver",
            side_effect=AssertionError("CLI must not reactivate after transactional apply"),
        ),
        redirect_stdout(stdout),
    ):
        assert cli_module._install_action(arguments) == 0
    load_plan.assert_called_once_with(
        Path(arguments.journal),
        expected_plan_digest=arguments.plan_digest,
    )
    output = json.loads(stdout.getvalue())
    assert output["receiver_healthy"] is True
    assert output["hook_trust"] == "requires-review-or-observed-hook"


def complete_terminal_arguments(root: Path) -> List[str]:
    return [
        "declare",
        "terminal",
        "--outcome",
        "complete",
        "--verification",
        "verified",
        "--task-kind",
        "primary",
        "--cause",
        "not-applicable",
        "--requirement",
        "REQ-CLI=satisfied:verified",
        "--evidence",
        "REQ-CLI=test:cli-terminal",
        "--acceptance-baseline",
        "baseline:cli-v1",
        "--scope-change",
        "scope:approved-1",
        "--task-type",
        "implementation",
        "--scope-size",
        "small",
        "--method",
        "direct",
        "--policy-version",
        "policy:v1",
        "--model-config-version",
        "model:v1",
        "--runtime-config-version",
        "runtime:v1",
        "--recorder-config-version",
        "recorder:v1",
        "--runtime",
        "claude",
        "--session",
        "cli-session",
        "--state-dir",
        str(root / "cli declaration state"),
    ]


def remove_option(arguments: List[str], option: str) -> List[str]:
    result = list(arguments)
    index = result.index(option)
    del result[index : index + 2]
    return result


def assert_cli_declaration_interfaces(root: Path) -> None:
    """Exercise v1.1 mapping, bindings, and fail-closed completion."""

    task_binding = "task_" + "a" * 32
    stdout = StringIO()
    terminal_arguments = complete_terminal_arguments(root) + ["--emit-task-binding"]
    with (
        mock.patch.object(
            cli_module,
            "_record_declarations",
            return_value={"ok": True, "recorded": 2, "task_binding": task_binding},
        ) as record_declarations,
        mock.patch.object(cli_module, "_export_repository_summary_to_coordinator") as export,
        redirect_stdout(stdout),
    ):
        assert main(terminal_arguments) == 0
    assert json.loads(stdout.getvalue()) == {"task_binding": task_binding}
    export.assert_called_once()
    call = record_declarations.call_args
    assert call.args[1:3] == ("cli-session", False)
    emissions = call.args[3]
    assert [item[0]["event"] for item in emissions] == [
        "requirement.status",
        "task.terminal",
    ]
    requirement_payload = emissions[0][0]["payload"]
    assert requirement_payload["requirement_id"] == "REQ-CLI"
    assert requirement_payload["evidence"] == {
        "refs": ["test:cli-terminal"],
        "provenance": "agent-declared",
    }
    terminal_payload = emissions[1][0]["payload"]
    assert terminal_payload["task_metadata"] == {
        "acceptance_baseline_id": "baseline:cli-v1",
        "acceptance_baseline_provenance": "agent-declared",
        "approved_scope_change_ids": ["scope:approved-1"],
        "scope_change_provenance": "agent-declared",
        "task_kind_provenance": "agent-declared",
        "task_type": "implementation",
        "task_type_provenance": "agent-declared",
        "scope_size": "small",
        "scope_size_provenance": "agent-declared",
        "method": "direct",
        "method_provenance": "agent-declared",
        "classifier_version": "task-v1",
    }
    assert terminal_payload["configuration"] == {
        "policy_version": "policy:v1",
        "policy_provenance": "agent-declared",
        "model_config_version": "model:v1",
        "model_config_provenance": "agent-declared",
        "runtime_config_version": "runtime:v1",
        "runtime_config_provenance": "agent-declared",
        "recorder_config_version": "recorder:v1",
        "recorder_config_provenance": "agent-declared",
    }

    empty_scope_arguments = complete_terminal_arguments(root)
    scope_index = empty_scope_arguments.index("--scope-change")
    empty_scope_arguments[scope_index : scope_index + 2] = ["--no-scope-changes"]
    with (
        mock.patch.object(
            cli_module,
            "_record_declarations",
            return_value={"ok": True, "recorded": 2, "task_binding": task_binding},
        ) as record_declarations,
        mock.patch.object(cli_module, "_export_repository_summary_to_coordinator") as export,
    ):
        assert main(empty_scope_arguments) == 0
    export.assert_called_once()
    empty_scope_terminal = record_declarations.call_args.args[3][-1][0]["payload"]
    assert empty_scope_terminal["task_metadata"]["approved_scope_change_ids"] == []
    assert (
        empty_scope_terminal["task_metadata"]["scope_change_provenance"]
        == "agent-declared"
    )

    with mock.patch(
        "delivery_efficiency.exec_runner.run_codex_exec", return_value=0
    ) as run_codex_exec:
        assert main(
            [
                "codex-exec",
                "--outcome",
                "incomplete",
                "--verification",
                "unverified",
                "--",
                "fixture request",
            ]
        ) == 0
    incomplete_declaration = run_codex_exec.call_args.kwargs[
        "terminal_declaration"
    ]
    for omitted in (
        "acceptance_baseline_id",
        "approved_scope_change_ids",
        "task_type",
        "scope_size",
        "method",
        "policy_version",
        "model_config_version",
        "runtime_config_version",
        "recorder_config_version",
    ):
        assert omitted not in incomplete_declaration

    current_binding = "binding_" + "b" * 32
    linked_binding = "task_" + "c" * 32
    with mock.patch.object(
        cli_module,
        "_record_declarations",
        return_value={"ok": True, "recorded": 1, "task_binding": task_binding},
    ) as record_declarations:
        assert main(
            [
                "declare",
                "lineage",
                "--linked-task-binding",
                linked_binding,
                "--task-kind",
                "defect-repair",
                "--cause",
                "agent-caused-mistake",
                "--runtime",
                "codex",
                "--binding",
                current_binding,
                "--state-dir",
                str(root / "cli declaration state"),
            ]
        ) == 0
    lineage_call = record_declarations.call_args
    assert lineage_call.args[1:3] == (current_binding, True)
    assert lineage_call.kwargs == {"linked_task_binding": linked_binding}
    assert lineage_call.args[3][0][0]["event"] == "lineage.link"

    target_binding = "task_" + "d" * 32
    with mock.patch.object(
        cli_module,
        "_record_declarations",
        return_value={"ok": True, "recorded": 1, "task_binding": task_binding},
    ) as record_declarations:
        assert main(
            [
                "declare",
                "correction",
                "requirement",
                "--target-event",
                "e" * 32,
                "--target-task-binding",
                target_binding,
                "--requirement-id",
                "REQ-CLI",
                "--status",
                "satisfied",
                "--verification",
                "verified",
                "--evidence-ref",
                "test:correction",
                "--runtime",
                "claude",
                "--binding",
                current_binding,
                "--state-dir",
                str(root / "cli declaration state"),
            ]
        ) == 0
    correction_call = record_declarations.call_args
    assert correction_call.args[1:3] == (current_binding, True)
    assert correction_call.kwargs == {"target_task_binding": target_binding}
    correction_payload = correction_call.args[3][0][0]["payload"]
    assert correction_payload["correction"] == {
        "event_id": "e" * 32,
        "provenance": "agent-declared",
    }

    required_options = (
        "--acceptance-baseline",
        "--scope-change",
        "--task-type",
        "--scope-size",
        "--method",
        "--evidence",
    )
    for missing_option in required_options:
        stderr = StringIO()
        with (
            mock.patch.object(cli_module, "_record_declarations") as record_declarations,
            redirect_stderr(stderr),
        ):
            assert main(remove_option(complete_terminal_arguments(root), missing_option)) == 2
        assert not record_declarations.called
        assert stderr.getvalue() == "delivery-efficiency error: DeclarationError\n"


def assert_optional_coordinator_projection(root: Path) -> None:
    project = str(root / "private repository")
    executable = "/usr/local/bin/devcoordinator"
    capability = SimpleNamespace(
        returncode=0,
        stdout=json.dumps(
            {
                "ok": True,
                "capabilities": {
                    "efficiency": {"schema_version": 1, "actions": ["ingest"]}
                },
            }
        ).encode("utf-8"),
    )
    with mock.patch.object(cli_module.subprocess, "run", return_value=capability) as run:
        assert cli_module._coordinator_supports_efficiency(executable, project)
    assert run.call_args.args[0] == [executable, "capabilities", "--project", project]
    assert run.call_args.kwargs["cwd"] == project

    missing = SimpleNamespace(returncode=0, stdout=b'{"ok":true,"capabilities":{}}')
    with mock.patch.object(cli_module.subprocess, "run", return_value=missing):
        assert not cli_module._coordinator_supports_efficiency(executable, project)

    opaque = "id_" + "7" * 32
    repository = {
        "project_id": opaque,
        "task_count": 1,
        "complete_task_count": 1,
        "outcomes": {"complete": 1},
        "causes": {"not-applicable": 1},
        "tokens": {},
        "tokens_by_phase": {},
        "request_to_delivery_ns": {},
        "execution_to_delivery_ns": {},
        "automation_opportunities": [],
    }
    recorder = mock.MagicMock()
    recorder.__enter__.return_value = recorder
    recorder.__exit__.return_value = False
    recorder.opaque_id.return_value = opaque
    recorder.read_verified_events.return_value = [{"private": "must-not-export"}]
    ingested = SimpleNamespace(returncode=0, stdout=b"")
    with (
        mock.patch.object(cli_module.shutil, "which", return_value=executable),
        mock.patch.object(cli_module, "_discover_worktree", return_value=project),
        mock.patch.object(cli_module, "_coordinator_supports_efficiency", return_value=True),
        mock.patch("delivery_efficiency.storage.Recorder", return_value=recorder),
        mock.patch(
            "delivery_efficiency.reporting.summarize_repositories",
            return_value={"repositories": [repository]},
        ),
        mock.patch.object(cli_module.subprocess, "run", return_value=ingested) as run,
    ):
        assert cli_module._export_repository_summary_to_coordinator(root)
    call = run.call_args
    assert call.args[0] == [executable, "efficiency", "ingest", "--project", project]
    payload = json.loads(call.kwargs["input"].decode("utf-8"))
    assert payload == {"schema_version": 1, "summary": repository}
    assert project not in call.kwargs["input"].decode("utf-8")
    assert "must-not-export" not in call.kwargs["input"].decode("utf-8")

    with mock.patch.object(cli_module.shutil, "which", return_value=None):
        assert not cli_module._export_repository_summary_to_coordinator(root)


def main_test() -> int:
    assert _hook_gap_code(MalformedSourceEvent("private source detail")) == "malformed-source-event"
    assert _hook_gap_code(UnsupportedHookRuntime("private runtime detail")) == "unsupported-runtime-event"
    assert _hook_gap_code(RuntimeConfigurationError("private settings detail")) == "receiver-unavailable"
    assert _hook_gap_code(StorageUnavailableError("private spool detail")) == "storage-unavailable"
    unavailable = HTTPError("http://127.0.0.1", 503, "private", {}, None)
    assert _hook_gap_code(unavailable) == "storage-unavailable"

    with tempfile.TemporaryDirectory(prefix="delivery-cli-") as raw:
        root = Path(raw).resolve()
        assert_hook_deadline_budget(root)
        assert_claude_prompt_deadline_budget(root)
        assert_runtime_target_validation(root)
        assert_install_apply_uses_transactional_activation(root)
        assert_cli_declaration_interfaces(root)
        assert_optional_coordinator_projection(root)
        unavailable_state = root / "receiver unavailable"
        arguments = argparse.Namespace(
            state_dir=str(unavailable_state),
            managed_id=MANAGED_ID,
            runtime="codex",
        )
        source = {
            "hook_event_name": "Stop",
            "session_id": "session-unavailable",
            "turn_id": "turn-unavailable",
        }
        hook_stdin = SimpleNamespace(
            buffer=BytesIO(json.dumps(source, separators=(",", ":")).encode("utf-8"))
        )
        hook_stdout = StringIO()
        with mock.patch.object(sys, "stdin", hook_stdin), redirect_stdout(hook_stdout):
            assert _hook(arguments) == 0
        assert json.loads(hook_stdout.getvalue()) == {}
        gap = json.loads((unavailable_state / "last-runtime-gap.json").read_text(encoding="utf-8"))
        assert gap["gap_code"] == "receiver-unavailable"

        malformed_state = root / "malformed source"
        arguments.state_dir = str(malformed_state)
        malformed_stdin = SimpleNamespace(buffer=BytesIO(b"{"))
        with mock.patch.object(sys, "stdin", malformed_stdin):
            assert _hook(arguments) == 0
        gap = json.loads((malformed_state / "last-runtime-gap.json").read_text(encoding="utf-8"))
        assert gap["gap_code"] == "malformed-source-event"

        state = root / "authoritative report"
        project = root / "readable repository"
        (project / ".git").mkdir(parents=True)
        recorder = Recorder(state)
        observation, source_key = translate_hook(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "session-1",
                "turn_id": "turn-1",
                "cwd": str(project),
                "prompt": "PROMPT-MUST-NOT-PERSIST",
            },
            surface="cli-interactive",
            source_project=str(project),
        )[0]
        recorder.record(observation, source_key=source_key)
        recorder.close()

        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            assert main(["report", "--state-dir", str(state)]) == 0
        report = json.loads(stdout.getvalue())
        assert report["task_count"] == 1
        assert report["tasks"][0]["display_name"] == "readable repository task 1"
        assert "PROMPT-MUST-NOT-PERSIST" not in stdout.getvalue()
        assert str(project) not in stdout.getvalue()

        stdout = StringIO()
        with redirect_stdout(stdout):
            assert main(["report", "--tasks", "--state-dir", str(state)]) == 0
        task_report = json.loads(stdout.getvalue())
        assert task_report["tasks"][0]["repository"] == "readable repository"
        assert task_report["tasks"][0]["display_name"] == "readable repository task 1"
        assert str(project) not in stdout.getvalue()

        stdout = StringIO()
        with redirect_stdout(stdout):
            assert main(["report", "--repositories", "--state-dir", str(state)]) == 0
        repository_report = json.loads(stdout.getvalue())
        assert repository_report["repositories"][0]["display_name"] == "readable repository"
        assert str(project) not in stdout.getvalue()

        ledger = state / "EfficiencyLedger.jsonl"
        event = json.loads(ledger.read_text(encoding="utf-8"))
        ledger.write_text(json.dumps(event, sort_keys=True) + "\n", encoding="utf-8")
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            assert main(["report", "--state-dir", str(state)]) == 2
        assert stdout.getvalue() == ""
        assert "LedgerIntegrityError" in stderr.getvalue()
        assert "PROMPT-MUST-NOT-PERSIST" not in stderr.getvalue()

    print("cli self-test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_test())
