"""Transactional, cross-platform installation of the recorder runtime.

The repository checkout is canonical.  Installation creates an immutable,
versioned copy in an explicitly supplied per-user state directory, then edits
only explicitly named Codex or Claude homes. Plans bind the source payload,
private managed-target inventory, and every configuration target by digest;
apply and rollback revalidate those digests at each mutation boundary.

The journal deliberately contains no authentication token.  A private sibling
file carries the one-time generated token between a persisted plan and apply.
On POSIX both files are mode 0600.  On Windows Python's standard library cannot
authoritatively harden or inspect ACLs, so the journal records that inherited
ACLs are used and never claims stronger protection.
"""

from __future__ import annotations

import base64
import copy
from contextlib import contextmanager
import ctypes
from dataclasses import dataclass
from datetime import datetime, timezone
import errno
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple, Union

from . import (
    CLAUDE_HOOK_TIMEOUT_SECONDS,
    CLAUDE_ORDINARY_HOOK_TIMEOUT_SECONDS,
    CLAUDE_PROMPT_HOOK_TIMEOUT_SECONDS,
    CODEX_HOOK_TIMEOUT_SECONDS,
    RECORDER_VERSION,
)
from . import platforms


JOURNAL_SCHEMA_VERSION = 2
INSTALL_PLAN_SCHEMA_VERSION = 1
SETTINGS_SCHEMA_VERSION = 1
MANAGED_TARGETS_SCHEMA_VERSION = 1
MANAGED_ID = "holyskills-delivery-efficiency-v1"
MANAGED_BEGIN = "# BEGIN HOLYSKILLS DELIVERY EFFICIENCY v1"
MANAGED_END = "# END HOLYSKILLS DELIVERY EFFICIENCY v1"
AUTH_HEADER = "x-holyskills-recorder-token"
DEFAULT_LISTEN_PORT = 4319
LIFECYCLE_HANDOFF_MIN_VERSION = (0, 1, 2)
# Anthropic's v2.1.212 release is the first documented build whose OTLP/HTTP
# exporter avoids chunked transfer encoding, which this bounded receiver rejects.
# https://github.com/anthropics/claude-code/releases/tag/v2.1.212
CLAUDE_MINIMUM_VERSION = (2, 1, 212)
CLAUDE_FAIL_CLOSED_ENV_MIN_VERSION = (0, 2, 1)
HOOK_EVENTS = (
    "SessionStart",
    "SessionEnd",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "SubagentStart",
    "SubagentStop",
    "Stop",
)
CLAUDE_HOOK_EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "SubagentStart",
    "SubagentStop",
    "Stop",
    "StopFailure",
)
CLAUDE_ASYNC_HOOK_EVENTS = frozenset(
    {"SubagentStart", "SubagentStop", "Stop", "StopFailure"}
)
CLAUDE_TOOL_MATCHER_EVENTS = frozenset()
CLAUDE_LEGACY_HOOK_EVENTS = (
    "SessionStart",
    "SessionEnd",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "SubagentStop",
    "Stop",
)
CLAUDE_MANAGED_ENV_KEY = "CLAUDE_CODE_ENABLE_TELEMETRY"
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_LOWER_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_RUNTIME_TARGET_PATTERN = re.compile(r"^target_v1_[0-9a-f]{32}$")
_RUNTIME_TARGET_DOMAIN = b"holyskills-delivery-efficiency:runtime-target:v1"
_RUNTIME_TARGET_MIN_VERSION = (0, 2, 3)
_STABLE_HOOK_LAUNCHER_MIN_VERSION = (0, 2, 4)
_WINDOWS_RETRY_ERRORS = {5, 32, 33}
_MAX_CONFIG_BYTES = 4 * 1024 * 1024
_MAX_MANAGED_TARGETS = 1024
_PARENT_LOCK_NAME = ".holyskills-recorder-parent.lock"
_TRANSACTION_LOCK_NAME = ".holyskills-recorder-transaction.lock"
_LOCK_MARKER = b"holyskills-delivery-efficiency-lock-v1\n"


class InstallerError(RuntimeError):
    """Base class for safe installer failures."""


class InstallerConflict(InstallerError):
    """An existing configuration cannot be safely owned or merged."""


class InstallerTransactionIdentityConflict(InstallerConflict):
    """The held transaction directory no longer has its reviewed identity."""


class InstallerDrift(InstallerError):
    """Source or target bytes changed after the reviewed plan."""


class InstallerVerificationError(InstallerError):
    """Installed state does not match the transaction journal."""


@dataclass
class InstallPlan:
    """In-memory plan plus its token, which is never serialized in the journal."""

    journal: Dict[str, Any]
    auth_token: str
    immutable_plan: Optional[Dict[str, Any]] = None
    plan_digest: Optional[str] = None
    transaction_anchor: Optional[Any] = None
    parent_anchors: Optional[Dict[str, Any]] = None
    allow_detached_transaction: bool = False
    windows_stage_bindings: Optional[Dict[str, Dict[str, Any]]] = None

    @property
    def journal_path(self) -> Path:
        return Path(self.journal["journal_path"])

    @property
    def secret_path(self) -> Path:
        return self.journal_path.with_name("plan-secret.json")

    @property
    def plan_path(self) -> Path:
        return self.journal_path.with_name("plan.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8")


def _is_link_or_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(metadata.st_mode):
        return True
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def _assert_no_link_components(path: Path, *, include_leaf: bool = True) -> None:
    """Reject symlinks/junctions in every existing path component."""

    absolute = Path(os.path.abspath(str(path)))
    parts = absolute.parts
    if not parts:
        raise InstallerError("an empty path is not allowed")
    current = Path(parts[0])
    limit = len(parts) if include_leaf else max(1, len(parts) - 1)
    for part in parts[1:limit]:
        current = current / part
        if _is_link_or_reparse(current):
            raise InstallerConflict("symlink or reparse-point path component is not allowed: {}".format(current))
        if not current.exists():
            break
    if include_leaf and len(parts) == 1 and _is_link_or_reparse(current):
        raise InstallerConflict("symlink or reparse-point target is not allowed: {}".format(current))


def _absolute_path(value: Union[str, os.PathLike[str]], label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise InstallerError("{} must be an absolute path".format(label))
    _assert_no_link_components(path)
    return Path(os.path.realpath(str(path)))


def _absolute_executable(value: Union[str, os.PathLike[str]]) -> Path:
    """Resolve a normal platform interpreter symlink to its regular target."""

    path = Path(value).expanduser()
    if not path.is_absolute():
        raise InstallerError("python_executable must be an absolute path")
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise InstallerError("python_executable cannot be resolved: {}".format(path)) from error
    if not resolved.is_file():
        raise InstallerError("python_executable is not a regular file: {}".format(resolved))
    return resolved


def _state_path(value: Union[str, os.PathLike[str]]) -> Path:
    """Apply the shared host policy before filesystem-level link checks."""

    try:
        selected = platforms.state_directory(Path(value).expanduser())
    except (platforms.PlatformConfigurationError, OSError, RuntimeError) as error:
        raise InstallerError("state_root violates the current-host state placement policy") from error
    return _absolute_path(selected, "state_root")


def _paths_overlap(first: Path, second: Path) -> bool:
    try:
        common = Path(os.path.commonpath((str(first), str(second))))
    except ValueError:
        return False
    return common == first or common == second


def _payload_files(source_root: Path) -> List[Tuple[Path, str]]:
    """Return the minimal runtime payload and reject every included link."""

    required = (source_root / "recorder.py", source_root / "contract", source_root / "delivery_efficiency")
    if not required[0].is_file() or not required[1].is_dir() or not required[2].is_dir():
        raise InstallerError("source must contain recorder.py, contract/, and delivery_efficiency/")
    entries: List[Tuple[Path, str]] = []
    for root in required:
        _assert_no_link_components(root)
        if root.is_file():
            entries.append((root, root.relative_to(source_root).as_posix()))
            continue
        for directory, directory_names, file_names in os.walk(str(root), topdown=True, followlinks=False):
            directory_path = Path(directory)
            _assert_no_link_components(directory_path)
            kept_directories: List[str] = []
            for name in sorted(directory_names):
                child = directory_path / name
                if _is_link_or_reparse(child):
                    raise InstallerConflict("source payload contains a symlink or reparse point: {}".format(child))
                if name == "__pycache__":
                    continue
                kept_directories.append(name)
            directory_names[:] = kept_directories
            for name in sorted(file_names):
                file_path = directory_path / name
                if _is_link_or_reparse(file_path):
                    raise InstallerConflict("source payload contains a symlink or reparse point: {}".format(file_path))
                if name.endswith((".pyc", ".pyo")) or name.endswith("_self_test.py"):
                    continue
                metadata = file_path.lstat()
                if not stat.S_ISREG(metadata.st_mode):
                    raise InstallerConflict("source payload contains a non-regular file: {}".format(file_path))
                entries.append((file_path, file_path.relative_to(source_root).as_posix()))
    entries.sort(key=lambda item: item[1])
    return entries


def source_tree_digest(source_root: Union[str, os.PathLike[str]]) -> str:
    """Digest exactly the files copied into the installed runtime."""

    root = _absolute_path(source_root, "source_root")
    digest = hashlib.sha256()
    for path, relative in _payload_files(root):
        raw = path.read_bytes()
        encoded_name = relative.encode("utf-8")
        digest.update(len(encoded_name).to_bytes(8, "big"))
        digest.update(encoded_name)
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def _installed_tree_digest(install_root: Path) -> str:
    _assert_no_link_components(install_root)
    return source_tree_digest(install_root)


def _tree_is_read_only(install_root: Path) -> bool:
    files = [path for path, _relative in _payload_files(install_root)]
    if os.name == "nt":
        readonly_flag = getattr(stat, "FILE_ATTRIBUTE_READONLY", 0x1)
        return all(bool(getattr(path.stat(), "st_file_attributes", 0) & readonly_flag) for path in files)
    write_mask = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
    for path in files:
        if path.stat().st_mode & write_mask:
            return False
    for directory, directory_names, _file_names in os.walk(str(install_root)):
        if Path(directory).stat().st_mode & write_mask:
            return False
        for name in directory_names:
            if (Path(directory) / name).stat().st_mode & write_mask:
                return False
    return True


def _platform_info() -> Dict[str, str]:
    try:
        return platforms.detect_platform().as_event_value()
    except platforms.PlatformConfigurationError as error:
        raise InstallerError("unsupported operating system") from error


def _validate_token(token: str) -> str:
    if not isinstance(token, str) or not _LOWER_HEX_64.fullmatch(token):
        raise InstallerError("auth_token must be 32 bytes encoded as lowercase hex")
    return token


def _allocate_loopback_port() -> Tuple[int, str]:
    """Generate one persisted port, observing availability when permitted."""

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1]), "kernel-observed-available-at-plan"
    except OSError:
        # Agent sandboxes can prohibit bind even though the installed host can
        # run the receiver.  Select from IANA's dynamic range without claiming
        # availability; receiver health will expose a later collision.
        return 49152 + secrets.randbelow(65536 - 49152), "random-dynamic-unverified"


def _supports_receiver_retirement(version: Any) -> bool:
    parsed = _semantic_version(version, fullmatch=True)
    return parsed is not None and parsed >= LIFECYCLE_HANDOFF_MIN_VERSION


def _semantic_version(value: Any, *, fullmatch: bool = False) -> Optional[Tuple[int, int, int]]:
    if not isinstance(value, str):
        return None
    core = r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    pattern = core if fullmatch else r"(?<![0-9]){}(?![0-9])".format(core)
    match = re.fullmatch(pattern, value) if fullmatch else re.search(pattern, value)
    if match is None:
        return None
    return tuple(int(item) for item in match.groups())


