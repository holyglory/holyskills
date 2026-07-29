"""Authenticated loopback receiver for normalized observations and Codex OTLP JSON."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from pathlib import Path
import socket
import threading
from typing import Any, Dict, List, Tuple

from . import RECORDER_VERSION
from .runtime import AUTH_HEADER, load_settings, token_digest


MAX_REQUEST_BYTES = 1024 * 1024
SETTINGS_MONITOR_INTERVAL_SECONDS = 0.2
SETTINGS_DRIFT_CONFIRMATIONS = 3


class ReceiverError(RuntimeError):
    pass


class Receiver(ThreadingHTTPServer):
    daemon_threads = True
    # POSIX needs SO_REUSEADDR for a prompt authenticated handoff after an
    # accepted health connection.  Windows' SO_REUSEADDR has different,
    # weaker exclusivity semantics, so keep its safer default.
    allow_reuse_address = os.name != "nt"

    def __init__(self, state_dir: Path, *, monitor_settings: bool = True):
        self.state_dir = state_dir
        self.settings = load_settings(state_dir)
        self.instance_version = RECORDER_VERSION
        if self.settings["recorder_version"] != self.instance_version:
            raise ReceiverError("settings-version-mismatch")
        from .storage import Recorder

        self.recorder = Recorder(state_dir)
        self._lifecycle_stop = threading.Event()
        self._retirement_requested = threading.Event()
        self._retirement_lock = threading.Lock()
        self._settings_monitor: Any = None
        address = (self.settings["listen_host"], self.settings["listen_port"])
        try:
            super().__init__(address, ReceiverHandler)
        except BaseException:
            close = getattr(self.recorder, "close", None)
            if close is not None:
                close()
            raise
        if monitor_settings:
            self._settings_monitor = threading.Thread(
                target=self._monitor_settings,
                name="delivery-efficiency-settings-monitor",
                daemon=True,
            )
            self._settings_monitor.start()

    def _matches_current_settings(self, current: Dict[str, Any]) -> bool:
        scalar_fields = ("recorder_version", "listen_host", "listen_port", "install_root", "python_executable")
        if any(current.get(field) != self.settings.get(field) for field in scalar_fields):
            return False
        return hmac.compare_digest(current.get("auth_token", ""), self.settings["auth_token"])

    def _monitor_settings(self) -> None:
        mismatches = 0
        while not self._lifecycle_stop.wait(SETTINGS_MONITOR_INTERVAL_SECONDS):
            try:
                current = load_settings(self.state_dir)
            except Exception:
                # A transient read failure is not evidence that this instance
                # lost ownership. Only repeated valid, conflicting settings
                # can retire it.
                mismatches = 0
                continue
            if self._matches_current_settings(current):
                mismatches = 0
                continue
            mismatches += 1
            if mismatches >= SETTINGS_DRIFT_CONFIRMATIONS:
                self.request_retirement("settings-drift")
                return

    def request_retirement(self, _reason: str) -> bool:
        """Idempotently stop only this authenticated recorder instance."""

        with self._retirement_lock:
            if self._retirement_requested.is_set():
                return False
            self._retirement_requested.set()
            thread = threading.Thread(
                target=self.shutdown,
                name="delivery-efficiency-retirement",
                daemon=True,
            )
            thread.start()
            return True

    def server_close(self) -> None:
        self._lifecycle_stop.set()
        monitor = self._settings_monitor
        if monitor is not None and monitor is not threading.current_thread():
            monitor.join(timeout=1.0)
        try:
            close = getattr(self.recorder, "close", None)
            if close is not None:
                close()
        finally:
            super().server_close()


class ReceiverHandler(BaseHTTPRequestHandler):
    server: Receiver
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *args: Any) -> None:
        return

    def _authorized(self) -> bool:
        supplied = self.headers.get(AUTH_HEADER, "")
        expected = self.server.settings["auth_token"]
        return hmac.compare_digest(supplied, expected)

    def _json_response(self, status: int, payload: Dict[str, Any]) -> None:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def _reject(self, status: int, code: str) -> None:
        self._json_response(status, {"ok": False, "error": code})

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            self._reject(404, "not-found")
            return
        if not self._authorized():
            self._reject(401, "unauthorized")
            return
        self._json_response(
            200,
            {
                "ok": True,
                "recorder_version": self.server.instance_version,
                "token_digest": token_digest(self.server.settings),
            },
        )

    def _read_json(self) -> Any:
        if self.headers.get("Transfer-Encoding"):
            raise ReceiverError("chunked-or-encoded-body")
        raw_length = self.headers.get("Content-Length")
        if raw_length is None or not raw_length.isdecimal():
            raise ReceiverError("missing-content-length")
        length = int(raw_length)
        if length < 0 or length > MAX_REQUEST_BYTES:
            raise ReceiverError("body-too-large")
        body = self.rfile.read(length)
        if len(body) != length:
            raise ReceiverError("truncated-body")
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ReceiverError("invalid-json") from error

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/v1/lifecycle/retire":
            self._retire()
            return
        if self.path not in {
            "/v1/observations",
            "/v1/declarations",
            "/v1/declaration-bindings",
            "/v1/logs",
        }:
            self._reject(404, "not-found")
            return
        if not self._authorized():
            self._reject(401, "unauthorized")
            return
        if self.headers.get_content_type() != "application/json":
            self._reject(415, "content-type")
            return
        try:
            payload = self._read_json()
            if self.path == "/v1/observations":
                results = self._record_normalized(payload)
            elif self.path == "/v1/declarations":
                results = self._record_declarations(payload)
            elif self.path == "/v1/declaration-bindings":
                binding = self._issue_declaration_binding(payload)
            else:
                results = self._record_otlp_logs(payload)
        except ReceiverError as error:
            self._reject(400, str(error))
            return
        except Exception:
            # Deliberately do not reflect raw errors or payload fragments.
            self._reject(503, "recorder-unavailable")
            return
        if self.path == "/v1/logs":
            # OTLP/HTTP JSON ExportLogsServiceResponse; an empty object is the
            # canonical all-accepted response.
            self._json_response(200, {})
        elif self.path == "/v1/declaration-bindings":
            self._json_response(200, {"ok": True, "binding": binding})
        else:
            response = {"ok": True, "recorded": len(results)}
            if self.path == "/v1/declarations" and results:
                response["task_binding"] = results[0].task_binding
            self._json_response(200, response)

    def _retire(self) -> None:
        if not self._authorized():
            self._reject(401, "unauthorized")
            return
        if self.headers.get_content_type() != "application/json":
            self._reject(415, "content-type")
            return
        try:
            payload = self._read_json()
        except ReceiverError as error:
            self._reject(400, str(error))
            return
        if payload != {}:
            self._reject(400, "invalid-retirement-request")
            return
        self._json_response(
            200,
            {
                "ok": True,
                "status": "retiring",
                "recorder_version": self.server.instance_version,
            },
        )
        self.wfile.flush()
        self.close_connection = True
        self.server.request_retirement("authenticated-request")

    def _record_normalized(self, payload: Any) -> List[Dict[str, Any]]:
        values = payload if isinstance(payload, list) else [payload]
        if len(values) > 128:
            raise ReceiverError("too-many-observations")
        results: List[Dict[str, Any]] = []
        for item in values:
            if not isinstance(item, dict) or set(item) != {"observation", "source_key"}:
                raise ReceiverError("invalid-observation-envelope")
            source_key = item["source_key"]
            if not isinstance(source_key, str) or not 1 <= len(source_key) <= 256:
                raise ReceiverError("invalid-source-key")
            observation = item["observation"]
            adapter = observation.get("adapter") if isinstance(observation, dict) else None
            if isinstance(adapter, dict) and adapter.get("name") == "agent-declaration":
                # Declarations must pass through the signed, task-resolved,
                # atomic batch endpoint.  Accepting them here would bypass
                # task-scoped deduplication and completion validation.
                raise ReceiverError("declaration-requires-batch-endpoint")
            results.append(self.server.recorder.record(observation, source_key=source_key))
        return results

    def _record_declarations(self, payload: Any) -> List[Dict[str, Any]]:
        if not isinstance(payload, dict):
            raise ReceiverError("invalid-declaration-batch")
        keys = set(payload)
        has_link = "linked_task_binding" in keys
        has_target = "target_task_binding" in keys
        base_keys = keys - {"linked_task_binding", "target_task_binding"}
        raw_mode = base_keys == {"source_session", "declarations"}
        binding_mode = base_keys == {"session_binding", "declarations"}
        if not (raw_mode or binding_mode):
            raise ReceiverError("invalid-declaration-batch")
        binding_key = "source_session" if raw_mode else "session_binding"
        supplied_binding = payload[binding_key]
        if not isinstance(supplied_binding, str):
            raise ReceiverError("invalid-declaration-session")
        encoded_binding = supplied_binding.encode("utf-8")
        maximum = 4096 if raw_mode else 160
        if not encoded_binding or len(encoded_binding) > maximum or "\x00" in supplied_binding:
            raise ReceiverError("invalid-declaration-session")
        linked_task_binding = payload.get("linked_task_binding")
        if has_link and (
            not isinstance(linked_task_binding, str)
            or not 1 <= len(linked_task_binding) <= 160
            or any(
                character not in "abcdefghijklmnopqrstuvwxyz0123456789_"
                for character in linked_task_binding
            )
        ):
            raise ReceiverError("invalid-linked-task-binding")
        target_task_binding = payload.get("target_task_binding")
        if has_target and (
            not isinstance(target_task_binding, str)
            or not 1 <= len(target_task_binding) <= 160
            or any(
                character not in "abcdefghijklmnopqrstuvwxyz0123456789_"
                for character in target_task_binding
            )
        ):
            raise ReceiverError("invalid-target-task-binding")
        values = payload["declarations"]
        if not isinstance(values, list) or not 1 <= len(values) <= 128:
            raise ReceiverError("invalid-declaration-count")

        from .contract import ContractValidationError, validate_normalized_observation, validate_source_key

        validated: List[Tuple[Dict[str, Any], str]] = []
        for item in values:
            if not isinstance(item, dict) or set(item) != {"observation", "source_key"}:
                raise ReceiverError("invalid-declaration-envelope")
            observation = item["observation"]
            source_key = item["source_key"]
            try:
                validate_normalized_observation(observation)
                validate_source_key(source_key)
            except ContractValidationError as error:
                raise ReceiverError("invalid-declaration-observation") from error
            if observation["adapter"]["name"] != "agent-declaration":
                raise ReceiverError("invalid-declaration-adapter")
            declared_session = observation["source_identity"]["session"]
            if not isinstance(declared_session, str) or not hmac.compare_digest(
                declared_session.encode("utf-8"), encoded_binding
            ):
                raise ReceiverError("declaration-session-mismatch")
            validated.append((observation, source_key))

        return self.server.recorder.record_declaration_batch(
            validated,
            source_session=supplied_binding if raw_mode else None,
            session_binding=supplied_binding if binding_mode else None,
            linked_task_binding=linked_task_binding,
            target_task_binding=target_task_binding,
        )

    def _issue_declaration_binding(self, payload: Any) -> str:
        if not isinstance(payload, dict) or set(payload) != {
            "runtime_family",
            "source_session",
        }:
            raise ReceiverError("invalid-declaration-binding-request")
        runtime_family = payload["runtime_family"]
        source_session = payload["source_session"]
        if runtime_family not in {"codex", "claude"} or not isinstance(
            source_session, str
        ):
            raise ReceiverError("invalid-declaration-binding-request")
        encoded_session = source_session.encode("utf-8")
        if not encoded_session or len(encoded_session) > 4096 or "\x00" in source_session:
            raise ReceiverError("invalid-declaration-binding-request")
        return self.server.recorder.declaration_binding(runtime_family, source_session)

    def _record_otlp_logs(self, payload: Any) -> List[Dict[str, Any]]:
        # One authenticated logs endpoint serves both runtimes.  Each
        # translator recognizes only its own record shapes and yields nothing
        # for the other's, so a mixed batch records exactly its own events.
        from .claude import translate_otlp as translate_claude_otlp
        from .codex import translate_otlp as translate_codex_otlp

        translated: List[Tuple[Dict[str, Any], str]] = list(translate_codex_otlp(payload))
        translated.extend(translate_claude_otlp(payload))
        return [
            self.server.recorder.record(observation, source_key=source_key)
            for observation, source_key in translated
        ]


def serve(state_dir: Path) -> int:
    try:
        receiver = Receiver(state_dir)
    except OSError as error:
        if error.errno in {
            getattr(socket, "EADDRINUSE", 48),
            48,
            98,
            10048,
        }:
            return 3
        raise
    try:
        receiver.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        receiver.server_close()
    return 0
