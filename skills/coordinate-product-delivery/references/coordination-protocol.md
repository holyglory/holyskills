# Coordination Protocol

## Contents

1. Task topology
2. Primary executor work order
3. Low-volume events
4. Scope-extension requests
5. Hourly reconciliation
6. Recovery and completion

## Task Topology

Keep one durable coordinator task and one primary execution task for the active delivery stream. The execution task may spawn subagents for implementation, tests, investigation, and review. Those subagents report to the executor, not directly to the coordinator.

Create another top-level executor only when the user explicitly requests it or the work is an independently governable delivery stream that cannot safely share the primary executor. More technical specialties alone are not a reason.

## Primary Executor Work Order

Use a compact prompt shaped like this:

```text
Execute release <release-id> at scope baseline <release-id>:r<revision>.

User outcome:
<plain-language outcome>

Approved requirements and evidence:
<bounded requirements and acceptance evidence>

Not in scope:
<explicit exclusions>

Work graph:
<tasks, dependencies, progress, blockers, expected updates>

Unfinished Completion Ledger issues:
<only relevant not-implemented or implemented-unverified issues>

Use the product-delivery database for every progress and ledger mutation.
Return only milestone events, blockers, scope proposals, and the final evidence summary.
Do not send raw logs or subagent output to the coordinator.
Do not change the scope baseline. Propose any material change in the required format.
```

Include the exact database invocation convention or backend handle. Do not paste the permanent event history.

## Low-Volume Events

Record an event only for a meaningful state change:

```json
{
  "event_type": "task_progress|blocked|unblocked|failed|scope_proposal|issue_changed|evidence_ready|complete",
  "release_id": "R1",
  "scope_baseline": "R1:r3",
  "task_id": "T-12",
  "completion_percent": 60,
  "summary": "Plain-language result or blocker.",
  "decision_needed": false,
  "evidence_ref": "bounded reference or null",
  "expected_next_update_at": "2026-08-20T14:00:00+00:00"
}
```

Omit irrelevant fields. Keep the summary concise. Do not attach command output, stack traces, test logs, diffs, or subagent transcripts. Those remain in the executor's own context or cold artifacts.

Update task completion only at planned checkpoints or when evidence invalidates a prior checkpoint. Ordinary coding activity is not a progress event.

## Scope-Extension Requests

The executor sends:

```text
Current accepted outcome:
<outcome>

Proposed additional behavior:
<user-visible meaning>

Why it appears necessary:
<reason and evidence>

Can the accepted outcome work without it?
<yes/no and consequence>

Release effect:
<scope, timing, risk, cost, or operating commitment>
```

The coordinator classifies the proposal. It may resolve clarifications, necessary completion work, and defects within the approved baseline. It sends true product expansion to the user in plain language and does not authorize it until the user decides.

## Hourly Reconciliation

While execution is active, wait for completion or attention events. Once per hour, obtain one compact snapshot even if no event arrived.

Reconcile:

1. Executor task lifecycle and whether it needs attention
2. Database `monitor-snapshot`
3. Missed `expected_update_at` values
4. Failed or blocked tasks
5. Blocking Completion Ledger issues
6. Executor scope revision versus the release scope revision
7. Newly completed evidence versus task completion

Do not treat one quiet hour as stale when the expected update is later. Do not narrate unchanged snapshots. Continue independent work while resolving a local blocker.

## Recovery And Completion

When the executor fails or becomes stale:

1. Preserve the last database event and task state.
2. Read a bounded task summary, not the full transcript.
3. Ask the same task to recover when its context and workspace remain valid.
4. Replace the task only when recovery is impossible or would preserve a corrupted state.
5. Record reassignment and the new expected update.

Before accepting completion, require the executor to provide acceptance evidence, database task updates, Completion Ledger reconciliation, and a plain-language delivered-outcome summary. The coordinator independently runs the database release gate; a worker's completion claim cannot bypass it.
