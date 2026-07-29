"""Private settings and loopback receiver lifecycle helpers."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from typing import Any, Dict, Iterable, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import CODEX_HOOK_TELEMETRY_BUDGET_SECONDS, RECORDER_VERSION


SETTINGS_NAME = "settings.json"
AUTH_HEADER = "x-holyskills-recorder-token"
MAX_OBSERVATION_BODY = 256 * 1024
GAP_CODES = {
    "hooks-untrusted",
    "hooks-disabled",
    "otel-conflict",
    "receiver-unavailable",
    "storage-unavailable",
    "malformed-source-event",
    "unsupported-runtime-event",
    "unknown",
}


class RuntimeConfigurationError(RuntimeError):
    """The installed runtime configuration is absent, unsafe, or invalid."""


def _private_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + secrets.token_hex(8))
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(str(temporary), flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temporary), str(path))
        if os.name != "nt":
            os.chmod(str(path), 0o600)
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def settings_path(state_dir: Path) -> Path:
    return state_dir / SETTINGS_NAME


def create_settings(
    state_dir: Path,
    *,
    listen_port: int,
    install_root: Path,
    python_executable: Path,
    platform_info: Dict[str, str],
    auth_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Create settings once; callers own port selection and path validation."""

    if not 1 <= int(listen_port) <= 65535:
        raise RuntimeConfigurationError("listen_port must be between 1 and 65535")
    token = auth_token or secrets.token_hex(32)
    if len(token) != 64 or any(character not in "0123456789abcdef" for character in token):
        raise RuntimeConfigurationError("auth_token must be 32 bytes encoded as lowercase hex")
    payload: Dict[str, Any] = {
        "schema_version": 1,
        "recorder_version": RECORDER_VERSION,
        "listen_host": "127.0.0.1",
        "listen_port": int(listen_port),
        "auth_token": token,
        "install_root": str(install_root.resolve()),
        "python_executable": str(python_executable.resolve()),
        "platform": {
            "os": platform_info["os"],
            "environment": platform_info["environment"],
        },
    }
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    destination = settings_path(state_dir)
    if destination.exists():
        raise RuntimeConfigurationError(f"settings already exist: {destination}")
    _private_write(destination, encoded)
    return payload


