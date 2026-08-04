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


def _load_reviewed_plan(journal: Path, plan_digest: str) -> Any:
    from .installer import load_plan

    journal = _assert_safe_absolute(journal, "transaction journal")
    plan = load_plan(journal, expected_plan_digest=_valid_digest(plan_digest))
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


def _request_value(
    *,
    journal: Path,
    plan_digest: str,
    job_id: str,
    wait_seconds: int,
    payload_digest: str,
    targets: Sequence[ProcessIdentity],
    peers: Sequence[ProcessIdentity],
) -> Dict[str, Any]:
    return {
        "schema_version": DEFERRED_SCHEMA_VERSION,
        "job_id": job_id,
        "journal": str(journal),
        "plan_sha256": plan_digest,
        "payload_sha256": payload_digest,
        "wait_seconds": wait_seconds,
        "created_at_utc": _utc_now(),
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
    if not isinstance(value, dict) or set(value) != expected_fields:
        raise DeferredInstallError("deferred request shape is invalid")
    if value.get("schema_version") != DEFERRED_SCHEMA_VERSION:
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
    value = dict(value)
    value["_journal_path"] = journal
    value["_paths"] = paths
    value["_targets"] = targets
    value["_peers"] = peers
    return value


def _safe_public_result(
    *,
    job_id: str,
    status: str,
    target_count: int,
    wait_seconds: int,
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
    if os.getpid() in {item.pid for item in targets}:
        raise DeferredInstallError("deferred launcher cannot wait for itself")
    launcher_identity = inspector.capture(os.getpid())
    if any(item.same_image(launcher_identity) for item in targets):
        raise DeferredInstallError(
            "target executable is ambiguous with the deferred worker interpreter"
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
            targets_alive = any(inspector.is_alive(item) for item in targets)
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

    _publish_state(paths, _state_value(job_id, "armed", "quiescing", len(targets)))
    quiescence_deadline = min(deadline, time.monotonic() + QUIESCENCE_SECONDS)
    while time.monotonic() < quiescence_deadline:
        if cancelled():
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
    if time.monotonic() >= deadline:
        return finish_before_apply("expired", "quiescing", "wait-timeout")

    # Cancellation and expiry freeze at this boundary.  Once applying is
    # published, the transactional mutation guard retains only process and
    # relaunch safety; a late cancel/timeout cannot interrupt the transaction.
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


def _validated_job(journal: Path, plan_digest: str, job_id: str) -> Tuple[Any, Dict[str, Path], Dict[str, Any]]:
    journal = _assert_safe_absolute(Path(journal), "transaction journal")
    plan = _load_reviewed_plan(journal, _valid_digest(plan_digest))
    paths = _job_paths(journal, _valid_job_id(job_id))
    request = _read_object(paths["request"], MAX_REQUEST_BYTES)
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

    from . import installer

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
    installer._validate_journal_bindings(journal_value)

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
        phase=str(value["phase"]),
        receipt_raw=raw,
        terminal=value,
    )


def read_deferred_install_status(
    journal: Path, plan_digest: str, job_id: str
) -> Dict[str, Any]:
    from .installer import InstallerTransactionIdentityConflict

    try:
        _plan, paths, request = _validated_job(journal, plan_digest, job_id)
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
        phase=phase,
    )


def cancel_deferred_install(
    journal: Path, plan_digest: str, job_id: str
) -> Dict[str, Any]:
    _plan, paths, request = _validated_job(journal, plan_digest, job_id)
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
