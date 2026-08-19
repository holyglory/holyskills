#!/usr/bin/env python3
"""Deterministic safety and lifecycle tests for the portable installer."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock


TOOL_ROOT = Path(__file__).resolve().parent
if str(TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOL_ROOT))

from delivery_efficiency import installer  # noqa: E402
from delivery_efficiency import runtime  # noqa: E402
from delivery_efficiency import server  # noqa: E402
from delivery_efficiency import (  # noqa: E402
    CLAUDE_HOOK_TELEMETRY_BUDGET_SECONDS,
    CLAUDE_ORDINARY_HOOK_TELEMETRY_BUDGET_SECONDS,
    CLAUDE_PROMPT_HOOK_TELEMETRY_BUDGET_SECONDS,
)


class InstallerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="delivery-installer-test-")
        self.real_activate_receiver = installer._activate_receiver
        self.receiver_activation = mock.patch.object(
            installer, "_activate_receiver", return_value=None
        )
        self.receiver_activation.start()
        # macOS commonly returns /var/... while /var is a host-managed symlink.
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "source tool"
        self.state = self.root / "state & telemetry"
        self.home = self.root / "Codex home's % configuration"
        self.home.mkdir(parents=True)
        self._make_source()

    def tearDown(self) -> None:
        self.receiver_activation.stop()
        self.temporary.cleanup()

    def _make_source(self) -> None:
        package = self.source / "delivery_efficiency"
        contract = self.source / "contract"
        package.mkdir(parents=True)
        contract.mkdir()
        (self.source / "recorder.py").write_text(
            "import os\nprint(os.environ.get('HOLYSKILLS_DELIVERY_EFFICIENCY_STATE_DIR', 'missing'))\n",
            encoding="utf-8",
        )
        (package / "__init__.py").write_text(
            "RECORDER_VERSION = '0.2.9'\nSCHEMA_VERSION = '1.2'\nADAPTER_VERSION = '0.2.4'\n",
            encoding="utf-8",
        )
        (package / "cli.py").write_text("def main(): return 0\n", encoding="utf-8")
        (contract / "adapter-event-v1.schema.json").write_text("{}\n", encoding="utf-8")
        (contract / "adapter-event-v1.1.schema.json").write_text("{}\n", encoding="utf-8")
        (contract / "adapter-event-v1.2.schema.json").write_text("{}\n", encoding="utf-8")
        # Prove test-only payloads are deliberately excluded from the immutable copy.
        (package / "ignored_self_test.py").write_text("raise RuntimeError('must not install')\n", encoding="utf-8")

    def _plan(self, **kwargs: object) -> installer.InstallPlan:
        return installer.plan_install(
            self.source,
            self.state,
            {"codex-main": self.home},
            python_executable=Path(sys.executable).resolve(),
            **kwargs,
        )

    def _stop_test_process(self, process: object) -> None:
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=2)

    def test_current_source_uses_unused_immutable_version(self) -> None:
        self.assertEqual(installer.RECORDER_VERSION, "0.2.9")
        occupied = self.state / "installs" / "0.1.2"
        (occupied / "delivery_efficiency").mkdir(parents=True)
        (occupied / "contract").mkdir()
        (occupied / "recorder.py").write_text("old immutable payload\n", encoding="utf-8")
        (occupied / "delivery_efficiency" / "__init__.py").write_text(
            "RECORDER_VERSION = '0.1.2'\n", encoding="utf-8"
        )
        (occupied / "contract" / "adapter-event-v1.schema.json").write_text(
            "{}\n", encoding="utf-8"
        )
        plan = self._plan()
        self.assertEqual(Path(plan.journal["target"]["install_root"]).name, "0.2.9")
        self.assertEqual((occupied / "recorder.py").read_text(), "old immutable payload\n")

    def test_historical_deferred_observation_never_authorizes_apply(self) -> None:
        with mock.patch.object(installer, "RECORDER_VERSION", "0.2.4"):
            historical = self._plan()
        with self.assertRaisesRegex(
            installer.InstallerConflict, "recorder version"
        ):
            installer.load_plan(historical.journal_path, historical.plan_digest)

        observed = installer.load_plan_for_deferred_observation(
            historical.journal_path,
            historical.plan_digest,
            {"0.2.4"},
        )
        self.assertEqual(observed.journal["recorder_version"], "0.2.4")
        with self.assertRaisesRegex(
            installer.InstallerConflict, "recorder version"
        ):
            installer._validate_journal_bindings(
                observed.journal, expected_recorder_version=""
            )
        with self.assertRaisesRegex(
            installer.InstallerConflict, "recorder version"
        ):
            installer.apply_install(observed, plan_digest=historical.plan_digest)
        with self.assertRaisesRegex(
            installer.InstallerConflict, "not observable"
        ):
            installer.load_plan_for_deferred_observation(
                historical.journal_path,
                historical.plan_digest,
                {"0.2.3"},
            )

    def test_runtime_target_refs_are_stable_distinct_and_path_hiding(self) -> None:
        token = "a" * 64
        second_home = self.root / "second runtime home"
        second_home.mkdir()
        first = installer._runtime_target_ref(token, "codex", self.home)
        repeated = installer._runtime_target_ref(token, "codex", self.home)
        second = installer._runtime_target_ref(token, "codex", second_home)
        other_runtime = installer._runtime_target_ref(token, "claude", self.home)

        self.assertRegex(first, r"^target_v1_[0-9a-f]{32}$")
        self.assertEqual(first, repeated)
        self.assertEqual(len({first, second, other_runtime}), 3)
        for reference in (first, second, other_runtime):
            self.assertNotIn(token, reference)
            self.assertNotIn(str(self.home), reference)
            self.assertNotIn(self.home.name, reference)
        self.assertNotEqual(
            first,
            installer._runtime_target_ref("b" * 64, "codex", self.home),
        )
        with self.assertRaises(installer.InstallerError):
            installer._runtime_target_ref(token, "other", self.home)
        with self.assertRaises(installer.InstallerError):
            installer._runtime_target_ref(token, "codex", Path("relative-home"))

    def test_each_codex_home_gets_its_exact_posix_and_windows_runtime_target(self) -> None:
        second_home = self.root / "second Codex home & %"
        second_home.mkdir()
        token = "c" * 64
        plan = installer.plan_install(
            self.source,
            self.state,
            {"codex-main": self.home, "codex-second": second_home},
            python_executable=Path(sys.executable).resolve(),
            auth_token=token,
            listen_port=4381,
        )
        installer.apply_install(plan)

        observed = set()
        for home in (self.home, second_home):
            value = json.loads((home / "hooks.json").read_text(encoding="utf-8"))
            managed = [
                handler
                for group in value["hooks"]["UserPromptSubmit"]
                for handler in group["hooks"]
                if installer._handler_is_managed(handler)
            ]
            self.assertEqual(len(managed), 1)
            expected = installer._runtime_target_ref(token, "codex", home)
            posix_arguments = shlex.split(managed[0]["command"])
            self.assertEqual(posix_arguments[1], str(self.state / "recorder.py"))
            self.assertNotIn("/installs/", posix_arguments[1].replace("\\", "/"))
            self.assertEqual(posix_arguments[-2:], ["--runtime-target", expected])
            encoded = managed[0]["commandWindows"].rsplit(" ", 1)[1]
            decoded = base64.b64decode(encoded).decode("utf-16le")
            self.assertIn(str(self.state / "recorder.py"), decoded)
            self.assertIn("'--runtime-target' '{}'".format(expected), decoded)
            self.assertNotIn(str(home), expected)
            observed.add(expected)
        self.assertEqual(len(observed), 2)

    def test_022_handler_upgrade_and_rollback_are_exact(self) -> None:
        previous_version = "0.2.2"
        previous_port = 4382
        token = "d" * 64
        old_install = self.state / "installs" / previous_version
        self.state.mkdir(parents=True)
        previous_settings = {
            "schema_version": installer.SETTINGS_SCHEMA_VERSION,
            "recorder_version": previous_version,
            "listen_host": "127.0.0.1",
            "listen_port": previous_port,
            "auth_token": token,
            "install_root": str(old_install),
            "python_executable": str(Path(sys.executable).resolve()),
            "platform": installer._platform_info(),
        }
        settings_bytes = installer._json_bytes(previous_settings)
        inventory_bytes = installer._managed_targets_bytes(
            [{"runtime": "codex", "name": "codex-main", "home": str(self.home)}]
        )
        legacy_handler = installer._hook_handler(
            Path(sys.executable).resolve(),
            old_install,
            self.state,
        )
        hooks_bytes = installer._render_hooks(b"", legacy_handler, None)
        config_bytes = installer._managed_otel_block(previous_port, token).encode("utf-8")
        (self.state / "settings.json").write_bytes(settings_bytes)
        (self.state / "managed-targets.json").write_bytes(inventory_bytes)
        (self.home / "hooks.json").write_bytes(hooks_bytes)
        (self.home / "config.toml").write_bytes(config_bytes)

        plan = self._plan()
        installer.apply_install(plan)
        installer.verify_install(plan)
        upgraded = json.loads((self.home / "hooks.json").read_text(encoding="utf-8"))
        command = upgraded["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
        expected = installer._runtime_target_ref(token, "codex", self.home)
        self.assertEqual(shlex.split(command)[-2:], ["--runtime-target", expected])

        installer.rollback_install(plan)
        self.assertEqual((self.state / "settings.json").read_bytes(), settings_bytes)
        self.assertEqual((self.state / "managed-targets.json").read_bytes(), inventory_bytes)
        self.assertEqual((self.home / "hooks.json").read_bytes(), hooks_bytes)
        self.assertEqual((self.home / "config.toml").read_bytes(), config_bytes)

    def test_runtime_target_handler_tampering_fails_closed(self) -> None:
        plan = self._plan(auth_token="e" * 64, listen_port=4383)
        installer.apply_install(plan)
        hooks_path = self.home / "hooks.json"
        original = hooks_path.read_text(encoding="utf-8")
        expected = installer._runtime_target_ref("e" * 64, "codex", self.home)
        tampered = original.replace(expected, "target_v1_" + "f" * 32)
        self.assertNotEqual(tampered, original)
        hooks_path.write_text(tampered, encoding="utf-8")
        with self.assertRaisesRegex(installer.InstallerConflict, "edited outside"):
            self._plan(persist=False)
        with self.assertRaises(installer.InstallerError):
            installer.rollback_install(plan)

    def test_claude_runtime_gate_requires_verified_non_chunked_release(self) -> None:
        # Anthropic records the non-chunked OTLP/HTTP export fix in v2.1.212.
        # Keep both sides of that exact release boundary as regression fixtures:
        # https://github.com/anthropics/claude-code/releases/tag/v2.1.212
        executable = Path(sys.executable).resolve()
        supported = subprocess.CompletedProcess(
            [str(executable), "--version"], 0, "2.1.212 (Claude Code)\n", ""
        )
        with mock.patch.object(installer.shutil, "which", return_value=str(executable)), mock.patch.object(
            installer.subprocess, "run", return_value=supported
        ):
            path, version = installer._probe_claude_runtime(None)
        self.assertEqual(path, executable)
        self.assertEqual(version, "2.1.212")

        unsupported = subprocess.CompletedProcess(
            [str(executable), "--version"], 0, "2.1.211 (Claude Code)\n", ""
        )
        with mock.patch.object(installer.subprocess, "run", return_value=unsupported):
            with self.assertRaisesRegex(installer.InstallerConflict, "2.1.212 or newer"):
                installer._probe_claude_runtime(executable)
        with mock.patch.object(installer.shutil, "which", return_value=None):
            with self.assertRaisesRegex(installer.InstallerConflict, "no Claude executable"):
                installer._probe_claude_runtime(None)

        from delivery_efficiency.cli import build_parser

        parsed = build_parser().parse_args(
            [
                "install",
                "plan",
                "--claude-home",
                "user={}".format(self.home),
                "--claude-executable",
                str(executable),
            ]
        )
        self.assertEqual(parsed.claude_executable, str(executable))

    def test_preserves_unrelated_hooks_and_is_idempotent(self) -> None:
        unrelated = {
            "description": "keep me",
            "custom": {"unchanged": [1, 2, 3]},
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [{"type": "command", "command": "existing --policy", "timeout": 9}],
                    }
                ]
            },
        }
        (self.home / "hooks.json").write_text(json.dumps(unrelated), encoding="utf-8")
        (self.home / "config.toml").write_text('model = "gpt-test"\n', encoding="utf-8")
        if os.name != "nt":
            self.home.chmod(0o755)

        first = self._plan(auth_token="a" * 64, listen_port=4327)
        result = installer.apply_install(first)
        self.assertTrue(result["ok"])
        hooks_after_first = (self.home / "hooks.json").read_bytes()
        config_after_first = (self.home / "config.toml").read_bytes()
        value = json.loads(hooks_after_first)
        self.assertEqual(value["description"], "keep me")
        self.assertEqual(value["custom"], unrelated["custom"])
        self.assertEqual(value["hooks"]["PreToolUse"][0], unrelated["hooks"]["PreToolUse"][0])
        for event in installer.HOOK_EVENTS:
            managed = [
                handler
                for group in value["hooks"][event]
                for handler in group["hooks"]
                if installer._handler_is_managed(handler)
            ]
            self.assertEqual(len(managed), 1, event)
            self.assertIn("commandWindows", managed[0])
            self.assertEqual(managed[0]["timeout"], installer.CODEX_HOOK_TIMEOUT_SECONDS)
        config_text = config_after_first.decode("utf-8")
        self.assertIn('model = "gpt-test"', config_text)
        self.assertIn("log_user_prompt = false", config_text)
        self.assertIn("http://127.0.0.1:4327/v1/logs", config_text)
        self.assertIn(installer.AUTH_HEADER, config_text)
        loaded_settings = runtime.load_settings(self.state)
        self.assertEqual(
            set(loaded_settings),
            {
                "schema_version",
                "recorder_version",
                "listen_host",
                "listen_port",
                "auth_token",
                "install_root",
                "python_executable",
                "platform",
            },
        )
        self.assertEqual(loaded_settings["auth_token"], first.auth_token)
        if os.name != "nt":
            self.assertEqual(self.home.stat().st_mode & 0o777, 0o755)
            self.assertEqual((self.home / "config.toml").stat().st_mode & 0o777, 0o600)
            self.assertEqual((self.state / "managed-targets.json").stat().st_mode & 0o777, 0o600)

        second = self._plan()
        installer.apply_install(second)
        self.assertEqual((self.home / "hooks.json").read_bytes(), hooks_after_first)
        self.assertEqual((self.home / "config.toml").read_bytes(), config_after_first)
        self.assertTrue(all(not action["changed"] for action in second.journal["actions"]))
        self.assertNotIn(first.auth_token, first.journal_path.read_text(encoding="utf-8"))
        self.assertNotIn(
            first.auth_token,
            (self.state / "managed-targets.json").read_text(encoding="utf-8"),
        )
        self.assertFalse(first.journal["security"]["windows_acl_hardened"])
        installed = Path(first.journal["target"]["install_root"])
        self.assertFalse((installed / "delivery_efficiency" / "ignored_self_test.py").exists())
        if os.name != "nt":
            self.assertEqual(first.journal_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(first.secret_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual((self.state / "settings.json").stat().st_mode & 0o777, 0o600)
            self.assertEqual((installed / "recorder.py").stat().st_mode & 0o222, 0)

    def test_malformed_hooks_json_causes_zero_installer_mutation(self) -> None:
        original = b'{"hooks": '
        (self.home / "hooks.json").write_bytes(original)
        with self.assertRaises(installer.InstallerConflict):
            self._plan()
        self.assertFalse(self.state.exists())
        self.assertEqual((self.home / "hooks.json").read_bytes(), original)
        self.assertFalse((self.home / "config.toml").exists())

    def test_source_drift_is_rejected_before_target_mutation(self) -> None:
        before_hooks = b'{"description":"before","hooks":{}}'
        (self.home / "hooks.json").write_bytes(before_hooks)
        plan = self._plan()
        (self.source / "recorder.py").write_text("print('changed after plan')\n", encoding="utf-8")
        with self.assertRaises(installer.InstallerDrift):
            installer.apply_install(plan)
        self.assertEqual((self.home / "hooks.json").read_bytes(), before_hooks)
        self.assertFalse((self.state / "settings.json").exists())
        self.assertFalse(Path(plan.journal["target"]["install_root"]).exists())

    def test_verify_uses_the_immutable_install_after_canonical_source_advances(self) -> None:
        plan = self._plan(auth_token="9" * 64)
        installer.apply_install(plan)
        installed = Path(plan.journal["target"]["install_root"])
        installed_digest = installer._installed_tree_digest(installed)

        (self.source / "recorder.py").write_text(
            "print('new canonical release after successful apply')\n",
            encoding="utf-8",
        )

        result = installer.verify_install(plan)
        self.assertTrue(result["ok"])
        self.assertEqual(result["payload_sha256"], installed_digest)

    def test_target_drift_is_rejected_before_any_apply_mutation(self) -> None:
        (self.home / "hooks.json").write_text('{"hooks":{}}\n', encoding="utf-8")
        plan = self._plan()
        changed = b'{"hooks":{},"changed":true}\n'
        (self.home / "hooks.json").write_bytes(changed)
        with self.assertRaises(installer.InstallerDrift):
            installer.apply_install(plan)
        self.assertEqual((self.home / "hooks.json").read_bytes(), changed)
        self.assertFalse((self.home / "config.toml").exists())
        self.assertFalse((self.state / "settings.json").exists())

    def test_apply_replace_race_preserves_competing_existing_target(self) -> None:
        hooks_path = self.home / "hooks.json"
        hooks_path.write_bytes(b'{"hooks":{},"owner":"before"}\n')
        competing = b'{"hooks":{},"owner":"uncooperative-writer"}\n'
        plan = self._plan(auth_token="e" * 64)
        hooks_action = next(
            action for action in plan.journal["actions"] if action["kind"] == "hooks"
        )
        before_path = Path(hooks_action["before_path"])
        real_atomic_move_no_replace = installer._atomic_move_no_replace
        raced = {"value": False}

        def capture_after_competing_write(
            source: Path,
            destination: Path,
            *,
            anchor: object,
            mutation_guard: object = None,
        ) -> None:
            if (
                Path(source) == hooks_path
                and Path(destination) == before_path
                and not raced["value"]
            ):
                # The reviewed target was classified as its prior bytes. Model
                # an unrelated writer changing it at the capture syscall boundary.
                hooks_path.write_bytes(competing)
                raced["value"] = True
            real_atomic_move_no_replace(
                source,
                destination,
                anchor=anchor,
                mutation_guard=mutation_guard,
            )

        with mock.patch.object(
            installer,
            "_atomic_move_no_replace",
            side_effect=capture_after_competing_write,
        ):
            caught = None
            try:
                installer.apply_install(plan)
            except installer.InstallerError as error:
                caught = error

        persisted = json.loads(plan.journal_path.read_text(encoding="utf-8"))
        with self.subTest(invariant="race fixture reached exact target"):
            self.assertTrue(raced["value"])
        with self.subTest(invariant="competing bytes preserved"):
            self.assertEqual(hooks_path.read_bytes(), competing)
        with self.subTest(invariant="transaction rejected"):
            self.assertIsNotNone(caught)
        with self.subTest(invariant="earlier mutations rolled back"):
            self.assertFalse((self.state / "settings.json").exists())
            self.assertFalse(Path(plan.journal["target"]["install_root"]).exists())
        with self.subTest(invariant="safe state journaled"):
            self.assertEqual(persisted["status"], "apply-failed-rolled-back")

    def test_legacy_upgrade_rotates_port_instead_of_colliding_with_unretirable_receiver(self) -> None:
        previous_version = "0.1.1"
        old_port = 4319
        token = "7" * 64
        old_install = self.state / "installs" / previous_version
        self.state.mkdir(parents=True)
        previous_settings = {
            "schema_version": 1,
            "recorder_version": previous_version,
            "listen_host": "127.0.0.1",
            "listen_port": old_port,
            "auth_token": token,
            "install_root": str(old_install),
            "python_executable": str(Path(sys.executable).resolve()),
            "platform": installer._platform_info(),
        }
        previous_settings_bytes = installer._json_bytes(previous_settings)
        (self.state / "settings.json").write_bytes(previous_settings_bytes)
        old_handler = installer._hook_handler(Path(sys.executable).resolve(), old_install, self.state)
        second_home = self.root / "second legacy Codex home"
        second_home.mkdir()
        for home in (self.home, second_home):
            (home / "hooks.json").write_bytes(installer._render_hooks(b"", old_handler, None))
            (home / "config.toml").write_text(
                installer._managed_otel_block(old_port, token),
                encoding="utf-8",
            )
        prior_plan_id = "1" * 32
        prior_journal_path = self.state / "transactions" / prior_plan_id / "journal.json"
        prior_journal_path.parent.mkdir(parents=True)
        prior_journal_path.write_bytes(
            installer._json_bytes(
                {
                    "plan_id": prior_plan_id,
                    "status": "applied",
                    "updated_at_utc": "2026-07-28T00:00:00Z",
                    "managed_id": installer.MANAGED_ID,
                    "recorder_version": previous_version,
                    "journal_path": str(prior_journal_path),
                    "python_executable": str(Path(sys.executable).resolve()),
                    "target": {
                        "state_root": str(self.state),
                        "install_root": str(old_install),
                        "settings": {
                            "path": str(self.state / "settings.json"),
                            "after_sha256": installer._sha256(previous_settings_bytes),
                        },
                    },
                    "receiver": {
                        "listen_port": old_port,
                        "auth_token_sha256": installer._sha256(token.encode("ascii")),
                    },
                    "codex_homes": [
                        {"name": "codex-main", "home": str(self.home)},
                        {"name": "codex-second", "home": str(second_home)},
                    ],
                    "claude_homes": [],
                }
            )
        )

        with self.assertRaisesRegex(installer.InstallerConflict, "omits previously managed"):
            self._plan()

        claude_home = self.root / "new Claude home"
        claude_home.mkdir()
        homes = {"codex-main": self.home, "codex-second": second_home}
        with mock.patch.object(
            installer,
            "_probe_claude_runtime",
            return_value=(Path(sys.executable).resolve(), "2.1.220"),
        ):
            plan = installer.plan_install(
                self.source,
                self.state,
                homes,
                claude_homes={"claude-new": claude_home},
                python_executable=Path(sys.executable).resolve(),
                rotate_auth_token=True,
            )
            self.assertEqual(
                plan.journal["target"]["managed_targets"]["before_provenance"],
                "recovered-applied-transaction-history",
            )
            self.assertEqual(
                len(plan.journal["target"]["managed_targets"]["before_targets"]), 2
            )
            self.assertEqual(len(plan.journal["target"]["managed_targets"]["after"]), 3)
            self.assertNotEqual(plan.journal["receiver"]["listen_port"], old_port)
            self.assertEqual(
                plan.journal["receiver"]["listen_port_provenance"],
                "legacy-upgrade-port-rotation",
            )
            with self.assertRaises(installer.InstallerConflict):
                installer.plan_install(
                    self.source,
                    self.state,
                    homes,
                    claude_homes={"claude-new": claude_home},
                    python_executable=Path(sys.executable).resolve(),
                    rotate_auth_token=True,
                    listen_port=old_port,
                )
            installer.apply_install(plan)
            inventory = json.loads(
                (self.state / "managed-targets.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(inventory["targets"]), 3)
            installer.rollback_install(plan)
        self.assertFalse((self.state / "managed-targets.json").exists())

    def test_existing_settings_without_authoritative_target_history_fail_closed(self) -> None:
        self.state.mkdir(parents=True)
        settings = installer._settings_value(
            install_root=self.state / "installs" / installer.RECORDER_VERSION,
            state_root=self.state,
            python_executable=Path(sys.executable).resolve(),
            listen_port=4370,
            auth_token="7" * 64,
        )
        (self.state / "settings.json").write_bytes(installer._json_bytes(settings))
        with self.assertRaisesRegex(installer.InstallerConflict, "no authoritative"):
            self._plan()

    def test_source_and_target_symlinks_are_refused(self) -> None:
        link = self.source / "delivery_efficiency" / "linked.py"
        try:
            link.symlink_to(self.source / "recorder.py")
        except (OSError, NotImplementedError):
            self.skipTest("host cannot create test symlinks")
        with self.assertRaises(installer.InstallerConflict):
            self._plan()
        link.unlink()

        real = self.root / "outside-hooks.json"
        real.write_text('{"hooks":{}}\n', encoding="utf-8")
        (self.home / "hooks.json").symlink_to(real)
        with self.assertRaises(installer.InstallerConflict):
            self._plan()
        self.assertEqual(real.read_text(encoding="utf-8"), '{"hooks":{}}\n')
        self.assertFalse(self.state.exists())

    def test_apply_failure_rolls_back_every_applied_byte(self) -> None:
        hooks_before = b'{"description":"original","hooks":{}}\n'
        config_before = b'model = "kept"\n'
        (self.home / "hooks.json").write_bytes(hooks_before)
        (self.home / "config.toml").write_bytes(config_before)
        plan = self._plan(auth_token="b" * 64)
        with self.assertRaisesRegex(RuntimeError, "injected installer failure"):
            installer.apply_install(plan, fault_after=3)
        self.assertEqual((self.home / "hooks.json").read_bytes(), hooks_before)
        self.assertEqual((self.home / "config.toml").read_bytes(), config_before)
        self.assertFalse((self.state / "settings.json").exists())
        self.assertFalse((self.state / "recorder.py").exists())
        self.assertFalse(Path(plan.journal["target"]["install_root"]).exists())
        persisted = json.loads(plan.journal_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["status"], "apply-failed-rolled-back")

    def test_apply_mutation_guard_rejects_before_any_forward_mutation(self) -> None:
        hooks_before = b'{"description":"guarded original","hooks":{}}\n'
        config_before = b'model = "guarded-kept"\n'
        (self.home / "hooks.json").write_bytes(hooks_before)
        (self.home / "config.toml").write_bytes(config_before)
        plan = self._plan(auth_token="1" * 64)
        guard_calls = []

        def reject_before_applying() -> None:
            self.assertIsNotNone(plan.transaction_anchor)
            self.assertIsNotNone(plan.parent_anchors)
            guard_calls.append(plan.journal["status"])
            raise RuntimeError("deterministic pre-mutation guard rejection")

        with self.assertRaisesRegex(RuntimeError, "pre-mutation guard rejection"):
            installer.apply_install(
                plan,
                mutation_guard=reject_before_applying,
                require_planned=True,
            )

        self.assertEqual(guard_calls, ["planned"])
        self.assertEqual((self.home / "hooks.json").read_bytes(), hooks_before)
        self.assertEqual((self.home / "config.toml").read_bytes(), config_before)
        self.assertFalse((self.state / "settings.json").exists())
        self.assertFalse((self.state / "recorder.py").exists())
        self.assertFalse((self.state / "managed-targets.json").exists())
        self.assertFalse(Path(plan.journal["target"]["install_root"]).exists())
        persisted = json.loads(plan.journal_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["status"], "planned")

    def test_apply_guard_flip_during_staging_blocks_final_publication(self) -> None:
        plan = self._plan(auth_token="6" * 64)
        install_action = next(
            action
            for action in plan.journal["actions"]
            if action["kind"] == "install-tree"
        )
        stage_path = Path(install_action["stage_path"])
        install_root = Path(install_action["path"])
        real_prepare = installer._prepare_action_stage
        guard_live = {"value": True}
        flipped = {"value": False}
        rejected = {"value": False}

        def prepare_then_invalidate(
            active_plan: installer.InstallPlan,
            action: dict[str, object],
            *,
            source: object = None,
            data: object = None,
        ) -> None:
            real_prepare(active_plan, action, source=source, data=data)
            if action["kind"] == "install-tree" and not flipped["value"]:
                self.assertTrue(stage_path.is_dir())
                self.assertFalse(install_root.exists())
                flipped["value"] = True
                guard_live["value"] = False

        def require_live_guard() -> None:
            if guard_live["value"]:
                return
            self.assertTrue(stage_path.is_dir())
            self.assertFalse(install_root.exists())
            self.assertEqual(
                json.loads(plan.journal_path.read_text(encoding="utf-8"))["status"],
                "applying",
            )
            rejected["value"] = True
            raise RuntimeError("guard invalidated while staging absent target")

        with mock.patch.object(
            installer,
            "_prepare_action_stage",
            side_effect=prepare_then_invalidate,
        ):
            with self.assertRaisesRegex(RuntimeError, "staging absent target"):
                installer.apply_install(
                    plan,
                    mutation_guard=require_live_guard,
                    require_planned=True,
                )

        self.assertTrue(flipped["value"])
        self.assertTrue(rejected["value"])
        self.assertFalse(install_root.exists())
        self.assertEqual(installer._classify_action_path(stage_path, install_action), "after")
        self.assertFalse((self.state / "settings.json").exists())
        self.assertFalse((self.state / "recorder.py").exists())
        self.assertFalse((self.state / "managed-targets.json").exists())
        self.assertFalse((self.home / "hooks.json").exists())
        self.assertFalse((self.home / "config.toml").exists())
        persisted = json.loads(plan.journal_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["status"], "apply-failed-rolled-back")
        self.assertEqual(persisted["error"], "RuntimeError")

    def test_apply_guard_flip_during_staging_blocks_existing_target_capture(self) -> None:
        hooks_before = b'{"description":"staging race original","hooks":{}}\n'
        config_before = b'model = "staging-race-kept"\n'
        hooks_path = self.home / "hooks.json"
        config_path = self.home / "config.toml"
        hooks_path.write_bytes(hooks_before)
        config_path.write_bytes(config_before)
        hooks_mode = hooks_path.stat().st_mode & 0o777
        config_mode = config_path.stat().st_mode & 0o777
        plan = self._plan(auth_token="7" * 64)
        hooks_action = next(
            action for action in plan.journal["actions"] if action["kind"] == "hooks"
        )
        stage_path = Path(hooks_action["stage_path"])
        before_path = Path(hooks_action["before_path"])
        real_prepare = installer._prepare_action_stage
        guard_live = {"value": True}
        flipped = {"value": False}
        rejected = {"value": False}

        def prepare_then_invalidate(
            active_plan: installer.InstallPlan,
            action: dict[str, object],
            *,
            source: object = None,
            data: object = None,
        ) -> None:
            real_prepare(active_plan, action, source=source, data=data)
            if action["kind"] == "hooks" and not flipped["value"]:
                self.assertTrue(stage_path.is_file())
                self.assertEqual(hooks_path.read_bytes(), hooks_before)
                self.assertFalse(before_path.exists())
                flipped["value"] = True
                guard_live["value"] = False

        def require_live_guard() -> None:
            if guard_live["value"]:
                return
            self.assertTrue(stage_path.is_file())
            self.assertEqual(hooks_path.read_bytes(), hooks_before)
            self.assertFalse(before_path.exists())
            rejected["value"] = True
            raise RuntimeError("guard invalidated while staging existing target")

        with mock.patch.object(
            installer,
            "_prepare_action_stage",
            side_effect=prepare_then_invalidate,
        ):
            with self.assertRaisesRegex(RuntimeError, "staging existing target"):
                installer.apply_install(
                    plan,
                    mutation_guard=require_live_guard,
                    require_planned=True,
                )

        self.assertTrue(flipped["value"])
        self.assertTrue(rejected["value"])
        self.assertEqual(hooks_path.read_bytes(), hooks_before)
        self.assertEqual(config_path.read_bytes(), config_before)
        if os.name != "nt":
            self.assertEqual(hooks_path.stat().st_mode & 0o777, hooks_mode)
            self.assertEqual(config_path.stat().st_mode & 0o777, config_mode)
        self.assertEqual(installer._classify_action_path(stage_path, hooks_action), "after")
        self.assertFalse(before_path.exists())
        self.assertFalse((self.state / "settings.json").exists())
        self.assertFalse((self.state / "recorder.py").exists())
        self.assertFalse((self.state / "managed-targets.json").exists())
        self.assertFalse(Path(plan.journal["target"]["install_root"]).exists())
        persisted = json.loads(plan.journal_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["status"], "apply-failed-rolled-back")
        self.assertEqual(persisted["error"], "RuntimeError")

    def test_apply_mid_batch_mutation_guard_failure_rolls_back_exact_bytes(self) -> None:
        hooks_before = b'{"description":"mid-batch original","hooks":{}}\n'
        config_before = b'model = "mid-batch-kept"\n'
        (self.home / "hooks.json").write_bytes(hooks_before)
        (self.home / "config.toml").write_bytes(config_before)
        hooks_mode = (self.home / "hooks.json").stat().st_mode & 0o777
        config_mode = (self.home / "config.toml").stat().st_mode & 0o777
        plan = self._plan(auth_token="2" * 64)
        guard_calls = 0

        def fail_after_hooks_mutation() -> None:
            nonlocal guard_calls
            self.assertIsNotNone(plan.transaction_anchor)
            self.assertIsNotNone(plan.parent_anchors)
            guard_calls += 1
            if guard_calls == 11:
                persisted = json.loads(plan.journal_path.read_text(encoding="utf-8"))
                self.assertEqual(persisted["status"], "applying")
                self.assertNotEqual((self.home / "hooks.json").read_bytes(), hooks_before)
                self.assertEqual((self.home / "config.toml").read_bytes(), config_before)
                self.assertTrue((self.state / "settings.json").is_file())
                self.assertTrue(Path(plan.journal["target"]["install_root"]).is_dir())
                raise RuntimeError("deterministic mid-batch guard rejection")

        with self.assertRaisesRegex(RuntimeError, "mid-batch guard rejection"):
            installer.apply_install(
                plan,
                mutation_guard=fail_after_hooks_mutation,
                require_planned=True,
            )

        self.assertEqual(guard_calls, 11)
        self.assertEqual((self.home / "hooks.json").read_bytes(), hooks_before)
        self.assertEqual((self.home / "config.toml").read_bytes(), config_before)
        if os.name != "nt":
            self.assertEqual((self.home / "hooks.json").stat().st_mode & 0o777, hooks_mode)
            self.assertEqual((self.home / "config.toml").stat().st_mode & 0o777, config_mode)
        self.assertFalse((self.state / "settings.json").exists())
        self.assertFalse((self.state / "recorder.py").exists())
        self.assertFalse((self.state / "managed-targets.json").exists())
        self.assertFalse(Path(plan.journal["target"]["install_root"]).exists())
        persisted = json.loads(plan.journal_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["status"], "apply-failed-rolled-back")
        self.assertEqual(persisted["error"], "RuntimeError")

    def test_apply_require_planned_rejects_applied_before_reuse(self) -> None:
        plan = self._plan(auth_token="3" * 64)
        installer.apply_install(plan)
        installed_bytes = {
            path: path.read_bytes()
            for path in (
                self.state / "settings.json",
                self.state / "recorder.py",
                self.state / "managed-targets.json",
                self.home / "hooks.json",
                self.home / "config.toml",
            )
        }
        guard = mock.Mock()
        activation = installer._activate_receiver
        activation.reset_mock()

        with self.assertRaisesRegex(installer.InstallerConflict, "must be planned.*applied"):
            installer.apply_install(
                plan,
                mutation_guard=guard,
                require_planned=True,
            )

        guard.assert_not_called()
        activation.assert_not_called()
        for path, expected in installed_bytes.items():
            self.assertEqual(path.read_bytes(), expected)

    def test_apply_require_planned_rejects_applying_before_recovery(self) -> None:
        plan = self._plan(auth_token="4" * 64)
        installer._journal_update(plan, "applying", plan.journal["actions"], None)
        guard = mock.Mock()

        with mock.patch.object(installer, "_recover_interrupted_apply") as recover:
            with self.assertRaisesRegex(
                installer.InstallerConflict,
                "must be planned.*applying",
            ):
                installer.apply_install(
                    plan,
                    mutation_guard=guard,
                    require_planned=True,
                )

        guard.assert_not_called()
        recover.assert_not_called()
        persisted = json.loads(plan.journal_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["status"], "applying")
        self.assertFalse((self.state / "settings.json").exists())

    def test_apply_mutation_guard_boundaries_and_default_callers_are_compatible(self) -> None:
        plan = self._plan(auth_token="5" * 64)
        observed_statuses = []

        def observe_boundary() -> None:
            self.assertIsNotNone(plan.transaction_anchor)
            self.assertIsNotNone(plan.parent_anchors)
            observed_statuses.append(
                json.loads(plan.journal_path.read_text(encoding="utf-8"))["status"]
            )

        result = installer.apply_install(
            plan,
            mutation_guard=observe_boundary,
            require_planned=True,
        )
        changed_actions = [
            action for action in plan.journal["actions"] if action["changed"]
        ]
        namespace_boundaries = sum(
            1 + int(action["before_exists"]) for action in changed_actions
        )
        expected_guard_calls = 3 + len(changed_actions) + namespace_boundaries
        self.assertEqual(len(observed_statuses), expected_guard_calls)
        self.assertEqual(observed_statuses[0], "planned")
        self.assertEqual(
            observed_statuses[1:],
            ["applying"] * (expected_guard_calls - 1),
        )
        self.assertTrue(result["receiver_healthy"])

        installed_bytes = {
            path: path.read_bytes()
            for path in (
                self.state / "settings.json",
                self.state / "recorder.py",
                self.state / "managed-targets.json",
                self.home / "hooks.json",
                self.home / "config.toml",
            )
        }
        activation = installer._activate_receiver
        activation.reset_mock()
        reused = installer.apply_install(plan)
        self.assertTrue(reused["receiver_healthy"])
        activation.assert_called_once_with(self.state)
        for path, expected in installed_bytes.items():
            self.assertEqual(path.read_bytes(), expected)

    def test_post_publication_failure_reconciles_and_rolls_back_hooks(self) -> None:
        hooks_path = self.home / "hooks.json"
        config_path = self.home / "config.toml"
        plan = self._plan(auth_token="4" * 64)
        hooks_action = next(
            action for action in plan.journal["actions"] if action["kind"] == "hooks"
        )
        real_publish = installer._publish_prepared_stage_no_replace
        failed_after_hooks_publication = {"value": False}

        def fail_once_after_hooks_publication(
            active_plan: installer.InstallPlan,
            action: dict[str, object],
            anchor: object,
            *,
            mutation_guard: object = None,
        ) -> None:
            real_publish(
                active_plan,
                action,
                anchor,
                mutation_guard=mutation_guard,
            )
            if (
                action["kind"] == "hooks"
                and Path(str(action["path"])) == hooks_path
                and not failed_after_hooks_publication["value"]
            ):
                self.assertTrue(hooks_path.is_file())
                self.assertEqual(
                    installer._sha256(hooks_path.read_bytes()),
                    hooks_action["after_sha256"],
                )
                failed_after_hooks_publication["value"] = True
                raise OSError("deterministic post-publication failure")

        with mock.patch.object(
            installer,
            "_publish_prepared_stage_no_replace",
            side_effect=fail_once_after_hooks_publication,
        ):
            with self.assertRaisesRegex(OSError, "post-publication failure"):
                installer.apply_install(plan)

        self.assertTrue(failed_after_hooks_publication["value"])
        self.assertFalse(hooks_path.exists())
        self.assertFalse(config_path.exists())
        self.assertFalse((self.state / "settings.json").exists())
        self.assertFalse((self.state / "recorder.py").exists())
        self.assertFalse((self.state / "managed-targets.json").exists())
        self.assertFalse(Path(plan.journal["target"]["install_root"]).exists())
        self.assertEqual(list(self.home.glob(".hooks.json.*")), [])
        persisted = json.loads(plan.journal_path.read_text(encoding="utf-8"))
        hooks_actions = [
            action
            for action in persisted["actions"]
            if action["kind"] == "hooks" and action["name"] == "codex-main"
        ]
        self.assertEqual(len(hooks_actions), 1)
        self.assertIs(hooks_actions[0]["applied"], True)
        self.assertEqual(persisted["status"], "apply-failed-rolled-back")

    def test_receiver_activation_is_part_of_commit_and_failure_rolls_back(self) -> None:
        hooks_before = b'{"description":"activation rollback","hooks":{}}\n'
        config_before = b'model = "keep"\n'
        (self.home / "hooks.json").write_bytes(hooks_before)
        (self.home / "config.toml").write_bytes(config_before)
        hooks_mode = self.home.joinpath("hooks.json").stat().st_mode & 0o777
        config_mode = self.home.joinpath("config.toml").stat().st_mode & 0o777
        plan = self._plan(auth_token="8" * 64)

        def fail_while_applying(_state: Path) -> None:
            persisted = json.loads(plan.journal_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["status"], "applying")
            raise RuntimeError("deterministic receiver health failure")

        with mock.patch.object(
            installer, "_activate_receiver", side_effect=fail_while_applying
        ):
            with self.assertRaisesRegex(RuntimeError, "receiver health failure"):
                installer.apply_install(plan)

        self.assertEqual((self.home / "hooks.json").read_bytes(), hooks_before)
        self.assertEqual((self.home / "config.toml").read_bytes(), config_before)
        if os.name != "nt":
            self.assertEqual((self.home / "hooks.json").stat().st_mode & 0o777, hooks_mode)
            self.assertEqual((self.home / "config.toml").stat().st_mode & 0o777, config_mode)
        self.assertFalse((self.state / "settings.json").exists())
        self.assertFalse((self.state / "managed-targets.json").exists())
        self.assertFalse(Path(plan.journal["target"]["install_root"]).exists())
        persisted = json.loads(plan.journal_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["status"], "apply-failed-rolled-back")
        self.assertEqual(persisted["error"], "RuntimeError")

    def test_receiver_activation_succeeds_before_transaction_commits(self) -> None:
        plan = self._plan(auth_token="6" * 64)

        def healthy_while_applying(state: Path) -> None:
            self.assertEqual(state, self.state)
            persisted = json.loads(plan.journal_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["status"], "applying")

        with mock.patch.object(
            installer, "_activate_receiver", side_effect=healthy_while_applying
        ) as activate:
            result = installer.apply_install(plan)
        activate.assert_called_once_with(self.state)
        self.assertTrue(result["receiver_healthy"])
        self.assertEqual(result["status"], "applied")
        self.assertEqual(
            json.loads(plan.journal_path.read_text(encoding="utf-8"))["status"],
            "applied",
        )

    def test_receiver_activation_requires_authenticated_health(self) -> None:
        settings = {"recorder_version": installer.RECORDER_VERSION}
        with mock.patch(
            "delivery_efficiency.runtime.ensure_receiver", return_value=settings
        ) as ensure, mock.patch(
            "delivery_efficiency.runtime.receiver_is_healthy", return_value=True
        ) as healthy:
            self.real_activate_receiver(self.state)
        ensure.assert_called_once_with(self.state, timeout_seconds=10.0)
        healthy.assert_called_once_with(settings, timeout_seconds=1.0)

        with mock.patch(
            "delivery_efficiency.runtime.ensure_receiver", return_value=settings
        ), mock.patch(
            "delivery_efficiency.runtime.receiver_is_healthy", return_value=False
        ):
            with self.assertRaisesRegex(
                installer.InstallerVerificationError, "authenticated health"
            ):
                self.real_activate_receiver(self.state)

    def test_compatible_receiver_retires_and_rebinds_same_port_authenticated(self) -> None:
        state = self.root / "authenticated same-port state"
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("127.0.0.1", 0))
                port = int(probe.getsockname()[1])
        except PermissionError:
            self.skipTest("host policy denied loopback bind")
        token = "8" * 64
        current_settings = runtime.create_settings(
            state,
            listen_port=port,
            install_root=TOOL_ROOT,
            python_executable=Path(sys.executable).resolve(),
            platform_info=installer._platform_info(),
            auth_token=token,
        )
        previous_settings = dict(current_settings)
        previous_settings["recorder_version"] = "0.2.3"
        runtime._private_write(
            state / "settings.json", installer._json_bytes(previous_settings)
        )
        with mock.patch.object(server, "RECORDER_VERSION", "0.2.3"):
            previous_receiver = server.Receiver(state)

        def serve_previous() -> None:
            try:
                previous_receiver.serve_forever(poll_interval=0.05)
            finally:
                previous_receiver.server_close()

        thread = threading.Thread(target=serve_previous, daemon=True)
        thread.start()
        spawned_processes = []
        real_popen = runtime.subprocess.Popen

        def capture_spawn(*arguments: object, **keywords: object):
            process = real_popen(*arguments, **keywords)
            spawned_processes.append(process)
            return process

        try:
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline and not runtime.receiver_is_healthy(
                previous_settings, timeout_seconds=0.2
            ):
                time.sleep(0.02)
            self.assertTrue(runtime.receiver_is_healthy(previous_settings))

            runtime._private_write(
                state / "settings.json", installer._json_bytes(current_settings)
            )
            with mock.patch.object(
                runtime.subprocess, "Popen", side_effect=capture_spawn
            ):
                selected = runtime.ensure_receiver(state, timeout_seconds=5.0)
            self.assertEqual(selected, current_settings)
            self.assertTrue(runtime.receiver_is_healthy(current_settings))
            thread.join(timeout=3.0)
            self.assertFalse(thread.is_alive())
        finally:
            runtime.request_receiver_retirement(
                current_settings, timeout_seconds=0.5
            )
            runtime.request_receiver_retirement(
                previous_settings, timeout_seconds=0.5
            )
            if thread.is_alive():
                previous_receiver.shutdown()
                thread.join(timeout=3.0)
            for process in spawned_processes:
                try:
                    process.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=3.0)

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    pass
            except OSError:
                break
            time.sleep(0.02)
        else:
            self.fail("replacement receiver did not retire from the preserved port")

    def test_exact_rollback_and_rollback_drift_guard(self) -> None:
        hooks_before = b'{"description":"exact bytes","hooks":{}}\n'
        config_before = b'# preserve formatting\nmodel="x"\n'
        (self.home / "hooks.json").write_bytes(hooks_before)
        (self.home / "config.toml").write_bytes(config_before)
        config_mode_before = (self.home / "config.toml").stat().st_mode & 0o777
        plan = self._plan(auth_token="c" * 64)
        installer.apply_install(plan)
        installer.rollback_install(plan)
        self.assertEqual((self.home / "hooks.json").read_bytes(), hooks_before)
        self.assertEqual((self.home / "config.toml").read_bytes(), config_before)
        if os.name != "nt":
            self.assertEqual((self.home / "config.toml").stat().st_mode & 0o777, config_mode_before)
        self.assertFalse((self.state / "settings.json").exists())
        self.assertFalse(Path(plan.journal["target"]["install_root"]).exists())

        second = self._plan(auth_token="d" * 64)
        installer.apply_install(second)
        drifted = (self.home / "config.toml").read_bytes() + b"# user edit\n"
        (self.home / "config.toml").write_bytes(drifted)
        with self.assertRaises(installer.InstallerVerificationError):
            installer.rollback_install(second)
        self.assertEqual((self.home / "config.toml").read_bytes(), drifted)
        self.assertTrue((self.state / "settings.json").exists())
        self.assertTrue(Path(second.journal["target"]["install_root"]).exists())

    def test_rollback_absent_before_race_preserves_competing_target(self) -> None:
        plan = self._plan(auth_token="f" * 64)
        installer.apply_install(plan)
        inventory_path = self.state / "managed-targets.json"
        competing = b'{"owner":"uncooperative-writer"}\n'
        real_atomic_move_no_replace = installer._atomic_move_no_replace
        raced = {"value": False}

        def move_after_competing_write(
            source: Path,
            destination: Path,
            *,
            anchor: object,
            mutation_guard: object = None,
        ) -> None:
            if Path(source) == inventory_path and not raced["value"]:
                # `_atomic_remove_if_matches` has completed its final expected
                # digest check. Change the first reversed, absent-before target
                # immediately before it is atomically moved into quarantine.
                inventory_path.write_bytes(competing)
                raced["value"] = True
            real_atomic_move_no_replace(
                source,
                destination,
                anchor=anchor,
                mutation_guard=mutation_guard,
            )

        with mock.patch.object(
            installer,
            "_atomic_move_no_replace",
            side_effect=move_after_competing_write,
        ):
            caught = None
            try:
                installer.rollback_install(plan)
            except installer.InstallerError as error:
                caught = error

        preserved = inventory_path.read_bytes() if inventory_path.exists() else None
        persisted = json.loads(plan.journal_path.read_text(encoding="utf-8"))
        with self.subTest(invariant="race fixture reached exact target"):
            self.assertTrue(raced["value"])
        with self.subTest(invariant="competing bytes preserved"):
            self.assertEqual(preserved, competing)
        with self.subTest(invariant="transaction rejected"):
            self.assertIsNotNone(caught)
        with self.subTest(invariant="no earlier rollback mutation"):
            self.assertTrue((self.state / "settings.json").exists())
            self.assertTrue(Path(plan.journal["target"]["install_root"]).exists())
        with self.subTest(invariant="safe state journaled"):
            self.assertEqual(persisted["status"], "rollback-blocked")

    def test_late_rollback_conflict_journals_progress_and_retry_is_safe(self) -> None:
        plan = self._plan(auth_token="1" * 64)
        installer.apply_install(plan)
        hooks_path = self.home / "hooks.json"
        config_path = self.home / "config.toml"
        inventory_path = self.state / "managed-targets.json"
        managed_hooks = hooks_path.read_bytes()
        managed_hooks_mode = hooks_path.stat().st_mode & 0o777
        competing = b'{"hooks":{},"owner":"late-rollback-writer"}\n'
        real_atomic_move_no_replace = installer._atomic_move_no_replace
        raced = {"value": False}

        def move_after_late_competing_write(
            source: Path,
            destination: Path,
            *,
            anchor: object,
            mutation_guard: object = None,
        ) -> None:
            if Path(source) == hooks_path and not raced["value"]:
                # Inventory and config are earlier reverse actions. Race only
                # when rollback reaches hooks, after both already completed.
                self.assertFalse(inventory_path.exists())
                self.assertFalse(config_path.exists())
                hooks_path.write_bytes(competing)
                raced["value"] = True
            real_atomic_move_no_replace(
                source,
                destination,
                anchor=anchor,
                mutation_guard=mutation_guard,
            )

        first_error = None
        with mock.patch.object(
            installer,
            "_atomic_move_no_replace",
            side_effect=move_after_late_competing_write,
        ):
            try:
                installer.rollback_install(plan)
            except installer.InstallerError as error:
                first_error = error

        after_conflict = json.loads(plan.journal_path.read_text(encoding="utf-8"))
        conflict_actions = {action["kind"]: action for action in after_conflict["actions"]}
        preserved_artifact = self.root / "operator-preserved-hooks.json"
        if hooks_path.exists():
            hooks_path.replace(preserved_artifact)
        hooks_path.write_bytes(managed_hooks)
        if os.name != "nt":
            hooks_path.chmod(managed_hooks_mode)

        retry_error = None
        retry_result = None
        try:
            retry_result = installer.rollback_install(
                plan.journal_path,
                plan_digest=plan.plan_digest,
            )
        except installer.InstallerError as error:
            retry_error = error
        after_retry = json.loads(plan.journal_path.read_text(encoding="utf-8"))

        with self.subTest(invariant="late race reached after reverse progress"):
            self.assertTrue(raced["value"])
            self.assertIsNotNone(first_error)
        with self.subTest(invariant="competing bytes survived operator resolution"):
            self.assertEqual(preserved_artifact.read_bytes(), competing)
        with self.subTest(invariant="blocked rollback status persisted"):
            self.assertEqual(after_conflict["status"], "rollback-blocked")
        expected_conflict_states = {
            "managed-targets": "restored",
            "otel-config": "restored",
            "hooks": "blocked",
            "launcher": "pending",
            "settings": "pending",
            "install-tree": "pending",
        }
        for kind, expected_state in expected_conflict_states.items():
            with self.subTest(invariant="resumable action state", action=kind):
                self.assertEqual(
                    conflict_actions[kind].get("rollback_state"),
                    expected_state,
                )
        with self.subTest(invariant="retry completed from persisted progress"):
            self.assertIsNone(retry_error)
            self.assertIsNotNone(retry_result)
            if retry_result is not None:
                self.assertEqual(retry_result["status"], "rolled-back")
            self.assertEqual(after_retry["status"], "rolled-back")
        with self.subTest(invariant="retry removed only installer targets"):
            self.assertFalse(hooks_path.exists())
            self.assertFalse(config_path.exists())
            self.assertFalse(inventory_path.exists())
            self.assertFalse((self.state / "settings.json").exists())
            self.assertFalse((self.state / "recorder.py").exists())
            self.assertFalse(Path(plan.journal["target"]["install_root"]).exists())
            self.assertEqual(preserved_artifact.read_bytes(), competing)

    def test_rollback_crash_after_reverse_mutation_is_reconciled_on_retry(self) -> None:
        class SimulatedRollbackCrash(BaseException):
            pass

        plan = self._plan(auth_token="2" * 64)
        installer.apply_install(plan)
        hooks_path = self.home / "hooks.json"
        config_path = self.home / "config.toml"
        inventory_path = self.state / "managed-targets.json"
        config_action = next(
            action
            for action in plan.journal["actions"]
            if action["kind"] == "otel-config"
        )
        config_after = Path(config_action["after_path"])
        real_atomic_move_no_replace = installer._atomic_move_no_replace
        crashed = {"value": False}

        def crash_after_config_reverse_mutation(
            source: Path,
            destination: Path,
            *,
            anchor: object,
            mutation_guard: object = None,
        ) -> None:
            real_atomic_move_no_replace(
                source,
                destination,
                anchor=anchor,
                mutation_guard=mutation_guard,
            )
            if (
                Path(source) == config_path
                and Path(destination) == config_after
                and not crashed["value"]
            ):
                # The absent-before config has moved out of its target name,
                # but the rollback loop has not yet journaled that reverse action.
                self.assertFalse(inventory_path.exists())
                self.assertFalse(config_path.exists())
                self.assertTrue(hooks_path.exists())
                crashed["value"] = True
                raise SimulatedRollbackCrash()

        caught_crash = None
        with mock.patch.object(
            installer,
            "_atomic_move_no_replace",
            side_effect=crash_after_config_reverse_mutation,
        ):
            try:
                installer.rollback_install(plan)
            except SimulatedRollbackCrash as error:
                caught_crash = error

        after_crash = json.loads(plan.journal_path.read_text(encoding="utf-8"))
        crash_actions = {action["kind"]: action for action in after_crash["actions"]}
        retry_error = None
        retry_result = None
        try:
            retry_result = installer.rollback_install(
                plan.journal_path,
                plan_digest=plan.plan_digest,
            )
        except installer.InstallerError as error:
            retry_error = error
        after_retry = json.loads(plan.journal_path.read_text(encoding="utf-8"))

        with self.subTest(invariant="crash occurred after exact reverse mutation"):
            self.assertTrue(crashed["value"])
            self.assertIsNotNone(caught_crash)
            self.assertFalse(inventory_path.exists())
            self.assertFalse(config_path.exists())
        with self.subTest(invariant="last durable action progress is resumable"):
            self.assertEqual(after_crash["status"], "rolling-back")
        expected_crash_states = {
            "managed-targets": "restored",
            # Config moved immediately before the simulated crash, so its last
            # durable action state records the pre-mutation intent until resume
            # reclassifies the bound target/after slots.
            "otel-config": "capture-intent",
            "hooks": "pending",
        }
        for kind, expected_state in expected_crash_states.items():
            with self.subTest(invariant="durable pre-crash action state", action=kind):
                self.assertEqual(
                    crash_actions[kind].get("rollback_state"),
                    expected_state,
                )
        with self.subTest(invariant="retry reconciled unjournaled reverse mutation"):
            self.assertIsNone(retry_error)
            self.assertIsNotNone(retry_result)
            if retry_result is not None:
                self.assertEqual(retry_result["status"], "rolled-back")
            self.assertEqual(after_retry["status"], "rolled-back")
        with self.subTest(invariant="retry completed every remaining reverse action"):
            self.assertFalse(hooks_path.exists())
            self.assertFalse(config_path.exists())
            self.assertFalse(inventory_path.exists())
            self.assertFalse((self.state / "settings.json").exists())
            self.assertFalse((self.state / "recorder.py").exists())
            self.assertFalse(Path(plan.journal["target"]["install_root"]).exists())

    def test_rollback_crash_after_quarantine_move_resumes_from_capture_intent(self) -> None:
        class SimulatedQuarantineCrash(BaseException):
            pass

        plan = self._plan(auth_token="3" * 64)
        installer.apply_install(plan)
        action = next(
            item
            for item in plan.journal["actions"]
            if item["kind"] == "managed-targets"
        )
        target = Path(action["path"])
        after = Path(action["after_path"])
        real_atomic_move_no_replace = installer._atomic_move_no_replace
        crashed = {"value": False}

        def crash_after_quarantine_move(
            source: Path,
            destination: Path,
            *,
            anchor: object,
            mutation_guard: object = None,
        ) -> None:
            real_atomic_move_no_replace(
                source,
                destination,
                anchor=anchor,
                mutation_guard=mutation_guard,
            )
            if (
                Path(source) == target
                and Path(destination) == after
                and not crashed["value"]
            ):
                self.assertFalse(target.exists())
                self.assertEqual(installer._classify_action_path(after, action), "after")
                crashed["value"] = True
                raise SimulatedQuarantineCrash()

        caught = None
        with mock.patch.object(
            installer,
            "_atomic_move_no_replace",
            side_effect=crash_after_quarantine_move,
        ):
            try:
                installer.rollback_install(plan)
            except SimulatedQuarantineCrash as error:
                caught = error

        persisted = json.loads(plan.journal_path.read_text(encoding="utf-8"))
        persisted_action = next(
            item for item in persisted["actions"] if item["id"] == action["id"]
        )
        self.assertTrue(crashed["value"])
        self.assertIsNotNone(caught)
        self.assertEqual(persisted["status"], "rolling-back")
        self.assertEqual(persisted_action["rollback_state"], "capture-intent")
        self.assertFalse(target.exists())
        self.assertEqual(installer._classify_action_path(after, action), "after")

        result = installer.rollback_install(
            plan.journal_path,
            plan_digest=plan.plan_digest,
        )
        self.assertEqual(result["status"], "rolled-back")
        self.assertFalse(target.exists())
        self.assertEqual(installer._classify_action_path(after, action), "after")
        self.assertIn(
            str(after),
            {artifact["path"] for artifact in result["retained_artifacts"]},
        )
        self.assertEqual(
            json.loads(plan.journal_path.read_text(encoding="utf-8"))["status"],
            "rolled-back",
        )

    def test_rollback_retains_artifacts_and_detects_mutation_without_deleting_it(self) -> None:
        plan = self._plan(auth_token="5" * 64)
        installer.apply_install(plan)
        result = installer.rollback_install(plan)
        retained = result["retained_artifacts"]
        self.assertGreater(len(retained), 0)
        for artifact in retained:
            with self.subTest(action=artifact["action_id"], role=artifact["role"]):
                self.assertTrue(Path(artifact["path"]).exists())

        hooks_action = next(
            action for action in plan.journal["actions"] if action["kind"] == "hooks"
        )
        retained_hooks = Path(hooks_action["after_path"])
        self.assertIn(str(retained_hooks), {artifact["path"] for artifact in retained})
        mutation = b'preserved artifact changed by an external writer\n'
        retained_hooks.write_bytes(mutation)

        with self.assertRaisesRegex(
            installer.InstallerVerificationError,
            "retained transaction artifact changed",
        ):
            with installer._locked_operation_plan(
                plan,
                expected_plan_digest=None,
            ) as held_plan:
                with installer._held_target_parents(held_plan):
                    installer._retained_artifacts(
                        held_plan,
                        held_plan.journal["actions"],
                    )
        self.assertEqual(retained_hooks.read_bytes(), mutation)
        with self.assertRaises(installer.InstallerConflict):
            installer.rollback_install(plan)
        self.assertEqual(retained_hooks.read_bytes(), mutation)

    def test_review_bound_slot_collisions_fail_before_target_mutation(self) -> None:
        occupant = b'uncooperative slot occupant\n'
        for field in ("stage_path", "before_path", "after_path"):
            with self.subTest(slot=field):
                state = self.root / ("slot-state-" + field)
                home = self.root / ("slot-home-" + field)
                home.mkdir()
                plan = installer.plan_install(
                    self.source,
                    state,
                    {"codex-slot": home},
                    python_executable=Path(sys.executable).resolve(),
                    auth_token="6" * 64,
                )
                action = next(
                    item for item in plan.journal["actions"] if item["kind"] == "hooks"
                )
                slot = Path(action[field])
                slot.write_bytes(occupant)

                with self.assertRaisesRegex(
                    installer.InstallerConflict,
                    "transaction artifact is occupied",
                ):
                    installer.apply_install(plan)

                self.assertEqual(slot.read_bytes(), occupant)
                self.assertFalse((home / "hooks.json").exists())
                self.assertFalse((home / "config.toml").exists())
                self.assertFalse((state / "settings.json").exists())
                self.assertFalse((state / "recorder.py").exists())
                self.assertFalse((state / "managed-targets.json").exists())
                self.assertFalse(Path(plan.journal["target"]["install_root"]).exists())
                persisted = json.loads(plan.journal_path.read_text(encoding="utf-8"))
                self.assertEqual(persisted["status"], "planned")

    def test_persisted_action_topology_tampering_is_rejected(self) -> None:
        cases = (
            "injected",
            "missing",
            "reordered",
            "duplicated",
            "target-path",
            "slot-path",
            "parent-path",
            "parent-identity",
            "invalid-state",
        )
        for label in cases:
            with self.subTest(case=label):
                state = self.root / ("tamper-state-" + label)
                home = self.root / ("tamper-home-" + label)
                home.mkdir()
                plan = installer.plan_install(
                    self.source,
                    state,
                    {"codex-tamper": home},
                    python_executable=Path(sys.executable).resolve(),
                    auth_token="7" * 64,
                )
                document = json.loads(plan.journal_path.read_text(encoding="utf-8"))
                if label == "injected":
                    document["actions"].append(
                        json.loads(json.dumps(document["actions"][-1]))
                    )
                elif label == "missing":
                    document["actions"].pop()
                elif label == "reordered":
                    document["actions"][0], document["actions"][1] = (
                        document["actions"][1],
                        document["actions"][0],
                    )
                elif label == "duplicated":
                    document["actions"][1] = json.loads(
                        json.dumps(document["actions"][0])
                    )
                elif label == "target-path":
                    document["actions"][3]["path"] = str(home / "substituted.json")
                elif label == "slot-path":
                    document["actions"][3]["after_path"] = str(
                        home / ".substituted-after"
                    )
                elif label == "parent-path":
                    document["actions"][3]["parent_path"] = str(self.root)
                elif label == "parent-identity":
                    document["actions"][3]["parent_identity"]["inode"] += 1
                else:
                    document["actions"][0]["rollback_state"] = "forged-restored"
                plan.journal_path.write_bytes(installer._json_bytes(document))

                with self.assertRaises(installer.InstallerConflict):
                    installer.load_plan(plan.journal_path, plan.plan_digest)
                self.assertFalse((home / "hooks.json").exists())
                self.assertFalse((state / "settings.json").exists())
                self.assertFalse(Path(plan.journal["target"]["install_root"]).exists())

    def test_valid_mutable_state_tampering_is_reclassified_from_namespace(self) -> None:
        plan = self._plan(auth_token="8" * 64)
        installer.apply_install(plan)
        document = json.loads(plan.journal_path.read_text(encoding="utf-8"))
        document["status"] = "rolling-back"
        for action in document["actions"]:
            if action["changed"]:
                action["rollback_state"] = "restored"
                action["blocked_reason"] = None
        plan.journal_path.write_bytes(installer._json_bytes(document))

        result = installer.rollback_install(
            plan.journal_path,
            plan_digest=plan.plan_digest,
        )
        self.assertEqual(result["status"], "rolled-back")
        self.assertFalse((self.home / "hooks.json").exists())
        self.assertFalse((self.home / "config.toml").exists())
        self.assertFalse((self.state / "settings.json").exists())
        self.assertFalse((self.state / "recorder.py").exists())
        self.assertFalse((self.state / "managed-targets.json").exists())
        self.assertFalse(Path(plan.journal["target"]["install_root"]).exists())

    def test_immutable_plan_tampering_is_rejected_by_reviewed_digest(self) -> None:
        for forge_journal_digest in (False, True):
            with self.subTest(forge_journal_digest=forge_journal_digest):
                state = self.root / (
                    "immutable-tamper-state-{}".format(forge_journal_digest)
                )
                home = self.root / (
                    "immutable-tamper-home-{}".format(forge_journal_digest)
                )
                home.mkdir()
                plan = installer.plan_install(
                    self.source,
                    state,
                    {"codex-immutable": home},
                    python_executable=Path(sys.executable).resolve(),
                    auth_token="9" * 64,
                )
                immutable = json.loads(plan.plan_path.read_text(encoding="utf-8"))
                immutable["actions"][3]["path"] = str(home / "forged-hooks.json")
                tampered_bytes = installer._json_bytes(immutable)
                plan.plan_path.write_bytes(tampered_bytes)
                if forge_journal_digest:
                    journal = json.loads(
                        plan.journal_path.read_text(encoding="utf-8")
                    )
                    journal["plan_sha256"] = installer._sha256(tampered_bytes)
                    plan.journal_path.write_bytes(installer._json_bytes(journal))

                with self.assertRaises(installer.InstallerConflict):
                    installer.load_plan(plan.journal_path, plan.plan_digest)
                self.assertFalse((home / "hooks.json").exists())
                self.assertFalse((state / "settings.json").exists())

    def test_disk_loaded_operations_require_reviewed_plan_digest(self) -> None:
        plan = self._plan(auth_token="a" * 64)
        for operation in (
            installer.apply_install,
            installer.verify_install,
            installer.rollback_install,
        ):
            with self.subTest(operation=operation.__name__), self.assertRaisesRegex(
                installer.InstallerConflict,
                "reviewed plan digest",
            ):
                operation(plan.journal_path)
        self.assertFalse((self.home / "hooks.json").exists())
        self.assertFalse((self.state / "settings.json").exists())
        self.assertFalse(Path(plan.journal["target"]["install_root"]).exists())

    def test_target_parent_identity_swap_is_rejected_before_mutation(self) -> None:
        plan = self._plan(auth_token="b" * 64)
        original_home = self.home.with_name(self.home.name + "-reviewed")
        os.replace(self.home, original_home)
        self.home.mkdir()
        sentinel = self.home / "replacement-owner.txt"
        sentinel.write_bytes(b"replacement parent\n")

        with self.assertRaisesRegex(
            installer.InstallerConflict,
            "identity",
        ):
            installer.apply_install(plan)

        self.assertEqual(sentinel.read_bytes(), b"replacement parent\n")
        self.assertFalse((self.home / "hooks.json").exists())
        self.assertFalse((original_home / "hooks.json").exists())
        self.assertFalse((self.state / "settings.json").exists())
        self.assertFalse(Path(plan.journal["target"]["install_root"]).exists())

    def test_transaction_directory_clone_swap_is_rejected_before_mutation(self) -> None:
        plan = self._plan(auth_token="c" * 64)
        transaction = plan.journal_path.parent
        original_transaction = transaction.with_name(transaction.name + "-reviewed")
        os.replace(transaction, original_transaction)
        shutil.copytree(original_transaction, transaction)

        with self.assertRaisesRegex(
            installer.InstallerConflict,
            "transaction directory identity",
        ):
            installer.apply_install(
                plan.journal_path,
                plan_digest=plan.plan_digest,
            )

        self.assertFalse((self.home / "hooks.json").exists())
        self.assertFalse((self.state / "settings.json").exists())
        self.assertFalse(Path(plan.journal["target"]["install_root"]).exists())

    @unittest.skipIf(os.name == "nt", "POSIX dir_fd ABA fixture")
    def test_held_classification_ignores_parent_swap_then_restore_aba(self) -> None:
        plan = self._plan(auth_token="d" * 64)
        with installer._locked_operation_plan(
            plan,
            expected_plan_digest=None,
        ) as held_plan:
            with installer._held_target_parents(held_plan):
                prepared = installer._prepare_apply(held_plan)
                action = next(
                    item
                    for item in held_plan.journal["actions"]
                    if item["kind"] == "hooks"
                )
                hooks_after = prepared["homes"][0]["hooks_after"]
                original_home = self.home.with_name(self.home.name + "-aba-reviewed")
                real_require = installer._require_directory_anchor
                calls = {"home": 0, "swapped": False}

                def require_with_transient_swap(
                    anchor: object,
                    *,
                    require_path: bool = True,
                ) -> None:
                    if getattr(anchor, "path", None) != self.home:
                        real_require(anchor, require_path=require_path)
                        return
                    calls["home"] += 1
                    if calls["home"] == 2:
                        real_require(anchor, require_path=require_path)
                        os.replace(self.home, original_home)
                        self.home.mkdir()
                        fabricated = self.home / "hooks.json"
                        fabricated.write_bytes(hooks_after)
                        fabricated.chmod(action["after_mode"])
                        calls["swapped"] = True
                        return
                    if calls["swapped"]:
                        shutil.rmtree(self.home)
                        os.replace(original_home, self.home)
                        calls["swapped"] = False
                    real_require(anchor, require_path=require_path)

                try:
                    with mock.patch.object(
                        installer,
                        "_require_directory_anchor",
                        side_effect=require_with_transient_swap,
                    ):
                        state = installer._held_action_namespace(held_plan, action)
                finally:
                    if calls["swapped"]:
                        shutil.rmtree(self.home)
                        os.replace(original_home, self.home)
                self.assertGreaterEqual(calls["home"], 3)
                self.assertEqual(state["target"], "missing")
                self.assertFalse((self.home / "hooks.json").exists())

    @unittest.skipIf(os.name == "nt", "POSIX dir_fd syscall-boundary fixture")
    def test_posix_no_replace_stays_bound_to_held_parent_at_syscall_boundary(self) -> None:
        parent = self.root / "reviewed syscall parent"
        parent.mkdir()
        source = parent / "source-slot"
        destination = parent / "destination-slot"
        source.write_bytes(b"reviewed source\n")
        detached = parent.with_name(parent.name + "-detached")
        replacement_sentinel = b"replacement parent\n"
        real_rename = installer._posix_rename_with_flags
        swapped = {"value": False}

        def swap_parent_then_rename(
            source_path: Path,
            destination_path: Path,
            *,
            directory_descriptor: int,
            linux_flags: int,
            macos_flags: int,
        ) -> None:
            os.replace(parent, detached)
            parent.mkdir()
            (parent / "replacement-owner.txt").write_bytes(replacement_sentinel)
            swapped["value"] = True
            real_rename(
                source_path,
                destination_path,
                directory_descriptor=directory_descriptor,
                linux_flags=linux_flags,
                macos_flags=macos_flags,
            )

        identity = installer._directory_identity(parent, "fixture parent")
        with installer._lock_directory(
            parent,
            identity,
            lock_name=".fixture.lock",
        ) as anchor:
            with mock.patch.object(
                installer,
                "_posix_rename_with_flags",
                side_effect=swap_parent_then_rename,
            ):
                with self.assertRaisesRegex(
                    installer.InstallerConflict,
                    "directory identity",
                ):
                    installer._atomic_move_no_replace(
                        source,
                        destination,
                        anchor=anchor,
                    )

        self.assertTrue(swapped["value"])
        self.assertEqual(
            (parent / "replacement-owner.txt").read_bytes(),
            replacement_sentinel,
        )
        self.assertFalse((parent / "destination-slot").exists())
        self.assertFalse((detached / "source-slot").exists())
        self.assertEqual(
            (detached / "destination-slot").read_bytes(),
            b"reviewed source\n",
        )

    @unittest.skipIf(os.name == "nt", "POSIX detached-directory fixture")
    def test_transaction_detach_during_apply_rolls_back_through_held_fd(self) -> None:
        plan = self._plan(auth_token="e" * 64)
        transaction = plan.journal_path.parent
        detached = transaction.with_name(transaction.name + "-detached")
        replacement_sentinel = b"replacement transaction\n"
        install_root = Path(plan.journal["target"]["install_root"])
        real_move = installer._atomic_move_no_replace
        detached_once = {"value": False}

        def detach_after_first_publication(
            source: Path,
            destination: Path,
            *,
            anchor: object,
            mutation_guard: object = None,
        ) -> None:
            real_move(
                source,
                destination,
                anchor=anchor,
                mutation_guard=mutation_guard,
            )
            if destination == install_root and not detached_once["value"]:
                os.replace(transaction, detached)
                transaction.mkdir()
                (transaction / "replacement-owner.txt").write_bytes(
                    replacement_sentinel
                )
                detached_once["value"] = True

        with mock.patch.object(
            installer,
            "_atomic_move_no_replace",
            side_effect=detach_after_first_publication,
        ):
            with self.assertRaises(installer.InstallerConflict):
                installer.apply_install(plan)

        self.assertTrue(detached_once["value"])
        self.assertEqual(
            (transaction / "replacement-owner.txt").read_bytes(),
            replacement_sentinel,
        )
        persisted = json.loads(
            (detached / "journal.json").read_text(encoding="utf-8")
        )
        self.assertEqual(persisted["status"], "apply-failed-rolled-back")
        self.assertFalse(install_root.exists())
        self.assertFalse((self.state / "settings.json").exists())
        self.assertFalse((self.home / "hooks.json").exists())
        self.assertFalse(plan.allow_detached_transaction)

    @unittest.skipIf(os.name == "nt", "POSIX detached-directory fixture")
    def test_transaction_detach_during_explicit_rollback_finishes_without_success(self) -> None:
        plan = self._plan(auth_token="f" * 64)
        installer.apply_install(plan)
        transaction = plan.journal_path.parent
        detached = transaction.with_name(transaction.name + "-detached")
        replacement_sentinel = b"replacement transaction\n"
        first_target = self.state / "managed-targets.json"
        real_move = installer._atomic_move_no_replace
        detached_once = {"value": False}

        def detach_after_first_reverse_move(
            source: Path,
            destination: Path,
            *,
            anchor: object,
            mutation_guard: object = None,
        ) -> None:
            real_move(
                source,
                destination,
                anchor=anchor,
                mutation_guard=mutation_guard,
            )
            if source == first_target and not detached_once["value"]:
                os.replace(transaction, detached)
                transaction.mkdir()
                (transaction / "replacement-owner.txt").write_bytes(
                    replacement_sentinel
                )
                detached_once["value"] = True

        with mock.patch.object(
            installer,
            "_atomic_move_no_replace",
            side_effect=detach_after_first_reverse_move,
        ):
            with self.assertRaisesRegex(
                installer.InstallerConflict,
                "directory",
            ):
                installer.rollback_install(plan)

        self.assertTrue(detached_once["value"])
        self.assertEqual(
            (transaction / "replacement-owner.txt").read_bytes(),
            replacement_sentinel,
        )
        persisted = json.loads(
            (detached / "journal.json").read_text(encoding="utf-8")
        )
        self.assertEqual(persisted["status"], "rolled-back")
        self.assertFalse((self.state / "managed-targets.json").exists())
        self.assertFalse((self.state / "settings.json").exists())
        self.assertFalse((self.home / "hooks.json").exists())
        self.assertFalse(Path(plan.journal["target"]["install_root"]).exists())
        self.assertFalse(plan.allow_detached_transaction)

    @unittest.skipIf(os.name == "nt", "POSIX detached-directory fixture")
    def test_transaction_detach_during_interrupted_apply_recovery_resets_strict_mode(self) -> None:
        plan = self._plan(auth_token="1" * 64)
        installer.apply_install(plan)
        for action in plan.journal["actions"]:
            action["applied"] = False
        installer._journal_update(plan, "applying", plan.journal["actions"], None)

        transaction = plan.journal_path.parent
        detached = transaction.with_name(transaction.name + "-recovery-detached")
        replacement_sentinel = b"replacement recovery transaction\n"
        real_move = installer._atomic_move_no_replace
        detached_once = {"value": False}

        def detach_after_first_recovery_move(
            source: Path,
            destination: Path,
            *,
            anchor: object,
            mutation_guard: object = None,
        ) -> None:
            real_move(
                source,
                destination,
                anchor=anchor,
                mutation_guard=mutation_guard,
            )
            if not detached_once["value"]:
                os.replace(transaction, detached)
                transaction.mkdir()
                (transaction / "replacement-owner.txt").write_bytes(
                    replacement_sentinel
                )
                detached_once["value"] = True

        with mock.patch.object(
            installer,
            "_atomic_move_no_replace",
            side_effect=detach_after_first_recovery_move,
        ):
            with self.assertRaises(installer.InstallerConflict):
                installer.apply_install(plan)

        self.assertTrue(detached_once["value"])
        self.assertEqual(
            (transaction / "replacement-owner.txt").read_bytes(),
            replacement_sentinel,
        )
        persisted = json.loads(
            (detached / "journal.json").read_text(encoding="utf-8")
        )
        self.assertEqual(persisted["status"], "apply-failed-rolled-back")
        self.assertFalse(Path(plan.journal["target"]["install_root"]).exists())
        self.assertFalse((self.state / "settings.json").exists())
        self.assertFalse((self.home / "hooks.json").exists())
        self.assertFalse(plan.allow_detached_transaction)

    def test_windows_namespace_primitive_never_accesses_replacefile(self) -> None:
        class FakeMove:
            def __init__(self) -> None:
                self.argtypes = None
                self.restype = None
                self.calls: list[tuple[object, ...]] = []

            def __call__(self, *arguments: object) -> int:
                self.calls.append(arguments)
                return 1

        class FakeKernel32:
            def __init__(self) -> None:
                self.MoveFileExW = FakeMove()
                self.replacefile_accessed = False

            @property
            def ReplaceFileW(self) -> object:
                self.replacefile_accessed = True
                raise AssertionError("ReplaceFileW must not be accessed")

        kernel32 = FakeKernel32()
        source = Path(r"C:\fixture\stage")
        destination = Path(r"C:\fixture\target")
        with mock.patch.object(
            installer.ctypes,
            "WinDLL",
            return_value=kernel32,
            create=True,
        ), mock.patch.object(
            installer.ctypes,
            "set_last_error",
            create=True,
        ):
            installer._windows_move_no_replace(source, destination)

        self.assertEqual(
            kernel32.MoveFileExW.calls,
            [(str(source), str(destination), 0x00000008)],
        )
        self.assertFalse(kernel32.replacefile_accessed)
        self.assertFalse(hasattr(installer, "_windows_replace_preserving"))
        self.assertFalse(hasattr(installer, "_atomic_exchange_preserving"))

    def test_windows_private_file_opener_denies_delete_and_stage_binding_denies_write(self) -> None:
        class FakeCreate:
            def __init__(self) -> None:
                self.argtypes = None
                self.restype = None
                self.calls: list[tuple[object, ...]] = []

            def __call__(self, *arguments: object) -> int:
                self.calls.append(arguments)
                return 123

        class FakeKernel32:
            def __init__(self) -> None:
                self.CreateFileW = FakeCreate()

        kernel32 = FakeKernel32()
        path = Path(r"C:\fixture\journal.json")
        with mock.patch.object(
            installer.ctypes,
            "WinDLL",
            return_value=kernel32,
            create=True,
        ), mock.patch.object(
            installer.ctypes,
            "set_last_error",
            create=True,
        ):
            self.assertEqual(
                installer._open_windows_regular_file_handle(path),
                (123, 0),
            )
            self.assertEqual(
                installer._open_windows_regular_file_handle(
                    path,
                    allow_rename=True,
                ),
                (123, 0),
            )

        private_read = kernel32.CreateFileW.calls[0]
        held_stage = kernel32.CreateFileW.calls[1]
        self.assertEqual(private_read[2], 0x00000001 | 0x00000002)
        self.assertEqual(held_stage[2], 0x00000001)
        self.assertEqual(private_read[5], 0x00200000)
        self.assertEqual(held_stage[5], 0x00200000)
        self.assertEqual(int(held_stage[1]) & 0x00010000, 0x00010000)

    def test_windows_child_names_reject_alias_and_escape_syntax(self) -> None:
        self.assertEqual(installer._windows_child_name("safe-stage.json"), "safe-stage.json")
        for unsafe in (
            "",
            ".",
            "..",
            "nested\\child",
            "nested/child",
            "stream:name",
            "nul\x00suffix",
            "trailing.",
            "trailing ",
        ):
            with self.subTest(name=repr(unsafe)), self.assertRaises(
                installer.InstallerError
            ):
                installer._windows_child_name(unsafe)

    def test_orphan_empty_lock_marker_is_preserved_and_rejected(self) -> None:
        parent = self.root / "empty lock parent"
        parent.mkdir()
        lock_path = parent / ".empty.lock"
        lock_path.write_bytes(b"")
        identity = installer._filesystem_identity(lock_path.lstat())
        if os.name == "nt":
            with self.assertRaises(installer.InstallerConflict):
                installer._open_windows_lock_stream(lock_path, _empty_retries=0)
        else:
            anchor = installer._DirectoryAnchor(
                parent,
                installer._directory_identity(parent, "empty-lock fixture"),
            )
            anchor.descriptor = os.open(str(parent), os.O_RDONLY)
            try:
                with self.assertRaises(installer.InstallerConflict):
                    installer._open_anchor_lock_stream(
                        anchor,
                        lock_path.name,
                        _empty_retries=0,
                    )
            finally:
                os.close(anchor.descriptor)
        self.assertEqual(lock_path.read_bytes(), b"")
        self.assertEqual(
            installer._filesystem_identity(lock_path.lstat())["inode"],
            identity["inode"],
        )

    def test_first_lock_creation_race_serializes_without_false_conflict(self) -> None:
        parent = self.root / "first lock race parent"
        parent.mkdir()
        creator_ready = self.root / "creator-made-empty-lock"
        creator_release = self.root / "release-creator"
        creator_result = self.root / "creator-result"
        contender_started = self.root / "contender-started"
        contender_result = self.root / "contender-result"
        creator_script = "\n".join(
            (
                "import os, sys, time",
                "from pathlib import Path",
                "sys.path.insert(0, sys.argv[1])",
                "from delivery_efficiency import installer",
                "parent = Path(sys.argv[2])",
                "ready = Path(sys.argv[3])",
                "release = Path(sys.argv[4])",
                "result = Path(sys.argv[5])",
                "if os.name == 'nt':",
                "    real_open = installer._open_windows_lock_handle",
                "    def delayed_open(path, disposition):",
                "        opened = real_open(path, disposition)",
                "        if disposition == 1 and opened[0] is not None:",
                "            ready.write_text('ready', encoding='utf-8')",
                "            while not release.exists(): time.sleep(0.01)",
                "        return opened",
                "    installer._open_windows_lock_handle = delayed_open",
                "else:",
                "    real_open = installer.os.open",
                "    def delayed_open(path, flags, *args, **kwargs):",
                "        descriptor = real_open(path, flags, *args, **kwargs)",
                "        if str(path) == '.first.lock' and flags & os.O_EXCL:",
                "            ready.write_text('ready', encoding='utf-8')",
                "            while not release.exists(): time.sleep(0.01)",
                "        return descriptor",
                "    installer.os.open = delayed_open",
                "identity = installer._directory_identity(parent, 'first-lock fixture')",
                "with installer._lock_directory(parent, identity, lock_name='.first.lock'):",
                "    result.write_text('creator', encoding='utf-8')",
            )
        )
        contender_script = "\n".join(
            (
                "import os, sys",
                "from pathlib import Path",
                "sys.path.insert(0, sys.argv[1])",
                "from delivery_efficiency import installer",
                "parent = Path(sys.argv[2])",
                "opened = Path(sys.argv[3])",
                "if os.name == 'nt':",
                "    real_open = installer._open_windows_lock_handle",
                "    def observed_open(path, disposition):",
                "        result = real_open(path, disposition)",
                "        if disposition == 3 and result[0] is not None:",
                "            opened.write_text('opened', encoding='utf-8')",
                "        return result",
                "    installer._open_windows_lock_handle = observed_open",
                "else:",
                "    real_open = installer.os.open",
                "    def observed_open(path, flags, *args, **kwargs):",
                "        descriptor = real_open(path, flags, *args, **kwargs)",
                "        if str(path) == '.first.lock' and not flags & os.O_EXCL:",
                "            opened.write_text('opened', encoding='utf-8')",
                "        return descriptor",
                "    installer.os.open = observed_open",
                "identity = installer._directory_identity(parent, 'first-lock fixture')",
                "with installer._lock_directory(parent, identity, lock_name='.first.lock'):",
                "    Path(sys.argv[4]).write_text('contender', encoding='utf-8')",
            )
        )
        creator = subprocess.Popen(
            [
                str(Path(sys.executable).resolve()),
                "-c",
                creator_script,
                str(TOOL_ROOT),
                str(parent),
                str(creator_ready),
                str(creator_release),
                str(creator_result),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        contender = None
        try:
            deadline = time.monotonic() + 10
            while (
                not creator_ready.exists()
                and creator.poll() is None
                and time.monotonic() < deadline
            ):
                time.sleep(0.01)
            self.assertTrue(creator_ready.exists())
            contender = subprocess.Popen(
                [
                    str(Path(sys.executable).resolve()),
                    "-c",
                    contender_script,
                    str(TOOL_ROOT),
                    str(parent),
                    str(contender_started),
                    str(contender_result),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            deadline = time.monotonic() + 10
            while (
                not contender_started.exists()
                and contender.poll() is None
                and time.monotonic() < deadline
            ):
                time.sleep(0.01)
            self.assertTrue(contender_started.exists())
            with self.assertRaises(subprocess.TimeoutExpired):
                contender.wait(timeout=0.2)
            self.assertFalse(contender_result.exists())
            creator_release.write_text("release", encoding="utf-8")
            contender_stdout, contender_stderr = contender.communicate(timeout=10)
            creator_stdout, creator_stderr = creator.communicate(timeout=10)
            self.assertEqual(contender.returncode, 0, contender_stdout + contender_stderr)
            self.assertTrue(contender_started.exists())
            self.assertEqual(contender_result.read_text(encoding="utf-8"), "contender")
            self.assertEqual(creator.returncode, 0, creator_stdout + creator_stderr)
            self.assertEqual(creator_result.read_text(encoding="utf-8"), "creator")
            self.assertEqual((parent / ".first.lock").read_bytes(), installer._LOCK_MARKER)
        finally:
            if not creator_release.exists():
                creator_release.write_text("release", encoding="utf-8")
            self._stop_test_process(contender)
            self._stop_test_process(creator)

    @unittest.skipUnless(os.name == "nt", "native Windows handle fixture")
    def test_windows_nt_child_creation_and_handle_rename_cover_nested_tree_and_file(self) -> None:
        parent = self.root / "native handle parent"
        parent.mkdir()
        parent_handle = installer._open_windows_directory_handle(
            parent,
            installer._directory_identity(parent, "native fixture parent"),
            allow_child_file_create=True,
            allow_child_directory_create=True,
            allow_child_traverse=True,
        )
        open_handles: list[int] = [parent_handle]
        try:
            stage = parent / "tree-stage"
            tree_handle = installer._create_windows_directory_handle(
                parent_handle,
                stage.name,
                stage,
            )
            open_handles.append(tree_handle)
            tree_identity = installer._windows_directory_handle_identity(tree_handle)
            level_one = stage / "level-one"
            level_one_handle = installer._create_windows_directory_handle(
                tree_handle,
                level_one.name,
                level_one,
            )
            open_handles.append(level_one_handle)
            level_two = level_one / "level-two"
            level_two_handle = installer._create_windows_directory_handle(
                level_one_handle,
                level_two.name,
                level_two,
            )
            open_handles.append(level_two_handle)
            root_file = stage / "root.txt"
            root_file_handle = installer._create_windows_file_handle(
                tree_handle,
                root_file.name,
                root_file,
            )
            installer._close_windows_handle(root_file_handle)
            nested_file = level_two / "nested.txt"
            nested_file_handle = installer._create_windows_file_handle(
                level_two_handle,
                nested_file.name,
                nested_file,
            )
            installer._close_windows_handle(nested_file_handle)

            installer._close_windows_handle(level_two_handle)
            open_handles.remove(level_two_handle)
            installer._close_windows_handle(level_one_handle)
            open_handles.remove(level_one_handle)
            installed_tree = parent / "tree-target"
            installed_tree.mkdir()
            tree_sentinel = installed_tree / "owner.txt"
            tree_sentinel.write_bytes(b"tree occupant\n")
            occupied_tree_identity = installer._filesystem_identity(installed_tree.lstat())
            with self.assertRaises(OSError):
                installer._windows_rename_handle_no_replace(
                    tree_handle,
                    parent_handle,
                    installed_tree.name,
                )
            self.assertEqual(tree_sentinel.read_bytes(), b"tree occupant\n")
            self.assertEqual(
                installer._filesystem_identity(installed_tree.lstat())["inode"],
                occupied_tree_identity["inode"],
            )
            self.assertEqual(
                installer._filesystem_identity(stage.lstat())["inode"],
                tree_identity["inode"],
            )
            shutil.rmtree(installed_tree)
            installer._windows_rename_handle_no_replace(
                tree_handle,
                parent_handle,
                installed_tree.name,
            )
            installed_identity = installer._filesystem_identity(installed_tree.lstat())
            self.assertEqual(installed_identity["device"], tree_identity["device"])
            self.assertEqual(installed_identity["inode"], tree_identity["inode"])
            self.assertTrue((installed_tree / "root.txt").is_file())
            self.assertTrue(
                (installed_tree / "level-one" / "level-two" / "nested.txt").is_file()
            )
            with self.assertRaises(OSError):
                os.replace(installed_tree, parent / "tree-held-move")
            installer._close_windows_handle(tree_handle)
            open_handles.remove(tree_handle)
            moved_tree = parent / "tree-after-release"
            os.replace(installed_tree, moved_tree)
            os.replace(moved_tree, installed_tree)

            collision = parent / "occupied-child"
            collision.mkdir()
            with self.assertRaises(FileExistsError):
                installer._create_windows_directory_handle(
                    parent_handle,
                    collision.name,
                    collision,
                )

            file_stage = parent / "file-stage"
            file_handle = installer._create_windows_file_handle(
                parent_handle,
                file_stage.name,
                file_stage,
            )
            open_handles.append(file_handle)
            file_identity = installer._windows_directory_handle_identity(file_handle)
            file_target = parent / "file-target"
            file_target.write_bytes(b"file occupant\n")
            occupied_file_identity = installer._filesystem_identity(file_target.lstat())
            with self.assertRaises(OSError):
                installer._windows_rename_handle_no_replace(
                    file_handle,
                    parent_handle,
                    file_target.name,
                )
            self.assertEqual(file_target.read_bytes(), b"file occupant\n")
            self.assertEqual(
                installer._filesystem_identity(file_target.lstat())["inode"],
                occupied_file_identity["inode"],
            )
            self.assertEqual(
                installer._filesystem_identity(file_stage.lstat())["inode"],
                file_identity["inode"],
            )
            file_target.unlink()
            installer._windows_rename_handle_no_replace(
                file_handle,
                parent_handle,
                file_target.name,
            )
            target_identity = installer._filesystem_identity(file_target.lstat())
            self.assertEqual(target_identity["device"], file_identity["device"])
            self.assertEqual(target_identity["inode"], file_identity["inode"])
            with self.assertRaises(OSError):
                os.replace(file_target, parent / "file-held-move")
            installer._close_windows_handle(file_handle)
            open_handles.remove(file_handle)
            moved_file = parent / "file-after-release"
            os.replace(file_target, moved_file)
            os.replace(moved_file, file_target)

            move_source = parent / "move-source"
            move_target = parent / "move-target"
            move_source.write_bytes(b"move source\n")
            move_target.write_bytes(b"move target\n")
            source_identity = installer._filesystem_identity(move_source.lstat())
            move_target_identity = installer._filesystem_identity(move_target.lstat())
            anchor = installer._DirectoryAnchor(
                parent,
                installer._directory_identity(parent, "native move parent"),
            )
            anchor.windows_directory_handle = parent_handle
            with self.assertRaises(installer.InstallerDrift):
                installer._atomic_move_no_replace(
                    move_source,
                    move_target,
                    anchor=anchor,
                )
            self.assertEqual(move_source.read_bytes(), b"move source\n")
            self.assertEqual(move_target.read_bytes(), b"move target\n")
            self.assertEqual(
                installer._filesystem_identity(move_source.lstat())["inode"],
                source_identity["inode"],
            )
            self.assertEqual(
                installer._filesystem_identity(move_target.lstat())["inode"],
                move_target_identity["inode"],
            )
            move_target.unlink()
            installer._atomic_move_no_replace(
                move_source,
                move_target,
                anchor=anchor,
            )
            self.assertFalse(move_source.exists())
            self.assertEqual(move_target.read_bytes(), b"move source\n")
            self.assertEqual(
                installer._filesystem_identity(move_target.lstat())["inode"],
                source_identity["inode"],
            )
        finally:
            for handle in reversed(open_handles):
                installer._close_windows_handle(handle)

    @unittest.skipUnless(os.name == "nt", "native Windows handle fixture")
    def test_windows_apply_holds_exact_file_and_directory_stages_through_publication(self) -> None:
        nested = self.source / "delivery_efficiency" / "nested" / "deeper"
        nested.mkdir(parents=True)
        (nested / "payload.py").write_text("VALUE = 1\n", encoding="utf-8")
        plan = self._plan(auth_token="2" * 64)
        real_publish = installer._publish_windows_stage_no_replace
        published: dict[str, int] = {}

        def publish_with_competing_swap(
            active_plan: installer.InstallPlan,
            action: dict[str, object],
            anchor: object,
            *,
            mutation_guard: object = None,
        ) -> None:
            stage = Path(str(action["stage_path"]))
            target = Path(str(action["path"]))
            binding = active_plan.windows_stage_bindings[
                installer._normalized_path_text(stage)
            ]
            captured = dict(binding["identity"])
            with self.assertRaises(OSError):
                os.replace(stage, stage.with_name(stage.name + "-competitor"))
            if action["kind"] != "install-tree":
                with self.assertRaises(OSError):
                    with stage.open("r+b"):
                        pass
            real_publish(
                active_plan,
                action,
                anchor,
                mutation_guard=mutation_guard,
            )
            current = installer._filesystem_identity(target.lstat())
            self.assertEqual(current["device"], captured["device"])
            self.assertEqual(current["inode"], captured["inode"])
            published[str(action["kind"])] = published.get(str(action["kind"]), 0) + 1

        with mock.patch.object(
            installer,
            "_publish_windows_stage_no_replace",
            side_effect=publish_with_competing_swap,
        ):
            result = installer.apply_install(plan)

        self.assertTrue(result["ok"])
        self.assertGreaterEqual(published.get("install-tree", 0), 1)
        self.assertGreaterEqual(published.get("hooks", 0), 1)
        self.assertGreaterEqual(published.get("otel-config", 0), 1)
        hooks = self.home / "hooks.json"
        with hooks.open("r+b"):
            pass
        moved = self.home / "hooks.after-release"
        os.replace(hooks, moved)
        os.replace(moved, hooks)
        self.assertTrue(
            Path(plan.journal["target"]["install_root"])
            .joinpath("delivery_efficiency", "nested", "deeper", "payload.py")
            .is_file()
        )

    @unittest.skipUnless(os.name == "nt", "native Windows sharing fixture")
    def test_windows_held_parent_ancestor_and_lock_names_cannot_be_renamed(self) -> None:
        ancestor = self.root / "held ancestor"
        parent = ancestor / "held parent"
        parent.mkdir(parents=True)
        identity = installer._directory_identity(parent, "held parent")
        with installer._lock_directory(
            parent,
            identity,
            lock_name=".fixture.lock",
            allow_child_file_create=True,
            allow_child_traverse=True,
        ):
            lock_path = parent / ".fixture.lock"
            for source, destination in (
                (lock_path, parent / ".fixture.lock-moved"),
                (parent, ancestor / "held parent-moved"),
                (ancestor, self.root / "held ancestor-moved"),
            ):
                with self.subTest(source=source), self.assertRaises(OSError):
                    os.replace(source, destination)

        lock_moved = parent / ".fixture.lock-after-release"
        os.replace(parent / ".fixture.lock", lock_moved)
        os.replace(lock_moved, parent / ".fixture.lock")
        parent_moved = ancestor / "held parent-after-release"
        os.replace(parent, parent_moved)
        os.replace(parent_moved, parent)
        ancestor_moved = self.root / "held ancestor-after-release"
        os.replace(ancestor, ancestor_moved)
        os.replace(ancestor_moved, ancestor)

    @unittest.skipUnless(os.name == "nt", "native Windows reparse fixture")
    def test_windows_lock_and_transaction_child_reparse_points_are_refused(self) -> None:
        probe_target = self.root / "symlink-probe-target"
        probe_link = self.root / "symlink-probe-link"
        probe_target.write_bytes(b"probe\n")
        try:
            probe_link.symlink_to(probe_target)
        except (OSError, NotImplementedError):
            self.skipTest("Windows account cannot create test symlinks")
        probe_link.unlink()

        lock_parent = self.root / "lock reparse parent"
        lock_parent.mkdir()
        lock_path = lock_parent / ".race.lock"
        lock_path.write_bytes(installer._LOCK_MARKER)
        moved_lock = lock_parent / ".race.lock-real"
        real_open = installer._open_windows_lock_handle
        raced = {"value": False}

        def replace_lock_with_reparse(
            path: Path,
            disposition: int,
        ) -> object:
            if disposition == 3 and not raced["value"]:
                os.replace(lock_path, moved_lock)
                lock_path.symlink_to(moved_lock.name)
                raced["value"] = True
            return real_open(path, disposition)

        with mock.patch.object(
            installer,
            "_open_windows_lock_handle",
            side_effect=replace_lock_with_reparse,
        ):
            with self.assertRaises(installer.InstallerConflict):
                installer._open_windows_lock_stream(lock_path)
        self.assertTrue(raced["value"])
        self.assertEqual(moved_lock.read_bytes(), installer._LOCK_MARKER)

        plan = self._plan(auth_token="3" * 64)
        original_plan = plan.plan_path.with_name("plan-real.json")
        os.replace(plan.plan_path, original_plan)
        plan.plan_path.symlink_to(original_plan.name)
        with self.assertRaises(installer.InstallerConflict):
            installer.load_plan(plan.journal_path, plan.plan_digest)
        self.assertEqual(
            installer._sha256(original_plan.read_bytes()),
            plan.plan_digest,
        )

    @unittest.skipUnless(os.name == "nt", "native Windows recovery fixture")
    def test_windows_source_slot_reoccupation_releases_target_and_retains_both(self) -> None:
        plan = self._plan(auth_token="4" * 64)
        hooks_action = next(
            action for action in plan.journal["actions"] if action["kind"] == "hooks"
        )
        hooks_stage = Path(hooks_action["stage_path"])
        hooks_target = Path(hooks_action["path"])
        foreign = b"foreign source-slot occupant\n"
        real_rename = installer._windows_rename_handle_no_replace
        injected = {"value": False}

        def rename_then_reoccupy(
            handle: int,
            parent_handle: int,
            destination_name: str,
        ) -> None:
            real_rename(handle, parent_handle, destination_name)
            if destination_name == hooks_target.name and not injected["value"]:
                hooks_stage.write_bytes(foreign)
                injected["value"] = True

        with mock.patch.object(
            installer,
            "_windows_rename_handle_no_replace",
            side_effect=rename_then_reoccupy,
        ):
            with self.assertRaisesRegex(
                installer.InstallerError,
                "rollback was blocked",
            ):
                installer.apply_install(plan)

        self.assertTrue(injected["value"])
        self.assertEqual(hooks_stage.read_bytes(), foreign)
        self.assertEqual(
            installer._sha256(hooks_target.read_bytes()),
            hooks_action["after_sha256"],
        )
        moved = hooks_target.with_name("hooks.safe-held-target")
        os.replace(hooks_target, moved)
        os.replace(moved, hooks_target)
        persisted = json.loads(plan.journal_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["status"], "apply-failed-rollback-blocked")

    @unittest.skipUnless(os.name == "nt", "native Windows process-lock fixture")
    def test_windows_transaction_lock_serializes_conforming_processes(self) -> None:
        plan = self._plan(auth_token="5" * 64)
        marker = self.root / "second-process-loaded"
        script = (
            "import sys; from pathlib import Path; "
            "sys.path.insert(0, sys.argv[4]); "
            "from delivery_efficiency import installer; "
            "installer.load_plan(Path(sys.argv[1]), sys.argv[2]); "
            "Path(sys.argv[3]).write_text('loaded', encoding='utf-8')"
        )
        command = [
            str(Path(sys.executable).resolve()),
            "-c",
            script,
            str(plan.journal_path),
            str(plan.plan_digest),
            str(marker),
            str(TOOL_ROOT),
        ]
        process = None
        try:
            with installer._lock_transaction_directory(
                plan.journal_path.parent,
                plan.journal["transaction_identity"],
            ):
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                with self.assertRaises(subprocess.TimeoutExpired):
                    process.wait(timeout=0.5)
                self.assertFalse(marker.exists())
            assert process is not None
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, stdout + stderr)
            self.assertEqual(marker.read_text(encoding="utf-8"), "loaded")
        finally:
            self._stop_test_process(process)

    def test_explicit_codex_retirement_preserves_unrelated_configuration(self) -> None:
        unrelated_hooks = {
            "description": "keep",
            "hooks": {
                "PreToolUse": [
                    {"hooks": [{"type": "command", "command": "user-owned"}]}
                ]
            },
        }
        (self.home / "hooks.json").write_text(json.dumps(unrelated_hooks), encoding="utf-8")
        (self.home / "config.toml").write_text('model = "kept"\n', encoding="utf-8")
        first = self._plan(auth_token="0" * 64, listen_port=4374)
        installer.apply_install(first)
        hooks_before_retirement = (self.home / "hooks.json").read_bytes()
        config_before_retirement = (self.home / "config.toml").read_bytes()
        inventory_before_retirement = (self.state / "managed-targets.json").read_bytes()

        retirement = installer.plan_install(
            self.source,
            self.state,
            {},
            retire_codex_homes={"codex-main": self.home},
            python_executable=Path(sys.executable).resolve(),
        )
        result = installer.apply_install(retirement)
        self.assertEqual(result["retired_codex_homes"], ["codex-main"])
        self.assertEqual(result["managed_target_count"], 0)
        retired_hooks = json.loads((self.home / "hooks.json").read_text(encoding="utf-8"))
        self.assertEqual(retired_hooks["description"], "keep")
        self.assertEqual(retired_hooks["hooks"]["PreToolUse"][0], unrelated_hooks["hooks"]["PreToolUse"][0])
        self.assertNotIn(installer.MANAGED_ID, (self.home / "hooks.json").read_text(encoding="utf-8"))
        retired_config = (self.home / "config.toml").read_text(encoding="utf-8")
        self.assertIn('model = "kept"', retired_config)
        self.assertNotIn(installer.MANAGED_BEGIN, retired_config)

        installer.rollback_install(retirement)
        self.assertEqual((self.home / "hooks.json").read_bytes(), hooks_before_retirement)
        self.assertEqual((self.home / "config.toml").read_bytes(), config_before_retirement)
        self.assertEqual(
            (self.state / "managed-targets.json").read_bytes(),
            inventory_before_retirement,
        )

    def test_posix_and_windows_commands_quote_spaces_and_metacharacters(self) -> None:
        arguments = [
            "/Users/name & team's %/python",
            "/Users/name & team's %/recorder.py",
            "hook",
            "codex",
            "--state-dir",
            "/tmp/state & 'quoted' %!()",
            "--managed-id",
            installer.MANAGED_ID,
        ]
        posix = installer.build_posix_hook_command(arguments)
        self.assertEqual(shlex.split(posix), arguments)

        windows = installer.build_windows_hook_command(arguments)
        encoded = windows.rsplit(" ", 1)[1]
        decoded = base64.b64decode(encoded).decode("utf-16le")
        self.assertIn("& '/Users/name & team''s %/python'", decoded)
        self.assertIn("'/tmp/state & ''quoted'' %!()'", decoded)
        self.assertNotIn(arguments[0], windows)
        self.assertRegex(encoded, r"^[A-Za-z0-9+/]+=*$")

    def test_plan_repairs_end_marker_displaced_by_codex_features_writer(self) -> None:
        token = "8" * 64
        port = 4376
        (self.home / "config.toml").write_text('model = "kept"\n', encoding="utf-8")
        installed = self._plan(auth_token=token, listen_port=port)
        installer.apply_install(installed)

        config_path = self.home / "config.toml"
        managed = config_path.read_bytes()
        marker = (installer.MANAGED_END + "\n").encode("utf-8")
        displaced = (
            b"# preserved host feature activation\n"
            b"\n"
            b"[features]\n"
            b'enabled = ["hooks"]\n'
        )
        drifted = managed.replace(marker, displaced + marker, 1)
        config_path.write_bytes(drifted)

        normalized = managed.replace(marker, marker + displaced, 1)
        repair = self._plan(persist=False)
        config_spec = repair.journal["codex_homes"][0]["config"]
        self.assertEqual(config_path.read_bytes(), drifted)
        self.assertEqual(config_spec["before"]["sha256"], installer._sha256(drifted))
        self.assertEqual(config_spec["after_sha256"], installer._sha256(normalized))

        retirement = installer.plan_install(
            self.source,
            self.state,
            {},
            retire_codex_homes={"codex-main": self.home},
            python_executable=Path(sys.executable).resolve(),
            persist=False,
        )
        retired_config_spec = retirement.journal["retired_codex_homes"][0]["config"]
        managed_block = installer._managed_otel_block(port, token).encode("utf-8")
        expected_retired = managed.replace(managed_block, displaced, 1)
        self.assertEqual(config_path.read_bytes(), drifted)
        self.assertEqual(
            retired_config_spec["after_sha256"],
            installer._sha256(expected_retired),
        )

        previous_token = "7" * 64
        previous_port = 4375
        crlf_marker = installer.MANAGED_END + "\r\n"
        previous_block = installer._managed_otel_block(
            previous_port,
            previous_token,
            "\r\n",
        )
        crlf_displaced = "# kept\r\n[features]\r\nenabled = [\"hooks\"]\r\n"
        previous_drift = previous_block.replace(
            crlf_marker,
            crlf_displaced + crlf_marker,
            1,
        )
        upgraded = installer._render_otel_config(
            previous_drift.encode("utf-8"),
            listen_port=port,
            auth_token=token,
            previous_port=previous_port,
            previous_token=previous_token,
        )
        self.assertEqual(
            upgraded,
            (
                installer._managed_otel_block(port, token, "\r\n")
                + crlf_displaced
            ).encode("utf-8"),
        )

        installer.save_plan(repair)
        installer.apply_install(repair)
        self.assertEqual(config_path.read_bytes(), normalized)

    def test_displaced_end_marker_repair_refuses_otel_edits_and_owners(self) -> None:
        token = "6" * 64
        port = 4377
        managed = installer._managed_otel_block(port, token)
        marker = installer.MANAGED_END + "\n"
        payload = managed[: -len(marker)]
        conflicting = {
            "scalar still in otel": (
                payload
                + 'log_user_prompt = true\n[features]\nenabled = ["hooks"]\n'
                + marker
            ),
            "interleaved otel payload": managed.replace(
                "log_user_prompt = false\n",
                '[features]\nenabled = ["hooks"]\nlog_user_prompt = false\n',
                1,
            ),
            "later otel owner": (
                payload
                + '[features]\nenabled = ["hooks"]\n[otel.extra]\nexporter = "none"\n'
                + marker
            ),
            "assignment before table": (
                payload
                + 'enabled = ["hooks"]\n[features]\n'
                + marker
            ),
            "malformed table header": (
                payload
                + '["features]\nenabled = ["hooks"]\n'
                + marker
            ),
        }
        for label, config in conflicting.items():
            with self.subTest(label=label), self.assertRaisesRegex(
                installer.InstallerConflict,
                "managed Codex otel block was edited",
            ):
                installer._render_otel_config(
                    config.encode("utf-8"),
                    listen_port=port,
                    auth_token=token,
                    previous_port=port,
                    previous_token=token,
                )

    def test_existing_or_malformed_otel_configuration_is_never_overwritten(self) -> None:
        conflicting = (
            '[otel]\nexporter = "none"\n',
            'otel.log_user_prompt = true\n',
            '["otel"]\nexporter = "none"\n',
            installer.MANAGED_BEGIN + "\n[otel]\n",
        )
        for index, text in enumerate(conflicting):
            with self.subTest(index=index):
                home = self.root / ("conflict-home-{}".format(index))
                home.mkdir()
                config = home / "config.toml"
                config.write_text(text, encoding="utf-8")
                state = self.root / ("conflict-state-{}".format(index))
                with self.assertRaises(installer.InstallerConflict):
                    installer.plan_install(
                        self.source,
                        state,
                        {"conflict-{}".format(index): home},
                        python_executable=Path(sys.executable).resolve(),
                    )
                self.assertEqual(config.read_text(encoding="utf-8"), text)
                self.assertFalse(state.exists())

    def test_atomic_replace_retries_only_a_bounded_number(self) -> None:
        calls = {"count": 0}

        def flaky(_source: str, _destination: str) -> None:
            calls["count"] += 1
            if calls["count"] < 3:
                raise PermissionError("sharing violation")

        with mock.patch.object(installer.os, "replace", side_effect=flaky), mock.patch.object(
            installer, "_retryable_replace_error", return_value=True
        ), mock.patch.object(installer.time, "sleep"):
            installer._atomic_replace(Path("source"), Path("destination"), attempts=4)
        self.assertEqual(calls["count"], 3)

    def test_platform_classification_distinguishes_native_and_wsl(self) -> None:
        with mock.patch.object(
            installer.platforms,
            "detect_platform",
            return_value=installer.platforms.PlatformIdentity("macos", "native"),
        ):
            self.assertEqual(installer._platform_info(), {"os": "macos", "environment": "native"})
        with mock.patch.object(
            installer.platforms,
            "detect_platform",
            return_value=installer.platforms.PlatformIdentity("windows", "native"),
        ):
            self.assertEqual(installer._platform_info(), {"os": "windows", "environment": "native"})
        with mock.patch.object(
            installer.platforms,
            "detect_platform",
            return_value=installer.platforms.PlatformIdentity("linux", "native"),
        ):
            self.assertEqual(installer._platform_info(), {"os": "linux", "environment": "native"})
        with mock.patch.object(
            installer.platforms,
            "detect_platform",
            return_value=installer.platforms.PlatformIdentity("linux", "wsl"),
        ):
            self.assertEqual(installer._platform_info(), {"os": "linux", "environment": "wsl"})

    def test_current_host_wsl_policy_rejects_windows_mounted_state(self) -> None:
        with mock.patch.object(
            installer.platforms,
            "detect_platform",
            return_value=installer.platforms.PlatformIdentity("linux", "wsl"),
        ):
            with self.assertRaisesRegex(installer.InstallerError, "state placement policy"):
                installer.plan_install(
                    self.source,
                    Path("/mnt/c/Users/example/AppData/Local/HolySkills/DeliveryEfficiency"),
                    {"codex-wsl": self.home},
                    python_executable=Path(sys.executable).resolve(),
                )

    def test_linux_mount_evidence_rejects_drvfs_remote_and_unknown_filesystems(self) -> None:
        mountinfo = "\n".join(
            (
                "24 1 8:1 / / rw,relatime - ext4 /dev/sda1 rw",
                "31 24 0:42 / /workspace rw,nosuid,nodev - 9p C:\\\\ rw,aname=drvfs;path=C:\\\\workspace",
                "32 24 0:43 / /srv/team rw,relatime - nfs4 fileserver:/team rw,vers=4.2",
                "33 24 0:44 / /future rw,relatime - mysteryfs none rw",
                "34 24 8:2 / /media/My\\040Disk rw,relatime - xfs /dev/sdb1 rw",
                "35 24 0:45 / /run/volatile rw,nosuid,nodev - tmpfs tmpfs rw,size=65536k",
                "36 24 0:46 / /run/ram-backed rw,nosuid,nodev - ramfs ramfs rw",
            )
        )
        linux = installer.platforms.PlatformIdentity("linux", "native")
        wsl = installer.platforms.PlatformIdentity("linux", "wsl")

        installer.platforms._validate_local_state_filesystem(
            "/home/user/.local/state/holyskills", linux, linux_mountinfo=mountinfo
        )
        installer.platforms._validate_local_state_filesystem(
            "/media/My Disk/holyskills", linux, linux_mountinfo=mountinfo
        )
        with self.assertRaisesRegex(
            installer.platforms.PlatformConfigurationError, "DrvFS|local filesystem"
        ):
            installer.platforms._validate_local_state_filesystem(
                "/workspace/repo/.state", wsl, linux_mountinfo=mountinfo
            )
        with self.assertRaisesRegex(
            installer.platforms.PlatformConfigurationError, "local filesystem"
        ):
            installer.platforms._validate_local_state_filesystem(
                "/srv/team/recorder", linux, linux_mountinfo=mountinfo
            )
        with self.assertRaisesRegex(
            installer.platforms.PlatformConfigurationError, "not recognized as local"
        ):
            installer.platforms._validate_local_state_filesystem(
                "/future/recorder", linux, linux_mountinfo=mountinfo
            )
        with self.assertRaisesRegex(
            installer.platforms.PlatformConfigurationError, "mount evidence"
        ):
            installer.platforms._validate_local_state_filesystem(
                "/home/user/state", linux, linux_mountinfo="malformed"
            )
        for path in ("/run/volatile/recorder", "/run/ram-backed/recorder"):
            with self.subTest(path=path), self.assertRaisesRegex(
                installer.platforms.PlatformConfigurationError, "durable local filesystem"
            ):
                installer.platforms._validate_local_state_filesystem(
                    path, linux, linux_mountinfo=mountinfo
                )

    def test_windows_unc_remote_and_unknown_storage_are_rejected(self) -> None:
        windows = installer.platforms.PlatformIdentity("windows", "native")
        for path in (
            r"\\wsl$\Ubuntu\home\user\recorder",
            r"\\server\share\recorder",
            r"\\?\UNC\server\share\recorder",
        ):
            with self.subTest(path=path), self.assertRaisesRegex(
                installer.platforms.PlatformConfigurationError, "UNC|network"
            ):
                installer.platforms.validate_state_path(path, windows)

        installer.platforms._validate_local_state_filesystem(
            r"C:\Users\fixture\AppData\Local\HolySkills", windows, windows_drive_type=3
        )
        for drive_type in (0, 1, 2, 4, 5, 6):
            with self.subTest(drive_type=drive_type), self.assertRaisesRegex(
                installer.platforms.PlatformConfigurationError, "fixed local drive"
            ):
                installer.platforms._validate_local_state_filesystem(
                    r"Z:\Recorder", windows, windows_drive_type=drive_type
                )

    def test_macos_mount_flags_must_confirm_local_storage(self) -> None:
        macos = installer.platforms.PlatformIdentity("macos", "native")
        installer.platforms._validate_local_state_filesystem(
            "/Users/fixture/Library/Application Support/HolySkills",
            macos,
            darwin_mount_flags=0x00001000,
        )
        with self.assertRaisesRegex(
            installer.platforms.PlatformConfigurationError, "local filesystem"
        ):
            installer.platforms._validate_local_state_filesystem(
                "/Volumes/TeamShare/HolySkills", macos, darwin_mount_flags=0
            )

    def test_persisted_plan_can_apply_verify_and_rollback_without_in_memory_secret(self) -> None:
        plan = self._plan(auth_token="e" * 64)
        loaded = installer.load_plan(plan.journal_path, plan.plan_digest)
        self.assertEqual(loaded.auth_token, "e" * 64)
        installer.apply_install(plan.journal_path, plan_digest=plan.plan_digest)
        self.assertTrue(
            installer.verify_install(
                plan.journal_path,
                plan_digest=plan.plan_digest,
            )["ok"]
        )
        self.assertEqual(
            installer.rollback_install(
                plan.journal_path,
                plan_digest=plan.plan_digest,
            )["status"],
            "rolled-back",
        )

    def test_interrupted_apply_journal_is_reconciled_from_bound_namespace(self) -> None:
        plan = self._plan(auth_token="f" * 64)
        installer.apply_install(plan)
        for action in plan.journal["actions"]:
            action["applied"] = False
        installer._journal_update(plan, "applying", plan.journal["actions"], None)
        with self.assertRaises(installer.InstallerConflict):
            installer.apply_install(
                plan.journal_path,
                plan_digest=plan.plan_digest,
            )
        recovered = installer.load_plan(plan.journal_path, plan.plan_digest)
        self.assertEqual(recovered.journal["status"], "apply-failed-rolled-back")
        self.assertFalse((self.home / "hooks.json").exists())
        self.assertFalse((self.home / "config.toml").exists())
        self.assertFalse((self.state / "settings.json").exists())
        self.assertFalse((self.state / "recorder.py").exists())
        self.assertFalse((self.state / "managed-targets.json").exists())
        self.assertFalse(Path(plan.journal["target"]["install_root"]).exists())

    def test_stable_launcher_updates_runs_idempotently_and_rolls_back(self) -> None:
        self.state.mkdir(parents=True)
        launcher = self.state / "recorder.py"
        old_launcher = b"# prior managed launcher bytes\n"
        launcher.write_bytes(old_launcher)
        old_mode = launcher.stat().st_mode & 0o777

        first = self._plan(auth_token="1" * 64, listen_port=4331)
        installer.apply_install(first)
        self.assertEqual(launcher.read_bytes(), installer.stable_launcher_bytes())
        self.assertFalse(launcher.is_symlink())
        if os.name != "nt":
            self.assertEqual(launcher.stat().st_mode & 0o777, 0o500)
        hostile_environment = dict(os.environ)
        hostile_environment["HOME"] = str(self.root / "unrelated synthetic home")
        hostile_environment["HOLYSKILLS_DELIVERY_EFFICIENCY_STATE_DIR"] = str(
            self.root / "wrong inherited state"
        )
        execution = subprocess.run(
            [str(Path(sys.executable).resolve()), str(launcher)],
            cwd=str(self.root),
            env=hostile_environment,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(execution.returncode, 0, execution.stderr)
        self.assertEqual(execution.stdout, str(self.state) + "\n")

        settings_path = self.state / "settings.json"
        original_settings = settings_path.read_bytes()
        invalid = json.loads(original_settings)
        invalid["install_root"] = "relative/install"
        settings_path.write_text(json.dumps(invalid), encoding="utf-8")
        relative_failure = subprocess.run(
            [str(Path(sys.executable).resolve()), str(launcher)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertNotEqual(relative_failure.returncode, 0)
        self.assertIn("install_root must be absolute", relative_failure.stderr)
        invalid = json.loads(original_settings)
        invalid["recorder_version"] = "9.9"
        settings_path.write_text(json.dumps(invalid), encoding="utf-8")
        version_failure = subprocess.run(
            [str(Path(sys.executable).resolve()), str(launcher)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertNotEqual(version_failure.returncode, 0)
        self.assertIn("recorder_version is invalid", version_failure.stderr)

        invalid = json.loads(original_settings)
        invalid["recorder_version"] = "9.9.9"
        settings_path.write_text(json.dumps(invalid), encoding="utf-8")
        path_failure = subprocess.run(
            [str(Path(sys.executable).resolve()), str(launcher)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertNotEqual(path_failure.returncode, 0)
        self.assertIn("outside the versioned state location", path_failure.stderr)

        next_install = self.state / "installs" / "0.2.10"
        next_install.mkdir(parents=True)
        (next_install / "recorder.py").write_text(
            "import os\nprint(os.environ.get('HOLYSKILLS_DELIVERY_EFFICIENCY_STATE_DIR', 'missing'))\n",
            encoding="utf-8",
        )
        next_settings = json.loads(original_settings)
        next_settings["recorder_version"] = "0.2.10"
        next_settings["install_root"] = str(next_install)
        settings_path.write_text(json.dumps(next_settings), encoding="utf-8")
        next_execution = subprocess.run(
            [str(Path(sys.executable).resolve()), str(launcher)],
            cwd=str(self.root),
            env=hostile_environment,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(next_execution.returncode, 0, next_execution.stderr)
        self.assertEqual(next_execution.stdout, str(self.state) + "\n")
        self.assertEqual(launcher.read_bytes(), installer.stable_launcher_bytes())

        linked_install = self.state / "installs" / "0.2.11"
        try:
            linked_install.symlink_to(next_install, target_is_directory=True)
        except (OSError, NotImplementedError):
            pass
        else:
            linked_settings = json.loads(original_settings)
            linked_settings["recorder_version"] = "0.2.11"
            linked_settings["install_root"] = str(linked_install)
            settings_path.write_text(json.dumps(linked_settings), encoding="utf-8")
            linked_failure = subprocess.run(
                [str(Path(sys.executable).resolve()), str(launcher)],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertNotEqual(linked_failure.returncode, 0)
            self.assertIn("install_root is missing or unsafe", linked_failure.stderr)
        settings_path.write_bytes(original_settings)
        if os.name != "nt":
            settings_path.chmod(0o600)

        second = self._plan()
        installer.apply_install(second)
        launcher_actions = [action for action in second.journal["actions"] if action["kind"] == "launcher"]
        self.assertEqual(len(launcher_actions), 1)
        self.assertFalse(launcher_actions[0]["changed"])
        installer.rollback_install(second)
        installer.rollback_install(first)
        self.assertEqual(launcher.read_bytes(), old_launcher)
        if os.name != "nt":
            self.assertEqual(launcher.stat().st_mode & 0o777, old_mode)

    def test_auth_token_rotation_is_secret_transactional_and_rollback_safe(self) -> None:
        original_token = "2" * 64
        first = self._plan(auth_token=original_token, listen_port=4332)
        installer.apply_install(first)
        settings_path = self.state / "settings.json"
        config_path = self.home / "config.toml"
        settings_before = settings_path.read_bytes()
        config_before = config_path.read_bytes()

        with self.assertRaises(installer.InstallerConflict):
            self._plan(rotate_auth_token=True, listen_port=4332)

        rotating = self._plan(rotate_auth_token=True)
        rotated_token = rotating.auth_token
        self.assertRegex(rotated_token, r"^[0-9a-f]{64}$")
        self.assertNotEqual(rotated_token, original_token)
        self.assertNotEqual(rotating.journal["receiver"]["listen_port"], 4332)
        self.assertEqual(
            rotating.journal["receiver"]["listen_port_provenance"],
            "auth-rotation-port-rotation",
        )
        self.assertEqual(rotating.journal["receiver"]["auth_token_lifecycle"], "rotated")
        journal_text = rotating.journal_path.read_text(encoding="utf-8")
        self.assertNotIn(rotated_token, journal_text)
        self.assertNotIn(original_token, journal_text)

        installer.apply_install(rotating)
        installed_settings = runtime.load_settings(self.state)
        self.assertEqual(installed_settings["auth_token"], rotated_token)
        installed_config = config_path.read_text(encoding="utf-8")
        self.assertIn(rotated_token, installed_config)
        self.assertNotIn(original_token, installed_config)
        self.assertNotIn(rotated_token, rotating.journal_path.read_text(encoding="utf-8"))

        installer.rollback_install(rotating)
        self.assertEqual(settings_path.read_bytes(), settings_before)
        self.assertEqual(config_path.read_bytes(), config_before)
        self.assertEqual(runtime.load_settings(self.state)["auth_token"], original_token)

        from delivery_efficiency.cli import build_parser

        parsed = build_parser().parse_args(
            [
                "install",
                "plan",
                "--codex-home",
                "main={}".format(self.home),
                "--rotate-auth-token",
            ]
        )
        self.assertTrue(parsed.rotate_auth_token)


class ClaudeHomeInstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="delivery-claude-installer-")
        self.receiver_activation = mock.patch.object(
            installer, "_activate_receiver", return_value=None
        )
        self.receiver_activation.start()
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "source tool"
        self.state = self.root / "state & telemetry"
        self.codex_home = self.root / "codex home"
        self.claude_home = self.root / "Claude home's % configuration"
        self.codex_home.mkdir(parents=True)
        self.claude_home.mkdir(parents=True)
        self.claude_probe = mock.patch.object(
            installer,
            "_probe_claude_runtime",
            return_value=(Path(sys.executable).resolve(), "2.1.220"),
        )
        self.claude_probe.start()
        package = self.source / "delivery_efficiency"
        contract = self.source / "contract"
        package.mkdir(parents=True)
        contract.mkdir()
        (self.source / "recorder.py").write_text("print('runtime')\n", encoding="utf-8")
        (package / "__init__.py").write_text(
            "RECORDER_VERSION = '0.2.9'\nSCHEMA_VERSION = '1.2'\nADAPTER_VERSION = '0.2.4'\n",
            encoding="utf-8",
        )
        (contract / "adapter-event-v1.schema.json").write_text("{}\n", encoding="utf-8")
        (contract / "adapter-event-v1.1.schema.json").write_text("{}\n", encoding="utf-8")
        (contract / "adapter-event-v1.2.schema.json").write_text("{}\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.claude_probe.stop()
        self.receiver_activation.stop()
        self.temporary.cleanup()

    def _plan(self, **kwargs: object) -> installer.InstallPlan:
        kwargs.setdefault("claude_homes", {"claude-user": self.claude_home})
        return installer.plan_install(
            self.source,
            self.state,
            kwargs.pop("codex_homes", {}),
            python_executable=Path(sys.executable).resolve(),
            **kwargs,
        )

    def _settings_value(self) -> dict:
        return json.loads((self.claude_home / "settings.json").read_text(encoding="utf-8"))

    def test_claude_only_install_creates_managed_hooks_and_env(self) -> None:
        plan = self._plan(auth_token="a" * 64, listen_port=4361)
        result = installer.apply_install(plan)
        self.assertTrue(result["ok"])
        self.assertEqual(result["claude_homes"], ["claude-user"])
        self.assertEqual(result["codex_homes"], [])
        self.assertEqual(plan.journal["claude_runtime"]["observed_version"], "2.1.220")
        self.assertEqual(plan.journal["claude_runtime"]["required_minimum"], "2.1.212")
        value = self._settings_value()
        session_start_handler = None
        for event in installer.CLAUDE_HOOK_EVENTS:
            groups = value["hooks"][event]
            managed = [
                handler
                for group in groups
                for handler in group["hooks"]
                if installer._handler_is_managed(handler)
            ]
            self.assertEqual(len(managed), 1, event)
            if event == "SessionStart":
                session_start_handler = managed[0]
            self.assertNotIn("commandWindows", managed[0])
            self.assertEqual(managed[0]["command"], str(Path(sys.executable).resolve()))
            self.assertEqual(managed[0]["args"][0], str(self.state / "recorder.py"))
            self.assertEqual(managed[0]["args"][1:3], ["hook", "claude"])
            self.assertEqual(managed[0]["args"][-2:], ["--managed-id", installer.MANAGED_ID])
            if event == "SessionStart":
                self.assertEqual(managed[0]["timeout"], installer.CLAUDE_HOOK_TIMEOUT_SECONDS)
                self.assertNotIn("async", managed[0])
            elif event == "UserPromptSubmit":
                self.assertEqual(
                    managed[0]["timeout"], installer.CLAUDE_PROMPT_HOOK_TIMEOUT_SECONDS
                )
                self.assertLessEqual(managed[0]["timeout"], 1)
                self.assertNotIn("async", managed[0])
            else:
                self.assertEqual(
                    managed[0]["timeout"], installer.CLAUDE_ORDINARY_HOOK_TIMEOUT_SECONDS
                )
                if event in installer.CLAUDE_ASYNC_HOOK_EVENTS:
                    self.assertIs(managed[0]["async"], True)
                else:
                    self.assertNotIn("async", managed[0])
            self.assertNotIn("matcher", groups[0])
        for uninstalled_event in (
            "SessionEnd",
            "PreToolUse",
            "PostToolUse",
            "PostToolUseFailure",
            "MessageDisplay",
        ):
            self.assertNotIn(uninstalled_event, value["hooks"])
        environment = value["env"]
        expected_privacy = {
            "OTEL_METRICS_EXPORTER": "none",
            "OTEL_TRACES_EXPORTER": "none",
            "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA": "0",
            "ENABLE_ENHANCED_TELEMETRY_BETA": "0",
            "OTEL_LOG_USER_PROMPTS": "0",
            "OTEL_LOG_ASSISTANT_RESPONSES": "0",
            "OTEL_LOG_TOOL_DETAILS": "0",
            "OTEL_LOG_TOOL_CONTENT": "0",
            "OTEL_LOG_RAW_API_BODIES": "0",
            "OTEL_METRICS_INCLUDE_ACCOUNT_UUID": "false",
            "OTEL_METRICS_INCLUDE_SESSION_ID": "false",
            "OTEL_METRICS_INCLUDE_RESOURCE_ATTRIBUTES": "false",
        }
        self.assertEqual(environment["CLAUDE_CODE_ENABLE_TELEMETRY"], "1")
        self.assertEqual(environment["OTEL_LOGS_EXPORTER"], "otlp")
        self.assertEqual(environment["OTEL_EXPORTER_OTLP_LOGS_PROTOCOL"], "http/json")
        self.assertEqual(
            environment["OTEL_EXPORTER_OTLP_LOGS_ENDPOINT"],
            "http://127.0.0.1:4361/v1/logs",
        )
        self.assertEqual(
            environment["OTEL_EXPORTER_OTLP_LOGS_HEADERS"],
            "{}={}".format(installer.AUTH_HEADER, "a" * 64),
        )
        self.assertEqual(
            {key: environment[key] for key in expected_privacy}, expected_privacy
        )
        if os.name != "nt":
            self.assertEqual(
                (self.claude_home / "settings.json").stat().st_mode & 0o777, 0o600
            )
        self.assertEqual(CLAUDE_HOOK_TELEMETRY_BUDGET_SECONDS, 8.5)
        self.assertEqual(CLAUDE_PROMPT_HOOK_TELEMETRY_BUDGET_SECONDS, 0.75)
        self.assertLessEqual(CLAUDE_PROMPT_HOOK_TELEMETRY_BUDGET_SECONDS, 0.75)
        self.assertEqual(CLAUDE_ORDINARY_HOOK_TELEMETRY_BUDGET_SECONDS, 2.25)
        self.assertIsNotNone(session_start_handler)
        conformance = subprocess.run(
            [session_start_handler["command"]] + session_start_handler["args"],
            input=b"{}",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=5.0,
        )
        self.assertEqual(conformance.returncode, 0, conformance.stderr.decode("utf-8", "replace"))

    def test_existing_user_settings_are_preserved_and_apply_is_idempotent(self) -> None:
        existing = {
            "model": "opus",
            "permissions": {"allow": ["Bash(ls:*)"]},
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [{"type": "command", "command": "existing --policy", "timeout": 9}],
                    }
                ]
            },
            "env": {"EDITOR": "vim"},
        }
        (self.claude_home / "settings.json").write_text(json.dumps(existing), encoding="utf-8")
        first = self._plan(auth_token="b" * 64, listen_port=4362)
        installer.apply_install(first)
        after_first = (self.claude_home / "settings.json").read_bytes()
        value = json.loads(after_first)
        self.assertEqual(value["model"], "opus")
        self.assertEqual(value["permissions"], existing["permissions"])
        self.assertEqual(value["env"]["EDITOR"], "vim")
        self.assertEqual(value["hooks"]["PreToolUse"][0], existing["hooks"]["PreToolUse"][0])
        managed_prompt = [
            handler
            for group in value["hooks"]["UserPromptSubmit"]
            for handler in group["hooks"]
            if installer._handler_is_managed(handler)
        ]
        self.assertEqual(len(managed_prompt), 1)

        second = self._plan()
        installer.apply_install(second)
        self.assertEqual((self.claude_home / "settings.json").read_bytes(), after_first)
        self.assertTrue(all(not action["changed"] for action in second.journal["actions"]))

    def test_023_upgrade_preserves_receiver_and_migrates_handlers_once(self) -> None:
        previous_version = "0.2.3"
        previous_port = 4363
        token = "c" * 64
        interpreter = Path(sys.executable).resolve()
        previous_install = self.state / "installs" / previous_version
        previous_settings = {
            "schema_version": installer.SETTINGS_SCHEMA_VERSION,
            "recorder_version": previous_version,
            "listen_host": "127.0.0.1",
            "listen_port": previous_port,
            "auth_token": token,
            "install_root": str(previous_install),
            "python_executable": str(interpreter),
            "platform": installer._platform_info(),
        }
        runtime_target = installer._runtime_target_ref(token, "codex", self.codex_home)
        previous_codex_handler = installer._hook_handler(
            interpreter,
            previous_install,
            self.state,
            runtime_target,
        )
        previous_codex_hooks = installer._render_hooks(
            b"", previous_codex_handler, None
        )
        previous_codex_config = installer._managed_otel_block(
            previous_port, token
        ).encode("utf-8")
        previous_claude_handlers = installer._claude_hook_handlers(
            interpreter, previous_install, self.state
        )
        previous_claude_settings = installer._json_bytes(
            {
                "model": "opus",
                "hooks": {
                    event: [{"hooks": [handler]}]
                    for event, handler in previous_claude_handlers.items()
                },
                "env": {
                    "EDITOR": "vim",
                    **installer._managed_claude_env_for_version(
                        previous_port, token, previous_version
                    ),
                },
            }
        )
        previous_inventory = installer._managed_targets_bytes(
            [
                {
                    "runtime": "claude",
                    "name": "claude-user",
                    "home": str(self.claude_home),
                },
                {
                    "runtime": "codex",
                    "name": "codex-main",
                    "home": str(self.codex_home),
                },
            ]
        )
        self.state.mkdir(parents=True)
        (self.state / "settings.json").write_bytes(installer._json_bytes(previous_settings))
        (self.state / "managed-targets.json").write_bytes(previous_inventory)
        (self.codex_home / "hooks.json").write_bytes(previous_codex_hooks)
        (self.codex_home / "config.toml").write_bytes(previous_codex_config)
        (self.claude_home / "settings.json").write_bytes(previous_claude_settings)

        plan = self._plan(codex_homes={"codex-main": self.codex_home})
        self.assertEqual(plan.auth_token, token)
        self.assertEqual(plan.journal["receiver"]["listen_port"], previous_port)
        self.assertEqual(
            plan.journal["receiver"]["listen_port_provenance"],
            "compatible-upgrade-port-preserved",
        )
        self.assertEqual(
            plan.journal["receiver"]["lifecycle_handoff"],
            "authenticated-same-port-retirement",
        )
        self.assertEqual(plan.journal["receiver"]["auth_token_lifecycle"], "preserved")
        self.assertTrue(plan.journal["receiver"]["managed_binding_change"])

        actions = {(item["kind"], item["name"]): item for item in plan.journal["actions"]}
        self.assertTrue(actions[("hooks", "codex-main")]["bytes_changed"])
        self.assertTrue(actions[("claude-settings", "claude-user")]["bytes_changed"])
        self.assertFalse(actions[("otel-config", "codex-main")]["bytes_changed"])

        installer.apply_install(plan)
        codex_value = json.loads(
            (self.codex_home / "hooks.json").read_text(encoding="utf-8")
        )
        codex_handler = codex_value["hooks"]["UserPromptSubmit"][0]["hooks"][0]
        self.assertEqual(
            shlex.split(codex_handler["command"])[1],
            str(self.state / "recorder.py"),
        )
        claude_value = self._settings_value()
        for event in installer.CLAUDE_HOOK_EVENTS:
            managed = [
                handler
                for group in claude_value["hooks"][event]
                for handler in group["hooks"]
                if installer._handler_is_managed(handler)
            ]
            self.assertEqual(managed[0]["args"][0], str(self.state / "recorder.py"))
        self.assertEqual(claude_value["env"]["EDITOR"], "vim")

        idempotent = self._plan(codex_homes={"codex-main": self.codex_home})
        self.assertTrue(all(not action["changed"] for action in idempotent.journal["actions"]))

        installer.rollback_install(plan)
        self.assertEqual(
            (self.state / "settings.json").read_bytes(),
            installer._json_bytes(previous_settings),
        )
        self.assertEqual((self.state / "managed-targets.json").read_bytes(), previous_inventory)
        self.assertEqual((self.codex_home / "hooks.json").read_bytes(), previous_codex_hooks)
        self.assertEqual((self.codex_home / "config.toml").read_bytes(), previous_codex_config)
        self.assertEqual((self.claude_home / "settings.json").read_bytes(), previous_claude_settings)

    def test_stable_to_next_upgrade_does_not_rewrite_host_configuration(self) -> None:
        first = self._plan(
            codex_homes={"codex-main": self.codex_home},
            auth_token="d" * 64,
            listen_port=4364,
        )
        installer.apply_install(first)
        host_paths = (
            self.codex_home / "hooks.json",
            self.codex_home / "config.toml",
            self.claude_home / "settings.json",
        )
        before = {
            path: (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns)
            for path in host_paths
        }
        source_version = self.source / "delivery_efficiency" / "__init__.py"
        source_version.write_text(
            "RECORDER_VERSION = '0.2.10'\nSCHEMA_VERSION = '1.2'\nADAPTER_VERSION = '0.2.4'\n",
            encoding="utf-8",
        )

        with mock.patch.object(installer, "RECORDER_VERSION", "0.2.10"):
            upgrade = self._plan(codex_homes={"codex-main": self.codex_home})
            self.assertEqual(upgrade.auth_token, first.auth_token)
            self.assertEqual(upgrade.journal["receiver"]["listen_port"], 4364)
            self.assertEqual(
                upgrade.journal["receiver"]["lifecycle_handoff"],
                "authenticated-same-port-retirement",
            )
            self.assertFalse(upgrade.journal["receiver"]["managed_binding_change"])
            actions = {
                (item["kind"], item["name"]): item
                for item in upgrade.journal["actions"]
            }
            for key in (
                ("launcher", "stable"),
                ("hooks", "codex-main"),
                ("otel-config", "codex-main"),
                ("claude-settings", "claude-user"),
                ("managed-targets", "inventory"),
            ):
                self.assertFalse(actions[key]["changed"], key)
            self.assertTrue(actions[("install-tree", "runtime")]["changed"])
            self.assertTrue(actions[("settings", "recorder")]["changed"])

            installer.apply_install(upgrade)
            installer.verify_install(upgrade)
            for path in host_paths:
                self.assertEqual(
                    (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns),
                    before[path],
                    path,
                )
            installer.rollback_install(upgrade)

        installer.rollback_install(first)

    def test_legacy_claude_handlers_migrate_to_the_low_overhead_event_set(self) -> None:
        interpreter = Path(sys.executable).resolve()
        old_install = self.state / "installs" / "0.1.2"
        new_install = self.state / "installs" / installer.RECORDER_VERSION
        legacy_handlers = installer._claude_hook_handlers(
            interpreter,
            old_install,
            self.state,
            legacy_uniform_timeout=True,
            legacy_shell_command=True,
            events=installer.CLAUDE_LEGACY_HOOK_EVENTS,
        )
        old_port = 4375
        old_token = "1" * 64
        legacy_value = {
            "hooks": {
                event: [{"hooks": [handler]}]
                for event, handler in legacy_handlers.items()
            },
            "env": installer._managed_claude_env_for_version(
                old_port, old_token, "0.1.2"
            ),
        }
        current_handlers = installer._claude_hook_handlers(
            interpreter, new_install, self.state
        )
        migrated = json.loads(
            installer._render_claude_settings(
                installer._json_bytes(legacy_value),
                current_handlers,
                legacy_handlers,
                listen_port=4376,
                auth_token="2" * 64,
                previous_port=old_port,
                previous_token=old_token,
                previous_version="0.1.2",
            )
        )
        for removed_event in {"SessionEnd", "PreToolUse", "PostToolUse"}:
            self.assertFalse(
                any(
                    installer._handler_is_managed(handler)
                    for group in migrated["hooks"][removed_event]
                    for handler in group["hooks"]
                )
            )
        for event in installer.CLAUDE_HOOK_EVENTS:
            managed = [
                handler
                for group in migrated["hooks"][event]
                for handler in group["hooks"]
                if installer._handler_is_managed(handler)
            ]
            self.assertEqual(managed, [current_handlers[event]], event)

    def test_020_environment_upgrades_and_retires_by_its_recorded_version(self) -> None:
        interpreter = Path(sys.executable).resolve()
        old_port = 4377
        old_token = "3" * 64
        old_handlers = installer._claude_hook_handlers(
            interpreter, self.state / "installs" / "0.2.0", self.state
        )
        legacy = {
            "hooks": {
                event: [{"hooks": [handler]}]
                for event, handler in old_handlers.items()
            },
            "env": {
                "EDITOR": "vim",
                **installer._managed_claude_env_for_version(
                    old_port, old_token, "0.2.0"
                ),
            },
        }
        new_handlers = installer._claude_hook_handlers(
            interpreter, self.state / "installs" / installer.RECORDER_VERSION, self.state
        )
        upgraded_bytes = installer._render_claude_settings(
            installer._json_bytes(legacy),
            new_handlers,
            old_handlers,
            listen_port=4378,
            auth_token="4" * 64,
            previous_port=old_port,
            previous_token=old_token,
            previous_version="0.2.0",
        )
        upgraded = json.loads(upgraded_bytes)
        self.assertEqual(upgraded["env"]["EDITOR"], "vim")
        for key, value in installer._managed_claude_env(4378, "4" * 64).items():
            self.assertEqual(upgraded["env"][key], value, key)
        self.assertEqual(
            installer._render_claude_settings(
                upgraded_bytes,
                new_handlers,
                new_handlers,
                listen_port=4378,
                auth_token="4" * 64,
                previous_port=4378,
                previous_token="4" * 64,
                previous_version=installer.RECORDER_VERSION,
            ),
            upgraded_bytes,
        )

        retired = json.loads(
            installer._retire_claude_settings(
                installer._json_bytes(legacy),
                old_handlers,
                previous_port=old_port,
                previous_token=old_token,
                previous_version="0.2.0",
            )
        )
        self.assertEqual(retired["env"], {"EDITOR": "vim"})
        self.assertFalse(
            any(
                installer._handler_is_managed(handler)
                for groups in retired["hooks"].values()
                for group in groups
                for handler in group["hooks"]
            )
        )

    def test_020_transaction_upgrade_and_retirement_are_exactly_rollback_safe(self) -> None:
        previous_version = "0.2.0"
        previous_port = 4379
        previous_token = "5" * 64
        interpreter = Path(sys.executable).resolve()
        previous_install = self.state / "installs" / previous_version
        previous_settings = {
            "schema_version": installer.SETTINGS_SCHEMA_VERSION,
            "recorder_version": previous_version,
            "listen_host": "127.0.0.1",
            "listen_port": previous_port,
            "auth_token": previous_token,
            "install_root": str(previous_install),
            "python_executable": str(interpreter),
            "platform": installer._platform_info(),
        }
        previous_settings_bytes = installer._json_bytes(previous_settings)
        previous_handlers = installer._claude_hook_handlers(
            interpreter, previous_install, self.state
        )
        hooks = {}
        for event, handler in previous_handlers.items():
            group = {"hooks": [handler]}
            if event in installer.CLAUDE_TOOL_MATCHER_EVENTS:
                group["matcher"] = "*"
            hooks[event] = [group]
        previous_claude_bytes = installer._json_bytes(
            {
                "model": "opus",
                "hooks": hooks,
                "env": {
                    "EDITOR": "vim",
                    **installer._managed_claude_env_for_version(
                        previous_port, previous_token, previous_version
                    ),
                },
            }
        )
        previous_inventory_bytes = installer._managed_targets_bytes(
            [
                {
                    "runtime": "claude",
                    "name": "claude-user",
                    "home": str(self.claude_home),
                }
            ]
        )
        self.state.mkdir(parents=True)
        (self.state / "settings.json").write_bytes(previous_settings_bytes)
        (self.state / "managed-targets.json").write_bytes(previous_inventory_bytes)
        (self.claude_home / "settings.json").write_bytes(previous_claude_bytes)

        upgrade = self._plan()
        self.assertEqual(upgrade.journal["receiver"]["listen_port"], previous_port)
        self.assertEqual(
            upgrade.journal["receiver"]["lifecycle_handoff"],
            "authenticated-same-port-retirement",
        )
        installer.apply_install(upgrade)
        installer.verify_install(upgrade)
        upgraded = self._settings_value()
        self.assertEqual(upgraded["model"], "opus")
        self.assertEqual(upgraded["env"]["EDITOR"], "vim")
        managed = installer._managed_claude_env(
            upgrade.journal["receiver"]["listen_port"], upgrade.auth_token
        )
        self.assertEqual(
            {key: upgraded["env"][key] for key in managed},
            managed,
        )

        idempotent = self._plan()
        self.assertTrue(all(not action["changed"] for action in idempotent.journal["actions"]))
        installer.rollback_install(upgrade)
        self.assertEqual((self.state / "settings.json").read_bytes(), previous_settings_bytes)
        self.assertEqual(
            (self.state / "managed-targets.json").read_bytes(), previous_inventory_bytes
        )
        self.assertEqual(
            (self.claude_home / "settings.json").read_bytes(), previous_claude_bytes
        )

        retirement = self._plan(
            claude_homes={},
            retire_claude_homes={"claude-user": self.claude_home},
        )
        installer.apply_install(retirement)
        retired = self._settings_value()
        self.assertEqual(retired["model"], "opus")
        self.assertEqual(retired["env"], {"EDITOR": "vim"})
        self.assertFalse(
            any(
                installer._handler_is_managed(handler)
                for groups in retired["hooks"].values()
                for group in groups
                for handler in group["hooks"]
            )
        )
        installer.rollback_install(retirement)
        self.assertEqual((self.state / "settings.json").read_bytes(), previous_settings_bytes)
        self.assertEqual(
            (self.state / "managed-targets.json").read_bytes(), previous_inventory_bytes
        )
        self.assertEqual(
            (self.claude_home / "settings.json").read_bytes(), previous_claude_bytes
        )

    def test_user_owned_otel_environment_conflicts_before_mutation(self) -> None:
        conflicting = (
            {"OTEL_LOGS_EXPORTER": "otlp", "OTEL_EXPORTER_OTLP_ENDPOINT": "https://collector.invalid"},
            {"CLAUDE_CODE_ENABLE_TELEMETRY": "0"},
            {"OTEL_METRICS_EXPORTER": "otlp"},
            {"OTEL_TRACES_EXPORTER": "otlp"},
            {"CLAUDE_CODE_ENHANCED_TELEMETRY_BETA": "1"},
            {"ENABLE_ENHANCED_TELEMETRY_BETA": "1"},
            {"OTEL_EXPORTER_OTLP_LOGS_HEADERS": "authorization=Bearer user-owned"},
            {"OTEL_LOG_ASSISTANT_RESPONSES": "1"},
            {"OTEL_LOG_USER_PROMPTS": "1"},
            {"OTEL_LOG_TOOL_DETAILS": "1"},
            {"OTEL_LOG_TOOL_CONTENT": "1"},
            {"OTEL_LOG_RAW_API_BODIES": "file:/private/export"},
            {"OTEL_METRICS_INCLUDE_ACCOUNT_UUID": "true"},
            {"OTEL_METRICS_INCLUDE_SESSION_ID": "true"},
            {"OTEL_METRICS_INCLUDE_RESOURCE_ATTRIBUTES": "true"},
        )
        for index, environment in enumerate(conflicting):
            with self.subTest(index=index):
                home = self.root / "conflict-home-{}".format(index)
                home.mkdir()
                original = json.dumps({"env": environment})
                (home / "settings.json").write_text(original, encoding="utf-8")
                state = self.root / "conflict-state-{}".format(index)
                with self.assertRaises(installer.InstallerConflict):
                    installer.plan_install(
                        self.source,
                        state,
                        {},
                        claude_homes={"conflict": home},
                        python_executable=Path(sys.executable).resolve(),
                    )
                self.assertEqual((home / "settings.json").read_text(encoding="utf-8"), original)
                self.assertFalse(state.exists())

    def test_edited_managed_handler_blocks_replanning_and_drifted_rollback(self) -> None:
        before = json.dumps({"statusLine": {"type": "command", "command": "keep"}})
        (self.claude_home / "settings.json").write_text(before, encoding="utf-8")
        plan = self._plan(auth_token="c" * 64)
        installer.apply_install(plan)
        value = self._settings_value()
        for group in value["hooks"]["Stop"]:
            for handler in group["hooks"]:
                if installer._handler_is_managed(handler):
                    handler["timeout"] = 99
        drifted = json.dumps(value)
        (self.claude_home / "settings.json").write_text(drifted, encoding="utf-8")
        with self.assertRaises(installer.InstallerConflict):
            self._plan()
        # Exact rollback refuses to touch a target that drifted after apply.
        with self.assertRaises(installer.InstallerVerificationError):
            installer.rollback_install(plan)
        self.assertEqual(
            (self.claude_home / "settings.json").read_text(encoding="utf-8"), drifted
        )

    def test_rollback_restores_prior_settings_exactly(self) -> None:
        before = json.dumps({"model": "haiku", "env": {"EDITOR": "nano"}}, indent=4) + "\n"
        (self.claude_home / "settings.json").write_text(before, encoding="utf-8")
        plan = self._plan(auth_token="d" * 64)
        installer.apply_install(plan)
        self.assertNotEqual(
            (self.claude_home / "settings.json").read_text(encoding="utf-8"), before
        )
        installer.rollback_install(plan)
        self.assertEqual(
            (self.claude_home / "settings.json").read_text(encoding="utf-8"), before
        )
        self.assertFalse((self.state / "settings.json").exists())

    @unittest.skipIf(os.name == "nt", "POSIX mode contract is not claimed on Windows")
    def test_secret_bearing_claude_settings_are_private_and_rollback_restores_mode(self) -> None:
        settings_path = self.claude_home / "settings.json"
        before = b'{"model":"haiku"}\n'
        settings_path.write_bytes(before)
        settings_path.chmod(0o644)

        applied = self._plan(auth_token="8" * 64, listen_port=4367)
        installer.apply_install(applied)
        self.assertEqual(settings_path.stat().st_mode & 0o777, 0o600)
        installer.rollback_install(applied)
        self.assertEqual(settings_path.read_bytes(), before)
        self.assertEqual(settings_path.stat().st_mode & 0o777, 0o644)

        failed = self._plan(auth_token="9" * 64, listen_port=4368)
        with self.assertRaisesRegex(RuntimeError, "injected installer failure"):
            installer.apply_install(failed, fault_after=4)
        self.assertEqual(settings_path.read_bytes(), before)
        self.assertEqual(settings_path.stat().st_mode & 0o777, 0o644)

    def test_token_rotation_refuses_an_omitted_previously_managed_claude_home(self) -> None:
        first = self._plan(
            codex_homes={"codex-main": self.codex_home},
            auth_token="6" * 64,
            listen_port=4369,
        )
        installer.apply_install(first)
        claude_before = (self.claude_home / "settings.json").read_bytes()

        with self.assertRaisesRegex(installer.InstallerConflict, "omits previously managed"):
            self._plan(
                codex_homes={"codex-main": self.codex_home},
                claude_homes={},
                rotate_auth_token=True,
            )
        self.assertEqual((self.claude_home / "settings.json").read_bytes(), claude_before)

    def test_mixed_codex_and_claude_homes_share_one_transaction(self) -> None:
        plan = self._plan(codex_homes={"codex-main": self.codex_home}, auth_token="e" * 64)
        self.assertEqual([home["name"] for home in plan.journal["codex_homes"]], ["codex-main"])
        self.assertEqual([home["name"] for home in plan.journal["claude_homes"]], ["claude-user"])
        result = installer.apply_install(plan)
        self.assertTrue(result["ok"])
        self.assertEqual(result["codex_homes"], ["codex-main"])
        self.assertEqual(result["claude_homes"], ["claude-user"])
        self.assertTrue((self.codex_home / "hooks.json").is_file())
        self.assertTrue((self.claude_home / "settings.json").is_file())
        loaded = installer.load_plan(plan.journal_path, plan.plan_digest)
        self.assertEqual(
            [home["name"] for home in loaded.journal["claude_homes"]], ["claude-user"]
        )
        installer.rollback_install(loaded)
        self.assertFalse((self.claude_home / "settings.json").exists())
        self.assertFalse((self.codex_home / "hooks.json").exists())

    def test_subset_idempotent_update_retains_omitted_target_inventory(self) -> None:
        first = self._plan(
            codex_homes={"codex-main": self.codex_home},
            auth_token="4" * 64,
            listen_port=4371,
        )
        installer.apply_install(first)
        inventory_path = self.state / "managed-targets.json"
        inventory_before = inventory_path.read_bytes()
        claude_before = (self.claude_home / "settings.json").read_bytes()

        subset = self._plan(
            codex_homes={"codex-main": self.codex_home},
            claude_homes={},
        )
        result = installer.apply_install(subset)
        self.assertEqual(result["managed_target_count"], 2)
        self.assertEqual(inventory_path.read_bytes(), inventory_before)
        self.assertEqual((self.claude_home / "settings.json").read_bytes(), claude_before)

    def test_explicit_claude_retirement_is_narrow_and_exactly_rollback_safe(self) -> None:
        original_claude = {
            "model": "opus",
            "hooks": {
                "StopFailure": [
                    {"hooks": [{"type": "command", "command": "user-owned-handler"}]}
                ]
            },
            "env": {"EDITOR": "vim"},
        }
        (self.claude_home / "settings.json").write_text(
            json.dumps(original_claude), encoding="utf-8"
        )
        first = self._plan(
            codex_homes={"codex-main": self.codex_home},
            auth_token="5" * 64,
            listen_port=4372,
        )
        installer.apply_install(first)
        settings_path = self.claude_home / "settings.json"
        inventory_path = self.state / "managed-targets.json"
        settings_before_retirement = settings_path.read_bytes()
        inventory_before_retirement = inventory_path.read_bytes()
        mode_before_retirement = settings_path.stat().st_mode & 0o777

        retirement = self._plan(
            codex_homes={},
            claude_homes={},
            retire_claude_homes={"claude-user": self.claude_home},
        )
        result = installer.apply_install(retirement)
        self.assertEqual(result["retired_claude_homes"], ["claude-user"])
        self.assertEqual(result["managed_target_count"], 1)
        retired = self._settings_value()
        self.assertEqual(retired["model"], "opus")
        self.assertEqual(retired["env"], {"EDITOR": "vim"})
        self.assertEqual(
            retired["hooks"]["StopFailure"][0], original_claude["hooks"]["StopFailure"][0]
        )
        for event in installer.CLAUDE_HOOK_EVENTS:
            self.assertFalse(
                any(
                    installer._handler_is_managed(handler)
                    for group in retired["hooks"][event]
                    for handler in group["hooks"]
                )
            )

        installer.rollback_install(retirement)
        self.assertEqual(settings_path.read_bytes(), settings_before_retirement)
        self.assertEqual(inventory_path.read_bytes(), inventory_before_retirement)
        if os.name != "nt":
            self.assertEqual(settings_path.stat().st_mode & 0o777, mode_before_retirement)

        from delivery_efficiency.cli import build_parser

        parsed = build_parser().parse_args(
            [
                "install",
                "plan",
                "--retire-claude-home",
                "claude-user={}".format(self.claude_home),
            ]
        )
        self.assertEqual(parsed.retire_claude_home, ["claude-user={}".format(self.claude_home)])

    def test_binding_change_with_complete_mixed_target_set_succeeds(self) -> None:
        first = self._plan(
            codex_homes={"codex-main": self.codex_home},
            auth_token="3" * 64,
            listen_port=4373,
        )
        installer.apply_install(first)
        rotating = self._plan(
            codex_homes={"codex-main": self.codex_home},
            claude_homes={"claude-user": self.claude_home},
            rotate_auth_token=True,
        )
        result = installer.apply_install(rotating)
        self.assertEqual(result["managed_target_count"], 2)
        self.assertTrue(rotating.journal["receiver"]["managed_binding_change"])
        self.assertIn(rotating.auth_token, (self.codex_home / "config.toml").read_text())
        self.assertIn(rotating.auth_token, (self.claude_home / "settings.json").read_text())

    def test_zero_homes_are_rejected(self) -> None:
        with self.assertRaises(installer.InstallerError):
            installer.plan_install(
                self.source,
                self.state,
                {},
                claude_homes={},
                python_executable=Path(sys.executable).resolve(),
            )

    def test_claude_exec_form_preserves_hostile_argv_on_every_platform(self) -> None:
        python = self.root / "Python home's %!()" / "python.exe"
        state = self.root / "state with 'quotes' & %!()"
        install = state / "installs" / "x"
        handler = installer._claude_hook_handler(python, install, state)
        self.assertEqual(handler["command"], str(python))
        self.assertEqual(
            handler["args"],
            [
                str(install / "recorder.py"),
                "hook",
                "claude",
                "--state-dir",
                str(state),
                "--managed-id",
                installer.MANAGED_ID,
            ],
        )
        self.assertNotIn("powershell", json.dumps(handler).lower())
        self.assertEqual(handler["timeout"], installer.CLAUDE_HOOK_TIMEOUT_SECONDS)
        ordinary = installer._claude_hook_handler(
            python,
            install,
            state,
            "SubagentStart",
        )
        self.assertEqual(ordinary["timeout"], installer.CLAUDE_ORDINARY_HOOK_TIMEOUT_SECONDS)
        self.assertIs(ordinary["async"], True)
        self.assertEqual(ordinary["args"], handler["args"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
