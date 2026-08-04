#!/usr/bin/env python3
"""Deterministic privacy, lifecycle, and core-binding tests for the Claude adapter.

Fixtures mirror the documented Claude Code hook stdin payloads and OTLP/HTTP
JSON log export, including the content-bearing fields a real session delivers
(prompt text, transcript paths, working directories, tool arguments and
results, account attributes).  They are must-catch privacy fixtures: none of
that content may ever reach an observation, source key, or durable state.
"""

from __future__ import annotations

import copy
from contextlib import redirect_stdout
import io
import json
import multiprocessing
import re
import socket
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock
from pathlib import Path


TOOL_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL_ROOT))

from delivery_efficiency import cli as recorder_cli  # noqa: E402
from delivery_efficiency.claude import (  # noqa: E402
    MalformedSourceEvent,
    OversizedSourceEvent,
    record_hook,
    translate_hook,
    translate_otlp,
)
from delivery_efficiency.codex import translate_hook as codex_translate_hook  # noqa: E402
from delivery_efficiency.contract import (  # noqa: E402
    ContractValidationError,
    validate_normalized_observation,
)
from delivery_efficiency.declarations import phase_emission, terminal_emissions  # noqa: E402
from delivery_efficiency.reporting import summarize  # noqa: E402
from delivery_efficiency.storage import Recorder  # noqa: E402


SESSION = "29bafd1a-4bbc-4d9a-b9a4-6d3e3fe1a2b8"
PROMPT_ID = "a17b32e6-2d52-4d72-8d2f-2c01258b19c4"
SECOND_PROMPT_ID = "f8f57db9-8289-44d2-9d2b-9ec3eddb23b7"
CLIENT_REQUEST_ID = "client-request-private-01"
ERROR_REQUEST_ID = "request-private-error-01"
OTLP_TOOL_ID = "toolu_private_otlp_result_1"
OTLP_REJECTED_TOOL_ID = "toolu_private_otlp_rejected_2"
MESSAGE_ID = "message-private-01"
AGENT_ID = "agent-private-777"
OPAQUE_BINDING = "binding_v1_claude_{}_{}".format("a" * 32, "b" * 32)
CANARIES = {
    "prompt": "PROMPT-CANARY-never-store",
    "assistant": "ASSISTANT-CANARY-never-store",
    "transcript": "/private/transcripts/TRANSCRIPT-CANARY.jsonl",
    "cwd": "/private/CWD-CANARY/repository",
    "command": "printf COMMAND-CANARY-value",
    "tool_input": "TOOL-INPUT-CANARY-value",
    "tool_result": "TOOL-RESULT-CANARY-value",
    "error": "ERROR-CANARY-value",
    "email": "ACCOUNT-CANARY@example.invalid",
    "file": "/private/FILE-CANARY.txt",
    "account": "ACCOUNT-UUID-CANARY",
    "organization": "ORGANIZATION-CANARY",
    "model": "MODEL-NAME-CANARY",
    "notification": "NOTIFICATION-CANARY-text",
    "assistant_response": "ASSISTANT-RESPONSE-CANARY-never-store",
    "error_details": "ERROR-DETAILS-CANARY-never-store",
    "raw_body": "RAW-BODY-CANARY-never-store",
    "tool_parameters": "TOOL-PARAMETERS-CANARY-never-store",
    "background_description": "BACKGROUND-DESCRIPTION-CANARY-never-store",
    "background_command": "BACKGROUND-COMMAND-CANARY-never-store",
    "cron_prompt": "CRON-PROMPT-CANARY-never-store",
    "transcript_delta": "TRANSCRIPT-DELTA-CANARY-never-store",
    "agent_name": "AGENT-NAME-CANARY-never-store",
}


def observations(emissions):
    return [observation for observation, _ in emissions]


def assert_private(testcase, emissions):
    serialized = json.dumps(emissions, sort_keys=True)
    for canary in CANARIES.values():
        testcase.assertNotIn(canary, serialized)
    for observation, _ in emissions:
        validate_normalized_observation(observation)
        testcase.assertEqual(observation["runtime"]["family"], "claude")
        testcase.assertEqual(observation["adapter"]["name"], "claude-runtime")


def hook_payload(event_name, **extra):
    """A realistic Claude Code hook stdin payload with content canaries."""

    payload = {
        "session_id": SESSION,
        "transcript_path": CANARIES["transcript"],
        "cwd": CANARIES["cwd"],
        "permission_mode": "acceptEdits",
        "hook_event_name": event_name,
    }
    if event_name != "SessionStart" and "prompt_id" not in extra:
        payload["prompt_id"] = PROMPT_ID
    payload.update(extra)
    return payload


