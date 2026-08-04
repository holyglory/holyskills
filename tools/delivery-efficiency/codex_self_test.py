#!/usr/bin/env python3
"""Deterministic privacy and lifecycle tests for the Codex adapters."""

from __future__ import annotations

import copy
from contextlib import redirect_stdout
import io
import json
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
from pathlib import Path


TOOL_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL_ROOT))

from delivery_efficiency.codex import (  # noqa: E402
    CodexExecTranslator,
    MalformedSourceEvent,
    OversizedSourceEvent,
    record_hook,
    translate_hook,
    translate_otlp,
)
from delivery_efficiency import cli as recorder_cli  # noqa: E402
from delivery_efficiency.contract import validate_normalized_observation  # noqa: E402


CANARIES = {
    "prompt": "PROMPT-CANARY-never-store",
    "assistant": "ASSISTANT-CANARY-never-store",
    "transcript": "/private/transcripts/TRANSCRIPT-CANARY.jsonl",
    "cwd": "/secret/CWD-CANARY/repository",
    "command": "printf COMMAND-CANARY-secret",
    "tool_input": "TOOL-INPUT-CANARY-secret",
    "tool_result": "TOOL-RESULT-CANARY-secret",
    "error": "ERROR-CANARY-secret",
    "email": "ACCOUNT-CANARY@example.invalid",
    "file": "/secret/FILE-CANARY.txt",
}
OPAQUE_BINDING = "binding_v1_codex_{}_{}".format("a" * 32, "b" * 32)
TARGET_A = "target_v1_" + "a" * 32
TARGET_B = "target_v1_" + "b" * 32


def observations(emissions):
    return [observation for observation, _ in emissions]


def assert_private(testcase, emissions):
    serialized = json.dumps(emissions, sort_keys=True)
    for canary in CANARIES.values():
        testcase.assertNotIn(canary, serialized)
    for observation, _ in emissions:
        validate_normalized_observation(observation)


def assert_observation_shape(testcase, observation):
    validate_normalized_observation(observation)
    testcase.assertEqual(
        set(observation),
        {
            "runtime",
            "adapter",
            "source_identity",
            "classification",
            "measurement",
            "coverage",
            "event",
            "payload",
        },
    )
    testcase.assertEqual(
        set(observation["source_identity"]),
        {
            "lineage",
            "task",
            "project",
            "revision",
            "session",
            "turn",
            "agent",
            "span",
            "target",
        },
    )
    testcase.assertEqual(
        set(observation["classification"]),
        {
            "phase",
            "phase_provenance",
            "activity_state",
            "activity_provenance",
            "classifier_version",
        },
    )
    testcase.assertEqual(
        set(observation["measurement"]["tokens"]),
        {"input", "cached_input", "output", "reasoning_output", "tool", "other"},
    )
    testcase.assertEqual(
        set(observation["coverage"]),
        {
            "request_receipt",
            "first_activity",
            "tokens",
            "tools",
            "subagents",
            "terminal_delivery",
            "scope",
            "verification",
        },
    )
    testcase.assertEqual(
        set(observation["payload"]),
        {
            "source_event",
            "span_id",
            "parent_span_id",
            "duration_ns",
            "success",
            "tool_category",
            "outcome",
            "task_kind",
            "cause",
            "requirement_id",
            "requirement_status",
            "verification",
            "gap_code",
            "link",
            "correction",
            "task_metadata",
            "evidence",
            "configuration",
        },
    )
    testcase.assertEqual(
        observation["payload"]["link"],
        {"task_id": None, "lineage_id": None, "provenance": "not-applicable"},
    )
    testcase.assertEqual(
        observation["payload"]["correction"],
        {"event_id": None, "provenance": "not-applicable"},
    )
    testcase.assertEqual(
        observation["payload"]["task_metadata"],
        {
            "acceptance_baseline_id": None,
            "acceptance_baseline_provenance": "unknown",
            "approved_scope_change_ids": [],
            "scope_change_provenance": "unknown",
            "task_kind_provenance": "unknown",
            "task_type": "unknown",
            "task_type_provenance": "unknown",
            "scope_size": "unknown",
            "scope_size_provenance": "unknown",
            "method": "unknown",
            "method_provenance": "unknown",
            "classifier_version": "task-v1",
        },
    )
    testcase.assertEqual(
        observation["payload"]["evidence"],
        {"refs": [], "provenance": "unknown"},
    )
    testcase.assertEqual(
        observation["payload"]["configuration"],
        {
            "policy_version": None,
            "policy_provenance": "unknown",
            "model_config_version": None,
            "model_config_provenance": "unknown",
            "runtime_config_version": None,
            "runtime_config_provenance": "unknown",
            "recorder_config_version": None,
            "recorder_config_provenance": "unknown",
        },
    )


