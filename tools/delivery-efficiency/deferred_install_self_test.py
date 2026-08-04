#!/usr/bin/env python3
"""Focused safety tests for the one-shot deferred installer."""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from delivery_efficiency import cli  # noqa: E402
from delivery_efficiency import deferred_install as deferred  # noqa: E402
from delivery_efficiency import installer  # noqa: E402
from delivery_efficiency import process_identity as processes  # noqa: E402


def identity(
    pid: int,
    creation: str,
    path: str,
    file_id: str,
    owner: str = "uid:1000",
) -> processes.ProcessIdentity:
    return processes.ProcessIdentity(pid, creation, owner, path, file_id)


class FakeBackend:
    def __init__(self, values: dict[int, processes.ProcessIdentity]) -> None:
        self.values = values

    def current_owner(self) -> str:
        return "uid:1000"

    def owner(self, pid: int) -> str:
        value = self.values.get(pid)
        if value is None:
            raise processes.ProcessNotFound("gone")
        return value.owner

    def image_hints(self, pid: int):
        value = self.values.get(pid)
        if value is None:
            raise processes.ProcessNotFound("gone")
        return (Path(value.executable_path).name,)

    def capture(self, pid: int) -> processes.ProcessIdentity:
        value = self.values.get(pid)
        if value is None:
            raise processes.ProcessNotFound("gone")
        return value

    def list_pids(self):
        return list(self.values)


def fake_inspector(values: dict[int, processes.ProcessIdentity]) -> processes.ProcessInspector:
    value = object.__new__(processes.ProcessInspector)
    value._backend = FakeBackend(values)
    value.owner = "uid:1000"
    return value


class ProcessIdentityTests(unittest.TestCase):
    def test_pid_reuse_never_satisfies_exact_identity(self) -> None:
        reviewed = identity(41, "boot:10", "/Applications/Target", "1:10")
        reused = identity(41, "boot:99", "/Applications/Target", "1:10")
        inspector = fake_inspector({41: reused})
        self.assertFalse(inspector.is_alive(reviewed))

    def test_target_exit_or_reuse_before_ready_is_must_catch(self) -> None:
        reviewed = identity(51, "boot:10", "/Applications/Target", "1:10")
        exited = fake_inspector({})
        reused = fake_inspector(
            {51: identity(51, "boot:11", "/Applications/Target", "1:10")}
        )
        self.assertFalse(deferred._all_targets_alive(exited, [reviewed]))
        self.assertFalse(deferred._all_targets_alive(reused, [reviewed]))
        self.assertTrue(
            deferred._all_targets_alive(fake_inspector({51: reviewed}), [reviewed])
        )

    def test_relaunch_detection_ignores_exact_baseline_peers_and_unrelated_images(self) -> None:
        target = identity(10, "start-a", "/opt/codex", "1:1")
        peer = identity(11, "start-b", "/opt/codex", "1:1")
        relaunched = identity(12, "start-c", "/opt/codex", "1:1")
        unrelated = identity(13, "start-d", "/opt/other", "1:2")
        inspector = fake_inspector(
            {10: target, 11: peer, 12: relaunched, 13: unrelated}
        )
        self.assertEqual(
            inspector.detected_relaunches([target], [peer]), [relaunched]
        )

    def test_process_identity_private_shape_is_exact(self) -> None:
        original = identity(10, "start", "/opt/tool", "2:3")
        self.assertEqual(
            processes.ProcessIdentity.from_private_value(original.private_value()),
            original,
        )
        changed = original.private_value()
        changed["command"] = "PROMPT-MUST-NOT-PERSIST"
        with self.assertRaises(processes.ProcessIdentityError):
            processes.ProcessIdentity.from_private_value(changed)

    def test_windows_open_process_preserves_high_bit_handle(self) -> None:
        expected = 0x1234567887654321

        class Kernel:
            @staticmethod
            def OpenProcess(_access, _inherit, _pid):
                return expected

        backend = object.__new__(processes._WindowsBackend)
        backend._kernel32 = Kernel()
        self.assertEqual(backend._open(77), expected)

    def test_inventory_ambiguity_fails_closed_but_other_owner_is_skipped(self) -> None:
        target = identity(10, "start", "/opt/codex", "1:1")

        class AmbiguousBackend:
            def current_owner(self):
                return "uid:1000"

            def list_pids(self):
                return [20]

            def owner(self, _pid):
                return "uid:1000"

            def capture(self, _pid):
                raise processes.ProcessIdentityError("ambiguous live process")

            def image_hints(self, _pid):
                return ("codex",)

        inspector = object.__new__(processes.ProcessInspector)
        inspector._backend = AmbiguousBackend()
        inspector.owner = "uid:1000"
        with self.assertRaises(processes.ProcessIdentityError):
            inspector.list_processes([target])

        class OtherOwnerBackend(AmbiguousBackend):
            def owner(self, _pid):
                return "uid:2000"

            def capture(self, _pid):
                raise AssertionError("other-owner process must not be captured")

        inspector._backend = OtherOwnerBackend()
        self.assertEqual(inspector.list_processes([target]), [])

    def test_linux_identity_stats_proc_exe_not_resolved_path(self) -> None:
        backend = object.__new__(processes._LinuxBackend)
        backend._boot_id = "boot"
        metadata = os.stat_result(
            (stat.S_IFREG | 0o755, 123, 9, 1, 1000, 1000, 10, 0, 0, 0)
        )
        with mock.patch.object(
            backend, "_start_time", side_effect=["boot:1", "boot:1"]
        ), mock.patch.object(
            backend, "owner", return_value="uid:1000"
        ), mock.patch.object(
            processes.os, "readlink", return_value="/opt/tool (deleted)"
        ), mock.patch.object(
            processes.os, "stat", return_value=metadata
        ) as stat_call:
            captured = backend.capture(71)
        stat_call.assert_called_once_with("/proc/71/exe")
        self.assertEqual(captured.executable_path, "/opt/tool")
        self.assertEqual(captured.executable_file_id, "9:123")