def _probe_claude_runtime(
    executable: Optional[Union[str, os.PathLike[str]]],
) -> Tuple[Path, str]:
    selected: Optional[Union[str, os.PathLike[str]]] = executable
    if selected is None:
        selected = shutil.which("claude")
    if selected is None:
        raise InstallerConflict(
            "Claude Code 2.1.212 or newer is required but no Claude executable was found"
        )
    path = _absolute_executable(selected)
    try:
        result = subprocess.run(
            [str(path), "--version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=5.0,
            text=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise InstallerConflict("Claude Code version could not be verified") from error
    output = (result.stdout or "") + "\n" + (result.stderr or "")
    version = _semantic_version(output)
    if result.returncode != 0 or version is None:
        raise InstallerConflict("Claude Code version could not be verified")
    if version < CLAUDE_MINIMUM_VERSION:
        raise InstallerConflict("Claude Code 2.1.212 or newer is required")
    version_text = ".".join(str(item) for item in version)
    return path, version_text


def _allocate_upgrade_port(excluded_port: int) -> Tuple[int, str]:
    for _attempt in range(16):
        port, provenance = _allocate_loopback_port()
        if port != excluded_port:
            return port, provenance
    raise InstallerError("could not allocate a receiver port distinct from the legacy installation")


def _load_json_object(raw: bytes, label: str, *, maximum: int = _MAX_CONFIG_BYTES) -> Dict[str, Any]:
    if len(raw) > maximum:
        raise InstallerConflict("{} exceeds the {} byte safety limit".format(label, maximum))
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InstallerConflict("{} is not valid UTF-8 JSON".format(label)) from error
    if not isinstance(value, dict):
        raise InstallerConflict("{} must contain a JSON object".format(label))
    return value


def _load_existing_settings(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    if _is_link_or_reparse(path) or not path.is_file():
        raise InstallerConflict("settings target must be a regular file, not a link: {}".format(path))
    return _load_existing_settings_bytes(path.read_bytes())


def _load_existing_settings_bytes(raw: bytes) -> Dict[str, Any]:
    value = _load_json_object(raw, "existing recorder settings", maximum=64 * 1024)
    expected = {
        "schema_version",
        "recorder_version",
        "listen_host",
        "listen_port",
        "auth_token",
        "install_root",
        "python_executable",
        "platform",
    }
    if set(value) != expected or value.get("schema_version") != SETTINGS_SCHEMA_VERSION:
        raise InstallerConflict("existing recorder settings have an unsupported shape")
    if _semantic_version(value.get("recorder_version"), fullmatch=True) is None:
        raise InstallerConflict("existing recorder settings contain an invalid recorder version")
    if value.get("listen_host") != "127.0.0.1":
        raise InstallerConflict("existing recorder settings are not loopback-only")
    port = value.get("listen_port")
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise InstallerConflict("existing recorder settings contain an invalid port")
    _validate_token(value.get("auth_token"))
    platform_value = value.get("platform")
    if not isinstance(platform_value, dict) or set(platform_value) != {"os", "environment"}:
        raise InstallerConflict("existing recorder settings contain invalid platform data")
    return value


def _target_key(target: Mapping[str, Any]) -> Tuple[str, str]:
    return (
        str(target["runtime"]),
        _normalized_path_text(Path(str(target["home"]))),
    )


def _validate_managed_targets(
    targets: Any,
    *,
    source_root: Path,
    state_root: Path,
    label: str,
) -> List[Dict[str, str]]:
    """Validate the private persistent inventory without inferring ownership."""

    if not isinstance(targets, list) or len(targets) > _MAX_MANAGED_TARGETS:
        raise InstallerConflict("{} target list is invalid".format(label))
    normalized: List[Dict[str, str]] = []
    names = set()
    paths: List[Path] = []
    for target in targets:
        if not isinstance(target, dict) or set(target) != {"runtime", "name", "home"}:
            raise InstallerConflict("{} target entry is invalid".format(label))
        runtime_name = target.get("runtime")
        name = target.get("name")
        home_value = target.get("home")
        if runtime_name not in {"codex", "claude"}:
            raise InstallerConflict("{} target runtime is invalid".format(label))
        if not isinstance(name, str) or not _NAME_PATTERN.fullmatch(name):
            raise InstallerConflict("{} target name is invalid".format(label))
        if (runtime_name, name) in names:
            raise InstallerConflict("{} target name is duplicated".format(label))
        names.add((runtime_name, name))
        if not isinstance(home_value, str):
            raise InstallerConflict("{} target home is invalid".format(label))
        home = Path(home_value)
        if not home.is_absolute():
            raise InstallerConflict("{} target home is not absolute".format(label))
        _assert_no_link_components(home)
        home = Path(os.path.realpath(str(home)))
        if _paths_overlap(source_root, home) or _paths_overlap(state_root, home):
            raise InstallerConflict("{} target home overlaps source or state".format(label))
        if any(_paths_overlap(existing, home) for existing in paths):
            raise InstallerConflict("{} target homes overlap".format(label))
        paths.append(home)
        normalized.append({"runtime": runtime_name, "name": name, "home": str(home)})
    normalized.sort(key=lambda item: (item["runtime"], item["name"], item["home"]))
    return normalized


def _managed_targets_bytes(targets: Sequence[Mapping[str, str]]) -> bytes:
    return _json_bytes(
        {
            "schema_version": MANAGED_TARGETS_SCHEMA_VERSION,
            "managed_id": MANAGED_ID,
            "targets": [dict(target) for target in targets],
        }
    )


def _load_managed_targets(
    path: Path,
    *,
    source_root: Path,
    state_root: Path,
) -> Optional[List[Dict[str, str]]]:
    if not path.exists():
        return None
    if _is_link_or_reparse(path) or not path.is_file():
        raise InstallerConflict("managed target inventory must be a regular file")
    return _load_managed_targets_bytes(
        path.read_bytes(),
        source_root=source_root,
        state_root=state_root,
    )


def _load_managed_targets_bytes(
    raw: bytes,
    *,
    source_root: Path,
    state_root: Path,
) -> List[Dict[str, str]]:
    value = _load_json_object(raw, "managed target inventory", maximum=256 * 1024)
    if set(value) != {"schema_version", "managed_id", "targets"}:
        raise InstallerConflict("managed target inventory has an unsupported shape")
    if value.get("schema_version") != MANAGED_TARGETS_SCHEMA_VERSION:
        raise InstallerConflict("managed target inventory schema is unsupported")
    if value.get("managed_id") != MANAGED_ID:
        raise InstallerConflict("managed target inventory belongs to another installer")
    targets = _validate_managed_targets(
        value.get("targets"),
        source_root=source_root,
        state_root=state_root,
        label="managed target inventory",
    )
    if raw != _managed_targets_bytes(targets):
        raise InstallerConflict("managed target inventory bytes are not canonical")
    return targets


def _recover_managed_targets_from_transactions(
    state_root: Path,
    previous_settings: Mapping[str, Any],
    *,
    source_root: Path,
) -> List[Dict[str, str]]:
    """Recover pre-inventory ownership only from journals bound to active settings."""

    transactions = state_root / "transactions"
    if not transactions.exists():
        raise InstallerConflict(
            "existing recorder settings have no authoritative managed target inventory"
        )
    _assert_no_link_components(transactions)
    if not transactions.is_dir():
        raise InstallerConflict("recorder transaction history is not a directory")
    settings_digest = _sha256((state_root / "settings.json").read_bytes())
    token_digest = _sha256(str(previous_settings["auth_token"]).encode("ascii"))
    recovered: Dict[Tuple[str, str], Tuple[str, Dict[str, str]]] = {}
    for transaction_dir in sorted(transactions.iterdir(), key=lambda item: item.name):
        if not re.fullmatch(r"[0-9a-f]{32}", transaction_dir.name):
            continue
        if _is_link_or_reparse(transaction_dir) or not transaction_dir.is_dir():
            continue
        journal_path = transaction_dir / "journal.json"
        if _is_link_or_reparse(journal_path) or not journal_path.is_file():
            continue
        try:
            journal = _load_json_object(
                journal_path.read_bytes(),
                "historical transaction journal",
                maximum=4 * 1024 * 1024,
            )
            target = journal["target"]
            receiver = journal["receiver"]
            settings_spec = target["settings"]
        except (InstallerConflict, KeyError, TypeError):
            continue
        if (
            journal.get("status") != "applied"
            or journal.get("managed_id") != MANAGED_ID
            or journal.get("plan_id") != transaction_dir.name
            or _normalized_path_text(Path(str(journal.get("journal_path", ""))))
            != _normalized_path_text(journal_path)
            or _normalized_path_text(Path(str(target.get("state_root", ""))))
            != _normalized_path_text(state_root)
            or _normalized_path_text(Path(str(target.get("install_root", ""))))
            != _normalized_path_text(Path(str(previous_settings["install_root"])))
            or _normalized_path_text(Path(str(settings_spec.get("path", ""))))
            != _normalized_path_text(state_root / "settings.json")
            or settings_spec.get("after_sha256") != settings_digest
            or journal.get("recorder_version") != previous_settings["recorder_version"]
            or receiver.get("listen_port") != previous_settings["listen_port"]
            or receiver.get("auth_token_sha256") != token_digest
            or journal.get("python_executable") != previous_settings["python_executable"]
        ):
            continue
        timestamp = journal.get("updated_at_utc")
        if not isinstance(timestamp, str):
            timestamp = ""
        candidates: List[Dict[str, Any]] = []
        valid_home_shape = True
        for runtime_name, key in (("codex", "codex_homes"), ("claude", "claude_homes")):
            homes = journal.get(key, [])
            if not isinstance(homes, list):
                valid_home_shape = False
                break
            for home in homes:
                if not isinstance(home, dict):
                    valid_home_shape = False
                    break
                candidates.append(
                    {
                        "runtime": runtime_name,
                        "name": home.get("name"),
                        "home": home.get("home"),
                    }
                )
            if not valid_home_shape:
                break
        if not valid_home_shape:
            continue
        try:
            validated = _validate_managed_targets(
                candidates,
                source_root=source_root,
                state_root=state_root,
                label="historical transaction journal",
            )
        except InstallerConflict:
            continue
        for target_record in validated:
            key = _target_key(target_record)
            current = recovered.get(key)
            if current is None or timestamp >= current[0]:
                recovered[key] = (timestamp, target_record)
    if not recovered:
        raise InstallerConflict(
            "existing recorder settings have no authoritative managed target inventory"
        )
    return _validate_managed_targets(
        [item[1] for item in recovered.values()],
        source_root=source_root,
        state_root=state_root,
        label="recovered managed target inventory",
    )


def _settings_value(
    *,
    install_root: Path,
    state_root: Path,
    python_executable: Path,
    listen_port: int,
    auth_token: str,
) -> Dict[str, Any]:
    del state_root  # Kept in the signature to make the ownership boundary explicit.
    return {
        "schema_version": SETTINGS_SCHEMA_VERSION,
        "recorder_version": RECORDER_VERSION,
        "listen_host": "127.0.0.1",
        "listen_port": int(listen_port),
        "auth_token": _validate_token(auth_token),
        "install_root": str(install_root),
        "python_executable": str(python_executable),
        "platform": _platform_info(),
    }


def stable_launcher_bytes() -> bytes:
    """Return the version-neutral launcher copied directly under state_root."""

    template = '''#!/usr/bin/env python3
"""Stable entry point for the installed Holy Skills delivery recorder."""

import json
import os
from pathlib import Path
import re
import runpy
import stat


VERSION_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$")
REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def is_link_or_reparse(path):
    try:
        metadata = path.lstat()
    except OSError:
        return False
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & REPARSE_POINT
    )


def has_link_component(path):
    absolute = Path(os.path.abspath(str(path)))
    parts = absolute.parts
    if not parts:
        return True
    current = Path(parts[0])
    for part in parts[1:]:
        current = current / part
        if is_link_or_reparse(current):
            return True
    return False


LAUNCHER_PATH = Path(os.path.abspath(__file__))
if has_link_component(LAUNCHER_PATH) or not LAUNCHER_PATH.is_file():
    raise SystemExit("delivery-efficiency launcher topology is unsafe")
STATE_ROOT = LAUNCHER_PATH.parent
SETTINGS_PATH = STATE_ROOT / "settings.json"

if has_link_component(SETTINGS_PATH) or not SETTINGS_PATH.is_file():
    raise SystemExit("delivery-efficiency settings are missing or unsafe")
raw = SETTINGS_PATH.read_bytes()
if len(raw) > 65536:
    raise SystemExit("delivery-efficiency settings exceed the safety limit")
try:
    settings = json.loads(raw.decode("utf-8"))
except (UnicodeDecodeError, json.JSONDecodeError):
    raise SystemExit("delivery-efficiency settings are not valid UTF-8 JSON")
if not isinstance(settings, dict) or settings.get("schema_version") != 1:
    raise SystemExit("delivery-efficiency settings schema is unsupported")
version = settings.get("recorder_version")
if not isinstance(version, str) or VERSION_PATTERN.fullmatch(version) is None:
    raise SystemExit("delivery-efficiency recorder_version is invalid")
install_value = settings.get("install_root")
if not isinstance(install_value, str):
    raise SystemExit("delivery-efficiency install_root is invalid")
install_root = Path(install_value)
if not install_root.is_absolute():
    raise SystemExit("delivery-efficiency install_root must be absolute")
expected_root = STATE_ROOT / "installs" / version
if os.path.normcase(os.path.abspath(str(install_root))) != os.path.normcase(os.path.abspath(str(expected_root))):
    raise SystemExit("delivery-efficiency install_root is outside the versioned state location")
if has_link_component(install_root) or not install_root.is_dir():
    raise SystemExit("delivery-efficiency install_root is missing or unsafe")
entry = install_root / "recorder.py"
if has_link_component(entry) or not entry.is_file():
    raise SystemExit("delivery-efficiency installed entry point is missing or unsafe")
os.environ["HOLYSKILLS_DELIVERY_EFFICIENCY_STATE_DIR"] = str(STATE_ROOT)
runpy.run_path(str(entry), run_name="__main__")
'''
    return template.encode("utf-8")


def _runtime_target_ref(
    auth_token: str,
    runtime: str,
    canonical_home: Union[str, os.PathLike[str]],
) -> str:
    """Derive non-secret, path-hiding correlation metadata for one runtime home."""

    token = _validate_token(auth_token)
    if runtime not in {"codex", "claude"}:
        raise InstallerError("runtime target family is unsupported")
    home = Path(canonical_home)
    if not home.is_absolute():
        raise InstallerError("runtime target home must be an absolute canonical path")
    normalized_home = _normalized_path_text(home)
    message = b"\x00".join(
        (
            _RUNTIME_TARGET_DOMAIN,
            runtime.encode("ascii"),
            normalized_home.encode("utf-8"),
        )
    )
    digest = hmac.new(bytes.fromhex(token), message, hashlib.sha256).hexdigest()
    return "target_v1_" + digest[:32]


def _hook_arguments(
    python_executable: Path,
    entry_root: Path,
    state_root: Path,
    runtime_target: Optional[str] = None,
) -> List[str]:
    arguments = [
        str(python_executable),
        str(entry_root / "recorder.py"),
        "hook",
        "codex",
        "--state-dir",
        str(state_root),
        "--managed-id",
        MANAGED_ID,
    ]
    if runtime_target is not None:
        if not isinstance(runtime_target, str) or not _RUNTIME_TARGET_PATTERN.fullmatch(
            runtime_target
        ):
            raise InstallerError("runtime target reference is invalid")
        arguments.extend(("--runtime-target", runtime_target))
    return arguments


def build_posix_hook_command(arguments: Sequence[str]) -> str:
    """Quote a command without interpolation by a POSIX-compatible shell."""

    return " ".join(shlex.quote(str(argument)) for argument in arguments)


def _powershell_literal(value: str) -> str:
    return "'{}'".format(value.replace("'", "''"))


def build_windows_hook_command(arguments: Sequence[str]) -> str:
    """Build a cmd-safe command by carrying all paths in encoded PowerShell.

    The visible command contains only a fixed executable/options and Base64.
    Characters such as %, !, &, |, quotes, and parentheses in user profile
    paths therefore never pass through cmd.exe's interpolation grammar.
    """

    if not arguments:
        raise InstallerError("a hook command requires an executable")
    executable = _powershell_literal(str(arguments[0]))
    rest = " ".join(_powershell_literal(str(argument)) for argument in arguments[1:])
    script = "$ErrorActionPreference='Stop'; & {} {}; exit $LASTEXITCODE".format(executable, rest)
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    return "powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand {}".format(encoded)


def _hook_handler(
    python_executable: Path,
    entry_root: Path,
    state_root: Path,
    runtime_target: Optional[str] = None,
) -> Dict[str, Any]:
    arguments = _hook_arguments(
        python_executable,
        entry_root,
        state_root,
        runtime_target,
    )
    return {
        "type": "command",
        "command": build_posix_hook_command(arguments),
        "commandWindows": build_windows_hook_command(arguments),
        "timeout": CODEX_HOOK_TIMEOUT_SECONDS,
    }


def _handler_is_managed(handler: Any) -> bool:
    if not isinstance(handler, dict):
        return False
    if MANAGED_ID in str(handler.get("command", "")):
        return True
    arguments = handler.get("args")
    return isinstance(arguments, list) and MANAGED_ID in arguments


def _claude_hook_arguments(python_executable: Path, entry_root: Path, state_root: Path) -> List[str]:
    return [
        str(python_executable),
        str(entry_root / "recorder.py"),
        "hook",
        "claude",
        "--state-dir",
        str(state_root),
        "--managed-id",
        MANAGED_ID,
    ]


def _claude_hook_handler(
    python_executable: Path,
    entry_root: Path,
    state_root: Path,
    event: str = "SessionStart",
    *,
    legacy_uniform_timeout: bool = False,
    legacy_shell_command: bool = False,
) -> Dict[str, Any]:
    """One shell-free Claude command hook with exact argv boundaries."""

    arguments = _claude_hook_arguments(python_executable, entry_root, state_root)
    if legacy_shell_command and _platform_info()["os"] == "windows":
        command = build_windows_hook_command(arguments)
        handler: Dict[str, Any] = {"type": "command", "command": command}
    elif legacy_shell_command:
        command = build_posix_hook_command(arguments)
        handler = {"type": "command", "command": command}
    else:
        handler = {
            "type": "command",
            "command": arguments[0],
            "args": arguments[1:],
        }
    timeout = (
        CLAUDE_HOOK_TIMEOUT_SECONDS
        if event == "SessionStart" or legacy_uniform_timeout
        else CLAUDE_PROMPT_HOOK_TIMEOUT_SECONDS
        if event == "UserPromptSubmit"
        else CLAUDE_ORDINARY_HOOK_TIMEOUT_SECONDS
    )
    handler["timeout"] = timeout
    if event in CLAUDE_ASYNC_HOOK_EVENTS and not legacy_uniform_timeout:
        handler["async"] = True
    return handler


def _claude_hook_handlers(
    python_executable: Path,
    entry_root: Path,
    state_root: Path,
    *,
    legacy_uniform_timeout: bool = False,
    legacy_shell_command: bool = False,
    events: Optional[Sequence[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    selected_events = tuple(events or CLAUDE_HOOK_EVENTS)
    return {
        event: _claude_hook_handler(
            python_executable,
            entry_root,
            state_root,
            event,
            legacy_uniform_timeout=legacy_uniform_timeout,
            legacy_shell_command=legacy_shell_command,
        )
        for event in selected_events
    }


def _managed_claude_env_for_version(
    listen_port: int, auth_token: str, recorder_version: Optional[str]
) -> Dict[str, str]:
    """Return the exact installer-owned Claude environment for one release.

    User settings override inherited shell values, so current releases pin
    unused signals and every content-bearing telemetry gate off. Project,
    local, CLI, or managed settings have higher precedence and remain an
    external configuration boundary that this user-level installer cannot
    claim to control.
    """

    environment = {
        CLAUDE_MANAGED_ENV_KEY: "1",
        "OTEL_LOGS_EXPORTER": "otlp",
        "OTEL_LOG_ASSISTANT_RESPONSES": "0",
        "OTEL_EXPORTER_OTLP_LOGS_PROTOCOL": "http/json",
        "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://127.0.0.1:{}/v1/logs".format(int(listen_port)),
        "OTEL_EXPORTER_OTLP_LOGS_HEADERS": "{}={}".format(AUTH_HEADER, _validate_token(auth_token)),
    }
    version = _semantic_version(recorder_version, fullmatch=True)
    if version is None:
        raise InstallerConflict("Claude telemetry environment requires a valid recorder version")
    if version >= CLAUDE_FAIL_CLOSED_ENV_MIN_VERSION:
        environment.update(
            {
                "OTEL_METRICS_EXPORTER": "none",
                "OTEL_TRACES_EXPORTER": "none",
                "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA": "0",
                "ENABLE_ENHANCED_TELEMETRY_BETA": "0",
                "OTEL_LOG_USER_PROMPTS": "0",
                "OTEL_LOG_TOOL_DETAILS": "0",
                "OTEL_LOG_TOOL_CONTENT": "0",
                "OTEL_LOG_RAW_API_BODIES": "0",
                "OTEL_METRICS_INCLUDE_ACCOUNT_UUID": "false",
                "OTEL_METRICS_INCLUDE_SESSION_ID": "false",
                "OTEL_METRICS_INCLUDE_RESOURCE_ATTRIBUTES": "false",
            }
        )
    return environment


def _managed_claude_env(listen_port: int, auth_token: str) -> Dict[str, str]:
    """The managed telemetry environment for the current recorder release."""

    return _managed_claude_env_for_version(listen_port, auth_token, RECORDER_VERSION)


def _render_claude_settings(
    original: bytes,
    new_handlers: Mapping[str, Dict[str, Any]],
    previous_handlers: Optional[Mapping[str, Dict[str, Any]]],
    *,
    listen_port: int,
    auth_token: str,
    previous_port: Optional[int],
    previous_token: Optional[str],
    previous_version: Optional[str] = None,
) -> bytes:
    if original:
        value = _load_json_object(original, "Claude settings.json")
    else:
        value = {}
    hooks = value.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise InstallerConflict("Claude settings.json field 'hooks' must be an object")

    located: Dict[str, List[Tuple[Dict[str, Any], int]]] = {event: [] for event in CLAUDE_HOOK_EVENTS}
    deprecated: Dict[str, List[Tuple[Dict[str, Any], int]]] = {}
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            raise InstallerConflict("Claude hook event {} must be an array".format(event))
        for group in groups:
            if not isinstance(group, dict):
                raise InstallerConflict("Claude hook groups must be JSON objects")
            handlers = group.get("hooks")
            if not isinstance(handlers, list):
                raise InstallerConflict("Claude hook group handlers must be an array")
            for index, handler in enumerate(handlers):
                if _handler_is_managed(handler):
                    if event not in located:
                        if (
                            previous_handlers is None
                            or event not in previous_handlers
                            or handler != previous_handlers[event]
                        ):
                            raise InstallerConflict(
                                "managed telemetry handler is attached to unsupported Claude event {}".format(event)
                            )
                        deprecated.setdefault(event, []).append((group, index))
                        continue
                    located[event].append((group, index))

    for event, matches in deprecated.items():
        if len(matches) != 1:
            raise InstallerConflict(
                "duplicate deprecated managed telemetry handlers for Claude event {}".format(event)
            )
        group, index = matches[0]
        del group["hooks"][index]

    for event in CLAUDE_HOOK_EVENTS:
        matches = located[event]
        if len(matches) > 1:
            raise InstallerConflict("duplicate managed telemetry handlers for Claude event {}".format(event))
        if not matches:
            event_groups = hooks.setdefault(event, [])
            if not isinstance(event_groups, list):
                raise InstallerConflict("Claude hook event {} must be an array".format(event))
            group = {"hooks": [copy.deepcopy(new_handlers[event])]}
            if event in CLAUDE_TOOL_MATCHER_EVENTS:
                group = {"matcher": "*", "hooks": [copy.deepcopy(new_handlers[event])]}
            event_groups.append(group)
            continue
        group, index = matches[0]
        current = group["hooks"][index]
        if current == new_handlers[event]:
            continue
        if previous_handlers is not None and current == previous_handlers[event]:
            group["hooks"][index] = copy.deepcopy(new_handlers[event])
            continue
        raise InstallerConflict(
            "managed Claude telemetry handler for {} was edited outside the installer".format(event)
        )

    environment = value.setdefault("env", {})
    if not isinstance(environment, dict):
        raise InstallerConflict("Claude settings.json field 'env' must be an object")
    managed_env = _managed_claude_env(listen_port, auth_token)
    previous_env: Dict[str, str] = {}
    if previous_port is not None and previous_token is not None:
        previous_env = _managed_claude_env_for_version(
            previous_port, previous_token, previous_version
        )
    for key, existing_value in environment.items():
        if not isinstance(key, str):
            raise InstallerConflict("Claude settings.json env keys must be strings")
        owns_telemetry = (
            key in managed_env
            or key in previous_env
            or key.upper().startswith("OTEL_")
        )
        if not owns_telemetry:
            continue
        if key not in managed_env:
            raise InstallerConflict(
                "Claude settings.json already routes OpenTelemetry; refusing to overwrite it"
            )
        if existing_value == managed_env[key] or existing_value == previous_env.get(key):
            continue
        raise InstallerConflict(
            "managed Claude telemetry environment was edited outside the installer"
        )
    environment.update(managed_env)
    return _json_bytes(value)


def _remove_exact_managed_handlers(
    hooks: Dict[str, Any],
    expected_handlers: Mapping[str, Dict[str, Any]],
    expected_events: Sequence[str],
    *,
    label: str,
) -> None:
    """Remove only exact installer-owned handlers, leaving every container intact."""

    located: Dict[str, List[Tuple[Dict[str, Any], int]]] = {
        event: [] for event in expected_events
    }
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            raise InstallerConflict("{} hook event {} must be an array".format(label, event))
        for group in groups:
            if not isinstance(group, dict):
                raise InstallerConflict("{} hook groups must be JSON objects".format(label))
            handlers = group.get("hooks")
            if not isinstance(handlers, list):
                raise InstallerConflict("{} hook group handlers must be an array".format(label))
            for index, handler in enumerate(handlers):
                if not _handler_is_managed(handler):
                    continue
                if event not in located:
                    raise InstallerConflict(
                        "managed telemetry handler is attached to unsupported {} event {}".format(
                            label, event
                        )
                    )
                located[event].append((group, index))
    for event in expected_events:
        matches = located[event]
        if len(matches) != 1:
            raise InstallerConflict(
                "{} must contain exactly one managed telemetry handler for {}".format(
                    label, event
                )
            )
        group, index = matches[0]
        if group["hooks"][index] != expected_handlers[event]:
            raise InstallerConflict(
                "managed {} telemetry handler for {} was edited outside the installer".format(
                    label, event
                )
            )
    for event in expected_events:
        group, index = located[event][0]
        del group["hooks"][index]


def _retire_claude_settings(
    original: bytes,
    previous_handlers: Mapping[str, Dict[str, Any]],
    *,
    previous_port: int,
    previous_token: str,
    previous_version: Optional[str],
) -> bytes:
    value = _load_json_object(original, "Claude settings.json")
    hooks = value.get("hooks")
    if not isinstance(hooks, dict):
        raise InstallerConflict("Claude settings.json has no managed hooks object")
    _remove_exact_managed_handlers(
        hooks,
        previous_handlers,
        tuple(previous_handlers),
        label="Claude",
    )
    environment = value.get("env")
    if not isinstance(environment, dict):
        raise InstallerConflict("Claude settings.json has no managed telemetry environment")
    expected_env = _managed_claude_env_for_version(
        previous_port, previous_token, previous_version
    )
    for key, expected_value in expected_env.items():
        if environment.get(key) != expected_value:
            raise InstallerConflict(
                "managed Claude telemetry environment was edited outside the installer"
            )
    for key in expected_env:
        del environment[key]
    return _json_bytes(value)


def _previous_claude_handlers(
    settings: Optional[Dict[str, Any]], state_root: Path
) -> Optional[Dict[str, Dict[str, Any]]]:
    if settings is None:
        return None
    try:
        python = Path(settings["python_executable"])
        install = Path(settings["install_root"])
    except (KeyError, TypeError):
        return None
    previous_version = _semantic_version(settings.get("recorder_version"), fullmatch=True)
    legacy_uniform_timeout = previous_version is None or previous_version < (0, 1, 3)
    entry_root = (
        state_root
        if previous_version is not None
        and previous_version >= _STABLE_HOOK_LAUNCHER_MIN_VERSION
        else install
    )
    return _claude_hook_handlers(
        python,
        entry_root,
        state_root,
        legacy_uniform_timeout=legacy_uniform_timeout,
        legacy_shell_command=legacy_uniform_timeout,
        events=CLAUDE_LEGACY_HOOK_EVENTS if legacy_uniform_timeout else CLAUDE_HOOK_EVENTS,
    )


def _plan_claude_home(
    name: str,
    home: Path,
    new_handlers: Mapping[str, Dict[str, Any]],
    previous_handlers: Optional[Mapping[str, Dict[str, Any]]],
    *,
    listen_port: int,
    auth_token: str,
    previous_settings: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if not _NAME_PATTERN.fullmatch(name):
        raise InstallerError("Claude home name must be a stable 1-64 character identifier: {}".format(name))
    _assert_no_link_components(home)
    if not home.is_dir():
        raise InstallerConflict(
            "Claude home must already exist as a real directory: {}".format(home)
        )
    settings_path = home / "settings.json"
    settings_state = _file_state(settings_path)
    settings_before = _read_or_empty(settings_path)
    previous_port = previous_settings.get("listen_port") if previous_settings else None
    previous_token = previous_settings.get("auth_token") if previous_settings else None
    settings_after = _render_claude_settings(
        settings_before,
        new_handlers,
        previous_handlers,
        listen_port=listen_port,
        auth_token=auth_token,
        previous_port=previous_port if isinstance(previous_port, int) else None,
        previous_token=previous_token if isinstance(previous_token, str) else None,
        previous_version=(
            previous_settings.get("recorder_version")
            if previous_settings and isinstance(previous_settings.get("recorder_version"), str)
            else None
        ),
    )
    return {
        "name": name,
        "home": str(home),
        "home_existed": home.exists(),
        "settings": {
            "path": str(settings_path),
            "before": settings_state,
            "after_sha256": _sha256(settings_after),
        },
    }


def _render_hooks(
    original: bytes,
    new_handler: Dict[str, Any],
    previous_handler: Optional[Dict[str, Any]],
) -> bytes:
    if original:
        value = _load_json_object(original, "Codex hooks.json")
    else:
        value = {}
    hooks = value.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise InstallerConflict("Codex hooks.json field 'hooks' must be an object")

    located: Dict[str, List[Tuple[Dict[str, Any], int]]] = {event: [] for event in HOOK_EVENTS}
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            raise InstallerConflict("Codex hook event {} must be an array".format(event))
        for group in groups:
            if not isinstance(group, dict):
                raise InstallerConflict("Codex hook groups must be JSON objects")
            handlers = group.get("hooks")
            if not isinstance(handlers, list):
                raise InstallerConflict("Codex hook group handlers must be an array")
            for index, handler in enumerate(handlers):
                if _handler_is_managed(handler):
                    if event not in located:
                        raise InstallerConflict("managed telemetry handler is attached to unsupported event {}".format(event))
                    located[event].append((group, index))

    for event in HOOK_EVENTS:
        matches = located[event]
        if len(matches) > 1:
            raise InstallerConflict("duplicate managed telemetry handlers for {}".format(event))
        if not matches:
            event_groups = hooks.setdefault(event, [])
            if not isinstance(event_groups, list):
                raise InstallerConflict("Codex hook event {} must be an array".format(event))
            event_groups.append({"hooks": [copy.deepcopy(new_handler)]})
            continue
        group, index = matches[0]
        current = group["hooks"][index]
        if current == new_handler:
            continue
        if previous_handler is not None and current == previous_handler:
            group["hooks"][index] = copy.deepcopy(new_handler)
            continue
        raise InstallerConflict("managed telemetry handler for {} was edited outside the installer".format(event))
    return _json_bytes(value)


def _retire_hooks(original: bytes, previous_handler: Dict[str, Any]) -> bytes:
    value = _load_json_object(original, "Codex hooks.json")
    hooks = value.get("hooks")
    if not isinstance(hooks, dict):
        raise InstallerConflict("Codex hooks.json has no managed hooks object")
    _remove_exact_managed_handlers(
        hooks,
        {event: previous_handler for event in HOOK_EVENTS},
        HOOK_EVENTS,
        label="Codex",
    )
    return _json_bytes(value)


def _toml_without_comments(line: str) -> str:
    output: List[str] = []
    quote: Optional[str] = None
    escaped = False
    for character in line:
        if quote == '"':
            output.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if quote == "'":
            output.append(character)
            if character == quote:
                quote = None
            continue
        if character in ("'", '"'):
            quote = character
            output.append(character)
        elif character == "#":
            break
        else:
            output.append(character)
    return "".join(output)


_OTEL_TABLE = re.compile(r"^\s*\[\[?\s*(?:otel|[\"']otel[\"'])(?=\s*(?:[.\]]))", re.IGNORECASE)
_OTEL_KEY = re.compile(r"^\s*(?:otel|[\"']otel[\"'])\s*(?:\.|=)", re.IGNORECASE)
_TOML_TABLE_HEADER = re.compile(
    r"^\s*(?:"
    r"\[\[\s*[A-Za-z0-9_-]+(?:\s*\.\s*[A-Za-z0-9_-]+)*\s*\]\]"
    r"|\[\s*[A-Za-z0-9_-]+(?:\s*\.\s*[A-Za-z0-9_-]+)*\s*\]"
    r")\s*$"
)


def _contains_otel_definition(text: str) -> bool:
    for line in text.splitlines():
        content = _toml_without_comments(line)
        if _OTEL_TABLE.match(content) or _OTEL_KEY.match(content):
            return True
    return False


def _toml_string(value: str) -> str:
    return '"{}"'.format(value.replace("\\", "\\\\").replace('"', '\\"'))


def _managed_otel_block(listen_port: int, auth_token: str, newline: str = "\n") -> str:
    endpoint = "http://127.0.0.1:{}/v1/logs".format(listen_port)
    lines = (
        MANAGED_BEGIN,
        "[otel]",
        'environment = "dev"',
        "log_user_prompt = false",
        "exporter = { otlp-http = { endpoint = %s, protocol = \"json\", headers = { %s = %s } } }"
        % (_toml_string(endpoint), _toml_string(AUTH_HEADER), _toml_string(auth_token)),
        MANAGED_END,
    )
    return newline.join(lines) + newline


def _split_managed_block(text: str) -> Optional[Tuple[str, str, str]]:
    begin_matches = list(re.finditer(r"(?m)^[ \t]*" + re.escape(MANAGED_BEGIN) + r"[ \t]*(?:\r?\n|$)", text))
    end_matches = list(re.finditer(r"(?m)^[ \t]*" + re.escape(MANAGED_END) + r"[ \t]*(?:\r?\n|$)", text))
    if not begin_matches and not end_matches:
        return None
    if len(begin_matches) != 1 or len(end_matches) != 1 or end_matches[0].start() <= begin_matches[0].start():
        raise InstallerConflict("Codex config.toml contains malformed or duplicate telemetry markers")
    begin = begin_matches[0].start()
    end = end_matches[0].end()
    return text[:begin], text[begin:end], text[end:]


def _decode_toml(raw: bytes) -> Tuple[str, bytes]:
    bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
    payload = raw[len(bom) :]
    if len(payload) > _MAX_CONFIG_BYTES:
        raise InstallerConflict("Codex config.toml exceeds the safety limit")
    try:
        return payload.decode("utf-8"), bom
    except UnicodeDecodeError as error:
        raise InstallerConflict("Codex config.toml is not valid UTF-8") from error


def _displaced_managed_otel_suffix(
    current: str,
    acceptable_blocks: Sequence[str],
    newline: str,
) -> Optional[str]:
    """Return bytes a host writer appended before the managed end marker.

    The recovery is deliberately narrower than TOML parsing: the recorder
    payload and marker must remain byte-exact, and the first semantic line
    displaced after that payload must close the `[otel]` table by opening a
    different TOML table. Any OTel definition anywhere in the displaced bytes
    remains a conflict.
    """

    marker = MANAGED_END + newline
    if not current.endswith(marker):
        return None
    for acceptable in acceptable_blocks:
        if not acceptable.endswith(marker):
            continue
        payload = acceptable[: -len(marker)]
        if not current.startswith(payload):
            continue
        displaced = current[len(payload) : -len(marker)]
        if not displaced or _contains_otel_definition(displaced):
            continue
        for line in displaced.splitlines():
            semantic = _toml_without_comments(line).strip()
            if not semantic:
                continue
            if _TOML_TABLE_HEADER.fullmatch(semantic):
                return displaced
            break
    return None


def _render_otel_config(
    original: bytes,
    *,
    listen_port: int,
    auth_token: str,
    previous_port: Optional[int],
    previous_token: Optional[str],
) -> bytes:
    text, bom = _decode_toml(original)
    newline = "\r\n" if "\r\n" in text else "\n"
    wanted = _managed_otel_block(listen_port, auth_token, newline)
    split = _split_managed_block(text)
    if split is None:
        if _contains_otel_definition(text):
            raise InstallerConflict("Codex config.toml already defines otel; refusing to overwrite it")
        prefix = text
        if prefix and not prefix.endswith(("\n", "\r")):
            prefix += newline
        if prefix and not prefix.endswith(newline * 2):
            prefix += newline
        result = prefix + wanted
        return bom + result.encode("utf-8")

    prefix, current, suffix = split
    if _contains_otel_definition(prefix) or _contains_otel_definition(suffix):
        raise InstallerConflict("Codex config.toml defines otel outside the managed telemetry block")
    acceptable_blocks = [wanted]
    if previous_port is not None and previous_token is not None:
        acceptable_blocks.append(_managed_otel_block(previous_port, previous_token, newline))
    if current in acceptable_blocks:
        displaced = ""
    else:
        displaced = _displaced_managed_otel_suffix(current, acceptable_blocks, newline)
    if displaced is None:
        raise InstallerConflict("managed Codex otel block was edited outside the installer")
    return bom + (prefix + wanted + displaced + suffix).encode("utf-8")


def _retire_otel_config(
    original: bytes,
    *,
    previous_port: int,
    previous_token: str,
) -> bytes:
    text, bom = _decode_toml(original)
    newline = "\r\n" if "\r\n" in text else "\n"
    split = _split_managed_block(text)
    if split is None:
        raise InstallerConflict("Codex config.toml has no managed telemetry block")
    prefix, current, suffix = split
    if _contains_otel_definition(prefix) or _contains_otel_definition(suffix):
        raise InstallerConflict("Codex config.toml defines otel outside the managed telemetry block")
    previous = _managed_otel_block(previous_port, previous_token, newline)
    if current == previous:
        displaced = ""
    else:
        displaced = _displaced_managed_otel_suffix(current, [previous], newline)
    if displaced is None:
        raise InstallerConflict("managed Codex otel block was edited outside the installer")
    return bom + (prefix + displaced + suffix).encode("utf-8")


def _file_state(path: Path) -> Dict[str, Any]:
    _assert_no_link_components(path)
    if not path.exists():
        return {"exists": False, "sha256": None, "mode": None}
    if _is_link_or_reparse(path) or not path.is_file():
        raise InstallerConflict("configuration target must be a regular file: {}".format(path))
    raw = path.read_bytes()
    return {
        "exists": True,
        "sha256": _sha256(raw),
        "mode": stat.S_IMODE(path.stat().st_mode) if os.name != "nt" else None,
    }


def _filesystem_identity(metadata: os.stat_result) -> Dict[str, int]:
    identity = {
        "device": int(metadata.st_dev),
        "inode": int(metadata.st_ino),
        "mode": int(stat.S_IMODE(metadata.st_mode)),
    }
    attributes = getattr(metadata, "st_file_attributes", None)
    if attributes is not None:
        identity["file_attributes"] = int(attributes)
    return identity


def _validate_filesystem_identity(value: Any, label: str) -> Dict[str, int]:
    required = {"device", "inode", "mode"}
    allowed = required | {"file_attributes"}
    if (
        not isinstance(value, dict)
        or not required.issubset(value)
        or not set(value).issubset(allowed)
        or any(
            isinstance(item, bool) or not isinstance(item, int) or item < 0
            for item in value.values()
        )
    ):
        raise InstallerConflict("{} identity is invalid".format(label))
    return {str(key): int(item) for key, item in value.items()}


def _directory_identity(path: Path, label: str) -> Dict[str, int]:
    _assert_no_link_components(path)
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise InstallerConflict("{} does not exist: {}".format(label, path)) from error
    if (
        stat.S_ISLNK(metadata.st_mode)
        or _is_link_or_reparse(path)
        or not stat.S_ISDIR(metadata.st_mode)
    ):
        raise InstallerConflict("{} must be one real directory: {}".format(label, path))
    return _filesystem_identity(metadata)


_MUTABLE_JOURNAL_FIELDS = {"status", "updated_at_utc", "error"}
_MUTABLE_ACTION_FIELDS = {
    "applied",
    "apply_state",
    "rollback_state",
    "blocked_reason",
}


def _action_after_mode(kind: str, before: Dict[str, Any]) -> Optional[int]:
    if os.name == "nt":
        return None
    if kind == "launcher":
        return 0o500
    if kind in {"settings", "otel-config", "claude-settings", "managed-targets"}:
        return 0o600
    return before["mode"] if before["mode"] is not None else 0o600


def _action_slot(path: Path, plan_id: str, index: int, role: str) -> Path:
    return path.parent / ".holyskills-recorder-{}-{:04d}-{}".format(
        plan_id,
        index,
        role,
    )


def _planned_action(
    *,
    index: int,
    plan_id: str,
    kind: str,
    name: str,
    path: Path,
    before: Dict[str, Any],
    after_sha256: str,
    after_mode: Optional[int],
    parent_identity: Dict[str, int],
) -> Dict[str, Any]:
    bytes_changed = not before["exists"] or before["sha256"] != after_sha256
    mode_changed = (
        os.name != "nt"
        and before["exists"]
        and before["mode"] != after_mode
    )
    changed = bytes_changed or mode_changed
    return {
        "id": "{:04d}-{}-{}".format(index, kind, name),
        "index": index,
        "kind": kind,
        "name": name,
        "path": str(path),
        "changed": changed,
        "before_exists": before["exists"],
        "before_sha256": before["sha256"],
        "before_mode": before["mode"],
        "after_mode": after_mode,
        "bytes_changed": bytes_changed,
        "mode_changed": mode_changed,
        "after_sha256": after_sha256,
        "namespace_protocol": "adjacent-no-replace-v1",
        "parent_path": str(path.parent),
        "parent_identity": copy.deepcopy(parent_identity),
        "stage_path": str(_action_slot(path, plan_id, index, "stage")),
        "before_path": str(_action_slot(path, plan_id, index, "before")),
        "after_path": str(_action_slot(path, plan_id, index, "after")),
        "applied": False,
        "apply_state": "pending" if changed else "unchanged",
        "rollback_state": "pending" if changed else "restored",
        "blocked_reason": None,
    }


def _build_action_topology(
    journal: Dict[str, Any],
    *,
    parent_identities: Optional[Sequence[Dict[str, int]]] = None,
) -> List[Dict[str, Any]]:
    plan_id = journal["plan_id"]
    target = journal["target"]
    rows: List[Tuple[str, str, Path, Dict[str, Any], str, Optional[int]]] = []
    install_before = target["install_before"]
    rows.append(
        (
            "install-tree",
            "runtime",
            Path(target["install_root"]),
            install_before,
            journal["source"]["payload_sha256"],
            None,
        )
    )

    def add_file(kind: str, name: str, spec: Dict[str, Any]) -> None:
        rows.append(
            (
                kind,
                name,
                Path(spec["path"]),
                spec["before"],
                spec["after_sha256"],
                _action_after_mode(kind, spec["before"]),
            )
        )

    add_file("settings", "recorder", target["settings"])
    add_file("launcher", "stable", target["launcher"])
    for home in journal["codex_homes"]:
        add_file("hooks", home["name"], home["hooks"])
        add_file("otel-config", home["name"], home["config"])
    for home in journal["claude_homes"]:
        add_file("claude-settings", home["name"], home["settings"])
    for home in journal["retired_codex_homes"]:
        add_file("retired-hooks", home["name"], home["hooks"])
        add_file("retired-otel-config", home["name"], home["config"])
    for home in journal["retired_claude_homes"]:
        add_file("retired-claude-settings", home["name"], home["settings"])
    add_file("managed-targets", "inventory", target["managed_targets"])
    if parent_identities is None:
        identities_by_parent: Dict[str, Dict[str, int]] = {}
        captured_identities: List[Dict[str, int]] = []
        for _kind, _name, path, _before, _after_sha256, _after_mode in rows:
            key = _normalized_path_text(path.parent)
            if key not in identities_by_parent:
                identities_by_parent[key] = _directory_identity(
                    path.parent,
                    "review-bound target parent",
                )
            captured_identities.append(identities_by_parent[key])
        parent_identities = captured_identities
    if len(parent_identities) != len(rows):
        raise InstallerConflict("transaction action parent identity count is invalid")
    return [
        _planned_action(
            index=index,
            plan_id=plan_id,
            kind=kind,
            name=name,
            path=path,
            before=before,
            after_sha256=after_sha256,
            after_mode=after_mode,
            parent_identity=_validate_filesystem_identity(
                parent_identities[index],
                "review-bound target parent",
            ),
        )
        for index, (kind, name, path, before, after_sha256, after_mode) in enumerate(rows)
    ]


def _immutable_action(action: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: copy.deepcopy(value)
        for key, value in action.items()
        if key not in _MUTABLE_ACTION_FIELDS
    }


def _immutable_plan_document(journal: Dict[str, Any]) -> Dict[str, Any]:
    document = {
        key: copy.deepcopy(value)
        for key, value in journal.items()
        if key not in _MUTABLE_JOURNAL_FIELDS
        and key not in {"plan_path", "plan_sha256"}
    }
    document["install_plan_schema_version"] = INSTALL_PLAN_SCHEMA_VERSION
    document["actions"] = [_immutable_action(action) for action in journal["actions"]]
    return document


def _read_or_empty(path: Path) -> bytes:
    return path.read_bytes() if path.exists() else b""


def _previous_handler(
    settings: Optional[Dict[str, Any]],
    state_root: Path,
    canonical_home: Path,
) -> Optional[Dict[str, Any]]:
    if settings is None:
        return None
    try:
        python = Path(settings["python_executable"])
        install = Path(settings["install_root"])
    except (KeyError, TypeError):
        return None
    version = _semantic_version(settings.get("recorder_version"), fullmatch=True)
    runtime_target = None
    if version is not None and version >= _RUNTIME_TARGET_MIN_VERSION:
        runtime_target = _runtime_target_ref(
            settings["auth_token"],
            "codex",
            canonical_home,
        )
    entry_root = (
        state_root
        if version is not None and version >= _STABLE_HOOK_LAUNCHER_MIN_VERSION
        else install
    )
    return _hook_handler(python, entry_root, state_root, runtime_target)


def _plan_home(
    name: str,
    home: Path,
    new_handler: Dict[str, Any],
    previous_handler: Optional[Dict[str, Any]],
    *,
    listen_port: int,
    auth_token: str,
    previous_settings: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if not _NAME_PATTERN.fullmatch(name):
        raise InstallerError("Codex home name must be a stable 1-64 character identifier: {}".format(name))
    _assert_no_link_components(home)
    if not home.is_dir():
        raise InstallerConflict(
            "Codex home must already exist as a real directory: {}".format(home)
        )
    hooks_path = home / "hooks.json"
    config_path = home / "config.toml"
    hooks_state = _file_state(hooks_path)
    config_state = _file_state(config_path)
    hooks_before = _read_or_empty(hooks_path)
    config_before = _read_or_empty(config_path)
    hooks_after = _render_hooks(hooks_before, new_handler, previous_handler)
    previous_port = previous_settings.get("listen_port") if previous_settings else None
    previous_token = previous_settings.get("auth_token") if previous_settings else None
    config_after = _render_otel_config(
        config_before,
        listen_port=listen_port,
        auth_token=auth_token,
        previous_port=previous_port if isinstance(previous_port, int) else None,
        previous_token=previous_token if isinstance(previous_token, str) else None,
    )
    return {
        "name": name,
        "home": str(home),
        "home_existed": home.exists(),
        "hooks": {
            "path": str(hooks_path),
            "before": hooks_state,
            "after_sha256": _sha256(hooks_after),
        },
        "config": {
            "path": str(config_path),
            "before": config_state,
            "after_sha256": _sha256(config_after),
        },
    }


def _plan_retired_codex_home(
    name: str,
    home: Path,
    previous_handler: Dict[str, Any],
    *,
    previous_port: int,
    previous_token: str,
) -> Dict[str, Any]:
    if not _NAME_PATTERN.fullmatch(name):
        raise InstallerError("Codex retirement name is invalid: {}".format(name))
    _assert_no_link_components(home)
    if not home.is_dir():
        raise InstallerConflict("retired Codex home is missing or not a directory: {}".format(home))
    hooks_path = home / "hooks.json"
    config_path = home / "config.toml"
    hooks_state = _file_state(hooks_path)
    config_state = _file_state(config_path)
    hooks_after = _retire_hooks(_read_or_empty(hooks_path), previous_handler)
    config_after = _retire_otel_config(
        _read_or_empty(config_path),
        previous_port=previous_port,
        previous_token=previous_token,
    )
    return {
        "name": name,
        "home": str(home),
        "home_existed": True,
        "hooks": {
            "path": str(hooks_path),
            "before": hooks_state,
            "after_sha256": _sha256(hooks_after),
        },
        "config": {
            "path": str(config_path),
            "before": config_state,
            "after_sha256": _sha256(config_after),
        },
    }


def _plan_retired_claude_home(
    name: str,
    home: Path,
    previous_handlers: Mapping[str, Dict[str, Any]],
    *,
    previous_port: int,
    previous_token: str,
    previous_version: Optional[str],
) -> Dict[str, Any]:
    if not _NAME_PATTERN.fullmatch(name):
        raise InstallerError("Claude retirement name is invalid: {}".format(name))
    _assert_no_link_components(home)
    if not home.is_dir():
        raise InstallerConflict("retired Claude home is missing or not a directory: {}".format(home))
    settings_path = home / "settings.json"
    settings_state = _file_state(settings_path)
    settings_after = _retire_claude_settings(
        _read_or_empty(settings_path),
        previous_handlers,
        previous_port=previous_port,
        previous_token=previous_token,
        previous_version=previous_version,
    )
    return {
        "name": name,
        "home": str(home),
        "home_existed": True,
        "settings": {
            "path": str(settings_path),
            "before": settings_state,
            "after_sha256": _sha256(settings_after),
        },
    }


def plan_install(
    source_root: Union[str, os.PathLike[str]],
    state_root: Union[str, os.PathLike[str]],
    codex_homes: Mapping[str, Union[str, os.PathLike[str]]],
    *,
    claude_homes: Optional[Mapping[str, Union[str, os.PathLike[str]]]] = None,
    retire_codex_homes: Optional[Mapping[str, Union[str, os.PathLike[str]]]] = None,
    retire_claude_homes: Optional[Mapping[str, Union[str, os.PathLike[str]]]] = None,
    claude_executable: Optional[Union[str, os.PathLike[str]]] = None,
    python_executable: Optional[Union[str, os.PathLike[str]]] = None,
    listen_port: Optional[int] = None,
    auth_token: Optional[str] = None,
    rotate_auth_token: bool = False,
    persist: bool = True,
) -> InstallPlan:
    """Create and optionally persist a fully bound installation plan.

    Home and retirement mappings are intentionally explicit
    name-to-absolute-path bindings: discovery and authorization belong to the
    caller.  Omission never implies retirement, and no default home is mutated.
    """

    source = _absolute_path(source_root, "source_root")
    state = _state_path(state_root)
    if _paths_overlap(source, state):
        raise InstallerConflict("source_root and state_root must not contain one another")
    if claude_homes is None:
        claude_homes = {}
    if retire_codex_homes is None:
        retire_codex_homes = {}
    if retire_claude_homes is None:
        retire_claude_homes = {}
    if not codex_homes and not claude_homes and not retire_codex_homes and not retire_claude_homes:
        raise InstallerError(
            "at least one explicitly named active or retired Codex or Claude home is required"
        )
    interpreter = _absolute_executable(python_executable or sys.executable)
    if claude_homes:
        verified_claude_executable, verified_claude_version = _probe_claude_runtime(
            claude_executable
        )
        claude_runtime: Optional[Dict[str, str]] = {
            "executable": str(verified_claude_executable),
            "observed_version": verified_claude_version,
            "required_minimum": ".".join(str(item) for item in CLAUDE_MINIMUM_VERSION),
        }
    else:
        claude_runtime = None

    digest = source_tree_digest(source)
    install_root = state / "installs" / RECORDER_VERSION
    _assert_no_link_components(install_root)
    install_exists = install_root.exists()
    if install_exists and _installed_tree_digest(install_root) != digest:
        raise InstallerConflict("installed version {} already exists with different bytes".format(RECORDER_VERSION))
    if install_exists and not _tree_is_read_only(install_root):
        raise InstallerConflict("installed version target exists but is not immutable")

    settings_path = state / "settings.json"
    _assert_no_link_components(settings_path)
    previous_settings = _load_existing_settings(settings_path)
    inventory_path = state / "managed-targets.json"
    _assert_no_link_components(inventory_path)
    inventory_state = _file_state(inventory_path)
    prior_targets = _load_managed_targets(
        inventory_path,
        source_root=source,
        state_root=state,
    )
    if previous_settings is None and prior_targets is not None:
        raise InstallerConflict("managed target inventory exists without recorder settings")
    if previous_settings is not None and prior_targets is None:
        prior_targets = _recover_managed_targets_from_transactions(
            state,
            previous_settings,
            source_root=source,
        )
        inventory_provenance = "recovered-applied-transaction-history"
    elif prior_targets is not None:
        inventory_provenance = "persisted-private-inventory"
    else:
        prior_targets = []
        inventory_provenance = "new-install"
    if not isinstance(rotate_auth_token, bool):
        raise InstallerError("rotate_auth_token must be a boolean")
    if rotate_auth_token and auth_token is not None:
        raise InstallerError("auth_token and rotate_auth_token are mutually exclusive")
    if auth_token is not None:
        _validate_token(auth_token)
    previous_version = previous_settings.get("recorder_version") if previous_settings else None
    is_version_change = bool(previous_settings and previous_version != RECORDER_VERSION)
    legacy_upgrade = bool(is_version_change and not _supports_receiver_retirement(previous_version))
    explicit_token_change = bool(
        previous_settings and auth_token is not None and auth_token != previous_settings["auth_token"]
    )
    credential_change = bool(previous_settings and (rotate_auth_token or explicit_token_change))
    rotate_port_by_default = bool(previous_settings and (legacy_upgrade or credential_change))
    if listen_port is None:
        if rotate_port_by_default:
            selected_port, port_selection_detail = _allocate_upgrade_port(previous_settings["listen_port"])
            if legacy_upgrade:
                port_provenance = "legacy-upgrade-port-rotation"
            else:
                port_provenance = "auth-rotation-port-rotation"
        elif previous_settings:
            selected_port = previous_settings["listen_port"]
            if is_version_change:
                port_provenance = "compatible-upgrade-port-preserved"
                port_selection_detail = "authenticated-retirement-supported"
            else:
                port_provenance = "persisted-existing"
                port_selection_detail = "persisted-existing"
        else:
            selected_port, port_provenance = _allocate_loopback_port()
            port_selection_detail = port_provenance
    else:
        selected_port = listen_port
        port_provenance = "caller-explicit"
        port_selection_detail = "caller-explicit"
    if not isinstance(selected_port, int) or isinstance(selected_port, bool) or not 1 <= selected_port <= 65535:
        raise InstallerError("listen_port must be an integer between 1 and 65535")
    if previous_settings and (legacy_upgrade or credential_change) and selected_port == previous_settings["listen_port"]:
        raise InstallerConflict(
            "credential changes and legacy upgrades require a distinct listen_port for portable handoff"
        )
    if rotate_auth_token:
        selected_token = secrets.token_hex(32)
        token_lifecycle = "rotated" if previous_settings else "generated-new"
    elif auth_token is None:
        selected_token = previous_settings["auth_token"] if previous_settings else secrets.token_hex(32)
        token_lifecycle = "preserved" if previous_settings else "generated-new"
    else:
        selected_token = _validate_token(auth_token)
        token_lifecycle = "caller-explicit"
    previous_semantic_version = _semantic_version(previous_version, fullmatch=True)
    stable_handler_migration = bool(
        previous_settings
        and (
            previous_semantic_version is None
            or previous_semantic_version < _STABLE_HOOK_LAUNCHER_MIN_VERSION
        )
    )
    binding_change = bool(
        previous_settings
        and (
            credential_change
            or selected_port != previous_settings["listen_port"]
            or str(interpreter) != previous_settings["python_executable"]
            or stable_handler_migration
        )
    )

    settings_value = _settings_value(
        install_root=install_root,
        state_root=state,
        python_executable=interpreter,
        listen_port=selected_port,
        auth_token=selected_token,
    )
    settings_after = _json_bytes(settings_value)
    launcher_path = state / "recorder.py"
    launcher_after = stable_launcher_bytes()
    launcher_state = _file_state(launcher_path)
    new_claude_handlers = _claude_hook_handlers(interpreter, state, state)
    old_claude_handlers = _previous_claude_handlers(previous_settings, state)

    homes: List[Dict[str, Any]] = []
    seen_paths: List[Path] = []
    for name in sorted(codex_homes):
        home = _absolute_path(codex_homes[name], "Codex home {}".format(name))
        if _paths_overlap(source, home) or _paths_overlap(state, home):
            raise InstallerConflict("Codex homes must be outside source and recorder state roots")
        if any(_paths_overlap(existing, home) for existing in seen_paths):
            raise InstallerError("Codex home paths must not duplicate or contain one another: {}".format(home))
        seen_paths.append(home)
        runtime_target = _runtime_target_ref(selected_token, "codex", home)
        new_handler = _hook_handler(
            interpreter,
            state,
            state,
            runtime_target,
        )
        old_handler = _previous_handler(previous_settings, state, home)
        homes.append(
            _plan_home(
                name,
                home,
                new_handler,
                old_handler,
                listen_port=selected_port,
                auth_token=selected_token,
                previous_settings=previous_settings,
            )
        )

    claude_home_specs: List[Dict[str, Any]] = []
    for name in sorted(claude_homes):
        home = _absolute_path(claude_homes[name], "Claude home {}".format(name))
        if _paths_overlap(source, home) or _paths_overlap(state, home):
            raise InstallerConflict("Claude homes must be outside source and recorder state roots")
        if any(_paths_overlap(existing, home) for existing in seen_paths):
            raise InstallerError("home paths must not duplicate or contain one another: {}".format(home))
        seen_paths.append(home)
        claude_home_specs.append(
            _plan_claude_home(
                name,
                home,
                new_claude_handlers,
                old_claude_handlers,
                listen_port=selected_port,
                auth_token=selected_token,
                previous_settings=previous_settings,
            )
        )

    requested_targets = [
        {"runtime": "codex", "name": home["name"], "home": home["home"]}
        for home in homes
    ] + [
        {"runtime": "claude", "name": home["name"], "home": home["home"]}
        for home in claude_home_specs
    ]
    requested_targets = _validate_managed_targets(
        requested_targets,
        source_root=source,
        state_root=state,
        label="requested managed targets",
    )
    retirement_requests: List[Dict[str, str]] = []
    for runtime_name, mapping, label in (
        ("codex", retire_codex_homes, "retired Codex home"),
        ("claude", retire_claude_homes, "retired Claude home"),
    ):
        for name in sorted(mapping):
            retirement_requests.append(
                {
                    "runtime": runtime_name,
                    "name": name,
                    "home": str(_absolute_path(mapping[name], "{} {}".format(label, name))),
                }
            )
    retirement_requests = _validate_managed_targets(
        retirement_requests,
        source_root=source,
        state_root=state,
        label="requested target retirements",
    )
    prior_by_key = {_target_key(target): target for target in prior_targets}
    requested_by_key = {_target_key(target): target for target in requested_targets}
    retired_by_key = {_target_key(target): target for target in retirement_requests}
    if set(requested_by_key).intersection(retired_by_key):
        raise InstallerConflict("a managed target cannot be active and retired in one transaction")
    for key, retirement in retired_by_key.items():
        prior = prior_by_key.get(key)
        if prior is None or prior != retirement:
            raise InstallerConflict(
                "target retirement must exactly match a previously managed runtime, name, and home"
            )
    if binding_change:
        missing = set(prior_by_key).difference(requested_by_key, retired_by_key)
        if missing:
            raise InstallerConflict(
                "receiver binding change omits previously managed Codex or Claude targets"
            )
    next_by_key = dict(prior_by_key)
    next_by_key.update(requested_by_key)
    for key in retired_by_key:
        del next_by_key[key]
    next_targets = _validate_managed_targets(
        list(next_by_key.values()),
        source_root=source,
        state_root=state,
        label="resulting managed target inventory",
    )
    inventory_after = _managed_targets_bytes(next_targets)

    if retirement_requests and previous_settings is None:
        raise InstallerConflict("target retirement requires an existing managed installation")
    if retirement_requests and (
        previous_settings is None or old_claude_handlers is None
    ):
        raise InstallerConflict("prior managed hook identity cannot be reconstructed")
    retired_codex_specs: List[Dict[str, Any]] = []
    retired_claude_specs: List[Dict[str, Any]] = []
    for retirement in retirement_requests:
        home = Path(retirement["home"])
        if retirement["runtime"] == "codex":
            old_handler = _previous_handler(previous_settings, state, home)
            if old_handler is None:
                raise InstallerConflict("prior managed Codex hook identity cannot be reconstructed")
            retired_codex_specs.append(
                _plan_retired_codex_home(
                    retirement["name"],
                    home,
                    old_handler,
                    previous_port=previous_settings["listen_port"],
                    previous_token=previous_settings["auth_token"],
                )
            )
        else:
            retired_claude_specs.append(
                _plan_retired_claude_home(
                    retirement["name"],
                    home,
                    old_claude_handlers,
                    previous_port=previous_settings["listen_port"],
                    previous_token=previous_settings["auth_token"],
                    previous_version=previous_settings.get("recorder_version"),
                )
            )

    # Planning provisions only recorder-owned scaffolding. Runtime homes must
    # already exist, which lets the reviewed plan bind every target parent to
    # one concrete filesystem identity before any managed target is mutated.
    _secure_directory(state)
    _secure_directory(state / "installs")
    transactions_root = state / "transactions"
    _secure_directory(transactions_root)
    plan_id = secrets.token_hex(16)
    transaction_directory = transactions_root / plan_id
    try:
        transaction_directory.mkdir(mode=0o700)
    except FileExistsError as error:
        raise InstallerConflict("new transaction identifier is already occupied") from error
    if os.name != "nt":
        os.chmod(str(transaction_directory), 0o700)
    transaction_identity = _directory_identity(
        transaction_directory,
        "transaction directory",
    )
    journal_path = transaction_directory / "journal.json"
    journal: Dict[str, Any] = {
        "journal_schema_version": JOURNAL_SCHEMA_VERSION,
        "plan_id": plan_id,
        "status": "planned",
        "created_at_utc": _utc_now(),
        "updated_at_utc": _utc_now(),
        "managed_id": MANAGED_ID,
        "recorder_version": RECORDER_VERSION,
        "source": {"root": str(source), "payload_sha256": digest},
        "target": {
            "state_root": str(state),
            "install_root": str(install_root),
            "install_before": {
                "exists": install_exists,
                "sha256": digest if install_exists else None,
                "mode": None,
            },
            "settings": {
                "path": str(settings_path),
                "before": _file_state(settings_path),
                "after_sha256": _sha256(settings_after),
            },
            "launcher": {
                "path": str(launcher_path),
                "before": launcher_state,
                "after_sha256": _sha256(launcher_after),
            },
            "managed_targets": {
                "path": str(inventory_path),
                "before": inventory_state,
                "before_targets": prior_targets,
                "after_sha256": _sha256(inventory_after),
                "before_provenance": inventory_provenance,
                "after": next_targets,
            },
        },
        "python_executable": str(interpreter),
        "claude_runtime": claude_runtime,
        "receiver": {
            "listen_host": "127.0.0.1",
            "listen_port": selected_port,
            "listen_port_provenance": port_provenance,
            "listen_port_selection_detail": port_selection_detail,
            "lifecycle_handoff": (
                "legacy-port-rotation"
                if legacy_upgrade
                else "credential-change-port-rotation"
                if credential_change
                else "authenticated-same-port-retirement"
                if is_version_change
                and previous_settings is not None
                and selected_port == previous_settings["listen_port"]
                else "settings-drift-port-change"
                if previous_settings is not None
                and selected_port != previous_settings["listen_port"]
                else "not-applicable"
            ),
            "auth_header": AUTH_HEADER,
            "auth_token_sha256": _sha256(selected_token.encode("ascii")),
            "auth_token_lifecycle": token_lifecycle,
            "managed_binding_change": binding_change,
        },
        "platform": _platform_info(),
        "codex_homes": homes,
        "claude_homes": claude_home_specs,
        "retired_codex_homes": retired_codex_specs,
        "retired_claude_homes": retired_claude_specs,
        "journal_path": str(journal_path),
        "transaction_identity": transaction_identity,
        "security": {
            "contains_auth_token": False,
            "posix_private_modes_enforced": os.name != "nt",
            "windows_acl_hardened": False,
            "windows_acl_note": "inherits containing-directory ACL; stdlib installer makes no ACL-hardening claim",
            "install_immutability": (
                "windows-readonly-attribute-plus-digest-enforcement-no-acl"
                if os.name == "nt"
                else "posix-no-write-mode-bits-plus-digest-enforcement"
            ),
        },
        "actions": [],
        "error": None,
    }
    journal["actions"] = _build_action_topology(journal)
    immutable_plan = _immutable_plan_document(journal)
    plan_digest = _sha256(_json_bytes(immutable_plan))
    journal["plan_path"] = str(journal_path.with_name("plan.json"))
    journal["plan_sha256"] = plan_digest
    plan = InstallPlan(
        journal=journal,
        auth_token=selected_token,
        immutable_plan=immutable_plan,
        plan_digest=plan_digest,
    )
    if persist:
        save_plan(plan)
    return plan


def _secure_directory(path: Path) -> None:
    _assert_no_link_components(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    _assert_no_link_components(path)
    if os.name != "nt":
        os.chmod(str(path), 0o700)


def _retryable_replace_error(error: OSError) -> bool:
    return os.name == "nt" and (getattr(error, "winerror", None) in _WINDOWS_RETRY_ERRORS or isinstance(error, PermissionError))


def _atomic_replace(source: Path, destination: Path, *, attempts: int = 8) -> None:
    for attempt in range(attempts):
        try:
            os.replace(str(source), str(destination))
            return
        except OSError as error:
            if not _retryable_replace_error(error) or attempt + 1 >= attempts:
                raise
            time.sleep(min(0.01 * (2**attempt), 0.16))


def _same_directory(first: Path, second: Path) -> bool:
    return os.path.normcase(os.path.abspath(str(first.parent))) == os.path.normcase(
        os.path.abspath(str(second.parent))
    )


def _posix_rename_with_flags(
    source: Path,
    destination: Path,
    *,
    directory_descriptor: int,
    linux_flags: int,
    macos_flags: int,
) -> None:
    """Invoke a flagged rename through one held parent directory."""

    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        try:
            rename = library.renameatx_np
        except AttributeError as error:
            raise InstallerError(
                "macOS atomic rename flags are unavailable in this runtime"
            ) from error
        rename.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        rename.restype = ctypes.c_int
        ctypes.set_errno(0)
        result = rename(
            directory_descriptor,
            os.fsencode(source.name),
            directory_descriptor,
            os.fsencode(destination.name),
            macos_flags,
        )
    elif sys.platform.startswith("linux"):
        try:
            rename = library.renameat2
        except AttributeError as error:
            raise InstallerError(
                "Linux atomic rename flags are unavailable in this runtime"
            ) from error
        rename.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        rename.restype = ctypes.c_int
        ctypes.set_errno(0)
        result = rename(
            directory_descriptor,
            os.fsencode(source.name),
            directory_descriptor,
            os.fsencode(destination.name),
            linux_flags,
        )
    else:
        raise InstallerError("atomic namespace mutation is unsupported on this POSIX host")
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(
            error_number,
            "{}: {} -> {}".format(
                os.strerror(error_number), source, destination
            ),
        )


def _windows_move_no_replace(source: Path, destination: Path) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    move = kernel32.MoveFileExW
    move.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32)
    move.restype = ctypes.c_int
    ctypes.set_last_error(0)  # type: ignore[attr-defined]
    # Omitting MOVEFILE_REPLACE_EXISTING is the no-overwrite guarantee.
    if not move(str(source), str(destination), 0x00000008):  # MOVEFILE_WRITE_THROUGH
        error_number = ctypes.get_last_error()  # type: ignore[attr-defined]
        raise ctypes.WinError(error_number)  # type: ignore[attr-defined]


def _windows_rename_handle_no_replace(
    handle: int,
    parent_handle: int,
    destination_name: str,
) -> None:
    """Rename the exact held file/directory to one unoccupied sibling name."""

    child = _windows_child_name(destination_name)

    class _ReplaceUnion(ctypes.Union):
        _fields_ = [
            ("replace_if_exists", ctypes.c_ubyte),
            ("flags", ctypes.c_uint32),
        ]

    class _FileRenameInformation(ctypes.Structure):
        _anonymous_ = ("replace",)
        _fields_ = [
            ("replace", _ReplaceUnion),
            ("root_directory", ctypes.c_void_p),
            ("file_name_length", ctypes.c_uint32),
            ("file_name", ctypes.c_wchar * 1),
        ]

    encoded = child.encode("utf-16-le")
    total_size = ctypes.sizeof(_FileRenameInformation) + len(encoded)
    storage = ctypes.create_string_buffer(total_size)
    information = ctypes.cast(
        storage,
        ctypes.POINTER(_FileRenameInformation),
    ).contents
    information.flags = 0  # ReplaceIfExists = FALSE
    information.root_directory = ctypes.c_void_p(parent_handle)
    information.file_name_length = len(encoded)
    ctypes.memmove(
        ctypes.addressof(storage) + _FileRenameInformation.file_name.offset,
        encoded,
        len(encoded),
    )

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    rename = kernel32.SetFileInformationByHandle
    rename.argtypes = (
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    )
    rename.restype = ctypes.c_int
    ctypes.set_last_error(0)  # type: ignore[attr-defined]
    if not rename(
        ctypes.c_void_p(handle),
        3,  # FileRenameInfo
        ctypes.byref(storage),
        total_size,
    ):
        error_number = int(ctypes.get_last_error())  # type: ignore[attr-defined]
        raise OSError(error_number, ctypes.FormatError(error_number))


def _publish_windows_stage_no_replace(
    plan: InstallPlan,
    action: Dict[str, Any],
    anchor: _DirectoryAnchor,
    *,
    mutation_guard: Optional[Callable[[], None]] = None,
) -> None:
    """Publish the exact reviewed stage object while its handle stays held."""

    if plan.windows_stage_bindings is None or anchor.windows_directory_handle is None:
        raise InstallerError("Windows stage or target-parent handle is not held")
    stage = Path(action["stage_path"])
    target = Path(action["path"])
    key = _normalized_path_text(stage)
    binding = plan.windows_stage_bindings.get(key)
    if binding is None:
        raise InstallerConflict("Windows prepared stage has no held publication binding")
    handle = int(binding["handle"])
    captured = dict(binding["identity"])
    _require_directory_anchor(anchor)
    if mutation_guard is not None:
        mutation_guard()
    try:
        _windows_rename_handle_no_replace(
            handle,
            anchor.windows_directory_handle,
            target.name,
        )
    except OSError as error:
        _raise_namespace_error("handle-bound atomic no-replace move", error)
    held = _windows_directory_handle_identity(handle)
    try:
        target_metadata = target.lstat()
    except FileNotFoundError as error:
        raise InstallerConflict(
            "handle-bound Windows publication has no destination occupant"
        ) from error
    target_identity = _filesystem_identity(target_metadata)
    if (
        held["device"] != captured["device"]
        or held["inode"] != captured["inode"]
        or target_identity["device"] != captured["device"]
        or target_identity["inode"] != captured["inode"]
    ):
        raise InstallerConflict(
            "handle-bound Windows publication changed or lost its stage identity"
        )
    source_slot_reoccupied = _lexical_exists(stage)
    _require_directory_anchor(anchor)
    # Once target and held-handle identities match, release the target handle
    # before reporting a newly occupied source slot. Otherwise recovery could
    # deadlock on this installer's own no-delete-share handle.
    _release_windows_stage_binding(plan, stage)
    if source_slot_reoccupied:
        raise InstallerDrift(
            "Windows stage source slot was reoccupied after exact publication"
        )


def _publish_prepared_stage_no_replace(
    plan: InstallPlan,
    action: Dict[str, Any],
    anchor: _DirectoryAnchor,
    *,
    mutation_guard: Optional[Callable[[], None]] = None,
) -> None:
    if os.name == "nt":  # pragma: no cover - native Windows CI
        _ensure_windows_stage_binding(plan, action)
        _publish_windows_stage_no_replace(
            plan,
            action,
            anchor,
            mutation_guard=mutation_guard,
        )
        return
    _atomic_move_no_replace(
        Path(action["stage_path"]),
        Path(action["path"]),
        anchor=anchor,
        mutation_guard=mutation_guard,
    )


def _namespace_error_code(error: OSError) -> int:
    if os.name == "nt":
        return int(getattr(error, "winerror", 0) or getattr(error, "errno", 0) or 0)
    return int(getattr(error, "errno", 0) or 0)


def _raise_namespace_error(operation: str, error: OSError) -> None:
    code = _namespace_error_code(error)
    if (os.name == "nt" and code in {80, 183}) or (
        os.name != "nt" and code in {errno.EEXIST, errno.ENOTEMPTY}
    ):
        raise InstallerDrift(
            "{} refused because another writer occupied the destination".format(operation)
        ) from error
    if (os.name == "nt" and code in {2, 3}) or (
        os.name != "nt" and code == errno.ENOENT
    ):
        raise InstallerDrift(
            "{} refused because a required source or target disappeared".format(operation)
        ) from error
    unsupported = {errno.EINVAL, errno.EXDEV, errno.ENOSYS}
    if hasattr(errno, "ENOTSUP"):
        unsupported.add(errno.ENOTSUP)
    if hasattr(errno, "EOPNOTSUPP"):
        unsupported.add(errno.EOPNOTSUPP)
    if (os.name == "nt" and code in {1, 17, 50}) or (
        os.name != "nt" and code in unsupported
    ):
        raise InstallerError(
            "{} is not supported by the target filesystem; no unsafe fallback was used".format(
                operation
            )
        ) from error
    raise InstallerError("{} failed without overwriting the destination".format(operation)) from error


def _atomic_move_no_replace(
    source: Path,
    destination: Path,
    *,
    anchor: _DirectoryAnchor,
    mutation_guard: Optional[Callable[[], None]] = None,
) -> None:
    """Move adjacent names through one held reviewed parent identity."""

    if not _same_directory(source, destination):
        raise InstallerConflict("atomic no-replace moves require one parent directory")
    if (
        _normalized_path_text(source.parent) != _normalized_path_text(anchor.path)
        or _normalized_path_text(destination.parent) != _normalized_path_text(anchor.path)
        or source.name in {"", ".", ".."}
        or destination.name in {"", ".", ".."}
    ):
        raise InstallerConflict("atomic no-replace move escaped its held target parent")
    _require_directory_anchor(anchor)
    if mutation_guard is not None:
        mutation_guard()
    try:
        if os.name == "nt":
            _windows_move_no_replace(source, destination)
        else:
            if anchor.descriptor is None:
                raise InstallerError("POSIX no-replace move lacks a held directory descriptor")
            _posix_rename_with_flags(
                source,
                destination,
                directory_descriptor=anchor.descriptor,
                linux_flags=0x1,  # RENAME_NOREPLACE
                macos_flags=0x4,  # RENAME_EXCL
            )
    except OSError as error:
        _raise_namespace_error("atomic no-replace move", error)
    if anchor.descriptor is not None:
        os.fsync(anchor.descriptor)
    else:
        _fsync_directory(anchor.path)
    _require_directory_anchor(anchor)


def _atomic_write(
    path: Path,
    data: bytes,
    *,
    mode: int = 0o600,
) -> None:
    """Atomically write installer-private state, never a managed runtime target."""

    _assert_no_link_components(path)
    if path.parent.exists():
        _assert_no_link_components(path.parent)
        if not path.parent.is_dir():
            raise InstallerConflict("write parent is not a directory: {}".format(path.parent))
    else:
        _secure_directory(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(prefix="." + path.name + ".tmp-", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        if os.name != "nt":
            os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        _atomic_replace(temporary, path)
        _fsync_directory(path.parent)
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def _write_private_once(path: Path, data: bytes, *, mode: int = 0o600) -> None:
    """Create one immutable private transaction file without replacement."""

    _secure_directory(path.parent)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(str(path), flags, mode)
    try:
        if os.name != "nt":
            os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        descriptor = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _held_child_name(name: str) -> str:
    if not name or Path(name).name != name or name in {".", ".."}:
        raise InstallerError("unsafe held-directory child name")
    return name


def _windows_child_name(name: str) -> str:
    """Reject Win32/NT child spellings that can escape or alias a slot."""

    child = _held_child_name(name)
    if (
        any(character in child for character in ("\x00", "\\", "/", ":"))
        or child.endswith((".", " "))
    ):
        raise InstallerConflict("unsafe Windows held-directory child name")
    return child


def _read_private_held(
    anchor: _DirectoryAnchor,
    name: str,
    *,
    maximum: int = _MAX_CONFIG_BYTES,
) -> bytes:
    """Read one transaction child through its held directory identity."""

    child = _held_child_name(name)
    _require_directory_anchor(anchor)
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        if anchor.descriptor is not None:
            descriptor = os.open(child, flags, dir_fd=anchor.descriptor)
        elif os.name == "nt":  # pragma: no cover - native Windows CI
            descriptor = _open_windows_regular_file_descriptor(
                anchor.path / child,
                require_single_link=True,
            )
        else:
            descriptor = os.open(str(anchor.path / child), flags)
    except FileNotFoundError as error:
        raise InstallerError(
            "transaction file does not exist: {}".format(anchor.path / child)
        ) from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise InstallerConflict(
                "transaction file must be one real regular file: {}".format(
                    anchor.path / child
                )
            )
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            raw = stream.read(maximum + 1)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(raw) > maximum:
        raise InstallerConflict(
            "transaction file exceeds the {} byte safety limit".format(maximum)
        )
    _require_directory_anchor(anchor)
    return raw


def _write_private_once_held(
    anchor: _DirectoryAnchor,
    name: str,
    data: bytes,
    *,
    mode: int = 0o600,
) -> None:
    child = _held_child_name(name)
    _require_directory_anchor(anchor)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if anchor.descriptor is not None:
        descriptor = os.open(child, flags, mode, dir_fd=anchor.descriptor)
    else:
        descriptor = os.open(str(anchor.path / child), flags, mode)
    try:
        if os.name != "nt":
            os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if anchor.descriptor is not None:
        os.fsync(anchor.descriptor)
    else:
        _fsync_directory(anchor.path)
    _require_directory_anchor(anchor)


def _atomic_write_held(
    anchor: _DirectoryAnchor,
    name: str,
    data: bytes,
    *,
    mode: int = 0o600,
    allow_detached: bool = False,
) -> None:
    """Replace mutable private state through a held transaction directory."""

    child = _held_child_name(name)
    detached_via_descriptor = allow_detached and anchor.descriptor is not None
    _require_directory_anchor(anchor, require_path=not detached_via_descriptor)
    if anchor.descriptor is None:
        # Native Windows holds a no-delete-share directory handle, so the
        # transaction pathname cannot be renamed or replaced during this call.
        _atomic_write(anchor.path / child, data, mode=mode)
        _require_directory_anchor(anchor)
        return
    temporary = ".{}.tmp-{}".format(child, secrets.token_hex(16))
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, mode, dir_fd=anchor.descriptor)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.rename(
            temporary,
            child,
            src_dir_fd=anchor.descriptor,
            dst_dir_fd=anchor.descriptor,
        )
        os.fsync(anchor.descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=anchor.descriptor)
        except FileNotFoundError:
            pass
    _require_directory_anchor(anchor, require_path=not detached_via_descriptor)


@contextmanager
def _lock_transaction_directory(
    transaction: Path,
    expected_identity: Optional[Dict[str, int]] = None,
) -> Iterator[_DirectoryAnchor]:
    expected = expected_identity or _directory_identity(
        transaction,
        "transaction directory",
    )
    with _lock_directory(
        transaction,
        expected,
        lock_name=_TRANSACTION_LOCK_NAME,
    ) as anchor:
        yield anchor


def save_plan(plan: InstallPlan) -> Path:
    """Persist immutable reviewed topology, mutable journal, and token sidecar."""

    _validate_plan_integrity(plan)
    journal_path = plan.journal_path
    secret = {"plan_id": plan.journal["plan_id"], "auth_token": _validate_token(plan.auth_token)}
    plan_bytes = _json_bytes(plan.immutable_plan)
    if _sha256(plan_bytes) != plan.plan_digest:
        raise InstallerConflict("immutable install plan digest changed before persistence")
    with _lock_transaction_directory(
        journal_path.parent,
        plan.journal["transaction_identity"],
    ) as anchor:
        _write_private_once_held(
            anchor,
            plan.secret_path.name,
            _json_bytes(secret),
            mode=0o600,
        )
        _write_private_once_held(
            anchor,
            plan.plan_path.name,
            plan_bytes,
            mode=0o600,
        )
        _write_private_once_held(
            anchor,
            journal_path.name,
            _json_bytes(plan.journal),
            mode=0o600,
        )
    return journal_path


def _load_plan_held(
    path: Path,
    expected_plan_digest: str,
    anchor: _DirectoryAnchor,
) -> InstallPlan:
    if path.parent != anchor.path or path.name != "journal.json":
        raise InstallerConflict("transaction journal is not the held journal child")
    journal_raw = _read_private_held(anchor, path.name)
    journal = _load_json_object(journal_raw, "transaction journal")
    if journal_raw != _json_bytes(journal):
        raise InstallerConflict("transaction journal bytes are not canonical")
    if journal.get("journal_schema_version") != JOURNAL_SCHEMA_VERSION:
        raise InstallerError("unsupported transaction journal schema")
    if journal.get("journal_path") != str(path):
        raise InstallerConflict("transaction journal path does not match its bound path")
    _validate_journal_bindings(journal)
    expected_transaction_identity = _validate_filesystem_identity(
        journal.get("transaction_identity"),
        "transaction directory",
    )
    if anchor.identity != expected_transaction_identity:
        raise InstallerTransactionIdentityConflict(
            "held transaction directory identity differs from the reviewed transaction"
        )
    _require_directory_anchor(anchor)
    plan_path = path.with_name("plan.json")
    _bound_path(journal.get("plan_path"), plan_path, "immutable plan path")
    plan_raw = _read_private_held(anchor, plan_path.name)
    immutable_plan = _load_json_object(plan_raw, "immutable install plan")
    if plan_raw != _json_bytes(immutable_plan):
        raise InstallerConflict("immutable install plan bytes are not canonical")
    plan_digest = _sha256(plan_raw)
    bound_digest = journal.get("plan_sha256")
    if not isinstance(bound_digest, str) or not _LOWER_HEX_64.fullmatch(bound_digest):
        raise InstallerConflict("transaction journal immutable plan digest is invalid")
    if plan_digest != bound_digest:
        raise InstallerConflict("immutable install plan digest does not match the journal")
    if not isinstance(expected_plan_digest, str) or not _LOWER_HEX_64.fullmatch(
        expected_plan_digest
    ):
        raise InstallerConflict("expected install plan digest is invalid")
    if plan_digest != expected_plan_digest:
        raise InstallerConflict("immutable install plan digest does not match review")
    secret_raw = _read_private_held(anchor, "plan-secret.json", maximum=4096)
    secret = _load_json_object(
        secret_raw,
        "transaction token sidecar",
        maximum=4096,
    )
    if secret_raw != _json_bytes(secret):
        raise InstallerConflict("transaction token sidecar bytes are not canonical")
    if secret.get("plan_id") != journal.get("plan_id"):
        raise InstallerConflict("transaction token sidecar belongs to a different plan")
    token = _validate_token(secret.get("auth_token"))
    if _sha256(token.encode("ascii")) != journal.get("receiver", {}).get("auth_token_sha256"):
        raise InstallerConflict("transaction token sidecar digest does not match the journal")
    plan = InstallPlan(
        journal=journal,
        auth_token=token,
        immutable_plan=immutable_plan,
        plan_digest=plan_digest,
    )
    _validate_plan_integrity(plan, expected_plan_digest=expected_plan_digest)
    _require_directory_anchor(anchor)
    return plan


def load_plan(
    journal_path: Union[str, os.PathLike[str]],
    expected_plan_digest: str,
) -> InstallPlan:
    path = _absolute_path(journal_path, "journal_path")
    with _lock_transaction_directory(path.parent) as anchor:
        return _load_plan_held(path, expected_plan_digest, anchor)


def _coerce_plan(
    value: Union[InstallPlan, str, os.PathLike[str]],
    *,
    expected_plan_digest: Optional[str] = None,
) -> InstallPlan:
    if isinstance(value, InstallPlan):
        plan = value
    else:
        if expected_plan_digest is None:
            raise InstallerConflict(
                "a reviewed plan digest is required when loading a transaction path"
            )
        plan = load_plan(value, expected_plan_digest=expected_plan_digest)
    _validate_plan_integrity(plan, expected_plan_digest=expected_plan_digest)
    return plan


@contextmanager
def _locked_operation_plan(
    value: Union[InstallPlan, str, os.PathLike[str]],
    *,
    expected_plan_digest: Optional[str],
) -> Iterator[InstallPlan]:
    if isinstance(value, InstallPlan):
        _validate_plan_integrity(value, expected_plan_digest=expected_plan_digest)
        digest = expected_plan_digest or value.plan_digest
        if not isinstance(digest, str):
            raise InstallerConflict("in-memory transaction has no reviewed plan digest")
        journal_path = _absolute_path(value.journal_path, "journal_path")
        expected_transaction_identity = value.journal["transaction_identity"]
    else:
        if expected_plan_digest is None:
            raise InstallerConflict(
                "a reviewed plan digest is required when loading a transaction path"
            )
        digest = expected_plan_digest
        journal_path = _absolute_path(value, "journal_path")
        expected_transaction_identity = None
    with _lock_transaction_directory(
        journal_path.parent,
        expected_transaction_identity,
    ) as transaction_anchor:
        loaded = _load_plan_held(journal_path, digest, transaction_anchor)
        if isinstance(value, InstallPlan):
            if (
                value.plan_digest != loaded.plan_digest
                or value.immutable_plan != loaded.immutable_plan
                or value.auth_token != loaded.auth_token
            ):
                raise InstallerConflict(
                    "in-memory transaction differs from its held persisted plan"
                )
            value.journal = loaded.journal
            plan = value
        else:
            plan = loaded
        plan.transaction_anchor = transaction_anchor
        plan.allow_detached_transaction = False
        try:
            yield plan
        finally:
            plan.parent_anchors = None
            plan.transaction_anchor = None
            plan.allow_detached_transaction = False


@contextmanager
def _held_target_parents(plan: InstallPlan) -> Iterator[None]:
    with _lock_action_parents(plan.journal["actions"]) as anchors:
        plan.parent_anchors = anchors
        plan.windows_stage_bindings = {}
        try:
            yield
        finally:
            bindings = plan.windows_stage_bindings or {}
            plan.windows_stage_bindings = None
            for binding in list(bindings.values()):
                _close_windows_stage_binding(binding)
            plan.parent_anchors = None


def _validate_plan_integrity(
    plan: InstallPlan,
    *,
    expected_plan_digest: Optional[str] = None,
) -> None:
    _validate_journal_bindings(plan.journal)
    if not isinstance(plan.immutable_plan, dict):
        raise InstallerConflict("transaction has no immutable reviewed install plan")
    raw = _json_bytes(plan.immutable_plan)
    digest = _sha256(raw)
    if plan.plan_digest != digest or plan.journal.get("plan_sha256") != digest:
        raise InstallerConflict("immutable install plan digest binding changed")
    if expected_plan_digest is not None and digest != expected_plan_digest:
        raise InstallerConflict("immutable install plan digest does not match review")
    if plan.immutable_plan.get("install_plan_schema_version") != INSTALL_PLAN_SCHEMA_VERSION:
        raise InstallerConflict("unsupported immutable install plan schema")
    if _immutable_plan_document(plan.journal) != plan.immutable_plan:
        raise InstallerConflict("mutable journal topology differs from the reviewed install plan")


def _normalized_path_text(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def _bound_path(actual: Any, expected: Path, label: str) -> None:
    if not isinstance(actual, str) or _normalized_path_text(Path(actual)) != _normalized_path_text(expected):
        raise InstallerConflict("transaction journal has an invalid {} binding".format(label))


def _validate_journal_bindings(journal: Dict[str, Any]) -> None:
    """Reject path substitution in a persisted transaction journal."""

    try:
        plan_id = journal["plan_id"]
        version = journal["recorder_version"]
        target = journal["target"]
        state = Path(target["state_root"])
        source = Path(journal["source"]["root"])
        homes = journal["codex_homes"]
    except (KeyError, TypeError) as error:
        raise InstallerConflict("transaction journal is missing required bindings") from error
    if not isinstance(plan_id, str) or not re.fullmatch(r"[0-9a-f]{32}", plan_id):
        raise InstallerConflict("transaction journal plan_id is invalid")
    if version != RECORDER_VERSION:
        raise InstallerConflict("transaction journal recorder version does not match this installer")
    if not state.is_absolute():
        raise InstallerConflict("transaction journal state_root is not absolute")
    if not source.is_absolute() or _paths_overlap(source, state):
        raise InstallerConflict("transaction journal source/state binding is invalid")
    _bound_path(target.get("install_root"), state / "installs" / version, "install root")
    install_before = target.get("install_before")
    if (
        not isinstance(install_before, dict)
        or set(install_before) != {"exists", "sha256", "mode"}
        or not isinstance(install_before.get("exists"), bool)
        or install_before.get("mode") is not None
        or (
            install_before["exists"]
            and install_before.get("sha256") != journal.get("source", {}).get("payload_sha256")
        )
        or (
            not install_before["exists"]
            and install_before.get("sha256") is not None
        )
    ):
        raise InstallerConflict("transaction journal install-tree prior state is invalid")
    settings = target.get("settings")
    launcher = target.get("launcher")
    managed_targets = target.get("managed_targets")
    if not isinstance(settings, dict):
        raise InstallerConflict("transaction journal settings binding is invalid")
    if not isinstance(launcher, dict):
        raise InstallerConflict("transaction journal launcher binding is invalid")
    if not isinstance(managed_targets, dict):
        raise InstallerConflict("transaction journal managed target binding is invalid")
    _bound_path(settings.get("path"), state / "settings.json", "settings path")
    _bound_path(launcher.get("path"), state / "recorder.py", "launcher path")
    _bound_path(
        managed_targets.get("path"),
        state / "managed-targets.json",
        "managed target inventory path",
    )
    inventory_after = _validate_managed_targets(
        managed_targets.get("after"),
        source_root=source,
        state_root=state,
        label="journal managed target inventory",
    )
    if managed_targets.get("after_sha256") != _sha256(_managed_targets_bytes(inventory_after)):
        raise InstallerConflict("transaction journal managed target digest is invalid")
    inventory_before = _validate_managed_targets(
        managed_targets.get("before_targets"),
        source_root=source,
        state_root=state,
        label="journal prior managed target inventory",
    )
    before_file = managed_targets.get("before")
    if not isinstance(before_file, dict) or set(before_file) != {"exists", "sha256", "mode"}:
        raise InstallerConflict("transaction journal prior inventory file state is invalid")
    if before_file.get("exists") and before_file.get("sha256") != _sha256(
        _managed_targets_bytes(inventory_before)
    ):
        raise InstallerConflict("transaction journal prior inventory digest is invalid")
    if managed_targets.get("before_provenance") not in {
        "new-install",
        "persisted-private-inventory",
        "recovered-applied-transaction-history",
    }:
        raise InstallerConflict("transaction journal managed target provenance is invalid")
    _bound_path(
        journal.get("journal_path"),
        state / "transactions" / plan_id / "journal.json",
        "journal path",
    )
    _validate_filesystem_identity(
        journal.get("transaction_identity"),
        "transaction directory",
    )
    _bound_path(
        journal.get("plan_path"),
        state / "transactions" / plan_id / "plan.json",
        "immutable plan path",
    )
    if not isinstance(journal.get("plan_sha256"), str) or not _LOWER_HEX_64.fullmatch(
        journal["plan_sha256"]
    ):
        raise InstallerConflict("transaction journal immutable plan digest is invalid")
    claude_homes = journal.get("claude_homes", [])
    retired_codex_homes = journal.get("retired_codex_homes", [])
    retired_claude_homes = journal.get("retired_claude_homes", [])
    if not all(
        isinstance(value, list)
        for value in (homes, claude_homes, retired_codex_homes, retired_claude_homes)
    ):
        raise InstallerConflict("transaction journal home bindings are invalid")
    if not homes and not claude_homes and not retired_codex_homes and not retired_claude_homes:
        raise InstallerConflict(
            "transaction journal must bind at least one active or retired Codex or Claude home"
        )
    claude_runtime = journal.get("claude_runtime")
    if claude_homes:
        if not isinstance(claude_runtime, dict) or set(claude_runtime) != {
            "executable",
            "observed_version",
            "required_minimum",
        }:
            raise InstallerConflict("transaction journal Claude runtime proof is invalid")
        executable = Path(str(claude_runtime.get("executable", "")))
        observed_version = _semantic_version(
            claude_runtime.get("observed_version"), fullmatch=True
        )
        if (
            not executable.is_absolute()
            or observed_version is None
            or observed_version < CLAUDE_MINIMUM_VERSION
            or claude_runtime.get("required_minimum")
            != ".".join(str(item) for item in CLAUDE_MINIMUM_VERSION)
        ):
            raise InstallerConflict("transaction journal Claude runtime proof is invalid")
    elif claude_runtime is not None:
        raise InstallerConflict("transaction journal has an unbound Claude runtime proof")
    names = set()
    paths: List[Path] = []

    def _bound_home_path(home: Dict[str, Any], label: str) -> Path:
        name = home.get("name")
        if not isinstance(name, str) or not _NAME_PATTERN.fullmatch(name) or (label, name) in names:
            raise InstallerConflict("transaction journal {} home name is invalid or duplicated".format(label))
        names.add((label, name))
        home_path = Path(home.get("home", ""))
        if not home_path.is_absolute():
            raise InstallerConflict("transaction journal {} home path is not absolute".format(label))
        if _paths_overlap(source, home_path) or _paths_overlap(state, home_path):
            raise InstallerConflict("transaction journal {} home overlaps source or state".format(label))
        if any(_paths_overlap(existing, home_path) for existing in paths):
            raise InstallerConflict("transaction journal home paths overlap")
        paths.append(home_path)
        return home_path

    for home in homes:
        if not isinstance(home, dict):
            raise InstallerConflict("transaction journal Codex home binding is invalid")
        home_path = _bound_home_path(home, "Codex")
        hooks = home.get("hooks")
        config = home.get("config")
        if not isinstance(hooks, dict) or not isinstance(config, dict):
            raise InstallerConflict("transaction journal Codex file binding is invalid")
        _bound_path(hooks.get("path"), home_path / "hooks.json", "hooks path")
        _bound_path(config.get("path"), home_path / "config.toml", "config path")
    for home in claude_homes:
        if not isinstance(home, dict):
            raise InstallerConflict("transaction journal Claude home binding is invalid")
        home_path = _bound_home_path(home, "Claude")
        claude_settings = home.get("settings")
        if not isinstance(claude_settings, dict):
            raise InstallerConflict("transaction journal Claude file binding is invalid")
        _bound_path(claude_settings.get("path"), home_path / "settings.json", "Claude settings path")
    for home in retired_codex_homes:
        if not isinstance(home, dict):
            raise InstallerConflict("transaction journal retired Codex home binding is invalid")
        home_path = _bound_home_path(home, "Retired Codex")
        hooks = home.get("hooks")
        config = home.get("config")
        if not isinstance(hooks, dict) or not isinstance(config, dict):
            raise InstallerConflict("transaction journal retired Codex file binding is invalid")
        _bound_path(hooks.get("path"), home_path / "hooks.json", "retired hooks path")
        _bound_path(config.get("path"), home_path / "config.toml", "retired config path")
    for home in retired_claude_homes:
        if not isinstance(home, dict):
            raise InstallerConflict("transaction journal retired Claude home binding is invalid")
        home_path = _bound_home_path(home, "Retired Claude")
        claude_settings = home.get("settings")
        if not isinstance(claude_settings, dict):
            raise InstallerConflict("transaction journal retired Claude file binding is invalid")
        _bound_path(
            claude_settings.get("path"),
            home_path / "settings.json",
            "retired Claude settings path",
        )

    inventory_by_key = {_target_key(target_record): target_record for target_record in inventory_after}
    for runtime_name, active_homes in (("codex", homes), ("claude", claude_homes)):
        for home in active_homes:
            key = (runtime_name, _normalized_path_text(Path(home["home"])))
            if inventory_by_key.get(key) != {
                "runtime": runtime_name,
                "name": home["name"],
                "home": str(Path(home["home"])),
            }:
                raise InstallerConflict("active home is missing from managed target inventory")
    for runtime_name, retired_homes in (
        ("codex", retired_codex_homes),
        ("claude", retired_claude_homes),
    ):
        for home in retired_homes:
            key = (runtime_name, _normalized_path_text(Path(home["home"])))
            if key in inventory_by_key:
                raise InstallerConflict("retired home remains in managed target inventory")
    expected_inventory = {_target_key(target_record): target_record for target_record in inventory_before}
    for runtime_name, active_homes in (("codex", homes), ("claude", claude_homes)):
        for home in active_homes:
            record = {
                "runtime": runtime_name,
                "name": home["name"],
                "home": str(Path(home["home"])),
            }
            expected_inventory[_target_key(record)] = record
    for runtime_name, retired_homes in (
        ("codex", retired_codex_homes),
        ("claude", retired_claude_homes),
    ):
        for home in retired_homes:
            record = {
                "runtime": runtime_name,
                "name": home["name"],
                "home": str(Path(home["home"])),
            }
            key = _target_key(record)
            if expected_inventory.get(key) != record:
                raise InstallerConflict("retirement is not bound to the prior managed target inventory")
            del expected_inventory[key]
    expected_after = sorted(
        expected_inventory.values(),
        key=lambda item: (item["runtime"], item["name"], item["home"]),
    )
    if expected_after != inventory_after:
        raise InstallerConflict("managed target inventory update is not transactionally derived")
    binding_change = journal.get("receiver", {}).get("managed_binding_change")
    if not isinstance(binding_change, bool):
        raise InstallerConflict("transaction journal managed binding-change flag is invalid")
    if binding_change:
        covered = {
            (runtime_name, _normalized_path_text(Path(home["home"])))
            for runtime_name, home_list in (
                ("codex", homes),
                ("claude", claude_homes),
                ("codex", retired_codex_homes),
                ("claude", retired_claude_homes),
            )
            for home in home_list
        }
        if set(_target_key(target_record) for target_record in inventory_before).difference(covered):
            raise InstallerConflict(
                "binding-change journal omits a previously managed target"
            )

    allowed_statuses = {
        "planned",
        "applying",
        "applied",
        "apply-failed-rolling-back",
        "apply-failed-rolled-back",
        "apply-failed-rollback-blocked",
        "rolling-back",
        "rollback-blocked",
        "rolled-back",
    }
    if journal.get("status") not in allowed_statuses:
        raise InstallerConflict("transaction journal status is invalid")
    actions = journal.get("actions")
    if not isinstance(actions, list):
        raise InstallerConflict("transaction journal action topology is invalid")
    parent_identities: List[Dict[str, int]] = []
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            raise InstallerConflict(
                "transaction journal action {} is invalid".format(index)
            )
        path = Path(str(action.get("path", "")))
        parent = Path(str(action.get("parent_path", "")))
        if not path.is_absolute() or not parent.is_absolute() or path.parent != parent:
            raise InstallerConflict(
                "transaction journal action {} target parent is invalid".format(index)
            )
        for field in ("stage_path", "before_path", "after_path"):
            artifact = Path(str(action.get(field, "")))
            if not artifact.is_absolute() or artifact.parent != parent:
                raise InstallerConflict(
                    "transaction journal action {} artifact parent is invalid".format(index)
                )
        parent_identities.append(
            _validate_filesystem_identity(
                action.get("parent_identity"),
                "transaction action parent",
            )
        )
    expected_actions = _build_action_topology(
        journal,
        parent_identities=parent_identities,
    )
    if len(actions) != len(expected_actions):
        raise InstallerConflict("transaction journal action count differs from its bound topology")
    allowed_apply_states = {
        "pending",
        "preparing",
        "prepared",
        "capture-intent",
        "captured",
        "publish-intent",
        "applied",
        "unchanged",
        "conflict-restored",
        "blocked",
    }
    allowed_rollback_states = {
        "pending",
        "capture-intent",
        "captured",
        "restore-intent",
        "restored",
        "blocked",
    }
    for index, (action, expected_action) in enumerate(zip(actions, expected_actions)):
        if not isinstance(action, dict) or _immutable_action(action) != _immutable_action(
            expected_action
        ):
            raise InstallerConflict(
                "transaction journal action {} differs from its bound topology".format(index)
            )
        if not isinstance(action.get("applied"), bool):
            raise InstallerConflict("transaction journal action applied state is invalid")
        if action.get("apply_state") not in allowed_apply_states:
            raise InstallerConflict("transaction journal action apply state is invalid")
        if action.get("rollback_state") not in allowed_rollback_states:
            raise InstallerConflict("transaction journal action rollback state is invalid")
        reason = action.get("blocked_reason")
        if reason is not None and (
            not isinstance(reason, str)
            or not reason
            or len(reason) > 128
            or any(ord(character) < 32 for character in reason)
        ):
            raise InstallerConflict("transaction journal action blocked reason is invalid")


class _DirectoryAnchor:
    """Held identity and cooperative lock for one reviewed directory."""

    __slots__ = (
        "path",
        "identity",
        "descriptor",
        "stream",
        "windows_directory_handle",
    )

    def __init__(self, path: Path, identity: Dict[str, int]) -> None:
        self.path = path
        self.identity = identity
        self.descriptor: Optional[int] = None
        self.stream: Any = None
        self.windows_directory_handle: Optional[int] = None


def _windows_directory_handle_identity(handle: int) -> Dict[str, int]:
    class _ByHandleFileInformation(ctypes.Structure):
        _fields_ = [
            ("file_attributes", ctypes.c_uint32),
            ("creation_time_low", ctypes.c_uint32),
            ("creation_time_high", ctypes.c_uint32),
            ("access_time_low", ctypes.c_uint32),
            ("access_time_high", ctypes.c_uint32),
            ("write_time_low", ctypes.c_uint32),
            ("write_time_high", ctypes.c_uint32),
            ("volume_serial_number", ctypes.c_uint32),
            ("file_size_high", ctypes.c_uint32),
            ("file_size_low", ctypes.c_uint32),
            ("number_of_links", ctypes.c_uint32),
            ("file_index_high", ctypes.c_uint32),
            ("file_index_low", ctypes.c_uint32),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    get_information = kernel32.GetFileInformationByHandle
    get_information.argtypes = (ctypes.c_void_p, ctypes.POINTER(_ByHandleFileInformation))
    get_information.restype = ctypes.c_int
    information = _ByHandleFileInformation()
    if not get_information(ctypes.c_void_p(handle), ctypes.byref(information)):
        error_number = ctypes.get_last_error()  # type: ignore[attr-defined]
        raise OSError(error_number, ctypes.FormatError(error_number))
    return {
        "device": int(information.volume_serial_number),
        "inode": int(information.file_index_high) << 32
        | int(information.file_index_low),
        "file_attributes": int(information.file_attributes),
        "nlink": int(information.number_of_links),
    }


def _open_windows_directory_handle(
    path: Path,
    expected_identity: Optional[Dict[str, int]] = None,
    *,
    allow_child_file_create: bool = False,
    allow_child_directory_create: bool = False,
    allow_child_traverse: bool = False,
    allow_rename: bool = False,
) -> int:
    """Hold a directory without delete sharing so its pathname cannot swap."""

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    )
    create_file.restype = ctypes.c_void_p
    desired_access = 0x00000080  # FILE_READ_ATTRIBUTES
    if allow_child_file_create:
        desired_access |= (
            0x00000001  # FILE_LIST_DIRECTORY
            | 0x00000002  # FILE_ADD_FILE
            | 0x00000020  # FILE_TRAVERSE
        )
    if allow_child_directory_create:
        desired_access |= (
            0x00000001  # FILE_LIST_DIRECTORY
            | 0x00000004  # FILE_ADD_SUBDIRECTORY
            | 0x00000020  # FILE_TRAVERSE
        )
    if allow_child_traverse:
        desired_access |= 0x00000020  # FILE_TRAVERSE
    if allow_rename:
        desired_access |= 0x00010000  # DELETE
    handle = create_file(
        str(path),
        desired_access,
        0x00000001 | 0x00000002,  # share read/write, deliberately not delete
        None,
        3,  # OPEN_EXISTING
        0x02000000 | 0x00200000,  # BACKUP_SEMANTICS | OPEN_REPARSE_POINT
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if handle in (None, invalid):
        error_number = ctypes.get_last_error()  # type: ignore[attr-defined]
        raise InstallerError(
            "cannot hold Windows directory identity {}: {}".format(
                path,
                ctypes.FormatError(error_number),
            )
        )
    result = int(handle)
    try:
        held = _windows_directory_handle_identity(result)
        directory_attribute = 0x10
        reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if (
            not held["file_attributes"] & directory_attribute
            or held["file_attributes"] & reparse_attribute
        ):
            raise InstallerConflict(
                "Windows directory handle names a reparse point or non-directory: {}".format(
                    path
                )
            )
        if expected_identity is not None:
            expected = _validate_filesystem_identity(
                expected_identity,
                "Windows directory",
            )
            if (
                held["device"] != expected["device"]
                or held["inode"] != expected["inode"]
                or _directory_identity(path, "Windows directory") != expected
            ):
                raise InstallerConflict(
                    "Windows directory identity changed while it was held: {}".format(path)
                )
        return result
    except BaseException:
        _close_windows_handle(result)
        raise


def _create_windows_child_handle(
    parent_handle: int,
    child_name: str,
    display_path: Path,
    *,
    is_directory: bool,
) -> int:
    """Atomically create one child and return its no-delete-share handle.

    Path-based creation followed by a separate open has an unavoidable
    create-to-open rename gap. ``NtCreateFile`` creates relative to the
    already-held parent and returns the handle in the same namespace operation.
    """

    child = _windows_child_name(child_name)

    class _UnicodeString(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_ushort),
            ("maximum_length", ctypes.c_ushort),
            ("buffer", ctypes.c_wchar_p),
        ]

    class _ObjectAttributes(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_ulong),
            ("root_directory", ctypes.c_void_p),
            ("object_name", ctypes.POINTER(_UnicodeString)),
            ("attributes", ctypes.c_ulong),
            ("security_descriptor", ctypes.c_void_p),
            ("security_quality_of_service", ctypes.c_void_p),
        ]

    class _IoStatusUnion(ctypes.Union):
        _fields_ = [
            ("status", ctypes.c_int32),
            ("pointer", ctypes.c_void_p),
        ]

    class _IoStatusBlock(ctypes.Structure):
        _anonymous_ = ("result",)
        _fields_ = [
            ("result", _IoStatusUnion),
            ("information", ctypes.c_size_t),
        ]

    encoded_length = len(child.encode("utf-16-le"))
    if encoded_length > 0xFFFC:
        raise InstallerConflict("Windows stage child name is too long")
    buffer = ctypes.create_unicode_buffer(child)
    unicode_name = _UnicodeString(
        encoded_length,
        encoded_length + 2,
        ctypes.cast(buffer, ctypes.c_wchar_p),
    )
    object_attributes = _ObjectAttributes(
        ctypes.sizeof(_ObjectAttributes),
        ctypes.c_void_p(parent_handle),
        ctypes.pointer(unicode_name),
        0x00000040,  # OBJ_CASE_INSENSITIVE
        None,
        None,
    )
    io_status = _IoStatusBlock()
    result_handle = ctypes.c_void_p()
    ntdll = ctypes.WinDLL("ntdll", use_last_error=True)  # type: ignore[attr-defined]
    nt_create_file = ntdll.NtCreateFile
    nt_create_file.argtypes = (
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_ulong,
        ctypes.POINTER(_ObjectAttributes),
        ctypes.POINTER(_IoStatusBlock),
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.c_ulong,
    )
    nt_create_file.restype = ctypes.c_int32
    desired_access = (
        0x00000080  # FILE_READ_ATTRIBUTES
        | 0x00000100  # FILE_WRITE_ATTRIBUTES
        | 0x00010000  # DELETE (required for handle-bound publication)
        | 0x00100000  # SYNCHRONIZE
    )
    if is_directory:
        desired_access |= (
            0x00000001  # FILE_LIST_DIRECTORY
            | 0x00000002  # FILE_ADD_FILE
            | 0x00000004  # FILE_ADD_SUBDIRECTORY
            | 0x00000020  # FILE_TRAVERSE
        )
        create_options = 0x00000001 | 0x00000020  # DIRECTORY_FILE | SYNC_NONALERT
    else:
        desired_access |= 0x00000001 | 0x00000002  # FILE_READ_DATA | FILE_WRITE_DATA
        create_options = 0x00000040 | 0x00000020  # NON_DIRECTORY_FILE | SYNC_NONALERT
    status_value = int(
        nt_create_file(
            ctypes.byref(result_handle),
            desired_access,
            ctypes.byref(object_attributes),
            ctypes.byref(io_status),
            None,
            0x00000080,  # FILE_ATTRIBUTE_NORMAL
            0x00000001
            | (0x00000002 if is_directory else 0),
            # Directories share read/write while being populated. A staged
            # file shares read only, denying both write and delete until its
            # verified handle has been published and released.
            2,  # FILE_CREATE: fail if the child already exists
            create_options,
            None,
            0,
        )
    )
    if status_value < 0:
        rtl_status_to_dos_error = ntdll.RtlNtStatusToDosError
        rtl_status_to_dos_error.argtypes = (ctypes.c_int32,)
        rtl_status_to_dos_error.restype = ctypes.c_uint32
        error_number = int(rtl_status_to_dos_error(status_value))
        if error_number in {0, 317}:  # ERROR_MR_MID_NOT_FOUND
            raise InstallerError(
                "Windows child creation failed with NTSTATUS 0x{:08x}".format(
                    ctypes.c_uint32(status_value).value
                )
            )
        if error_number in {80, 183}:
            raise FileExistsError(error_number, ctypes.FormatError(error_number), str(display_path))
        raise OSError(error_number, ctypes.FormatError(error_number), str(display_path))
    raw_handle = result_handle.value
    if raw_handle is None:
        raise InstallerError(
            "Windows atomically created a stage child without returning a handle"
        )
    handle = int(raw_handle)
    try:
        # FILE_CREATED is the only acceptable completion.  Do not treat a
        # pre-existing or superseded namespace occupant as installer-owned.
        if int(io_status.information) != 2:
            raise InstallerConflict(
                "Windows stage child creation did not create a new occupant: {}".format(
                    display_path
                )
            )
        held = _windows_directory_handle_identity(handle)
        directory_attribute = 0x10
        reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        held_is_directory = bool(held["file_attributes"] & directory_attribute)
        if held_is_directory != is_directory or held["file_attributes"] & reparse_attribute:
            raise InstallerConflict(
                "Windows stage creation returned a reparse point or wrong type: {}".format(
                    display_path
                )
            )
        metadata = display_path.lstat()
        expected = _filesystem_identity(metadata)
        if (
            _is_link_or_reparse(display_path)
            or bool(stat.S_ISDIR(metadata.st_mode)) != is_directory
            or held["device"] != expected["device"]
            or held["inode"] != expected["inode"]
        ):
            raise InstallerConflict(
                "Windows stage child path differs from its created handle: {}".format(
                    display_path
                )
            )
        return handle
    except BaseException:
        _close_windows_handle(handle)
        raise


def _create_windows_directory_handle(
    parent_handle: int,
    child_name: str,
    display_path: Path,
) -> int:
    return _create_windows_child_handle(
        parent_handle,
        child_name,
        display_path,
        is_directory=True,
    )


def _create_windows_file_handle(
    parent_handle: int,
    child_name: str,
    display_path: Path,
) -> int:
    return _create_windows_child_handle(
        parent_handle,
        child_name,
        display_path,
        is_directory=False,
    )


def _close_windows_handle(handle: int) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    close = kernel32.CloseHandle
    close.argtypes = (ctypes.c_void_p,)
    close.restype = ctypes.c_int
    if not close(ctypes.c_void_p(handle)):
        error_number = ctypes.get_last_error()  # type: ignore[attr-defined]
        raise InstallerError(
            "cannot close Windows directory handle: {}".format(
                ctypes.FormatError(error_number)
            )
        )


def _set_windows_handle_read_only(handle: int, read_only: bool) -> None:
    """Set the readonly attribute on the already-held exact Windows object."""

    class _FileBasicInfo(ctypes.Structure):
        _fields_ = [
            ("creation_time", ctypes.c_int64),
            ("last_access_time", ctypes.c_int64),
            ("last_write_time", ctypes.c_int64),
            ("change_time", ctypes.c_int64),
            ("file_attributes", ctypes.c_uint32),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    get_information = kernel32.GetFileInformationByHandleEx
    get_information.argtypes = (
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    )
    get_information.restype = ctypes.c_int
    information = _FileBasicInfo()
    if not get_information(
        ctypes.c_void_p(handle),
        0,  # FileBasicInfo
        ctypes.byref(information),
        ctypes.sizeof(information),
    ):
        error_number = int(ctypes.get_last_error())  # type: ignore[attr-defined]
        raise OSError(error_number, ctypes.FormatError(error_number))
    if read_only:
        information.file_attributes = (
            information.file_attributes & ~0x00000080
        ) | 0x00000001  # READONLY cannot be combined with NORMAL
    else:
        information.file_attributes &= ~0x00000001
        if information.file_attributes == 0:
            information.file_attributes = 0x00000080  # FILE_ATTRIBUTE_NORMAL
    set_information = kernel32.SetFileInformationByHandle
    set_information.argtypes = (
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    )
    set_information.restype = ctypes.c_int
    if not set_information(
        ctypes.c_void_p(handle),
        0,  # FileBasicInfo
        ctypes.byref(information),
        ctypes.sizeof(information),
    ):
        error_number = int(ctypes.get_last_error())  # type: ignore[attr-defined]
        raise OSError(error_number, ctypes.FormatError(error_number))


def _open_windows_regular_file_handle(
    path: Path,
    *,
    allow_rename: bool = False,
) -> Tuple[Optional[int], int]:
    """Open a Windows leaf itself while denying rename/delete sharing."""

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    )
    create_file.restype = ctypes.c_void_p
    ctypes.set_last_error(0)  # type: ignore[attr-defined]
    desired_access = 0x80000000  # GENERIC_READ
    if allow_rename:
        desired_access |= 0x00010000  # DELETE
    share_access = 0x00000001  # FILE_SHARE_READ
    if not allow_rename:
        share_access |= 0x00000002  # FILE_SHARE_WRITE for cooperative private reads
    value = create_file(
        str(path),
        desired_access,
        share_access,  # never share delete; held stages also deny write
        None,
        3,  # OPEN_EXISTING
        0x00200000,  # FILE_FLAG_OPEN_REPARSE_POINT
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if value in (None, invalid):
        return None, int(ctypes.get_last_error())  # type: ignore[attr-defined]
    return int(value), 0


def _open_windows_regular_file_descriptor(
    path: Path,
    *,
    require_single_link: bool,
    allow_rename: bool = False,
) -> int:
    """Open one Windows leaf itself, never the target of a reparse point."""

    handle, error_number = _open_windows_regular_file_handle(
        path,
        allow_rename=allow_rename,
    )
    if handle is None:
        if error_number in {2, 3}:
            raise FileNotFoundError(error_number, ctypes.FormatError(error_number), str(path))
        raise OSError(error_number, ctypes.FormatError(error_number), str(path))
    raw_handle = handle
    try:
        import msvcrt

        descriptor = msvcrt.open_osfhandle(
            raw_handle,
            os.O_RDONLY | getattr(os, "O_BINARY", 0),
        )
        raw_handle = -1
        metadata = os.fstat(descriptor)
        attributes = getattr(metadata, "st_file_attributes", 0)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or bool(
                attributes
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            )
            or (require_single_link and metadata.st_nlink != 1)
        ):
            os.close(descriptor)
            raise InstallerConflict(
                "Windows file must be one real regular file: {}".format(path)
            )
        return descriptor
    finally:
        if raw_handle >= 0:
            _close_windows_handle(raw_handle)


def _open_windows_lock_handle(
    path: Path,
    disposition: int,
) -> Tuple[Optional[int], int]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    )
    create_file.restype = ctypes.c_void_p

    ctypes.set_last_error(0)  # type: ignore[attr-defined]
    value = create_file(
        str(path),
        0x80000000 | 0x40000000,  # GENERIC_READ | GENERIC_WRITE
        0x00000001 | 0x00000002,  # share read/write, deliberately not delete
        None,
        disposition,
        0x00200000,  # FILE_FLAG_OPEN_REPARSE_POINT
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if value in (None, invalid):
        return None, int(ctypes.get_last_error())  # type: ignore[attr-defined]
    return int(value), 0


def _open_windows_lock_stream(path: Path, *, _empty_retries: int = 100) -> Any:
    """Open/create one real Windows lock leaf with no delete sharing."""

    handle, error_number = _open_windows_lock_handle(path, 1)  # CREATE_NEW
    created = handle is not None
    if handle is None and error_number in {80, 183}:
        handle, error_number = _open_windows_lock_handle(path, 3)  # OPEN_EXISTING
    if handle is None:
        raise OSError(error_number, ctypes.FormatError(error_number), str(path))
    raw_handle = handle
    try:
        import msvcrt

        descriptor = msvcrt.open_osfhandle(
            raw_handle,
            os.O_RDWR | getattr(os, "O_BINARY", 0),
        )
        raw_handle = -1
        metadata = os.fstat(descriptor)
        attributes = getattr(metadata, "st_file_attributes", 0)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or bool(
                attributes
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            )
        ):
            os.close(descriptor)
            raise InstallerConflict(
                "recorder directory lock must be one real regular file: {}".format(
                    path
                )
            )
        stream = os.fdopen(descriptor, "r+b", buffering=0)
        locked = False
        try:
            import msvcrt

            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            locked = True
            stream.seek(0)
            marker = stream.read()
            if marker == b"":
                if created:
                    stream.seek(0)
                    if stream.write(_LOCK_MARKER) != len(_LOCK_MARKER):
                        raise InstallerError("recorder directory lock marker write was incomplete")
                    stream.truncate()
                    stream.flush()
                    os.fsync(stream.fileno())
                    marker = _LOCK_MARKER
                elif _empty_retries > 0:
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                    locked = False
                    stream.close()
                    time.sleep(0.01)
                    return _open_windows_lock_stream(
                        path,
                        _empty_retries=_empty_retries - 1,
                    )
            if marker != _LOCK_MARKER:
                raise InstallerConflict(
                    "recorder directory lock has unexpected contents: {}".format(path)
                )
            stream.seek(0)
            return stream
        except BaseException:
            if locked:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            stream.close()
            raise
    finally:
        if raw_handle >= 0:
            _close_windows_handle(raw_handle)


def _require_directory_anchor(
    anchor: _DirectoryAnchor,
    *,
    require_path: bool = True,
) -> None:
    if anchor.descriptor is not None:
        if _filesystem_identity(os.fstat(anchor.descriptor)) != anchor.identity:
            raise InstallerConflict(
                "held directory descriptor changed identity: {}".format(anchor.path)
            )
    if not require_path:
        return
    try:
        current = anchor.path.lstat()
    except FileNotFoundError as error:
        raise InstallerConflict(
            "review-bound directory disappeared during the operation: {}".format(
                anchor.path
            )
        ) from error
    if (
        stat.S_ISLNK(current.st_mode)
        or _is_link_or_reparse(anchor.path)
        or not stat.S_ISDIR(current.st_mode)
        or _filesystem_identity(current) != anchor.identity
    ):
        raise InstallerConflict(
            "review-bound directory identity changed: {}".format(anchor.path)
        )


def _open_anchor_lock_stream(
    anchor: _DirectoryAnchor,
    name: str,
    *,
    _empty_retries: int = 100,
) -> Any:
    if not name or Path(name).name != name:
        raise InstallerError("unsafe directory lock name")
    if os.name == "nt":  # pragma: no cover - native Windows CI
        return _open_windows_lock_stream(anchor.path / name)
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    created = False
    try:
        if anchor.descriptor is not None:
            descriptor = os.open(name, flags, 0o600, dir_fd=anchor.descriptor)
        else:
            descriptor = os.open(str(anchor.path / name), flags, 0o600)
        created = True
    except FileExistsError:
        if anchor.descriptor is not None:
            before = os.stat(name, dir_fd=anchor.descriptor, follow_symlinks=False)
        else:
            before = (anchor.path / name).lstat()
        if (
            stat.S_ISLNK(before.st_mode)
            or bool(
                getattr(before, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            )
            or not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
        ):
            raise InstallerConflict(
                "recorder directory lock is not one real regular file: {}".format(
                    anchor.path / name
                )
            )
        open_flags = os.O_RDWR
        if hasattr(os, "O_BINARY"):
            open_flags |= os.O_BINARY
        if hasattr(os, "O_NOFOLLOW"):
            open_flags |= os.O_NOFOLLOW
        if anchor.descriptor is not None:
            descriptor = os.open(name, open_flags, dir_fd=anchor.descriptor)
        else:
            descriptor = os.open(str(anchor.path / name), open_flags)
        opened = os.fstat(descriptor)
        if _filesystem_identity(opened) != _filesystem_identity(before) or opened.st_nlink != 1:
            os.close(descriptor)
            raise InstallerConflict("recorder directory lock changed while opening")
    stream = os.fdopen(descriptor, "r+b", buffering=0)
    locked = False
    try:
        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        locked = True
        stream.seek(0)
        marker = stream.read()
        if marker == b"":
            if created:
                stream.seek(0)
                if stream.write(_LOCK_MARKER) != len(_LOCK_MARKER):
                    raise InstallerError("recorder directory lock marker write was incomplete")
                stream.truncate()
                stream.flush()
                os.fsync(stream.fileno())
                marker = _LOCK_MARKER
            elif _empty_retries > 0:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                locked = False
                stream.close()
                time.sleep(0.01)
                return _open_anchor_lock_stream(
                    anchor,
                    name,
                    _empty_retries=_empty_retries - 1,
                )
        if marker != _LOCK_MARKER:
            raise InstallerConflict(
                "recorder directory lock has unexpected contents: {}".format(
                    anchor.path / name
                )
            )
        stream.seek(0)
        return stream
    except BaseException:
        if locked:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()
        raise


@contextmanager
def _lock_directory(
    path: Path,
    expected_identity: Dict[str, int],
    *,
    lock_name: str,
    allow_child_file_create: bool = False,
    allow_child_directory_create: bool = False,
    allow_child_traverse: bool = False,
) -> Iterator[_DirectoryAnchor]:
    expected = _validate_filesystem_identity(expected_identity, "review-bound directory")
    anchor = _DirectoryAnchor(path, expected)
    try:
        if os.name == "nt":  # pragma: no cover - native Windows CI
            anchor.windows_directory_handle = _open_windows_directory_handle(
                path,
                expected,
                allow_child_file_create=allow_child_file_create,
                allow_child_directory_create=allow_child_directory_create,
                allow_child_traverse=allow_child_traverse,
            )
        else:
            flags = os.O_RDONLY
            if hasattr(os, "O_DIRECTORY"):
                flags |= os.O_DIRECTORY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            anchor.descriptor = os.open(str(path), flags)
        _require_directory_anchor(anchor)
        stream = _open_anchor_lock_stream(anchor, lock_name)
        anchor.stream = stream
        _require_directory_anchor(anchor)
        yield anchor
    finally:
        try:
            if anchor.stream is not None:
                if os.name == "nt":  # pragma: no cover - native Windows CI
                    import msvcrt

                    anchor.stream.seek(0)
                    msvcrt.locking(anchor.stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(anchor.stream.fileno(), fcntl.LOCK_UN)
                anchor.stream.close()
        finally:
            if anchor.descriptor is not None:
                os.close(anchor.descriptor)
            if anchor.windows_directory_handle is not None:
                _close_windows_handle(anchor.windows_directory_handle)


@contextmanager
def _lock_action_parents(
    actions: Sequence[Dict[str, Any]],
) -> Iterator[Dict[str, _DirectoryAnchor]]:
    specifications: Dict[str, Tuple[Path, Dict[str, int], bool, bool]] = {}
    for action in actions:
        parent = Path(action["parent_path"])
        identity = _validate_filesystem_identity(
            action["parent_identity"],
            "transaction action parent",
        )
        key = _normalized_path_text(parent)
        previous = specifications.get(key)
        if previous is not None and previous[1] != identity:
            raise InstallerConflict(
                "transaction records conflicting identities for one target parent"
            )
        specifications[key] = (
            parent,
            identity,
            action.get("kind") != "install-tree"
            or (previous is not None and previous[2]),
            action.get("kind") == "install-tree"
            or (previous is not None and previous[3]),
        )
    anchors: Dict[str, _DirectoryAnchor] = {}
    acquired: List[Any] = []
    try:
        for key in sorted(specifications):
            (
                parent,
                identity,
                allow_child_file_create,
                allow_child_directory_create,
            ) = specifications[key]
            manager = _lock_directory(
                parent,
                identity,
                lock_name=_PARENT_LOCK_NAME,
                allow_child_file_create=allow_child_file_create,
                allow_child_directory_create=allow_child_directory_create,
                allow_child_traverse=True,
            )
            anchor = manager.__enter__()
            acquired.append(manager)
            anchors[key] = anchor
        yield anchors
    finally:
        for manager in reversed(acquired):
            manager.__exit__(None, None, None)


def _anchor_for_action(plan: InstallPlan, action: Dict[str, Any]) -> _DirectoryAnchor:
    if plan.parent_anchors is None:
        raise InstallerError("target-parent identities are not held for this operation")
    key = _normalized_path_text(Path(action["parent_path"]))
    try:
        anchor = plan.parent_anchors[key]
    except KeyError as error:
        raise InstallerConflict("transaction action has no held target parent") from error
    if anchor.identity != action["parent_identity"]:
        raise InstallerConflict("held target parent differs from the reviewed action")
    _require_directory_anchor(anchor)
    return anchor


def _require_all_action_parents(plan: InstallPlan) -> None:
    seen = set()
    for action in plan.journal["actions"]:
        key = _normalized_path_text(Path(action["parent_path"]))
        if key in seen:
            continue
        seen.add(key)
        _anchor_for_action(plan, action)


def _require_transaction_attached(plan: InstallPlan) -> None:
    if plan.transaction_anchor is None:
        raise InstallerError("transaction directory identity is not held")
    _require_directory_anchor(plan.transaction_anchor)


def _close_windows_stage_binding(binding: Dict[str, Any]) -> None:
    descriptor = binding.get("descriptor")
    if descriptor is not None:
        os.close(int(descriptor))
    else:
        _close_windows_handle(int(binding["handle"]))


def _remember_windows_stage_binding(
    plan: InstallPlan,
    action: Dict[str, Any],
    *,
    handle: int,
    descriptor: Optional[int],
) -> None:
    if os.name != "nt" or plan.windows_stage_bindings is None:
        raise InstallerError("Windows stage-binding lifetime is not active")
    stage = Path(action["stage_path"])
    key = _normalized_path_text(stage)
    if key in plan.windows_stage_bindings:
        raise InstallerConflict("Windows stage already has a held publication binding")
    held = _windows_directory_handle_identity(handle)
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    is_directory = bool(held["file_attributes"] & 0x10)
    if (
        bool(held["file_attributes"] & reparse_attribute)
        or is_directory != (action["kind"] == "install-tree")
    ):
        raise InstallerConflict(
            "Windows stage handle has the wrong type or names a reparse point"
        )
    try:
        metadata = stage.lstat()
    except FileNotFoundError as error:
        raise InstallerConflict("Windows stage path disappeared while binding it") from error
    current_identity = _filesystem_identity(metadata)
    if (
        _is_link_or_reparse(stage)
        or current_identity["device"] != held["device"]
        or current_identity["inode"] != held["inode"]
    ):
        raise InstallerConflict("Windows stage path differs from its held handle")
    plan.windows_stage_bindings[key] = {
        "handle": handle,
        "descriptor": descriptor,
        "identity": {"device": held["device"], "inode": held["inode"]},
        "is_directory": is_directory,
    }


def _release_windows_stage_binding(plan: InstallPlan, stage: Path) -> None:
    if plan.windows_stage_bindings is None:
        return
    binding = plan.windows_stage_bindings.pop(_normalized_path_text(stage), None)
    if binding is not None:
        _close_windows_stage_binding(binding)


def _ensure_windows_stage_binding(
    plan: InstallPlan,
    action: Dict[str, Any],
) -> None:
    if os.name != "nt":
        return
    if plan.windows_stage_bindings is None:
        raise InstallerError("Windows stage-binding lifetime is not active")
    stage = Path(action["stage_path"])
    key = _normalized_path_text(stage)
    if key in plan.windows_stage_bindings:
        return
    descriptor: Optional[int] = None
    handle: Optional[int] = None
    try:
        if action["kind"] == "install-tree":
            expected = _directory_identity(stage, "review-bound Windows stage")
            handle = _open_windows_directory_handle(
                stage,
                expected,
                allow_rename=True,
            )
        else:
            descriptor = _open_windows_regular_file_descriptor(
                stage,
                require_single_link=True,
                allow_rename=True,
            )
            import msvcrt

            handle = int(msvcrt.get_osfhandle(descriptor))
        _remember_windows_stage_binding(
            plan,
            action,
            handle=handle,
            descriptor=descriptor,
        )
        handle = None
        descriptor = None
        if _classify_action_child_held(
            _anchor_for_action(plan, action),
            stage.name,
            action,
        ) != "after":
            _release_windows_stage_binding(plan, stage)
            raise InstallerDrift(
                "held Windows stage differs from its reviewed replacement"
            )
    finally:
        if descriptor is not None:
            os.close(descriptor)
        elif handle is not None:
            _close_windows_handle(handle)


@contextmanager
def _held_installation_serialization(plan: InstallPlan) -> Iterator[None]:
    """Use the already-held common state parent as the installer mutex."""

    state = Path(plan.journal["target"]["state_root"])
    matching = [
        action
        for action in plan.journal["actions"]
        if _normalized_path_text(Path(action["parent_path"]))
        == _normalized_path_text(state)
    ]
    if not matching:
        raise InstallerConflict("transaction has no held state-root target parent")
    _anchor_for_action(plan, matching[0])
    yield
    _anchor_for_action(plan, matching[0])


def _copy_payload(source_root: Path, staging: Path, expected_digest: str) -> None:
    _secure_directory(staging)
    for source, relative in _payload_files(source_root):
        destination = staging / Path(relative)
        _secure_directory(destination.parent)
        with source.open("rb") as input_stream:
            data = input_stream.read()
        _atomic_write(destination, data, mode=0o600)
    staged_digest = source_tree_digest(staging)
    source_digest = source_tree_digest(source_root)
    if staged_digest != expected_digest or source_digest != expected_digest:
        raise InstallerDrift("source runtime payload drifted while staging the reviewed copy")


def _open_relative_directory(root_descriptor: int, parts: Sequence[str]) -> int:
    descriptor = os.dup(root_descriptor)
    try:
        for part in parts:
            if not part or Path(part).name != part or part in {".", ".."}:
                raise InstallerConflict("runtime payload contains an unsafe directory name")
            flags = os.O_RDONLY
            if hasattr(os, "O_DIRECTORY"):
                flags |= os.O_DIRECTORY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _copy_payload_windows_held(
    source_root: Path,
    stage: Path,
    expected_digest: str,
    root_handle: int,
) -> None:
    """Populate a newly created Windows stage without replacing any occupant."""

    directory_handles: Dict[Tuple[str, ...], int] = {tuple(): root_handle}
    digest = hashlib.sha256()
    try:
        for source, relative_text in _payload_files(source_root):
            relative = Path(relative_text)
            current = stage
            parts: Tuple[str, ...] = tuple()
            for part in relative.parts[:-1]:
                parent_parts = parts
                parts = parts + (part,)
                current = current / part
                if parts in directory_handles:
                    continue
                try:
                    directory_handles[parts] = _create_windows_directory_handle(
                        directory_handles[parent_parts],
                        part,
                        current,
                    )
                except FileExistsError as error:
                    raise InstallerDrift(
                        "review-bound runtime stage directory was occupied"
                    ) from error
            destination = stage / relative
            try:
                raw_handle = _create_windows_file_handle(
                    directory_handles[parts],
                    relative.name,
                    destination,
                )
            except FileExistsError as error:
                raise InstallerDrift(
                    "review-bound runtime stage file was occupied"
                ) from error
            descriptor: Optional[int] = None
            raw = source.read_bytes()
            encoded_name = relative_text.encode("utf-8")
            digest.update(len(encoded_name).to_bytes(8, "big"))
            digest.update(encoded_name)
            digest.update(len(raw).to_bytes(8, "big"))
            digest.update(raw)
            try:
                import msvcrt

                descriptor = msvcrt.open_osfhandle(
                    raw_handle,
                    os.O_RDWR | getattr(os, "O_BINARY", 0),
                )
                raw_handle = -1
                with os.fdopen(descriptor, "wb", closefd=False) as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                _set_windows_handle_read_only(
                    int(msvcrt.get_osfhandle(descriptor)),
                    True,
                )
            finally:
                if descriptor is not None:
                    os.close(descriptor)
                if raw_handle >= 0:
                    _close_windows_handle(raw_handle)
        if digest.hexdigest() != expected_digest:
            raise InstallerDrift("source runtime payload drifted while staging the reviewed copy")
        for parts in sorted(directory_handles, key=len, reverse=True):
            _set_windows_handle_read_only(directory_handles[parts], True)
    finally:
        for parts, handle in sorted(
            directory_handles.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            if parts:
                _close_windows_handle(handle)


def _copy_payload_to_held_stage(
    source_root: Path,
    stage: Path,
    expected_digest: str,
    anchor: _DirectoryAnchor,
) -> Optional[int]:
    """Create an immutable runtime tree beneath a held target parent."""

    _require_directory_anchor(anchor)
    if anchor.descriptor is None:
        # Native Windows creates relative to the no-delete-share parent handle,
        # returning a bound no-delete-share stage handle in the same syscall.
        # There is no create-to-open interval in which another writer can
        # replace the stage before the installer owns it.
        if anchor.windows_directory_handle is None:
            raise InstallerError("Windows target-parent handle is not held")
        try:
            stage_handle = _create_windows_directory_handle(
                anchor.windows_directory_handle,
                stage.name,
                stage,
            )
        except FileExistsError as error:
            raise InstallerDrift(
                "review-bound runtime stage was occupied during creation"
            ) from error
        try:
            _copy_payload_windows_held(
                source_root,
                stage,
                expected_digest,
                stage_handle,
            )
        except BaseException:
            _close_windows_handle(stage_handle)
            raise
        _require_directory_anchor(anchor)
        return stage_handle

    if os.mkdir not in getattr(os, "supports_dir_fd", set()) or os.open not in getattr(
        os,
        "supports_dir_fd",
        set(),
    ):
        raise InstallerError("POSIX runtime lacks directory-anchored staging support")
    os.mkdir(stage.name, 0o700, dir_fd=anchor.descriptor)
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    root_descriptor = os.open(stage.name, flags, dir_fd=anchor.descriptor)
    created_directories = {tuple()}
    digest = hashlib.sha256()
    try:
        for source, relative_text in _payload_files(source_root):
            relative = Path(relative_text)
            parent_parts = tuple(relative.parts[:-1])
            current: Tuple[str, ...] = tuple()
            for part in parent_parts:
                next_parts = current + (part,)
                if next_parts not in created_directories:
                    parent_descriptor = _open_relative_directory(root_descriptor, current)
                    try:
                        os.mkdir(part, 0o700, dir_fd=parent_descriptor)
                        os.fsync(parent_descriptor)
                    finally:
                        os.close(parent_descriptor)
                    created_directories.add(next_parts)
                current = next_parts
            parent_descriptor = _open_relative_directory(root_descriptor, parent_parts)
            try:
                file_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                if hasattr(os, "O_BINARY"):
                    file_flags |= os.O_BINARY
                if hasattr(os, "O_NOFOLLOW"):
                    file_flags |= os.O_NOFOLLOW
                file_descriptor = os.open(
                    relative.name,
                    file_flags,
                    0o400,
                    dir_fd=parent_descriptor,
                )
                raw = source.read_bytes()
                encoded_name = relative_text.encode("utf-8")
                digest.update(len(encoded_name).to_bytes(8, "big"))
                digest.update(encoded_name)
                digest.update(len(raw).to_bytes(8, "big"))
                digest.update(raw)
                try:
                    os.fchmod(file_descriptor, 0o400)
                    with os.fdopen(file_descriptor, "wb") as stream:
                        file_descriptor = -1
                        stream.write(raw)
                        stream.flush()
                        os.fsync(stream.fileno())
                finally:
                    if file_descriptor >= 0:
                        os.close(file_descriptor)
                os.fsync(parent_descriptor)
            finally:
                os.close(parent_descriptor)
        if digest.hexdigest() != expected_digest:
            raise InstallerDrift("source runtime payload drifted while staging the reviewed copy")
        for parts in sorted(created_directories, key=len, reverse=True):
            directory_descriptor = _open_relative_directory(root_descriptor, parts)
            try:
                os.fchmod(directory_descriptor, 0o500)
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        os.fchmod(root_descriptor, 0o500)
        os.fsync(root_descriptor)
    finally:
        os.close(root_descriptor)
    os.fsync(anchor.descriptor)
    _require_directory_anchor(anchor)
    return None


def _make_tree_read_only(root: Path) -> None:
    for directory, directory_names, file_names in os.walk(str(root), topdown=False):
        directory_path = Path(directory)
        for name in file_names:
            path = directory_path / name
            if os.name == "nt":
                os.chmod(str(path), stat.S_IREAD)
            else:
                os.chmod(str(path), 0o400)
        for name in directory_names:
            path = directory_path / name
            if os.name == "nt":
                os.chmod(str(path), stat.S_IREAD)
            else:
                os.chmod(str(path), 0o500)
    if os.name == "nt":
        os.chmod(str(root), stat.S_IREAD)
    else:
        os.chmod(str(root), 0o500)


def _assert_file_matches(
    path: Path,
    expected: Dict[str, Any],
    label: str,
    *,
    anchor: Optional[_DirectoryAnchor] = None,
) -> bytes:
    if anchor is None:
        _assert_no_link_components(path)
        exists = path.exists()
    else:
        if _normalized_path_text(path.parent) != _normalized_path_text(anchor.path):
            raise InstallerConflict("{} escaped its held target parent".format(label))
        _require_directory_anchor(anchor)
        if anchor.descriptor is not None:
            try:
                os.stat(path.name, dir_fd=anchor.descriptor, follow_symlinks=False)
                exists = True
            except FileNotFoundError:
                exists = False
        else:
            exists = _lexical_exists(path)
    if exists != bool(expected["exists"]):
        raise InstallerDrift("{} existence changed after planning".format(label))
    if not exists:
        return b""
    if anchor is None:
        if not path.is_file() or _is_link_or_reparse(path):
            raise InstallerDrift("{} is no longer a regular file".format(label))
        raw = path.read_bytes()
        current_mode = stat.S_IMODE(path.stat().st_mode) if os.name != "nt" else None
    else:
        try:
            raw, current_mode = _read_regular_child_held(anchor, path.name)
        except (InstallerError, OSError) as error:
            raise InstallerDrift("{} is no longer a regular file".format(label)) from error
    if _sha256(raw) != expected["sha256"]:
        raise InstallerDrift("{} bytes changed after planning".format(label))
    expected_mode = expected.get("mode")
    if os.name != "nt" and expected_mode is not None and current_mode != expected_mode:
        raise InstallerDrift("{} mode changed after planning".format(label))
    if anchor is not None:
        _require_directory_anchor(anchor)
    return raw


def _prepare_apply(plan: InstallPlan) -> Dict[str, Any]:
    _require_all_action_parents(plan)
    journal = plan.journal
    actions_by_key = {
        (action["kind"], action["name"]): action
        for action in journal["actions"]
    }

    def action_anchor(kind: str, name: str) -> _DirectoryAnchor:
        return _anchor_for_action(plan, actions_by_key[(kind, name)])

    source = _absolute_path(journal["source"]["root"], "planned source_root")
    if source_tree_digest(source) != journal["source"]["payload_sha256"]:
        raise InstallerDrift("source runtime payload changed after planning")
    state = _state_path(journal["target"]["state_root"])
    install_root = _absolute_path(journal["target"]["install_root"], "planned install_root")
    if _paths_overlap(source, state):
        raise InstallerConflict("planned source and state roots overlap")
    install_before = journal["target"]["install_before"]
    install_anchor = action_anchor("install-tree", "runtime")
    install_classification = _classify_action_child_held(
        install_anchor,
        install_root.name,
        actions_by_key[("install-tree", "runtime")],
    )
    if install_before["exists"]:
        if install_classification != "after":
            raise InstallerDrift("installed version target contains different bytes")
    elif install_classification != "missing":
        raise InstallerDrift("installed version target existence changed after planning")
    settings_spec = journal["target"]["settings"]
    settings_path = _absolute_path(settings_spec["path"], "planned settings path")
    settings_before = _assert_file_matches(
        settings_path,
        settings_spec["before"],
        "settings.json",
        anchor=action_anchor("settings", "recorder"),
    )
    previous_settings = (
        _load_existing_settings_bytes(settings_before) if settings_before else None
    )
    inventory_spec = journal["target"]["managed_targets"]
    inventory_path = _absolute_path(
        inventory_spec["path"], "planned managed target inventory path"
    )
    inventory_before = _assert_file_matches(
        inventory_path,
        inventory_spec["before"],
        "managed target inventory",
        anchor=action_anchor("managed-targets", "inventory"),
    )
    if inventory_before:
        prior_targets = _load_managed_targets_bytes(
            inventory_before,
            source_root=source,
            state_root=state,
        )
    elif inventory_spec["before_provenance"] == "recovered-applied-transaction-history":
        if previous_settings is None:
            raise InstallerDrift("prior settings disappeared after inventory recovery planning")
        prior_targets = _recover_managed_targets_from_transactions(
            state,
            previous_settings,
            source_root=source,
        )
    else:
        prior_targets = []
    if prior_targets != inventory_spec["before_targets"]:
        raise InstallerDrift("managed target ownership changed after planning")
    inventory_after = _managed_targets_bytes(inventory_spec["after"])
    if _sha256(inventory_after) != inventory_spec["after_sha256"]:
        raise InstallerDrift("planned managed target inventory cannot be reproduced")

    interpreter = _absolute_executable(journal["python_executable"])
    if journal.get("claude_homes"):
        claude_runtime = journal["claude_runtime"]
        verified_executable, verified_version = _probe_claude_runtime(
            claude_runtime["executable"]
        )
        if (
            str(verified_executable) != claude_runtime["executable"]
            or verified_version != claude_runtime["observed_version"]
        ):
            raise InstallerDrift("Claude Code runtime changed after planning")
    port = journal["receiver"]["listen_port"]
    settings_value = _settings_value(
        install_root=install_root,
        state_root=state,
        python_executable=interpreter,
        listen_port=port,
        auth_token=plan.auth_token,
    )
    settings_after = _json_bytes(settings_value)
    if _sha256(settings_after) != settings_spec["after_sha256"]:
        raise InstallerDrift("planned settings output cannot be reproduced")
    launcher_spec = journal["target"]["launcher"]
    launcher_path = _absolute_path(launcher_spec["path"], "planned launcher path")
    launcher_before = _assert_file_matches(
        launcher_path,
        launcher_spec["before"],
        "stable recorder launcher",
        anchor=action_anchor("launcher", "stable"),
    )
    launcher_after = stable_launcher_bytes()
    if _sha256(launcher_after) != launcher_spec["after_sha256"]:
        raise InstallerDrift("planned stable launcher output cannot be reproduced")

    home_outputs: List[Dict[str, Any]] = []
    for home_spec in journal["codex_homes"]:
        home = _absolute_path(home_spec["home"], "planned Codex home")
        if home.exists() != bool(home_spec["home_existed"]):
            raise InstallerDrift("Codex home existence changed after planning: {}".format(home))
        if home.exists() and not home.is_dir():
            raise InstallerDrift("Codex home is no longer a directory: {}".format(home))
        hooks_path = _absolute_path(home_spec["hooks"]["path"], "planned hooks path")
        config_path = _absolute_path(home_spec["config"]["path"], "planned config path")
        hooks_before = _assert_file_matches(
            hooks_path,
            home_spec["hooks"]["before"],
            "{} hooks.json".format(home_spec["name"]),
            anchor=action_anchor("hooks", home_spec["name"]),
        )
        config_before = _assert_file_matches(
            config_path,
            home_spec["config"]["before"],
            "{} config.toml".format(home_spec["name"]),
            anchor=action_anchor("otel-config", home_spec["name"]),
        )
        runtime_target = _runtime_target_ref(plan.auth_token, "codex", home)
        new_handler = _hook_handler(
            interpreter,
            state,
            state,
            runtime_target,
        )
        old_handler = _previous_handler(previous_settings, state, home)
        hooks_after = _render_hooks(hooks_before, new_handler, old_handler)
        config_after = _render_otel_config(
            config_before,
            listen_port=port,
            auth_token=plan.auth_token,
            previous_port=previous_settings.get("listen_port") if previous_settings else None,
            previous_token=previous_settings.get("auth_token") if previous_settings else None,
        )
        if _sha256(hooks_after) != home_spec["hooks"]["after_sha256"]:
            raise InstallerDrift("planned hooks output cannot be reproduced for {}".format(home_spec["name"]))
        if _sha256(config_after) != home_spec["config"]["after_sha256"]:
            raise InstallerDrift("planned OTel output cannot be reproduced for {}".format(home_spec["name"]))
        home_outputs.append(
            {
                "spec": home_spec,
                "home": home,
                "hooks_path": hooks_path,
                "hooks_before": hooks_before,
                "hooks_after": hooks_after,
                "config_path": config_path,
                "config_before": config_before,
                "config_after": config_after,
            }
        )

    new_claude_handlers = _claude_hook_handlers(interpreter, state, state)
    old_claude_handlers = _previous_claude_handlers(previous_settings, state)
    claude_home_outputs: List[Dict[str, Any]] = []
    for home_spec in journal.get("claude_homes", []):
        home = _absolute_path(home_spec["home"], "planned Claude home")
        if home.exists() != bool(home_spec["home_existed"]):
            raise InstallerDrift("Claude home existence changed after planning: {}".format(home))
        if home.exists() and not home.is_dir():
            raise InstallerDrift("Claude home is no longer a directory: {}".format(home))
        claude_settings_path = _absolute_path(home_spec["settings"]["path"], "planned Claude settings path")
        claude_settings_before = _assert_file_matches(
            claude_settings_path,
            home_spec["settings"]["before"],
            "{} settings.json".format(home_spec["name"]),
            anchor=action_anchor("claude-settings", home_spec["name"]),
        )
        claude_settings_after = _render_claude_settings(
            claude_settings_before,
            new_claude_handlers,
            old_claude_handlers,
            listen_port=port,
            auth_token=plan.auth_token,
            previous_port=previous_settings.get("listen_port") if previous_settings else None,
            previous_token=previous_settings.get("auth_token") if previous_settings else None,
            previous_version=(
                previous_settings.get("recorder_version") if previous_settings else None
            ),
        )
        if _sha256(claude_settings_after) != home_spec["settings"]["after_sha256"]:
            raise InstallerDrift(
                "planned Claude settings output cannot be reproduced for {}".format(home_spec["name"])
            )
        claude_home_outputs.append(
            {
                "spec": home_spec,
                "home": home,
                "settings_path": claude_settings_path,
                "settings_before": claude_settings_before,
                "settings_after": claude_settings_after,
            }
        )
    retired_home_outputs: List[Dict[str, Any]] = []
    if journal.get("retired_codex_homes"):
        if previous_settings is None:
            raise InstallerDrift("prior Codex handler cannot be reconstructed for retirement")
        for home_spec in journal["retired_codex_homes"]:
            home = _absolute_path(home_spec["home"], "planned retired Codex home")
            if not home.is_dir():
                raise InstallerDrift("retired Codex home is missing: {}".format(home))
            hooks_path = _absolute_path(home_spec["hooks"]["path"], "planned retired hooks path")
            config_path = _absolute_path(home_spec["config"]["path"], "planned retired config path")
            hooks_before = _assert_file_matches(
                hooks_path,
                home_spec["hooks"]["before"],
                "{} retired hooks.json".format(home_spec["name"]),
                anchor=action_anchor("retired-hooks", home_spec["name"]),
            )
            config_before = _assert_file_matches(
                config_path,
                home_spec["config"]["before"],
                "{} retired config.toml".format(home_spec["name"]),
                anchor=action_anchor("retired-otel-config", home_spec["name"]),
            )
            old_handler = _previous_handler(previous_settings, state, home)
            if old_handler is None:
                raise InstallerDrift("prior Codex handler cannot be reconstructed for retirement")
            hooks_after = _retire_hooks(hooks_before, old_handler)
            config_after = _retire_otel_config(
                config_before,
                previous_port=previous_settings["listen_port"],
                previous_token=previous_settings["auth_token"],
            )
            if _sha256(hooks_after) != home_spec["hooks"]["after_sha256"]:
                raise InstallerDrift("planned retired Codex hooks output cannot be reproduced")
            if _sha256(config_after) != home_spec["config"]["after_sha256"]:
                raise InstallerDrift("planned retired Codex OTel output cannot be reproduced")
            retired_home_outputs.append(
                {
                    "spec": home_spec,
                    "home": home,
                    "hooks_path": hooks_path,
                    "hooks_before": hooks_before,
                    "hooks_after": hooks_after,
                    "config_path": config_path,
                    "config_before": config_before,
                    "config_after": config_after,
                }
            )
    retired_claude_home_outputs: List[Dict[str, Any]] = []
    if journal.get("retired_claude_homes"):
        if previous_settings is None or old_claude_handlers is None:
            raise InstallerDrift("prior Claude handler cannot be reconstructed for retirement")
        for home_spec in journal["retired_claude_homes"]:
            home = _absolute_path(home_spec["home"], "planned retired Claude home")
            if not home.is_dir():
                raise InstallerDrift("retired Claude home is missing: {}".format(home))
            claude_settings_path = _absolute_path(
                home_spec["settings"]["path"], "planned retired Claude settings path"
            )
            claude_settings_before = _assert_file_matches(
                claude_settings_path,
                home_spec["settings"]["before"],
                "{} retired settings.json".format(home_spec["name"]),
                anchor=action_anchor(
                    "retired-claude-settings",
                    home_spec["name"],
                ),
            )
            claude_settings_after = _retire_claude_settings(
                claude_settings_before,
                old_claude_handlers,
                previous_port=previous_settings["listen_port"],
                previous_token=previous_settings["auth_token"],
                previous_version=previous_settings.get("recorder_version"),
            )
            if _sha256(claude_settings_after) != home_spec["settings"]["after_sha256"]:
                raise InstallerDrift("planned retired Claude settings output cannot be reproduced")
            retired_claude_home_outputs.append(
                {
                    "spec": home_spec,
                    "home": home,
                    "settings_path": claude_settings_path,
                    "settings_before": claude_settings_before,
                    "settings_after": claude_settings_after,
                }
            )
    result = {
        "source": source,
        "state": state,
        "install_root": install_root,
        "settings_path": settings_path,
        "settings_before": settings_before,
        "settings_after": settings_after,
        "launcher_path": launcher_path,
        "launcher_before": launcher_before,
        "launcher_after": launcher_after,
        "inventory_path": inventory_path,
        "inventory_before": inventory_before,
        "inventory_after": inventory_after,
        "homes": home_outputs,
        "claude_homes": claude_home_outputs,
        "retired_homes": retired_home_outputs,
        "retired_claude_homes": retired_claude_home_outputs,
    }
    _require_all_action_parents(plan)
    return result


def _journal_update(plan: InstallPlan, status_value: str, actions: List[Dict[str, Any]], error: Optional[str]) -> None:
    plan.journal["status"] = status_value
    plan.journal["updated_at_utc"] = _utc_now()
    plan.journal["actions"] = actions
    plan.journal["error"] = error
    payload = _json_bytes(plan.journal)
    if plan.transaction_anchor is not None:
        try:
            _atomic_write_held(
                plan.transaction_anchor,
                plan.journal_path.name,
                payload,
                mode=0o600,
                allow_detached=plan.allow_detached_transaction,
            )
        except InstallerConflict:
            resumable_statuses = {
                "apply-failed-rolling-back",
                "apply-failed-rolled-back",
                "apply-failed-rollback-blocked",
                "rolling-back",
                "rollback-blocked",
                "rolled-back",
            }
            if (
                status_value not in resumable_statuses
                or plan.transaction_anchor.descriptor is None
            ):
                raise
            _require_directory_anchor(
                plan.transaction_anchor,
                require_path=False,
            )
            plan.allow_detached_transaction = True
            _atomic_write_held(
                plan.transaction_anchor,
                plan.journal_path.name,
                payload,
                mode=0o600,
                allow_detached=True,
            )
        return
    with _lock_transaction_directory(
        plan.journal_path.parent,
        plan.journal["transaction_identity"],
    ) as anchor:
        _atomic_write_held(anchor, plan.journal_path.name, payload, mode=0o600)


def _maybe_fault(fault_after: Optional[int], mutations: int) -> None:
    if fault_after is not None and mutations >= fault_after:
        raise RuntimeError("injected installer failure after {} mutations".format(mutations))


def _action_position(action: Dict[str, Any]) -> str:
    """Classify an interrupted atomic mutation as before, after, or drifted."""

    path = Path(action["path"])
    _assert_no_link_components(path)
    if action["kind"] == "install-tree":
        if not path.exists():
            return "before" if not action["before_exists"] else "drift"
        if not path.is_dir():
            return "drift"
        try:
            digest = _installed_tree_digest(path)
        except InstallerError:
            return "drift"
        if digest == action["after_sha256"]:
            return "after"
        return "drift"
    if not path.exists():
        return "before" if not action["before_exists"] else "drift"
    if not path.is_file() or _is_link_or_reparse(path):
        return "drift"
    digest = _sha256(path.read_bytes())
    current_mode = stat.S_IMODE(path.stat().st_mode) if os.name != "nt" else None
    if digest == action["after_sha256"] and (
        os.name == "nt" or action.get("after_mode") is None or current_mode == action["after_mode"]
    ):
        return "after"
    if action["before_exists"] and digest == action["before_sha256"] and (
        os.name == "nt" or action.get("before_mode") is None or current_mode == action["before_mode"]
    ):
        return "before"
    return "drift"


def _lexical_exists(path: Path) -> bool:
    return os.path.lexists(str(path))


def _action_spec(action: Dict[str, Any], position: str) -> Dict[str, Any]:
    if position == "before":
        return {
            "exists": action["before_exists"],
            "sha256": action["before_sha256"],
            "mode": action["before_mode"],
        }
    if position == "after":
        return {
            "exists": True,
            "sha256": action["after_sha256"],
            "mode": action.get("after_mode"),
        }
    raise InstallerError("unknown action position")


def _path_matches_action(path: Path, action: Dict[str, Any], position: str) -> bool:
    spec = _action_spec(action, position)
    if not spec["exists"]:
        return not _lexical_exists(path)
    try:
        _assert_no_link_components(path)
        if action["kind"] == "install-tree":
            return (
                position == "after"
                and path.is_dir()
                and not _is_link_or_reparse(path)
                and _installed_tree_digest(path) == spec["sha256"]
                and _tree_is_read_only(path)
            )
        if not path.is_file() or _is_link_or_reparse(path):
            return False
        raw = path.read_bytes()
        if _sha256(raw) != spec["sha256"]:
            return False
        return (
            os.name == "nt"
            or spec["mode"] is None
            or stat.S_IMODE(path.stat().st_mode) == spec["mode"]
        )
    except (InstallerError, OSError):
        return False


def _classify_action_path(path: Path, action: Dict[str, Any]) -> str:
    if not _lexical_exists(path):
        return "missing"
    if _path_matches_action(path, action, "after"):
        return "after"
    if action["before_exists"] and _path_matches_action(path, action, "before"):
        return "before"
    return "other"


def _read_regular_child_held(
    anchor: _DirectoryAnchor,
    name: str,
) -> Tuple[bytes, Optional[int]]:
    child = _held_child_name(name)
    if anchor.descriptor is None:
        path = anchor.path / child
        if os.name == "nt":  # pragma: no cover - native Windows CI
            descriptor = _open_windows_regular_file_descriptor(
                path,
                require_single_link=False,
            )
            try:
                with os.fdopen(descriptor, "rb") as stream:
                    descriptor = -1
                    return stream.read(), None
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
        if not path.is_file() or _is_link_or_reparse(path):
            raise InstallerConflict("held child is not a real regular file")
        return path.read_bytes(), stat.S_IMODE(path.stat().st_mode)
    metadata = os.stat(child, dir_fd=anchor.descriptor, follow_symlinks=False)
    if not stat.S_ISREG(metadata.st_mode):
        raise InstallerConflict("held child is not a real regular file")
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(child, flags, dir_fd=anchor.descriptor)
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or _filesystem_identity(opened) != _filesystem_identity(metadata)
        ):
            raise InstallerConflict("held child changed while it was opened")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            raw = stream.read()
        return raw, stat.S_IMODE(opened.st_mode)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _held_tree_digest_and_readonly(
    anchor: _DirectoryAnchor,
    name: str,
) -> Tuple[str, bool]:
    child = _held_child_name(name)
    if anchor.descriptor is None:
        path = anchor.path / child
        if os.name == "nt":  # pragma: no cover - native Windows CI
            expected = _directory_identity(path, "installed runtime tree")
            handle = _open_windows_directory_handle(path, expected)
            try:
                return _installed_tree_digest(path), _tree_is_read_only(path)
            finally:
                _close_windows_handle(handle)
        return _installed_tree_digest(path), _tree_is_read_only(path)
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    root_descriptor = os.open(child, flags, dir_fd=anchor.descriptor)
    write_mask = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
    entries: List[Tuple[str, bytes]] = []
    readonly = not bool(os.fstat(root_descriptor).st_mode & write_mask)

    def open_directory(parent_descriptor: int, directory_name: str) -> int:
        metadata = os.stat(
            directory_name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if not stat.S_ISDIR(metadata.st_mode):
            raise InstallerConflict("installed runtime contains a non-directory payload node")
        descriptor = os.open(directory_name, flags, dir_fd=parent_descriptor)
        if _filesystem_identity(os.fstat(descriptor)) != _filesystem_identity(metadata):
            os.close(descriptor)
            raise InstallerConflict("installed runtime directory changed while opening")
        return descriptor

    def walk(directory_descriptor: int, prefix: str) -> None:
        nonlocal readonly
        if os.fstat(directory_descriptor).st_mode & write_mask:
            readonly = False
        for entry_name in sorted(os.listdir(directory_descriptor)):
            metadata = os.stat(
                entry_name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
            relative = entry_name if not prefix else prefix + "/" + entry_name
            if stat.S_ISDIR(metadata.st_mode):
                if entry_name == "__pycache__":
                    continue
                child_descriptor = open_directory(directory_descriptor, entry_name)
                try:
                    walk(child_descriptor, relative)
                finally:
                    os.close(child_descriptor)
                continue
            if (
                entry_name.endswith((".pyc", ".pyo"))
                or entry_name.endswith("_self_test.py")
            ):
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise InstallerConflict("installed runtime contains an unsafe payload node")
            file_flags = os.O_RDONLY
            if hasattr(os, "O_BINARY"):
                file_flags |= os.O_BINARY
            if hasattr(os, "O_NOFOLLOW"):
                file_flags |= os.O_NOFOLLOW
            descriptor = os.open(entry_name, file_flags, dir_fd=directory_descriptor)
            try:
                opened = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or _filesystem_identity(opened) != _filesystem_identity(metadata)
                ):
                    raise InstallerConflict("installed runtime file changed while opening")
                if opened.st_mode & write_mask:
                    readonly = False
                with os.fdopen(descriptor, "rb") as stream:
                    descriptor = -1
                    entries.append((relative, stream.read()))
            finally:
                if descriptor >= 0:
                    os.close(descriptor)

    try:
        recorder_raw, recorder_mode = _read_regular_child_from_directory_descriptor(
            root_descriptor,
            "recorder.py",
        )
        if recorder_mode & write_mask:
            readonly = False
        entries.append(("recorder.py", recorder_raw))
        for required_directory in ("contract", "delivery_efficiency"):
            directory_descriptor = open_directory(root_descriptor, required_directory)
            try:
                walk(directory_descriptor, required_directory)
            finally:
                os.close(directory_descriptor)
    finally:
        os.close(root_descriptor)
    entries.sort(key=lambda item: item[0])
    digest = hashlib.sha256()
    for relative, raw in entries:
        encoded_name = relative.encode("utf-8")
        digest.update(len(encoded_name).to_bytes(8, "big"))
        digest.update(encoded_name)
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest(), readonly


def _read_regular_child_from_directory_descriptor(
    directory_descriptor: int,
    name: str,
) -> Tuple[bytes, int]:
    metadata = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
    if not stat.S_ISREG(metadata.st_mode):
        raise InstallerConflict("installed runtime required file is unsafe")
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(name, flags, dir_fd=directory_descriptor)
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or _filesystem_identity(opened) != _filesystem_identity(metadata)
        ):
            raise InstallerConflict("installed runtime required file changed while opening")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            return stream.read(), opened.st_mode
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _classify_action_child_held(
    anchor: _DirectoryAnchor,
    name: str,
    action: Dict[str, Any],
) -> str:
    _require_directory_anchor(anchor)
    child = _held_child_name(name)
    try:
        if anchor.descriptor is not None:
            os.stat(child, dir_fd=anchor.descriptor, follow_symlinks=False)
        elif not _lexical_exists(anchor.path / child):
            return "missing"
    except FileNotFoundError:
        return "missing"
    try:
        if action["kind"] == "install-tree":
            digest, readonly = _held_tree_digest_and_readonly(anchor, child)
            if digest == action["after_sha256"] and readonly:
                return "after"
            return "other"
        raw, current_mode = _read_regular_child_held(anchor, child)
        digest = _sha256(raw)
        if digest == action["after_sha256"] and (
            os.name == "nt"
            or action.get("after_mode") is None
            or current_mode == action["after_mode"]
        ):
            return "after"
        if action["before_exists"] and digest == action["before_sha256"] and (
            os.name == "nt"
            or action.get("before_mode") is None
            or current_mode == action["before_mode"]
        ):
            return "before"
        return "other"
    except (InstallerError, OSError):
        return "other"


def _action_namespace(action: Dict[str, Any]) -> Dict[str, str]:
    return {
        "target": _classify_action_path(Path(action["path"]), action),
        "before": _classify_action_path(Path(action["before_path"]), action),
        "stage": _classify_action_path(Path(action["stage_path"]), action),
        "after": _classify_action_path(Path(action["after_path"]), action),
    }


def _held_action_namespace(plan: InstallPlan, action: Dict[str, Any]) -> Dict[str, str]:
    anchor = _anchor_for_action(plan, action)
    state = {
        "target": _classify_action_child_held(
            anchor,
            Path(action["path"]).name,
            action,
        ),
        "before": _classify_action_child_held(
            anchor,
            Path(action["before_path"]).name,
            action,
        ),
        "stage": _classify_action_child_held(
            anchor,
            Path(action["stage_path"]).name,
            action,
        ),
        "after": _classify_action_child_held(
            anchor,
            Path(action["after_path"]).name,
            action,
        ),
    }
    _require_directory_anchor(anchor)
    return state


def _journal_action_progress(
    plan: InstallPlan,
    action: Dict[str, Any],
    *,
    apply_state: Optional[str] = None,
    rollback_state: Optional[str] = None,
    blocked_reason: Optional[str] = None,
) -> None:
    if apply_state is not None:
        action["apply_state"] = apply_state
    if rollback_state is not None:
        action["rollback_state"] = rollback_state
    action["blocked_reason"] = blocked_reason
    _journal_update(
        plan,
        plan.journal["status"],
        plan.journal["actions"],
        plan.journal.get("error"),
    )


def _create_windows_staged_file(
    plan: InstallPlan,
    action: Dict[str, Any],
    path: Path,
    data: bytes,
    mode: int,
    anchor: _DirectoryAnchor,
) -> None:
    if anchor.windows_directory_handle is None:
        raise InstallerError("Windows target-parent handle is not held")
    try:
        handle = _create_windows_file_handle(
            anchor.windows_directory_handle,
            path.name,
            path,
        )
    except FileExistsError as error:
        raise InstallerDrift(
            "review-bound Windows file stage was occupied during creation"
        ) from error
    raw_handle = handle
    descriptor: Optional[int] = None
    try:
        import msvcrt

        descriptor = msvcrt.open_osfhandle(
            raw_handle,
            os.O_RDWR | getattr(os, "O_BINARY", 0),
        )
        raw_handle = -1
        metadata = os.fstat(descriptor)
        attributes = getattr(metadata, "st_file_attributes", 0)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or bool(
                attributes
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            )
        ):
            raise InstallerConflict(
                "new Windows stage handle is not one real regular file"
            )
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        handle = int(msvcrt.get_osfhandle(descriptor))
        _set_windows_handle_read_only(
            handle,
            not bool(mode & stat.S_IWUSR),
        )
        _remember_windows_stage_binding(
            plan,
            action,
            handle=handle,
            descriptor=descriptor,
        )
        descriptor = None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if raw_handle >= 0:
            _close_windows_handle(raw_handle)


def _create_staged_file(
    plan: InstallPlan,
    action: Dict[str, Any],
    path: Path,
    data: bytes,
    mode: int,
    anchor: _DirectoryAnchor,
) -> None:
    if _normalized_path_text(path.parent) != _normalized_path_text(anchor.path):
        raise InstallerConflict("staged file escaped its held target parent")
    _require_directory_anchor(anchor)
    if os.name == "nt":  # pragma: no cover - native Windows CI
        _create_windows_staged_file(plan, action, path, data, mode, anchor)
        _require_directory_anchor(anchor)
        return
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if anchor.descriptor is not None:
        descriptor = os.open(path.name, flags, mode, dir_fd=anchor.descriptor)
    else:
        descriptor = os.open(str(path), flags, mode)
    try:
        if os.name != "nt":
            os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if anchor.descriptor is not None:
        os.fsync(anchor.descriptor)
    else:
        _fsync_directory(anchor.path)
    _require_directory_anchor(anchor)


def _prepare_action_stage(
    plan: InstallPlan,
    action: Dict[str, Any],
    *,
    source: Optional[Path] = None,
    data: Optional[bytes] = None,
) -> None:
    stage = Path(action["stage_path"])
    anchor = _anchor_for_action(plan, action)
    classification = _classify_action_child_held(anchor, stage.name, action)
    if classification == "after":
        _ensure_windows_stage_binding(plan, action)
        return
    if classification != "missing":
        raise InstallerDrift("review-bound apply stage is occupied by unexpected data")
    if action["kind"] == "install-tree":
        if source is None:
            raise InstallerError("install-tree staging requires its reviewed source")
        stage_handle = _copy_payload_to_held_stage(
            source,
            stage,
            action["after_sha256"],
            anchor,
        )
        if stage_handle is not None:
            try:
                _remember_windows_stage_binding(
                    plan,
                    action,
                    handle=stage_handle,
                    descriptor=None,
                )
            except BaseException:
                _close_windows_handle(stage_handle)
                raise
    else:
        if data is None:
            raise InstallerError("file staging requires reviewed output bytes")
        mode = action["after_mode"] if action["after_mode"] is not None else 0o600
        _create_staged_file(plan, action, stage, data, mode, anchor)
    _require_directory_anchor(anchor)
    if _classify_action_child_held(anchor, stage.name, action) != "after":
        raise InstallerVerificationError("review-bound apply stage failed verification")
    _ensure_windows_stage_binding(plan, action)


def _apply_namespace_case(plan: InstallPlan, action: Dict[str, Any]) -> str:
    state = _held_action_namespace(plan, action)
    if state["after"] != "missing":
        return "blocked"
    if action["before_exists"]:
        if state == {"target": "before", "before": "missing", "stage": "missing", "after": "missing"}:
            return "unstaged"
        if state == {"target": "before", "before": "missing", "stage": "after", "after": "missing"}:
            return "prepared"
        if state == {"target": "missing", "before": "before", "stage": "after", "after": "missing"}:
            return "captured"
        if state == {"target": "after", "before": "before", "stage": "missing", "after": "missing"}:
            return "applied"
        if state["target"] == "other" and state["before"] == "missing" and state["stage"] == "after":
            return "conflict-restored"
    else:
        if state == {"target": "missing", "before": "missing", "stage": "missing", "after": "missing"}:
            return "unstaged"
        if state == {"target": "missing", "before": "missing", "stage": "after", "after": "missing"}:
            return "prepared"
        if state == {"target": "after", "before": "missing", "stage": "missing", "after": "missing"}:
            return "applied"
        if state["target"] == "other" and state["before"] == "missing" and state["stage"] == "after":
            return "conflict-restored"
    return "blocked"


def _restore_captured_apply_conflict(plan: InstallPlan, action: Dict[str, Any]) -> None:
    target = Path(action["path"])
    before = Path(action["before_path"])
    state = _held_action_namespace(plan, action)
    if state["target"] == "missing" and state["before"] in {"before", "other"}:
        _atomic_move_no_replace(
            before,
            target,
            anchor=_anchor_for_action(plan, action),
        )
        state = _held_action_namespace(plan, action)
    if state["before"] == "missing" and state["target"] in {"before", "other"}:
        action["applied"] = False
        _journal_action_progress(
            plan,
            action,
            apply_state="conflict-restored",
            blocked_reason="apply-target-changed-at-capture",
        )
        raise InstallerDrift("apply target changed at capture; competing data was restored")
    _journal_action_progress(
        plan,
        action,
        apply_state="blocked",
        blocked_reason="apply-capture-recovery-required",
    )
    raise InstallerDrift("apply capture is incomplete; all namespace occupants were retained")


def _apply_one_action(
    plan: InstallPlan,
    action: Dict[str, Any],
    *,
    source: Optional[Path] = None,
    data: Optional[bytes] = None,
    mutation_guard: Optional[Callable[[], None]] = None,
) -> None:
    if not action["changed"]:
        action["applied"] = False
        action["apply_state"] = "unchanged"
        return
    case = _apply_namespace_case(plan, action)
    if case == "unstaged":
        _journal_action_progress(plan, action, apply_state="preparing")
        _prepare_action_stage(plan, action, source=source, data=data)
        _journal_action_progress(plan, action, apply_state="prepared")
        case = _apply_namespace_case(plan, action)
    if case == "applied":
        action["applied"] = True
        _journal_action_progress(plan, action, apply_state="applied")
        return
    if case == "conflict-restored":
        action["applied"] = False
        _journal_action_progress(
            plan,
            action,
            apply_state="conflict-restored",
            blocked_reason="apply-target-changed",
        )
        raise InstallerDrift("apply target changed; competing data was preserved")
    if case == "blocked":
        _journal_action_progress(
            plan,
            action,
            apply_state="blocked",
            blocked_reason="apply-namespace-unclassifiable",
        )
        raise InstallerDrift("apply namespace is not a safe resumable state")

    if action["before_exists"]:
        _journal_action_progress(plan, action, apply_state="capture-intent")
        if _apply_namespace_case(plan, action) != "prepared":
            raise InstallerDrift("apply target changed before capture")
        _atomic_move_no_replace(
            Path(action["path"]),
            Path(action["before_path"]),
            anchor=_anchor_for_action(plan, action),
            mutation_guard=mutation_guard,
        )
        state = _held_action_namespace(plan, action)
        if state["target"] != "missing" or state["before"] != "before":
            _restore_captured_apply_conflict(plan, action)
        _journal_action_progress(plan, action, apply_state="captured")

    _journal_action_progress(plan, action, apply_state="publish-intent")
    state = _held_action_namespace(plan, action)
    expected_before_slot = "before" if action["before_exists"] else "missing"
    if not (
        state["target"] == "missing"
        and state["before"] == expected_before_slot
        and state["stage"] == "after"
        and state["after"] == "missing"
    ):
        if not action["before_exists"] and state["target"] == "other":
            action["applied"] = False
            _journal_action_progress(
                plan,
                action,
                apply_state="conflict-restored",
                blocked_reason="apply-absent-target-occupied",
            )
            raise InstallerDrift("apply destination was occupied; competing data was preserved")
        _journal_action_progress(
            plan,
            action,
            apply_state="blocked",
            blocked_reason="apply-publish-boundary-changed",
        )
        raise InstallerDrift("apply publish boundary changed; artifacts were retained")
    anchor = _anchor_for_action(plan, action)
    _publish_prepared_stage_no_replace(
        plan,
        action,
        anchor,
        mutation_guard=mutation_guard,
    )
    if _apply_namespace_case(plan, action) != "applied":
        _journal_action_progress(
            plan,
            action,
            apply_state="blocked",
            blocked_reason="apply-publish-unclassifiable",
        )
        raise InstallerDrift("apply publication could not be classified; artifacts were retained")
    action["applied"] = True
    _journal_action_progress(plan, action, apply_state="applied")


def _recover_interrupted_apply(plan: InstallPlan) -> None:
    """Classify bound namespace slots, then finish failure rollback."""

    with _held_installation_serialization(plan):
        actions = plan.journal["actions"]
        _journal_update(
            plan,
            "apply-failed-rolling-back",
            actions,
            "interrupted-apply-recovered",
        )
        try:
            _reconcile_apply_action_positions(plan, actions)
            _rollback_actions(
                plan,
                actions,
                require_applied=False,
                apply_failure=True,
            )
        except Exception as error:
            _journal_update(
                plan,
                "apply-failed-rollback-blocked",
                actions,
                type(error).__name__,
            )
            raise


def _reconcile_apply_action_positions(
    plan: InstallPlan,
    actions: List[Dict[str, Any]],
) -> None:
    """Derive applied state from target plus immutable adjacent slots."""

    for action in actions:
        if not action.get("changed"):
            action["applied"] = False
            action["apply_state"] = "unchanged"
            continue
        case = _apply_namespace_case(plan, action)
        if case == "applied":
            action["applied"] = True
            action["apply_state"] = "applied"
            continue
        if case in {"unstaged", "prepared", "conflict-restored"}:
            action["applied"] = False
            if case == "conflict-restored":
                action["apply_state"] = "conflict-restored"
            continue
        if case == "captured" and action["before_exists"]:
            _journal_action_progress(
                plan,
                action,
                apply_state="capture-intent",
                blocked_reason="interrupted-before-publish",
            )
            _atomic_move_no_replace(
                Path(action["before_path"]),
                Path(action["path"]),
                anchor=_anchor_for_action(plan, action),
            )
            if _apply_namespace_case(plan, action) not in {"prepared", "unstaged"}:
                _journal_action_progress(
                    plan,
                    action,
                    apply_state="blocked",
                    blocked_reason="interrupted-apply-restore-unclassifiable",
                )
                raise InstallerDrift("interrupted apply could not restore its captured target")
            action["applied"] = False
            action["apply_state"] = "conflict-restored"
            continue
        _journal_action_progress(
            plan,
            action,
            apply_state="blocked",
            blocked_reason="interrupted-apply-namespace-unclassifiable",
        )
        raise InstallerDrift("interrupted apply namespace cannot be reconciled safely")
    _journal_update(
        plan,
        plan.journal["status"],
        actions,
        plan.journal.get("error"),
    )


def _activate_receiver(state: Path) -> None:
    """Require one authenticated healthy installed receiver before commit.

    The shared runtime lifecycle refuses occupied unknown ports and never
    signals an unverified PID. Any exception remains inside the surrounding
    install transaction so its exact configuration actions are rolled back.
    """

    from .runtime import ensure_receiver, receiver_is_healthy

    settings = ensure_receiver(state, timeout_seconds=10.0)
    if not receiver_is_healthy(settings, timeout_seconds=1.0):
        raise InstallerVerificationError(
            "installed loopback receiver failed its authenticated health check"
        )


def apply_install(
    value: Union[InstallPlan, str, os.PathLike[str]],
    *,
    fault_after: Optional[int] = None,
    plan_digest: Optional[str] = None,
    mutation_guard: Optional[Callable[[], None]] = None,
    require_planned: bool = False,
) -> Dict[str, Any]:
    """Apply a plan transactionally; telemetry failure never changes source."""

    with _locked_operation_plan(
        value,
        expected_plan_digest=plan_digest,
    ) as plan:
        with _held_target_parents(plan):
            return _apply_install_held(
                plan,
                fault_after=fault_after,
                mutation_guard=mutation_guard,
                require_planned=require_planned,
            )


def _apply_install_held(
    plan: InstallPlan,
    *,
    fault_after: Optional[int],
    mutation_guard: Optional[Callable[[], None]],
    require_planned: bool,
) -> Dict[str, Any]:
    """Apply while the transaction and every target parent remain held."""

    _require_all_action_parents(plan)
    status_value = plan.journal.get("status")
    if require_planned and status_value != "planned":
        raise InstallerConflict(
            "plan status must be planned for this apply: {}".format(status_value)
        )
    if status_value == "applying":
        _recover_interrupted_apply(plan)
    if plan.journal.get("status") == "applied":
        result = _verify_install_held(plan)
        if mutation_guard is not None:
            mutation_guard()
        _activate_receiver(_state_path(plan.journal["target"]["state_root"]))
        result["receiver_healthy"] = True
        return result
    if plan.journal.get("status") != "planned":
        raise InstallerConflict("plan status is not applicable: {}".format(plan.journal.get("status")))
    prepared = _prepare_apply(plan)  # All malformed/conflicting files fail before mutation.
    state: Path = prepared["state"]
    actions: List[Dict[str, Any]] = plan.journal["actions"]
    mutations = 0

    with _held_installation_serialization(plan):
        # Repeat the complete preflight under the process lock.
        prepared = _prepare_apply(plan)
        for action in actions:
            if not action["changed"]:
                continue
            anchor = _anchor_for_action(plan, action)
            for field in ("stage_path", "before_path", "after_path"):
                artifact = Path(action[field])
                if (
                    _classify_action_child_held(
                        anchor,
                        artifact.name,
                        action,
                    )
                    != "missing"
                ):
                    raise InstallerConflict(
                        "review-bound transaction artifact is occupied before apply"
                    )
        if mutation_guard is not None:
            mutation_guard()
        _journal_update(plan, "applying", actions, None)

        try:
            outputs: Dict[Tuple[str, str], bytes] = {
                ("settings", "recorder"): prepared["settings_after"],
                ("launcher", "stable"): prepared["launcher_after"],
                ("managed-targets", "inventory"): prepared["inventory_after"],
            }
            for home in prepared["homes"]:
                name = home["spec"]["name"]
                outputs[("hooks", name)] = home["hooks_after"]
                outputs[("otel-config", name)] = home["config_after"]
            for home in prepared["claude_homes"]:
                outputs[("claude-settings", home["spec"]["name"])] = home["settings_after"]
            for home in prepared["retired_homes"]:
                name = home["spec"]["name"]
                outputs[("retired-hooks", name)] = home["hooks_after"]
                outputs[("retired-otel-config", name)] = home["config_after"]
            for home in prepared["retired_claude_homes"]:
                outputs[("retired-claude-settings", home["spec"]["name"])] = home[
                    "settings_after"
                ]
            for action in actions:
                if not action["changed"]:
                    continue
                if source_tree_digest(prepared["source"]) != plan.journal["source"]["payload_sha256"]:
                    raise InstallerDrift("source runtime payload changed before a configuration mutation")
                if mutation_guard is not None:
                    mutation_guard()
                if action["kind"] == "install-tree":
                    _apply_one_action(
                        plan,
                        action,
                        source=prepared["source"],
                        mutation_guard=mutation_guard,
                    )
                else:
                    _apply_one_action(
                        plan,
                        action,
                        data=outputs[(action["kind"], action["name"])],
                        mutation_guard=mutation_guard,
                    )
                mutations += 1
                _maybe_fault(fault_after, mutations)
            if source_tree_digest(prepared["source"]) != plan.journal["source"]["payload_sha256"]:
                raise InstallerDrift("source runtime payload changed during apply")
            for action in actions:
                _verify_action_after(plan, action)
            if mutation_guard is not None:
                mutation_guard()
            _activate_receiver(state)
            for action in actions:
                _verify_action_after(plan, action)
            if mutation_guard is not None:
                mutation_guard()
            _journal_update(plan, "applied", actions, None)
        except BaseException as error:
            # POSIX keeps the reviewed transaction directory reachable through
            # its held descriptor even if another writer renames its pathname.
            # Failure recovery writes only through that descriptor; success
            # can never commit while the reviewed path is detached.
            plan.allow_detached_transaction = True
            try:
                _journal_update(
                    plan,
                    "apply-failed-rolling-back",
                    actions,
                    type(error).__name__,
                )
                _reconcile_apply_action_positions(plan, actions)
                _rollback_actions(
                    plan,
                    actions,
                    require_applied=False,
                    apply_failure=True,
                )
            except Exception as rollback_error:
                _journal_update(
                    plan,
                    "apply-failed-rollback-blocked",
                    actions,
                    "{}; rollback blocked: {}".format(type(error).__name__, type(rollback_error).__name__),
                )
                raise InstallerError("apply failed and exact rollback was blocked") from rollback_error
            raise
    result = _verify_install_held(plan)
    result["receiver_healthy"] = True
    return result


def _verify_action_after(plan: InstallPlan, action: Dict[str, Any]) -> None:
    anchor = _anchor_for_action(plan, action)
    path = Path(action["path"])
    if _classify_action_child_held(anchor, path.name, action) != "after":
        raise InstallerVerificationError(
            "installed action is missing, unsafe, or drifted: {}".format(path)
        )
    _require_directory_anchor(anchor)


def verify_install(
    value: Union[InstallPlan, str, os.PathLike[str]],
    *,
    plan_digest: Optional[str] = None,
) -> Dict[str, Any]:
    """Verify immutable installed bytes, token binding, and configured homes.

    Canonical source is plan/apply input, not post-install runtime state. Apply
    revalidates its reviewed digest at every mutation boundary; later source
    changes must not invalidate the independently hash-bound immutable copy.
    """

    with _locked_operation_plan(
        value,
        expected_plan_digest=plan_digest,
    ) as plan:
        with _held_target_parents(plan):
            return _verify_install_held(plan)


def _verify_install_held(plan: InstallPlan) -> Dict[str, Any]:
    """Verify while the transaction and every target parent remain held."""

    _require_transaction_attached(plan)
    _require_all_action_parents(plan)
    if plan.journal.get("status") != "applied":
        raise InstallerVerificationError("transaction is not in applied state")
    for action in plan.journal.get("actions", []):
        _verify_action_after(plan, action)
        if action["changed"] and (
            not action["applied"]
            or action["apply_state"] != "applied"
            or _rollback_namespace_case(plan, action) != "applied"
        ):
            raise InstallerVerificationError(
                "installed action namespace does not match its reviewed plan"
            )
    settings_action = next(
        action
        for action in plan.journal["actions"]
        if action["kind"] == "settings" and action["name"] == "recorder"
    )
    settings_raw, _settings_mode = _read_regular_child_held(
        _anchor_for_action(plan, settings_action),
        Path(settings_action["path"]).name,
    )
    settings = _load_json_object(
        settings_raw,
        "installed recorder settings",
        maximum=64 * 1024,
    )
    if _sha256(str(settings.get("auth_token", "")).encode("ascii")) != plan.journal["receiver"]["auth_token_sha256"]:
        raise InstallerVerificationError("installed settings token does not match the journal")
    result = {
        "ok": True,
        "status": "applied",
        "plan_id": plan.journal["plan_id"],
        "plan_sha256": plan.plan_digest,
        "payload_sha256": plan.journal["source"]["payload_sha256"],
        "codex_homes": [home["name"] for home in plan.journal["codex_homes"]],
        "claude_homes": [home["name"] for home in plan.journal.get("claude_homes", [])],
        "retired_codex_homes": [
            home["name"] for home in plan.journal.get("retired_codex_homes", [])
        ],
        "retired_claude_homes": [
            home["name"] for home in plan.journal.get("retired_claude_homes", [])
        ],
        "managed_target_count": len(
            plan.journal["target"]["managed_targets"]["after"]
        ),
        "windows_acl_hardened": False,
        "retained_artifacts": _retained_artifacts(plan, plan.journal["actions"]),
    }
    _require_transaction_attached(plan)
    return result


def _rollback_namespace_case(plan: InstallPlan, action: Dict[str, Any]) -> str:
    state = _held_action_namespace(plan, action)
    if state["stage"] != "missing":
        return "blocked"
    if action["before_exists"]:
        if state == {"target": "after", "before": "before", "stage": "missing", "after": "missing"}:
            return "applied"
        if state == {"target": "missing", "before": "before", "stage": "missing", "after": "after"}:
            return "captured"
        if state == {"target": "before", "before": "missing", "stage": "missing", "after": "after"}:
            return "restored"
    else:
        if state == {"target": "after", "before": "missing", "stage": "missing", "after": "missing"}:
            return "applied"
        if state == {"target": "missing", "before": "missing", "stage": "missing", "after": "after"}:
            return "restored"
    return "blocked"


def _rollback_one_action(plan: InstallPlan, action: Dict[str, Any]) -> None:
    case = _rollback_namespace_case(plan, action)
    if case == "restored":
        _journal_action_progress(plan, action, rollback_state="restored")
        return
    if case == "blocked":
        state = _held_action_namespace(plan, action)
        # A writer raced exactly at capture. Move the captured object back only
        # into an absent target; otherwise retain both names and stop.
        if state["target"] == "missing" and state["after"] == "other":
            _atomic_move_no_replace(
                Path(action["after_path"]),
                Path(action["path"]),
                anchor=_anchor_for_action(plan, action),
            )
            state = _held_action_namespace(plan, action)
        _journal_action_progress(
            plan,
            action,
            rollback_state="blocked",
            blocked_reason="rollback-namespace-unclassifiable",
        )
        raise InstallerDrift("rollback namespace changed; every occupant was preserved")

    if case == "applied":
        _journal_action_progress(plan, action, rollback_state="capture-intent")
        if _rollback_namespace_case(plan, action) != "applied":
            raise InstallerDrift("rollback target changed before capture")
        _atomic_move_no_replace(
            Path(action["path"]),
            Path(action["after_path"]),
            anchor=_anchor_for_action(plan, action),
        )
        state = _held_action_namespace(plan, action)
        if state["target"] != "missing" or state["after"] != "after":
            if state["target"] == "missing" and state["after"] == "other":
                _atomic_move_no_replace(
                    Path(action["after_path"]),
                    Path(action["path"]),
                    anchor=_anchor_for_action(plan, action),
                )
            _journal_action_progress(
                plan,
                action,
                rollback_state="blocked",
                blocked_reason="rollback-capture-changed",
            )
            raise InstallerDrift("rollback captured competing data and preserved it")
        _journal_action_progress(plan, action, rollback_state="captured")
        case = "captured" if action["before_exists"] else "restored"

    if case == "captured":
        _journal_action_progress(plan, action, rollback_state="restore-intent")
        if _rollback_namespace_case(plan, action) != "captured":
            raise InstallerDrift("rollback restore boundary changed")
        _atomic_move_no_replace(
            Path(action["before_path"]),
            Path(action["path"]),
            anchor=_anchor_for_action(plan, action),
        )
        if _rollback_namespace_case(plan, action) != "restored":
            _journal_action_progress(
                plan,
                action,
                rollback_state="blocked",
                blocked_reason="rollback-restore-unclassifiable",
            )
            raise InstallerDrift("rollback restore could not be classified; artifacts were retained")
    if _rollback_namespace_case(plan, action) != "restored":
        raise InstallerVerificationError("rollback action did not reach its exact prior state")
    _journal_action_progress(plan, action, rollback_state="restored")


def _retained_artifacts(
    plan: InstallPlan,
    actions: Sequence[Dict[str, Any]],
) -> List[Dict[str, str]]:
    artifacts: List[Dict[str, str]] = []
    expected_classification = {
        "stage_path": "after",
        "before_path": "before",
        "after_path": "after",
    }
    for action in actions:
        anchor = _anchor_for_action(plan, action)
        for field, role in (
            ("stage_path", "stage"),
            ("before_path", "before"),
            ("after_path", "after"),
        ):
            path = Path(action[field])
            classification = _classify_action_child_held(
                anchor,
                path.name,
                action,
            )
            if classification == "missing":
                continue
            if classification != expected_classification[field]:
                raise InstallerVerificationError(
                    "retained transaction artifact changed: {}".format(path)
                )
            artifacts.append(
                {
                    "action_id": action["id"],
                    "role": role,
                    "path": str(path),
                    "classification": classification,
                }
            )
        _require_directory_anchor(anchor)
    return artifacts


def _rollback_actions(
    plan: InstallPlan,
    actions: List[Dict[str, Any]],
    *,
    require_applied: bool,
    apply_failure: bool = False,
) -> None:
    current_status = plan.journal.get("status")
    if require_applied:
        allowed = {"applied", "rolling-back", "rollback-blocked"}
        if current_status not in allowed:
            raise InstallerConflict("transaction is not in a resumable rollback state")
    else:
        allowed = {
            "applying",
            "apply-failed-rolling-back",
            "apply-failed-rollback-blocked",
        }
        if current_status not in allowed:
            raise InstallerConflict("failed apply is not in a resumable rollback state")

    first_pass = current_status in {"applied", "applying"}
    if first_pass:
        for action in actions:
            if not action["changed"] or not action["applied"]:
                action["rollback_state"] = "restored"
                continue
            if _rollback_namespace_case(plan, action) != "applied":
                raise InstallerVerificationError(
                    "rollback preflight found non-applied namespace state"
                )
            action["rollback_state"] = "pending"
            action["blocked_reason"] = None
    active_status = "apply-failed-rolling-back" if apply_failure else "rolling-back"
    blocked_status = "apply-failed-rollback-blocked" if apply_failure else "rollback-blocked"
    terminal_status = "apply-failed-rolled-back" if apply_failure else "rolled-back"
    _journal_update(plan, active_status, actions, plan.journal.get("error"))
    try:
        for action in reversed(actions):
            if not action["changed"] or not action["applied"]:
                if action["rollback_state"] != "restored":
                    _journal_action_progress(plan, action, rollback_state="restored")
                continue
            _rollback_one_action(plan, action)
        for action in actions:
            if action["changed"] and action["applied"]:
                if _rollback_namespace_case(plan, action) != "restored":
                    raise InstallerVerificationError(
                        "rollback completion contains an unresolved action"
                    )
        _retained_artifacts(plan, actions)
    except Exception as error:
        _journal_update(plan, blocked_status, actions, type(error).__name__)
        raise
    _journal_update(plan, terminal_status, actions, plan.journal.get("error"))

def rollback_install(
    value: Union[InstallPlan, str, os.PathLike[str]],
    *,
    plan_digest: Optional[str] = None,
) -> Dict[str, Any]:
    """Restore exact prior bytes only while every installed digest still matches."""

    with _locked_operation_plan(
        value,
        expected_plan_digest=plan_digest,
    ) as plan:
        with _held_target_parents(plan):
            return _rollback_install_held(plan)


def _rollback_install_held(plan: InstallPlan) -> Dict[str, Any]:
    """Roll back while the transaction and every target parent remain held."""

    _require_all_action_parents(plan)
    with _held_installation_serialization(plan):
        actions = plan.journal.get("actions", [])
        _rollback_actions(plan, actions, require_applied=True)
    result = {
        "ok": True,
        "status": "rolled-back",
        "plan_id": plan.journal["plan_id"],
        "plan_sha256": plan.plan_digest,
        "retained_artifacts": _retained_artifacts(plan, actions),
    }
    _require_transaction_attached(plan)
    return result


__all__ = [
    "AUTH_HEADER",
    "CLAUDE_HOOK_EVENTS",
    "DEFAULT_LISTEN_PORT",
    "HOOK_EVENTS",
    "InstallPlan",
    "InstallerConflict",
    "InstallerDrift",
    "InstallerError",
    "InstallerTransactionIdentityConflict",
    "InstallerVerificationError",
    "MANAGED_ID",
    "apply_install",
    "build_posix_hook_command",
    "build_windows_hook_command",
    "load_plan",
    "plan_install",
    "rollback_install",
    "save_plan",
    "source_tree_digest",
    "stable_launcher_bytes",
    "verify_install",
]
