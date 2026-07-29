"""Controlled `codex exec --json` wrapper with lossless stdout forwarding."""

from __future__ import annotations

import os
from pathlib import Path
import secrets
import subprocess
import sys
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .codex import CodexExecTranslator, SourceEventError, record_emissions
from .runtime import record_local_gap


WRAPPED_CODEX_EXEC_ENV = "HOLYSKILLS_DELIVERY_EFFICIENCY_WRAPPED_CODEX_EXEC"
_DISABLE_CODEX_LOG_EXPORT = 'otel.exporter="none"'


def _command(codex_binary: str, arguments: Sequence[str]) -> List[str]:
    if not codex_binary or "\x00" in codex_binary:
        raise ValueError("codex binary is invalid")
    values = list(arguments)
    if values and values[0] == "exec":
        values = values[1:]
    if values and values[0] == "--":
        values = values[1:]
    if "--json" not in values:
        values.insert(0, "--json")
    # The wrapper consumes the child's lossless JSONL stream, including the
    # provider-native counters.  A Codex home managed by this recorder also
    # contains an OTLP log exporter, so letting the child inherit it would
    # account the same response twice.  This documented one-run override is
    # appended last so it wins over an earlier CLI override without changing
    # the user's config.toml or disabling trace/metrics exporters.
    return [codex_binary, "exec"] + values + ["--config", _DISABLE_CODEX_LOG_EXPORT]


def _child_environment() -> Dict[str, str]:
    """Preserve the caller environment and mark only this managed child."""

    environment = dict(os.environ)
    # The recorder's installed hook handler recognizes this child-only marker
    # and becomes a no-op.  Other Codex hooks continue to run normally.
    environment[WRAPPED_CODEX_EXEC_ENV] = "1"
    return environment


def run_codex_exec(
    state_dir: Path,
    *,
    codex_binary: str,
    arguments: Sequence[str],
    terminal_declaration: Optional[Dict[str, Any]] = None,
) -> int:
    """Run Codex without capturing content-bearing stream fields in telemetry."""

    from .storage import Recorder

    invocation = "exec-" + secrets.token_hex(16)
    translator = CodexExecTranslator(invocation_id=invocation)
    recorder = Recorder(state_dir)
    record_emissions(recorder, translator.receipt())
    interrupted = False
    try:
        process = subprocess.Popen(
            _command(codex_binary, arguments),
            stdin=None,
            stdout=subprocess.PIPE,
            stderr=None,
            env=_child_environment(),
            shell=False,
            bufsize=0,
        )
    except OSError:
        record_emissions(recorder, translator.process_exit(127))
        record_local_gap(state_dir, "receiver-unavailable")
        close = getattr(recorder, "close", None)
        if close:
            close()
        return 127

    assert process.stdout is not None
    try:
        while True:
            line = process.stdout.readline()
            if not line:
                break
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()
            try:
                emissions = translator.translate(line)
            except SourceEventError:
                record_local_gap(state_dir, "malformed-source-event")
            else:
                record_emissions(recorder, emissions)
        exit_code = process.wait()
    except KeyboardInterrupt:
        interrupted = True
        try:
            process.terminate()
            exit_code = process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass
            exit_code = process.wait()
    finally:
        process.stdout.close()

    record_emissions(
        recorder,
        translator.process_exit(
            exit_code,
            interrupted=interrupted,
            terminal_declaration=terminal_declaration,
        ),
    )
    close = getattr(recorder, "close", None)
    if close:
        close()
    if interrupted and exit_code == 0:
        return 130
    return int(exit_code)
