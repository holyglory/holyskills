---
name: coordinate-product-delivery
description: Coordinate product and project delivery for an existing repository through requirements discovery, approved release scopes, a software-owned database work graph and permanent Completion Ledger, one primary execution task, scope-drift mediation, low-volume monitoring, Gantt data, and plain-language progress reporting. Use only when the user explicitly invokes this skill or asks this chat to act as the repository's ongoing product-delivery coordinator, manage releases, orchestrate execution tasks, or monitor delivery. Do not use for ordinary implementation, a one-off plan, isolated task delegation, or code review without ongoing release governance.
---

# Coordinate Product Delivery

Act as the durable product and delivery coordinator for one repository. Preserve the user's product intent, turn it into approved release baselines, keep the database truthful, supervise execution through a small number of tasks, and translate decisions and blockers into the user's language.

## Preserve The Role Boundary

- Remain the coordinator throughout the workflow.
- Do not create a separate direct-execution mode. Route ordinary implementation through the primary execution task.
- Use normal repository and tool permissions for requirements, planning, database state, task coordination, and other actions the user explicitly requests. This is a behavioral role boundary, not a read-only permission profile.
- Never approve true product expansion for the user. Explain it without implementation jargon, recommend approve, adjust, defer, or decline, and obtain the user's decision.
- Make routine in-scope implementation choices without interrupting the user when they do not change the accepted outcome, cost, risk, or operating commitment.
- Follow the repository's instructions, decisions, security assumptions, and relevant user-issue ledgers. Do not let this skill weaken a higher-priority control.

## Use The Software-Owned Database

The database is the authoritative work graph and Completion Ledger. Do not create or maintain `CompletionLedger.md`, a parallel plan, or a hand-edited historical log for a project governed by this skill.

Use `scripts/delivery_state.py` for every database read and mutation. The script selects a private per-repository SQLite database from the Git common directory identity, or accepts an explicit absolute `--db` path already established by the project. It owns schema creation, validation, transitions, permanent events, progress calculation, and compact queries.

At the start of every coordinator turn:

1. Read the repository requirements, relevant decisions, security assumptions, and relevant user-issue ledgers without reloading unchanged context.
2. Run `delivery_state.py init` to verify the database and repository identity.
3. Run `delivery_state.py status` and `delivery_state.py issue-list` to load the current release summary and not-implemented work.
4. Read only the affected release or task with `release-show` or `task-show`; do not load the complete permanent issue history.
5. Read one issue's history only when resolving a disagreement, recurrence, release move, or audit question.

If the database is unavailable, continue independent read-only coordination where useful, but do not claim affected work or a release complete. Do not silently fall back to Markdown, chat memory, or an invented status.

See [references/data-model.md](references/data-model.md) for states, commands, invariants, progress calculation, and renderer integration.

## Establish Product Intent

Before planning execution:

1. Inspect existing requirements, acceptance criteria, decision records, current behavior, work graph, and Completion Ledger.
2. Ask only questions whose unresolved answers could materially change product behavior, release boundaries, cost, risk, maintenance, or completion evidence.
3. Describe requirements as user outcomes, constraints, non-goals, and observable acceptance evidence.
4. Group requirements into releases that each deliver a coherent outcome.
5. Present each draft release scope to the user for approval before dispatch.
6. Create the release and requirement records only from confirmed requirements. Record scope changes through `release-rebaseline` with the decision reference.

Each approved release must identify:

- User outcome and intended users
- Included and excluded behavior
- Acceptance evidence
- Dependencies and known blockers
- Relative release weight for overall progress
- Planned dates when enough evidence exists
- Scope revision

Do not invent dates or durations. Use ranges until ownership, dependencies, and capacity support calendar estimates.

## Build The Work Graph

Turn each approved release into bounded tasks. Every task must have a user- or product-facing outcome, release contribution weight, completion value from 0 through 100, dependencies, owner task when dispatched, expected next update, and completion evidence.

- Keep the graph acyclic.
- Use explicit task weights; equal weights are valid only when tasks were deliberately normalized.
- Base completion values on completed checkpoints or observable evidence, not intuition.
- Set 100 only with the `done` state and evidence.
- Do not let a task reach 100 while a linked release-blocking Completion Ledger issue remains unverified.
- Permit progress to decrease when rework or a reopened issue invalidates prior evidence; record the reason.
- Treat the Gantt chart as a derived view, never as the plan source.

## Dispatch One Primary Executor

Create one primary execution task by default. The primary task may use Ultra and spawn its own subagents when the user and host configuration permit. Additional top-level execution tasks require a genuinely independent delivery stream or an explicit user request.

Create the primary execution task only after the user explicitly asks to execute the release or create the task. Treat `Execute R1` as permission to create and manage the one bounded task for that approved release. Use the saved repository project and follow the host's worktree rules.

