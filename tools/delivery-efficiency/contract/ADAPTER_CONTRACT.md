# Delivery-efficiency adapter contract v1.2

The shared recorder owns event validation, private identity derivation, clocks,
SQLite spooling, `EfficiencyLedger.jsonl` projection, recovery, and installation
transactions. Runtime adapters are translators only. They must never create a
second schema, ledger writer, or store.

## Input boundary

An adapter passes a small allowlisted observation to the core. It must discard
prompt and assistant text, transcript paths, working directories, filenames,
source content, tool arguments and results, shell commands, raw errors, account
data, email addresses, credentials, and unknown source fields before the
observation crosses the adapter boundary. Redaction is not a substitute for an
allowlist.

Opaque identities are derived by the core with the installation-local HMAC
key. Adapters may carry bounded source identifiers only in process memory or
one authenticated loopback request to the local core; they are never written
to a diagnostic, spool, ledger, request log, or other durable serialization.
Custom tool names are reduced to the low-cardinality categories in the schema.
Acceptance baselines, scope changes, evidence, and configuration versions use
bounded nonsensitive reference labels, never paths, URLs, source excerpts,
prompts, or other content-bearing identifiers.

## Output boundary

Every durable line conforms exactly to one published immutable schema, with no
additional properties:

- `adapter-event-v1.schema.json` is legacy schema `1.0`. Existing rows remain
  valid and readable, but the recorder never writes new `1.0` rows.
- `adapter-event-v1.1.schema.json` is legacy schema `1.1`. Existing rows remain
  valid and readable, but the recorder never writes new `1.1` rows.
- `adapter-event-v1.2.schema.json` is current schema `1.2`. Recorder `0.2.4`
  with adapter `0.2.3` writes only this shape.

One ledger may contain validated immutable `1.0` and `1.1` history followed by
new `1.2` rows. Reporting states per-version event counts and whether metadata
is unavailable for an older task; it does not fabricate new fields. Upgrade
does not rewrite, reinterpret, or discard earlier bytes. An unsupported version
or a row that mixes version shapes fails closed. Decimal strings carry counters
and nanoseconds so a consumer cannot lose precision. `null` means unobserved;
zero is permitted only when the authoritative source explicitly reported zero.

Schema `1.1` adds separately proven linked-work targets, append-only correction
targets, acceptance and scope-change metadata, task type, scope size, method,
requirement evidence references, and policy/model/runtime/recorder
configuration versions. Every classification and metadata family carries its
own provenance. Linked-work `task_kind` (continuation, retry, rollback, defect
repair, or rework) is independent of stable `task_type` (implementation,
diagnosis, review, audit, research, documentation, operations, mixed, or
other).

Schema `1.2` adds nullable durable `identity.target_id` so evidence from one
configured runtime target cannot satisfy activation checks for another target.
The managed Codex hook carries a bounded transient target reference whose
format is `target_v1_` followed by 32 lowercase hexadecimal characters. The
core derives `target_id` with its installation-local HMAC and never persists
the source reference. Codex OTLP does not accept a target attribute: its usage
inherits a target only after the existing exact task/session/turn correlation,
or the existing single-active-task correlation when no turn identifier exists,
selects one matching hook task. Missing or ambiguous correlation remains
`null`; a hook target that conflicts with its task start fails closed. Claude,
wrapped-exec, and agent-declaration observations supply no independent target.
Task-bound declarations inherit the recorded task identity, including its
target when present; unrelated Claude and wrapped-exec events remain `null`.
Immutable `1.0` and `1.1` rows have no target field and are never rewritten.

The phase and activity state are independent. Their attribution provenance is
independent of measurement provenance. Coverage is stated per dimension and
is never upgraded by inference.

## Lifecycle semantics

- `task.start` records the closest observable request boundary. A prompt hook
  is partial request-receipt coverage unless the host documents it as receipt.
- `task.first_activity` is separate from `task.start` and is emitted once per
  task from the first observed model or tool activity.
- `runtime.turn_stopped` is not terminal delivery.
- `task.terminal` requires an explicit outcome. `complete` additionally
  requires every in-scope requirement to be satisfied or explicitly removed
  with nonsensitive evidence, verification coverage to be stated, an
  acceptance-baseline reference, an explicit approved-scope-change set (which
  may be empty), task-kind provenance, and explicit task type, scope size, and
  method.