class HookTranslatorTests(unittest.TestCase):
    def _run_hook(self, source, *, receiver_error=None, settings=None):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary).resolve()
            stdout = io.StringIO()
            stdin = SimpleNamespace(
                buffer=io.BytesIO(
                    json.dumps(source, separators=(",", ":")).encode("utf-8")
                )
            )
            arguments = SimpleNamespace(
                state_dir=str(state),
                managed_id=recorder_cli.MANAGED_ID,
                runtime="codex",
            )
            runtime_settings = settings or {
                "python_executable": str(state / "runtime with spaces" / "python"),
            }
            receiver = (
                mock.patch.object(
                    recorder_cli, "ensure_receiver", side_effect=receiver_error
                )
                if receiver_error is not None
                else mock.patch.object(
                    recorder_cli,
                    "ensure_receiver",
                    return_value=runtime_settings,
                )
            )
            with (
                mock.patch.object(sys, "stdin", stdin),
                redirect_stdout(stdout),
                receiver,
                mock.patch.object(recorder_cli, "record_local_gap") as record_gap,
                mock.patch("delivery_efficiency.runtime.post_observations"),
                mock.patch(
                    "delivery_efficiency.runtime.request_declaration_binding",
                    return_value=OPAQUE_BINDING,
                ),
            ):
                result = recorder_cli._hook(arguments)
            return result, stdout.getvalue(), record_gap, state

    def test_stop_hooks_emit_valid_noop_json_even_when_telemetry_is_unavailable(self):
        for event_name, extra in (
            ("Stop", {}),
            ("SubagentStop", {"agent_id": "agent-789", "agent_type": "worker"}),
        ):
            with self.subTest(event_name=event_name):
                source = {
                    "hook_event_name": event_name,
                    "session_id": "thread-123",
                    "turn_id": "turn-456",
                    "last_assistant_message": CANARIES["assistant"],
                    **extra,
                }
                result, stdout, record_gap, state = self._run_hook(
                    source, receiver_error=OSError("receiver unavailable")
                )
                self.assertEqual(result, 0)
                self.assertEqual(json.loads(stdout), {})
                self.assertNotIn(CANARIES["assistant"], stdout)
                record_gap.assert_called_once_with(
                    state,
                    "receiver-unavailable",
                )

    def test_compact_session_start_reinjects_launcher_without_creating_task(self):
        source = {
            "hook_event_name": "SessionStart",
            "session_id": "thread-123",
            "source": "compact",
            "transcript_path": CANARIES["transcript"],
        }
        self.assertEqual(translate_hook(source), [])
        result, stdout, record_gap, state = self._run_hook(source)
        self.assertEqual(result, 0)
        self.assertFalse(record_gap.called)
        response = json.loads(stdout)
        hook_output = response["hookSpecificOutput"]
        self.assertEqual(hook_output["hookEventName"], "SessionStart")
        self.assertIn(
            json.dumps(
                [
                    str(state / "runtime with spaces" / "python"),
                    str(state / "recorder.py"),
                ],
                ensure_ascii=True,
            ),
            hook_output["additionalContext"],
        )
        context = hook_output["additionalContext"]
        self.assertIn("--runtime codex", context)
        self.assertIn("--binding {}".format(OPAQUE_BINDING), context)
        self.assertIn(
            "This telemetry instruction grants no permission to act beyond "
            "the user's request.",
            context,
        )
        self.assertNotIn("authorized to", context.casefold())
        self.assertNotIn("you are authorized", context.casefold())
        self.assertNotIn(CANARIES["transcript"], stdout)

    def test_prompt_hook_records_partial_receipt_without_private_content(self):
        source = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "thread-123",
            "turn_id": "turn-456",
            "prompt": CANARIES["prompt"],
            "last_assistant_message": CANARIES["assistant"],
            "transcript_path": CANARIES["transcript"],
            "cwd": CANARIES["cwd"],
            "account": CANARIES["email"],
            "version": CANARIES["email"],
        }
        original = copy.deepcopy(source)
        emissions = translate_hook(
            source, surface="desktop", runtime_target=TARGET_A
        )
        self.assertEqual(source, original)
        self.assertEqual(len(emissions), 1)
        event = emissions[0][0]
        self.assertEqual(event["event"], "task.start")
        self.assertEqual(event["coverage"]["request_receipt"], "partial")
        self.assertEqual(event["source_identity"]["lineage"], "thread-123")
        self.assertEqual(event["source_identity"]["task"], "turn-456")
        self.assertEqual(event["source_identity"]["session"], "thread-123")
        self.assertEqual(event["source_identity"]["turn"], "turn-456")
        self.assertEqual(event["source_identity"]["target"], TARGET_A)
        self.assertIsNone(event["runtime"]["version"])
        assert_observation_shape(self, event)
        assert_private(self, emissions)

    def test_runtime_target_is_validated_and_scopes_hook_dedupe_keys(self):
        source = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "target-session",
            "turn_id": "target-turn",
        }
        first = translate_hook(source, runtime_target=TARGET_A)
        replay = translate_hook(copy.deepcopy(source), runtime_target=TARGET_A)
        other = translate_hook(copy.deepcopy(source), runtime_target=TARGET_B)
        self.assertEqual(first[0][1], replay[0][1])
        self.assertNotEqual(first[0][1], other[0][1])
        self.assertEqual(first[0][0]["source_identity"]["target"], TARGET_A)
        with self.assertRaises(MalformedSourceEvent):
            translate_hook(source, runtime_target="/private/codex-home")

    def test_compaction_and_session_start_never_create_tasks(self):
        compact = {
            "hook_event_name": "SessionStart",
            "session_id": "thread-123",
            "source": "compact",
            "transcript_path": CANARIES["transcript"],
        }
        startup = dict(compact, source="startup")
        self.assertEqual(translate_hook(compact), [])
        self.assertEqual(translate_hook(startup), [])

    def test_stop_is_a_turn_boundary_not_terminal(self):
        source = {
            "hook_event_name": "Stop",
            "session_id": "thread-123",
            "turn_id": "turn-456",
            "last_assistant_message": CANARIES["assistant"],
            "error": CANARIES["error"],
        }
        emissions = translate_hook(source)
        self.assertEqual([item[0]["event"] for item in emissions], ["runtime.turn_stopped"])
        self.assertNotIn("task.terminal", [item[0]["event"] for item in emissions])
        assert_private(self, emissions)

    def test_tool_hooks_are_low_cardinality_and_deduplicate_stably(self):
        source = {
            "hook_event_name": "PreToolUse",
            "session_id": "thread-123",
            "turn_id": "turn-456",
            "tool_use_id": "tool-789",
            "tool_name": "custom-" + CANARIES["tool_input"],
            "tool_input": {
                "command": CANARIES["command"],
                "path": CANARIES["file"],
                "secret": CANARIES["tool_input"],  # public-artifact-guard: allow text-secret
            },
        }
        first = translate_hook(source)
        second = translate_hook(copy.deepcopy(source))
        self.assertEqual([key for _, key in first], [key for _, key in second])
        self.assertEqual(
            [item["event"] for item in observations(first)],
            ["task.first_activity", "span.start"],
        )
        self.assertEqual(first[0][0]["payload"]["tool_category"], "unknown")
        self.assertEqual(first[1][0]["payload"]["tool_category"], "other")
        self.assertIsNone(first[0][0]["source_identity"]["span"])
        self.assertEqual(first[1][0]["source_identity"]["span"], "tool-789")
        assert_private(self, first)

        post = dict(source)
        post.update(
            {
                "hook_event_name": "PostToolUse",
                "tool_response": CANARIES["tool_result"],
                "error": CANARIES["error"],
            }
        )
        post_emissions = translate_hook(post)
        self.assertEqual([item[0]["event"] for item in post_emissions], ["span.end"])
        self.assertIsNone(post_emissions[0][0]["payload"]["success"])
        assert_private(self, post_emissions)

    def test_subagent_hooks_keep_only_runtime_identity_and_category(self):
        start = {
            "hook_event_name": "SubagentStart",
            "session_id": "thread-123",
            "turn_id": "turn-456",
            "agent_id": "agent-789",
            "agent_type": CANARIES["prompt"],
            "prompt": CANARIES["prompt"],
        }
        started = translate_hook(start)
        self.assertEqual(
            [item[0]["event"] for item in started],
            ["task.first_activity", "span.start"],
        )
        self.assertEqual(started[-1][0]["source_identity"]["agent"], "agent-789")
        self.assertEqual(started[-1][0]["source_identity"]["span"], "agent-789")
        self.assertIsNone(started[0][0]["source_identity"]["span"])
        self.assertEqual(started[-1][0]["payload"]["tool_category"], "agent")
        stopped = translate_hook(dict(start, hook_event_name="SubagentStop"))
        self.assertEqual([item[0]["event"] for item in stopped], ["span.end"])
        assert_private(self, started + stopped)

    def test_first_activity_candidate_is_stable_across_tools_and_subagents(self):
        tool_first = translate_hook(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "thread-123",
                "turn_id": "turn-456",
                "tool_use_id": "tool-789",
                "tool_name": "Bash",
            }
        )[0]
        agent_first = translate_hook(
            {
                "hook_event_name": "SubagentStart",
                "session_id": "thread-123",
                "turn_id": "turn-456",
                "agent_id": "agent-789",
            }
        )[0]
        self.assertEqual(tool_first, agent_first)

    def test_session_end_is_advisory_gap(self):
        emissions = translate_hook(
            {
                "hook_event_name": "SessionEnd",
                "session_id": "thread-123",
                "reason": "logout",
            }
        )
        self.assertEqual(emissions[0][0]["event"], "coverage.gap")
        self.assertEqual(
            emissions[0][0]["payload"]["gap_code"], "host-boundary-unavailable"
        )
        assert_private(self, emissions)

    def test_malformed_and_oversized_hook_input_is_rejected(self):
        with self.assertRaises(MalformedSourceEvent):
            translate_hook("[]")
        with self.assertRaises(MalformedSourceEvent):
            translate_hook(
                {
                    "hook_event_name": "Stop",
                    "session_id": "thread-123",
                    "turn_id": "turn id contains spaces",
                }
            )
        with self.assertRaises(OversizedSourceEvent):
            translate_hook(
                json.dumps(
                    {
                        "hook_event_name": "Stop",
                        "session_id": "thread-123",
                        "turn_id": "turn-456",
                        "ignored": "x" * 1_100_000,
                    }
                )
            )

    def test_best_effort_sink_handoff_does_not_raise(self):
        class BrokenSink:
            def record(self, observation, *, source_key):
                raise OSError("storage unavailable")

        count = record_hook(
            {
                "hook_event_name": "Stop",
                "session_id": "thread-123",
                "turn_id": "turn-456",
            },
            BrokenSink(),
        )
        self.assertEqual(count, 0)


