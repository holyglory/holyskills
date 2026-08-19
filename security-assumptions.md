# Security Assumptions

Status: user-confirmed on 2026-08-01.

## Scope

These assumptions govern installation, repair, activation, and operation of the
HolySkills delivery-efficiency recorder for these user-owned runtimes:

- Codex at `$HOME/.codex`
- Parall Codex at
  `$HOME/Library/Application Support/Parall/ChatGPT (TT)/.codex`
- Claude Code at `$HOME/.claude`

They do not establish the security posture of unrelated applications or
projects. Reuse the confirmed answers below for routine recorder work. Ask only
about an unresolved assumption that is material to a concrete pending control
decision and whose wrong answer could cause unnecessary controls, an omitted
necessary control, expanded work, or meaningful rework.

## Linux development server

Confirmed by the user on 2026-08-09:

- The entire Linux server is the user's development server.
- The `holyglory`, `holygloryTT`, `slawa`, and `axel` accounts and their Codex
  CLI instances are controlled by the user and are used for different projects.
- Recorder state, credentials, receiver, and counters remain separate per OS
  account. Within each account, events retain project/repository attribution by
  design; counters must not be combined across accounts or repositories.
- The current installation scope is only the `holygloryTT` Codex home. The
  other three accounts require their own explicit installation operations.

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
- Repository sharing does not combine recorder state, credentials, counters,
  or repository attribution. Delivery-efficiency stores remain separate per
  OS account as confirmed above.

## Confirmed assumptions

- **Users and operators:** This is a personal macOS account. The user owns and
  trusts all three named runtimes. No unrelated users or administrators operate
  them.
- **Environment and ownership:** The recorder is local-only, runs under the
  same account, and communicates over loopback. It is not a shared, remote, or
  network service.
- **Allowed telemetry:** Lifecycle metadata, timing, provider-native token
  counters, runtime and version metadata, and opaque correlation identifiers.
- **Prohibited telemetry:** Prompts, responses, source content, commands, tool
  payloads, credentials, and personal content.
- **Credible threats:** Configuration drift, an unrelated owner of the same
  runtime configuration, unintended network exposure, and unauthenticated
  local submissions.
- **Out of scope:** Root compromise, malware, and a malicious process already
  running as this same OS account.
- **Necessary gates:** One canonical repository source; immutable installed
  runtime copies; a loopback bearer credential; digest-reviewed
  plan/apply/verify/rollback; explicit runtime homes; preservation of unrelated
  settings; fail-closed conflict and drift handling; manual Codex `/hooks`
  review; and no trust bypass.
- **Explicitly unnecessary gates:** An administrator daemon, TLS on loopback,
  cross-account local hardening, credential rotation without compromise or
  contrary evidence, a remote collector, and migration or preservation of
  disposable telemetry.
- **Accepted risks and costs:** A same-account process can read the local
  credential; hooks can add minor latency or fail; local metadata is retained;
  and activation may require runtime restarts and manual trust review.
- **Review triggers:** Reassess the material assumptions if the machine or
  account becomes shared, another OS account is involved, the recorder becomes
  remotely reachable, sensitive or regulated scope is introduced, compromise
  is suspected, runtimes or homes change, ownership changes, or deployment is
  added on native Windows, WSL, or Linux.

## Current recorder decision

The recorder `0.2.9` installation upgrade keeps the established loopback
boundary, bearer credential, explicit homes, and host trust gate. It preserves
the `0.2.3` opaque per-Codex-home correlation contract and adds a same-user,
local-only, detached one-shot installer handoff. Existing `0.2.4` through
`0.2.6` deferred jobs remain status/cancel observable, but never become mutable
by current installer code.

For the confirmed `holygloryTT` Linux target, the worker separately binds the
transient remote client/proxy, persistent app-server daemon, and owned helpers
to one reviewed plan, exact process incarnations, exact Codex executable and
pathname identity, exact `CODEX_HOME`, reported CLI/app-server versions, and
reported lifecycle backend. A nonempty backend selects the captured
executable's fixed native `app-server daemon stop` with a platform-owned system
path, never caller `PATH`.

The confirmed macOS remote client currently runs a legacy Linux
`app-server --listen unix://` whose version response has no backend; Codex's
own bootstrap refuses to adopt it while it runs. The bridge waits for the bound
proxy to exit, opens pidfds for each exact reviewed code-mode host and the exact
reviewed server incarnation, rechecks owner, creation, executable path and
inode, sends graceful `SIGTERM` to each bound host before the server, and never
signals a bare PID or uses `SIGKILL`. It waits for each exact process to exit,
invokes the exact Codex executable's bootstrap with the explicitly reviewed
`code_mode_host` feature, requires a real managed backend, then invokes Codex's
native stop before transactional apply/verify. This
process-lifecycle control is supported by the confirmed single-developer,
same-account environment and accepted restart requirement. It adds no
privilege, network exposure, credential, cross-account access, service, or
trust bypass and touches none of the other confirmed accounts.

The same confirmed environment may contain unrelated same-UID processes inside
nested container PID namespaces. When Linux denies their executable identity,
the recorder may exclude one from same-image relaunch inventory only when the
kernel `NSpid` chain proves its namespace depth differs from every exact
reviewed target. A candidate at a reviewed target's namespace depth, malformed
or unavailable namespace evidence, and every readable same-image peer remain
fail-closed. This narrow exclusion is supported by the confirmed
single-developer server, same-account ownership, and explicit exclusion of a
malicious same-account process; it does not weaken exact target capture,
pidfd-bound termination, cross-account separation, or relaunch detection within
the reviewed namespace.

The worker uses private bounded state, saves a privacy-bounded receipt, and
expires. It is not a daemon, scheduler, login item, remote service,
authorization mechanism, or trust bypass.

Recorder `0.2.9` may read the host-supplied transcript path only for the exact
managed Codex home and only when it resolves to a regular non-symlinked bounded
`rollout-*.jsonl` beneath that home's session directories. The adapter accepts
only task-boundary records and provider-native token-counter fields; it neither
copies nor persists prompt, response, reasoning, tool, command, path, or source
content. A private integrity-protected repository basename supports readable
local reports, while the cold ledger and optional Coordinator projection retain
only opaque project identity. This uses the confirmed same-account local
runtime and allowed token/lifecycle metadata without adding network, account,
credential, or trust boundaries.

The handoff wait covers a realistic delayed return but remains bounded and
nonpersistent; an OS reboot kills it and requires agent-owned replan/rearm. A
read-only recovery status may report a canonical exact job-and-digest-bound
receipt across volatile filesystem device-identity drift only when the receipt
strictly proves that mutation never started and claims no verification,
receiver health, rollback, trust, activation, or success. This narrow behavior
is supported by the confirmed single trusted account and the explicit
exclusion of a malicious same-account process. Apply, rearm, successful
verification, rollback, trust, and activation continue to require the complete
reviewed transaction and drift gates.

Compatible upgrades keep the confirmed credential and loopback port and route
managed hooks through a strictly validating version-neutral launcher. Rotation,
privilege, extra hardening, and new network or account boundaries remain
unselected without a review trigger or concrete contrary evidence. Native
Windows, WSL, or deployment to another Linux account still requires the
smallest material assumption review for that actual target; the current Linux
decision covers only the confirmed `holygloryTT` home, and portable tests do not
claim deployment elsewhere.