- Session shutdown is advisory and must not be treated as visible delivery.

Agent declaration batches are task-bound and atomic. The receiver resolves one
opaque task from the authenticated raw session or signed session binding once
under a write transaction, scopes every declaration dedupe key to that task,
validates the final completion state, and commits all items together. A
concurrent task start cannot divide one batch. Any validation or dedupe conflict
rolls back every new item. Exact same-task replay, including an exact terminal
batch replay, deduplicates; new declarations after a terminal are rejected, and
the same declaration shape on a later task receives a distinct durable event.
- Compaction resumes the same task; it never creates a new lineage.
- The receiver returns an opaque signed task binding only when requested. A
  later `lineage.link` resolves that binding to the earlier task and lineage
  under the receiver transaction, while the link event remains on the current
  task. The binding only authenticates a recorder reference. It does not
  authorize any user-facing or system action.
- A correction requires the target task binding and exact target event ID. The
  receiver validates that target on the historical task even after a newer
  prompt exists, then appends the correction without changing the original
  row. A correction replaces exactly one terminal state or one requirement
  state. Requirement corrections may supply replacement evidence; when they
  do not, reporting retains the original evidence.
- Later continuation, retry, rollback, defect repair, and rework events link to
  the original lineage without rewriting prior records.

Supported Claude hosts expose one UUID-v4 `prompt_id` across task-specific
hooks and the matching OTLP `prompt.id`. The adapter carries it only as a
transient task/turn candidate; the core scopes it by runtime family and session
before HMAC persistence. Hook and OTLP prompt starts collapse atomically by
that exact identity, including OTLP-first arrival. Later activity and usage
bind only to the same exact prompt task, including counters received after a
Stop attempt or declared terminal. Missing, malformed, or changed OTLP prompt
correlation never falls back to a session heuristic.

Only legacy hook payloads with no prompt identifier use core-owned
session-task generations. Repeated starts share the still-open generation; an
unblockable `StopFailure` boundary or declared terminal closes it, and the next
legacy prompt opens a deterministic new generation. A blockable `Stop` is one
attempt, not proof that a turn stopped, and repeated invocations remain
distinct partial observations. `MessageDisplay` runs before rendering; it can
prove first model activity but never visible terminal delivery.

## Clock and interval semantics

The receiver assigns `observed_at_utc`, `monotonic_ns`, and a random
`clock_domain` for its process lifetime. Interval unions may use monotonic
values only within one clock domain. A receiver restart creates a new domain;
cross-domain duration stays unknown. Concurrent per-agent active time may be
summed only as a separately labeled measure and is never called wall time.

Endpoint-to-endpoint elapsed values likewise use receiver monotonic values
only when both endpoints have the same valid `clock_domain`. The
`request_to_delivery_ns` and `execution_to_delivery_ns` fields additionally
require `complete` coverage for the applicable start and delivery dimensions
and `runtime-observed` measurement provenance at both endpoints. A complete
delivery endpoint cannot upgrade a partial, inferred, or agent-declared start.
Reports expose each selected endpoint's coverage, measurement provenance,
clock domain, and receiver-observation timing basis. Agent terminal declarations
remain separate diagnostics named
`observed_task_start_to_terminal_declaration_ns` and
`observed_first_activity_to_terminal_declaration_ns`; they describe arrival at
the receiver and do not claim exact request receipt, execution, or user-visible
delivery.

Phase token totals use only authoritative runtime token counters carrying
their own runtime-observed or agent-declared phase. Inferred or unknown phase
claims are routed to `unattributed`; tokens are never allocated by elapsed
time. Per-agent active time uses matched same-clock model/tool spans, reports
opaque delegated agents separately from the root-or-unidentified bucket, and
labels the concurrent per-agent sum separately from wall time. Recorder
overhead has a total only when every event in the task carries a
runtime-observed value; otherwise the total is `null` with explicit observed
coverage.

