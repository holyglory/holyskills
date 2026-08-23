# Product Delivery Coordinator

`coordinate-product-delivery` turns repository requirements into approved release scopes, keeps an authoritative database work graph and permanent Completion Ledger, dispatches one primary execution task, monitors milestone events, mediates scope changes, and reports weighted progress in plain language.

Invoke it deliberately with `$coordinate-product-delivery`. It is intended for ongoing repository delivery governance, not ordinary implementation, a one-off plan, code review, or isolated delegation.

## Operating Model

- One coordinator task owns product intent, release baselines, decisions, monitoring, and user reports.
- One primary execution task handles implementation and may spawn its own subagents.
- The bundled shared SQLite engine owns releases, requirements, tasks, dependencies, completion percentages, transactional imports, permanent incomplete-work history, and progress calculation.
- The normal Completion Ledger query returns only not-implemented work; implemented and verified history remains permanently available by issue ID.
- True product expansion always returns to the user for a plain-language decision.
- Monitoring requires an enabled scheduled task inside the same coordinator chat, one compact hourly reconciliation, retained executor cursor, overlap-safe run keys, and a verified first run. Missing automation capability is reported as unarmed and blocked; active-turn polling is never a fallback.

## State Engine

Initialize the per-repository database:

```bash
python3 scripts/delivery_state.py --project /absolute/path/to/repository init
```

Read current progress and unfinished work:

```bash
python3 scripts/delivery_state.py --project /absolute/path/to/repository status
python3 scripts/delivery_state.py --project /absolute/path/to/repository issue-list
```

The command interface is the only supported writer. The default database is the primary checkout's shared `.product-delivery/delivery.sqlite3`, used by linked worktrees and trusted local accounts. Do not edit it directly, commit it, or create a parallel `CompletionLedger.md` in any repository.

`gantt-data` produces renderer-neutral schedule data. A separately installed DevCoordinator may render it only when capability discovery advertises a compatible delivery or Gantt action; the skill does not depend on a DevCoordinator checkout or guess unsupported commands.