class HookTranslatorTests(unittest.TestCase):
    def test_session_start_variants_and_untranslated_events_emit_nothing(self):
        for source in ("startup", "resume", "clear", "compact"):
            self.assertEqual(
                translate_hook(hook_payload("SessionStart", source=source)), []
            )
        self.assertEqual(
            translate_hook(
                hook_payload(
                    "PreCompact",
                    trigger="auto",
                    custom_instructions=CANARIES["prompt"],
                )
            ),
            [],
        )
        self.assertEqual(
            translate_hook(
                hook_payload("Notification", message=CANARIES["notification"])
            ),
            [],
        )

    def test_prompt_submit_records_exact_prompt_identity_without_content(self):
        source = hook_payload(
            "UserPromptSubmit",
            prompt=CANARIES["prompt"],
        )
        original = copy.deepcopy(source)
        emissions = translate_hook(source, surface="cli-interactive")
        self.assertEqual(source, original)
        self.assertEqual(len(emissions), 1)
        event, key = emissions[0]
        self.assertEqual(event["event"], "task.start")
        self.assertEqual(event["coverage"]["request_receipt"], "partial")
        self.assertEqual(event["payload"]["source_event"], "prompt_submit")
        self.assertEqual(event["payload"]["task_kind"], "primary")
        self.assertEqual(event["source_identity"]["lineage"], SESSION)
        self.assertEqual(event["source_identity"]["session"], SESSION)
        self.assertIsNone(event["source_identity"]["target"])
        self.assertIn(PROMPT_ID, event["source_identity"]["task"])
        self.assertEqual(
            event["source_identity"]["turn"], event["source_identity"]["task"]
        )
        # The key is stable so a duplicate delivery cannot mint a second task.
        again = translate_hook(copy.deepcopy(source), surface="cli-interactive")
        self.assertEqual(key, again[0][1])
        assert_private(self, emissions)

        legacy = translate_hook(
            hook_payload(
                "UserPromptSubmit",
                prompt=CANARIES["prompt"],
                prompt_id=None,
            )
        )[0][0]
        self.assertIsNone(legacy["source_identity"]["task"])
        self.assertIsNone(legacy["source_identity"]["turn"])


    def test_tool_hooks_use_host_correlation_and_low_cardinality_categories(self):
        source = hook_payload(
            "PreToolUse",
            tool_name="Bash",
            tool_use_id="toolu_01AbCdEfGh",
            tool_input={
                "command": CANARIES["command"],
                "description": CANARIES["tool_input"],
                "background_command": CANARIES["background_command"],
            },
        )
        first = translate_hook(source)
        second = translate_hook(copy.deepcopy(source))
        self.assertEqual(
            [item["event"] for item in observations(first)],
            ["task.first_activity", "span.start"],
        )
        self.assertEqual([key for _, key in first], [key for _, key in second])
        self.assertEqual(first[0][0]["payload"]["tool_category"], "unknown")
        self.assertIsNone(first[0][0]["source_identity"]["span"])
        self.assertEqual(first[1][0]["payload"]["tool_category"], "shell")
        self.assertEqual(first[1][0]["source_identity"]["span"], "toolu_01AbCdEfGh")
        self.assertEqual(
            first[1][0]["classification"],
            {
                "phase": "unattributed",
                "phase_provenance": "unknown",
                "activity_state": "unattributed",
                "activity_provenance": "unknown",
                "classifier_version": "claude-v1",
            },
        )
        assert_private(self, first)

        post = dict(source)
        post.update(
            {
                "hook_event_name": "PostToolUse",
                "tool_response": {
                    "stdout": CANARIES["tool_result"],
                    "stderr": CANARIES["error"],
                },
                "duration_ms": 875,
            }
        )
        post_emissions = translate_hook(post)
        self.assertEqual(
            [item["event"] for item in observations(post_emissions)], ["span.end"]
        )
        self.assertTrue(post_emissions[0][0]["payload"]["success"])
        self.assertEqual(
            post_emissions[0][0]["payload"]["duration_ns"], "875000000"
        )
        self.assertEqual(
            post_emissions[0][0]["classification"]["activity_state"], "tool-active"
        )
        self.assertEqual(
            post_emissions[0][0]["classification"]["activity_provenance"],
            "runtime-observed",
        )
        assert_private(self, post_emissions)

        failed = translate_hook(
            hook_payload(
                "PostToolUseFailure",
                tool_name="Bash",
                tool_use_id="toolu_01AbCdEfGh",
                tool_input={"command": CANARIES["command"]},
                error=CANARIES["error"],
                error_details=CANARIES["error_details"],
                is_interrupt=False,
                duration_ms="912",
            )
        )
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0][0]["event"], "span.end")
        self.assertEqual(failed[0][0]["payload"]["source_event"], "post_tool_failure")
        self.assertFalse(failed[0][0]["payload"]["success"])
        self.assertEqual(failed[0][0]["payload"]["duration_ns"], "912000000")
        assert_private(self, failed)

    def test_hook_durations_reject_non_authoritative_values(self):
        for value in (-1, 1.25, True, "01", "1" * 25, "not-a-duration"):
            with self.subTest(duration_ms=value):
                with self.assertRaises(MalformedSourceEvent):
                    translate_hook(
                        hook_payload(
                            "PostToolUse",
                            tool_name="Read",
                            tool_use_id="toolu_duration",
                            duration_ms=value,
                        )
                    )
        zero = translate_hook(
            hook_payload(
                "PostToolUseFailure",
                tool_name="Read",
                tool_use_id="toolu_duration",
                duration_ms=0,
                error=CANARIES["error"],
            )
        )
        self.assertEqual(zero[0][0]["payload"]["duration_ns"], "0")

    def test_tool_categories_map_known_claude_tools(self):
        expectations = {
            "Bash": "shell",
            "Edit": "patch",
            "Write": "patch",
            "NotebookEdit": "patch",
            "mcp__coordinator__inventory": "mcp",
            "WebSearch": "web",
            "WebFetch": "web",
            "Task": "agent",
            "Read": "local",
            "Grep": "local",
            "Glob": "local",
            "TodoWrite": "local",
            "Skill": "other",
            "custom-" + CANARIES["tool_input"]: "other",
        }
        for tool_name, category in expectations.items():
            emissions = translate_hook(
                hook_payload(
                    "PreToolUse",
                    tool_name=tool_name,
                    tool_use_id="toolu_02",
                    tool_input={"value": CANARIES["tool_input"]},
                )
            )
            self.assertEqual(
                emissions[-1][0]["payload"]["tool_category"], category, tool_name
            )

    def test_tool_hook_without_correlation_id_records_only_first_activity(self):
        source = hook_payload(
            "PreToolUse",
            tool_name="Bash",
            tool_input={"command": CANARIES["command"]},
        )
        emissions = translate_hook(source)
        self.assertEqual(
            [item["event"] for item in observations(emissions)],
            ["task.first_activity"],
        )
        post = translate_hook(
            hook_payload(
                "PostToolUse",
                tool_name="Bash",
                tool_input={"command": CANARIES["command"]},
                tool_response=CANARIES["tool_result"],
            )
        )
        self.assertEqual(post, [])
        assert_private(self, emissions)

    def test_subagent_hooks_translate_with_and_without_agent_identity(self):
        start = hook_payload(
            "SubagentStart",
            agent_id=AGENT_ID,
            agent_type="general-purpose",
            prompt=CANARIES["prompt"],
            transcript_delta=CANARIES["transcript_delta"],
        )
        started = translate_hook(start)
        self.assertEqual(
            [item["event"] for item in observations(started)],
            ["task.first_activity", "coverage.gap"],
        )
        self.assertEqual(started[-1][0]["source_identity"]["agent"], AGENT_ID)
        self.assertIsNone(started[-1][0]["source_identity"]["span"])
        self.assertEqual(started[-1][0]["payload"]["tool_category"], "agent")
        self.assertEqual(
            started[-1][0]["classification"]["activity_state"], "unattributed"
        )
        self.assertEqual(
            started[-1][0]["classification"]["activity_provenance"], "unknown"
        )
        stopped = translate_hook(
            hook_payload(
                "SubagentStop",
                agent_id=AGENT_ID,
                stop_hook_active=False,
                last_assistant_message=CANARIES["assistant"],
            )
        )
        self.assertEqual(
            [item["event"] for item in observations(stopped)], ["coverage.gap"]
        )
        retry = translate_hook(
            hook_payload(
                "SubagentStop",
                agent_id=AGENT_ID,
                stop_hook_active=True,
                last_assistant_message=CANARIES["assistant"],
            )
        )
        self.assertNotEqual(stopped[0][1], retry[0][1])
        self.assertEqual(
            stopped[0][0]["classification"]["activity_state"], "unattributed"
        )
        anonymous_stop = translate_hook(
            hook_payload("SubagentStop", stop_hook_active=False)
        )
        self.assertEqual(
            [item["event"] for item in observations(anonymous_stop)],
            ["coverage.gap"],
        )
        assert_private(self, started + stopped + anonymous_stop)

    def test_stop_is_an_attempt_and_stop_failure_is_a_turn_boundary(self):
        source = hook_payload(
            "Stop",
            stop_hook_active=False,
            last_assistant_message=CANARIES["assistant"],
        )
        first = translate_hook(source)
        second = translate_hook(copy.deepcopy(source))
        self.assertEqual(
            [item["event"] for item in observations(first)], ["coverage.gap"]
        )
        self.assertEqual(
            first[0][0]["payload"]["gap_code"], "host-boundary-unavailable"
        )
        self.assertNotIn(
            "task.terminal", [item["event"] for item in observations(first)]
        )
        # Peer Stop hooks run in parallel and may block a stop, so repeated
        # invocations for one prompt are distinct partial boundaries.
        self.assertNotEqual(first[0][1], second[0][1])

        legacy = hook_payload("Stop", stop_hook_active=False, prompt_id=None)
        legacy_first = translate_hook(legacy)
        legacy_second = translate_hook(copy.deepcopy(legacy))
        self.assertNotEqual(legacy_first[0][1], legacy_second[0][1])
        failure = hook_payload(
            "StopFailure",
            error=CANARIES["error"],
            error_details=CANARIES["error_details"],
        )
        failed_once = translate_hook(failure)
        failed_replay = translate_hook(copy.deepcopy(failure))
        self.assertEqual(failed_once[0][1], failed_replay[0][1])
        self.assertEqual(failed_once[0][0]["event"], "runtime.turn_stopped")
        self.assertEqual(failed_once[0][0]["payload"]["source_event"], "turn_failure")
        self.assertFalse(failed_once[0][0]["payload"]["success"])
        self.assertNotIn(
            "task.terminal", [item["event"] for item in observations(failed_once)]
        )
        assert_private(self, first + second + failed_once)

    def test_message_display_is_first_activity_only_not_delivery(self):
        emissions = translate_hook(
            hook_payload(
                "MessageDisplay",
                message_id=MESSAGE_ID,
                turn_id="turn-private-message-1",
                message={"content": CANARIES["assistant_response"]},
                delta=CANARIES["transcript_delta"],
                final=True,
            )
        )
        self.assertEqual([item["event"] for item in observations(emissions)], ["task.first_activity"])
        event = emissions[0][0]
        self.assertEqual(event["payload"]["source_event"], "message_display")
        self.assertEqual(event["classification"]["activity_state"], "model-active")
        self.assertEqual(event["classification"]["activity_provenance"], "runtime-observed")
        self.assertNotIn("task.terminal", [item["event"] for item in observations(emissions)])
        self.assertNotIn("runtime.turn_stopped", [item["event"] for item in observations(emissions)])
        self.assertNotIn(MESSAGE_ID, json.dumps(emissions, sort_keys=True))
        assert_private(self, emissions)

    def test_session_end_is_advisory_gap(self):
        emissions = translate_hook(hook_payload("SessionEnd", reason="logout"))
        self.assertEqual(emissions[0][0]["event"], "coverage.gap")
        self.assertEqual(
            emissions[0][0]["payload"]["gap_code"], "host-boundary-unavailable"
        )
        self.assertEqual(
            emissions[0][1],
            translate_hook(hook_payload("SessionEnd", reason="logout"))[0][1],
        )
        assert_private(self, emissions)

    def test_malformed_and_oversized_hook_input_is_rejected(self):
        with self.assertRaises(MalformedSourceEvent):
            translate_hook("[]")
        with self.assertRaises(MalformedSourceEvent):
            translate_hook(hook_payload("UserPromptSubmit", session_id=None))
        with self.assertRaises(MalformedSourceEvent):
            translate_hook(
                hook_payload("Stop", session_id="session id contains spaces")
            )
        with self.assertRaises(MalformedSourceEvent):
            translate_hook(hook_payload("PermissionRequest"))
        with self.assertRaises(MalformedSourceEvent):
            translate_hook(
                hook_payload("Stop", prompt_id="malformed-prompt-correlation")
            )
        with self.assertRaises(MalformedSourceEvent):
            translate_hook(
                hook_payload("Stop"), event_name="UserPromptSubmit"
            )
        with self.assertRaises(OversizedSourceEvent):
            translate_hook(
                json.dumps(hook_payload("Stop", ignored="x" * 1_100_000))
            )

    def test_best_effort_sink_handoff_does_not_raise(self):
        class BrokenSink:
            def record(self, observation, *, source_key):
                raise OSError("storage unavailable")

        self.assertEqual(
            record_hook(hook_payload("Stop", stop_hook_active=False), BrokenSink()),
            0,
        )
        self.assertEqual(record_hook("{", BrokenSink()), 0)


