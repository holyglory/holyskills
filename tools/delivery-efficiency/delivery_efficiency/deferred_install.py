"""One-shot, digest-bound deferred recorder installation.

An agent arms this worker before the affected applications exit.  The worker
waits only for the exact process incarnations reviewed by the caller, then
delegates every installation mutation to the existing transactional installer.
Installation evidence is private state, never recorder telemetry.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import threading
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .process_identity import (
    ProcessIdentity,
    ProcessIdentityError,
    ProcessInspector,
)


DEFERRED_SCHEMA_VERSION = 1
DEFERRED_REQUEST_SCHEMA_VERSION = 2
_HISTORICAL_DEFERRED_OBSERVATION_VERSIONS = frozenset({"0.2.4", "0.2.5", "0.2.6"})
DEFAULT_WAIT_SECONDS = 86_400
MAX_WAIT_SECONDS = 604_800
MAX_REQUEST_BYTES = 512 * 1024
MAX_RECEIPT_BYTES = 16 * 1024
MAX_TRANSACTION_BYTES = 4 * 1024 * 1024
READY_WAIT_SECONDS = 10.0
QUIESCENCE_SECONDS = 0.5
WAIT_POLL_SECONDS = 1.0
QUIESCENCE_POLL_SECONDS = 0.1
STATE_HEARTBEAT_SECONDS = 300.0
MANAGED_DAEMON_CONTROL_TIMEOUT_SECONDS = 15.0
MANAGED_DAEMON_EXIT_TIMEOUT_SECONDS = 15.0
_JOB_ID_LENGTH = 32
_RECEIPT_BASENAME = "deferred-install-result.json"
_TERMINAL_STATUSES = {
    "verified",
    "cancelled",
    "expired",
    "target-race",
    "failed-unapplied",
    "failed-rolled-back",
    "rollback-blocked",
}
_RECEIPT_FIELDS = {
    "schema_version",
    "job_id",
    "plan_sha256",
    "status",
    "phase",
    "target_count",
    "apply_status",
    "verification_ok",
    "receiver_healthy",
    "rollback_status",
    "failure_code",
    "started_at_utc",
    "finished_at_utc",
}
_RECEIPT_PHASES = {
    "preparing",
    "waiting",
    "stopping-managed-daemons",
    "quiescing",
    "applying",
    "verifying",
    "complete",
}
_APPLY_STATUSES = {
    "not-started",
    "planned",
    "applying",
    "applied",
    "apply-failed-rolling-back",
    "apply-failed-rolled-back",
    "apply-failed-rollback-blocked",
    "rolling-back",
    "rolled-back",
    "rollback-blocked",
    "unknown",
}
_ROLLBACK_STATUSES = {"not-applicable", "rolled-back", "blocked"}
_FAILURE_CODES = {
    "none",
    "worker-not-ready",
    "cancelled",
    "wait-timeout",
    "process-inspection-failed",
    "target-relaunched",
    "managed-daemon-stop-failed",
    "managed-daemon-exit-timeout",
    "legacy-daemon-transition-failed",
    "installer-failure",
    "worker-lost",
}
_NO_MUTATION_RECEIPT_CATEGORIES = {
    "cancelled": {("waiting", "cancelled"), ("quiescing", "cancelled")},
    "expired": {("waiting", "wait-timeout"), ("quiescing", "wait-timeout")},
    "target-race": {("quiescing", "target-relaunched")},
    "failed-unapplied": {
        ("preparing", "worker-not-ready"),
        ("waiting", "process-inspection-failed"),
        ("quiescing", "process-inspection-failed"),
    },
}


class DeferredInstallError(RuntimeError):
    """The deferred operation cannot proceed safely."""


class DeferredInstallCancelled(DeferredInstallError):
    pass


class DeferredInstallExpired(DeferredInstallError):
    pass


class DeferredTargetRace(DeferredInstallError):
    pass


class ManagedDaemonStopError(DeferredInstallError):
    def __init__(self, failure_code: str) -> None:
        super().__init__(failure_code)
        self.failure_code = failure_code


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode(
        "utf-8"
    )


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _valid_digest(value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise DeferredInstallError("reviewed digest is invalid")
    return value


def _valid_job_id(value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _JOB_ID_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise DeferredInstallError("deferred job identity is invalid")
    return value


def _validated_wait_seconds(value: Any) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 1 <= value <= MAX_WAIT_SECONDS
    ):
        raise DeferredInstallError("deferred wait is outside its safe bound")
    return value


def _is_link_or_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(metadata.st_mode):
        return True
    return bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _assert_safe_absolute(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise DeferredInstallError("{} must be absolute".format(label))
    absolute = Path(os.path.abspath(str(path)))
    parts = absolute.parts
    current = Path(parts[0])
    for part in parts[1:]:
        current = current / part
        if _is_link_or_reparse(current):
            raise DeferredInstallError("{} contains an unsafe path component".format(label))
        if not current.exists():
            break
    return absolute


def _secure_directory(path: Path, *, create: bool = True) -> None:
    _assert_safe_absolute(path, "private deferred directory")
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if _is_link_or_reparse(path) or not path.is_dir():
        raise DeferredInstallError("private deferred directory is unsafe")
    if os.name != "nt":
        os.chmod(str(path), 0o700)


def _write_once(path: Path, raw: bytes, maximum: int) -> None:
    if not raw or len(raw) > maximum:
        raise DeferredInstallError("private deferred artifact exceeds its safe bound")
    _secure_directory(path.parent)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(str(path), flags, 0o600)
    except FileExistsError as error:
        raise DeferredInstallError("private deferred artifact is already occupied") from error
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise DeferredInstallError("private deferred artifact is not regular")
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short private deferred write")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if _is_link_or_reparse(path) or not path.is_file():
        raise DeferredInstallError("private deferred artifact changed during publication")
    if os.name != "nt":
        os.chmod(str(path), 0o600)


def _atomic_write(path: Path, raw: bytes, maximum: int) -> None:
    if not raw or len(raw) > maximum:
        raise DeferredInstallError("private deferred state exceeds its safe bound")
    _secure_directory(path.parent)
    temporary = path.with_name(".{}.{}.tmp".format(path.name, secrets.token_hex(8)))
    try:
        _write_once(temporary, raw, maximum)
        os.replace(str(temporary), str(path))
        if os.name != "nt":
            os.chmod(str(path), 0o600)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _read_bounded(path: Path, maximum: int) -> bytes:
    _assert_safe_absolute(path, "private deferred artifact")
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    try:
        descriptor = os.open(str(path), flags)
    except FileNotFoundError as error:
        raise DeferredInstallError("private deferred artifact is missing") from error
    except OSError as error:
        raise DeferredInstallError("private deferred artifact cannot be opened safely") from error
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_size <= 0
            or before.st_size > maximum
        ):
            raise DeferredInstallError("private deferred artifact is unsafe or oversized")
        remaining = maximum + 1
        chunks: List[bytes] = []
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            len(raw) != before.st_size
            or len(raw) > maximum
            or before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_mode != after.st_mode
            or before.st_size != after.st_size
        ):
            raise DeferredInstallError("private deferred artifact changed while reading")
        return raw
    finally:
        os.close(descriptor)


def _decode_canonical_object(raw: bytes) -> Dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DeferredInstallError("private deferred artifact is invalid") from error
    if not isinstance(value, dict) or raw != _canonical_bytes(value):
        raise DeferredInstallError("private deferred artifact is not canonical")
    return value


def _read_object(path: Path, maximum: int) -> Dict[str, Any]:
    return _decode_canonical_object(_read_bounded(path, maximum))


def _validated_receipt(
    value: Any,
    *,
    job_id: str,
    plan_digest: str,
    target_count: Optional[int] = None,
) -> Dict[str, Any]:
    """Validate a terminal receipt and its exact reviewed-job binding."""

    job_id = _valid_job_id(job_id)
    plan_digest = _valid_digest(plan_digest)
    if not isinstance(value, dict) or set(value) != _RECEIPT_FIELDS:
        raise DeferredInstallError("deferred receipt shape is invalid")
    if (
        value.get("schema_version") != DEFERRED_SCHEMA_VERSION
        or value.get("job_id") != job_id
        or value.get("plan_sha256") != plan_digest
        or value.get("status") not in _TERMINAL_STATUSES
        or value.get("phase") not in _RECEIPT_PHASES
        or value.get("apply_status") not in _APPLY_STATUSES
        or value.get("rollback_status") not in _ROLLBACK_STATUSES
        or value.get("failure_code") not in _FAILURE_CODES
    ):
        raise DeferredInstallError("deferred receipt binding or category is invalid")
    count = value.get("target_count")
    if (
        not isinstance(count, int)
        or isinstance(count, bool)
        or not 1 <= count <= 128
        or (target_count is not None and count != target_count)
    ):
        raise DeferredInstallError("deferred receipt target binding is invalid")
    if type(value.get("verification_ok")) is not bool or type(
        value.get("receiver_healthy")
    ) is not bool:
        raise DeferredInstallError("deferred receipt booleans are invalid")
    for name in ("started_at_utc", "finished_at_utc"):
        timestamp = value.get(name)
        if not isinstance(timestamp, str) or not 1 <= len(timestamp) <= 64:
            raise DeferredInstallError("deferred receipt timestamp is invalid")
    if value["status"] == "verified":
        if (
            value["phase"] != "complete"
            or value["apply_status"] != "applied"
            or value["verification_ok"] is not True
            or value["receiver_healthy"] is not True
            or value["rollback_status"] != "not-applicable"
            or value["failure_code"] != "none"
        ):
            raise DeferredInstallError("verified deferred receipt is inconsistent")
    elif value["verification_ok"] is not False or value["receiver_healthy"] is not False:
        raise DeferredInstallError("failed deferred receipt claims successful verification")
    return dict(value)


def _read_receipt(
    path: Path,
    *,
    job_id: str,
    plan_digest: str,
    target_count: Optional[int] = None,
) -> Tuple[Dict[str, Any], bytes]:
    raw = _read_bounded(path, MAX_RECEIPT_BYTES)
    value = _validated_receipt(
        _decode_canonical_object(raw),
        job_id=job_id,
        plan_digest=plan_digest,
        target_count=target_count,
    )
    return value, raw


def _is_strict_no_mutation_receipt(value: Mapping[str, Any]) -> bool:
    categories = _NO_MUTATION_RECEIPT_CATEGORIES.get(str(value.get("status")))
    return bool(
        categories is not None
        and (value.get("phase"), value.get("failure_code")) in categories
        and value.get("apply_status") == "not-started"
        and value.get("verification_ok") is False
        and value.get("receiver_healthy") is False
        and value.get("rollback_status") == "not-applicable"
    )


def _validated_active(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "job_id",
        "plan_sha256",
    }:
        raise DeferredInstallError("deferred active-job shape is invalid")
    if value.get("schema_version") != DEFERRED_SCHEMA_VERSION:
        raise DeferredInstallError("deferred active-job schema is unsupported")
    _valid_job_id(value.get("job_id"))
    _valid_digest(value.get("plan_sha256"))
    return dict(value)


def _validated_ready(
    value: Any, *, job_id: str, request_digest: Optional[str] = None
) -> Tuple[Dict[str, Any], ProcessIdentity]:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "job_id",
        "request_sha256",
        "worker_process",
    }:
        raise DeferredInstallError("deferred worker readiness shape is invalid")
    if (
        value.get("schema_version") != DEFERRED_SCHEMA_VERSION
        or value.get("job_id") != _valid_job_id(job_id)
        or (request_digest is not None and value.get("request_sha256") != request_digest)
    ):
        raise DeferredInstallError("deferred worker readiness binding is invalid")
    _valid_digest(value.get("request_sha256"))
    return dict(value), ProcessIdentity.from_private_value(value.get("worker_process"))


def _replaceable_worker_lost(
    journal: Path,
    previous: Mapping[str, Any],
    previous_paths: Mapping[str, Path],
) -> bool:
    """Return true only for a dead ready worker and a pristine transaction."""

    if not previous_paths["ready"].exists():
        return False
    request_raw = _read_bounded(previous_paths["request"], MAX_REQUEST_BYTES)
    ready, identity = _validated_ready(
        _read_object(previous_paths["ready"], MAX_RECEIPT_BYTES),
        job_id=str(previous["job_id"]),
        request_digest=_digest(request_raw),
    )
    del ready
    if ProcessInspector().is_alive(identity):
        return False
    return _plan_status(journal, str(previous["plan_sha256"])) == "planned"


def _job_paths(journal: Path, job_id: str) -> Dict[str, Path]:
    job = journal.parent / "deferred" / _valid_job_id(job_id)
    return {
        "root": job,
        "runtime": job / "runtime",
        "request": job / "request.json",
        "claim": job / "claim.json",
        "ready": job / "ready.json",
        "state": job / "state.json",
        "cancel": job / "cancel.json",
        "receipt": job / _RECEIPT_BASENAME,
        "active": journal.parent / "deferred-active.json",
    }


def _acquire_active_job(plan: Any, paths: Mapping[str, Path], active: Mapping[str, Any]) -> None:
    """Serialize one active job while allowing a completed job to be replaced."""

    from . import installer

    with installer._lock_transaction_directory(
        plan.journal_path.parent, plan.journal["transaction_identity"]
    ):
        active_path = paths["active"]
        if active_path.exists():
            previous = _validated_active(
                _read_object(active_path, MAX_RECEIPT_BYTES)
            )
            previous_job = _valid_job_id(previous.get("job_id"))
            previous_paths = _job_paths(plan.journal_path, previous_job)
            if previous_paths["receipt"].exists():
                _read_receipt(
                    previous_paths["receipt"],
                    job_id=previous_job,
                    plan_digest=str(previous["plan_sha256"]),
                )
            elif not _replaceable_worker_lost(
                plan.journal_path, previous, previous_paths
            ):
                raise DeferredInstallError("another deferred job is still active")
            _atomic_write(active_path, _canonical_bytes(dict(active)), MAX_RECEIPT_BYTES)
        else:
            _write_once(active_path, _canonical_bytes(dict(active)), MAX_RECEIPT_BYTES)


def _release_active_job(
    plan: Any, paths: Mapping[str, Path], expected: Mapping[str, Any]
) -> None:
    """Release only the exact arm that failed before readiness."""

    from . import installer

    with installer._lock_transaction_directory(
        plan.journal_path.parent, plan.journal["transaction_identity"]
    ):
        active_path = paths["active"]
        if not active_path.exists():
            return
        if _read_object(active_path, MAX_RECEIPT_BYTES) != dict(expected):
            raise DeferredInstallError("active deferred job changed before release")
        if _is_link_or_reparse(active_path) or not active_path.is_file():
            raise DeferredInstallError("active deferred job is unsafe")
        active_path.unlink()


def _load_reviewed_plan(
    journal: Path, plan_digest: str, *, allow_historical_observation: bool = False
) -> Any:
    from .installer import load_plan, load_plan_for_deferred_observation

    journal = _assert_safe_absolute(journal, "transaction journal")
    digest = _valid_digest(plan_digest)
    if allow_historical_observation:
        plan = load_plan_for_deferred_observation(
            journal,
            expected_plan_digest=digest,
            allowed_historical_versions=_HISTORICAL_DEFERRED_OBSERVATION_VERSIONS,
        )
    else:
        plan = load_plan(journal, expected_plan_digest=digest)
    if plan.journal_path != journal:
        raise DeferredInstallError("transaction journal binding changed")
    return plan


def _snapshot_payload(source: Path, destination: Path, expected_digest: str) -> None:
    from . import installer

    if destination.exists():
        raise DeferredInstallError("deferred runtime snapshot is already occupied")
    destination.mkdir(mode=0o700)
    try:
        for source_file, relative in installer._payload_files(source):
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copyfile(str(source_file), str(target), follow_symlinks=False)
        if installer.source_tree_digest(destination) != expected_digest:
            raise DeferredInstallError("deferred runtime snapshot digest differs from review")
        installer._make_tree_read_only(destination)
        if (
            installer.source_tree_digest(destination) != expected_digest
            or not installer._tree_is_read_only(destination)
        ):
            raise DeferredInstallError("deferred runtime snapshot is not immutable")
    except BaseException:
        try:
            installer._make_tree_read_only(destination)
        except Exception:
            pass
        raise


_TARGET_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_CODEX_FEATURE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MANAGED_CODEX_PROTOCOL = "codex-app-server-daemon-stop-v2"
_HISTORICAL_MANAGED_CODEX_PROTOCOL = "codex-app-server-daemon-stop-v1"
_MAX_DAEMON_CONTROL_BYTES = 16 * 1024


def _bounded_runtime_version(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 64
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    ):
        raise DeferredInstallError("{} is invalid".format(label))
    return value


def _regular_file_id(path: Path) -> str:
    try:
        metadata = path.stat()
    except OSError as error:
        raise DeferredInstallError("managed Codex executable is unavailable") from error
    if not stat.S_ISREG(metadata.st_mode):
        raise DeferredInstallError("managed Codex executable is not a regular file")
    return "{}:{}".format(int(metadata.st_dev), int(metadata.st_ino))


def _trusted_native_control_path(environment: Mapping[str, str]) -> str:
    """Return a platform-owned search path without inheriting caller entries."""

    if os.name != "nt":
        return os.defpath
    root_value = next(
        (
            value
            for name, value in environment.items()
            if name.upper() in {"SYSTEMROOT", "WINDIR"}
        ),
        None,
    )
    if not root_value:
        raise DeferredInstallError("Windows native control requires a system root")
    root = _assert_safe_absolute(Path(root_value), "Windows system root")
    if not root.is_dir():
        raise DeferredInstallError("Windows system root is unavailable")
    return os.pathsep.join((str(root / "System32"), str(root)))


def _codex_control_kwargs(home: Path, *, capture: bool) -> Dict[str, Any]:
    environment = _sanitized_environment()
    environment["CODEX_HOME"] = str(home)
    environment["PATH"] = _trusted_native_control_path(environment)
    kwargs: Dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE if capture else subprocess.DEVNULL,
        "stderr": subprocess.PIPE if capture else subprocess.DEVNULL,
        "cwd": str(home),
        "env": environment,
        "close_fds": True,
        "check": False,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(
            subprocess, "CREATE_NO_WINDOW", 0x08000000
        )
    return kwargs


def _run_bound_codex_daemon_control(
    executable_path: str,
    executable_file_id: str,
    home: Path,
    action: str,
    *,
    bootstrap_features: Sequence[str] = (),
) -> subprocess.CompletedProcess:
    if action not in {"bootstrap", "version", "stop"}:
        raise DeferredInstallError("managed Codex control action is invalid")
    if (
        (bootstrap_features and action != "bootstrap")
        or len(bootstrap_features) > 16
        or len(set(bootstrap_features)) != len(bootstrap_features)
        or any(
            not isinstance(feature, str)
            or _CODEX_FEATURE_PATTERN.fullmatch(feature) is None
            for feature in bootstrap_features
        )
    ):
        raise DeferredInstallError("managed Codex bootstrap feature set is invalid")
    executable = _assert_safe_absolute(
        Path(executable_path), "managed Codex executable"
    )
    if _regular_file_id(executable) != executable_file_id:
        raise DeferredInstallError("managed Codex executable path changed")
    timeout = MANAGED_DAEMON_CONTROL_TIMEOUT_SECONDS
    try:
        command = [str(executable), "app-server", "daemon", action]
        for feature in bootstrap_features:
            command.extend(("--enable", feature))
        return subprocess.run(
            command,
            timeout=timeout,
            **_codex_control_kwargs(home, capture=action == "version"),
        )
    except (OSError, subprocess.SubprocessError) as error:
        failure_code = (
            "legacy-daemon-transition-failed"
            if action == "bootstrap"
            else "managed-daemon-stop-failed"
        )
        raise ManagedDaemonStopError(failure_code) from error


def _run_exact_codex_daemon_control(
    inspector: ProcessInspector,
    daemon: ProcessIdentity,
    home: Path,
    action: str,
) -> subprocess.CompletedProcess:
    if action not in {"version", "stop"}:
        raise DeferredInstallError("exact Codex control action is invalid")
    if not inspector.is_exact(daemon) or not inspector.executable_path_matches(daemon):
        raise DeferredInstallError("managed Codex daemon identity changed")
    return _run_bound_codex_daemon_control(
        daemon.executable_path, daemon.executable_file_id, home, action
    )


def _read_bound_codex_daemon_status(
    executable_path: str,
    executable_file_id: str,
    home: Path,
) -> Dict[str, Any]:
    result = _run_bound_codex_daemon_control(
        executable_path, executable_file_id, home, "version"
    )
    stdout = result.stdout or b""
    stderr = result.stderr or b""
    if (
        result.returncode != 0
        or len(stdout) + len(stderr) > _MAX_DAEMON_CONTROL_BYTES
    ):
        raise DeferredInstallError("managed Codex daemon control could not be verified")
    try:
        value = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DeferredInstallError("managed Codex daemon control returned invalid status") from error
    if not isinstance(value, dict):
        raise DeferredInstallError("managed Codex daemon control returned invalid status")
    return value


def _probe_bound_codex_daemon(
    executable_path: str,
    executable_file_id: str,
    home: Path,
) -> Tuple[str, str, str]:
    value = _read_bound_codex_daemon_status(
        executable_path, executable_file_id, home
    )
    if value.get("status") != "running":
        raise DeferredInstallError("managed Codex daemon is not running")
    managed_path_value = value.get("managedCodexPath")
    if not isinstance(managed_path_value, str) or not Path(managed_path_value).is_absolute():
        raise DeferredInstallError("managed Codex daemon executable proof is invalid")
    try:
        managed_path = Path(managed_path_value).resolve(strict=True)
    except OSError as error:
        raise DeferredInstallError("managed Codex daemon executable proof is unavailable") from error
    if _regular_file_id(managed_path) != executable_file_id:
        raise DeferredInstallError("managed Codex daemon differs from its control target")
    return (
        (
            _bounded_runtime_version(value.get("backend"), "Codex daemon backend")
            if value.get("backend") is not None
            else "legacy-ephemeral"
        ),
        _bounded_runtime_version(value.get("cliVersion"), "Codex CLI version"),
        _bounded_runtime_version(
            value.get("appServerVersion"), "Codex app-server version"
        ),
    )


def _probe_managed_codex_daemon(
    inspector: ProcessInspector,
    daemon: ProcessIdentity,
    home: Path,
) -> Tuple[str, str, str]:
    if not inspector.is_exact(daemon) or not inspector.executable_path_matches(daemon):
        raise DeferredInstallError("managed Codex daemon identity changed")
    return _probe_bound_codex_daemon(
        daemon.executable_path, daemon.executable_file_id, home
    )


# Backward-compatible internal name retained for existing focused fixtures.
def _run_codex_daemon_control(
    inspector: ProcessInspector, daemon: ProcessIdentity, home: Path, action: str
) -> subprocess.CompletedProcess:
    return _run_exact_codex_daemon_control(inspector, daemon, home, action)


def _plan_codex_homes(plan: Any) -> Dict[str, Path]:
    result: Dict[str, Path] = {}
    for value in plan.journal.get("codex_homes", []):
        if not isinstance(value, dict):
            raise DeferredInstallError("reviewed Codex target binding is invalid")
        name = value.get("name")
        home_value = value.get("home")
        if (
            not isinstance(name, str)
            or _TARGET_NAME_PATTERN.fullmatch(name) is None
            or name in result
            or not isinstance(home_value, str)
        ):
            raise DeferredInstallError("reviewed Codex target binding is invalid")
        result[name] = _assert_safe_absolute(Path(home_value), "reviewed Codex home")
    return result


def _prepare_managed_codex_daemons(
    plan: Any,
    inspector: ProcessInspector,
    targets: Sequence[ProcessIdentity],
    daemon_pids: Optional[Mapping[str, int]],
    client_pids: Optional[Mapping[str, Sequence[int]]],
    member_pids: Optional[Mapping[str, Sequence[int]]],
    bootstrap_features: Optional[Mapping[str, Sequence[str]]] = None,
) -> List[Dict[str, Any]]:
    daemon_pids = dict(daemon_pids or {})
    client_pids = {name: list(values) for name, values in (client_pids or {}).items()}
    member_pids = {name: list(values) for name, values in (member_pids or {}).items()}
    bootstrap_features = {
        name: list(values) for name, values in (bootstrap_features or {}).items()
    }
    if not daemon_pids:
        if client_pids or member_pids or bootstrap_features:
            raise DeferredInstallError("managed Codex clients or members lack a daemon")
        return []
    if (
        set(client_pids).difference(daemon_pids)
        or set(member_pids).difference(daemon_pids)
        or set(bootstrap_features).difference(daemon_pids)
    ):
        raise DeferredInstallError("managed Codex process group names differ")
    homes = _plan_codex_homes(plan)
    targets_by_pid = {item.pid: item for item in targets}
    used_pids = set()
    actions: List[Dict[str, Any]] = []
    for name in sorted(daemon_pids):
        if name not in homes:
            raise DeferredInstallError("managed Codex daemon is not a reviewed target")
        daemon_pid = daemon_pids[name]
        clients_raw = client_pids.get(name, [])
        members_raw = member_pids.get(name, [])
        all_values = [daemon_pid] + clients_raw + members_raw
        if (
            not isinstance(daemon_pid, int)
            or isinstance(daemon_pid, bool)
            or daemon_pid <= 0
            or not clients_raw
            or len(clients_raw) > 64
            or len(members_raw) > 64
            or any(
                not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0
                for pid in all_values
            )
            or len(set(all_values)) != len(all_values)
            or used_pids.intersection(all_values)
            or any(pid not in targets_by_pid for pid in all_values)
        ):
            raise DeferredInstallError("managed Codex process group is invalid")
        daemon = targets_by_pid[daemon_pid]
        clients = [targets_by_pid[pid] for pid in clients_raw]
        members = [targets_by_pid[pid] for pid in members_raw]
        if any(not client.same_image(daemon) for client in clients):
            raise DeferredInstallError("managed Codex client image differs from its daemon")
        backend, cli_version, app_server_version = _probe_managed_codex_daemon(
            inspector, daemon, homes[name]
        )
        if (
            backend == "legacy-ephemeral"
            and not inspector.supports_exact_graceful_termination()
        ):
            raise DeferredInstallError(
                "legacy Codex daemon lacks exact graceful transition support"
            )
        features = bootstrap_features.get(name, [])
        if (
            len(features) > 16
            or len(set(features)) != len(features)
            or any(
                not isinstance(feature, str)
                or _CODEX_FEATURE_PATTERN.fullmatch(feature) is None
                for feature in features
            )
            or (features and backend != "legacy-ephemeral")
        ):
            raise DeferredInstallError(
                "managed Codex bootstrap feature binding is invalid"
            )
        used_pids.update(all_values)
        actions.append(
            {
                "target_name": name,
                "home": homes[name],
                "daemon": daemon,
                "clients": clients,
                "members": members,
                "backend": backend,
                "bootstrap_features": features,
                "cli_version": cli_version,
                "app_server_version": app_server_version,
            }
        )
    return actions


def _managed_codex_private_value(action: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "protocol": _MANAGED_CODEX_PROTOCOL,
        "target_name": action["target_name"],
        "home": str(action["home"]),
        "daemon_process": action["daemon"].private_value(),
        "client_processes": [item.private_value() for item in action["clients"]],
        "member_processes": [item.private_value() for item in action["members"]],
        "backend": action["backend"],
        "bootstrap_features": list(action["bootstrap_features"]),
        "cli_version": action["cli_version"],
        "app_server_version": action["app_server_version"],
    }


def _validated_managed_codex_daemon(value: Any) -> Dict[str, Any]:
    historical_expected = {
        "protocol",
        "target_name",
        "home",
        "daemon_process",
        "client_processes",
        "member_processes",
        "cli_version",
        "app_server_version",
    }
    expected = historical_expected | {"backend", "bootstrap_features"}
    if not isinstance(value, dict):
        raise DeferredInstallError("managed Codex daemon request shape is invalid")
    if (
        value.get("protocol") == _HISTORICAL_MANAGED_CODEX_PROTOCOL
        and set(value) == historical_expected
    ):
        backend_value = "historical-unbound"
    elif value.get("protocol") == _MANAGED_CODEX_PROTOCOL and set(value) == expected:
        backend_value = _bounded_runtime_version(
            value.get("backend"), "reviewed Codex daemon backend"
        )
    else:
        raise DeferredInstallError("managed Codex daemon request shape is invalid")
    name = value.get("target_name")
    home_value = value.get("home")
    raw_clients = value.get("client_processes")
    raw_members = value.get("member_processes")
    raw_features = value.get("bootstrap_features", [])
    if (
        not isinstance(name, str)
        or _TARGET_NAME_PATTERN.fullmatch(name) is None
        or not isinstance(home_value, str)
        or not isinstance(raw_clients, list)
        or not 1 <= len(raw_clients) <= 64
        or not isinstance(raw_members, list)
        or len(raw_members) > 64
        or not isinstance(raw_features, list)
        or len(raw_features) > 16
        or len(set(raw_features)) != len(raw_features)
        or any(
            not isinstance(feature, str)
            or _CODEX_FEATURE_PATTERN.fullmatch(feature) is None
            for feature in raw_features
        )
        or (raw_features and backend_value != "legacy-ephemeral")
    ):
        raise DeferredInstallError("managed Codex daemon request is invalid")
    daemon = ProcessIdentity.from_private_value(value.get("daemon_process"))
    clients = [ProcessIdentity.from_private_value(item) for item in raw_clients]
    members = [ProcessIdentity.from_private_value(item) for item in raw_members]
    all_processes = [daemon] + clients + members
    if len({item.pid for item in all_processes}) != len(all_processes):
        raise DeferredInstallError("managed Codex process identities overlap")
    return {
        "target_name": name,
        "home": _assert_safe_absolute(Path(home_value), "managed Codex home"),
        "daemon": daemon,
        "clients": clients,
        "members": members,
        "backend": backend_value,
        "bootstrap_features": raw_features,
        "cli_version": _bounded_runtime_version(
            value.get("cli_version"), "reviewed Codex CLI version"
        ),
        "app_server_version": _bounded_runtime_version(
            value.get("app_server_version"), "reviewed Codex app-server version"
        ),
    }


def _bind_managed_codex_daemons(
    plan: Any,
    targets: Sequence[ProcessIdentity],
    actions: Sequence[Mapping[str, Any]],
) -> set[int]:
    homes = _plan_codex_homes(plan)
    targets_by_pid = {item.pid: item for item in targets}
    used_pids = set()
    daemon_owned_pids = set()
    names = set()
    for action in actions:
        name = action["target_name"]
        if name in names or homes.get(name) != action["home"]:
            raise DeferredInstallError("managed Codex daemon differs from reviewed plan")
        names.add(name)
        daemon = action["daemon"]
        clients = action["clients"]
        members = action["members"]
        group = [daemon] + list(clients) + list(members)
        if (
            any(targets_by_pid.get(item.pid) != item for item in group)
            or any(not client.same_image(daemon) for client in clients)
            or used_pids.intersection(item.pid for item in group)
        ):
            raise DeferredInstallError("managed Codex process binding changed")
        used_pids.update(item.pid for item in group)
        daemon_owned_pids.add(daemon.pid)
        daemon_owned_pids.update(item.pid for item in members)
    return daemon_owned_pids


def _request_value(
    *,
    journal: Path,
    plan_digest: str,
    job_id: str,
    wait_seconds: int,
    payload_digest: str,
    targets: Sequence[ProcessIdentity],
    peers: Sequence[ProcessIdentity],
    managed_codex_daemons: Sequence[Mapping[str, Any]] = (),
) -> Dict[str, Any]:
    return {
        "schema_version": DEFERRED_REQUEST_SCHEMA_VERSION,
        "job_id": job_id,
        "journal": str(journal),
        "plan_sha256": plan_digest,
        "payload_sha256": payload_digest,
        "wait_seconds": wait_seconds,
        "created_at_utc": _utc_now(),
        "managed_codex_daemons": [
            _managed_codex_private_value(item) for item in managed_codex_daemons
        ],
        "target_processes": [item.private_value() for item in targets],
        "baseline_image_peers": [item.private_value() for item in peers],
    }


def _validated_request(value: Any, request_path: Path) -> Dict[str, Any]:
    expected_fields = {
        "schema_version",
        "job_id",
        "journal",
        "plan_sha256",
        "payload_sha256",
        "wait_seconds",
        "created_at_utc",
        "target_processes",
        "baseline_image_peers",
    }
    if not isinstance(value, dict):
        raise DeferredInstallError("deferred request shape is invalid")
    request_schema = value.get("schema_version")
    if request_schema == DEFERRED_SCHEMA_VERSION and set(value) == expected_fields:
        raw_managed_daemons: Any = []
    elif (
        request_schema == DEFERRED_REQUEST_SCHEMA_VERSION
        and set(value) == expected_fields | {"managed_codex_daemons"}
    ):
        raw_managed_daemons = value.get("managed_codex_daemons")
        if not isinstance(raw_managed_daemons, list) or len(raw_managed_daemons) > 32:
            raise DeferredInstallError("managed Codex daemon set is invalid")
    else:
        raise DeferredInstallError("deferred request schema is unsupported")
    job_id = _valid_job_id(value.get("job_id"))
    journal_value = value.get("journal")
    if not isinstance(journal_value, str):
        raise DeferredInstallError("deferred request journal binding is invalid")
    journal = _assert_safe_absolute(Path(journal_value), "transaction journal")
    paths = _job_paths(journal, job_id)
    if request_path != paths["request"]:
        raise DeferredInstallError("deferred request path differs from its binding")
    _valid_digest(value.get("plan_sha256"))
    _valid_digest(value.get("payload_sha256"))
    _validated_wait_seconds(value.get("wait_seconds"))
    if not isinstance(value.get("created_at_utc"), str) or len(value["created_at_utc"]) > 64:
        raise DeferredInstallError("deferred request timestamp is invalid")
    raw_targets = value.get("target_processes")
    raw_peers = value.get("baseline_image_peers")
    if (
        not isinstance(raw_targets, list)
        or not 1 <= len(raw_targets) <= 128
        or not isinstance(raw_peers, list)
        or len(raw_peers) > 1024
    ):
        raise DeferredInstallError("deferred process identity set is invalid")
    targets = [ProcessIdentity.from_private_value(item) for item in raw_targets]
    peers = [ProcessIdentity.from_private_value(item) for item in raw_peers]
    if len({item.pid for item in targets}) != len(targets):
        raise DeferredInstallError("deferred target process identities are duplicated")
    managed_daemons = [
        _validated_managed_codex_daemon(item) for item in raw_managed_daemons
    ]
    value = dict(value)
    value["_journal_path"] = journal
    value["_paths"] = paths
    value["_targets"] = targets
    value["_peers"] = peers
    value["_managed_daemons"] = managed_daemons
    return value


def _safe_public_result(
    *,
    job_id: str,
    status: str,
    target_count: int,
    wait_seconds: int,
    managed_daemon_count: int = 0,
    phase: Optional[str] = None,
    receipt_raw: Optional[bytes] = None,
    terminal: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "job_id": _valid_job_id(job_id),
        "filename": _RECEIPT_BASENAME,
        "status": status,
        "targets": target_count,
        "wait_seconds": wait_seconds,
    }
    if managed_daemon_count:
        result["managed_daemons"] = managed_daemon_count
    if phase is not None:
        result["phase"] = phase
    if receipt_raw is not None:
        result["sha256"] = _digest(receipt_raw)
        result["bytes"] = len(receipt_raw)
    if terminal is not None:
        for key in (
            "verification_ok",
            "receiver_healthy",
            "rollback_status",
            "failure_code",
        ):
            if key in terminal:
                result[key] = terminal[key]
    return result


def _sanitized_environment() -> Dict[str, str]:
    allowed = {
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "TMPDIR",
        "LANG",
        "LC_ALL",
    }
    result = {name: value for name, value in os.environ.items() if name.upper() in allowed}
    result["PYTHONDONTWRITEBYTECODE"] = "1"
    return result


def _spawn_worker(python: Path, runtime: Path, request: Path, request_digest: str) -> subprocess.Popen:
    command = [
        str(python),
        "-I",
        "-B",
        str(runtime / "recorder.py"),
        "install",
        "deferred-worker",
        "--request",
        str(request),
        "--request-digest",
        request_digest,
    ]
    kwargs: Dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "cwd": str(runtime),
        "env": _sanitized_environment(),
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)
        )
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(command, **kwargs)


def _reap_worker(process: subprocess.Popen) -> None:
    """Retain and reap a detached child when the arming host stays alive."""

    thread = threading.Thread(
        target=process.wait,
        name="holyskills-deferred-installer-reaper",
        daemon=True,
    )
    thread.start()


def arm_deferred_install(
    journal: Path,
    plan_digest: str,
    target_pids: Sequence[int],
    wait_seconds: int = DEFAULT_WAIT_SECONDS,
    *,
    managed_codex_daemon_pids: Optional[Mapping[str, int]] = None,
    managed_codex_client_pids: Optional[Mapping[str, Sequence[int]]] = None,
    managed_codex_member_pids: Optional[Mapping[str, Sequence[int]]] = None,
    managed_codex_bootstrap_features: Optional[Mapping[str, Sequence[str]]] = None,
) -> Dict[str, Any]:
    """Persist, snapshot, detach, and prove readiness of one reviewed job."""

    wait_seconds = _validated_wait_seconds(wait_seconds)
    plan_digest = _valid_digest(plan_digest)
    journal = _assert_safe_absolute(Path(journal), "transaction journal")
    plan = _load_reviewed_plan(journal, plan_digest)
    if plan.journal.get("status") != "planned":
        raise DeferredInstallError("only a planned transaction can be deferred")
    source = Path(plan.journal["source"]["root"])
    payload_digest = _valid_digest(plan.journal["source"]["payload_sha256"])
    from .installer import source_tree_digest

    if source_tree_digest(source) != payload_digest:
        raise DeferredInstallError("canonical recorder source changed after review")
    inspector = ProcessInspector()
    targets = inspector.capture_many(target_pids)
    inspector.bind_reviewed_pid_namespaces(targets)
    if os.getpid() in {item.pid for item in targets}:
        raise DeferredInstallError("deferred launcher cannot wait for itself")
    launcher_identity = inspector.capture(os.getpid())
    if any(item.same_image(launcher_identity) for item in targets):
        raise DeferredInstallError(
            "target executable is ambiguous with the deferred worker interpreter"
        )
    managed_daemons = _prepare_managed_codex_daemons(
        plan,
        inspector,
        targets,
        managed_codex_daemon_pids,
        managed_codex_client_pids,
        managed_codex_member_pids,
        managed_codex_bootstrap_features,
    )
    peers = inspector.baseline_image_peers(targets)
    job_id = secrets.token_hex(16)
    paths = _job_paths(journal, job_id)
    deferred_root = paths["root"].parent
    _secure_directory(deferred_root)
    try:
        paths["root"].mkdir(mode=0o700)
    except FileExistsError as error:
        raise DeferredInstallError("deferred job identity is already occupied") from error
    _secure_directory(paths["root"], create=False)
    active = {
        "schema_version": DEFERRED_SCHEMA_VERSION,
        "job_id": job_id,
        "plan_sha256": plan_digest,
    }
    _acquire_active_job(plan, paths, active)
    process: Optional[subprocess.Popen] = None
    try:
        request = _request_value(
            journal=journal,
            plan_digest=plan_digest,
            job_id=job_id,
            wait_seconds=wait_seconds,
            payload_digest=payload_digest,
            targets=targets,
            peers=peers,
            managed_codex_daemons=managed_daemons,
        )
        request_raw = _canonical_bytes(request)
        if len(request_raw) > MAX_REQUEST_BYTES:
            raise DeferredInstallError("deferred request exceeds its safe bound")
        request_digest = _digest(request_raw)
        _write_once(paths["request"], request_raw, MAX_REQUEST_BYTES)
        _snapshot_payload(source, paths["runtime"], payload_digest)
        python = Path(plan.journal["python_executable"])
        process = _spawn_worker(
            python, paths["runtime"], paths["request"], request_digest
        )
        deadline = time.monotonic() + READY_WAIT_SECONDS
        while time.monotonic() < deadline:
            if paths["ready"].exists():
                _validated_ready(
                    _read_object(paths["ready"], MAX_RECEIPT_BYTES),
                    job_id=job_id,
                    request_digest=request_digest,
                )
                _reap_worker(process)
                return _safe_public_result(
                    job_id=job_id,
                    status="armed",
                    target_count=len(targets),
                    wait_seconds=wait_seconds,
                    managed_daemon_count=len(managed_daemons),
                )
            if process.poll() is not None:
                break
            time.sleep(0.05)
        raise DeferredInstallError("deferred worker did not prove readiness")
    except Exception:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        if paths["receipt"].exists():
            receipt, receipt_raw = _read_receipt(
                paths["receipt"],
                job_id=job_id,
                plan_digest=plan_digest,
                target_count=len(targets),
            )
        else:
            receipt = _receipt_value(
                job_id=job_id,
                plan_digest=plan_digest,
                status="failed-unapplied",
                phase="preparing",
                target_count=len(targets),
                started_at=_utc_now(),
                apply_status="not-started",
                verification_ok=False,
                receiver_healthy=False,
                rollback_status="not-applicable",
                failure_code="worker-not-ready",
            )
            receipt_raw = _canonical_bytes(receipt)
            receipt = _finish(paths, receipt)
        _release_active_job(plan, paths, active)
        return _safe_public_result(
            job_id=job_id,
            status=str(receipt.get("status", "failed-unapplied")),
            target_count=len(targets),
            wait_seconds=wait_seconds,
            managed_daemon_count=len(managed_daemons),
            phase=str(receipt.get("phase", "preparing")),
            receipt_raw=receipt_raw,
            terminal=receipt,
        )


def _cancel_requested(path: Path, job_id: str) -> bool:
    if not path.exists():
        return False
    value = _read_object(path, MAX_RECEIPT_BYTES)
    if value != {
        "schema_version": DEFERRED_SCHEMA_VERSION,
        "job_id": job_id,
        "requested_at_utc": value.get("requested_at_utc"),
    } or not isinstance(value.get("requested_at_utc"), str) or not 1 <= len(
        value["requested_at_utc"]
    ) <= 64:
        raise DeferredInstallError("deferred cancellation binding is invalid")
    return True


def _state_value(job_id: str, status: str, phase: str, target_count: int) -> Dict[str, Any]:
    return {
        "schema_version": DEFERRED_SCHEMA_VERSION,
        "job_id": job_id,
        "status": status,
        "phase": phase,
        "target_count": target_count,
        "updated_at_utc": _utc_now(),
    }


def _publish_state(paths: Mapping[str, Path], value: Mapping[str, Any]) -> None:
    _atomic_write(paths["state"], _canonical_bytes(dict(value)), MAX_RECEIPT_BYTES)


def _receipt_value(
    *,
    job_id: str,
    plan_digest: str,
    status: str,
    phase: str,
    target_count: int,
    started_at: str,
    apply_status: str,
    verification_ok: bool,
    receiver_healthy: bool,
    rollback_status: str,
    failure_code: str,
) -> Dict[str, Any]:
    value = {
        "schema_version": DEFERRED_SCHEMA_VERSION,
        "job_id": job_id,
        "plan_sha256": plan_digest,
        "status": status,
        "phase": phase,
        "target_count": target_count,
        "apply_status": apply_status,
        "verification_ok": verification_ok,
        "receiver_healthy": receiver_healthy,
        "rollback_status": rollback_status,
        "failure_code": failure_code,
        "started_at_utc": started_at,
        "finished_at_utc": _utc_now(),
    }
    return _validated_receipt(
        value,
        job_id=job_id,
        plan_digest=plan_digest,
        target_count=target_count,
    )


def _finish(paths: Mapping[str, Path], receipt: Mapping[str, Any]) -> Dict[str, Any]:
    value = _validated_receipt(
        dict(receipt),
        job_id=str(receipt.get("job_id")),
        plan_digest=str(receipt.get("plan_sha256")),
        target_count=receipt.get("target_count")
        if isinstance(receipt.get("target_count"), int)
        else None,
    )
    _publish_state(
        paths,
        _state_value(
            str(value["job_id"]),
            str(value["status"]),
            str(value["phase"]),
            int(value["target_count"]),
        ),
    )
    # The create-once receipt is the terminal commit point.  No fallible state
    # publication or rollback decision may follow it in this function.
    _write_once(paths["receipt"], _canonical_bytes(value), MAX_RECEIPT_BYTES)
    return value


def _plan_status(journal: Path, plan_digest: str) -> str:
    try:
        plan = _load_reviewed_plan(journal, plan_digest)
        status_value = plan.journal.get("status")
    except Exception:
        return "unknown"
    return status_value if isinstance(status_value, str) else "unknown"


def _all_targets_alive(
    inspector: ProcessInspector, targets: Sequence[ProcessIdentity]
) -> bool:
    return all(inspector.is_alive(item) for item in targets)


def _rollback_after_post_apply_failure(journal: Path, plan_digest: str) -> str:
    from .installer import rollback_install

    try:
        result = rollback_install(journal, plan_digest=plan_digest)
    except Exception:
        return "blocked"
    return "rolled-back" if result.get("status") == "rolled-back" else "blocked"


def _exact_alive_processes(
    inspector: ProcessInspector, identities: Sequence[ProcessIdentity]
) -> List[ProcessIdentity]:
    alive: List[ProcessIdentity] = []
    for identity in identities:
        if inspector.is_exact(identity):
            alive.append(identity)
        elif inspector.is_alive(identity):
            raise ProcessIdentityError("managed Codex process image changed")
    return alive


def _wait_exact_group_exit(
    inspector: ProcessInspector,
    group: Sequence[ProcessIdentity],
    mutation_guard: Any,
) -> None:
    exit_deadline = time.monotonic() + MANAGED_DAEMON_EXIT_TIMEOUT_SECONDS
    while True:
        alive = _exact_alive_processes(inspector, group)
        if not alive:
            break
        if time.monotonic() >= exit_deadline:
            raise ManagedDaemonStopError("managed-daemon-exit-timeout")
        mutation_guard()
        time.sleep(
            min(
                WAIT_POLL_SECONDS,
                max(0.0, exit_deadline - time.monotonic()),
            )
        )
    mutation_guard()


def _bootstrap_and_stop_bound_codex_daemon(action: Mapping[str, Any]) -> None:
    daemon: ProcessIdentity = action["daemon"]
    home: Path = action["home"]
    result = _run_bound_codex_daemon_control(
        daemon.executable_path,
        daemon.executable_file_id,
        home,
        "bootstrap",
        bootstrap_features=action["bootstrap_features"],
    )
    if result.returncode != 0:
        raise ManagedDaemonStopError("legacy-daemon-transition-failed")
    observed = _probe_bound_codex_daemon(
        daemon.executable_path, daemon.executable_file_id, home
    )
    if observed[0] == "legacy-ephemeral":
        raise ManagedDaemonStopError("legacy-daemon-transition-failed")
    result = _run_bound_codex_daemon_control(
        daemon.executable_path, daemon.executable_file_id, home, "stop"
    )
    if result.returncode != 0:
        raise ManagedDaemonStopError("legacy-daemon-transition-failed")
    deadline = time.monotonic() + MANAGED_DAEMON_EXIT_TIMEOUT_SECONDS
    while True:
        status = _read_bound_codex_daemon_status(
            daemon.executable_path, daemon.executable_file_id, home
        )
        if status.get("status") != "running":
            break
        if time.monotonic() >= deadline:
            raise ManagedDaemonStopError("legacy-daemon-transition-failed")
        time.sleep(
            min(WAIT_POLL_SECONDS, max(0.0, deadline - time.monotonic()))
        )


def _wait_for_relaunch_quiescence(relaunch_detected: Any) -> None:
    """Allow reviewed native stop to finish, but reject a persistent relaunch."""

    deadline = time.monotonic() + MANAGED_DAEMON_EXIT_TIMEOUT_SECONDS
    while relaunch_detected():
        now = time.monotonic()
        if now >= deadline:
            raise DeferredTargetRace("a matching process relaunched")
        time.sleep(
            min(
                QUIESCENCE_POLL_SECONDS,
                max(0.0, deadline - now),
            )
        )


def _stop_managed_codex_daemons(
    inspector: ProcessInspector,
    actions: Sequence[Mapping[str, Any]],
    mutation_guard: Any,
) -> None:
    for action in actions:
        daemon: ProcessIdentity = action["daemon"]
        members: List[ProcessIdentity] = list(action["members"])
        group = [daemon] + members
        alive = _exact_alive_processes(inspector, group)
        if not alive:
            continue
        if daemon not in alive:
            raise ManagedDaemonStopError("managed-daemon-stop-failed")
        observed_versions = _probe_managed_codex_daemon(
            inspector, daemon, action["home"]
        )
        if observed_versions != (
            action["backend"],
            action["cli_version"],
            action["app_server_version"],
        ):
            raise ManagedDaemonStopError("managed-daemon-stop-failed")
        mutation_guard()
        if action["backend"] == "legacy-ephemeral":
            # A legacy app-server can keep its SIGTERM handler pending while an
            # owned host helper is still active. Retire only the exact bound
            # helpers first, then retire the exact daemon incarnation. Every
            # signal remains pidfd-bound and graceful; an unbound or changed
            # process is never touched.
            try:
                alive_members = _exact_alive_processes(inspector, members)
                for member in alive_members:
                    inspector.terminate_exact_gracefully(member)
            except ProcessIdentityError as error:
                raise ManagedDaemonStopError(
                    "legacy-daemon-transition-failed"
                ) from error
            _wait_exact_group_exit(inspector, members, mutation_guard)
            try:
                alive_daemons = _exact_alive_processes(inspector, [daemon])
                if alive_daemons:
                    inspector.terminate_exact_gracefully(daemon)
            except ProcessIdentityError as error:
                raise ManagedDaemonStopError(
                    "legacy-daemon-transition-failed"
                ) from error
            _wait_exact_group_exit(inspector, [daemon], mutation_guard)
            _bootstrap_and_stop_bound_codex_daemon(action)
            continue
        result = _run_codex_daemon_control(
            inspector, daemon, action["home"], "stop"
        )
        if result.returncode != 0:
            raise ManagedDaemonStopError("managed-daemon-stop-failed")
        mutation_guard()
        exit_deadline = time.monotonic() + MANAGED_DAEMON_EXIT_TIMEOUT_SECONDS
        while True:
            alive = _exact_alive_processes(inspector, group)
            if not alive:
                break
            if time.monotonic() >= exit_deadline:
                raise ManagedDaemonStopError("managed-daemon-exit-timeout")
            mutation_guard()
            time.sleep(
                min(
                    WAIT_POLL_SECONDS,
                    max(0.0, exit_deadline - time.monotonic()),
                )
            )
        mutation_guard()


def _run_deferred_install_once(request_path: Path, request_digest: str) -> Dict[str, Any]:
    """Run one detached job; normal errors become categorical private receipts."""

    request_path = _assert_safe_absolute(Path(request_path), "deferred request")
    request_raw = _read_bounded(request_path, MAX_REQUEST_BYTES)
    if _digest(request_raw) != _valid_digest(request_digest):
        raise DeferredInstallError("deferred request digest differs from launch binding")
    try:
        raw_value = json.loads(request_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DeferredInstallError("deferred request is invalid") from error
    request = _validated_request(raw_value, request_path)
    job_id = str(request["job_id"])
    journal: Path = request["_journal_path"]
    paths: Dict[str, Path] = request["_paths"]
    plan_digest = str(request["plan_sha256"])
    targets: List[ProcessIdentity] = request["_targets"]
    peers: List[ProcessIdentity] = request["_peers"]
    managed_daemons: List[Dict[str, Any]] = request["_managed_daemons"]
    wait_seconds = int(request["wait_seconds"])
    started_at = _utc_now()
    claim = {
        "schema_version": DEFERRED_SCHEMA_VERSION,
        "job_id": job_id,
        "request_sha256": request_digest,
    }
    _write_once(paths["claim"], _canonical_bytes(claim), MAX_RECEIPT_BYTES)
    plan = _load_reviewed_plan(journal, plan_digest)
    from .installer import source_tree_digest

    if (
        plan.journal.get("status") != "planned"
        or source_tree_digest(paths["runtime"]) != request["payload_sha256"]
        or source_tree_digest(Path(plan.journal["source"]["root"]))
        != request["payload_sha256"]
    ):
        raise DeferredInstallError("deferred worker review binding changed before readiness")
    inspector = ProcessInspector()
    if not _all_targets_alive(inspector, targets):
        raise DeferredInstallError(
            "reviewed target exited or changed before worker readiness"
        )
    inspector.bind_reviewed_pid_namespaces(targets)
    daemon_owned_pids = _bind_managed_codex_daemons(
        plan, targets, managed_daemons
    )
    passive_targets = [
        item for item in targets if item.pid not in daemon_owned_pids
    ]
    for action in managed_daemons:
        observed_versions = _probe_managed_codex_daemon(
            inspector, action["daemon"], action["home"]
        )
        if observed_versions != (
            action["backend"],
            action["cli_version"],
            action["app_server_version"],
        ):
            raise DeferredInstallError(
                "managed Codex daemon changed before worker readiness"
            )
    worker_identity = inspector.capture(os.getpid())
    ready = {
        "schema_version": DEFERRED_SCHEMA_VERSION,
        "job_id": job_id,
        "request_sha256": request_digest,
        "worker_process": worker_identity.private_value(),
    }
    allowed_peers = peers + [worker_identity]
    waiting_started = time.monotonic()
    deadline = waiting_started + wait_seconds
    last_heartbeat = waiting_started

    def cancelled() -> bool:
        return _cancel_requested(paths["cancel"], job_id)

    def relaunch_detected() -> bool:
        return bool(inspector.detected_relaunches(targets, allowed_peers))

    def mutation_guard() -> None:
        if relaunch_detected():
            raise DeferredTargetRace("a matching process relaunched")

    def finish_before_apply(status: str, phase: str, failure_code: str) -> Dict[str, Any]:
        return _finish(
            paths,
            _receipt_value(
                job_id=job_id,
                plan_digest=plan_digest,
                status=status,
                phase=phase,
                target_count=len(targets),
                started_at=started_at,
                apply_status="not-started",
                verification_ok=False,
                receiver_healthy=False,
                rollback_status="not-applicable",
                failure_code=failure_code,
            ),
        )

    # Readiness is the final initialization commit.  Every subsequent fallible
    # path is covered by run_deferred_install's terminal recovery wrapper.
    _publish_state(paths, _state_value(job_id, "armed", "waiting", len(targets)))
    _write_once(paths["ready"], _canonical_bytes(ready), MAX_RECEIPT_BYTES)

    while True:
        try:
            targets_alive = any(inspector.is_alive(item) for item in passive_targets)
        except ProcessIdentityError:
            return finish_before_apply(
                "failed-unapplied", "waiting", "process-inspection-failed"
            )
        if not targets_alive:
            break
        now = time.monotonic()
        if cancelled():
            return finish_before_apply("cancelled", "waiting", "cancelled")
        if now >= deadline:
            return finish_before_apply("expired", "waiting", "wait-timeout")
        if now - last_heartbeat >= STATE_HEARTBEAT_SECONDS:
            _publish_state(paths, _state_value(job_id, "armed", "waiting", len(targets)))
            last_heartbeat = now
        time.sleep(min(WAIT_POLL_SECONDS, max(0.0, deadline - now)))

    if managed_daemons:
        if cancelled():
            return finish_before_apply("cancelled", "waiting", "cancelled")
        if time.monotonic() >= deadline:
            return finish_before_apply("expired", "waiting", "wait-timeout")
        try:
            mutation_guard()
        except ProcessIdentityError:
            return finish_before_apply(
                "failed-unapplied", "waiting", "process-inspection-failed"
            )
        except DeferredTargetRace:
            return finish_before_apply(
                "target-race", "waiting", "target-relaunched"
            )

        # Cancellation and the user-wait deadline freeze before host-native
        # shutdown begins. A late cancel cannot leave a stopped host without
        # completing the already reviewed install transaction.
        stopping_phase = "stopping-managed-daemons"
        _publish_state(
            paths,
            _state_value(job_id, "armed", stopping_phase, len(targets)),
        )
        try:
            _stop_managed_codex_daemons(
                inspector, managed_daemons, mutation_guard
            )
            _wait_for_relaunch_quiescence(relaunch_detected)
        except ProcessIdentityError:
            return finish_before_apply(
                "failed-unapplied", stopping_phase, "process-inspection-failed"
            )
        except DeferredTargetRace:
            return finish_before_apply(
                "target-race", stopping_phase, "target-relaunched"
            )
        except ManagedDaemonStopError as error:
            return finish_before_apply(
                "failed-unapplied", stopping_phase, error.failure_code
            )
        except DeferredInstallError:
            return finish_before_apply(
                "failed-unapplied", stopping_phase, "managed-daemon-stop-failed"
            )

    _publish_state(paths, _state_value(job_id, "armed", "quiescing", len(targets)))
    quiescence_deadline = (
        time.monotonic() + QUIESCENCE_SECONDS
        if managed_daemons
        else min(deadline, time.monotonic() + QUIESCENCE_SECONDS)
    )
    while time.monotonic() < quiescence_deadline:
        if not managed_daemons and cancelled():
            return finish_before_apply("cancelled", "quiescing", "cancelled")
        try:
            relaunched = relaunch_detected()
        except ProcessIdentityError:
            return finish_before_apply(
                "failed-unapplied", "quiescing", "process-inspection-failed"
            )
        if relaunched:
            return finish_before_apply(
                "target-race", "quiescing", "target-relaunched"
            )
        time.sleep(
            min(
                QUIESCENCE_POLL_SECONDS,
                max(0.0, quiescence_deadline - time.monotonic()),
            )
        )
    if not managed_daemons and time.monotonic() >= deadline:
        return finish_before_apply("expired", "quiescing", "wait-timeout")

    # Without a managed daemon, cancellation and expiry freeze here as before.
    # With one, they froze immediately before the reviewed native stop.
    if not managed_daemons:
        if cancelled():
            return finish_before_apply("cancelled", "quiescing", "cancelled")
        if time.monotonic() >= deadline:
            return finish_before_apply("expired", "quiescing", "wait-timeout")
    try:
        mutation_guard()
    except ProcessIdentityError:
        return finish_before_apply(
            "failed-unapplied", "quiescing", "process-inspection-failed"
        )
    except DeferredTargetRace:
        return finish_before_apply(
            "target-race", "quiescing", "target-relaunched"
        )

    applied = False
    phase = "applying"
    _publish_state(paths, _state_value(job_id, "armed", phase, len(targets)))
    try:
        from .installer import apply_install, verify_install

        apply_kwargs: Dict[str, Any] = {"plan_digest": plan_digest}
        parameters = inspect.signature(apply_install).parameters
        if "mutation_guard" in parameters:
            apply_kwargs["mutation_guard"] = mutation_guard
        if "require_planned" in parameters:
            apply_kwargs["require_planned"] = True
        apply_result = apply_install(journal, **apply_kwargs)
        applied = True
        phase = "verifying"
        _publish_state(paths, _state_value(job_id, "armed", phase, len(targets)))
        mutation_guard()
        verification = verify_install(journal, plan_digest=plan_digest)
        mutation_guard()
        if verification.get("ok") is not True or verification.get("status") != "applied":
            raise DeferredInstallError("deferred installation verification was incomplete")
        return _finish(
            paths,
            _receipt_value(
                job_id=job_id,
                plan_digest=plan_digest,
                status="verified",
                phase="complete",
                target_count=len(targets),
                started_at=started_at,
                apply_status=str(apply_result.get("status", "applied")),
                verification_ok=True,
                receiver_healthy=apply_result.get("receiver_healthy") is True,
                rollback_status="not-applicable",
                failure_code="none",
            ),
        )
    except Exception as error:
        failure_code = "installer-failure"
        if isinstance(error, DeferredTargetRace):
            failure_code = "target-relaunched"
        elif isinstance(error, ProcessIdentityError):
            failure_code = "process-inspection-failed"
        rollback_status = "not-applicable"
        if applied:
            rollback_status = _rollback_after_post_apply_failure(journal, plan_digest)
        journal_status = _plan_status(journal, plan_digest)
        if rollback_status == "blocked" or journal_status.endswith("rollback-blocked"):
            status_value = "rollback-blocked"
        elif rollback_status == "rolled-back" or journal_status == "apply-failed-rolled-back":
            status_value = "failed-rolled-back"
            rollback_status = "rolled-back"
        elif isinstance(error, DeferredTargetRace):
            status_value = "target-race"
        else:
            status_value = "failed-unapplied"
        return _finish(
            paths,
            _receipt_value(
                job_id=job_id,
                plan_digest=plan_digest,
                status=status_value,
                phase=phase,
                target_count=len(targets),
                started_at=started_at,
                apply_status=journal_status,
                verification_ok=False,
                receiver_healthy=False,
                rollback_status=rollback_status,
                failure_code=failure_code,
            ),
        )


def _recover_post_ready_failure(
    request_path: Path, request_digest: str
) -> Dict[str, Any]:
    """Recover a ready worker or leave it truthfully observable as worker-lost."""

    request_path = _assert_safe_absolute(Path(request_path), "deferred request")
    request_raw = _read_bounded(request_path, MAX_REQUEST_BYTES)
    if _digest(request_raw) != _valid_digest(request_digest):
        raise DeferredInstallError("deferred request digest differs from launch binding")
    try:
        request_value = json.loads(request_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DeferredInstallError("deferred request is invalid") from error
    request = _validated_request(request_value, request_path)
    job_id = str(request["job_id"])
    plan_digest = str(request["plan_sha256"])
    journal: Path = request["_journal_path"]
    paths: Dict[str, Path] = request["_paths"]
    target_count = len(request["_targets"])
    if not paths["ready"].exists():
        raise DeferredInstallError("deferred worker failed before readiness")
    _validated_ready(
        _read_object(paths["ready"], MAX_RECEIPT_BYTES),
        job_id=job_id,
        request_digest=request_digest,
    )
    if paths["receipt"].exists():
        receipt, _raw = _read_receipt(
            paths["receipt"],
            job_id=job_id,
            plan_digest=plan_digest,
            target_count=target_count,
        )
        return receipt

    phase = "waiting"
    if paths["state"].exists():
        try:
            state = _read_object(paths["state"], MAX_RECEIPT_BYTES)
            candidate = state.get("phase")
            if state.get("job_id") == job_id and candidate in _RECEIPT_PHASES:
                phase = str(candidate)
        except DeferredInstallError:
            pass

    journal_status = _plan_status(journal, plan_digest)
    if journal_status in {
        "applying",
        "applied",
        "apply-failed-rolling-back",
        "rolling-back",
    }:
        _rollback_after_post_apply_failure(journal, plan_digest)
        journal_status = _plan_status(journal, plan_digest)

    if journal_status == "planned":
        status_value = "failed-unapplied"
        rollback_status = "not-applicable"
    elif journal_status in {"apply-failed-rolled-back", "rolled-back"}:
        status_value = "failed-rolled-back"
        rollback_status = "rolled-back"
    elif journal_status in {
        "apply-failed-rollback-blocked",
        "rollback-blocked",
    }:
        status_value = "rollback-blocked"
        rollback_status = "blocked"
    else:
        # No categorical receipt is safer than guessing at unknown transaction
        # state.  Status inspection will report the dead ready worker as lost.
        raise DeferredInstallError("deferred worker transaction state is unknown")

    return _finish(
        paths,
        _receipt_value(
            job_id=job_id,
            plan_digest=plan_digest,
            status=status_value,
            phase=phase,
            target_count=target_count,
            started_at=str(request["created_at_utc"]),
            apply_status=journal_status,
            verification_ok=False,
            receiver_healthy=False,
            rollback_status=rollback_status,
            failure_code="worker-lost",
        ),
    )


def run_deferred_install(request_path: Path, request_digest: str) -> Dict[str, Any]:
    """Run a detached job with categorical recovery after readiness."""

    try:
        return _run_deferred_install_once(request_path, request_digest)
    except Exception:
        return _recover_post_ready_failure(request_path, request_digest)


def _validated_job(
    journal: Path,
    plan_digest: str,
    job_id: str,
    *,
    allow_historical_observation: bool = False,
) -> Tuple[Any, Dict[str, Path], Dict[str, Any]]:
    journal = _assert_safe_absolute(Path(journal), "transaction journal")
    plan = _load_reviewed_plan(
        journal,
        _valid_digest(plan_digest),
        allow_historical_observation=allow_historical_observation,
    )
    paths = _job_paths(journal, _valid_job_id(job_id))
    request = _validated_request(
        _read_object(paths["request"], MAX_REQUEST_BYTES), paths["request"]
    )
    if request.get("job_id") != job_id or request.get("plan_sha256") != plan_digest:
        raise DeferredInstallError("deferred request differs from active-job binding")
    if paths["active"].exists():
        active = _validated_active(_read_object(paths["active"], MAX_RECEIPT_BYTES))
        if active.get("job_id") == job_id and active != {
            "schema_version": DEFERRED_SCHEMA_VERSION,
            "job_id": job_id,
            "plan_sha256": plan_digest,
        }:
            raise DeferredInstallError("deferred active-job binding differs from review")
    return plan, paths, request


def _read_no_mutation_receipt_after_device_identity_change(
    journal: Path, plan_digest: str, job_id: str
) -> Dict[str, Any]:
    """Read one exact failure receipt without authorizing transaction reuse."""

    from . import RECORDER_VERSION, installer

    journal = _assert_safe_absolute(Path(journal), "transaction journal")
    plan_digest = _valid_digest(plan_digest)
    job_id = _valid_job_id(job_id)

    journal_raw = _read_bounded(journal, MAX_TRANSACTION_BYTES)
    try:
        journal_value = json.loads(journal_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DeferredInstallError("transaction journal is invalid") from error
    if (
        not isinstance(journal_value, dict)
        or journal_raw != installer._json_bytes(journal_value)
        or journal_value.get("journal_path") != str(journal)
        or journal_value.get("plan_sha256") != plan_digest
        or journal_value.get("status") != "planned"
    ):
        raise DeferredInstallError("transaction journal cannot support receipt recovery")
    recorder_version = journal_value.get("recorder_version")
    if not isinstance(recorder_version, str) or (
        recorder_version != RECORDER_VERSION
        and recorder_version not in _HISTORICAL_DEFERRED_OBSERVATION_VERSIONS
    ):
        raise DeferredInstallError(
            "transaction journal recorder version is not observable"
        )
    installer._validate_journal_bindings(
        journal_value, expected_recorder_version=recorder_version
    )

    expected_identity = journal_value.get("transaction_identity")
    current_identity = installer._directory_identity(
        journal.parent, "transaction directory"
    )
    if (
        not isinstance(expected_identity, dict)
        or set(expected_identity) != set(current_identity)
        or expected_identity.get("device") == current_identity.get("device")
        or any(
            expected_identity.get(key) != current_identity.get(key)
            for key in current_identity
            if key != "device"
        )
    ):
        raise DeferredInstallError(
            "transaction identity conflict is not a device-only restart change"
        )

    actions = journal_value.get("actions")
    if not isinstance(actions, list) or any(
        not isinstance(action, dict)
        or action.get("applied") is not False
        or action.get("apply_state") not in {"pending", "unchanged"}
        or action.get("rollback_state") not in {"pending", "restored"}
        for action in actions
    ):
        raise DeferredInstallError("transaction journal does not prove a pristine plan")

    plan_raw = _read_bounded(journal.with_name("plan.json"), MAX_TRANSACTION_BYTES)
    try:
        plan_value = json.loads(plan_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DeferredInstallError("immutable install plan is invalid") from error
    if (
        not isinstance(plan_value, dict)
        or plan_raw != installer._json_bytes(plan_value)
        or _digest(plan_raw) != plan_digest
        or plan_value != installer._immutable_plan_document(journal_value)
    ):
        raise DeferredInstallError("immutable install plan differs from review")

    paths = _job_paths(journal, job_id)
    request = _validated_request(
        _read_object(paths["request"], MAX_REQUEST_BYTES), paths["request"]
    )
    if (
        request.get("job_id") != job_id
        or request.get("plan_sha256") != plan_digest
        or request.get("_journal_path") != journal
    ):
        raise DeferredInstallError("deferred request differs from receipt recovery binding")
    target_count = len(request["_targets"])
    wait_seconds = _validated_wait_seconds(request["wait_seconds"])
    value, raw = _read_receipt(
        paths["receipt"],
        job_id=job_id,
        plan_digest=plan_digest,
        target_count=target_count,
    )
    if not _is_strict_no_mutation_receipt(value):
        raise DeferredInstallError(
            "transaction identity recovery refuses a success or mutation receipt"
        )
    return _safe_public_result(
        job_id=job_id,
        status=str(value["status"]),
        target_count=target_count,
        wait_seconds=wait_seconds,
        managed_daemon_count=len(request["_managed_daemons"]),
        phase=str(value["phase"]),
        receipt_raw=raw,
        terminal=value,
    )


def read_deferred_install_status(
    journal: Path, plan_digest: str, job_id: str
) -> Dict[str, Any]:
    from .installer import InstallerTransactionIdentityConflict

    try:
        _plan, paths, request = _validated_job(
            journal,
            plan_digest,
            job_id,
            allow_historical_observation=True,
        )
    except InstallerTransactionIdentityConflict:
        # security-assumptions.md keeps every mutation fail-closed.  This
        # device-only recovery reads one exact non-success/no-mutation receipt;
        # apply, cancel, rearm, verify, and rollback still use the strict loader.
        return _read_no_mutation_receipt_after_device_identity_change(
            journal, plan_digest, job_id
        )
    target_count = len(request.get("target_processes", []))
    wait_seconds = int(request.get("wait_seconds", DEFAULT_WAIT_SECONDS))
    if paths["receipt"].exists():
        value, raw = _read_receipt(
            paths["receipt"],
            job_id=job_id,
            plan_digest=plan_digest,
            target_count=target_count,
        )
        return _safe_public_result(
            job_id=job_id,
            status=str(value.get("status")),
            target_count=target_count,
            wait_seconds=wait_seconds,
            managed_daemon_count=len(request["_managed_daemons"]),
            phase=str(value.get("phase")),
            receipt_raw=raw,
            terminal=value,
        )
    phase = "preparing"
    status_value = "armed"
    if paths["state"].exists():
        state = _read_object(paths["state"], MAX_RECEIPT_BYTES)
        if state.get("job_id") != job_id:
            raise DeferredInstallError("deferred state belongs to another job")
        phase = str(state.get("phase", phase))
        status_value = str(state.get("status", status_value))
    if paths["ready"].exists():
        _ready, identity = _validated_ready(
            _read_object(paths["ready"], MAX_RECEIPT_BYTES),
            job_id=job_id,
            request_digest=_digest(_read_bounded(paths["request"], MAX_REQUEST_BYTES)),
        )
        if not ProcessInspector().is_alive(identity):
            status_value = "worker-lost"
    return _safe_public_result(
        job_id=job_id,
        status=status_value,
        target_count=target_count,
        wait_seconds=wait_seconds,
        managed_daemon_count=len(request["_managed_daemons"]),
        phase=phase,
    )


def cancel_deferred_install(
    journal: Path, plan_digest: str, job_id: str
) -> Dict[str, Any]:
    _plan, paths, request = _validated_job(
        journal,
        plan_digest,
        job_id,
        allow_historical_observation=True,
    )
    if paths["receipt"].exists():
        return read_deferred_install_status(journal, plan_digest, job_id)
    marker = {
        "schema_version": DEFERRED_SCHEMA_VERSION,
        "job_id": job_id,
        "requested_at_utc": _utc_now(),
    }
    try:
        _write_once(paths["cancel"], _canonical_bytes(marker), MAX_RECEIPT_BYTES)
    except DeferredInstallError:
        existing = _read_object(paths["cancel"], MAX_RECEIPT_BYTES)
        if existing.get("job_id") != job_id:
            raise
    return _safe_public_result(
        job_id=job_id,
        status="cancel-requested",
        target_count=len(request.get("target_processes", [])),
        wait_seconds=int(request.get("wait_seconds", DEFAULT_WAIT_SECONDS)),
        managed_daemon_count=len(request["_managed_daemons"]),
        phase="cancelling",
    )


__all__ = [
    "DEFAULT_WAIT_SECONDS",
    "DeferredInstallError",
    "MAX_WAIT_SECONDS",
    "arm_deferred_install",
    "cancel_deferred_install",
    "read_deferred_install_status",
    "run_deferred_install",
]