class OtlpTranslatorTests(unittest.TestCase):
    def realistic_payload(self):
        return {
            "resourceLogs": [
                {
                    "resource": {
                        "attributes": [
                            {
                                "key": "app.version",
                                "value": {"stringValue": "1.2.3"},
                            },
                            {
                                "key": "originator",
                                "value": {"stringValue": "codex_exec"},
                            },
                            {
                                "key": "user.email",
                                "value": {"stringValue": CANARIES["email"]},
                            },
                        ]
                    },
                    "scopeLogs": [
                        {
                            "scope": {"name": "codex"},
                            "logRecords": [
                                {
                                    "timeUnixNano": "1785250000000000000",
                                    "traceId": "0123456789abcdef0123456789abcdef",
                                    "spanId": "0123456789abcdef",
                                    "body": {
                                        "kvlistValue": {
                                            "values": [
                                                {
                                                    "key": "event.name",
                                                    "value": {
                                                        "stringValue": "codex.sse_event"
                                                    },
                                                },
                                                {
                                                    "key": "event.kind",
                                                    "value": {
                                                        "stringValue": "response.completed"
                                                    },
                                                },
                                            ]
                                        }
                                    },
                                    "attributes": [
                                        {
                                            "key": "conversation.id",
                                            "value": {"stringValue": "thread-otel"},
                                        },
                                        {
                                            "key": "turn.id",
                                            "value": {"stringValue": "turn-otel"},
                                        },
                                        {
                                            "key": "input_token_count",
                                            "value": {"intValue": "100"},
                                        },
                                        {
                                            "key": "cached_input_token_count",
                                            "value": {"intValue": "80"},
                                        },
                                        {
                                            "key": "output_token_count",
                                            "value": {"intValue": "20"},
                                        },
                                        {
                                            "key": "reasoning_token_count",
                                            "value": {"intValue": "0"},
                                        },
                                        {
                                            "key": "tool_token_count",
                                            "value": {"intValue": "7"},
                                        },
                                        {
                                            "key": "user.email",
                                            "value": {"stringValue": CANARIES["email"]},
                                        },
                                        {
                                            "key": "prompt",
                                            "value": {"stringValue": CANARIES["prompt"]},
                                        },
                                    ],
                                },
                                {
                                    "timeUnixNano": "1785250000000000001",
                                    "body": {"stringValue": "codex.user_prompt"},
                                    "attributes": [
                                        {
                                            "key": "prompt",
                                            "value": {"stringValue": CANARIES["prompt"]},
                                        }
                                    ],
                                },
                                {
                                    "timeUnixNano": "1785250000000000002",
                                    "body": {"stringValue": "codex.tool_result"},
                                    "attributes": [
                                        {
                                            "key": "output",
                                            "value": {
                                                "stringValue": CANARIES["tool_result"]
                                            },
                                        }
                                    ],
                                },
                            ],
                        }
                    ],
                }
            ]
        }

    def test_response_completed_preserves_counters_without_synthesizing_first_activity(self):
        payload = self.realistic_payload()
        original = copy.deepcopy(payload)
        first = translate_otlp(payload)
        second = translate_otlp(copy.deepcopy(payload))
        self.assertEqual(payload, original)
        self.assertEqual([key for _, key in first], [key for _, key in second])
        self.assertEqual(
            [item["event"] for item in observations(first)],
            ["usage.observed"],
        )
        usage = observations(first)[-1]
        self.assertEqual(
            usage["measurement"]["tokens"],
            {
                "input": "100",
                "cached_input": "80",
                "output": "20",
                "reasoning_output": "0",
                "tool": "7",
                "other": None,
            },
        )
        self.assertEqual(usage["measurement"]["counter_source"], "provider-native")
        self.assertEqual(usage["coverage"]["tokens"], "complete")
        self.assertEqual(usage["runtime"]["surface"], "cli-exec")
        self.assertEqual(usage["runtime"]["version"], "1.2.3")
        self.assertIsNone(usage["source_identity"]["target"])
        assert_private(self, first)

    def test_non_counter_prompt_and_tool_events_are_ignored(self):
        payload = self.realistic_payload()
        payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"] = payload[
            "resourceLogs"
        ][0]["scopeLogs"][0]["logRecords"][1:]
        self.assertEqual(translate_otlp(payload), [])

    def test_bad_otlp_shape_and_counter_are_rejected(self):
        with self.assertRaises(MalformedSourceEvent):
            translate_otlp({"resourceLogs": {}})
        payload = self.realistic_payload()
        record = payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
        record["attributes"].append(
            {
                "key": "input_token_count",
                "value": {"intValue": "-1"},
            }
        )
        with self.assertRaises(MalformedSourceEvent):
            translate_otlp(payload)