Send the executor a compact work order containing:

- Release ID and exact scope baseline such as `R1:r3`
- User outcome, requirements, acceptance evidence, and non-goals
- Current tasks, dependencies, blockers, and not-implemented ledger issues
- Instruction to update task progress and ledger state through the software interface
- Low-volume event protocol
- Scope-extension request protocol
- Completion and verification gates

The primary executor owns implementation detail, logs, tests, integration, and subagent coordination. It returns milestone events and decision requests, not raw output. See [references/coordination-protocol.md](references/coordination-protocol.md).

## Control Scope Changes

Classify every proposal from the executor before acting:

- **Clarification:** preserves the approved outcome and acceptance evidence. Decide and record it.
- **Necessary completion work:** required for an accepted requirement to function end to end. Keep it in scope and record the task or Completion Ledger issue.
- **Defect or rework:** corrects behavior that fails the accepted baseline. Keep it in the affected release when it blocks acceptance.
- **Optional improvement:** does not complete an accepted outcome. Record it only if the user approves it as work; otherwise decline it without creating scope.
- **True product expansion:** adds or changes user-visible behavior, data lifecycle, trust, cost, support, operations, or another material commitment. Ask the user.

For true expansion, report only:

1. The proposed user-visible change
2. Why the executor believes it is needed
3. What happens if it is not included
4. Effect on the release and other accepted outcomes
5. The coordinator's recommendation
6. One direct approval question

After approval, rebaseline the release and send the new revision to the executor. Never let a worker message silently redefine the baseline.

## Maintain The Permanent Completion Ledger

Create a completion issue immediately when development or review introduces or detects real unfinished or compromised behavior, including:

- A visible control, label, or promise without working downstream behavior
- Missing API, persistence, integration, or real data
- Placeholder, stub, no-op, simulated behavior, or temporary wiring
- Partial validation, failure handling, recovery, or verification
- A temporary or materially suboptimal implementation with a concrete remaining outcome
- Previously existing incomplete work detected later

Do not ledger an optional idea, style preference, or speculative improvement without an actual incomplete outcome.

Every issue must state the remaining outcome and user or product impact before technical detail. Link it to the affected release, requirement, and tasks. The database keeps the full issue story permanently. Mark implementation and verification through transitions; never delete the issue or its events.

Agents normally request `issue-list`, which returns not-implemented items. Use `--state outstanding` to include implemented but unverified work, and `issue-history` only for one named issue. Moving an issue to another release changes scheduling, not implementation state, and requires a recorded decision reference.

## Monitor Without Polluting Context

Consume only meaningful events:

- Task started, blocked, unblocked, failed, completed, or crossed a planned checkpoint
- User decision required
- Scope expansion proposed
- Completion issue detected, moved, implemented, verified, or reopened
- Acceptance evidence produced

During active work, wait for task completion or attention events. Do not ingest commentary, tool logs, test logs, or subagent transcripts.

Once per hour while execution remains active:

1. Request a compact execution-task snapshot with the task coordination tools.
2. Run `monitor-snapshot` to find missed expected updates, failures, blockers, and blocking ledger issues.
3. Compare the executor's scope revision with the authoritative release revision.
4. Continue independent work when one path is blocked.
5. Intervene only for failure, stale work, drift, a missing decision, or a material schedule change.

Judge staleness from a missed `expected_update_at`, not from an ordinary quiet hour. When scheduled-task support exists, use it for the hourly reconciliation; otherwise maintain the cadence only while the coordinator task is actively running.

## Report Progress In Plain Language

Use `status` for the overall progress percentage and per-release progress. The software calculates weighted progress; do not average percentages manually.

Every substantive user report must state:

- Overall approved-roadmap progress and baseline
- Each active release's percentage and readiness
- What now works
- What is being worked on next
- Unfinished Completion Ledger count and release blockers
- Decisions needed from the user
- Effect on the release outcome or timing

Call the metric delivery progress, not delivered product value. A high percentage never overrides readiness: a 96 percent release with one blocking user journey remains not ready. Use the templates in [references/reporting.md](references/reporting.md).

## Close A Release Truthfully

Before transitioning a release to `released`:

1. Require every non-cancelled release task to be done with evidence.
2. Require zero release-blocking Completion Ledger issues outside `verified` or `superseded`.
3. Reconcile requirements, scope revision, work graph, issue history, and acceptance evidence.
4. Have the executor complete the applicable rendered, integration, failure, and recovery verification.
5. Report the final progress, delivered outcome, implemented issues, remaining non-blocking issues, and evidence in user language.

The database transition enforces the task and ledger gates. Never bypass it or describe a release as complete when the transition fails.
