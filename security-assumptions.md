# Security Assumptions

Status: user-confirmed on 2026-08-01.

## Scope

These assumptions govern the repository-sharing, software-owned delivery
database, and scheduled product-delivery monitoring decisions recorded below.
They do not establish the security posture of unrelated applications or
projects.

## Linux development server

Confirmed by the user on 2026-08-09:

- The entire Linux server is the user's development server.
- The `holyglory`, `holygloryTT`, `slawa`, and `axel` accounts and their Codex
  CLI instances are controlled by the user and are used for different projects.

## Shared VPS repository access

Confirmed by the user on 2026-08-15:

- The `holyglory`, `holygloryTT`, `slawa`, and `axel` accounts are four
  workspaces of the same human operator and are mutually trusted for source
  repository access on this development VPS.
- Every account requires equal read, write, and traversal access to every Git
  working tree, linked worktree, Git metadata directory, and bare repository
  discovered under `/home`. New files and directories inside those repository
  roots must inherit the same access.
- Repository-associated roots containing incomplete or stale `.git` markers
  receive the same filesystem ACLs so a repaired or materialized workspace is
  immediately usable. They do not receive Git trust or repository
  configuration until Git validates them as repositories.
- Ancestor directories receive traversal only where needed to reach a
  repository. Non-repository home content is not made readable or writable by
  this decision, and service/system accounts are not added to the trust set.
- Git owner-safety exceptions are explicit per discovered repository and per
  account; a global wildcard trust exception is unnecessary.

## Shared product-delivery database

Confirmed by the user on 2026-08-20:

- The `holyglory`, `holygloryTT`, `slawa`, and `axel` accounts are one human
  operator and use the same authoritative product-delivery state for a shared
  repository.
- The software-owned completion ledger and work graph live in the primary
  checkout's ignored `.product-delivery/delivery.sqlite3`, and all four
  accounts require equal read, write, locking, and traversal access to it.
  Linked worktrees resolve the same Git common directory and therefore the
  same database.
- The database permanently retains issue and event history. Routine agent
  queries load only the bounded active projection or one named issue's bounded
  history.
- Ledger records contain concise project requirements, incomplete outcomes,
  impact, states, decisions, and evidence references. Raw logs, credentials,
  secrets, source dumps, prompts, and tool payloads remain outside the ledger.
- No Markdown, chat-memory, or per-account fallback ledger is authorized when
  the shared database is unavailable.

## Scheduled product-delivery monitoring

Confirmed by the user on 2026-08-20:

- Ongoing product-delivery monitoring is an hourly scheduled task inside the
  existing coordinator chat. Independent scheduled runs do not satisfy the
  requirement because they lose the coordinator's working context.
- The scheduled task uses the coordinator chat's established project and
  permission boundary; scheduling does not grant broader filesystem, network,
  credential, production, or scope authority.
- Local monitoring depends on the desktop app remaining open, the computer
  staying on, and the project remaining available on disk. Loss of those
  conditions makes monitoring unavailable rather than authorizing a fallback.
- Durable monitoring state may retain opaque coordinator, executor, host,
  automation, run, and cursor identifiers plus cadence, timestamps, concise
  outcomes, blockers, and evidence references. It does not retain raw thread
  output, prompts, logs, source content, credentials, or tool payloads.
- Monitoring is not armed until schedule creation and an immediate first run
  are verified. Missing automation capability or a failed run is reported as a
  blocker and never represented as ongoing supervision.