class ExecTranslatorTests(unittest.TestCase):
    def setUp(self):
        self.translator = CodexExecTranslator(
            invocation_id="invocation-123", runtime_version="1.2.3"
        )

    def complete_declaration(self):
        return {
            "outcome": "complete",
            "verification": "verified",
            "task_kind": "primary",
            "task_type": "implementation",
            "cause": "not-applicable",
            "acceptance_baseline_id": "baseline:v1",
            "approved_scope_change_ids": [],
            "scope_size": "small",
            "method": "direct",
            "policy_version": "policy:v1",
            "model_config_version": "model:v1",
            "runtime_config_version": "runtime:v1",
            "recorder_config_version": "recorder:v1",
            "requirements": [
                {
                    "id": "REQ-1",
                    "status": "satisfied",
                    "verification": "verified",
                    "evidence_refs": ["test:REQ-1"],
                }
            ],
        }

    def test_exec_stream_preserves_usage_and_discards_content(self):
        receipt = self.translator.receipt()
        self.assertEqual(receipt[0][0]["event"], "task.start")
        self.assertEqual(receipt[0][0]["coverage"]["request_receipt"], "complete")
        self.assertEqual(self.translator.receipt(), [])

        thread = {
            "type": "thread.started",
            "thread_id": "thread-exec",
            "title": CANARIES["prompt"],
        }
        self.assertEqual(self.translator.translate(thread), [])
        first = self.translator.translate({"type": "turn.started", "prompt": CANARIES["prompt"]})
        self.assertEqual([item[0]["event"] for item in first], ["task.first_activity"])
        self.assertEqual(first[0][0]["source_identity"]["session"], "thread-exec")

        started = self.translator.translate(
            {
                "type": "item.started",
                "item": {
                    "id": "item-1",
                    "type": "command_execution",
                    "command": CANARIES["command"],
                    "cwd": CANARIES["cwd"],
                    "status": "in_progress",
                },
            }
        )
        self.assertEqual([item[0]["event"] for item in started], ["span.start"])
        self.assertEqual(started[0][0]["payload"]["tool_category"], "shell")
        self.assertEqual(started[0][0]["source_identity"]["span"], "item-1")

        completed = self.translator.translate(
            {
                "type": "item.completed",
                "item": {
                    "id": "item-1",
                    "type": "command_execution",
                    "command": CANARIES["command"],
                    "aggregated_output": CANARIES["tool_result"],
                    "error": CANARIES["error"],
                    "status": "completed",
                },
            }
        )
        self.assertEqual([item[0]["event"] for item in completed], ["span.end"])
        self.assertTrue(completed[0][0]["payload"]["success"])

        ignored_message = self.translator.translate(
            {
                "type": "item.completed",
                "item": {
                    "id": "item-2",
                    "type": "agent_message",
                    "text": CANARIES["assistant"],
                },
            }
        )
        self.assertEqual(ignored_message, [])

        turn = self.translator.translate(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 24763,
                    "cached_input_tokens": 24448,
                    "output_tokens": 122,
                    "reasoning_output_tokens": 0,
                },
                "last_message": CANARIES["assistant"],
            }
        )
        self.assertEqual(
            [item[0]["event"] for item in turn],
            ["usage.observed", "runtime.turn_stopped"],
        )
        self.assertNotIn("task.terminal", [item[0]["event"] for item in turn])
        self.assertEqual(
            turn[0][0]["measurement"]["tokens"]["cached_input"], "24448"
        )
        self.assertEqual(
            turn[0][0]["measurement"]["tokens"]["reasoning_output"], "0"
        )
        assert_private(self, receipt + first + started + completed + turn)

    def test_successful_exit_is_not_completion_without_declaration(self):
        self.translator.translate(
            {"type": "thread.started", "thread_id": "thread-exec"}
        )
        emissions = self.translator.process_exit(0)
        self.assertEqual(
            [item[0]["event"] for item in emissions],
            ["runtime.turn_stopped", "coverage.gap"],
        )
        self.assertNotIn("task.terminal", [item[0]["event"] for item in emissions])
        self.assertEqual(
            emissions[-1][0]["payload"]["gap_code"], "host-boundary-unavailable"
        )
        assert_private(self, emissions)

    def test_explicit_complete_declaration_requires_resolved_requirements(self):
        obsolete = self.complete_declaration()
        obsolete["requirements_resolved"] = True
        with self.assertRaises(MalformedSourceEvent):
            self.translator.process_exit(
                0,
                terminal_declaration=obsolete,
            )

        empty = self.complete_declaration()
        empty["requirements"] = []
        with self.assertRaises(MalformedSourceEvent):
            self.translator.process_exit(
                0,
                terminal_declaration=empty,
            )

        unresolved = self.complete_declaration()
        unresolved["requirements"] = [
            {
                "id": "REQ-1",
                "status": "partial",
                "verification": "partially-verified",
                "evidence_refs": ["test:REQ-1"],
            }
        ]
        with self.assertRaises(MalformedSourceEvent):
            self.translator.process_exit(
                0,
                terminal_declaration=unresolved,
            )

        declaration = self.complete_declaration()
        declaration["requirements"].append(
            {
                "id": "REQ-2",
                "status": "removed",
                "verification": "not-applicable",
                "evidence_refs": ["approval:REQ-2"],
                "legacy_evidence": CANARIES["file"],
            }
        )
        declaration["notes"] = CANARIES["prompt"]
        emissions = self.translator.process_exit(
            0,
            terminal_declaration=declaration,
        )
        self.assertEqual(
            [item[0]["event"] for item in emissions],
            [
                "runtime.turn_stopped",
                "requirement.status",
                "requirement.status",
                "task.terminal",
            ],
        )
        requirement_events = [item[0] for item in emissions[1:-1]]
        self.assertEqual(
            [item["payload"]["requirement_id"] for item in requirement_events],
            ["REQ-1", "REQ-2"],
        )
        self.assertEqual(
            [item["payload"]["requirement_status"] for item in requirement_events],
            ["satisfied", "removed"],
        )
        self.assertEqual(
            [item["payload"]["verification"] for item in requirement_events],
            ["verified", "not-applicable"],
        )
        self.assertEqual(
            [item["payload"]["evidence"] for item in requirement_events],
            [
                {"refs": ["test:REQ-1"], "provenance": "agent-declared"},
                {"refs": ["approval:REQ-2"], "provenance": "agent-declared"},
            ],
        )
        for requirement in requirement_events:
            metadata = requirement["payload"]["task_metadata"]
            self.assertIsNone(metadata["acceptance_baseline_id"])
            self.assertEqual(metadata["approved_scope_change_ids"], [])
            self.assertEqual(metadata["task_kind_provenance"], "agent-declared")
            self.assertEqual(metadata["task_type"], "implementation")
            self.assertEqual(metadata["task_type_provenance"], "agent-declared")
            self.assertEqual(metadata["scope_size_provenance"], "agent-declared")
            self.assertEqual(metadata["method_provenance"], "agent-declared")
        terminal = emissions[-1][0]
        self.assertEqual(terminal["payload"]["outcome"], "complete")
        self.assertEqual(terminal["measurement"]["provenance"], "agent-declared")
        self.assertEqual(terminal["coverage"]["scope"], "complete")
        self.assertEqual(
            terminal["payload"]["task_metadata"],
            {
                "acceptance_baseline_id": "baseline:v1",
                "acceptance_baseline_provenance": "agent-declared",
                "approved_scope_change_ids": [],
                "scope_change_provenance": "agent-declared",
                "task_kind_provenance": "agent-declared",
                "task_type": "implementation",
                "task_type_provenance": "agent-declared",
                "scope_size": "small",
                "scope_size_provenance": "agent-declared",
                "method": "direct",
                "method_provenance": "agent-declared",
                "classifier_version": "task-v1",
            },
        )
        self.assertEqual(
            terminal["payload"]["configuration"],
            {
                "policy_version": "policy:v1",
                "policy_provenance": "agent-declared",
                "model_config_version": "model:v1",
                "model_config_provenance": "agent-declared",
                "runtime_config_version": "runtime:v1",
                "runtime_config_provenance": "agent-declared",
                "recorder_config_version": "recorder:v1",
                "recorder_config_provenance": "agent-declared",
            },
        )
        self.assertEqual(
            terminal["payload"]["evidence"],
            {"refs": [], "provenance": "unknown"},
        )
        assert_private(self, emissions)

    def test_complete_requirement_list_rejects_missing_fields_and_duplicates(self):
        invalid_requirements = [
            {"status": "satisfied", "verification": "verified"},
            {"id": "REQ-1", "verification": "verified"},
            {"id": "REQ-1", "status": "satisfied"},
            {
                "id": "REQ-1",
                "status": "satisfied",
                "verification": "not-applicable",
            },
        ]
        for requirement in invalid_requirements:
            with self.subTest(requirement=requirement):
                declaration = self.complete_declaration()
                declaration["requirements"] = [requirement]
                with self.assertRaises(MalformedSourceEvent):
                    self.translator.process_exit(
                        0,
                        terminal_declaration=declaration,
                    )

        duplicate = self.complete_declaration()
        duplicate["requirements"].append(
            {
                "id": "REQ-1",
                "status": "removed",
                "verification": "not-applicable",
                "evidence_refs": ["approval:REQ-1"],
            }
        )
        with self.assertRaises(MalformedSourceEvent):
            self.translator.process_exit(
                0,
                terminal_declaration=duplicate,
            )

    def test_complete_requires_explicit_baseline_scope_and_classifications(self):
        for field in (
            "acceptance_baseline_id",
            "approved_scope_change_ids",
            "task_kind",
            "task_type",
            "scope_size",
            "method",
        ):
            with self.subTest(missing=field):
                declaration = self.complete_declaration()
                del declaration[field]
                with self.assertRaises(MalformedSourceEvent):
                    self.translator.process_exit(
                        0, terminal_declaration=declaration
                    )

        for field, value in (
            ("task_type", "unknown"),
            ("task_type", "not-applicable"),
            ("task_type", "not-a-task-type"),
            ("scope_size", "unknown"),
            ("scope_size", "not-applicable"),
            ("scope_size", "enormous"),
            ("method", "unknown"),
            ("method", "not-applicable"),
            ("method", "manual-ish"),
        ):
            with self.subTest(field=field, value=value):
                declaration = self.complete_declaration()
                declaration[field] = value
                with self.assertRaises(MalformedSourceEvent):
                    self.translator.process_exit(
                        0, terminal_declaration=declaration
                    )

    def test_declared_reference_and_configuration_allowlists_are_strict(self):
        invalid_mutations = (
            ("acceptance_baseline_id", CANARIES["file"]),
            ("approved_scope_change_ids", "scope:one"),
            ("approved_scope_change_ids", [CANARIES["email"]]),
            ("approved_scope_change_ids", ["scope:one", "scope:one"]),
            (
                "approved_scope_change_ids",
                ["scope:{}".format(index) for index in range(33)],
            ),
            ("policy_version", CANARIES["command"]),
            ("model_config_version", None),
            ("runtime_config_version", ""),
            ("recorder_config_version", "version/with/path"),
        )
        for field, value in invalid_mutations:
            with self.subTest(field=field, value=value):
                declaration = self.complete_declaration()
                declaration[field] = value
                with self.assertRaises(MalformedSourceEvent):
                    self.translator.process_exit(
                        0, terminal_declaration=declaration
                    )

        invalid_evidence_lists = (
            None,
            "test:REQ-1",
            [],
            [CANARIES["file"]],
            ["test:one", "test:one"],
            ["test:{}".format(index) for index in range(33)],
        )
        for evidence_refs in invalid_evidence_lists:
            with self.subTest(evidence_refs=evidence_refs):
                declaration = self.complete_declaration()
                declaration["requirements"][0]["evidence_refs"] = evidence_refs
                with self.assertRaises(MalformedSourceEvent):
                    self.translator.process_exit(
                        0, terminal_declaration=declaration
                    )

        missing_evidence = self.complete_declaration()
        del missing_evidence["requirements"][0]["evidence_refs"]
        with self.assertRaises(MalformedSourceEvent):
            self.translator.process_exit(
                0, terminal_declaration=missing_evidence
            )

    def test_complete_allows_missing_unobserved_configuration_versions(self):
        declaration = self.complete_declaration()
        for field in (
            "policy_version",
            "model_config_version",
            "runtime_config_version",
            "recorder_config_version",
        ):
            del declaration[field]
        terminal = CodexExecTranslator("no-config-invocation").process_exit(
            0, terminal_declaration=declaration
        )[-1][0]
        self.assertEqual(
            terminal["payload"]["configuration"],
            {
                "policy_version": None,
                "policy_provenance": "unknown",
                "model_config_version": None,
                "model_config_provenance": "unknown",
                "runtime_config_version": None,
                "runtime_config_provenance": "unknown",
                "recorder_config_version": None,
                "recorder_config_provenance": "unknown",
            },
        )

    def test_incomplete_declaration_keeps_unobserved_metadata_unknown(self):
        emissions = self.translator.process_exit(
            1,
            terminal_declaration={
                "outcome": "incomplete",
                "verification": "unverified",
                "requirements": [
                    {
                        "id": "REQ-1",
                        "status": "blocked",
                        "verification": "unverified",
                    }
                ],
                "notes": CANARIES["prompt"],
            },
        )
        requirement = emissions[-2][0]
        terminal = emissions[-1][0]
        defaults = terminal["payload"]["task_metadata"]
        self.assertIsNone(defaults["acceptance_baseline_id"])
        self.assertEqual(defaults["acceptance_baseline_provenance"], "unknown")
        self.assertEqual(defaults["approved_scope_change_ids"], [])
        self.assertEqual(defaults["scope_change_provenance"], "unknown")
        self.assertEqual(defaults["task_kind_provenance"], "unknown")
        self.assertEqual(defaults["task_type"], "unknown")
        self.assertEqual(defaults["task_type_provenance"], "unknown")
        self.assertEqual(defaults["scope_size"], "unknown")
        self.assertEqual(defaults["scope_size_provenance"], "unknown")
        self.assertEqual(defaults["method"], "unknown")
        self.assertEqual(defaults["method_provenance"], "unknown")
        self.assertEqual(defaults["classifier_version"], "task-v1")
        self.assertEqual(
            requirement["payload"]["evidence"],
            {"refs": [], "provenance": "unknown"},
        )
        self.assertEqual(
            terminal["payload"]["configuration"],
            {
                "policy_version": None,
                "policy_provenance": "unknown",
                "model_config_version": None,
                "model_config_provenance": "unknown",
                "runtime_config_version": None,
                "runtime_config_provenance": "unknown",
                "recorder_config_version": None,
                "recorder_config_provenance": "unknown",
            },
        )
        assert_private(self, emissions)

    def test_declared_metadata_and_evidence_participate_in_source_keys(self):
        def keys_for(declaration):
            emitted = CodexExecTranslator("stable-invocation").process_exit(
                0, terminal_declaration=declaration
            )
            requirement_key = next(
                key for event, key in emitted if event["event"] == "requirement.status"
            )
            terminal_key = next(
                key for event, key in emitted if event["event"] == "task.terminal"
            )
            return requirement_key, terminal_key

        baseline = self.complete_declaration()
        baseline_requirement_key, baseline_terminal_key = keys_for(baseline)

        mutations = {
            "acceptance_baseline_id": "baseline:v2",
            "approved_scope_change_ids": ["scope:approved-1"],
            "task_type": "diagnosis",
            "scope_size": "medium",
            "method": "hybrid",
            "policy_version": "policy:v2",
            "model_config_version": "model:v2",
            "runtime_config_version": "runtime:v2",
            "recorder_config_version": "recorder:v2",
        }
        for field, value in mutations.items():
            with self.subTest(field=field):
                declaration = self.complete_declaration()
                declaration[field] = value
                requirement_key, terminal_key = keys_for(declaration)
                self.assertNotEqual(terminal_key, baseline_terminal_key)
                if field in {"task_type", "scope_size", "method"}:
                    self.assertNotEqual(requirement_key, baseline_requirement_key)

        changed_evidence = self.complete_declaration()
        changed_evidence["requirements"][0]["evidence_refs"] = ["test:REQ-1:v2"]
        requirement_key, terminal_key = keys_for(changed_evidence)
        self.assertNotEqual(requirement_key, baseline_requirement_key)
        self.assertNotEqual(terminal_key, baseline_terminal_key)

    def test_failure_and_interruption_are_runtime_terminal(self):
        turn_failed = self.translator.translate(
            {"type": "turn.failed", "error": {"message": CANARIES["error"]}}
        )
        self.assertEqual(turn_failed[-1][0]["event"], "task.terminal")
        self.assertEqual(turn_failed[-1][0]["payload"]["outcome"], "incomplete")
        self.assertEqual(turn_failed[-1][0]["payload"]["source_event"], "exec_turn")
        same_process_exit = self.translator.process_exit(7)
        self.assertNotIn(
            "task.terminal", [item[0]["event"] for item in same_process_exit]
        )
        failed = CodexExecTranslator("second-invocation").process_exit(7)
        self.assertEqual(failed[-1][0]["event"], "task.terminal")
        self.assertEqual(failed[-1][0]["payload"]["outcome"], "incomplete")
        interrupted = CodexExecTranslator("third-invocation").process_exit(
            130, interrupted=True
        )
        self.assertEqual(interrupted[-1][0]["payload"]["outcome"], "interrupted")
        assert_private(self, turn_failed + same_process_exit + failed + interrupted)

    def test_exec_errors_and_unknown_items_never_retain_payloads(self):
        error = self.translator.translate(
            {"type": "error", "message": CANARIES["error"], "details": CANARIES["prompt"]}
        )
        unknown = self.translator.translate(
            {
                "type": "item.completed",
                "item": {
                    "id": "item-unknown",
                    "type": "future_private_item",
                    "text": CANARIES["assistant"],
                    "path": CANARIES["file"],
                },
            }
        )
        self.assertEqual(error, [])
        self.assertEqual(unknown, [])

    def test_malformed_and_oversized_exec_events_are_rejected(self):
        with self.assertRaises(MalformedSourceEvent):
            self.translator.translate({"type": ["turn.completed"]})
        with self.assertRaises(OversizedSourceEvent):
            self.translator.translate(
                json.dumps({"type": "error", "message": "x" * 1_100_000})
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
