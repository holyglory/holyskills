#!/usr/bin/env python3
"""Emit a bounded, journal-bound receipt for fresh hook/task correlation."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import sys
import tempfile
import time
from typing import Any, Dict, Iterable, Iterator, Mapping, Optional, Tuple, Union


RUNTIMES = ("codex", "claude")
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
TOOL_ROOT = REPOSITORY_ROOT / "tools" / "delivery-efficiency"
RuntimeValue = Union[int, bool, str, None]
_LOWER_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_MAX_PLAN_BYTES = 8 * 1024 * 1024
_MAX_REPORT_BYTES = 1024 * 1024
_MAX_WATCH_SECONDS = 900
_DEFAULT_WATCH_SECONDS = 300
_REPORT_SCHEMA_VERSION = 1


class ActivationStatusError(RuntimeError):
    """The reviewed recorder installation cannot be inspected safely."""


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


def _assert_no_link_components(path: Path) -> None:
    absolute = Path(os.path.abspath(str(path)))
    if not absolute.is_absolute() or not absolute.parts:
        raise ActivationStatusError("reviewed path is not absolute")
    current = Path(absolute.parts[0])
    for part in absolute.parts[1:]:
        current = current / part
        if _is_link_or_reparse(current):
            raise ActivationStatusError("reviewed path contains a link or reparse point")
        if not current.exists():
            raise ActivationStatusError("reviewed path is missing")


def _payload_files(source_root: Path) -> list[Tuple[Path, str]]:
    _assert_no_link_components(source_root)
    required = (
        source_root / "recorder.py",
        source_root / "contract",
        source_root / "delivery_efficiency",
    )
    if not required[0].is_file() or not required[1].is_dir() or not required[2].is_dir():
        raise ActivationStatusError("reviewed recorder payload is incomplete")
    entries: list[Tuple[Path, str]] = []
    for root in required:
        _assert_no_link_components(root)
        if root.is_file():
            entries.append((root, root.relative_to(source_root).as_posix()))
            continue
        for directory, directory_names, file_names in os.walk(
            str(root), topdown=True, followlinks=False
        ):
            directory_path = Path(directory)
            _assert_no_link_components(directory_path)
            kept_directories = []
            for name in sorted(directory_names):
                child = directory_path / name
                if _is_link_or_reparse(child):
                    raise ActivationStatusError("reviewed payload contains a link or reparse point")
                if name != "__pycache__":
                    kept_directories.append(name)
            directory_names[:] = kept_directories
            for name in sorted(file_names):
                path = directory_path / name
                if _is_link_or_reparse(path):
                    raise ActivationStatusError("reviewed payload contains a link or reparse point")
                if name.endswith((".pyc", ".pyo")) or name.endswith("_self_test.py"):
                    continue
                metadata = path.lstat()
                if not stat.S_ISREG(metadata.st_mode):
                    raise ActivationStatusError("reviewed payload contains a non-regular file")
                entries.append((path, path.relative_to(source_root).as_posix()))
    entries.sort(key=lambda item: item[1])
    return entries


def _payload_digest(source_root: Path) -> str:
    digest = hashlib.sha256()
    for path, relative in _payload_files(source_root):
        raw = path.read_bytes()
        encoded_name = relative.encode("utf-8")
        digest.update(len(encoded_name).to_bytes(8, "big"))
        digest.update(encoded_name)
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode(
        "utf-8"
    )


def _read_regular_bounded(path: Path, maximum: int) -> bytes:
    _assert_no_link_components(path)
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > maximum:
        raise ActivationStatusError("reviewed plan file is unsafe or oversized")
    raw = path.read_bytes()
    if len(raw) > maximum:
        raise ActivationStatusError("reviewed plan file is oversized")
    return raw


def _same_path(first: Path, second: Path) -> bool:
    return os.path.normcase(os.path.abspath(str(first))) == os.path.normcase(
        os.path.abspath(str(second))
    )


def _preflight_reviewed_payload(journal: Path, plan_digest: str) -> Tuple[Path, str]:
    """Validate reviewed payload bytes without importing recorder-owned code."""

    if not journal.is_absolute() or journal.name != "journal.json":
        raise ActivationStatusError("journal path is not the reviewed journal child")
    if not isinstance(plan_digest, str) or not _LOWER_HEX_64.fullmatch(plan_digest):
        raise ActivationStatusError("reviewed plan digest is invalid")
    plan_path = journal.with_name("plan.json")
    raw = _read_regular_bounded(plan_path, _MAX_PLAN_BYTES)
    if hashlib.sha256(raw).hexdigest() != plan_digest:
        raise ActivationStatusError("immutable plan digest does not match review")
    try:
        immutable_plan = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ActivationStatusError("immutable plan is not canonical JSON") from error
    if not isinstance(immutable_plan, dict) or raw != _canonical_json_bytes(immutable_plan):
        raise ActivationStatusError("immutable plan is not canonical JSON")
    if immutable_plan.get("install_plan_schema_version") != 1:
        raise ActivationStatusError("immutable plan schema is unsupported")
    if immutable_plan.get("journal_path") != str(journal):
        raise ActivationStatusError("immutable plan does not bind this journal")
    try:
        source = Path(immutable_plan["source"]["root"])
        expected_digest = immutable_plan["source"]["payload_sha256"]
        install_root = Path(immutable_plan["target"]["install_root"])
    except (KeyError, TypeError) as error:
        raise ActivationStatusError("immutable plan omits recorder payload bindings") from error
    if not isinstance(expected_digest, str) or not _LOWER_HEX_64.fullmatch(expected_digest):
        raise ActivationStatusError("immutable plan payload digest is invalid")
    _assert_no_link_components(TOOL_ROOT)
    _assert_no_link_components(source)
    _assert_no_link_components(install_root)
    expected_source = TOOL_ROOT.resolve(strict=True)
    if not _same_path(source.resolve(strict=True), expected_source):
        raise ActivationStatusError("journal source is not this canonical recorder")
    if _payload_digest(expected_source) != expected_digest:
        raise ActivationStatusError("canonical recorder changed after review")
    if _payload_digest(install_root.resolve(strict=True)) != expected_digest:
        raise ActivationStatusError("installed recorder differs from reviewed payload")
    return install_root.resolve(strict=True), expected_digest


def _empty_runtime() -> Dict[str, RuntimeValue]:
    return {
        "events": 0,
        "hook_events": 0,
        "task_starts": 0,
        "usage_events": 0,
        "task_bound_usage": 0,
        "correlated_tasks": 0,
        "terminal_declarations": 0,
        "coverage_gaps": 0,
        "latest_sequence": None,
        "latest_observed_at_utc": None,
        "active": False,
    }


def _sequence(event: Mapping[str, Any]) -> int:
    try:
        sequence = int(event["sequence"])
    except (KeyError, TypeError, ValueError) as error:
        raise ActivationStatusError("verified event has no valid sequence") from error
    if sequence < 0:
        raise ActivationStatusError("verified event has a negative sequence")
    return sequence


def summarize_events(
    events: Iterable[Mapping[str, Any]],
    *,
    after_sequence: int,
    selected_runtime: str,
    expected_targets: Optional[Mapping[str, str]] = None,
) -> Dict[str, object]:
    """Summarize strict adapter tuples without returning opaque identities."""

    summaries = {runtime: _empty_runtime() for runtime in RUNTIMES}
    started_tasks = {runtime: set() for runtime in RUNTIMES}
    usage_tasks = {runtime: set() for runtime in RUNTIMES}
    hook_tasks = {runtime: set() for runtime in RUNTIMES}
    target_started = {
        name: set() for name in (expected_targets or {})
    }
    target_hooks = {
        name: set() for name in (expected_targets or {})
    }
    target_usage = {
        name: set() for name in (expected_targets or {})
    }
    target_hook_counts = {
        name: 0 for name in (expected_targets or {})
    }
    task_target_names: Dict[str, set[str]] = {}
    expected_by_id = {
        value: name for name, value in (expected_targets or {}).items()
    }
    if len(expected_by_id) != len(expected_targets or {}):
        raise ActivationStatusError("reviewed runtime targets are not unique")
    legacy_codex_hook_events = 0
    unrecognized_target_hook_events = 0
    max_sequence = 0
    selected = set(RUNTIMES if selected_runtime == "all" else (selected_runtime,))

    for event in events:
        if not isinstance(event, Mapping):
            raise ActivationStatusError("verified event is not an object")
        sequence = _sequence(event)
        max_sequence = max(max_sequence, sequence)
        if sequence <= after_sequence:
            continue

        runtime = event.get("runtime")
        family = runtime.get("family") if isinstance(runtime, Mapping) else None
        if family not in selected:
            continue
        summary = summaries[family]
        summary["events"] = int(summary["events"]) + 1
        summary["latest_sequence"] = str(sequence)
        observed = event.get("observed_at_utc")
        summary["latest_observed_at_utc"] = (
            observed if isinstance(observed, str) else None
        )

        adapter = event.get("adapter")
        adapter_name = adapter.get("name") if isinstance(adapter, Mapping) else None
        event_name = event.get("event")
        identity = event.get("identity")
        task_id = identity.get("task_id") if isinstance(identity, Mapping) else None
        target_id = identity.get("target_id") if isinstance(identity, Mapping) else None
        payload = event.get("payload")
        source_event = (
            payload.get("source_event") if isinstance(payload, Mapping) else None
        )
        measurement = event.get("measurement")
        counter_source = (
            measurement.get("counter_source")
            if isinstance(measurement, Mapping)
            else None
        )
        measurement_provenance = (
            measurement.get("provenance")
            if isinstance(measurement, Mapping)
            else None
        )
        tokens = measurement.get("tokens") if isinstance(measurement, Mapping) else None
        has_token_counter = isinstance(tokens, Mapping) and any(
            value is not None for value in tokens.values()
        )

        is_codex_hook = family == "codex" and adapter_name == "codex-hooks"
        is_claude_hook = (
            family == "claude"
            and adapter_name == "claude-runtime"
            and (
                (
                    event_name == "coverage.gap"
                    and source_event
                    in {"turn_stop", "subagent_start", "subagent_stop"}
                )
                or (
                    event_name == "runtime.turn_stopped"
                    and source_event == "turn_failure"
                )
            )
        )
        if is_codex_hook or is_claude_hook:
            summary["hook_events"] = int(summary["hook_events"]) + 1
            if isinstance(task_id, str) and task_id:
                hook_tasks[family].add(task_id)

        if is_codex_hook and isinstance(task_id, str) and task_id:
            target_name = expected_by_id.get(target_id)
            if target_name is not None:
                target_hook_counts[target_name] += 1
                target_hooks[target_name].add(task_id)
                task_target_names.setdefault(task_id, set()).add(target_name)
            elif target_id is None:
                legacy_codex_hook_events += 1
            else:
                unrecognized_target_hook_events += 1

        is_task_start = event_name == "task.start" and source_event == "prompt_submit" and (
            (family == "codex" and adapter_name == "codex-hooks")
            or (family == "claude" and adapter_name == "claude-runtime")
        )
        if is_task_start:
            summary["task_starts"] = int(summary["task_starts"]) + 1
            if isinstance(task_id, str) and task_id:
                started_tasks[family].add(task_id)
                if family == "codex":
                    target_name = expected_by_id.get(target_id)
                    if target_name is not None:
                        target_started[target_name].add(task_id)

        is_usage = (
            event_name == "usage.observed"
            and measurement_provenance == "runtime-observed"
            and has_token_counter
            and (
                (
                    family == "codex"
                    and adapter_name == "codex-otel"
                    and source_event == "otel_response_completed"
                    and counter_source == "provider-native"
                )
                or (
                    family == "claude"
                    and adapter_name == "claude-runtime"
                    and source_event == "otel_api"
                    and counter_source == "runtime-native"
                )
            )
        )
        if is_usage:
            summary["usage_events"] = int(summary["usage_events"]) + 1
            if isinstance(task_id, str) and task_id:
                summary["task_bound_usage"] = int(summary["task_bound_usage"]) + 1
                usage_tasks[family].add(task_id)
                if family == "codex":
                    target_name = expected_by_id.get(target_id)
                    if target_name is not None:
                        target_usage[target_name].add(task_id)
                        task_target_names.setdefault(task_id, set()).add(target_name)

        if event_name == "task.terminal" and adapter_name == "agent-declaration":
            summary["terminal_declarations"] = int(summary["terminal_declarations"]) + 1
        if event_name == "coverage.gap":
            summary["coverage_gaps"] = int(summary["coverage_gaps"]) + 1

    for runtime in RUNTIMES:
        summary = summaries[runtime]
        correlated_tasks = (
            started_tasks[runtime] & usage_tasks[runtime] & hook_tasks[runtime]
        )
        summary["correlated_tasks"] = len(correlated_tasks)
        summary["active"] = bool(correlated_tasks)

    target_summaries: Dict[str, Dict[str, RuntimeValue]] = {}
    for name in sorted(target_started):
        uniquely_attributed = {
            task_id
            for task_id, names in task_target_names.items()
            if names == {name}
        }
        correlated = (
            target_started[name]
            & target_hooks[name]
            & target_usage[name]
            & uniquely_attributed
        )
        target_summaries[name] = {
            "hook_events": target_hook_counts[name],
            "task_starts": len(target_started[name]),
            "correlated_tasks": len(correlated),
            "active": bool(correlated),
        }
    return {
        "max_sequence": str(max_sequence),
        "runtimes": summaries,
        "targets": target_summaries,
        "target_attribution": {
            "legacy_codex_hook_events": legacy_codex_hook_events,
            "unrecognized_target_hook_events": unrecognized_target_hook_events,
        },
    }


def _copy_payload(source_root: Path, destination_root: Path) -> None:
    for source, relative in _payload_files(source_root):
        destination = destination_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(source), str(destination), follow_symlinks=False)


def _write_private_report(
    state_root: Path,
    report: Mapping[str, Any],
) -> Tuple[Path, str, int]:
    """Publish one bounded private report without following links or replacing files."""

    raw = _canonical_json_bytes(report)
    if len(raw) > _MAX_REPORT_BYTES:
        raise ActivationStatusError("activation report exceeds its safe bound")
    _assert_no_link_components(state_root)
    report_root = state_root / "activation-reports"
    try:
        os.mkdir(str(report_root), 0o700)
    except FileExistsError:
        pass
    if _is_link_or_reparse(report_root) or not report_root.is_dir():
        raise ActivationStatusError("activation report directory is unsafe")
    _assert_no_link_components(report_root)
    if os.name != "nt":
        os.chmod(str(report_root), 0o700)

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    for _attempt in range(8):
        destination = report_root / (
            "activation-{}-{}.json".format(
                time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()),
                secrets.token_hex(8),
            )
        )
        try:
            descriptor = os.open(str(destination), flags, 0o600)
        except FileExistsError:
            continue
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise ActivationStatusError("activation report target is not regular")
            view = memoryview(raw)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("short activation report write")
                view = view[written:]
            os.fsync(descriptor)
        except BaseException:
            os.close(descriptor)
            raise
        else:
            os.close(descriptor)
        if _is_link_or_reparse(report_root) or _is_link_or_reparse(destination):
            raise ActivationStatusError("activation report path changed during publication")
        published = destination.lstat()
        if not stat.S_ISREG(published.st_mode) or (
            getattr(opened, "st_ino", 0)
            and getattr(published, "st_ino", 0)
            and (opened.st_dev, opened.st_ino) != (published.st_dev, published.st_ino)
        ):
            raise ActivationStatusError("activation report target changed during publication")
        if os.name != "nt":
            os.chmod(str(destination), 0o600)
        return destination.resolve(strict=True), hashlib.sha256(raw).hexdigest(), len(raw)
    raise ActivationStatusError("activation report filename collisions exceeded the safe bound")


def _report_receipt(
    filename: Path,
    *,
    status: str,
    active: int,
    total: int,
    digest: str,
    size: int,
) -> str:
    return "REPORT_SAVED " + json.dumps(
        {
            "filename": str(filename),
            "status": status,
            "active": "{}/{}".format(active, total),
            "pending": total - active,
            "sha256": digest,
            "bytes": size,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _suffix_closes_managed_otel(installer: Any, suffix: str) -> bool:
    """Reject keys that would remain inside the preceding managed `[otel]`."""

    for line in suffix.splitlines():
        semantic = installer._toml_without_comments(line).strip()
        if not semantic:
            continue
        return bool(installer._TOML_TABLE_HEADER.fullmatch(semantic))
    return True


def _decode_toml_basic_key(value: str) -> str:
    """Decode one TOML basic quoted key without accepting unknown escapes."""

    output = []
    index = 0
    escapes = {
        "b": "\b",
        "t": "\t",
        "n": "\n",
        "f": "\f",
        "r": "\r",
        '"': '"',
        "\\": "\\",
    }
    while index < len(value):
        character = value[index]
        if character != "\\":
            output.append(character)
            index += 1
            continue
        index += 1
        if index >= len(value):
            raise ActivationStatusError("outer Codex config has an invalid quoted key")
        escape = value[index]
        if escape in escapes:
            output.append(escapes[escape])
            index += 1
            continue
        if escape not in ("u", "U"):
            raise ActivationStatusError("outer Codex config has an invalid quoted key")
        digits = 4 if escape == "u" else 8
        encoded = value[index + 1 : index + 1 + digits]
        if len(encoded) != digits or not all(
            character in "0123456789abcdefABCDEF" for character in encoded
        ):
            raise ActivationStatusError("outer Codex config has an invalid quoted key")
        codepoint = int(encoded, 16)
        if codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
            raise ActivationStatusError("outer Codex config has an invalid quoted key")
        output.append(chr(codepoint))
        index += 1 + digits
    return "".join(output)


def _toml_root_key(installer: Any, line: str) -> Optional[str]:
    """Return a decoded root key for a table or assignment when recognizable."""

    semantic = installer._toml_without_comments(line).lstrip()
    if not semantic:
        return None
    table = False
    if semantic.startswith("[["):
        table = True
        semantic = semantic[2:].lstrip()
    elif semantic.startswith("["):
        table = True
        semantic = semantic[1:].lstrip()

    if not semantic:
        return None
    if semantic[0] == '"':
        escaped = False
        end = None
        for index in range(1, len(semantic)):
            character = semantic[index]
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                end = index
                break
        if end is None:
            raise ActivationStatusError("outer Codex config has an invalid quoted key")
        key = _decode_toml_basic_key(semantic[1:end])
        remainder = semantic[end + 1 :].lstrip()
    elif semantic[0] == "'":
        end = semantic.find("'", 1)
        if end < 0:
            raise ActivationStatusError("outer Codex config has an invalid quoted key")
        key = semantic[1:end]
        remainder = semantic[end + 1 :].lstrip()
    else:
        match = re.match(r"[A-Za-z0-9_-]+", semantic)
        if match is None:
            return None
        key = match.group(0)
        remainder = semantic[match.end() :].lstrip()

    expected = (".", "]") if table else (".", "=")
    if not remainder.startswith(expected):
        return None
    return key


def _assert_supported_outer_toml(installer: Any, prefix: str, suffix: str) -> None:
    """Fail closed on ambiguous outer syntax and decoded competing OTel roots."""

    for outer in (prefix, suffix):
        # A bounded activation receipt does not need to implement a complete TOML
        # lexer. Reject multiline strings so a marker-looking line cannot be data.
        if '\"\"\"' in outer or "'''" in outer:
            raise installer.InstallerVerificationError(
                "Codex config activation outer content uses unsupported multiline strings"
            )
        if installer._contains_otel_definition(outer):
            raise installer.InstallerVerificationError(
                "Codex config activation target has a competing OTel owner"
            )
        try:
            roots = (
                _toml_root_key(installer, line)
                for line in outer.splitlines()
            )
            if any(root is not None and root.lower() == "otel" for root in roots):
                raise installer.InstallerVerificationError(
                    "Codex config activation target has a competing OTel owner"
                )
        except ActivationStatusError as error:
            raise installer.InstallerVerificationError(
                "Codex config activation outer content is not safely recognizable"
            ) from error


def _reviewed_managed_newline(installer: Any, plan: Any, action: Mapping[str, Any]) -> str:
    """Recover the exact newline encoding used by the reviewed changed action."""

    if not action.get("changed"):
        raise installer.InstallerVerificationError(
            "unchanged Codex config drift has no reviewed fragment bytes"
        )
    if not action.get("before_exists"):
        return "\n"
    anchor = installer._anchor_for_action(plan, action)
    before_raw, _before_mode = installer._read_regular_child_held(
        anchor,
        Path(str(action["before_path"])).name,
    )
    before_text, _before_bom = installer._decode_toml(before_raw)
    return "\r\n" if "\r\n" in before_text else "\n"


def _verify_relaxed_codex_config(
    installer: Any,
    plan: Any,
    action: Mapping[str, Any],
    settings: Mapping[str, Any],
) -> None:
    """Verify only the managed OTel ownership inside one host-rewritten config."""

    anchor = installer._anchor_for_action(plan, action)
    state = installer._held_action_namespace(plan, action)
    expected_before = (
        "before" if action["changed"] and action["before_exists"] else "missing"
    )
    if state != {
        "target": "other",
        "before": expected_before,
        "stage": "missing",
        "after": "missing",
    }:
        raise installer.InstallerVerificationError(
            "Codex config activation namespace differs from the reviewed install"
        )
    raw, current_mode = installer._read_regular_child_held(
        anchor,
        Path(str(action["path"])).name,
    )
    if (
        os.name != "nt"
        and action.get("after_mode") is not None
        and current_mode != action["after_mode"]
    ):
        raise installer.InstallerVerificationError(
            "Codex config activation target mode drifted"
        )

    text, _bom = installer._decode_toml(raw)
    split = installer._split_managed_block(text)
    if split is None:
        raise installer.InstallerVerificationError(
            "Codex config activation target has no managed OTel block"
        )
    prefix, current, suffix = split
    reviewed_newline = _reviewed_managed_newline(installer, plan, action)
    wanted = installer._managed_otel_block(
        settings["listen_port"], settings["auth_token"], reviewed_newline
    )
    if current != wanted:
        raise installer.InstallerVerificationError(
            "Codex config activation managed OTel block was edited"
        )
    _assert_supported_outer_toml(installer, prefix, suffix)
    if not _suffix_closes_managed_otel(installer, suffix):
        raise installer.InstallerVerificationError(
            "Codex config activation target extends the managed OTel table"
        )
    installer._require_directory_anchor(anchor)


def _verify_activation_install_held(installer: Any, plan: Any) -> Dict[str, Any]:
    """Preserve exact verification except for active Codex config outer bytes."""

    installer._require_transaction_attached(plan)
    installer._require_all_action_parents(plan)
    if plan.journal.get("status") != "applied":
        raise installer.InstallerVerificationError(
            "transaction is not in applied state"
        )

    eligible_configs = {
        (
            home["name"],
            os.path.normcase(os.path.abspath(str(home["config"]["path"]))),
        )
        for home in plan.journal.get("codex_homes", [])
    }
    relaxed_actions = []
    for action in plan.journal.get("actions", []):
        key = (
            action.get("name"),
            os.path.normcase(os.path.abspath(str(action.get("path", "")))),
        )
        eligible = (
            action.get("kind") == "otel-config"
            and bool(action.get("changed"))
            and key in eligible_configs
        )
        try:
            installer._verify_action_after(plan, action)
        except installer.InstallerVerificationError:
            if not eligible:
                raise
            relaxed_actions.append(action)
        if action["changed"] and (
            not action["applied"] or action["apply_state"] != "applied"
        ):
            raise installer.InstallerVerificationError(
                "installed action progress does not match its reviewed plan"
            )
        if action["changed"] and action not in relaxed_actions:
            if installer._rollback_namespace_case(plan, action) != "applied":
                raise installer.InstallerVerificationError(
                    "installed action namespace does not match its reviewed plan"
                )

    if not relaxed_actions:
        raise installer.InstallerVerificationError(
            "exact installation verification failed without eligible Codex config drift"
        )

    settings_action = next(
        action
        for action in plan.journal["actions"]
        if action["kind"] == "settings" and action["name"] == "recorder"
    )
    settings_raw, _settings_mode = installer._read_regular_child_held(
        installer._anchor_for_action(plan, settings_action),
        Path(settings_action["path"]).name,
    )
    settings = installer._load_existing_settings_bytes(settings_raw)
    receiver = plan.journal["receiver"]
    if (
        settings.get("auth_token") != plan.auth_token
        or settings.get("listen_port") != receiver.get("listen_port")
        or hashlib.sha256(settings["auth_token"].encode("ascii")).hexdigest()
        != receiver.get("auth_token_sha256")
    ):
        raise installer.InstallerVerificationError(
            "installed settings do not match the reviewed OTel binding"
        )

    for action in relaxed_actions:
        _verify_relaxed_codex_config(installer, plan, action, settings)

    installer._retained_artifacts(plan, plan.journal["actions"])
    installer._require_transaction_attached(plan)
    installer._require_all_action_parents(plan)
    return {"ok": True, "activation_config_conformance": True}


def _verify_activation_install(
    installer: Any,
    value: Any,
    *,
    plan_digest: str,
) -> Dict[str, Any]:
    """Use exact installer verification, then one fail-closed activation exception."""

    try:
        return installer.verify_install(value, plan_digest=plan_digest)
    except installer.InstallerVerificationError:
        pass
    with installer._locked_operation_plan(
        value,
        expected_plan_digest=plan_digest,
    ) as plan:
        with installer._held_target_parents(plan):
            return _verify_activation_install_held(installer, plan)


@contextmanager
def _snapshot_recorder_api(
    install_root: Path,
    expected_digest: str,
) -> Iterator[Tuple[Any, Any, Any, Any, Any, Any, Any]]:
    """Import only a private snapshot whose bytes match the reviewed payload."""

    with tempfile.TemporaryDirectory(prefix="delivery-efficiency-inspection-") as raw:
        temporary_root = Path(raw).resolve(strict=True)
        snapshot = temporary_root / "delivery-efficiency"
        snapshot.mkdir()
        _copy_payload(install_root, snapshot)
        if _payload_digest(snapshot) != expected_digest:
            raise ActivationStatusError("reviewed recorder changed while snapshotting")

        saved_modules = {
            name: module
            for name, module in list(sys.modules.items())
            if name == "delivery_efficiency" or name.startswith("delivery_efficiency.")
        }
        for name in saved_modules:
            sys.modules.pop(name, None)
        snapshot_text = str(snapshot)
        sys.path.insert(0, snapshot_text)
        try:
            from delivery_efficiency import installer
            from delivery_efficiency.runtime import load_settings, receiver_is_healthy
            from delivery_efficiency.storage import Recorder

            def verify_activation_install(value: Any, *, plan_digest: str) -> Dict[str, Any]:
                return _verify_activation_install(
                    installer,
                    value,
                    plan_digest=plan_digest,
                )

            yield (
                installer.load_plan,
                installer.source_tree_digest,
                verify_activation_install,
                load_settings,
                receiver_is_healthy,
                Recorder,
                getattr(installer, "_runtime_target_ref", None),
            )
        except ActivationStatusError:
            raise
        except (ImportError, OSError) as error:
            raise ActivationStatusError("reviewed recorder API is unavailable") from error
        finally:
            for name in list(sys.modules):
                if name == "delivery_efficiency" or name.startswith("delivery_efficiency."):
                    sys.modules.pop(name, None)
            for name, module in saved_modules.items():
                sys.modules[name] = module
            if sys.path and sys.path[0] == snapshot_text:
                sys.path.pop(0)
            else:
                try:
                    sys.path.remove(snapshot_text)
                except ValueError:
                    pass


@contextmanager
def _recorder_api(
    journal: Path,
    plan_digest: str,
) -> Iterator[Tuple[Any, Any, Any, Any, Any, Any, Any]]:
    install_root, expected_digest = _preflight_reviewed_payload(journal, plan_digest)
    with _snapshot_recorder_api(install_root, expected_digest) as api:
        yield api


def _inspect_with_api(
    api: Tuple[Any, Any, Any, Any, Any, Any, Any],
    journal: Path,
    plan_digest: str,
    *,
    after_sequence: int,
    selected_runtime: str,
) -> Dict[str, object]:
    (
        load_plan,
        source_tree_digest,
        verify_install,
        load_settings,
        receiver_is_healthy,
        Recorder,
        _runtime_target_ref,
    ) = api
    try:
        plan = load_plan(journal, expected_plan_digest=plan_digest)
        source = Path(plan.journal["source"]["root"])
        expected_source = TOOL_ROOT.resolve(strict=True)
        if not _same_path(source.resolve(strict=True), expected_source):
            raise ActivationStatusError("journal source is not this canonical recorder")
        expected_digest = plan.journal["source"]["payload_sha256"]
        if source_tree_digest(expected_source) != expected_digest:
            raise ActivationStatusError("canonical recorder changed after review")
        verification_before = verify_install(plan, plan_digest=plan_digest)
        state = Path(plan.journal["target"]["state_root"])
        settings = load_settings(state)
        if not receiver_is_healthy(settings):
            raise ActivationStatusError("reviewed recorder receiver is unhealthy")
        with Recorder(state) as recorder:
            store = recorder.status()
            if store.get("healthy") is not True:
                raise ActivationStatusError("reviewed recorder store is unhealthy")
            summary = summarize_events(
                recorder.read_verified_events(),
                after_sequence=after_sequence,
                selected_runtime=selected_runtime,
            )
        verification_after = verify_install(plan, plan_digest=plan_digest)
        settings_after = load_settings(state)
        if settings_after != settings:
            raise ActivationStatusError("recorder settings changed during inspection")
        if not receiver_is_healthy(settings_after):
            raise ActivationStatusError("reviewed recorder receiver changed during inspection")
        if source_tree_digest(expected_source) != expected_digest:
            raise ActivationStatusError("canonical recorder changed during inspection")
    except ActivationStatusError:
        raise
    except Exception as error:
        raise ActivationStatusError("reviewed installation verification failed") from error

    used_config_conformance = any(
        isinstance(value, Mapping) and value.get("activation_config_conformance") is True
        for value in (verification_before, verification_after)
    )
    return {
        "ok": True,
        "after_sequence": str(after_sequence),
        "max_sequence": summary["max_sequence"],
        "plan_sha256": plan_digest,
        "recorder_version": store.get("recorder_version"),
        "schema_version": store.get("schema_version"),
        "verification": (
            "journal-bound-reviewed-snapshot-and-double-activation-config-conformance"
            if used_config_conformance
            else "journal-bound-reviewed-snapshot-and-double-verified-store"
        ),
        "runtimes": summary["runtimes"],
    }


def _watch_with_api(
    api: Tuple[Any, Any, Any, Any, Any, Any, Any],
    journal: Path,
    plan_digest: str,
    *,
    selected_targets: Optional[list[str]],
    wait_seconds: int,
) -> Tuple[Dict[str, object], Path, str, int]:
    """Own the baseline and watch every reviewed Codex target concurrently."""

    (
        load_plan,
        source_tree_digest,
        verify_install,
        load_settings,
        receiver_is_healthy,
        Recorder,
        runtime_target_ref,
    ) = api
    try:
        plan = load_plan(journal, expected_plan_digest=plan_digest)
        source = Path(plan.journal["source"]["root"])
        expected_source = TOOL_ROOT.resolve(strict=True)
        if not _same_path(source.resolve(strict=True), expected_source):
            raise ActivationStatusError("journal source is not this canonical recorder")
        expected_digest = plan.journal["source"]["payload_sha256"]
        if source_tree_digest(expected_source) != expected_digest:
            raise ActivationStatusError("canonical recorder changed after review")
        verification_before = verify_install(plan, plan_digest=plan_digest)
        state = Path(plan.journal["target"]["state_root"])
        settings = load_settings(state)
        if not receiver_is_healthy(settings):
            raise ActivationStatusError("reviewed recorder receiver is unhealthy")

        home_specs = plan.journal.get("codex_homes", [])
        if not isinstance(home_specs, list) or not home_specs:
            raise ActivationStatusError("reviewed plan has no Codex targets")
        by_name = {
            home.get("name"): home
            for home in home_specs
            if isinstance(home, Mapping) and isinstance(home.get("name"), str)
        }
        if len(by_name) != len(home_specs):
            raise ActivationStatusError("reviewed Codex target list is invalid")
        requested = list(selected_targets or sorted(by_name))
        if not requested or len(set(requested)) != len(requested):
            raise ActivationStatusError("selected Codex target list is invalid")
        if any(name not in by_name for name in requested):
            raise ActivationStatusError("selected Codex target is not in the reviewed plan")

        with Recorder(state) as recorder:
            store = recorder.status()
            if store.get("healthy") is not True:
                raise ActivationStatusError("reviewed recorder store is unhealthy")
            baseline_events = recorder.read_verified_events()
            baseline_summary = summarize_events(
                baseline_events,
                after_sequence=0,
                selected_runtime="codex",
            )
            baseline = int(str(baseline_summary["max_sequence"]))
            expected_targets: Dict[str, str] = {}
            if callable(runtime_target_ref):
                for name in requested:
                    home = Path(str(by_name[name]["home"]))
                    source_ref = runtime_target_ref(
                        plan.auth_token,
                        "codex",
                        home,
                    )
                    expected_targets[name] = recorder.opaque_id("target", source_ref)

        attribution = "target-aware" if len(expected_targets) == len(requested) else "family-only"
        deadline = time.monotonic() + wait_seconds
        summary: Dict[str, object]
        while True:
            with Recorder(state) as recorder:
                events = recorder.read_verified_events()
            summary = summarize_events(
                events,
                after_sequence=baseline,
                selected_runtime="codex",
                expected_targets=expected_targets,
            )
            targets_value = summary.get("targets")
            targets = targets_value if isinstance(targets_value, Mapping) else {}
            target_complete = bool(expected_targets) and all(
                isinstance(targets.get(name), Mapping)
                and bool(targets[name].get("active"))
                for name in requested
            )
            family = summary["runtimes"]["codex"]
            family_complete = isinstance(family, Mapping) and bool(family.get("active"))
            if target_complete or (attribution == "family-only" and family_complete):
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))

        verification_after = verify_install(plan, plan_digest=plan_digest)
        settings_after = load_settings(state)
        if settings_after != settings or not receiver_is_healthy(settings_after):
            raise ActivationStatusError("reviewed recorder changed during activation watch")
        if source_tree_digest(expected_source) != expected_digest:
            raise ActivationStatusError("canonical recorder changed during activation watch")
    except ActivationStatusError:
        raise
    except Exception as error:
        raise ActivationStatusError("reviewed activation watch failed") from error

    targets_value = summary.get("targets")
    target_values = targets_value if isinstance(targets_value, Mapping) else {}
    target_reports = []
    active_count = 0
    for name in requested:
        value = target_values.get(name)
        item = value if isinstance(value, Mapping) else {}
        active = attribution == "target-aware" and bool(item.get("active"))
        active_count += int(active)
        target_reports.append(
            {
                "name": name,
                "status": (
                    "active"
                    if active
                    else "unproven-family-only"
                    if attribution == "family-only"
                    else "pending"
                ),
                "hook_events": int(item.get("hook_events", 0)),
                "task_starts": int(item.get("task_starts", 0)),
                "correlated_tasks": int(item.get("correlated_tasks", 0)),
            }
        )
    complete = attribution == "target-aware" and active_count == len(requested)
    family = summary["runtimes"]["codex"]
    family_value = family if isinstance(family, Mapping) else {}
    status = (
        "active"
        if complete
        else "family-only"
        if attribution == "family-only"
        else "timeout"
    )
    used_config_conformance = any(
        isinstance(value, Mapping) and value.get("activation_config_conformance") is True
        for value in (verification_before, verification_after)
    )
    report: Dict[str, object] = {
        "schema_version": _REPORT_SCHEMA_VERSION,
        "report_kind": "codex-target-activation",
        "status": status,
        "attribution": attribution,
        "proof_scope": "configured-runtime-home-not-process-or-session",
        "plan_sha256": plan_digest,
        "recorder_version": store.get("recorder_version"),
        "event_schema_version": store.get("schema_version"),
        "baseline_sequence": str(baseline),
        "latest_sequence": str(summary["max_sequence"]),
        "wait_seconds": wait_seconds,
        "requested_target_count": len(requested),
        "active_target_count": active_count,
        "pending_target_count": len(requested) - active_count,
        "targets": target_reports,
        "family_evidence": {
            "events": int(family_value.get("events", 0)),
            "hook_events": int(family_value.get("hook_events", 0)),
            "task_starts": int(family_value.get("task_starts", 0)),
            "task_bound_usage": int(family_value.get("task_bound_usage", 0)),
            "correlated_tasks": int(family_value.get("correlated_tasks", 0)),
            "active": bool(family_value.get("active")),
        },
        "verification": (
            "journal-bound-reviewed-snapshot-and-double-activation-config-conformance"
            if used_config_conformance
            else "journal-bound-reviewed-snapshot-and-double-verified-store"
        ),
        "limitations": (
            ["legacy-family-evidence-cannot-prove-a-configured-home"]
            if attribution == "family-only"
            else ["a-fresh-task-proves-the-configured-home-not-a-particular-process-or-session"]
        ),
    }
    filename, report_digest, report_size = _write_private_report(state, report)
    result = {
        "ok": complete,
        "status": status,
        "active": active_count,
        "total": len(requested),
        "pending": len(requested) - active_count,
        "report_sha256": report_digest,
        "report_bytes": report_size,
    }
    return result, filename, report_digest, report_size


def watch(
    journal: Path,
    plan_digest: str,
    *,
    selected_targets: Optional[list[str]],
    wait_seconds: int,
) -> Tuple[Dict[str, object], Path, str, int]:
    try:
        with _recorder_api(journal, plan_digest) as api:
            return _watch_with_api(
                api,
                journal,
                plan_digest,
                selected_targets=selected_targets,
                wait_seconds=wait_seconds,
            )
    except ActivationStatusError:
        raise
    except Exception as error:
        raise ActivationStatusError("reviewed activation watch failed") from error


def inspect(
    journal: Path,
    plan_digest: str,
    *,
    after_sequence: int,
    selected_runtime: str,
) -> Dict[str, object]:
    try:
        with _recorder_api(journal, plan_digest) as api:
            return _inspect_with_api(
                api,
                journal,
                plan_digest,
                after_sequence=after_sequence,
                selected_runtime=selected_runtime,
            )
    except ActivationStatusError:
        raise
    except Exception as error:
        raise ActivationStatusError("reviewed installation verification failed") from error


def _selected_ready(result: Mapping[str, object], selected_runtime: str) -> bool:
    runtimes = result["runtimes"]
    if not isinstance(runtimes, Mapping):
        return False
    selected = RUNTIMES if selected_runtime == "all" else (selected_runtime,)
    return all(
        isinstance(runtimes.get(name), Mapping)
        and bool(runtimes[name].get("active"))
        for name in selected
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--plan-digest", required=True)
    parser.add_argument("--runtime", choices=("all",) + RUNTIMES, default="all")
    parser.add_argument("--after-sequence", type=int, default=0)
    parser.add_argument("--wait-seconds", type=int)
    parser.add_argument("--require-active", action="store_true")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--target", action="append", default=[])
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.journal.is_absolute():
        print("ACTIVATION_STATUS error=journal-must-be-absolute")
        return 1
    wait_seconds = args.wait_seconds
    if wait_seconds is None:
        wait_seconds = _DEFAULT_WATCH_SECONDS if args.watch else 0
    maximum_wait = _MAX_WATCH_SECONDS if args.watch else 30
    if args.after_sequence < 0 or not 0 <= wait_seconds <= maximum_wait:
        print("ACTIVATION_STATUS error=invalid-bounds")
        return 1

    if args.watch:
        if (
            args.runtime != "codex"
            or args.after_sequence != 0
            or args.require_active
        ):
            print("ACTIVATION_STATUS error=invalid-watch-options")
            return 1
        try:
            result, filename, digest, size = watch(
                args.journal,
                args.plan_digest,
                selected_targets=args.target or None,
                wait_seconds=wait_seconds,
            )
            print(
                _report_receipt(
                    filename,
                    status=str(result["status"]),
                    active=int(result["active"]),
                    total=int(result["total"]),
                    digest=digest,
                    size=size,
                )
            )
            return 0 if result["ok"] else 2
        except ActivationStatusError:
            print("ACTIVATION_STATUS error=inspection-failed")
            return 1

    if args.target:
        print("ACTIVATION_STATUS error=target-requires-watch")
        return 1
    deadline = time.monotonic() + wait_seconds
    try:
        while True:
            result = inspect(
                args.journal,
                args.plan_digest,
                after_sequence=args.after_sequence,
                selected_runtime=args.runtime,
            )
            if not args.require_active or _selected_ready(result, args.runtime):
                print(
                    "ACTIVATION_STATUS "
                    + json.dumps(result, sort_keys=True, separators=(",", ":"))
                )
                return 0
            if time.monotonic() >= deadline:
                print(
                    "ACTIVATION_STATUS "
                    + json.dumps(result, sort_keys=True, separators=(",", ":"))
                )
                return 2
            time.sleep(1)
    except ActivationStatusError:
        print("ACTIVATION_STATUS error=inspection-failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
