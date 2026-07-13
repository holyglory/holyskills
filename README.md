# Holy Skills

Holy Skills is the canonical public source for five portable Codex and Claude
Code skills. It contains audit, verification, and documentation workflows; it
does not own or deploy local-service coordination products.

The coordinator, PostgreSQL protection skill, native DevOps Board, and web
DevOps Console are independently versioned in
[holyglory/DevCoordinator](https://github.com/holyglory/DevCoordinator).
Holy Skills does not import, clone, pin, build, or test that repository.

## Canonical skills

- `formal-web-ui-verification`: a deterministic Playwright/Chromium heuristic
  for rendered geometry, visibility, clipping, overlap, media health, target
  coverage, declared areas, and visible scrollbars. It can optionally consume
  URLs from a separately installed coordinator script supplied by the caller.
- `full-repo-audit`: a manifest-verified repository review framework with
  deterministic batches, evidence binding, lead review, and merged findings.
- `full-repo-test-coverage-audit`: a structural test-assurance audit with exact
  target decisions, validated test references, and optional empirical coverage
  ingestion.
- `ui-implementation-audit`: a source- and evidence-bound UI implementation
  audit covering rendered behavior, journeys, handlers, backend paths,
  permissions, persistence, and tests.
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
- `scripts/check_repository_freshness.py`: fetched remote-ancestry preflight for
  broad repository work.
- `scripts/check_repository_boundaries.py`: exact ownership/dependency guard
  that prevents moved components or checkout/build/CI pins from returning.
- `scripts/public_artifact_guard.py`: public-text, symlink, and PNG provenance
  guard.
- `SKILL_AUDIT.md`: honest capabilities, improvements, and residual limits for
  all five skills.
- `DecisionHistory.md`: dated architecture and ownership decisions.

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

## Global Codex policy source

`reference/codex-app-wide/AGENTS.md` is the canonical app-wide Codex policy.
Root `AGENTS.md` is Holy Skills repository policy and must not be installed
globally. For runtimes intentionally managed from this checkout, preserve and
compare any existing global policy, then make every discovered global
`AGENTS.md` a direct absolute symlink to the canonical reference. Verify both
the exact `readlink` target and `realpath`; copied mirrors will drift.

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

It proves the exact five-skill layout, freshness and dependency-boundary detector
recall, vendored-harness synchronization, link-manager rollback behavior,
public-artifact policy, interaction-label parity, all five in-repository
self-tests, Python compilation, and all five self-tests from standalone copied
skill directories. CI installs a locked Playwright runtime solely because the
remaining formal web verifier requires a real Chromium run.

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