def load_settings(state_dir: Path) -> Dict[str, Any]:
    path = settings_path(state_dir)
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise RuntimeConfigurationError(f"cannot read recorder settings: {error}") from error
    if len(raw) > 64 * 1024:
        raise RuntimeConfigurationError("recorder settings exceed 64 KiB")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeConfigurationError("recorder settings are not valid UTF-8 JSON") from error
    required = {
        "schema_version",
        "recorder_version",
        "listen_host",
        "listen_port",
        "auth_token",
        "install_root",
        "python_executable",
        "platform",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise RuntimeConfigurationError("recorder settings have an unexpected shape")
    if value["schema_version"] != 1 or value["listen_host"] != "127.0.0.1":
        raise RuntimeConfigurationError("unsupported settings schema or non-loopback host")
    if not isinstance(value["listen_port"], int) or not 1 <= value["listen_port"] <= 65535:
        raise RuntimeConfigurationError("invalid receiver port")
    token = value["auth_token"]
    if not isinstance(token, str) or len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
        raise RuntimeConfigurationError("invalid receiver authentication token")
    platform_value = value["platform"]
    if (
        not isinstance(platform_value, dict)
        or set(platform_value) != {"os", "environment"}
        or platform_value["os"] not in {"windows", "linux", "macos"}
        or platform_value["environment"] not in {"native", "wsl"}
    ):
        raise RuntimeConfigurationError("invalid platform settings")
    for field in ("install_root", "python_executable"):
        if not isinstance(value[field], str) or not Path(value[field]).is_absolute():
            raise RuntimeConfigurationError(f"{field} must be absolute")
    return value


def token_digest(settings: Dict[str, Any]) -> str:
    return hashlib.sha256(settings["auth_token"].encode("ascii")).hexdigest()


def record_local_gap(state_dir: Path, code: str) -> None:
    """Persist one bounded health diagnostic without source payload or errors."""

    if code not in GAP_CODES:
        code = "unknown"
    from datetime import datetime, timezone

    payload = {
        "schema_version": 1,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "gap_code": code,
    }
    try:
        _private_write(
            state_dir / "last-runtime-gap.json",
            (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8"),
        )
    except OSError:
        pass


def receiver_url(settings: Dict[str, Any], path: str) -> str:
    return "http://{}:{}{}".format(settings["listen_host"], settings["listen_port"], path)


def _validated_timeout(timeout_seconds: float) -> float:
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(float(timeout_seconds))
        or float(timeout_seconds) <= 0
    ):
        raise RuntimeConfigurationError("runtime timeout must be a positive finite number")
    return float(timeout_seconds)


def _request(
    settings: Dict[str, Any],
    path: str,
    *,
    body: Optional[bytes] = None,
    timeout_seconds: float = 1.0,
) -> bytes:
    timeout = _validated_timeout(timeout_seconds)
    headers = {AUTH_HEADER: settings["auth_token"]}
    method = "GET"
    if body is not None:
        method = "POST"
        headers["Content-Type"] = "application/json"
    request = Request(receiver_url(settings, path), data=body, headers=headers, method=method)
    with urlopen(request, timeout=timeout) as response:
        return response.read(64 * 1024)


def receiver_is_healthy(
    settings: Dict[str, Any], *, timeout_seconds: float = 1.0
) -> bool:
    response = receiver_health(settings, timeout_seconds=timeout_seconds)
    return response == {
        "ok": True,
        "recorder_version": settings["recorder_version"],
        "token_digest": token_digest(settings),
    }


def receiver_health(
    settings: Dict[str, Any], *, timeout_seconds: float = 1.0
) -> Optional[Dict[str, Any]]:
    """Return only an authenticated, bounded recorder health identity."""

    try:
        response = json.loads(
            _request(
                settings,
                "/health",
                timeout_seconds=timeout_seconds,
            ).decode("utf-8")
        )
    except (OSError, ValueError, HTTPError, URLError):
        return None
    if (
        not isinstance(response, dict)
        or set(response) != {"ok", "recorder_version", "token_digest"}
        or response.get("ok") is not True
        or not isinstance(response.get("recorder_version"), str)
        or len(response["recorder_version"]) > 64
        or response.get("token_digest") != token_digest(settings)
    ):
        return None
    return response


def request_receiver_retirement(
    settings: Dict[str, Any], *, timeout_seconds: float = 1.0
) -> bool:
    """Ask only the token-authenticated recorder on the configured port to stop."""

    try:
        response = json.loads(
            _request(
                settings,
                "/v1/lifecycle/retire",
                body=b"{}",
                timeout_seconds=timeout_seconds,
            ).decode("utf-8")
        )
    except (OSError, ValueError, HTTPError, URLError):
        return False
    return bool(
        isinstance(response, dict)
        and set(response) == {"ok", "status", "recorder_version"}
        and response.get("ok") is True
        and response.get("status") == "retiring"
        and isinstance(response.get("recorder_version"), str)
        and len(response["recorder_version"]) <= 64
    )


def _receiver_port_is_open(
    settings: Dict[str, Any], *, timeout_seconds: float = 0.15
) -> bool:
    timeout = _validated_timeout(timeout_seconds)
    try:
        with socket.create_connection(
            (settings["listen_host"], settings["listen_port"]),
            timeout=timeout,
        ):
            return True
    except OSError:
        return False


def _remaining_timeout(deadline: float, cap_seconds: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RuntimeConfigurationError("runtime operation exceeded its deadline")
    return min(_validated_timeout(cap_seconds), remaining)


def ensure_receiver(
    state_dir: Path,
    *,
    timeout_seconds: float = CODEX_HOOK_TELEMETRY_BUDGET_SECONDS,
) -> Dict[str, Any]:
    timeout = _validated_timeout(timeout_seconds)
    deadline = time.monotonic() + timeout
    settings = load_settings(state_dir)
    health = receiver_health(
        settings,
        timeout_seconds=_remaining_timeout(deadline, 0.25),
    )
    if health == {
        "ok": True,
        "recorder_version": settings["recorder_version"],
        "token_digest": token_digest(settings),
    }:
        return settings

    if health is not None:
        request_receiver_retirement(
            settings,
            timeout_seconds=_remaining_timeout(deadline, 0.25),
        )

    # A newer recorder self-retires after settings drift, including auth-token
    # rotation where the replacement cannot authenticate to the old instance.
    # Wait a bounded interval for that graceful path. Never signal a PID or
    # terminate an arbitrary process that happens to own the port.
    retirement_deadline = min(deadline, time.monotonic() + min(1.1, timeout * 0.5))
    port_is_open = _receiver_port_is_open(
        settings,
        timeout_seconds=_remaining_timeout(retirement_deadline, 0.1),
    )
    while port_is_open and time.monotonic() < retirement_deadline:
        remaining = retirement_deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(0.05, remaining))
        port_is_open = _receiver_port_is_open(
            settings,
            timeout_seconds=_remaining_timeout(retirement_deadline, 0.1),
        )
    if port_is_open:
        raise RuntimeConfigurationError(
            "configured receiver port is occupied and no authenticated recorder completed retirement"
        )

    entry = Path(settings["install_root"]) / "recorder.py"
    python = Path(settings["python_executable"])
    if not entry.is_file() or not python.is_file():
        raise RuntimeConfigurationError("installed recorder entry point or Python executable is missing")
    command = [str(python), str(entry), "serve", "--state-dir", str(state_dir)]
    kwargs: Dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        )
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(command, **kwargs)

    while time.monotonic() < deadline:
        if receiver_is_healthy(
            settings,
            timeout_seconds=_remaining_timeout(deadline, 0.2),
        ):
            return settings
        if process.poll() is not None:
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(0.05, remaining))
    # Do not spend the host's safety margin attempting retirement. A spawned
    # recorder still validates the private settings before serving and may be
    # ready for the next hook; this hook reports the bounded coverage gap.
    raise RuntimeConfigurationError("loopback receiver did not become healthy before the hook deadline")


