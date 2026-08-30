# Holy Skills

Holy Skills is the canonical public source for six portable Codex and Claude
Code skills. It contains audit, verification, and documentation tooling; it
does not own or deploy local-service coordination products.

The coordinator, PostgreSQL protection skill, native DevOps Board, and web
DevOps Console are independently versioned outside this repository. Holy Skills
does not import, clone, pin, build, or test their source repository.

## Canonical skills

- `formal-web-ui-verification`: the deterministic web engine for declared
  journeys, rendered geometry, continuation, contrast/theme checks, responsive
  coverage, screenshot pairs, and changed-review evidence.
- `full-repo-audit`: a manifest-verified semantic implementation review with
  deterministic responsibility-level `Contract ID`s (`batch_###:C###` and
  lead-reconciliation `lead:C###`), cross-file reconciliation, evidence binding,
  atomic findings, and a required reviewed external active-ledger projection;
  applying that projection to a repository remains authorization-gated.
- `full-repo-test-coverage-audit`: a structural test-assurance audit with exact
  target decisions, validated test references, and optional empirical coverage
  ingestion.
- `ui-implementation-audit`: an explicit-invocation-only, source- and
  evidence-bound audit used once a substantive product UI surface exists,
  covering missing screens/states, mockup and journey alignment, source wiring,
  native and web visual judgment, and tests. It imports formal web evidence
  instead of recreating it and leaves worker effort to the runtime/user.
- `user-journey-docs-audit`: a lexical and structural documentation audit for
  product intent, users, journeys, feature/UI inventories, edge cases,
  implementation expectations, tests, and usability acceptance criteria.

`full_repo_harness/` is the canonical shared Python harness used by the three
repository/UI audit skills. Each of those skills carries a synchronized
vendored copy so its directory remains independently installable and testable.

## Layout

- `skills/`: the six canonical skill packages.
- `full_repo_harness/`: shared audit discovery, evidence, batching, queue, and
  verification code.
- `scripts/validate.py`: the complete six-skill and standalone-copy gate.
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
- `scripts/check_user_issue_ledgers.py`: recursive, no-follow validation for
  persistent scoped user-correction ledgers; absence is valid before the first
  qualifying correction.
- `scripts/public_artifact_guard.py`: public-text, symlink, and PNG provenance
  guard.
- `SKILL_AUDIT.md`: honest capabilities, improvements, and residual limits for
  the audited skills.
- `UserIssueLedgers/`: compact persistent prevention rules separated by
  surface, domain, or business-logic perspective.

Decisions and the completion ledger live in DevCoordinator2's planning
database: record decisions with `decision_record` (aspect, plain
management-facing title and body, `supersedes`, stable `ref`), load context
with `decision_tail`, search with `decision_search`, and store rolling
summaries with `decision_summarize` when a read reports `summary_due`.
Work items are `task_create`/`task_update` tasks sized in estimated lines
of code; issues and events are permanent, and normal queries return the
bounded active projection. A database outage keeps affected work
incomplete.

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

## Install as direct links

This repository is the only writable source for its seven skills. Never edit an
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

It proves the exact six-skill layout, universal-policy semantics, compact
decision-history integrity, database-only completion-ledger policy and schema,
freshness and
dependency-boundary and self-hosted-CI detector recall, vendored-harness synchronization,
skill-link and global-policy transaction/rollback behavior, public-artifact policy, interaction-label
parity, all six in-repository self-tests, Python compilation, and all six
standalone copied skill tests. CI installs a locked
Playwright runtime solely because the remaining formal web verifier requires a
real Chromium run.

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
