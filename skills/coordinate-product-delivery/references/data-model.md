# Product Delivery Data Model

## Contents

1. Backend selection
2. Database lifecycle
3. Release and task model
4. Completion Ledger model
5. Progress calculation
6. Command map
7. Gantt rendering

## Backend Selection

Use the bundled `scripts/delivery_state.py` database as the authoritative state engine unless the project has already recorded another compatible software-owned backend. Never keep two writable graphs or ledgers.

The bundled engine derives one database identity from the repository's Git common directory, so linked worktrees share delivery state. By default it stores the SQLite file in the platform's per-user state directory. Use `--db /absolute/path` only when the project has deliberately established that exact location.

Do not commit the SQLite database to the repository. Do not open it in an editor or mutate it with raw SQL. Use the command interface so validation, permanent history, and release gates remain effective.

## Database Lifecycle

Initialize or verify:

```bash
python3 "$SKILL_ROOT/scripts/delivery_state.py" --project "$REPO" init
```

All commands emit JSON. Mutations require `--actor` with a stable agent, user, or task identity. Individual fields are bounded, issue and event deletion is rejected, and database identity is bound to the Git repository.

If a command fails, preserve its structured error. Do not retry a state mutation with different data merely to make it pass.

## Release And Task Model

Release states:

```text
draft -> approved -> active -> acceptance -> released
                     |              |
                     +-> paused <---+
```

Cancellation is terminal. Releasing requires every non-cancelled task to be done and every release-blocking completion issue to be verified or superseded.

A scope revision begins at 1. Use `release-rebaseline` with a decision reference for every approved change to the release boundary. Work orders bind the exact value as `<release-id>:r<revision>`.

Task states:

```text
planned | ready | in_progress | blocked | review | done | failed | cancelled
```

Task completion is an integer from 0 through 100. State `done` and completion 100 require each other. Completion requires evidence and no linked blocking issue outside `verified` or `superseded`.

Dependencies form an acyclic directed graph. The database rejects self-dependencies and cycles.

## Completion Ledger Model

Completion issue states:

```text
detected -> planned -> in_progress -> implemented -> verified
              |             |
              +-> blocked <-+

implemented | verified | superseded -> reopened
```

The current issue row is a projection. The `events` table is the permanent story. Each mutation appends an immutable event with actor, timestamp, summary, evidence reference, previous state, next state, and bounded metadata.

Implemented issues remain queryable forever. `implemented` means the work exists; `verified` means the observable result was proven. Reopening appends history and makes the issue not implemented again.

Normal queries:

```bash
# Default: detected, planned, in-progress, blocked, and reopened issues.
python3 "$SKILL_ROOT/scripts/delivery_state.py" --project "$REPO" issue-list

# Include implemented but unverified issues.
python3 "$SKILL_ROOT/scripts/delivery_state.py" --project "$REPO" \
  issue-list --state outstanding --release R1

# Read the bounded permanent story of one issue.
python3 "$SKILL_ROOT/scripts/delivery_state.py" --project "$REPO" \
  issue-history --id CI-104 --limit 100
```

Moving an issue requires a decision reference and does not change implementation state. A moved blocking issue continues to exist; update affected release scope and task links consistently.

## Progress Calculation

Each task stores:

- `completion`: evidence-based completion from 0 through 100
- `weight`: the task's contribution to its release delivery plan

The database calculates:

```text
release progress = sum(task weight * task completion) / sum(task weight)
```

Each release also has a weight. Overall approved-roadmap progress is the same weighted calculation across non-cancelled releases.

Do not describe this as business value. Product value may remain unrealized until a whole journey works. Report readiness separately from progress.

Changing scope, task weights, or release weights can change the percentage without implementation progress. Record the new baseline and explain that distinction.

## Command Map

Create and govern scope:

```text
release-create
release-rebaseline
release-transition
requirement-create
```

Build and operate the graph:

```text
task-create
task-update
dependency-add
release-show
task-show
status
```

Maintain permanent incomplete-work history:

```text
issue-create
issue-link-task
issue-transition
issue-move
issue-note
issue-list
issue-history
```

Monitor and render:

```text
events
monitor-snapshot
gantt-data
```

Run `delivery_state.py <command> --help` for the exact options. Do not reconstruct SQL or invent a missing command.

## Gantt Rendering

`gantt-data --release <id>` emits `holyskills.product-delivery.gantt.v1` with release dates, task dates, durations, completion, owners, and dependencies. This is renderer-neutral derived data; the database remains authoritative.

When the separately installed DevCoordinator advertises a compatible delivery-graph or Gantt-rendering capability, use its documented action with this data. Capability discovery must precede invocation. Do not infer support from the executable merely being installed, guess an unadvertised command, import a DevCoordinator checkout, or add a repository dependency.

When no compatible rendering capability is advertised, keep Gantt data available and report that the rendered view is unavailable. Do not generate a second authoritative schedule.
