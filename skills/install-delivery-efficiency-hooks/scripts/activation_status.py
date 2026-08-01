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
) -> Dict[str, object]:
    """Summarize strict adapter tuples without returning opaque identities."""

    summaries = {runtime: _empty_runtime() for runtime in RUNTIMES}
    started_tasks = {runtime: set() for runtime in RUNTIMES}
    usage_tasks = {runtime: set() for runtime in RUNTIMES}
    hook_tasks = {runtime: set() for runtime in RUNTIMES}
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

        is_task_start = event_name == "task.start" and source_event == "prompt_submit" and (
            (family == "codex" and adapter_name == "codex-hooks")
            or (family == "claude" and adapter_name == "claude-runtime")
        )
        if is_task_start:
            summary["task_starts"] = int(summary["task_starts"]) + 1
            if isinstance(task_id, str) and task_id:
                started_tasks[family].add(task_id)

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
    return {"max_sequence": str(max_sequence), "runtimes": summaries}


def _copy_payload(source_root: Path, destination_root: Path) -> None:
    for source, relative in _payload_files(source_root):
        destination = destination_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(source), str(destination), follow_symlinks=False)


@contextmanager
def _snapshot_recorder_api(
    install_root: Path,
    expected_digest: str,
) -> Iterator[Tuple[Any, Any, Any, Any, Any, Any]]:
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
            from delivery_efficiency.installer import (
                load_plan,
                source_tree_digest,
                verify_install,
            )
            from delivery_efficiency.runtime import load_settings, receiver_is_healthy
            from delivery_efficiency.storage import Recorder

            yield (
                load_plan,
                source_tree_digest,
                verify_install,
                load_settings,
                receiver_is_healthy,
                Recorder,
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
) -> Iterator[Tuple[Any, Any, Any, Any, Any, Any]]:
    install_root, expected_digest = _preflight_reviewed_payload(journal, plan_digest)
    with _snapshot_recorder_api(install_root, expected_digest) as api:
        yield api


def _inspect_with_api(
    api: Tuple[Any, Any, Any, Any, Any, Any],
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
        verify_install(plan, plan_digest=plan_digest)
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
        verify_install(plan, plan_digest=plan_digest)
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

    return {
        "ok": True,
        "after_sequence": str(after_sequence),
        "max_sequence": summary["max_sequence"],
        "plan_sha256": plan_digest,
        "recorder_version": store.get("recorder_version"),
        "schema_version": store.get("schema_version"),
        "verification": "journal-bound-reviewed-snapshot-and-double-verified-store",
        "runtimes": summary["runtimes"],
    }


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
    parser.add_argument("--wait-seconds", type=int, default=0)
    parser.add_argument("--require-active", action="store_true")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.journal.is_absolute():
        print("ACTIVATION_STATUS error=journal-must-be-absolute")
        return 1
    if args.after_sequence < 0 or not 0 <= args.wait_seconds <= 30:
        print("ACTIVATION_STATUS error=invalid-bounds")
        return 1

    deadline = time.monotonic() + args.wait_seconds
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