def realistic_otlp_payload():
    """A realistic Claude Code OTLP/HTTP JSON logs export batch."""

    def attribute(key, value):
        return {"key": key, "value": value}

    api_request = {
        "timeUnixNano": "1785250000000000000",
        "observedTimeUnixNano": "1785250000000000001",
        "traceId": "0123456789abcdef0123456789abcdef",
        "spanId": "0123456789abcdef",
        "body": {"stringValue": "claude_code.api_request"},
        "attributes": [
            attribute("event.name", {"stringValue": "api_request"}),
            attribute("event.timestamp", {"stringValue": "2026-07-28T17:00:00.000Z"}),
            attribute("session.id", {"stringValue": SESSION}),
            attribute("prompt.id", {"stringValue": PROMPT_ID}),
            attribute("model", {"stringValue": CANARIES["model"]}),
            attribute("cost_usd", {"doubleValue": 0.42}),
            attribute("duration_ms", {"intValue": "5210"}),
            attribute("client_request_id", {"stringValue": CLIENT_REQUEST_ID}),
            attribute("input_tokens", {"intValue": "449"}),
            attribute("output_tokens", {"intValue": "1218"}),
            attribute("cache_read_tokens", {"intValue": "51072"}),
            attribute("cache_creation_tokens", {"intValue": "6021"}),
            attribute("user.id", {"stringValue": CANARIES["account"]}),
            attribute("user.email", {"stringValue": CANARIES["email"]}),
            attribute("user.account_uuid", {"stringValue": CANARIES["account"]}),
            attribute("organization.id", {"stringValue": CANARIES["organization"]}),
            attribute("terminal.type", {"stringValue": "iTerm.app"}),
        ],
    }
    user_prompt = {
        "timeUnixNano": "1785250000000000002",
        "body": {"stringValue": "claude_code.user_prompt"},
        "attributes": [
            attribute("event.name", {"stringValue": "user_prompt"}),
            attribute("session.id", {"stringValue": SESSION}),
            attribute("prompt.id", {"stringValue": PROMPT_ID}),
            attribute("prompt_length", {"intValue": "27"}),
            attribute("prompt", {"stringValue": CANARIES["cron_prompt"]}),
        ],
    }
    tool_result = {
        "timeUnixNano": "1785250000000000003",
        "body": {"stringValue": "claude_code.tool_result"},
        "attributes": [
            attribute("event.name", {"stringValue": "tool_result"}),
            attribute("session.id", {"stringValue": SESSION}),
            attribute("prompt.id", {"stringValue": PROMPT_ID}),
            attribute("tool_name", {"stringValue": "Bash"}),
            attribute("tool_use_id", {"stringValue": OTLP_TOOL_ID}),
            attribute("agent.name", {"stringValue": CANARIES["agent_name"]}),
            attribute("success", {"stringValue": "true"}),
            attribute("duration_ms", {"intValue": "812"}),
            attribute("tool_parameters", {"stringValue": CANARIES["tool_parameters"]}),
            attribute("tool_result", {"stringValue": CANARIES["tool_result"]}),
            attribute("error", {"stringValue": CANARIES["error"]}),
        ],
    }
    tool_decision = {
        "timeUnixNano": "1785250000000000004",
        "body": {"stringValue": "claude_code.tool_decision"},
        "attributes": [
            attribute("event.name", {"stringValue": "tool_decision"}),
            attribute("session.id", {"stringValue": SESSION}),
            attribute("prompt.id", {"stringValue": PROMPT_ID}),
            attribute("tool_name", {"stringValue": "Edit"}),
            attribute("tool_use_id", {"stringValue": OTLP_REJECTED_TOOL_ID}),
            attribute("decision", {"stringValue": "reject"}),
            attribute("tool_parameters", {"stringValue": CANARIES["tool_parameters"]}),
        ],
    }
    api_error = {
        "timeUnixNano": "1785250000000000005",
        "body": {"stringValue": "claude_code.api_error"},
        "attributes": [
            attribute("event.name", {"stringValue": "api_error"}),
            attribute("session.id", {"stringValue": SESSION}),
            attribute("prompt.id", {"stringValue": PROMPT_ID}),
            attribute("duration_ms", {"intValue": "133"}),
            attribute("client_request_id", {"stringValue": CLIENT_REQUEST_ID}),
            attribute("request_id", {"stringValue": ERROR_REQUEST_ID}),
            attribute("error", {"stringValue": CANARIES["error"]}),
            attribute("error_details", {"stringValue": CANARIES["error_details"]}),
        ],
    }
    assistant_response = {
        "timeUnixNano": "1785250000000000006",
        "body": {
            "kvlistValue": {
                "values": [
                    attribute("event.name", {"stringValue": "assistant_response"}),
                    attribute("content", {"stringValue": CANARIES["assistant_response"]}),
                    attribute("body", {"stringValue": CANARIES["raw_body"]}),
                ]
            }
        },
        "attributes": [
            attribute("session.id", {"stringValue": SESSION}),
            attribute("prompt.id", {"stringValue": PROMPT_ID}),
            attribute("message", {"stringValue": CANARIES["assistant_response"]}),
        ],
    }
    return {
        "resourceLogs": [
            {
                "resource": {
                    "attributes": [
                        attribute("service.name", {"stringValue": "claude-code"}),
                        attribute("service.version", {"stringValue": "2.1.220"}),
                        attribute("app.entrypoint", {"stringValue": "claude-vscode"}),
                        attribute("user.email", {"stringValue": CANARIES["email"]}),
                    ]
                },
                "scopeLogs": [
                    {
                        "scope": {"name": "com.anthropic.claude_code.events"},
                        "logRecords": [
                            api_request,
                            user_prompt,
                            tool_result,
                            tool_decision,
                            api_error,
                            assistant_response,
                        ],
                    }
                ],
            }
        ]
    }


def with_otlp_prompt(payload, prompt_id):
    """Return a fixture copy with every documented prompt.id replaced."""

    result = copy.deepcopy(payload)
    records = result["resourceLogs"][0]["scopeLogs"][0]["logRecords"]
    for record in records:
        for attribute in record.get("attributes", []):
            if attribute.get("key") == "prompt.id":
                attribute["value"] = {"stringValue": prompt_id}
    return result


