#!/usr/bin/env python3
"""Command and subprocess accounting contract for controlled Codex exec."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from delivery_efficiency.exec_runner import (
    WRAPPED_CODEX_EXEC_ENV,
    _child_environment,
    _command,
    run_codex_exec,
)
from delivery_efficiency.reporting import read_ledger, summarize


def _write_fake_codex(path: Path) -> None:
    """Create a child that models inherited managed hooks and Codex OTLP."""

    source = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, os.environ["HOLYSKILLS_TEST_PACKAGE_ROOT"])

from delivery_efficiency.codex import record_emissions, translate_hook, translate_otlp
from delivery_efficiency.storage import Recorder

state = Path(os.environ["HOLYSKILLS_TEST_STATE"])
home = Path(os.environ["CODEX_HOME"])
arguments = sys.argv[1:]
managed_hook_suppressed = (
    os.environ.get("HOLYSKILLS_DELIVERY_EFFICIENCY_WRAPPED_CODEX_EXEC") == "1"
)
managed_otel_suppressed = any(
    arguments[index] in {"-c", "--config"}
    and index + 1 < len(arguments)
    and arguments[index + 1] == 'otel.exporter="none"'
    for index in range(len(arguments))
)
hooks_globally_disabled = any(
    arguments[index] in {"-c", "--config"}
    and index + 1 < len(arguments)
    and arguments[index + 1] in {"features.hooks=false", "features.codex_hooks=false"}
    for index in range(len(arguments))
)

recorder = Recorder(state)
hooks = (
    {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "inherited-session",
        "turn_id": "inherited-turn",
    },
    {
        "hook_event_name": "PreToolUse",
        "session_id": "inherited-session",
        "turn_id": "inherited-turn",
        "tool_use_id": "inherited-tool",
        "tool_name": "Bash",
    },
    {
        "hook_event_name": "PostToolUse",
        "session_id": "inherited-session",
        "turn_id": "inherited-turn",
        "tool_use_id": "inherited-tool",
        "tool_name": "Bash",
    },
    {
        "hook_event_name": "Stop",
        "session_id": "inherited-session",
        "turn_id": "inherited-turn",
    },
)
managed_hook_results = []
try:
    if managed_hook_suppressed:
        for hook in hooks:
            result = subprocess.run(
                [
                    sys.executable,
                    os.environ["HOLYSKILLS_TEST_RECORDER_ENTRY"],
                    "hook",
                    "codex",
                    "--state-dir",
                    str(state),
                    "--managed-id",
                    "holyskills-delivery-efficiency-v1",
                ],
                input=json.dumps(hook).encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=dict(os.environ),
                check=False,
            )
            managed_hook_results.append(
                {
                    "returncode": result.returncode,
                    "stdout": result.stdout.decode("utf-8"),
                    "stderr": result.stderr.decode("utf-8"),
                }
            )
    else:
        for hook in hooks:
            record_emissions(recorder, translate_hook(hook, surface="cli-exec"))

    if not managed_otel_suppressed:
        otlp = {
            "resourceLogs": [{
                "resource": {"attributes": []},
                "scopeLogs": [{"logRecords": [{
                    "timeUnixNano": "1000",
                    "traceId": "1" * 32,
                    "spanId": "2" * 16,
                    "body": {"kvlistValue": {"values": [
                        {"key": "event.name", "value": {"stringValue": "codex.sse_event"}},
                        {"key": "event.kind", "value": {"stringValue": "response.completed"}},
                        {"key": "conversation.id", "value": {"stringValue": "inherited-session"}},
                        {"key": "turn.id", "value": {"stringValue": "inherited-turn"}},
                        {"key": "originator", "value": {"stringValue": "codex_exec"}},
                        {"key": "input_token_count", "value": {"intValue": "11"}},
                        {"key": "cached_input_token_count", "value": {"intValue": "3"}},
                        {"key": "output_token_count", "value": {"intValue": "5"}},
                        {"key": "reasoning_output_token_count", "value": {"intValue": "2"}},
                    ]}},
                }]}],
            }]}
        record_emissions(recorder, translate_otlp(otlp, surface="cli-exec"))
finally:
    recorder.close()

# Model Codex's additive hook loading: an unrelated user hook from the same
# home still runs unless the wrapper globally disabled hooks.
configured_hooks = json.loads((home / "hooks.json").read_text())
user_hook_configured = any(
    handler.get("command") == "user-hook"
    for groups in configured_hooks.get("hooks", {}).values()
    for group in groups
    for handler in group.get("hooks", [])
)
if user_hook_configured and not hooks_globally_disabled:
    Path(os.environ["HOLYSKILLS_TEST_USER_HOOK_MARKER"]).write_text("ran")

capture = {
    "arguments": arguments,
    "managed_hook_suppressed": managed_hook_suppressed,
    "managed_hook_results": managed_hook_results,
    "managed_otel_suppressed": managed_otel_suppressed,
    "unrelated_environment": os.environ.get("HOLYSKILLS_TEST_UNRELATED_ENV"),
    "user_hook_ran": Path(os.environ["HOLYSKILLS_TEST_USER_HOOK_MARKER"]).is_file(),
    "user_config_preserved": 'model = "user-model"' in (home / "config.toml").read_text(),
    "hooks_globally_disabled": hooks_globally_disabled,
}
Path(os.environ["HOLYSKILLS_TEST_CAPTURE"]).write_text(json.dumps(capture))

events = (
    {"type": "thread.started", "thread_id": "wrapped-session"},
    {"type": "turn.started", "turn_id": "wrapped-turn"},
    {"type": "item.started", "turn_id": "wrapped-turn", "item": {
        "id": "wrapped-tool", "type": "command_execution", "status": "in_progress"
    }},
    {"type": "item.completed", "turn_id": "wrapped-turn", "item": {
        "id": "wrapped-tool", "type": "command_execution", "status": "completed"
    }},
    {"type": "turn.completed", "turn_id": "wrapped-turn", "usage": {
        "input_tokens": 11,
        "cached_input_tokens": 3,
        "output_tokens": 5,
        "reasoning_output_tokens": 2,
    }},
)
for event in events:
    print(json.dumps(event, separators=(",", ":")), flush=True)
'''
    path.write_text(source, encoding="utf-8")


def _test_command() -> None:
    assert _command("codex", ["hello secret prompt"]) == [
        "codex",
        "exec",
        "--json",
        "hello secret prompt",
        "--config",
        'otel.exporter="none"',
    ]
    assert _command("C:\\Program Files\\Codex\\codex.exe", ["exec", "--json", "x"]) == [
        "C:\\Program Files\\Codex\\codex.exe",
        "exec",
        "--json",
        "x",
        "--config",
        'otel.exporter="none"',
    ]
    assert _command("codex", ["--", "x"]) == [
        "codex",
        "exec",
        "--json",
        "x",
        "--config",
        'otel.exporter="none"',
    ]
    earlier_override = _command(
        "codex",
        ["--config", 'otel.exporter={ otlp-http = { endpoint = "https://user.invalid" } }', "x"],
    )
    assert earlier_override[-2:] == ["--config", 'otel.exporter="none"']
    try:
        _command("", [])
    except ValueError:
        pass
    else:
        raise AssertionError("empty binary must fail")


def _test_child_environment_is_scoped_copy() -> None:
    sentinel = "HOLYSKILLS_EXEC_RUNNER_UNRELATED_SENTINEL"
    previous_sentinel = os.environ.get(sentinel)
    previous_marker = os.environ.get(WRAPPED_CODEX_EXEC_ENV)
    os.environ[sentinel] = "preserved"
    os.environ[WRAPPED_CODEX_EXEC_ENV] = "caller-value"
    try:
        child = _child_environment()
        assert child[sentinel] == "preserved"
        assert child[WRAPPED_CODEX_EXEC_ENV] == "1"
        assert os.environ[WRAPPED_CODEX_EXEC_ENV] == "caller-value"
    finally:
        if previous_sentinel is None:
            os.environ.pop(sentinel, None)
        else:
            os.environ[sentinel] = previous_sentinel
        if previous_marker is None:
            os.environ.pop(WRAPPED_CODEX_EXEC_ENV, None)
        else:
            os.environ[WRAPPED_CODEX_EXEC_ENV] = previous_marker


def _test_managed_sources_are_not_double_counted() -> None:
    with tempfile.TemporaryDirectory(prefix="delivery-efficiency-exec-") as raw:
        root = Path(raw).resolve()
        state = root / "state"
        home = root / "codex-home"
        home.mkdir()
        capture_path = root / "capture.json"
        user_hook_marker = root / "user-hook-ran"
        # `run_codex_exec` always inserts the `exec` subcommand. Pointing it at
        # Python with a cwd-local script named `exec` creates one real child
        # process without relying on POSIX executable bits or Windows .cmd
        # launching semantics.
        fake_codex = root / "exec"
        original_config = (
            'model = "user-model"\n\n'
            "# BEGIN HOLYSKILLS DELIVERY EFFICIENCY v1\n"
            "[otel]\n"
            'environment = "dev"\n'
            'log_user_prompt = false\n'
            'exporter = { otlp-http = { endpoint = "http://127.0.0.1:4319/v1/logs" } }\n'
            "# END HOLYSKILLS DELIVERY EFFICIENCY v1\n"
        )
        (home / "config.toml").write_text(original_config, encoding="utf-8")
        (home / "hooks.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        "UserPromptSubmit": [
                            {"hooks": [{"type": "command", "command": "user-hook"}]},
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": (
                                            "recorder hook --managed-id "
                                            "holyskills-delivery-efficiency-v1"
                                        ),
                                    }
                                ]
                            },
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        _write_fake_codex(fake_codex)

        updates = {
            "CODEX_HOME": str(home),
            "HOLYSKILLS_TEST_CAPTURE": str(capture_path),
            "HOLYSKILLS_TEST_PACKAGE_ROOT": str(HERE),
            "HOLYSKILLS_TEST_RECORDER_ENTRY": str(HERE / "recorder.py"),
            "HOLYSKILLS_TEST_STATE": str(state),
            "HOLYSKILLS_TEST_UNRELATED_ENV": "preserve-me",
            "HOLYSKILLS_TEST_USER_HOOK_MARKER": str(user_hook_marker),
        }
        original_marker = os.environ.get(WRAPPED_CODEX_EXEC_ENV)
        previous = {key: os.environ.get(key) for key in updates}
        previous_cwd = Path.cwd()
        os.environ.update(updates)
        try:
            os.chdir(root)
            result = run_codex_exec(
                state,
                codex_binary=sys.executable,
                arguments=["one wrapped run"],
            )
        finally:
            os.chdir(previous_cwd)
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        assert result == 0
        capture = json.loads(capture_path.read_text(encoding="utf-8"))
        assert capture["managed_hook_suppressed"] is True
        assert [item["returncode"] for item in capture["managed_hook_results"]] == [0, 0, 0, 0]
        assert [item["stdout"] for item in capture["managed_hook_results"]] == ["", "", "", "{}\n"]
        assert [item["stderr"] for item in capture["managed_hook_results"]] == ["", "", "", ""]
        assert capture["managed_otel_suppressed"] is True
        assert capture["hooks_globally_disabled"] is False
        assert capture["user_hook_ran"] is True
        assert user_hook_marker.read_text(encoding="utf-8") == "ran"
        assert capture["unrelated_environment"] == "preserve-me"
        assert capture["user_config_preserved"] is True
        assert (home / "config.toml").read_text(encoding="utf-8") == original_config
        assert os.environ.get(WRAPPED_CODEX_EXEC_ENV) == original_marker
        assert not (state / "last-runtime-gap.json").exists()

        ledger_path = state / "EfficiencyLedger.jsonl"
        assert WRAPPED_CODEX_EXEC_ENV.encode("ascii") not in ledger_path.read_bytes()
        events = read_ledger(ledger_path)
        assert [event["adapter"]["name"] for event in events if event["event"] == "task.start"] == [
            "codex-exec"
        ]
        assert [event["adapter"]["name"] for event in events if event["event"] == "span.start"] == [
            "codex-exec"
        ]
        assert [event["adapter"]["name"] for event in events if event["event"] == "span.end"] == [
            "codex-exec"
        ]
        usage = [event for event in events if event["event"] == "usage.observed"]
        assert len(usage) == 1
        assert usage[0]["adapter"]["name"] == "codex-exec"
        assert usage[0]["measurement"]["tokens"] == {
            "input": "11",
            "cached_input": "3",
            "output": "5",
            "reasoning_output": "2",
            "tool": None,
            "other": None,
        }
        task = summarize(events)["tasks"][0]
        assert task["tokens"]["input"] == "11"
        assert task["tokens"]["cached_input"] == "3"
        assert task["tokens"]["output"] == "5"
        assert task["tokens"]["reasoning_output"] == "2"


def main() -> int:
    _test_command()
    _test_child_environment_is_scoped_copy()
    _test_managed_sources_are_not_double_counted()
    print("exec runner self-test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