def post_observations(state_dir: Path, observations: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    settings = ensure_receiver(state_dir)
    return post_observations_to_receiver(settings, observations)


def post_observations_to_receiver(
    settings: Dict[str, Any],
    observations: Iterable[Dict[str, Any]],
    *,
    timeout_seconds: float = 1.0,
) -> Dict[str, Any]:
    """Post through an already authenticated healthy receiver within one budget."""

    timeout = _validated_timeout(timeout_seconds)
    deadline = time.monotonic() + timeout
    payload = json.dumps(list(observations), separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    if len(payload) > MAX_OBSERVATION_BODY:
        raise RuntimeConfigurationError("normalized observations exceed the receiver request limit")
    response = _request(
        settings,
        "/v1/observations",
        body=payload,
        timeout_seconds=_remaining_timeout(deadline, timeout),
    )
    value = json.loads(response.decode("utf-8"))
    if not isinstance(value, dict) or value.get("ok") is not True:
        raise RuntimeConfigurationError("receiver rejected normalized observations")
    return value


def request_declaration_binding(
    settings: Dict[str, Any],
    *,
    runtime_family: str,
    source_session: str,
    timeout_seconds: float = 1.0,
) -> str:
    """Exchange one raw runtime session for a signed opaque core handle.

    The raw identifier exists only in this authenticated loopback request.  It
    is neither returned by the receiver nor suitable for runtime-owned model
    context; callers inject only the returned opaque binding.
    """

    if runtime_family not in {"codex", "claude"}:
        raise RuntimeConfigurationError("declaration runtime family is unsupported")
    _validate_source_session(source_session)
    timeout = _validated_timeout(timeout_seconds)
    deadline = time.monotonic() + timeout
    payload = json.dumps(
        {"runtime_family": runtime_family, "source_session": source_session},
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    response = _request(
        settings,
        "/v1/declaration-bindings",
        body=payload,
        timeout_seconds=_remaining_timeout(deadline, timeout),
    )
    try:
        value = json.loads(response.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeConfigurationError("receiver returned an invalid declaration binding") from error
    binding = value.get("binding") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or set(value) != {"ok", "binding"}
        or value.get("ok") is not True
        or not isinstance(binding, str)
        or not 1 <= len(binding) <= 160
        or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in binding)
    ):
        raise RuntimeConfigurationError("receiver returned an invalid declaration binding")
    return binding


def post_declarations(
    state_dir: Path,
    declarations: Iterable[Dict[str, Any]],
    *,
    source_session: Optional[str] = None,
    session_binding: Optional[str] = None,
    linked_task_binding: Optional[str] = None,
    target_task_binding: Optional[str] = None,
) -> Dict[str, Any]:
    """Bind agent declarations inside the receiver's authoritative clock domain."""

    if (source_session is None) == (session_binding is None):
        raise RuntimeConfigurationError(
            "declarations require exactly one raw session or opaque binding"
        )
    if source_session is not None:
        _validate_source_session(source_session)
        binding_key = "source_session"
        binding_value = source_session
    else:
        if (
            not isinstance(session_binding, str)
            or not 1 <= len(session_binding) <= 160
            or any(
                character not in "abcdefghijklmnopqrstuvwxyz0123456789_"
                for character in session_binding
            )
        ):
            raise RuntimeConfigurationError("declaration binding is invalid")
        binding_key = "session_binding"
        binding_value = session_binding
    values = list(declarations)
    if not 1 <= len(values) <= 128:
        raise RuntimeConfigurationError("declaration batch must contain between 1 and 128 events")
    body = {binding_key: binding_value, "declarations": values}
    if linked_task_binding is not None:
        if (
            not isinstance(linked_task_binding, str)
            or not 1 <= len(linked_task_binding) <= 160
            or any(
                character not in "abcdefghijklmnopqrstuvwxyz0123456789_"
                for character in linked_task_binding
            )
        ):
            raise RuntimeConfigurationError("linked task binding is invalid")
        body["linked_task_binding"] = linked_task_binding
    if target_task_binding is not None:
        if (
            not isinstance(target_task_binding, str)
            or not 1 <= len(target_task_binding) <= 160
            or any(
                character not in "abcdefghijklmnopqrstuvwxyz0123456789_"
                for character in target_task_binding
            )
        ):
            raise RuntimeConfigurationError("target task binding is invalid")
        body["target_task_binding"] = target_task_binding
    payload = json.dumps(
        body,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    if len(payload) > MAX_OBSERVATION_BODY:
        raise RuntimeConfigurationError("normalized declarations exceed the receiver request limit")
    settings = ensure_receiver(state_dir)
    response = _request(settings, "/v1/declarations", body=payload)
    value = json.loads(response.decode("utf-8"))
    if (
        not isinstance(value, dict)
        or set(value) != {"ok", "recorded", "task_binding"}
        or value.get("ok") is not True
        or value.get("recorded") != len(values)
        or not isinstance(value.get("task_binding"), str)
        or not 1 <= len(value["task_binding"]) <= 160
        or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789_"
            for character in value["task_binding"]
        )
    ):
        raise RuntimeConfigurationError("receiver rejected normalized declarations")
    return value


def _validate_source_session(source_session: str) -> None:
    if not isinstance(source_session, str):
        raise RuntimeConfigurationError("declaration session must be a bounded string")
    encoded_session = source_session.encode("utf-8")
    if not encoded_session or len(encoded_session) > 4096 or "\x00" in source_session:
        raise RuntimeConfigurationError("declaration session must be a bounded string")
