# Holy Skills

Holy Skills is the canonical public source for five portable Codex and Claude
Code skills and one shared delivery-efficiency recorder. It contains audit,
verification, documentation, and observational agent-runtime tooling; it does
not own or deploy local-service coordination products.

The coordinator, PostgreSQL protection skill, native DevOps Board, and web
DevOps Console are independently versioned in
[holyglory/DevCoordinator](https://github.com/holyglory/DevCoordinator).
Holy Skills does not import, clone, pin, build, or test that repository.

## Canonical skills

- `formal-web-ui-verification`: a deterministic Playwright/Chromium heuristic
  for rendered geometry, visibility, clipping, overlap, media health, target
  coverage, declared areas, and visible scrollbars. It can optionally consume
  URLs from a separately installed coordinator script supplied by the caller.
- `full-repo-audit`: a manifest-verified semantic implementation review with
  deterministic responsibility-level `Contract ID`s (`batch_###:C###` and
  lead-reconciliation `lead:C###`), cross-file reconciliation, evidence binding,
  atomic findings, and a required reviewed external active-ledger projection;
  applying that projection to a repository remains authorization-gated.
- `full-repo-test-coverage-audit`: a structural test-assurance audit with exact
  target decisions, validated test references, and optional empirical coverage
  ingestion.
- `ui-implementation-audit`: a source- and evidence-bound audit used only once
  a substantive product UI surface exists, covering rendered behavior,
  journeys, handlers, backend paths, permissions, persistence, and tests.
- `user-journey-docs-audit`: a lexical and structural documentation audit for
  product intent, users, journeys, feature/UI inventories, edge cases,
  implementation expectations, tests, and usability acceptance criteria.

`full_repo_harness/` is the canonical shared Python harness used by the three
repository/UI audit skills. Each of those skills carries a synchronized
vendored copy so its directory remains independently installable and testable.

## Layout

- `skills/`: the five canonical skill packages.
- `full_repo_harness/`: shared audit discovery, evidence, batching, queue, and
  verification code.
- `scripts/validate.py`: the complete five-skill and standalone-copy gate.
- `scripts/manage_skill_links.py`: transactional direct-link installation and
  rollback for explicit runtime roots.
- `scripts/manage_global_policy.py`: digest-approved plan/apply/verify/rollback
  deployment of the one universal policy to explicit Codex and Claude files.
- `scripts/check_repository_freshness.py`: fetched remote-ancestry preflight for
  broad repository work.
- `scripts/check_repository_boundaries.py`: exact ownership/dependency guard
  that prevents moved components or checkout/build/CI pins from returning.
- `scripts/check_ci_security.py`: rejects pull-request execution on self-hosted
  runners while retaining trusted push and manual native-platform jobs.
- `scripts/check_app_wide_policy.py`: semantic contract guard for the universal
  policy.
- `scripts/check_decision_history.py`: compact decision-index, selective detail,
  stable-ID, and anti-loop guard.
- `scripts/check_completion_ledger.py`: open-only active-work ledger guard;
  absence is the valid state when no work remains.
- `scripts/check_user_issue_ledgers.py`: recursive, no-follow validation for
  persistent scoped user-correction ledgers; absence is valid before the first
  qualifying correction.
- `scripts/public_artifact_guard.py`: public-text, symlink, and PNG provenance
  guard.
- `tools/delivery-efficiency/`: the shared cross-runtime recorder, versioned
  adapter contract, Codex and Claude Code translators, exact Claude prompt
  correlation with a legacy session-generation fallback, transactional
  installer for Codex homes and Claude `settings.json` targets, and
  platform/privacy/crash tests.
- `SKILL_AUDIT.md`: honest capabilities, improvements, and residual limits for
  all five skills.
- `DecisionHistory.md`: compact major-decision and project-direction index.
- `DecisionDetails/`: one cold supporting record per indexed decision.
- `UserIssueLedgers/`: compact persistent prevention rules separated by
  surface, domain, or business-logic perspective.
- `EfficiencyLedger.jsonl` remains deliberately absent from this layout. The
  installed recorder creates it in platform-native user state outside this
  checkout and routine context.

`DecisionHistory.md` is routine context; `DecisionDetails/` is not. The index
contains one evidence-linked `Direction:` paragraph, then entries with this
exact shape:

```markdown
## [D-YYYYMMDD-NN — Short title](DecisionDetails/D-YYYYMMDD-NN.md)

Decision: The selected direction.

Why: Concise rationale. Options: selected A over rejected B because A fits the goal. Prior attempts: B failed in the observed way. Intent: durable user or project preference this reveals. Revisit only if: new evidence or a changed requirement invalidates the reason.
```

Use `Options: no material alternative` and `Prior attempts: none known` when
true; never invent either. `Why` captures the underlying project direction,
quality bar, workflow expectation, and UI taste that future work should follow.
The top synthesis labels `Confirmed:` user intent separately from `Inferred:`
patterns and cites the supporting decision IDs. A detail file starts with the
matching ID/title and an index backlink, and holds all evidence, implementation,
verification, chronology, and sources. Open only the detail relevant to a
decision being applied, challenged, superseded, or explicitly audited.

`CompletionLedger.md` exists only while requested work remains incomplete. Its
resolved rows are removed in the completing change, and the file is deleted
when no active items remain. Git is the default completion history; a separate
`CompletionHistory.md` is created only for an explicit audit-retention need and
is not routine working context.

When present in this repository, the ledger contains only its title and one
table with this exact schema:

```markdown
# Completion Ledger

| ID | Remaining work | Why it matters | Status | Verification |
| --- | --- | --- | --- | --- |
| Q-1 | Replace the temporary bridge. | The production path is incomplete. | Open | Exercise the real path end to end. |
```

Every field is required and IDs are unique. Status begins with `Active`,
`Blocked`, `In progress`, `Incomplete`, `Open`, `Partial`, `Pending`, `To do`,
`TODO`, `Unresolved`, or `Waiting`. Do not add prose, checklists, extra tables,
or terminal rows outside the schema; history belongs in the sources named
above.

`UserIssueLedgers/` is a different lifecycle: its rows remain after a fix so a
later task cannot repeat the same user-indicated mistake. It contains multiple
narrow ledger files, not one repository-wide catch-all. Typical routes include
`UI.md`, `Automation.md`, `CodingStyle.md`, and nested business perspectives
such as `BusinessLogic/Pricing.md` or `BusinessLogic/Permissions.md`; projects
create only the ledgers their confirmed corrections require. A file contains
only this shape:

```markdown
# User Issue Ledger: UI

| ID | Applies to | Mistake pattern | Required behavior | Prevention and verification |
| --- | --- | --- | --- | --- |
| UIL-UI-001 | Collection destinations | The creation form displaced the collection. | Show the collection or honest state first. | Exercise populated, empty, and long-list creation flows. |
```

Ledger and directory names use concise UpperCamelCase slugs; IDs are globally
unique `UIL-<SCOPE>-NNN` values. The path, title, and ID namespace identify the
same owner: for example, `BusinessLogic/Pricing.md` is titled
`Business logic / pricing` and uses `UIL-BUSINESS-LOGIC-PRICING-NNN`. This
binding makes a mixed `Everything.md` fail validation rather than merely
looking scoped. Generic leaf names such as `Everything.md`, `General.md`, and
`Misc.md`, plus an unsplit `BusinessLogic.md`, are rejected. Put each pattern
in its narrowest owner and do not duplicate it across files. Before
implementation, agents inventory the tree and read the ledgers relevant to the
affected UI, coding style, automation, or business perspectives;
repository-wide work reads them all. Rows contain reusable applicability,
required behavior, and verification—not prompts, incident chronology, status,
blame, or implementation history. A row is removed only after an explicit
retraction or recorded superseding decision; an empty scoped file is deleted.

Delivery-efficiency measurement is a runtime boundary, not a project ledger.
`tools/delivery-efficiency/` implements that boundary with one shared recorder
core and thin Codex and Claude adapters. It writes authoritative observations
to a SQLite WAL spool and projects a concurrency-safe cold
`EfficiencyLedger.jsonl` outside source worktrees. The schema separates phase
from activity state, measurement from attribution provenance, request wall
time from execution time, and runtime observation from agent-declared outcome,
scope, and verification. Unsupported host boundaries and counters remain
explicitly partial or unknown rather than being estimated or recorded as zero.

The recorder uses a positive privacy allowlist. Prompt and assistant text,
transcripts, source and working paths, filenames, commands, tool arguments and
results, raw errors, secrets, credentials, account data, and personal data do
not enter its durable schema. Source identifiers are converted in memory to
installation-keyed opaque IDs.

The runtime is deliberately not a sixth skill. A skill activates after model
work has begun and cannot own request receipt. Installation therefore copies a
hash-bound version into native per-user state without relying on symlinks or
administrator privileges. Native Windows and WSL use separate stores; WSL
state must remain on its Linux filesystem rather than `/mnt/*` or `\\wsl$`.

Every verified artifact-backed full-repo audit produces a reviewed ledger
projection outside the audited repository, including an empty projection for a
clean audit. Verified batch reports and the required manifest-bound
`reports/lead_reconciliation.md` feed atomic candidates through a pass-only
receipt that binds the exact report root and hashes; every candidate must be
disposed and top-level `review_status` set to `complete`. Its plan/apply importer
reruns the verifier over guarded current reports, sources, companion records,
prompts, and evidence artifacts and requires that canonical pass result to
match the receipt. It runs only when ledger mutation is authorized by an
explicit user request or applicable project instruction, preserves unrelated
active rows, never prunes, and writes only confirmed unresolved obligations
into this five-column schema.
Raw findings, hypotheses, audit limitations, and resolved evidence remain
outside the ledger.

## Install the delivery-efficiency recorder

The recorder requires Python 3.9 or newer and otherwise uses only the standard
library. Run installation from the canonical checkout and name every Codex and
Claude home explicitly; one plan may cover both runtimes or either alone.
Planning writes a private transaction plus a reviewable journal; the journal
contains the authentication-token digest, never the token.

Configuring a Claude home also probes `claude --version` and requires Claude
Code 2.1.212 or newer. Anthropic's
[v2.1.212 release notes](https://github.com/anthropics/claude-code/releases/tag/v2.1.212)
identify that release as fixing OTLP/HTTP exports for endpoints that reject
chunked transfer encoding. The recorder is intentionally such a bounded
receiver, so the installer rejects 2.1.211 and earlier even though the
[hook `prompt_id` correlation field](https://code.claude.com/docs/en/hooks#common-input-fields)
exists from v2.1.196. Use `--claude-executable` with an absolute path when the
intended binary is not on `PATH`.

On macOS, Linux, or WSL:

```bash
python3 tools/delivery-efficiency/recorder.py install plan \
  --codex-home "cli=$HOME/.codex" \
  --codex-home "desktop=/absolute/path/to/desktop-codex-home" \
  --claude-home "user=$HOME/.claude"
```

On Windows PowerShell:

```powershell
python .\tools\delivery-efficiency\recorder.py install plan `
  --codex-home "cli=$env:USERPROFILE\.codex" `
  --claude-home "user=$env:USERPROFILE\.claude"
```

The platform-native default state locations are:

| Runtime environment | Default cold state |
| --- | --- |
| Windows | `%LOCALAPPDATA%\HolySkills\DeliveryEfficiency` |
| macOS | `~/Library/Application Support/HolySkills/DeliveryEfficiency` |
| Linux | `${XDG_STATE_HOME:-~/.local/state}/holyskills/delivery-efficiency` |
| WSL | the Linux location above, on the WSL filesystem |

Review the printed `journal_path`, `plan_sha256`, source digest, target digests,
port provenance, and exact homes. The immutable `plan.json` is the review
baseline; every disk-loaded apply, verify, or rollback requires its printed
digest so changing both the mutable journal and its recorded digest cannot
silently change the reviewed topology. Then apply and verify the same journal:

```bash
python3 tools/delivery-efficiency/recorder.py install apply \
  --journal "/absolute/state/transactions/<plan-id>/journal.json" \
  --plan-digest "<plan_sha256>"
python3 tools/delivery-efficiency/recorder.py install verify \
  --journal "/absolute/state/transactions/<plan-id>/journal.json" \
  --plan-digest "<plan_sha256>"
```

For an upgrade, rotate the receiver credential inside the transaction rather
than supplying or copying the existing secret:

```bash
python3 tools/delivery-efficiency/recorder.py install plan \
  --codex-home "cli=$HOME/.codex" \
  --codex-home "desktop=/absolute/path/to/desktop-codex-home" \
  --claude-home "user=$HOME/.claude" \
  --rotate-auth-token
```

The journal records only the new token's digest. A private plan sidecar carries
the generated token through apply, and rollback restores the exact prior
settings, hooks, and OTel configuration. Version or token ownership changes
must name every retained target recorded in the private
`<state>/managed-targets.json`; an omitted Codex or Claude home is refused
rather than left with a stale credential. An ordinary idempotent subset update
retains omitted targets in that inventory and never interprets omission as
retirement. On POSIX the inventory and every secret-bearing settings file are
forced to mode `0600`; Windows uses the containing directory's inherited ACL
and the standard-library installer makes no stronger ACL-hardening claim.
Ownership changes select a distinct receiver port by default and
reject an explicitly reused port, so installation never kills an unknown
process merely because it owns the old port. Recorders at version 0.1.2 and
newer also retire themselves after confirmed valid settings drift. A pre-0.1.2
receiver cannot perform that hand-off; it may remain harmlessly on the
now-unused old port until its process ends while the upgraded configuration
targets the new authenticated receiver.

Retire a target only by binding its previously recorded name and absolute path
explicitly. Retirement removes only the exact installer-owned hooks and
telemetry environment or OTel block, preserves unrelated configuration, and is
covered by the same digest-bound rollback:

```bash
python3 tools/delivery-efficiency/recorder.py install plan \
  --retire-claude-home "user=$HOME/.claude"
```

Use `--retire-codex-home` for Codex. These flags accept the same absolute paths
on macOS, Linux, and WSL and PowerShell-native absolute paths on Windows.

Apply installs a read-only versioned copy and a stable
`<state>/recorder.py` launcher, merges named handlers into each `hooks.json`,
and appends an authenticated OTLP/HTTP JSON block only when `config.toml` does
not already own `[otel]`. A Claude home receives managed hook handlers and the
managed telemetry environment inside its `settings.json` (`hooks` plus
`CLAUDE_CODE_ENABLE_TELEMETRY` and the authenticated OTLP logs exporter
variables), preserving every unrelated key. Prompt, tool-detail, tool-content,
and raw-body export are pinned off in that user settings file. The managed
block sets `OTEL_METRICS_EXPORTER=none`, `OTEL_TRACES_EXPORTER=none`, both trace
beta switches to `0`, every prompt/assistant/tool/raw-body gate to `0`, and the
account/session/resource metric-attribute switches to `false`. Anthropic's
[environment-variable rules](https://code.claude.com/docs/en/env-vars#precedence)
define `0` or `false` as the off values for ordinary boolean switches, and its
[monitoring reference](https://code.claude.com/docs/en/monitoring-usage#common-configuration-variables)
defines `none` as the disabled exporter.

Claude gives project, local, CLI, and organization-managed settings higher
precedence than user settings. The installer cannot control those external
scopes: a higher-precedence override could route telemetry elsewhere or enable
raw bodies before the recorder sees anything, so the recorder allowlist is not
a defense for that path. Treat such an override as an external privacy and
instrumentation conflict; use managed settings to lock the same selectors and
content gates when organization-wide enforcement is required, and verify the
active sources with Claude's `/status` after restart.
Claude command hooks use its native `command` plus `args` exec form, so the
absolute Python, recorder, and state paths never pass through POSIX shells,
`cmd.exe`, or PowerShell tokenization on macOS, Linux, WSL, or Windows.
Existing OTel routing — a Codex `[otel]` table or a user-owned `OTEL_*` or
`CLAUDE_CODE_ENABLE_TELEMETRY` value — plus malformed configuration, source
drift, target drift, symlinks/junctions, and edited prior managed blocks are
checked at preflight and again immediately before each mutation. Recorder
installer processes sharing the state root are serialized by persistent
single-link lock files. Plans require every active Codex or Claude home to
already exist; planning provisions only recorder-owned state, install, and
transaction directories.

Each changed target uses immutable adjacent stage, prior, and recovery slots.
An existing target first moves no-replace into its prior slot, and the reviewed
stage then moves no-replace into the vacant target; the target can therefore be
briefly absent, but no namespace occupant is overwritten. On Windows the exact
top-level staged file or directory stays held without delete sharing and is
published by handle with `SetFileInformationByHandle(FileRenameInfo)`,
`ReplaceIfExists = FALSE`, then checked by volume/file ID before release.
POSIX uses held parent descriptors with native no-replace rename flags. A
racing target or slot occupant is restored when safe or retained as a recovery
artifact and the transaction fails; it is never path-unlinked or silently
replaced. Rollback uses the same move-only, no-replace state machine and keeps
every transaction artifact until an operator deliberately retires it.

The unconditional collision guarantee covers managed target names and the
exact top-level staged object. Private transaction metadata and random stage
internals are cooperative per-user state protected by the containing account's
ACL plus installer locks; digests detect accidental drift before and after
publication, but hostile mutation by another process running as that same OS
account is not an integrity boundary. The receiver is activated only after the
published content passes verification. Unsupported filesystem primitives fail
closed without a check-then-replace fallback. Rollback restores exact prior
bytes only while the installed digests observed by its checks still match:

```bash
python3 tools/delivery-efficiency/recorder.py install rollback \
  --journal "/absolute/state/transactions/<plan-id>/journal.json" \
  --plan-digest "<plan_sha256>"
```

Restart each Codex and Claude Code runtime after apply. Codex user hooks are
intentionally not marked trusted behind Codex's back: open `/hooks`, review the
exact installed command, and trust it; until then Codex hook coverage remains
an instrumentation gap. Claude Code loads `settings.json` hooks at session
start without a Codex-style trust grant. Its `/hooks` surface is useful for
inspection, but viewing it is not an activation or approval step. Claude
authentication and the recorder's loopback authentication token establish
identity only; neither grants the agent authority beyond the user's request.
The installer starts and health-checks the authenticated loopback receiver, and
a configured lifecycle hook starts it on demand in later sessions, after any
host-required hook trust step. Hook trust enables that telemetry hook only; it
does not authorize unrelated agent actions.
Managed Codex hooks retain the three-second host timeout but give receiver
startup and event posting one shared 2.25-second deadline. The remaining 0.75
seconds is reserved for interpreter, host, and bounded input/output overhead;
an exhausted telemetry budget records a gap when possible and returns without
extending the hook deadline. Claude `SessionStart` remains synchronous with a
ten-second command timeout and an 8.5-second cold-start budget. The synchronous
`UserPromptSubmit` hook is contractually capped at a one-second host timeout
and 0.75-second telemetry budget so a failed recorder cannot materially hold
every prompt. Asynchronous `SubagentStart`, `SubagentStop`, `Stop`, and
`StopFailure` hooks retain a three-second host timeout and 2.25-second telemetry
budget without blocking Claude's next action. Per-tool, `SessionEnd`, and
`MessageDisplay` hooks are not installed because their blocking frequency or
marginal boundary value does not justify their delivery overhead; the adapter
retains defensive fallback support for host events received through another
supported path. The subagent hooks record partial presence and an explicit
coverage gap, not a measured subagent lifetime or activity interval.

No durable native cold-start benchmark artifact is committed. The portable
enforced bounds are the 0.75-second internal deadline and one-second Claude
host timeout. Functional startup and ingestion require successful native job
evidence for each claimed platform; simulated branches and workflow
definitions are not substitutes for those results.

Supported Claude hooks expose a UUID-v4 `prompt_id` that matches OTLP
`prompt.id`. The recorder uses that transient exact identity for task starts,
activity, and late token usage, including OTLP that arrives before the hook or
after Stop and an agent declaration. Runtime family and session are included
before keyed opaque persistence, so equal Codex and Claude source values cannot
collide. Missing or changed OTLP correlation stays unbound; deterministic
per-session generations exist only as a partial legacy fallback for hooks that
omit the prompt ID.

Claude OTLP `api_request`, `api_error`, `tool_result`, and rejected
`tool_decision` events add allowlisted native activity, outcome, and duration
evidence without retaining raw content. Token mapping remains
`cache_read_tokens` to `cached_input` and `cache_creation_tokens` to `other`;
unsupported reasoning and tool-token categories stay null. `report` keeps
recorder-clock interval unions separate from runtime-native duration sums.
Those native sums retain measurement and attribution provenance, count equal
hook/OTLP evidence for one tool span once, and become unknown on conflicts;
they are never called wall time.

Inspect health and outcome-aware summaries through the stable launcher:

```bash
python3 "/absolute/state/recorder.py" status
python3 "/absolute/state/recorder.py" report
```

`report` fails closed unless every authoritative spool HMAC and sequence agrees
with the exact canonical cold-ledger bytes; a merely parseable or edited JSONL
file is never treated as measured evidence. Immutable schema `1.0` rows remain
validated and reportable; recorder `0.2.1` writes schema `1.1`, and reports
identify compatible mixed `1.0`/`1.1` ledgers without rewriting either version.
This compatibility does not assert that every universal-policy measurement is
available for legacy events.

Hooks and provider-native events record observable boundaries. Agents use the
same launcher only for facts the host cannot know, at meaningful phase changes
and immediately before terminal delivery:

```bash
python3 "/absolute/state/recorder.py" declare phase start \
  --phase testing --activity tool-active --span verification
python3 "/absolute/state/recorder.py" declare phase end \
  --phase testing --activity tool-active --span verification
python3 "/absolute/state/recorder.py" declare terminal \
  --outcome complete --verification verified \
  --task-kind primary --cause not-applicable \
  --acceptance-baseline request-v1 --no-scope-changes \
  --task-type implementation --scope-size medium --method hybrid \
  --requirement scope=satisfied:verified \
  --evidence scope=validation:self-test
```

Codex and Claude Code sessions add their runtime-specific
`--runtime <codex|claude> --binding <opaque-binding>` values; each managed
`SessionStart` hook exchanges the raw session ID with the authenticated local
receiver and reinjects only the exact launcher argv plus the signed
installation-local binding. The context is silent by default and grants no
authority beyond the user's request.

The declaration command binds to the current runtime session and refuses
cross-session tasks. The receiver resolves one task once and commits every
event from one declaration command as one transaction, so a concurrent prompt
cannot split requirement and terminal events across tasks. A conflict rolls
back the whole batch. Declaration deduplication is scoped to that resolved task:
an exact batch replay remains safe after its terminal, while any new declaration
for an already-terminal task is rejected; identical declaration shapes may be
used by a later task in the same session. A declared terminal does not upgrade
the host's delivery-boundary coverage: that boundary remains partial unless the
runtime itself exposes it. Phase declarations pass through the authenticated
receiver so separate launcher invocations share one process-owned monotonic
clock domain. If that receiver restarts between boundaries, the duration is
reported as unknown rather than combined across clocks or filled with zero.

For controlled automation, wrap `codex exec` while preserving its JSONL stdout:

```bash
python3 "/absolute/state/recorder.py" codex-exec -- \
  "summarize the repository"
```

Successful process exit alone is not recorded as completed scope. Supply
`--outcome`, `--verification`, and one or more explicit
`--requirement ID=STATUS:VERIFICATION` options only when the automation owns
that acceptance decision.

## Install as direct links

This repository is the only writable source for its five skills. Never edit an
installed copy. Discover every runtime's actual skills root and pass each one
explicitly; do not infer desktop or sandbox homes from the shell's `$HOME`.

```bash
REPO_ROOT="/absolute/path/to/holyskills"
CODEX_SKILLS_ROOT="/absolute/path/to/codex-home/skills"
CLAUDE_SKILLS_ROOT="/absolute/path/to/claude-config/skills"
PARALL_SKILLS_ROOT="/absolute/path/to/desktop-codex-home/skills"

python3 scripts/manage_skill_links.py plan \
  --repo-root "$REPO_ROOT" \
  --target-root "$CODEX_SKILLS_ROOT" \
  --target-root "$CLAUDE_SKILLS_ROOT" \
  --target-root "$PARALL_SKILLS_ROOT"
```

Review copied, divergent, broken, chained, or noncanonical paths before
replacement. Preserve intentional unique changes in their canonical owner
first. Apply into a new mode-private transaction directory on the same
filesystem as every named root:

```bash
install -d -m 700 "$HOME/.local/state/holyskills/backups"
python3 scripts/manage_skill_links.py apply \
  --repo-root "$REPO_ROOT" \
  --target-root "$CODEX_SKILLS_ROOT" \
  --target-root "$CLAUDE_SKILLS_ROOT" \
  --target-root "$PARALL_SKILLS_ROOT" \
  --transaction-dir "$HOME/.local/state/holyskills/backups/$(date +%Y%m%d-%H%M%S)" \
  --allow-noncanonical
```

Then verify with the same roots:

```bash
python3 scripts/manage_skill_links.py verify \
  --repo-root "$REPO_ROOT" \
  --target-root "$CODEX_SKILLS_ROOT" \
  --target-root "$CLAUDE_SKILLS_ROOT" \
  --target-root "$PARALL_SKILLS_ROOT"
```

Verification requires each managed destination to be a direct absolute symlink
whose `readlink` names the canonical directory and whose `realpath` resolves to
the same directory. The plan binds repository, `skills`, and per-skill
device/inode identities plus a canonical tree digest. Apply revalidates those
snapshots after transaction creation, immediately before and after each link,
and during final verification; a swapped checkout or skill source fails and
rolls back without following the replacement. The canonical `skills` tree must
therefore contain no symlinks. Unrelated repository and third-party runtime
entries are preserved. Version-2 journals remain rollback-compatible. Keep the
transaction directory until fresh Codex, Claude, and desktop sessions discover
the links; skill metadata is loaded at session startup.

The link manager does not prune an installed entry when its canonical skill is
retired. During retirement deployment, inventory each explicit runtime root,
preserve the old link text, and remove only a direct link whose exact target is
the retired canonical directory. Do not infer that copied, divergent, or
unrelated runtime entries may be deleted.

## Deploy the universal global policy

`reference/codex-app-wide/AGENTS.md` is the canonical app-wide Codex policy and
the universal cross-runtime policy loaded through each configured user-level
runtime target.
Root `AGENTS.md` is Holy Skills repository policy and must not be installed
globally. Root `CLAUDE.md` remains a thin relative import of repository policy;
the user-level Claude target already supplies the canonical universal policy,
so the project file does not import the same policy twice. Its startup text
requires a session-local direct read and an installation-gap report if that
user-level policy is absent or not activated.

Use only `scripts/manage_global_policy.py` to deploy the universal file. The
manager infers no home directory: every destination and the private transaction
directory must be an explicit absolute path. Planning records only prior object
type, digest or raw link text, and metadata—never prior policy contents—and
prints a SHA-256 that must be copied into apply, verify, and rollback. Each
operation holds and locks a no-follow transaction directory, journals through
that held directory on POSIX, and revalidates transaction, target, parent,
canonical-source, backup, and temporary identities at their relevant journal
and mutation boundaries. Native Windows additionally holds target-parent and
transaction-directory handles without delete sharing so their names cannot be
swapped during an operation. Existing regular files or links move to an adjacent
same-volume backup without copying, and all live name moves use native atomic
no-replace operations so a collision is preserved instead of overwritten.
Multiple targets are recoverably transactional rather than one cross-filesystem
atomic operation; rollback preflights all targets and restores them in reverse
order.

On macOS, Linux, and WSL, deploy direct absolute links for both runtimes:

```bash
python3 scripts/manage_global_policy.py plan \
  --repo-root "/absolute/path/to/holyskills" \
  --transaction-dir "/absolute/private/state/global-policy-transaction" \
  --codex-target "/absolute/codex-home/AGENTS.md" \
  --claude-target "/absolute/claude-home/CLAUDE.md"
```

Repeat either target option for another explicitly reviewed runtime instance.
On WSL, use the checkout and runtime homes visible inside WSL; do not substitute
native Windows paths or a `\\wsl$` spelling. Codex is direct-link-only on every
platform. On native Windows, direct links remain available when the account has
symlink capability. If that capability is unavailable, select the Claude-only
wrapper explicitly—failure to create a direct link never triggers this mode:

```powershell
python .\scripts\manage_global_policy.py plan `
  --repo-root 'C:\absolute\path\to\holyskills' `
  --transaction-dir 'C:\absolute\private\state\global-policy-transaction' `
  --claude-windows-import-wrapper-target 'C:\absolute\claude-home\CLAUDE.md'
```

That fallback transaction intentionally contains no Codex target: Codex remains
direct-link-only, so enable Windows Developer Mode or run with symlink privilege
and use a separate reviewed `--codex-target` plan before deploying Codex.

The wrapper is exactly one UTF-8/LF absolute `@C:/.../AGENTS.md` import line;
UNC/network sources and control characters are rejected. Its path serialization
is tested on every CI platform, while only a native Claude load check can prove
activation for a particular path. Anthropic documents absolute imports,
recommends this import topology where Windows symlinks are unavailable, and may
show a first-use approval prompt for an external import. See the
[Claude memory documentation](https://code.claude.com/docs/en/memory).

Plan prints the exact digest-bound apply command. Use the same transaction and
digest for the remaining operations:

```bash
python3 scripts/manage_global_policy.py apply \
  --transaction-dir "/absolute/private/state/global-policy-transaction" \
  --plan-digest PLAN_SHA256
python3 scripts/manage_global_policy.py verify \
  --transaction-dir "/absolute/private/state/global-policy-transaction" \
  --plan-digest PLAN_SHA256
python3 scripts/manage_global_policy.py rollback \
  --transaction-dir "/absolute/private/state/global-policy-transaction" \
  --plan-digest PLAN_SHA256
```

Rollback restores every runtime destination exactly. It intentionally retains
the captured deployed link or wrapper under the unique temporary path printed
as `retained_rollback_artifact`; deleting it automatically would reintroduce a
check/unlink race that could remove an external writer's replacement. The
retained object is inert because no runtime destination names it, and can be
reviewed and removed explicitly by the operator.

Immediate apply is bound to the reviewed canonical file identity and digest.
Later verify accepts normal canonical edits while still requiring the exact
link/import topology, because propagation without copied mirrors is the point
of this deployment. After apply, restart each runtime. For Codex, inspect the
loaded global instruction source; for Claude, use `/memory` or an
`InstructionsLoaded` observation to confirm the canonical path. Filesystem
installation, external-import approval, sign-in, hook trust, and telemetry
state are operational facts only; none expands what the user's request permits.

## Development and validation

Before a repository-wide audit, broad refactor, migration, history rewrite, or
split, run the freshness preflight and inspect its fetched ancestry result:

```bash
python3 scripts/check_repository_freshness.py --repo "$PWD" --json
```

`current` and `ahead` are safe ancestry states. Reconcile `behind`, `diverged`,
or `dirty-on-stale-base` from an isolated remote-fresh checkout without
discarding dirty work. `remote-unavailable` is unknown, not current.

The complete repository gate is:

```bash
python3 scripts/validate.py
```

It proves the exact five-skill layout, the recorder schema/privacy/storage and
adapter contracts, universal-policy semantics, compact
decision-history integrity, open-only completion-ledger state, freshness and
dependency-boundary and self-hosted-CI detector recall, vendored-harness synchronization,
skill-link and global-policy transaction/rollback behavior, public-artifact policy, interaction-label
parity, all five in-repository self-tests, recorder concurrency/crash/install
tests, Python compilation, all five standalone copied skill tests, and a copied
recorder test. CI installs a locked
Playwright runtime solely because the remaining formal web verifier requires a
real Chromium run. The workflow defines a separate Python 3.9/3.13 recorder
matrix for native Windows, Linux, and macOS with required loopback ingestion;
a job definition is not evidence that the job completed. Real WSL evidence
requires the separately labeled WSL runner. Injected platform branches and
simulated selection tests never replace a successful native result.

When changing a skill:

1. Reproduce the behavior or policy gap before editing.
2. Keep `SKILL.md` authoritative.
3. Add realistic must-catch and intentional-pattern controls for detector
   changes.
4. Run the changed path and the complete repository gate.
5. Keep generated audits, temporary runs, caches, secrets, and private rollback
   transactions out of Git.

This repository is public. Use portable fixture identities and paths, bind
publishable artifacts to isolated fixture provenance, and never commit private
workspace paths, credentials, customer data, or live runtime captures.
