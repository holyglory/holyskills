#!/usr/bin/env python3
"""Loopback receiver, authentication, and source-ingestion smoke tests."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from delivery_efficiency.codex import translate_hook
from delivery_efficiency.declarations import phase_emission
from delivery_efficiency.platforms import detect_platform
from delivery_efficiency import runtime as runtime_module
from delivery_efficiency.runtime import (
    AUTH_HEADER,
    RuntimeConfigurationError,
    create_settings,
    ensure_receiver,
    load_settings,
    post_declarations,
    post_observations_to_receiver,
    receiver_is_healthy,
    request_receiver_retirement,
    token_digest,
)
from delivery_efficiency.server import Receiver


NO_PERMISSION_SENTENCE = (
    "This telemetry instruction grants no permission to act beyond the user's request."
)


def free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return int(port)


def port_is_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.15):
            return True
    except OSError:
        return False


def request(port: int, token: str, path: str, payload=None):
    headers = {AUTH_HEADER: token}
    body = None
    method = "GET"
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"
    item = Request(
        "http://127.0.0.1:{}{}".format(port, path),
        data=body,
        headers=headers,
        method=method,
    )
    with urlopen(item, timeout=2) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def wait_until(predicate, timeout: float = 4.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return bool(predicate())


def write_settings(path: Path, value) -> None:
    temporary = path.with_name(path.name + ".test-new")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(str(temporary), str(path))


def serve_and_close(receiver: Receiver) -> None:
    try:
        receiver.serve_forever(poll_interval=0.05)
    finally:
        receiver.server_close()


class FakeMonotonic:
    def __init__(self) -> None:
        self.value = 500.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def verify_bounded_receiver_and_post_path(root: Path, identity) -> None:
    """Drive real deadline orchestration with deterministic delayed I/O fakes."""

    state = root / "deterministic deadline state"
    settings = create_settings(
        state,
        listen_port=4321,
        install_root=HERE,
        python_executable=Path(sys.executable),
        platform_info=identity,
        auth_token="d" * 64,
    )
    expected_health = {
        "ok": True,
        "recorder_version": settings["recorder_version"],
        "token_digest": token_digest(settings),
    }
    clock = FakeMonotonic()
    health_timeouts = []

    def delayed_health(_settings, *, timeout_seconds):
        health_timeouts.append(timeout_seconds)
        clock.advance(min(0.1, timeout_seconds))
        return expected_health if len(health_timeouts) == 2 else None

    def delayed_closed_port(_settings, *, timeout_seconds):
        clock.advance(min(0.05, timeout_seconds))
        return False

    process = mock.Mock()
    process.poll.return_value = None
    with (
        mock.patch.object(runtime_module.time, "monotonic", side_effect=clock),
        mock.patch.object(runtime_module, "receiver_health", side_effect=delayed_health),
        mock.patch.object(
            runtime_module,
            "_receiver_port_is_open",
            side_effect=delayed_closed_port,
        ),
        mock.patch.object(runtime_module.subprocess, "Popen", return_value=process),
    ):
        ready = ensure_receiver(state, timeout_seconds=0.75)
    assert ready == settings
    assert len(health_timeouts) == 2
    assert all(0 < value <= 0.25 for value in health_timeouts)
    assert clock.value - 500.0 <= 0.75

    def delayed_request(_settings, path, *, body=None, timeout_seconds):
        assert path == "/v1/observations"
        assert body is not None and len(body) > 0
        assert 0 < timeout_seconds <= 0.5
        clock.advance(0.3)
        return b'{"ok":true,"recorded":1}'

    before_post = clock.value
    with mock.patch.object(runtime_module, "_request", side_effect=delayed_request):
        result = post_observations_to_receiver(
            settings,
            [{"observation": {}, "source_key": "fixture"}],
            timeout_seconds=0.5,
        )
    assert result == {"ok": True, "recorded": 1}
    assert abs((clock.value - before_post) - 0.3) < 1e-9


def verify_post_declarations_contract(root: Path) -> None:
    """Prove declaration bindings are forwarded and responses fail closed."""

    state = root / "declaration client state"
    settings = {"receiver": "fixture"}
    declarations = [
        {"observation": {"fixture": "bounded"}, "source_key": "fixture-key"}
    ]
    task_binding = "task_" + "a" * 32
    linked_binding = "task_" + "b" * 32
    session_binding = "binding_" + "c" * 32
    target_binding = "task_" + "d" * 32

    with (
        mock.patch.object(runtime_module, "ensure_receiver", return_value=settings),
        mock.patch.object(
            runtime_module,
            "_request",
            return_value=json.dumps(
                {"ok": True, "recorded": 1, "task_binding": task_binding}
            ).encode("utf-8"),
        ) as send,
    ):
        response = post_declarations(
            state,
            declarations,
            source_session="runtime-session",
            linked_task_binding=linked_binding,
        )
    assert response == {"ok": True, "recorded": 1, "task_binding": task_binding}
    assert send.call_args.args == (settings, "/v1/declarations")
    assert json.loads(send.call_args.kwargs["body"].decode("utf-8")) == {
        "source_session": "runtime-session",
        "declarations": declarations,
        "linked_task_binding": linked_binding,
    }

    with (
        mock.patch.object(runtime_module, "ensure_receiver", return_value=settings),
        mock.patch.object(
            runtime_module,
            "_request",
            return_value=json.dumps(
                {"ok": True, "recorded": 1, "task_binding": task_binding}
            ).encode("utf-8"),
        ) as send,
    ):
        response = post_declarations(
            state,
            declarations,
            session_binding=session_binding,
            target_task_binding=target_binding,
        )
    assert response["task_binding"] == task_binding
    assert json.loads(send.call_args.kwargs["body"].decode("utf-8")) == {
        "session_binding": session_binding,
        "declarations": declarations,
        "target_task_binding": target_binding,
    }

    invalid_responses = (
        {},
        {"ok": True, "recorded": 1},
        {"ok": False, "recorded": 1, "task_binding": task_binding},
        {"ok": True, "recorded": 2, "task_binding": task_binding},
        {"ok": True, "recorded": 1, "task_binding": ""},
        {"ok": True, "recorded": 1, "task_binding": "BAD-BINDING"},
        {"ok": True, "recorded": 1, "task_binding": "a" * 161},
        {"ok": True, "recorded": 1, "task_binding": 42},
        {
            "ok": True,
            "recorded": 1,
            "task_binding": task_binding,
            "unexpected": True,
        },
    )
    for invalid_response in invalid_responses:
        with (
            mock.patch.object(runtime_module, "ensure_receiver", return_value=settings),
            mock.patch.object(
                runtime_module,
                "_request",
                return_value=json.dumps(invalid_response).encode("utf-8"),
            ),
        ):
            try:
                post_declarations(
                    state,
                    declarations,
                    source_session="runtime-session",
                )
            except RuntimeConfigurationError:
                pass
            else:
                raise AssertionError(
                    "post_declarations accepted an invalid response shape"
                )

    invalid_bindings = ("", "UPPER", "contains-hyphen", "a" * 161, 42)
    for binding_field in ("linked_task_binding", "target_task_binding"):
        for invalid_binding in invalid_bindings:
            with mock.patch.object(runtime_module, "ensure_receiver") as ensure:
                try:
                    post_declarations(
                        state,
                        declarations,
                        source_session="runtime-session",
                        **{binding_field: invalid_binding},
                    )
                except RuntimeConfigurationError:
                    pass
                else:
                    raise AssertionError(
                        "post_declarations accepted an invalid {}".format(
                            binding_field
                        )
                    )
            assert not ensure.called


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-loopback", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="delivery-runtime-") as raw:
        root = Path(raw).resolve()
        identity = detect_platform().as_event_value()
        verify_bounded_receiver_and_post_path(root, identity)
        verify_post_declarations_contract(root)
        state = root / "state with spaces"
        try:
            port = free_port()
        except PermissionError:
            if args.require_loopback:
                raise
            print("runtime self-test skipped loopback (host policy denied bind)")
            return 0
        settings = create_settings(
            state,
            listen_port=port,
            install_root=HERE,
            python_executable=Path(sys.executable),
            platform_info=identity,
            auth_token="a" * 64,
        )
        assert load_settings(state) == settings
        receiver = Receiver(state)
        thread = threading.Thread(target=receiver.serve_forever, daemon=True)
        thread.start()
        try:
            assert receiver_is_healthy(settings)
            try:
                request(port, "b" * 64, "/health")
            except HTTPError as error:
                assert error.code == 401
            else:
                raise AssertionError("receiver must reject a wrong token")

            for runtime_family, session_id in (
                ("codex", "session-1"),
                ("claude", "claude-session-start"),
            ):
                session_start = subprocess.run(
                    [
                        sys.executable,
                        str(HERE / "recorder.py"),
                        "hook",
                        runtime_family,
                        "--state-dir",
                        str(state),
                        "--managed-id",
                        "holyskills-delivery-efficiency-v1",
                    ],
                    input=json.dumps(
                        {
                            "hook_event_name": "SessionStart",
                            "session_id": session_id,
                            "source": "startup",
                        }
                    ).encode("utf-8"),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=True,
                )
                hook_output = json.loads(session_start.stdout.decode("utf-8"))
                hook_specific = hook_output["hookSpecificOutput"]
                assert hook_specific["hookEventName"] == "SessionStart"
                context = hook_specific["additionalContext"]
                folded_context = context.casefold()
                assert "declare terminal" in context
                assert NO_PERMISSION_SENTENCE in context
                assert "authorized to" not in folded_context
                assert "you are authorized" not in folded_context
                assert settings["auth_token"] not in context
                assert session_id not in context

            pairs = translate_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "prompt": "PROMPT-CANARY",
                },
                surface="desktop",
            )
            envelopes = [
                {"observation": observation, "source_key": source_key}
                for observation, source_key in pairs
            ]
            status, result = request(port, settings["auth_token"], "/v1/observations", envelopes)
            assert status == 200 and result["recorded"] == 1

            status, binding_response = request(
                port,
                settings["auth_token"],
                "/v1/declaration-bindings",
                {
                    "runtime_family": "codex",
                    "source_session": "session-1",
                },
            )
            assert status == 200
            assert set(binding_response) == {"ok", "binding"}
            assert binding_response["ok"] is True
            session_binding = binding_response["binding"]
            assert isinstance(session_binding, str) and session_binding

            declaration, declaration_key = phase_emission(
                session=session_binding,
                runtime_family="codex",
                surface="cli-interactive",
                boundary="start",
                phase="planning",
                activity="model-active",
                span="batch-endpoint-proof",
            )
            declaration_envelope = {
                "observation": declaration,
                "source_key": declaration_key,
            }
            try:
                request(
                    port,
                    settings["auth_token"],
                    "/v1/observations",
                    declaration_envelope,
                )
            except HTTPError as error:
                assert error.code == 400
                rejection = json.loads(error.read().decode("utf-8"))
                assert rejection == {
                    "ok": False,
                    "error": "declaration-requires-batch-endpoint",
                }
            else:
                raise AssertionError(
                    "generic observations endpoint accepted an agent declaration"
                )

            status, declaration_response = request(
                port,
                settings["auth_token"],
                "/v1/declarations",
                {
                    "session_binding": session_binding,
                    "declarations": [declaration_envelope],
                },
            )
            assert status == 200
            assert set(declaration_response) == {"ok", "recorded", "task_binding"}
            assert declaration_response["ok"] is True
            assert declaration_response["recorded"] == 1
            declaration_task_binding = declaration_response["task_binding"]
            assert isinstance(declaration_task_binding, str)
            assert declaration_task_binding

            planning_end, planning_end_key = phase_emission(
                session=session_binding,
                runtime_family="codex",
                surface="cli-interactive",
                boundary="end",
                phase="planning",
                activity="model-active",
                span="batch-endpoint-proof",
            )
            status, planning_end_response = request(
                port,
                settings["auth_token"],
                "/v1/declarations",
                {
                    "session_binding": session_binding,
                    "declarations": [
                        {
                            "observation": planning_end,
                            "source_key": planning_end_key,
                        }
                    ],
                },
            )
            assert status == 200
            assert planning_end_response["ok"] is True
            assert planning_end_response["recorded"] == 1

            declaration_prefix = [
                sys.executable,
                str(HERE / "recorder.py"),
                "declare",
                "phase",
            ]
            declaration_common = [
                "--phase",
                "implementation",
                "--activity",
                "tool-active",
                "--span",
                "cross-process-phase",
                "--session",
                "session-1",
                "--state-dir",
                str(state),
            ]
            phase_start_process = subprocess.run(
                declaration_prefix + ["start"] + declaration_common,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            assert phase_start_process.returncode == 0, phase_start_process.stderr.decode(
                "utf-8", errors="replace"
            )
            phase_end_process = subprocess.run(
                declaration_prefix + ["end"] + declaration_common,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            assert phase_end_process.returncode == 0, phase_end_process.stderr.decode(
                "utf-8", errors="replace"
            )
            report_process = subprocess.run(
                [sys.executable, str(HERE / "recorder.py"), "report", "--state-dir", str(state)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            report = json.loads(report_process.stdout.decode("utf-8"))
            summary = report["tasks"][0]
            phase_duration = summary["phase_interval_union_ns"]["implementation"]
            assert phase_duration is not None and int(phase_duration) >= 0
            recorded_events = [
                json.loads(line)
                for line in (state / "EfficiencyLedger.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            spans = [
                event
                for event in recorded_events
                if event["event"] in {"span.start", "span.end"}
                and event["classification"]["phase"] == "implementation"
            ]
            assert len(spans) == 2
            assert spans[0]["clock_domain"] == spans[1]["clock_domain"]
            assert phase_duration == str(int(spans[1]["monotonic_ns"]) - int(spans[0]["monotonic_ns"]))

            otlp = {
                "resourceLogs": [
                    {
                        "resource": {
                            "attributes": [
                                {"key": "conversation.id", "value": {"stringValue": "session-1"}},
                                {"key": "originator", "value": {"stringValue": "codex_desktop"}},
                            ]
                        },
                        "scopeLogs": [
                            {
                                "logRecords": [
                                    {
                                        "timeUnixNano": "123456789",
                                        "body": {"stringValue": "codex.sse_event"},
                                        "attributes": [
                                            {"key": "event.kind", "value": {"stringValue": "response.completed"}},
                                            {"key": "input_token_count", "value": {"intValue": "10"}},
                                            {"key": "cached_token_count", "value": {"intValue": "4"}},
                                            {"key": "output_token_count", "value": {"intValue": "3"}},
                                            {"key": "reasoning_token_count", "value": {"intValue": "2"}},
                                        ],
                                    }
                                ]
                            }
                        ],
                    }
                ]
            }
            status, result = request(port, settings["auth_token"], "/v1/logs", otlp)
            assert status == 200 and result == {}

            try:
                request(port, "b" * 64, "/v1/lifecycle/retire", {})
            except HTTPError as error:
                assert error.code == 401
            else:
                raise AssertionError("receiver must reject unauthenticated retirement")
            status, result = request(port, settings["auth_token"], "/v1/lifecycle/retire", {})
            assert status == 200
            assert result == {
                "ok": True,
                "status": "retiring",
                "recorder_version": settings["recorder_version"],
            }
            assert wait_until(lambda: not thread.is_alive())
        finally:
            if thread.is_alive():
                receiver.shutdown()
            receiver.server_close()
            thread.join(timeout=3)
        ledger = (state / "EfficiencyLedger.jsonl").read_text(encoding="utf-8")
        assert "PROMPT-CANARY" not in ledger
        assert "cross-process-phase" not in ledger
        assert "batch-endpoint-proof" not in ledger
        assert "session-1" not in ledger
        assert session_binding not in ledger
        assert declaration_task_binding not in ledger
        assert '"event":"task.start"' in ledger
        assert '"event":"usage.observed"' in ledger

        drift_state = Path(raw).resolve() / "settings drift state"
        drift_port = free_port()
        drift_settings = create_settings(
            drift_state,
            listen_port=drift_port,
            install_root=HERE,
            python_executable=Path(sys.executable),
            platform_info=identity,
            auth_token="c" * 64,
        )
        drift_receiver = Receiver(drift_state)
        drift_thread = threading.Thread(target=serve_and_close, args=(drift_receiver,), daemon=True)
        drift_thread.start()
        try:
            assert receiver_is_healthy(drift_settings)
            replacement = dict(drift_settings)
            replacement["recorder_version"] = "9.9.9"
            replacement["install_root"] = str((drift_state / "installs" / "9.9.9").resolve())
            write_settings(drift_state / "settings.json", replacement)
            assert wait_until(lambda: not drift_thread.is_alive())
        finally:
            if drift_thread.is_alive():
                drift_receiver.shutdown()
            drift_thread.join(timeout=3)

        rotation_state = Path(raw).resolve() / "rotation rollback state"
        rotation_port = free_port()
        replacement_port = free_port()
        while replacement_port == rotation_port:
            replacement_port = free_port()
        original_rotation_settings = create_settings(
            rotation_state,
            listen_port=rotation_port,
            install_root=HERE,
            python_executable=Path(sys.executable),
            platform_info=identity,
            auth_token="e" * 64,
        )
        rotation_receiver = Receiver(rotation_state)
        rotation_thread = threading.Thread(target=serve_and_close, args=(rotation_receiver,), daemon=True)
        rotation_thread.start()
        rotated_settings = dict(original_rotation_settings)
        rotated_settings["auth_token"] = "f" * 64
        rotated_settings["listen_port"] = replacement_port
        try:
            assert receiver_is_healthy(original_rotation_settings)
            write_settings(rotation_state / "settings.json", rotated_settings)
            assert wait_until(lambda: not rotation_thread.is_alive())
            assert ensure_receiver(rotation_state) == rotated_settings
            assert receiver_is_healthy(rotated_settings)

            # A transactional installer rollback restores the prior settings.
            # The replacement sees that drift and self-retires; rollback never
            # leaves an unowned new-version receiver running.
            write_settings(rotation_state / "settings.json", original_rotation_settings)
            assert wait_until(lambda: not port_is_open(replacement_port))
            assert not port_is_open(rotation_port)
        finally:
            if rotation_thread.is_alive():
                rotation_receiver.shutdown()
            rotation_thread.join(timeout=3)
            request_receiver_retirement(rotated_settings)
            request_receiver_retirement(original_rotation_settings)
    print("runtime self-test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