A host may also report an execution-only `duration_ns` on `span.end` without a
matching recorder-clock start. Reports expose a separately labeled arithmetic
sum of those runtime-observed native durations by phase and activity, including
measurement and independent attribution provenance. That sum is not wall time
or an interval union. Hook and OTLP tool completions share the opaque
runtime/session/span identity derived from `tool_use_id`; the report counts an
equal same-span duration once regardless of arrival order and reports an
affected bucket as unknown when same-span duration, definite success,
definite tool category, or attribution conflicts. A `null` success or `unknown`
tool category may coexist with one definite source value because absence of
evidence does not contradict that value.

## Adapter identities

- Codex hooks: `codex-hooks`
- Codex OTLP/HTTP JSON: `codex-otel`
- wrapped `codex exec --json`: `codex-exec`
- Claude Code hooks and OTLP/HTTP JSON logs: `claude-runtime`
- shared explicit outcome, scope, verification, phase, and linked-work input:
  `agent-declaration`

Each adapter must emit the common contract and pass the shared privacy and
schema fixtures. Runtime-native counters retain the provider categories that
map to the schema; unsupported categories remain `null`.

For a controlled `codex exec --json` run, `codex-exec` is the exclusive
recorder adapter for that child. The launcher applies a child-only
`otel.exporter="none"` override for Codex log export and an inherited marker
that makes only this recorder's managed Codex hook handler a no-op. It does not
write the Codex home, disable unrelated hooks, discard unrelated environment
variables or configuration, or weaken ordinary interactive Codex hook/OTLP
collection. This arbitration prevents wrapper JSON, managed hooks, and managed
OTLP from recording the same task, spans, or provider-native counters more
than once.

`claude-runtime` defensively translates documented hook payloads
(`SessionStart`, `SessionEnd`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`,
`PostToolUseFailure`, `SubagentStart`, `SubagentStop`, `Stop`, `StopFailure`,
and `MessageDisplay`; `PreCompact` and `Notification` deliberately translate
to nothing). The managed low-overhead installation uses only `SessionStart`,
`UserPromptSubmit`, `SubagentStart`, `SubagentStop`, `Stop`, and `StopFailure`;
per-tool, session-end, and display hooks remain uninstalled. Subagent lifetime
is not runtime-observed by these hooks. `SubagentStart` emits first activity
when applicable and a `coverage.gap`; `SubagentStop` emits a `coverage.gap`.
An allowlisted `agent_id`, when supplied, becomes opaque partial evidence of
which subagent triggered the hook, but the two observations are not paired or
reported as a measured lifetime or activity interval.

The shared `/v1/logs` endpoint accepts allowlisted `claude_code.user_prompt`,
`api_request`, `api_error`, `tool_result`, and `tool_decision` OTLP records.
Rejected decisions are not executed tool time, raw error/result/decision text
is discarded, and accepted decisions defer to the later tool result. Token
mapping is fixed:
`input_tokens` to `input`, `output_tokens` to `output`, `cache_read_tokens`
to `cached_input`, and `cache_creation_tokens` to `other`; Anthropic exposes
no separate reasoning or tool category, so those stay `null`. Tool and
API spans exist only when the host supplies or the adapter can derive a bounded
span identity. Claude subagent hooks do not currently emit spans; with or
without `agent_id`, they retain partial coverage rather than inventing a
lifetime. Without a tool identity, only first activity is recorded and tool
coverage stays partial.

## Failure semantics

Telemetry must not block agent delivery. An adapter returns success after a
bounded attempt and writes no user-visible hook output. The core records a
`coverage.gap` when the store remains usable. If storage itself is unavailable,
the adapter reports a bounded diagnostic to its own diagnostic stream and
`status` exposes the gap; it never fabricates a durable event.

Duplicate delivery from one source is normal. Each adapter supplies a stable,
privacy-safe deduplication key, and the core maps it to one event. Distinct
hook and OTLP observations remain distinct durable evidence; the same-span
native-duration report aggregation applies its explicit cross-source collapse
described above. Unknown, malformed, or oversized source input is rejected
before persistence. The generic observation endpoint rejects the
`agent-declaration` adapter so declarations cannot bypass signed task
resolution, atomic batching, completion validation, or task-scoped dedupe.