class OtlpTranslatorTests(unittest.TestCase):
    def test_api_request_preserves_native_duration_counters_and_surface(self):
        payload = realistic_otlp_payload()
        records = payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"]
        payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"] = records[:2]
        original = copy.deepcopy(payload)
        first = translate_otlp(payload)
        second = translate_otlp(copy.deepcopy(payload))
        self.assertEqual(payload, original)
        self.assertEqual([key for _, key in first], [key for _, key in second])
        self.assertEqual(
            [item["event"] for item in observations(first)],
            ["task.start", "task.first_activity", "span.end", "usage.observed"],
        )
        api_span = next(
            item for item in observations(first) if item["event"] == "span.end"
        )
        self.assertEqual(api_span["payload"]["source_event"], "otel_api")
        self.assertEqual(api_span["payload"]["duration_ns"], "5210000000")
        self.assertTrue(api_span["payload"]["success"])
        self.assertEqual(api_span["classification"]["activity_state"], "unattributed")
        self.assertEqual(
            api_span["classification"]["activity_provenance"], "unknown"
        )
        usage = next(
            item for item in observations(first) if item["event"] == "usage.observed"
        )
        self.assertEqual(
            usage["measurement"]["tokens"],
            {
                "input": "449",
                "cached_input": "51072",
                "output": "1218",
                "reasoning_output": None,
                "tool": None,
                "other": "6021",
            },
        )
        self.assertEqual(usage["measurement"]["counter_source"], "runtime-native")
        self.assertEqual(usage["coverage"]["tokens"], "complete")
        self.assertEqual(usage["payload"]["source_event"], "otel_api")
        self.assertEqual(usage["source_identity"]["session"], SESSION)
        self.assertIsNone(usage["source_identity"]["target"])
        self.assertIsNone(usage["source_identity"]["task"])
        self.assertEqual(usage["source_identity"]["turn"], PROMPT_ID)
        self.assertEqual(usage["runtime"]["version"], "2.1.220")
        self.assertEqual(usage["runtime"]["surface"], "ide")
        assert_private(self, first)

    def test_tool_result_rejection_and_api_error_use_native_outcomes(self):
        payload = realistic_otlp_payload()
        records = payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"]
        payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"] = records[2:]
        emissions = translate_otlp(payload)
        self.assertEqual(
            [item["event"] for item in observations(emissions)],
            [
                "task.first_activity",
                "span.end",
                "task.first_activity",
                "span.end",
                "task.first_activity",
                "span.end",
            ],
        )
        spans = [
            item for item in observations(emissions) if item["event"] == "span.end"
        ]
        self.assertEqual(
            [item["payload"]["source_event"] for item in spans],
            ["otel_tool", "otel_tool_decision", "otel_api_error"],
        )
        self.assertEqual(
            [item["payload"]["duration_ns"] for item in spans],
            ["812000000", None, "133000000"],
        )
        self.assertEqual(
            [item["payload"]["success"] for item in spans], [True, False, False]
        )
        self.assertEqual(
            [item["payload"]["tool_category"] for item in spans],
            ["shell", "patch", "not-applicable"],
        )
        self.assertEqual(spans[0]["classification"]["activity_state"], "tool-active")
        self.assertEqual(
            spans[0]["classification"]["activity_provenance"], "runtime-observed"
        )
        self.assertEqual(spans[1]["classification"]["activity_state"], "unattributed")
        self.assertEqual(spans[1]["classification"]["activity_provenance"], "unknown")
        self.assertEqual(spans[2]["classification"]["activity_state"], "unattributed")
        self.assertEqual(spans[0]["source_identity"]["agent"], "delegated")
        self.assertNotIn(CANARIES["agent_name"], json.dumps(emissions, sort_keys=True))
        self.assertTrue(all(item["source_identity"]["task"] is None for item in spans))
        self.assertTrue(
            all(item["source_identity"]["turn"] == PROMPT_ID for item in spans)
        )
        assert_private(self, emissions)

    def test_accepted_tool_decision_is_not_counted_as_executed_tool_time(self):
        payload = realistic_otlp_payload()
        record = payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"][3]
        for attribute in record["attributes"]:
            if attribute["key"] == "decision":
                attribute["value"] = {"stringValue": "accept"}
        payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"] = [record]
        self.assertEqual(translate_otlp(payload), [])

    def test_hook_fallback_and_otlp_share_the_native_tool_span_identity(self):
        hook_span = translate_hook(
            hook_payload(
                "PostToolUse",
                tool_name="Bash",
                tool_use_id=OTLP_TOOL_ID,
                duration_ms=812,
                tool_response=CANARIES["tool_result"],
            )
        )[0][0]
        payload = realistic_otlp_payload()
        record = payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"][2]
        payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"] = [record]
        otlp_span = next(
            item
            for item in observations(translate_otlp(payload))
            if item["event"] == "span.end"
        )
        self.assertEqual(
            hook_span["source_identity"]["span"],
            otlp_span["source_identity"]["span"],
        )
        self.assertEqual(
            hook_span["payload"]["duration_ns"], otlp_span["payload"]["duration_ns"]
        )
        self.assertEqual(hook_span["payload"]["success"], otlp_span["payload"]["success"])
        self.assertEqual(
            hook_span["classification"]["activity_state"],
            otlp_span["classification"]["activity_state"],
        )
        assert_private(self, [(hook_span, "content-free-test-key")])
        assert_private(self, [(otlp_span, "content-free-test-key")])

    def test_partial_counters_and_string_or_float_encodings_are_preserved(self):
        payload = realistic_otlp_payload()
        record = payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
        record["attributes"] = [
            item
            for item in record["attributes"]
            if item["key"] not in {"cache_read_tokens", "cache_creation_tokens"}
        ] + [
            {"key": "cache_read_tokens", "value": {"stringValue": "51072"}},
        ]
        usage = next(
            item
            for item in observations(translate_otlp(payload))
            if item["event"] == "usage.observed"
        )
        self.assertEqual(usage["coverage"]["tokens"], "partial")
        self.assertEqual(usage["measurement"]["tokens"]["cached_input"], "51072")
        self.assertIsNone(usage["measurement"]["tokens"]["other"])

        float_payload = realistic_otlp_payload()
        float_record = float_payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
        for item in float_record["attributes"]:
            if item["key"] == "input_tokens":
                item["value"] = {"doubleValue": 449.0}
        usage = next(
            item
            for item in observations(translate_otlp(float_payload))
            if item["event"] == "usage.observed"
        )
        self.assertEqual(usage["measurement"]["tokens"]["input"], "449")

    def test_user_prompt_is_a_content_free_correlated_task_boundary(self):
        payload = realistic_otlp_payload()
        record = payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"][1]
        payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"] = [record]
        emissions = translate_otlp(payload)
        self.assertEqual(
            [item["event"] for item in observations(emissions)], ["task.start"]
        )
        start = observations(emissions)[0]
        self.assertIn(PROMPT_ID, start["source_identity"]["task"])
        assert_private(self, emissions)

    def test_missing_or_malformed_otlp_prompt_id_keeps_usage_session_scoped(self):
        for replacement in (None, "not-a-prompt-uuid"):
            with self.subTest(prompt_id=replacement):
                payload = realistic_otlp_payload()
                record = payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
                payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"] = [record]
                for attribute in record["attributes"]:
                    if attribute["key"] == "prompt.id":
                        attribute["value"] = (
                            {"stringValue": replacement}
                            if replacement is not None
                            else {}
                        )
                translated = translate_otlp(payload)
                self.assertEqual(
                    [item["event"] for item in observations(translated)],
                    ["usage.observed"],
                )
                usage = observations(translated)[0]
                self.assertIsNotNone(usage["source_identity"]["session"])
                self.assertIsNone(usage["source_identity"]["task"])
                self.assertIsNone(usage["source_identity"]["turn"])

    def test_bad_shapes_counters_timestamps_and_durations_are_rejected(self):
        with self.assertRaises(MalformedSourceEvent):
            translate_otlp({"resourceLogs": {}})
        negative = realistic_otlp_payload()
        record = negative["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
        record["attributes"].append(
            {"key": "input_tokens", "value": {"intValue": "-1"}}
        )
        with self.assertRaises(MalformedSourceEvent):
            translate_otlp(negative)
        fractional = realistic_otlp_payload()
        record = fractional["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
        for item in record["attributes"]:
            if item["key"] == "output_tokens":
                item["value"] = {"doubleValue": 12.5}
        with self.assertRaises(MalformedSourceEvent):
            translate_otlp(fractional)
        missing_time = realistic_otlp_payload()
        record = missing_time["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
        record["timeUnixNano"] = None
        record["observedTimeUnixNano"] = "not-a-number"
        with self.assertRaises(MalformedSourceEvent):
            translate_otlp(missing_time)

        for value in (-1, 1.5, True, "01", "1" * 25):
            with self.subTest(duration_ms=value):
                bad_duration = realistic_otlp_payload()
                api = bad_duration["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
                bad_duration["resourceLogs"][0]["scopeLogs"][0]["logRecords"] = [api]
                for attribute in api["attributes"]:
                    if attribute["key"] == "duration_ms":
                        attribute["value"] = {"stringValue": str(value)}
                with self.assertRaises(MalformedSourceEvent):
                    translate_otlp(bad_duration)


class SessionTaskBindingTests(unittest.TestCase):
    """Claude prompt correlation is exact, with a legacy core fallback."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="delivery-claude-binding-")
        self.state = Path(self.temporary.name).resolve() / "state"
        self.recorder = Recorder(self.state)

    def tearDown(self):
        self.recorder.close()
        self.temporary.cleanup()

    def record_all(self, emissions):
        return [
            self.recorder.record(observation, source_key=key)
            for observation, key in emissions
        ]

    def record_event(self, emissions, event_name):
        result = None
        for observation, key in emissions:
            recorded = self.recorder.record(observation, source_key=key)
            if observation["event"] == event_name:
                result = recorded
        self.assertIsNotNone(result)
        return result

    def ledger_events(self):
        raw = (self.state / "EfficiencyLedger.jsonl").read_bytes()
        return [json.loads(line) for line in raw.splitlines()]

    def assert_not_in_state(self, *private_values):
        for child in self.state.rglob("*"):
            if not child.is_file():
                continue
            content = child.read_bytes()
            for value in private_values:
                self.assertNotIn(
                    value.encode("utf-8"),
                    content,
                    "private source value reached durable storage",
                )

    def prompt(self, prompt_id=PROMPT_ID):
        return translate_hook(
            hook_payload(
                "UserPromptSubmit",
                prompt=CANARIES["prompt"],
                prompt_id=prompt_id,
            )
        )

    def stop(self):
        return translate_hook(hook_payload("Stop", stop_hook_active=False))

    def test_prompt_ids_dedupe_replays_and_separate_sequential_tasks(self):
        first = self.record_all(self.prompt())[0]
        self.assertFalse(first.deduplicated)
        steering = self.record_all(self.prompt())[0]
        self.assertTrue(steering.deduplicated)
        self.assertEqual(steering.event_id, first.event_id)

        stop_result = self.record_all(self.stop())[0]
        self.assertFalse(stop_result.deduplicated)
        second = self.record_all(self.prompt(SECOND_PROMPT_ID))[0]
        self.assertFalse(second.deduplicated)
        self.assertNotEqual(second.event_id, first.event_id)

        events = self.ledger_events()
        starts = [event for event in events if event["event"] == "task.start"]
        self.assertEqual(len(starts), 2)
        task_ids = [event["identity"]["task_id"] for event in starts]
        self.assertTrue(all(task_id and task_id.startswith("id_") for task_id in task_ids))
        self.assertNotEqual(task_ids[0], task_ids[1])
        self.assertEqual(starts[0]["identity"]["session_id"], starts[1]["identity"]["session_id"])
        stop_event = next(
            event
            for event in events
            if event["event"] == "coverage.gap"
            and event["payload"]["source_event"] == "turn_stop"
        )
        self.assertEqual(stop_event["identity"]["task_id"], task_ids[0])
        self.assertFalse(
            any(event["event"] == "runtime.turn_stopped" for event in events)
        )

    def test_legacy_generation_closes_only_on_unblockable_failure_or_terminal(self):
        legacy_prompt = self.prompt(None)
        first = self.record_all(legacy_prompt)[0]
        duplicate = self.record_all(self.prompt(None))[0]
        self.assertTrue(duplicate.deduplicated)
        self.assertEqual(duplicate.event_id, first.event_id)

        self.record_all(
            translate_hook(
                hook_payload("Stop", prompt_id=None, stop_hook_active=False)
            )
        )
        still_open = self.record_all(self.prompt(None))[0]
        self.assertTrue(still_open.deduplicated)
        self.assertEqual(still_open.event_id, first.event_id)

        failure = self.record_all(
            translate_hook(
                hook_payload(
                    "StopFailure",
                    prompt_id=None,
                    error=CANARIES["error"],
                )
            )
        )[0]
        self.assertFalse(failure.deduplicated)
        next_generation = self.record_all(self.prompt(None))[0]
        self.assertFalse(next_generation.deduplicated)
        self.assertNotEqual(next_generation.event_id, first.event_id)

        for observation, key in terminal_emissions(
            session=SESSION,
            runtime_family="claude",
            surface="cli-interactive",
            outcome="incomplete",
            verification="partially-verified",
            task_kind="continuation",
            cause="not-applicable",
            requirements=[("REQ-LEGACY", "partial", "partially-verified")],
        ):
            self.recorder.record_declaration(
                observation, source_key=key, source_session=SESSION
            )
        after_terminal = self.record_all(self.prompt(None))[0]
        self.assertFalse(after_terminal.deduplicated)
        self.assertNotEqual(after_terminal.event_id, next_generation.event_id)

        starts = [
            event for event in self.ledger_events() if event["event"] == "task.start"
        ]
        self.assertEqual(len(starts), 3)
        self.assertNotEqual(
            starts[0]["identity"]["task_id"], starts[1]["identity"]["task_id"]
        )
        self.assertNotEqual(
            starts[1]["identity"]["task_id"], starts[2]["identity"]["task_id"]
        )

    def test_tool_spans_and_single_first_activity_bind_to_the_active_generation(self):
        self.record_all(self.prompt())
        pre = translate_hook(
            hook_payload(
                "PreToolUse",
                tool_name="Bash",
                tool_use_id="toolu_bind_1",
                tool_input={"command": CANARIES["command"]},
            )
        )
        post = translate_hook(
            hook_payload(
                "PostToolUse",
                tool_name="Bash",
                tool_use_id="toolu_bind_1",
                tool_input={"command": CANARIES["command"]},
                tool_response=CANARIES["tool_result"],
            )
        )
        second_pre = translate_hook(
            hook_payload(
                "PreToolUse",
                tool_name="Edit",
                tool_use_id="toolu_bind_2",
                tool_input={"file_path": CANARIES["file"]},
            )
        )
        self.record_all(pre + post + second_pre)
        events = self.ledger_events()
        start = next(event for event in events if event["event"] == "task.start")
        task_id = start["identity"]["task_id"]
        first_activities = [
            event for event in events if event["event"] == "task.first_activity"
        ]
        self.assertEqual(len(first_activities), 1)
        self.assertEqual(first_activities[0]["identity"]["task_id"], task_id)
        spans = [event for event in events if event["event"].startswith("span.")]
        self.assertEqual(len(spans), 3)
        self.assertTrue(all(event["identity"]["task_id"] == task_id for event in spans))
        self.assertEqual(spans[0]["payload"]["span_id"], spans[1]["payload"]["span_id"])
        self.assertNotEqual(spans[0]["payload"]["span_id"], spans[2]["payload"]["span_id"])

    def test_preinstall_activity_without_a_task_dedupes_per_session(self):
        orphan_one = translate_hook(
            hook_payload(
                "PreToolUse",
                tool_name="Read",
                tool_use_id="toolu_orphan_1",
                tool_input={"file_path": CANARIES["file"]},
                prompt_id=None,
            )
        )
        orphan_two = translate_hook(
            hook_payload(
                "PreToolUse",
                tool_name="Grep",
                tool_use_id="toolu_orphan_2",
                tool_input={"pattern": CANARIES["tool_input"]},
                prompt_id=None,
            )
        )
        self.record_all(orphan_one + orphan_two)
        events = self.ledger_events()
        first_activities = [
            event for event in events if event["event"] == "task.first_activity"
        ]
        self.assertEqual(len(first_activities), 1)
        self.assertIsNone(first_activities[0]["identity"]["task_id"])
        self.assertIsNotNone(first_activities[0]["identity"]["session_id"])

    def test_prompt_correlated_usage_remains_bound_after_stop(self):
        self.record_all(self.prompt())
        active_usage = self.record_event(
            translate_otlp(realistic_otlp_payload()), "usage.observed"
        )
        events = self.ledger_events()
        start = next(event for event in events if event["event"] == "task.start")
        bound = next(
            event for event in events if event["event_id"] == active_usage.event_id
        )
        self.assertEqual(bound["identity"]["task_id"], start["identity"]["task_id"])
        self.assertEqual(bound["measurement"]["tokens"]["input"], "449")

        # Claude's final response usage commonly flushes only after the agent
        # has declared delivery and the Stop hook has run.  Exact prompt
        # correlation must survive both closures.
        for observation, key in terminal_emissions(
            session=SESSION,
            runtime_family="claude",
            surface="cli-interactive",
            outcome="incomplete",
            verification="partially-verified",
            task_kind="primary",
            cause="not-applicable",
            requirements=[("REQ-LATE-USAGE", "partial", "partially-verified")],
        ):
            self.recorder.record_declaration(
                observation, source_key=key, source_session=SESSION
            )
        self.record_all(self.stop())
        late_payload = realistic_otlp_payload()
        record = late_payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
        record["timeUnixNano"] = "1785250000000009999"
        late_usage = self.record_event(translate_otlp(late_payload), "usage.observed")
        late_event = next(
            event
            for event in self.ledger_events()
            if event["event_id"] == late_usage.event_id
        )
        self.assertEqual(
            late_event["identity"]["task_id"], start["identity"]["task_id"]
        )
        self.assertIsNotNone(late_event["identity"]["session_id"])
        task_report = summarize(self.ledger_events())["tasks"][0]
        self.assertEqual(task_report["tokens"]["input"], "898")

    def test_two_prompt_tasks_receive_their_own_delayed_usage(self):
        first_start_result = self.record_all(self.prompt())[0]
        self.record_all(self.stop())
        second_start_result = self.record_all(self.prompt(SECOND_PROMPT_ID))[0]

        first_payload = realistic_otlp_payload()
        first_api = first_payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
        first_api["timeUnixNano"] = "1785250000000010001"
        first_usage = self.record_event(
            translate_otlp(first_payload), "usage.observed"
        )

        second_payload = with_otlp_prompt(realistic_otlp_payload(), SECOND_PROMPT_ID)
        second_api = second_payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
        second_api["timeUnixNano"] = "1785250000000010002"
        second_usage = self.record_event(translate_otlp(second_payload), "usage.observed")

        events = self.ledger_events()
        first_start = next(
            event for event in events if event["event_id"] == first_start_result.event_id
        )
        second_start = next(
            event for event in events if event["event_id"] == second_start_result.event_id
        )
        first_event = next(
            event for event in events if event["event_id"] == first_usage.event_id
        )
        second_event = next(
            event for event in events if event["event_id"] == second_usage.event_id
        )
        self.assertEqual(
            first_event["identity"]["task_id"], first_start["identity"]["task_id"]
        )
        self.assertEqual(
            second_event["identity"]["task_id"], second_start["identity"]["task_id"]
        )
        self.assertNotEqual(
            first_event["identity"]["task_id"], second_event["identity"]["task_id"]
        )

    def test_otlp_before_hook_collapses_to_one_exact_prompt_task(self):
        payload = realistic_otlp_payload()
        api = payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
        payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"] = [api]
        usage_result = self.record_event(
            translate_otlp(payload), "usage.observed"
        )
        before_hook = self.ledger_events()
        self.assertFalse(any(event["event"] == "task.start" for event in before_hook))
        self.assertTrue(
            all(event["identity"]["task_id"] is None for event in before_hook)
        )
        hook_start = self.record_all(self.prompt())[0]
        events = self.ledger_events()
        starts = [event for event in events if event["event"] == "task.start"]
        self.assertEqual(len(starts), 1)
        self.assertFalse(hook_start.deduplicated)
        usage = next(
            event for event in events if event["event_id"] == usage_result.event_id
        )
        self.assertIsNone(usage["identity"]["task_id"])
        report = summarize(events)
        self.assertEqual(report["task_count"], 1)
        self.assertEqual(report["tasks"][0]["tokens"]["input"], "449")

    def test_changed_or_malformed_otlp_prompt_never_uses_the_active_task(self):
        self.record_all(self.prompt())
        for prompt_id in (SECOND_PROMPT_ID, "malformed-prompt-id"):
            with self.subTest(prompt_id=prompt_id):
                payload = with_otlp_prompt(realistic_otlp_payload(), prompt_id)
                records = payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"]
                # Remove user_prompt so the mismatching API candidate has no
                # exact task boundary in this batch or the store.
                payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"] = [
                    records[0]
                ]
                records[0]["timeUnixNano"] = (
                    "1785250000000020001"
                    if prompt_id == SECOND_PROMPT_ID
                    else "1785250000000020002"
                )
                usage_result = self.record_event(
                    translate_otlp(payload), "usage.observed"
                )
                usage = next(
                    event
                    for event in self.ledger_events()
                    if event["event_id"] == usage_result.event_id
                )
                self.assertIsNone(usage["identity"]["task_id"])
                self.assertIsNotNone(usage["identity"]["session_id"])

    def test_declarations_bind_each_generation_and_survive_a_prior_terminal(self):
        self.record_all(self.prompt())
        first_terminal = terminal_emissions(
            session=SESSION,
            runtime_family="claude",
            surface="cli-interactive",
            outcome="complete",
            verification="verified",
            task_kind="primary",
            cause="not-applicable",
            requirements=[("REQ-1", "satisfied", "verified")],
            requirement_evidence={"REQ-1": ["test:REQ-1"]},
            acceptance_baseline_id="baseline:REQ-1",
            approved_scope_change_ids=[],
            task_type="implementation",
            scope_size="small",
            method="direct",
        )
        for observation, key in first_terminal:
            self.recorder.record_declaration(
                observation, source_key=key, source_session=SESSION
            )
        self.record_all(self.stop())
        self.record_all(self.prompt(SECOND_PROMPT_ID))
        second_terminal = terminal_emissions(
            session=SESSION,
            runtime_family="claude",
            surface="cli-interactive",
            outcome="incomplete",
            verification="partially-verified",
            task_kind="continuation",
            cause="new-scope",
            requirements=[("REQ-2", "partial", "partially-verified")],
        )
        for observation, key in second_terminal:
            self.recorder.record_declaration(
                observation, source_key=key, source_session=SESSION
            )
        events = self.ledger_events()
        starts = [event for event in events if event["event"] == "task.start"]
        terminals = [event for event in events if event["event"] == "task.terminal"]
        self.assertEqual(len(starts), 2)
        self.assertEqual(len(terminals), 2)
        self.assertEqual(
            terminals[0]["identity"]["task_id"], starts[0]["identity"]["task_id"]
        )
        self.assertEqual(
            terminals[1]["identity"]["task_id"], starts[1]["identity"]["task_id"]
        )
        report = summarize(events)
        self.assertEqual(report["task_count"], 2)
        outcome_by_task = {
            item["task_id"]: item["terminal_outcome"] for item in report["tasks"]
        }
        self.assertEqual(
            sorted(outcome_by_task.values()), ["complete", "incomplete"]
        )
        for item in report["tasks"]:
            self.assertEqual(item["runtime"]["family"], "claude")

    def test_opaque_declaration_binding_authenticates_runtime_and_session(self):
        self.record_all(self.prompt())
        binding = self.recorder.declaration_binding("claude", SESSION)
        self.assertRegex(
            binding,
            r"^binding_v1_claude_[0-9a-f]{32}_[0-9a-f]{32}$",
        )
        self.assertNotIn(SESSION, binding)

        observation, key = phase_emission(
            session=binding,
            runtime_family="claude",
            surface="cli-interactive",
            boundary="start",
            phase="testing",
            activity="tool-active",
            span="binding-regression",
        )
        result = self.recorder.record_declaration(
            observation,
            source_key=key,
            session_binding=binding,
        )
        event = next(
            item for item in self.ledger_events() if item["event_id"] == result.event_id
        )
        start = next(item for item in self.ledger_events() if item["event"] == "task.start")
        self.assertEqual(event["identity"]["task_id"], start["identity"]["task_id"])

        tampered = binding[:-1] + ("0" if binding[-1] != "0" else "1")
        tampered_observation, tampered_key = phase_emission(
            session=tampered,
            runtime_family="claude",
            surface="cli-interactive",
            boundary="start",
            phase="testing",
            activity="tool-active",
            span="tampered-binding",
        )
        with self.assertRaises(ContractValidationError):
            self.recorder.record_declaration(
                tampered_observation,
                source_key=tampered_key,
                session_binding=tampered,
            )

        other_binding = self.recorder.declaration_binding(
            "claude", "different-private-session"
        )
        other_observation, other_key = phase_emission(
            session=other_binding,
            runtime_family="claude",
            surface="cli-interactive",
            boundary="start",
            phase="testing",
            activity="tool-active",
            span="cross-session-binding",
        )
        with self.assertRaises(ContractValidationError):
            self.recorder.record_declaration(
                other_observation,
                source_key=other_key,
                session_binding=other_binding,
            )

        cross_runtime, cross_runtime_key = phase_emission(
            session=binding,
            runtime_family="codex",
            surface="cli-interactive",
            boundary="start",
            phase="testing",
            activity="tool-active",
            span="cross-runtime-binding",
        )
        with self.assertRaises(ContractValidationError):
            self.recorder.record_declaration(
                cross_runtime,
                source_key=cross_runtime_key,
                session_binding=binding,
            )
        self.assert_not_in_state(SESSION, binding, OPAQUE_BINDING)

    def test_codex_and_claude_share_one_store_without_interference(self):
        codex_emissions = codex_translate_hook(
            {
                "hook_event_name": "UserPromptSubmit",
                # Runtime session namespaces are provider-owned.  Two hosts may
                # legitimately emit the same raw value, so runtime family must
                # remain part of every core lookup and generated identity.
                "session_id": SESSION,
                "turn_id": PROMPT_ID,
                "prompt": CANARIES["prompt"],
            },
            surface="cli-interactive",
        )
        self.record_all(self.prompt())
        self.record_all(codex_emissions)
        self.record_all(
            translate_hook(
                hook_payload(
                    "PreToolUse",
                    tool_name="Bash",
                    tool_use_id="toolu_same_session",
                    tool_input={"command": CANARIES["command"]},
                )
            )
        )
        self.record_all(
            translate_hook(
                hook_payload(
                    "MessageDisplay",
                    message_id=MESSAGE_ID,
                    message={"content": CANARIES["assistant_response"]},
                    delta=CANARIES["transcript_delta"],
                    final=True,
                )
            )
        )
        self.record_all(
            translate_hook(
                hook_payload(
                    "SubagentStart",
                    agent_id=AGENT_ID,
                    agent_type="general-purpose",
                    prompt=CANARIES["background_description"],
                )
            )
        )
        self.record_all(translate_otlp(realistic_otlp_payload()))

        terminal = terminal_emissions(
            session=SESSION,
            runtime_family="claude",
            surface="cli-interactive",
            outcome="incomplete",
            verification="partially-verified",
            task_kind="primary",
            cause="not-applicable",
            requirements=[("REQ-SAME-SESSION", "partial", "partially-verified")],
        )
        for observation, key in terminal:
            self.recorder.record_declaration(
                observation,
                source_key=key,
                source_session=SESSION,
            )

        events = self.ledger_events()
        starts = [event for event in events if event["event"] == "task.start"]
        self.assertEqual(len(starts), 2)
        families = sorted(event["runtime"]["family"] for event in starts)
        self.assertEqual(families, ["claude", "codex"])
        starts_by_family = {
            event["runtime"]["family"]: event for event in starts
        }
        claude_task = starts_by_family["claude"]["identity"]["task_id"]
        codex_task = starts_by_family["codex"]["identity"]["task_id"]
        self.assertNotEqual(claude_task, codex_task)
        self.assertNotEqual(
            starts_by_family["claude"]["identity"]["session_id"],
            starts_by_family["codex"]["identity"]["session_id"],
        )
        claude_bound = [
            event
            for event in events
            if event["runtime"]["family"] == "claude"
            and event["event"]
            in {"task.first_activity", "span.start", "usage.observed", "requirement.status", "task.terminal"}
        ]
        self.assertTrue(claude_bound)
        self.assertTrue(
            all(event["identity"]["task_id"] == claude_task for event in claude_bound)
        )
        self.assertTrue(
            all(event["identity"]["task_id"] != codex_task for event in claude_bound)
        )

        # A steering prompt after the declaration must not be collapsed into
        # or generated from the Codex task that reused the raw session value.
        self.record_all(self.prompt(SECOND_PROMPT_ID))
        refreshed = self.ledger_events()
        claude_starts = [
            event
            for event in refreshed
            if event["event"] == "task.start"
            and event["runtime"]["family"] == "claude"
        ]
        self.assertEqual(len(claude_starts), 2)
        self.assertTrue(
            all(event["identity"]["task_id"] != codex_task for event in claude_starts)
        )
        report = summarize(events)
        self.assertEqual(report["task_count"], 2)

    def test_raw_identifiers_never_reach_durable_state(self):
        self.record_all(self.prompt())
        self.record_all(
            translate_hook(
                hook_payload(
                    "PreToolUse",
                    tool_name="Bash",
                    tool_use_id="toolu_privacy_1",
                    tool_input={"command": CANARIES["command"]},
                )
            )
        )
        self.record_all(
            translate_hook(
                hook_payload(
                    "MessageDisplay",
                    message_id=MESSAGE_ID,
                    message={"content": CANARIES["assistant_response"]},
                    delta=CANARIES["transcript_delta"],
                    final=True,
                )
            )
        )
        self.record_all(
            translate_hook(
                hook_payload(
                    "SubagentStart",
                    agent_id=AGENT_ID,
                    agent_type="general-purpose",
                    prompt=CANARIES["background_description"],
                )
            )
        )
        self.record_all(translate_otlp(realistic_otlp_payload()))
        forbidden = [
            SESSION,
            PROMPT_ID,
            SECOND_PROMPT_ID,
            "toolu_privacy_1",
            CLIENT_REQUEST_ID,
            ERROR_REQUEST_ID,
            OTLP_TOOL_ID,
            OTLP_REJECTED_TOOL_ID,
            MESSAGE_ID,
            AGENT_ID,
        ] + list(CANARIES.values())
        self.assert_not_in_state(*forbidden)


def _collapse_worker(state_dir: str, index: int) -> None:
    recorder = Recorder(Path(state_dir), busy_timeout_ms=10000)
    emissions = translate_hook(
        {
            "session_id": SESSION,
            "hook_event_name": "UserPromptSubmit",
            "prompt": "concurrent prompt",
        },
        surface="cli-interactive",
    )
    for observation, key in emissions:
        result = recorder.record(observation, source_key=key)
        if not result.projected:
            raise AssertionError("worker event was not projected")
    recorder.close()


def _exact_prompt_collapse_worker(state_dir: str, index: int) -> None:
    recorder = Recorder(Path(state_dir), busy_timeout_ms=10000)
    if index % 2 == 0:
        emissions = translate_hook(
            hook_payload(
                "UserPromptSubmit",
                prompt=CANARIES["prompt"],
                prompt_id=PROMPT_ID,
            )
        )
    else:
        emissions = [
            emission
            for emission in translate_otlp(realistic_otlp_payload())
            if emission[0]["event"] == "task.start"
        ]
    for observation, key in emissions:
        result = recorder.record(observation, source_key=key)
        if not result.projected:
            raise AssertionError("worker event was not projected")
    recorder.close()


def _native_tool_completion_worker(state_dir: str, index: int) -> None:
    """Race duplicate hook and OTLP evidence for one documented tool span."""

    recorder = Recorder(Path(state_dir), busy_timeout_ms=10000)
    if index % 2 == 0:
        emissions = translate_hook(
            hook_payload(
                "PostToolUse",
                tool_name="Bash",
                tool_use_id=OTLP_TOOL_ID,
                duration_ms=812,
                tool_response=CANARIES["tool_result"],
            )
        )
    else:
        payload = realistic_otlp_payload()
        record = payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"][2]
        payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"] = [record]
        emissions = translate_otlp(payload)
    for observation, key in emissions:
        result = recorder.record(observation, source_key=key)
        if not result.projected:
            raise AssertionError("worker event was not projected")
    recorder.close()


class ConcurrencyTests(unittest.TestCase):
    def test_concurrent_prompt_replays_collapse_to_one_task(self):
        context = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory(prefix="delivery-claude-concurrent-") as temporary:
            state = Path(temporary).resolve()
            Recorder(state).close()
            workers = [
                context.Process(target=_collapse_worker, args=(str(state), index))
                for index in range(8)
            ]
            for process in workers:
                process.start()
            for process in workers:
                process.join(45)
                self.assertEqual(process.exitcode, 0)
            raw = (state / "EfficiencyLedger.jsonl").read_bytes()
            events = [json.loads(line) for line in raw.splitlines()]
            starts = [event for event in events if event["event"] == "task.start"]
            self.assertEqual(len(starts), 1)
            self.assertIsNotNone(starts[0]["identity"]["task_id"])

    def test_hook_and_otlp_prompt_boundaries_collapse_atomically(self):
        context = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory(prefix="delivery-claude-prompt-race-") as temporary:
            state = Path(temporary).resolve()
            Recorder(state).close()
            workers = [
                context.Process(
                    target=_exact_prompt_collapse_worker,
                    args=(str(state), index),
                )
                for index in range(8)
            ]
            for process in workers:
                process.start()
            for process in workers:
                process.join(45)
                self.assertEqual(process.exitcode, 0)
            events = [
                json.loads(line)
                for line in (state / "EfficiencyLedger.jsonl").read_bytes().splitlines()
            ]
            starts = [event for event in events if event["event"] == "task.start"]
            self.assertEqual(len(starts), 1)
            self.assertIsNotNone(starts[0]["identity"]["task_id"])

    def test_concurrent_hook_and_otlp_native_tool_duration_counts_once(self):
        context = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory(prefix="delivery-claude-span-race-") as temporary:
            state = Path(temporary).resolve()
            recorder = Recorder(state)
            for observation, key in translate_hook(
                hook_payload(
                    "UserPromptSubmit",
                    prompt=CANARIES["prompt"],
                    prompt_id=PROMPT_ID,
                )
            ):
                recorder.record(observation, source_key=key)
            recorder.close()
            workers = [
                context.Process(
                    target=_native_tool_completion_worker,
                    args=(str(state), index),
                )
                for index in range(8)
            ]
            for process in workers:
                process.start()
            for process in workers:
                process.join(45)
                self.assertEqual(process.exitcode, 0)
            events = [
                json.loads(line)
                for line in (state / "EfficiencyLedger.jsonl").read_bytes().splitlines()
            ]
            spans = [event for event in events if event["event"] == "span.end"]
            self.assertEqual(len(spans), 2)
            self.assertEqual(
                {event["payload"]["span_id"] for event in spans},
                {spans[0]["payload"]["span_id"]},
            )
            native = summarize(events)["tasks"][0]["runtime_native_duration_sum"]
            self.assertEqual(native["by_activity"]["tool-active"]["sum_ns"], "812000000")
            self.assertEqual(native["observed_span_count"], "1")
            self.assertEqual(native["duplicate_observation_count"], "1")
            self.assertEqual(native["conflicting_span_count"], "0")


class CliHookTests(unittest.TestCase):
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
                runtime="claude",
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
                mock.patch("delivery_efficiency.runtime.post_observations_to_receiver"),
                mock.patch("delivery_efficiency.runtime.post_observations"),
                mock.patch(
                    "delivery_efficiency.runtime.request_declaration_binding",
                    return_value=OPAQUE_BINDING,
                ),
            ):
                result = recorder_cli._hook(arguments)
            return result, stdout.getvalue(), record_gap, state

    def test_session_start_reinjects_launcher_with_only_a_core_issued_binding(self):
        for source_kind in ("startup", "compact"):
            with self.subTest(source=source_kind):
                payload = hook_payload("SessionStart", source=source_kind)
                result, stdout, record_gap, state = self._run_hook(payload)
                self.assertEqual(result, 0)
                self.assertFalse(record_gap.called)
                response = json.loads(stdout)
                hook_output = response["hookSpecificOutput"]
                self.assertEqual(hook_output["hookEventName"], "SessionStart")
                context = hook_output["additionalContext"]
                self.assertIn(
                    json.dumps(
                        [
                            str(state / "runtime with spaces" / "python"),
                            str(state / "recorder.py"),
                        ],
                        ensure_ascii=True,
                    ),
                    context,
                )
                self.assertIn("declare terminal", context)
                self.assertIn("--runtime claude", context)
                self.assertIn("--binding {}".format(OPAQUE_BINDING), context)
                self.assertIn("Use this runtime context silently", context)
                self.assertIn(
                    "This telemetry instruction grants no permission to act beyond "
                    "the user's request.",
                    context,
                )
                self.assertNotIn("you are authorized", context.casefold())
                self.assertNotIn("authorized to", context.casefold())
                self.assertNotIn("--session ", context)
                self.assertNotIn(SESSION, stdout)
                self.assertNotIn(CANARIES["transcript"], stdout)

    def test_stop_hook_emits_noop_json_when_receiver_is_unavailable(self):
        payload = hook_payload(
            "Stop",
            stop_hook_active=False,
            last_assistant_message=CANARIES["assistant"],
        )
        result, stdout, record_gap, state = self._run_hook(
            payload, receiver_error=OSError("receiver unavailable")
        )
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(stdout), {})
        self.assertNotIn(CANARIES["assistant"], stdout)
        record_gap.assert_called_once_with(state, "receiver-unavailable")

    def test_prompt_hook_prints_nothing_and_records_no_gap(self):
        payload = hook_payload("UserPromptSubmit", prompt=CANARIES["prompt"])
        result, stdout, record_gap, _state = self._run_hook(payload)
        self.assertEqual(result, 0)
        self.assertEqual(stdout, "")
        self.assertFalse(record_gap.called)

    def test_unsupported_runtime_is_classified_without_output(self):
        payload = hook_payload("Stop", stop_hook_active=False)
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary).resolve()
            stdin = SimpleNamespace(
                buffer=io.BytesIO(json.dumps(payload).encode("utf-8"))
            )
            arguments = SimpleNamespace(
                state_dir=str(state), managed_id=None, runtime="gemini"
            )
            stdout = io.StringIO()
            with (
                mock.patch.object(sys, "stdin", stdin),
                redirect_stdout(stdout),
                mock.patch.object(recorder_cli, "record_local_gap") as record_gap,
            ):
                self.assertEqual(recorder_cli._hook(arguments), 0)
            record_gap.assert_called_once_with(state, "unsupported-runtime-event")
            self.assertEqual(json.loads(stdout.getvalue()), {})

    def test_hook_parser_accepts_claude_runtime(self):
        parsed = recorder_cli.build_parser().parse_args(
            ["hook", "claude", "--state-dir", "/tmp/state", "--managed-id", recorder_cli.MANAGED_ID]
        )
        self.assertEqual(parsed.runtime, "claude")


class LoopbackEndToEndTests(unittest.TestCase):
    def test_hook_and_otlp_flow_reaches_the_cold_ledger(self):
        from delivery_efficiency.platforms import detect_platform
        from delivery_efficiency.runtime import AUTH_HEADER, create_settings
        from delivery_efficiency.server import Receiver
        import subprocess
        from urllib.request import Request, urlopen

        with tempfile.TemporaryDirectory(prefix="delivery-claude-e2e-") as raw:
            state = Path(raw).resolve() / "state with spaces"
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            except PermissionError:
                self.skipTest("host policy denies loopback bind")
            finally:
                probe.close()
            settings = create_settings(
                state,
                listen_port=port,
                install_root=TOOL_ROOT,
                python_executable=Path(sys.executable),
                platform_info=detect_platform().as_event_value(),
                auth_token="a" * 64,
            )
            receiver = Receiver(state, monitor_settings=False)
            thread = threading.Thread(target=receiver.serve_forever, daemon=True)
            thread.start()
            try:
                session_start = subprocess.run(
                    [
                        sys.executable,
                        str(TOOL_ROOT / "recorder.py"),
                        "hook",
                        "claude",
                        "--state-dir",
                        str(state),
                        "--managed-id",
                        "holyskills-delivery-efficiency-v1",
                    ],
                    input=json.dumps(hook_payload("SessionStart", source="startup")).encode("utf-8"),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=True,
                )
                context = json.loads(session_start.stdout.decode("utf-8"))[
                    "hookSpecificOutput"
                ]["additionalContext"]
                self.assertIn("declare terminal", context)
                self.assertIn("--runtime claude", context)
                self.assertNotIn(settings["auth_token"], context)
                self.assertNotIn(SESSION, context)
                binding_match = re.search(
                    r"--binding (binding_v1_claude_[0-9a-f]{32}_[0-9a-f]{32})",
                    context,
                )
                self.assertIsNotNone(binding_match)
                binding = binding_match.group(1)

                def run_hook(payload):
                    completed = subprocess.run(
                        [
                            sys.executable,
                            str(TOOL_ROOT / "recorder.py"),
                            "hook",
                            "claude",
                            "--state-dir",
                            str(state),
                        ],
                        input=json.dumps(payload).encode("utf-8"),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        check=True,
                    )
                    self.assertEqual(completed.returncode, 0)

                run_hook(hook_payload("UserPromptSubmit", prompt=CANARIES["prompt"]))
                run_hook(
                    hook_payload(
                        "PreToolUse",
                        tool_name="Bash",
                        tool_use_id="toolu_e2e_1",
                        tool_input={"command": CANARIES["command"]},
                    )
                )
                run_hook(
                    hook_payload(
                        "PostToolUse",
                        tool_name="Bash",
                        tool_use_id="toolu_e2e_1",
                        tool_input={"command": CANARIES["command"]},
                        tool_response=CANARIES["tool_result"],
                    )
                )

                # Token export flushes while the turn is still active, so the
                # usage event must bind to the unique open generation.
                otlp_body = json.dumps(
                    realistic_otlp_payload(),
                    separators=(",", ":"),
                ).encode("utf-8")
                request = Request(
                    "http://127.0.0.1:{}/v1/logs".format(port),
                    data=otlp_body,
                    headers={
                        AUTH_HEADER: settings["auth_token"],
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                with urlopen(request, timeout=2) as response:
                    self.assertEqual(response.status, 200)

                run_hook(hook_payload("Stop", stop_hook_active=False))

                declaration = subprocess.run(
                    [
                        sys.executable,
                        str(TOOL_ROOT / "recorder.py"),
                        "declare",
                        "terminal",
                        "--runtime",
                        "claude",
                        "--binding",
                        binding,
                        "--outcome",
                        "complete",
                        "--verification",
                        "verified",
                        "--requirement",
                        "scope=satisfied:verified",
                        "--evidence",
                        "scope=test:claude-e2e",
                        "--acceptance-baseline",
                        "baseline:claude-e2e",
                        "--no-scope-changes",
                        "--task-type",
                        "implementation",
                        "--scope-size",
                        "small",
                        "--method",
                        "direct",
                        "--state-dir",
                        str(state),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                self.assertEqual(
                    declaration.returncode,
                    0,
                    declaration.stderr.decode("utf-8", "replace"),
                )
            finally:
                receiver.shutdown()
                receiver.server_close()
                thread.join(timeout=3)

            ledger = (state / "EfficiencyLedger.jsonl").read_text(encoding="utf-8")
            self.assertIn('"event":"task.start"', ledger)
            self.assertIn('"event":"span.end"', ledger)
            self.assertIn('"event":"usage.observed"', ledger)
            self.assertIn('"event":"task.terminal"', ledger)
            self.assertIn('"family":"claude"', ledger)
            self.assertNotIn(SESSION, ledger)
            for canary in CANARIES.values():
                self.assertNotIn(canary, ledger)
            events = [json.loads(line) for line in ledger.splitlines()]
            starts = [event for event in events if event["event"] == "task.start"]
            self.assertEqual(len(starts), 1)
            task_id = starts[0]["identity"]["task_id"]
            self.assertIsNotNone(task_id)
            terminal = next(event for event in events if event["event"] == "task.terminal")
            self.assertEqual(terminal["identity"]["task_id"], task_id)
            usage = next(event for event in events if event["event"] == "usage.observed")
            self.assertEqual(usage["identity"]["task_id"], task_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