class DeferredPrimitiveTests(unittest.TestCase):
    def test_private_reads_are_nofollow_bounded_and_canonical(self) -> None:
        with tempfile.TemporaryDirectory(prefix="deferred-private-read-") as raw:
            root = Path(raw).resolve()
            noncanonical = root / "noncanonical.json"
            noncanonical.write_bytes(b'{ "value": 1 }\n')
            with self.assertRaises(deferred.DeferredInstallError):
                deferred._read_object(noncanonical, deferred.MAX_RECEIPT_BYTES)

            oversized = root / "oversized.json"
            oversized.write_bytes(b"x" * (deferred.MAX_RECEIPT_BYTES + 1))
            with self.assertRaises(deferred.DeferredInstallError):
                deferred._read_bounded(oversized, deferred.MAX_RECEIPT_BYTES)

            target = root / "target.json"
            target.write_bytes(deferred._canonical_bytes({"value": 1}))
            linked = root / "linked.json"
            try:
                linked.symlink_to(target)
            except OSError:
                return
            with self.assertRaises(deferred.DeferredInstallError):
                deferred._read_object(linked, deferred.MAX_RECEIPT_BYTES)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO creation is unavailable")
    def test_private_read_rejects_fifo_promptly_without_a_writer(self) -> None:
        with tempfile.TemporaryDirectory(prefix="deferred-private-fifo-") as raw:
            fifo = Path(raw).resolve() / "receipt.json"
            os.mkfifo(str(fifo), mode=0o600)
            program = "\n".join(
                (
                    "import sys",
                    "from pathlib import Path",
                    "sys.path.insert(0, sys.argv[2])",
                    "from delivery_efficiency import deferred_install as deferred",
                    "try:",
                    "    deferred._read_bounded(Path(sys.argv[1]), deferred.MAX_RECEIPT_BYTES)",
                    "except deferred.DeferredInstallError:",
                    "    raise SystemExit(0)",
                    "raise SystemExit(3)",
                )
            )
            completed = subprocess.run(
                [sys.executable, "-I", "-B", "-c", program, str(fifo), str(ROOT)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=2.0,
                check=False,
            )
            self.assertEqual(
                completed.returncode,
                0,
                completed.stderr.decode("utf-8", "replace"),
            )

    def test_wait_window_covers_delayed_restarts_and_remains_bounded(self) -> None:
        self.assertEqual(deferred.DEFAULT_WAIT_SECONDS, 86_400)
        self.assertEqual(deferred.MAX_WAIT_SECONDS, 604_800)
        self.assertEqual(
            deferred._validated_wait_seconds(deferred.DEFAULT_WAIT_SECONDS),
            86_400,
        )
        self.assertEqual(
            deferred._validated_wait_seconds(deferred.MAX_WAIT_SECONDS),
            604_800,
        )
        for invalid in (0, 604_801, True):
            with self.subTest(invalid=invalid), self.assertRaises(
                deferred.DeferredInstallError
            ):
                deferred._validated_wait_seconds(invalid)

    def test_long_wait_uses_bounded_polling_and_private_state_heartbeat(self) -> None:
        self.assertEqual(deferred.WAIT_POLL_SECONDS, 1.0)
        self.assertEqual(deferred.QUIESCENCE_POLL_SECONDS, 0.1)
        self.assertEqual(deferred.STATE_HEARTBEAT_SECONDS, 300.0)
        self.assertLessEqual(
            deferred.MAX_WAIT_SECONDS / deferred.WAIT_POLL_SECONDS,
            604_800,
        )
        self.assertLessEqual(
            deferred.MAX_WAIT_SECONDS / deferred.STATE_HEARTBEAT_SECONDS,
            2_016,
        )
        self.assertLessEqual(
            deferred.QUIESCENCE_POLL_SECONDS, deferred.QUIESCENCE_SECONDS
        )

    def test_strict_no_mutation_receipt_matrix_rejects_every_cross_pair(self) -> None:
        accepted = {
            ("failed-unapplied", "preparing", "worker-not-ready"),
            ("failed-unapplied", "waiting", "process-inspection-failed"),
            ("failed-unapplied", "quiescing", "process-inspection-failed"),
            ("cancelled", "waiting", "cancelled"),
            ("cancelled", "quiescing", "cancelled"),
            ("expired", "waiting", "wait-timeout"),
            ("expired", "quiescing", "wait-timeout"),
            ("target-race", "quiescing", "target-relaunched"),
        }
        statuses = tuple(sorted(deferred._TERMINAL_STATUSES))
        phases = tuple(sorted(deferred._RECEIPT_PHASES))
        failure_codes = tuple(sorted(deferred._FAILURE_CODES))
        for status_value in statuses:
            for phase in phases:
                for failure_code in failure_codes:
                    triple = (status_value, phase, failure_code)
                    value = {
                        "status": status_value,
                        "phase": phase,
                        "failure_code": failure_code,
                        "apply_status": "not-started",
                        "verification_ok": False,
                        "receiver_healthy": False,
                        "rollback_status": "not-applicable",
                    }
                    with self.subTest(triple=triple):
                        self.assertEqual(
                            deferred._is_strict_no_mutation_receipt(value),
                            triple in accepted,
                        )
        valid = {
            "status": "expired",
            "phase": "waiting",
            "failure_code": "wait-timeout",
            "apply_status": "not-started",
            "verification_ok": False,
            "receiver_healthy": False,
            "rollback_status": "not-applicable",
        }
        for field, replacements in (
            (
                "apply_status",
                tuple(sorted(deferred._APPLY_STATUSES - {"not-started"})),
            ),
            ("verification_ok", (True,)),
            ("receiver_healthy", (True,)),
            ("rollback_status", ("rolled-back", "blocked")),
        ):
            for replacement in replacements:
                candidate = dict(valid, **{field: replacement})
                with self.subTest(field=field, replacement=replacement):
                    self.assertFalse(
                        deferred._is_strict_no_mutation_receipt(candidate)
                    )

    def test_public_line_is_one_bounded_allowlisted_receipt(self) -> None:
        output = StringIO()
        private_key = "to" + "ken"
        private_value = "PRIVATE-VALUE-MUST-NOT-PERSIST"
        supplied = {
            "job_id": "a" * 32,
            "filename": "deferred-install-result.json",
            "status": "verified",
            "targets": 2,
            "wait_seconds": 900,
            "verification_ok": True,
            "receiver_healthy": True,
            "path": "ABSOLUTE-PATH-MUST-NOT-PERSIST",
            "pid": 123,
            "raw_error": "PROMPT-MUST-NOT-PERSIST",
        }
        supplied[private_key] = private_value
        with redirect_stdout(output):
            cli._deferred_line(
                "DEFERRED_INSTALL_STATUS",
                supplied,
            )
        line = output.getvalue()
        self.assertEqual(line.count("\n"), 1)
        self.assertTrue(line.startswith("DEFERRED_INSTALL_STATUS "))
        self.assertNotIn("ABSOLUTE-PATH-MUST-NOT-PERSIST", line)
        self.assertNotIn('"pid"', line)
        self.assertNotIn(private_value, line)
        self.assertNotIn("PROMPT-MUST-NOT-PERSIST", line)
        value = json.loads(line.split(" ", 1)[1])
        self.assertTrue(value["verification_ok"])
        self.assertTrue(value["receiver_healthy"])

    def test_receipt_is_categorical_and_contains_no_process_or_source_fields(self) -> None:
        value = deferred._receipt_value(
            job_id="b" * 32,
            plan_digest="c" * 64,
            status="verified",
            phase="complete",
            target_count=2,
            started_at="2026-08-02T00:00:00Z",
            apply_status="applied",
            verification_ok=True,
            receiver_healthy=True,
            rollback_status="not-applicable",
            failure_code="none",
        )
        raw = deferred._canonical_bytes(value)
        self.assertLessEqual(len(raw), deferred.MAX_RECEIPT_BYTES)
        for prohibited in (
            b"pid",
            b"executable",
            b"journal",
            b"source",
            b"command",
            b"token",
            b"environment",
        ):
            self.assertNotIn(prohibited, raw.lower())

    def test_receipt_validation_rejects_stale_or_inconsistent_success(self) -> None:
        valid = deferred._receipt_value(
            job_id="b" * 32,
            plan_digest="c" * 64,
            status="verified",
            phase="complete",
            target_count=2,
            started_at="2026-08-02T00:00:00Z",
            apply_status="applied",
            verification_ok=True,
            receiver_healthy=True,
            rollback_status="not-applicable",
            failure_code="none",
        )
        changed_job = dict(valid, job_id="d" * 32)
        changed_health = dict(valid, receiver_healthy=False)
        changed_shape = dict(valid, unexpected="value")
        for candidate in (changed_job, changed_health, changed_shape):
            with self.assertRaises(deferred.DeferredInstallError):
                deferred._validated_receipt(
                    candidate,
                    job_id="b" * 32,
                    plan_digest="c" * 64,
                    target_count=2,
                )

    def test_terminal_receipt_is_not_published_when_state_commit_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="deferred-finish-") as raw:
            root = Path(raw).resolve()
            paths = {
                "state": root / "state.json",
                "receipt": root / "deferred-install-result.json",
            }
            receipt = deferred._receipt_value(
                job_id="e" * 32,
                plan_digest="f" * 64,
                status="verified",
                phase="complete",
                target_count=1,
                started_at="2026-08-02T00:00:00Z",
                apply_status="applied",
                verification_ok=True,
                receiver_healthy=True,
                rollback_status="not-applicable",
                failure_code="none",
            )
            with mock.patch.object(
                deferred,
                "_publish_state",
                side_effect=OSError("injected state failure"),
            ):
                with self.assertRaises(OSError):
                    deferred._finish(paths, receipt)
            self.assertFalse(paths["receipt"].exists())

    def test_cancel_marker_must_bind_the_exact_job(self) -> None:
        with tempfile.TemporaryDirectory(prefix="deferred-cancel-") as raw:
            root = Path(raw).resolve()
            path = root / "cancel.json"
            deferred._write_once(
                path,
                deferred._canonical_bytes(
                    {
                        "schema_version": deferred.DEFERRED_SCHEMA_VERSION,
                        "job_id": "d" * 32,
                        "requested_at_utc": "2026-08-02T00:00:00Z",
                    }
                ),
                deferred.MAX_RECEIPT_BYTES,
            )
            with self.assertRaises(deferred.DeferredInstallError):
                deferred._cancel_requested(path, "e" * 32)
            self.assertTrue(deferred._cancel_requested(path, "d" * 32))

    def test_receipt_validator_rejects_wrong_bindings_booleans_and_status(self) -> None:
        job_id = "7" * 32
        plan_digest = "8" * 64
        valid = deferred._receipt_value(
            job_id=job_id,
            plan_digest=plan_digest,
            status="expired",
            phase="waiting",
            target_count=1,
            started_at="2026-08-02T00:00:00Z",
            apply_status="not-started",
            verification_ok=False,
            receiver_healthy=False,
            rollback_status="not-applicable",
            failure_code="wait-timeout",
        )
        with self.assertRaises(deferred.DeferredInstallError):
            deferred._validated_receipt(
                valid, job_id="9" * 32, plan_digest=plan_digest
            )
        with self.assertRaises(deferred.DeferredInstallError):
            deferred._validated_receipt(
                valid, job_id=job_id, plan_digest="a" * 64
            )
        for field, replacement in (
            ("verification_ok", 0),
            ("receiver_healthy", 1),
            ("status", "armed"),
        ):
            changed = dict(valid)
            changed[field] = replacement
            with self.subTest(field=field), self.assertRaises(
                deferred.DeferredInstallError
            ):
                deferred._validated_receipt(
                    changed, job_id=job_id, plan_digest=plan_digest
                )

    def test_detach_uses_argv_devnull_sanitized_environment_and_no_shell(self) -> None:
        process = mock.Mock()
        with mock.patch.object(deferred.subprocess, "Popen", return_value=process) as popen:
            with mock.patch.dict(
                os.environ,
                {
                    "PROMPT_MUST_NOT_PERSIST": "secret",
                    "HOME": "/private/home",
                    "LANG": "C.UTF-8",
                },
                clear=True,
            ):
                result = deferred._spawn_worker(
                    Path(sys.executable),
                    Path("/private/runtime"),
                    Path("/private/request.json"),
                    "f" * 64,
                )
        self.assertIs(result, process)
        command = popen.call_args.args[0]
        options = popen.call_args.kwargs
        self.assertIsInstance(command, list)
        self.assertEqual(command[1:3], ["-I", "-B"])
        self.assertNotIn("shell", options)
        self.assertIs(options["stdin"], subprocess.DEVNULL)
        self.assertIs(options["stdout"], subprocess.DEVNULL)
        self.assertIs(options["stderr"], subprocess.DEVNULL)
        self.assertTrue(options["close_fds"])
        self.assertNotIn("PROMPT_MUST_NOT_PERSIST", options["env"])
        self.assertNotIn("HOME", options["env"])
        if os.name == "nt":
            self.assertTrue(options["creationflags"] & 0x01000000)
        else:
            self.assertTrue(options["start_new_session"])


class ActiveJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="deferred-active-")
        self.root = Path(self.temporary.name).resolve()
        self.transaction = self.root / "transaction"
        self.transaction.mkdir()
        os.chmod(str(self.transaction), 0o700)
        self.journal = self.transaction / "journal.json"

        class Plan:
            pass

        self.plan = Plan()
        self.plan.journal_path = self.journal
        self.plan.journal = {
            "transaction_identity": installer._directory_identity(
                self.transaction, "test transaction"
            )
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def active(self, job_id: str) -> dict[str, object]:
        return {
            "schema_version": deferred.DEFERRED_SCHEMA_VERSION,
            "job_id": job_id,
            "plan_sha256": "a" * 64,
        }

    def test_duplicate_active_job_is_refused_but_terminal_job_can_be_replaced(self) -> None:
        first_id = "1" * 32
        first_paths = deferred._job_paths(self.journal, first_id)
        deferred._secure_directory(first_paths["root"])
        deferred._acquire_active_job(self.plan, first_paths, self.active(first_id))
        second_id = "2" * 32
        second_paths = deferred._job_paths(self.journal, second_id)
        deferred._secure_directory(second_paths["root"])
        with self.assertRaises(deferred.DeferredInstallError):
            deferred._acquire_active_job(
                self.plan, second_paths, self.active(second_id)
            )
        deferred._write_once(
            first_paths["receipt"],
            deferred._canonical_bytes(
                deferred._receipt_value(
                    job_id=first_id,
                    plan_digest="a" * 64,
                    status="expired",
                    phase="waiting",
                    target_count=1,
                    started_at="2026-08-02T00:00:00Z",
                    apply_status="not-started",
                    verification_ok=False,
                    receiver_healthy=False,
                    rollback_status="not-applicable",
                    failure_code="wait-timeout",
                )
            ),
            deferred.MAX_RECEIPT_BYTES,
        )
        deferred._acquire_active_job(self.plan, second_paths, self.active(second_id))
        self.assertEqual(
            deferred._read_object(second_paths["active"], deferred.MAX_RECEIPT_BYTES),
            self.active(second_id),
        )

    def test_exact_failed_arm_release_allows_retry(self) -> None:
        job_id = "3" * 32
        paths = deferred._job_paths(self.journal, job_id)
        deferred._secure_directory(paths["root"])
        active = self.active(job_id)
        deferred._acquire_active_job(self.plan, paths, active)
        deferred._release_active_job(self.plan, paths, active)
        self.assertFalse(paths["active"].exists())
        retry_id = "4" * 32
        retry_paths = deferred._job_paths(self.journal, retry_id)
        deferred._secure_directory(retry_paths["root"])
        deferred._acquire_active_job(self.plan, retry_paths, self.active(retry_id))
        self.assertTrue(retry_paths["active"].is_file())

    def test_dead_ready_worker_on_pristine_plan_is_replaceable(self) -> None:
        first_id = "5" * 32
        first_paths = deferred._job_paths(self.journal, first_id)
        deferred._secure_directory(first_paths["root"])
        deferred._acquire_active_job(self.plan, first_paths, self.active(first_id))
        request_raw = b'{"request":"binding"}\n'
        deferred._write_once(
            first_paths["request"], request_raw, deferred.MAX_REQUEST_BYTES
        )
        worker = identity(91, "start", "/opt/python", "1:9")
        deferred._write_once(
            first_paths["ready"],
            deferred._canonical_bytes(
                {
                    "schema_version": deferred.DEFERRED_SCHEMA_VERSION,
                    "job_id": first_id,
                    "request_sha256": deferred._digest(request_raw),
                    "worker_process": worker.private_value(),
                }
            ),
            deferred.MAX_RECEIPT_BYTES,
        )
        second_id = "6" * 32
        second_paths = deferred._job_paths(self.journal, second_id)
        deferred._secure_directory(second_paths["root"])
        inspector = mock.Mock()
        inspector.is_alive.return_value = False
        with mock.patch.object(
            deferred, "ProcessInspector", return_value=inspector
        ), mock.patch.object(deferred, "_plan_status", return_value="planned"):
            deferred._acquire_active_job(
                self.plan, second_paths, self.active(second_id)
            )
        self.assertEqual(
            deferred._read_object(second_paths["active"], deferred.MAX_RECEIPT_BYTES),
            self.active(second_id),
        )


class DeferredWorkerRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="deferred-worker-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        home = self.root / "codex-home"
        home.mkdir()
        self.plan = installer.plan_install(
            ROOT,
            self.root / "state",
            {"worker-test": home},
            python_executable=Path(sys.executable).resolve(),
        )
        self.job_id = "7" * 32
        self.paths = deferred._job_paths(self.plan.journal_path, self.job_id)
        self.paths["root"].mkdir(parents=True, mode=0o700)
        self.target = identity(71, "target-start", "/opt/codex", "1:71")
        self.worker = identity(
            os.getpid(), "worker-start", sys.executable, "1:72"
        )
        self.request = deferred._request_value(
            journal=self.plan.journal_path,
            plan_digest=self.plan.plan_digest,
            job_id=self.job_id,
            wait_seconds=30,
            payload_digest=self.plan.journal["source"]["payload_sha256"],
            targets=[self.target],
            peers=[],
        )
        self.request_raw = deferred._canonical_bytes(self.request)
        self.request_digest = deferred._digest(self.request_raw)
        deferred._write_once(
            self.paths["request"], self.request_raw, deferred.MAX_REQUEST_BYTES
        )

    def _replace_request_wait(self, wait_seconds: int) -> str:
        request = dict(self.request, wait_seconds=wait_seconds)
        raw = deferred._canonical_bytes(request)
        deferred._atomic_write(
            self.paths["request"], raw, deferred.MAX_REQUEST_BYTES
        )
        return deferred._digest(raw)

    def test_wait_loop_expires_exactly_with_sparse_heartbeats_and_no_apply(self) -> None:
        request_digest = self._replace_request_wait(601)
        publications: list[dict[str, object]] = []

        class Clock:
            now = 0.0
            sleeps: list[float] = []

            def monotonic(inner_self) -> float:
                return inner_self.now

            def sleep(inner_self, seconds: float) -> None:
                inner_self.sleeps.append(seconds)
                inner_self.now += seconds

        clock = Clock()

        class Inspector:
            def is_alive(inner_self, _value: processes.ProcessIdentity) -> bool:
                return True

            def capture(inner_self, pid: int) -> processes.ProcessIdentity:
                self.assertEqual(pid, os.getpid())
                return self.worker

            def detected_relaunches(inner_self, _targets, _peers):
                raise AssertionError("quiescence must not start before expiry")

        with mock.patch.object(
            deferred, "ProcessInspector", return_value=Inspector()
        ), mock.patch.object(
            installer,
            "source_tree_digest",
            return_value=self.plan.journal["source"]["payload_sha256"],
        ), mock.patch.object(
            deferred, "_cancel_requested", return_value=False
        ), mock.patch.object(
            deferred,
            "_publish_state",
            side_effect=lambda _paths, value: publications.append(dict(value)),
        ), mock.patch.object(
            deferred.time, "monotonic", side_effect=clock.monotonic
        ), mock.patch.object(
            deferred.time, "sleep", side_effect=clock.sleep
        ), mock.patch.object(
            installer,
            "apply_install",
            side_effect=AssertionError("expiry must never apply"),
        ) as apply_install:
            result = deferred._run_deferred_install_once(
                self.paths["request"], request_digest
            )

        self.assertEqual(result["status"], "expired")
        self.assertEqual(result["apply_status"], "not-started")
        self.assertEqual(clock.now, 601.0)
        self.assertTrue(clock.sleeps)
        self.assertLessEqual(max(clock.sleeps), deferred.WAIT_POLL_SECONDS)
        armed_waiting = [
            value
            for value in publications
            if value.get("status") == "armed" and value.get("phase") == "waiting"
        ]
        self.assertEqual(len(armed_waiting), 3)
        apply_install.assert_not_called()

    def test_wait_loop_observes_pre_apply_cancel_within_one_poll(self) -> None:
        publications: list[dict[str, object]] = []

        class Clock:
            now = 0.0
            sleeps: list[float] = []

            def monotonic(inner_self) -> float:
                return inner_self.now

            def sleep(inner_self, seconds: float) -> None:
                inner_self.sleeps.append(seconds)
                inner_self.now += seconds

        clock = Clock()

        class Inspector:
            def is_alive(inner_self, _value: processes.ProcessIdentity) -> bool:
                return True

            def capture(inner_self, _pid: int) -> processes.ProcessIdentity:
                return self.worker

            def detected_relaunches(inner_self, _targets, _peers):
                return []

        with mock.patch.object(
            deferred, "ProcessInspector", return_value=Inspector()
        ), mock.patch.object(
            installer,
            "source_tree_digest",
            return_value=self.plan.journal["source"]["payload_sha256"],
        ), mock.patch.object(
            deferred,
            "_cancel_requested",
            side_effect=lambda _path, _job: clock.now >= 2.5,
        ), mock.patch.object(
            deferred,
            "_publish_state",
            side_effect=lambda _paths, value: publications.append(dict(value)),
        ), mock.patch.object(
            deferred.time, "monotonic", side_effect=clock.monotonic
        ), mock.patch.object(
            deferred.time, "sleep", side_effect=clock.sleep
        ), mock.patch.object(
            installer,
            "apply_install",
            side_effect=AssertionError("cancel must never apply"),
        ) as apply_install:
            result = deferred._run_deferred_install_once(
                self.paths["request"], self.request_digest
            )

        self.assertEqual(result["status"], "cancelled")
        self.assertGreaterEqual(clock.now, 2.5)
        self.assertLess(clock.now, 2.5 + deferred.WAIT_POLL_SECONDS)
        self.assertLessEqual(max(clock.sleeps), deferred.WAIT_POLL_SECONDS)
        self.assertEqual(
            len(
                [
                    value
                    for value in publications
                    if value.get("status") == "armed"
                    and value.get("phase") == "waiting"
                ]
            ),
            1,
        )
        apply_install.assert_not_called()

    def test_quiescence_keeps_fast_relaunch_checks(self) -> None:
        class Clock:
            now = 0.0
            sleeps: list[float] = []

            def monotonic(inner_self) -> float:
                return inner_self.now

            def sleep(inner_self, seconds: float) -> None:
                inner_self.sleeps.append(seconds)
                inner_self.now += seconds

        clock = Clock()

        class Inspector:
            alive_checks = 0
            relaunch_checks = 0

            def is_alive(inner_self, _value: processes.ProcessIdentity) -> bool:
                inner_self.alive_checks += 1
                return inner_self.alive_checks == 1

            def capture(inner_self, _pid: int) -> processes.ProcessIdentity:
                return self.worker

            def detected_relaunches(inner_self, _targets, _peers):
                inner_self.relaunch_checks += 1
                return [] if inner_self.relaunch_checks == 1 else [self.target]

        inspector = Inspector()
        with mock.patch.object(
            deferred, "ProcessInspector", return_value=inspector
        ), mock.patch.object(
            installer,
            "source_tree_digest",
            return_value=self.plan.journal["source"]["payload_sha256"],
        ), mock.patch.object(
            deferred, "_cancel_requested", return_value=False
        ), mock.patch.object(
            deferred, "_publish_state"
        ), mock.patch.object(
            deferred.time, "monotonic", side_effect=clock.monotonic
        ), mock.patch.object(
            deferred.time, "sleep", side_effect=clock.sleep
        ), mock.patch.object(
            installer,
            "apply_install",
            side_effect=AssertionError("target race must never apply"),
        ) as apply_install:
            result = deferred._run_deferred_install_once(
                self.paths["request"], self.request_digest
            )

        self.assertEqual(result["status"], "target-race")
        self.assertEqual(inspector.relaunch_checks, 2)
        self.assertEqual(clock.sleeps, [deferred.QUIESCENCE_POLL_SECONDS])
        apply_install.assert_not_called()

    def test_cancel_and_deadline_cannot_interrupt_after_apply_begins(self) -> None:
        applying = False
        cancel_checks = 0
        real_monotonic = time.monotonic

        class Inspector:
            target_checks = 0

            def is_alive(inner_self, value):
                if value.pid != self.target.pid:
                    return True
                inner_self.target_checks += 1
                return inner_self.target_checks == 1

            def capture(inner_self, pid):
                self.assertEqual(pid, os.getpid())
                return self.worker

            def detected_relaunches(inner_self, _targets, _peers):
                return []

        def monotonic() -> float:
            if applying:
                raise AssertionError("deadline was consulted after apply began")
            return real_monotonic()

        def cancelled(_path, _job_id) -> bool:
            nonlocal cancel_checks
            if applying:
                raise AssertionError("cancellation was consulted after apply began")
            cancel_checks += 1
            return False

        def apply_install(
            _journal,
            *,
            plan_digest,
            mutation_guard,
            require_planned,
        ):
            nonlocal applying
            self.assertEqual(plan_digest, self.plan.plan_digest)
            self.assertTrue(require_planned)
            applying = True
            mutation_guard()
            return {"status": "applied", "receiver_healthy": True}

        with mock.patch.object(
            deferred, "ProcessInspector", return_value=Inspector()
        ), mock.patch.object(
            deferred, "QUIESCENCE_SECONDS", 0.0
        ), mock.patch.object(
            deferred.time, "monotonic", side_effect=monotonic
        ), mock.patch.object(
            deferred, "_cancel_requested", side_effect=cancelled
        ), mock.patch.object(
            installer,
            "source_tree_digest",
            return_value=self.plan.journal["source"]["payload_sha256"],
        ), mock.patch.object(
            installer, "apply_install", new=apply_install
        ), mock.patch.object(
            installer,
            "verify_install",
            return_value={"ok": True, "status": "applied"},
        ):
            result = deferred._run_deferred_install_once(
                self.paths["request"], self.request_digest
            )

        self.assertEqual(result["status"], "verified")
        self.assertEqual(cancel_checks, 1)

    def test_post_ready_failure_recovers_to_failure_receipt(self) -> None:
        deferred._write_once(
            self.paths["ready"],
            deferred._canonical_bytes(
                {
                    "schema_version": deferred.DEFERRED_SCHEMA_VERSION,
                    "job_id": self.job_id,
                    "request_sha256": self.request_digest,
                    "worker_process": self.worker.private_value(),
                }
            ),
            deferred.MAX_RECEIPT_BYTES,
        )
        with mock.patch.object(
            deferred,
            "_run_deferred_install_once",
            side_effect=RuntimeError("post-ready worker failure"),
        ), mock.patch.object(deferred, "_plan_status", return_value="planned"):
            result = deferred.run_deferred_install(
                self.paths["request"], self.request_digest
            )

        self.assertEqual(result["status"], "failed-unapplied")
        self.assertEqual(result["failure_code"], "worker-lost")
        self.assertFalse(result["verification_ok"])
        saved, _raw = deferred._read_receipt(
            self.paths["receipt"],
            job_id=self.job_id,
            plan_digest=self.plan.plan_digest,
            target_count=1,
        )
        self.assertEqual(saved, result)


class DeferredStatusRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="deferred-status-recovery-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        home = self.root / "codex-home"
        home.mkdir()
        self.plan = installer.plan_install(
            ROOT,
            self.root / "state",
            {"status-recovery": home},
            python_executable=Path(sys.executable).resolve(),
        )
        self.job_id = "9" * 32
        self.paths = deferred._job_paths(self.plan.journal_path, self.job_id)
        self.paths["root"].mkdir(parents=True, mode=0o700)
        request = deferred._request_value(
            journal=self.plan.journal_path,
            plan_digest=self.plan.plan_digest,
            job_id=self.job_id,
            wait_seconds=900,
            payload_digest=self.plan.journal["source"]["payload_sha256"],
            targets=[identity(91, "target-start", "/opt/codex", "1:91")],
            peers=[],
        )
        deferred._write_once(
            self.paths["request"],
            deferred._canonical_bytes(request),
            deferred.MAX_REQUEST_BYTES,
        )
        self._filesystem_identity = installer._filesystem_identity

    def _receipt(self, **overrides: object) -> dict[str, object]:
        values: dict[str, object] = {
            "status": "expired",
            "phase": "waiting",
            "apply_status": "not-started",
            "verification_ok": False,
            "receiver_healthy": False,
            "rollback_status": "not-applicable",
            "failure_code": "wait-timeout",
        }
        values.update(overrides)
        return deferred._receipt_value(
            job_id=self.job_id,
            plan_digest=self.plan.plan_digest,
            target_count=1,
            started_at="2026-08-02T00:00:00Z",
            **values,
        )

    def _save_receipt(self, value: dict[str, object]) -> bytes:
        raw = deferred._canonical_bytes(value)
        deferred._atomic_write(
            self.paths["receipt"], raw, deferred.MAX_RECEIPT_BYTES
        )
        return raw

    def _reboot_filesystem_identity(self, metadata: os.stat_result) -> dict[str, int]:
        current = self._filesystem_identity(metadata)
        current["device"] += 1
        return current

    def test_expired_no_mutation_receipt_survives_plan_identity_conflict(self) -> None:
        raw = self._save_receipt(self._receipt())
        transaction = self.plan.journal_path.parent

        def snapshot() -> dict[str, bytes]:
            return {
                str(path.relative_to(transaction)): path.read_bytes()
                for path in sorted(transaction.rglob("*"))
                if path.is_file()
            }

        before = snapshot()
        with mock.patch.object(
            installer,
            "_filesystem_identity",
            side_effect=self._reboot_filesystem_identity,
        ), mock.patch.object(
            deferred,
            "_write_once",
            side_effect=AssertionError("status recovery must not publish"),
        ), mock.patch.object(
            deferred,
            "_atomic_write",
            side_effect=AssertionError("status recovery must not mutate state"),
        ), mock.patch.object(
            installer,
            "verify_install",
            side_effect=AssertionError("status recovery must not verify"),
        ), mock.patch.object(
            installer,
            "rollback_install",
            side_effect=AssertionError("status recovery must not roll back"),
        ):
            with self.assertRaises(installer.InstallerTransactionIdentityConflict):
                installer.load_plan(self.plan.journal_path, self.plan.plan_digest)
            result = deferred.read_deferred_install_status(
                self.plan.journal_path, self.plan.plan_digest, self.job_id
            )

            with self.assertRaises(installer.InstallerTransactionIdentityConflict):
                installer.apply_install(
                    self.plan.journal_path, plan_digest=self.plan.plan_digest
                )
            with self.assertRaises(installer.InstallerTransactionIdentityConflict):
                deferred.arm_deferred_install(
                    self.plan.journal_path,
                    self.plan.plan_digest,
                    [],
                    deferred.DEFAULT_WAIT_SECONDS,
                )
            with self.assertRaises(installer.InstallerTransactionIdentityConflict):
                deferred.cancel_deferred_install(
                    self.plan.journal_path,
                    self.plan.plan_digest,
                    self.job_id,
                )
        self.assertEqual(snapshot(), before)

        self.assertEqual(result["status"], "expired")
        self.assertEqual(result["filename"], "deferred-install-result.json")
        self.assertEqual(result["sha256"], deferred._digest(raw))
        self.assertEqual(result["bytes"], len(raw))
        self.assertEqual(result["wait_seconds"], 900)
        self.assertFalse(result["verification_ok"])
        self.assertFalse(result["receiver_healthy"])
        self.assertEqual(result["rollback_status"], "not-applicable")

    def test_identity_conflict_fallback_rejects_success_and_mutation_receipts(self) -> None:
        candidates = (
            self._receipt(
                status="verified",
                phase="complete",
                apply_status="applied",
                verification_ok=True,
                receiver_healthy=True,
                failure_code="none",
            ),
            self._receipt(
                status="failed-rolled-back",
                phase="verifying",
                apply_status="rolled-back",
                rollback_status="rolled-back",
                failure_code="installer-failure",
            ),
            self._receipt(
                status="failed-unapplied",
                phase="applying",
                apply_status="applying",
                failure_code="installer-failure",
            ),
            self._receipt(
                status="expired",
                phase="preparing",
                failure_code="worker-not-ready",
            ),
        )
        with mock.patch.object(
            installer,
            "_filesystem_identity",
            side_effect=self._reboot_filesystem_identity,
        ):
            with self.assertRaises(deferred.DeferredInstallError):
                deferred.read_deferred_install_status(
                    self.plan.journal_path,
                    self.plan.plan_digest,
                    self.job_id,
                )
            for candidate in candidates:
                with self.subTest(
                    status=candidate["status"], apply=candidate["apply_status"]
                ):
                    self._save_receipt(candidate)
                    with self.assertRaises(deferred.DeferredInstallError):
                        deferred.read_deferred_install_status(
                            self.plan.journal_path,
                            self.plan.plan_digest,
                            self.job_id,
                        )

    def test_identity_conflict_fallback_rejects_immutable_journal_drift(self) -> None:
        self._save_receipt(self._receipt())
        journal = json.loads(self.plan.journal_path.read_text(encoding="utf-8"))
        journal["python_executable"] = str(self.root / "different-python")
        self.plan.journal_path.write_bytes(installer._json_bytes(journal))
        with mock.patch.object(
            installer,
            "_filesystem_identity",
            side_effect=self._reboot_filesystem_identity,
        ):
            with self.assertRaises(deferred.DeferredInstallError):
                deferred.read_deferred_install_status(
                    self.plan.journal_path,
                    self.plan.plan_digest,
                    self.job_id,
                )


class CliContractTests(unittest.TestCase):
    def test_deferred_cli_contract_and_default_timeout(self) -> None:
        parser = cli.build_parser()
        defer = parser.parse_args(
            [
                "install",
                "defer",
                "--journal",
                "/tmp/journal.json",
                "--plan-digest",
                "a" * 64,
                "--target-pid",
                "41",
                "--target-pid",
                "42",
            ]
        )
        self.assertEqual(defer.target_pid, [41, 42])
        self.assertEqual(defer.wait_seconds, deferred.DEFAULT_WAIT_SECONDS)
        self.assertEqual(defer.wait_seconds, 86_400)
        for action in ("deferred-status", "deferred-cancel"):
            parsed = parser.parse_args(
                [
                    "install",
                    action,
                    "--journal",
                    "/tmp/journal.json",
                    "--plan-digest",
                    "a" * 64,
                    "--job-id",
                    "b" * 32,
                ]
            )
            self.assertEqual(parsed.job_id, "b" * 32)

    def test_ready_failure_is_never_reported_as_armed(self) -> None:
        arguments = cli.build_parser().parse_args(
            [
                "install",
                "defer",
                "--journal",
                "/tmp/journal.json",
                "--plan-digest",
                "a" * 64,
                "--target-pid",
                "41",
            ]
        )
        result = {
            "job_id": "b" * 32,
            "filename": "deferred-install-result.json",
            "status": "failed-unapplied",
            "targets": 1,
            "wait_seconds": 900,
            "phase": "preparing",
            "sha256": "c" * 64,
            "bytes": 400,
            "verification_ok": False,
            "receiver_healthy": False,
            "rollback_status": "not-applicable",
            "failure_code": "worker-not-ready",
        }
        output = StringIO()
        with mock.patch(
            "delivery_efficiency.deferred_install.arm_deferred_install",
            return_value=result,
        ), redirect_stdout(output):
            exit_code = cli._install_defer(arguments)
        self.assertEqual(exit_code, 2)
        self.assertTrue(
            output.getvalue().startswith("DEFERRED_INSTALL_RECEIPT_SAVED ")
        )
        self.assertNotIn("DEFERRED_INSTALL_ARMED", output.getvalue())


class NativeDeferredIntegrationTests(unittest.TestCase):
    def _target_command(self, base: Path) -> list[str]:
        del base
        if os.name == "nt":
            windows = os.environ.get("WINDIR", r"C:\Windows")
            source = Path(windows) / "System32" / "PING.EXE"
            if not source.is_file():
                self.skipTest("native Windows long-lived test executable is unavailable")
            return [str(source), "127.0.0.1", "-n", "30"]
        yes = Path("/usr/bin/yes")
        if yes.is_file():
            return [str(yes)]
        sleep = next(
            (
                candidate
                for candidate in (Path("/bin/sleep"), Path("/usr/bin/sleep"))
                if candidate.is_file()
            ),
            None,
        )
        if sleep is None:
            self.skipTest("native POSIX sleep executable is unavailable")
        return [str(sleep), "30"]

    def test_detached_worker_survives_launcher_exit_and_verifies(self) -> None:
        from delivery_efficiency.installer import plan_install
        from delivery_efficiency.runtime import (
            load_settings,
            request_receiver_retirement,
        )

        temporary = tempfile.TemporaryDirectory(prefix="deferred-native-")
        base = Path(temporary.name).resolve()
        target = None
        state = base / "state"
        try:
            home = base / "codex-home"
            home.mkdir()
            plan = plan_install(
                ROOT,
                state,
                {"native-test": home},
                python_executable=Path(sys.executable).resolve(),
            )
            target = subprocess.Popen(
                self._target_command(base),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            launcher = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "recorder.py"),
                    "install",
                    "defer",
                    "--journal",
                    str(plan.journal_path),
                    "--plan-digest",
                    str(plan.plan_digest),
                    "--target-pid",
                    str(target.pid),
                    "--wait-seconds",
                    "20",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                timeout=20,
                check=False,
            )
            self.assertEqual(
                launcher.returncode,
                0,
                launcher.stdout.decode("utf-8", "replace")
                + launcher.stderr.decode("utf-8", "replace"),
            )
            line = launcher.stdout.decode("utf-8")
            self.assertTrue(line.startswith("DEFERRED_INSTALL_ARMED "))
            self.assertNotIn(str(plan.journal_path), line)
            self.assertNotIn(str(target.pid), line)
            armed = json.loads(line.split(" ", 1)[1])
            target.terminate()
            target.wait(timeout=5)
            deadline = time.monotonic() + 20
            status = None
            while time.monotonic() < deadline:
                status = deferred.read_deferred_install_status(
                    plan.journal_path, plan.plan_digest, armed["job_id"]
                )
                if status.get("status") != "armed":
                    break
                time.sleep(0.1)
            self.assertIsNotNone(status)
            self.assertEqual(status.get("status"), "verified")
            self.assertIs(status.get("verification_ok"), True)
            self.assertIs(status.get("receiver_healthy"), True)
            settings = load_settings(state)
            request_receiver_retirement(settings, timeout_seconds=1.0)
            time.sleep(0.3)
        finally:
            if target is not None and target.poll() is None:
                target.terminate()
                target.wait(timeout=5)
            if os.name == "nt" and base.exists():
                for path in sorted(base.rglob("*"), reverse=True):
                    try:
                        os.chmod(str(path), stat.S_IWRITE | stat.S_IREAD)
                    except OSError:
                        pass
            temporary.cleanup()

    def test_failed_ready_arm_releases_active_job_and_real_retry_can_cancel(self) -> None:
        from delivery_efficiency.installer import plan_install

        temporary = tempfile.TemporaryDirectory(prefix="deferred-ready-retry-")
        base = Path(temporary.name).resolve()
        target = None
        try:
            home = base / "codex-home"
            home.mkdir()
            state = base / "state"
            plan = plan_install(
                ROOT,
                state,
                {"retry-test": home},
                python_executable=Path(sys.executable).resolve(),
            )
            target = subprocess.Popen(
                self._target_command(base),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            stopped = mock.Mock()
            stopped.poll.return_value = 2
            with mock.patch.object(deferred, "_spawn_worker", return_value=stopped):
                failed = deferred.arm_deferred_install(
                    plan.journal_path, plan.plan_digest, [target.pid], 20
                )
            self.assertEqual(failed["status"], "failed-unapplied")
            self.assertFalse((plan.journal_path.parent / "deferred-active.json").exists())
            retry = deferred.arm_deferred_install(
                plan.journal_path, plan.plan_digest, [target.pid], 20
            )
            self.assertEqual(retry["status"], "armed")
            deferred.cancel_deferred_install(
                plan.journal_path, plan.plan_digest, retry["job_id"]
            )
            deadline = time.monotonic() + 5
            status = None
            while time.monotonic() < deadline:
                status = deferred.read_deferred_install_status(
                    plan.journal_path, plan.plan_digest, retry["job_id"]
                )
                if status.get("status") != "armed":
                    break
                time.sleep(0.05)
            self.assertEqual(status.get("status"), "cancelled")
        finally:
            if target is not None and target.poll() is None:
                target.terminate()
                target.wait(timeout=5)
            if os.name == "nt" and base.exists():
                for path in sorted(base.rglob("*"), reverse=True):
                    try:
                        os.chmod(str(path), stat.S_IWRITE | stat.S_IREAD)
                    except OSError:
                        pass
            temporary.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
