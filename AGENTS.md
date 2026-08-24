# Repo Agent Instructions

These instructions apply to every coding agent working in this repository
(Codex and Claude Code alike). "The agent" below means whichever assistant is
doing the work.

## Repository Freshness Preflight

- Before a repository-wide audit, broad refactor, migration, history rewrite,
  or repository split, run
  `python3 scripts/check_repository_freshness.py --repo "$PWD" --json` and
  inspect the freshly fetched remote-default-branch ancestry.
- `current` and `ahead` are safe ancestry states. `behind`, `diverged`, and
  `dirty-on-stale-base` require reconciliation before implementation;
  `remote-unavailable` is unknown, never evidence that the checkout is current.
- Never discard or rewrite a dirty checkout to make it current. Preserve the
  work, establish a clean checkout from the remote baseline, and use an
  evidence-backed three-way merge. Do not pull, rebase, reset, stash, or clean
  valuable local changes as a freshness shortcut.
- If remote truth is unavailable, pause architecture-changing work until it is
  restored or the user explicitly authorizes an offline baseline.

## Agent Implementation Mistake Protocol

When the user reports an agent-made mistake, apply the prevention-first loop in
the universal policy proportionally:

1. Reproduce through the same surface the user saw, or preserve the closest
   concrete evidence when exact reproduction is unavailable. Finish the useful
   diagnostic cycle after non-critical gaps instead of fixing and restarting at
   the first failure.
2. Compare the original request, later clarifications, accepted plans, project
   records, and delivered behavior to distinguish an agent mistake from changed
   intent or external state.
3. Identify the immediate gap and the check or guardrail that allowed it.
   Record the complete pass's actionable findings, then strengthen the narrowest
   effective prevention layer and prove it detects the reported gap.
4. Group findings by cause, inspect adjacent paths only where that cause is
   plausible, and fix the guardrails and complete user-facing behavior as one
   batch.
5. Rerun the complete relevant cycle, including the original surface,
   prevention check, affected paths, and completion ledger, before reporting the
   mistake handled.

Keep the response and investigation proportionate. A focused regression test
and short explanation are enough for a straightforward mistake; serious or
explicitly requested postmortems can use a concise evidence-backed report
without requiring a repository-owned workflow skill.

## Repository Agent Efficiency

- Treat `UIL-AGENT-WORKFLOW-004`, `UIL-AGENT-WORKFLOW-005`,
  `UIL-AGENT-WORKFLOW-006`, and `UIL-AGENT-WORKFLOW-015` as mandatory for every
  repository change. Complete
  finite diagnostic cycles before batch fixing, obtain informed approval before
  implementing any agent-proposed addition outside the evidence-backed agreed
  scope through one bundled plain-language decision whose approval covers the
  recorded outcome and boundaries, and keep agent-controlled context and tool
  output relevant and bounded.
- Run complete raw-output processes to a cold log when practical and return a
  concise failure index. Do not paste a full log into model context or the
  software-owned completion ledger, repeatedly read an unchanged policy or artifact, or
  request a tool-output budget above a known host ceiling.
- Do not preserve or migrate disposable test data, or add cross-account local
  hardening for a known single-user environment, unless the request or evidence
  makes that work relevant. If uncertain and the expansion is material, explain
  the benefit, cost, and consequence and ask before acting.

## User Issue Ledger Enforcement

- `UserIssueLedgers/` follows the scoped persistent prevention-ledger contract
  in the universal policy. It is checked by
  `scripts/check_user_issue_ledgers.py`; each file must remain one compact table
  for one surface, domain, or business-logic perspective, not a mixed catch-all,
  incident archive, or substitute completion ledger. Its relative path, title,
  and ID namespace must identify the same single scope; generic catch-all leaf
  names and an unsplit `BusinessLogic.md` are invalid.
- When changing this contract or its checker, add realistic must-catch fixtures
  for every advertised structural failure and false-positive guards for
  distinct but related patterns, nested business perspectives, escaped table
  characters, and safe filesystem traversal. Run the checker, its self-test,
  and the complete repository validation.

## Skill Development

- Before fixing errors, reproduce the issue or policy gap you are changing.
- Keep each skill's `SKILL.md` contract authoritative and mirror enforceable
  behavior in deterministic self-tests where possible.
- Test the changed path the same way it was reproduced.
- For detector-style skills (verifiers, auditors, linters, monitors), the
  self-test must prove recall as well as precision: include at least one
  realistic must-catch fixture per detection class the `SKILL.md` advertises,
  built the way real applications break rather than the way the detector
  measures, plus false-positive guards for common intentional patterns. A
  detector change is not validated while an advertised detection class has no
  realistic failing fixture.
- When a test or verifier missed a user-visible mistake, add realistic coverage
  for the identified cause and adjacent failure paths that plausibly share it;
  do not infer repository-wide scope from one symptom.
- Canonicalize a test-owned temporary root before deriving fixture paths when
  production correctly rejects symlinked path components. Keep a separate
  must-catch fixture proving that an operator-supplied repository or target
  path containing a symlink is still rejected; never weaken production for a
  host-managed alias such as macOS `/var -> /private/var`.
- Never deliver static mocks, fake plumbing, no-op UI, synthetic data flows, or
  "wired later" implementations as completed work.

## Skill Installation Source Of Truth

- This repository is the only writable canonical source for its five skills:
  `formal-web-ui-verification`, `full-repo-audit`,
  `full-repo-test-coverage-audit`, `ui-implementation-audit`, and
  `user-journey-docs-audit`.
  Do not hand-edit copies under Codex, Claude, Parall, or another runtime home.
- Install each repo-owned skill through `scripts/manage_skill_links.py` as a
  direct symlink to `skills/<skill>`. Preserve unrelated runtime/system skills.
- Before relying on an installed repo skill, verify its direct `readlink` and
  canonical `realpath`. Treat copied directories, chained links, broken links,
  or content drift as installation failures and repair them from this repo with
  a hash-verified rollback record.
- Removing a canonical skill does not automatically remove installed entries.
  During retirement deployment, inventory every explicit runtime root, preserve
  the old link text, and remove only a direct link whose exact target is the
  retired canonical directory. Never prune copied, divergent, or unrelated
  runtime entries by inference.
- A reviewed link plan authorizes only the exact canonical source identity and
  bytes it captured. Apply must revalidate repository/skills/skill identities
  and tree digest at every mutation boundary; never follow a source symlink or
  accept a checkout/skill swap between plan and link creation. Rollback must
  compare exact link text so source drift cannot prevent restoring the saved
  installation.

## Global Policy Source Of Truth

- `reference/codex-app-wide/AGENTS.md` is the repository-owned canonical source
  for the universal policy consumed by Codex and Claude Code. Root `AGENTS.md`
  is repository policy and must not be installed globally.
- Deploy global policy only through `scripts/manage_global_policy.py` and its
  digest-approved plan/apply/verify/rollback workflow. Name every Codex
  `AGENTS.md`, Claude `CLAUDE.md`, and private transaction directory as an
  explicit absolute path; never infer runtime homes or edit a live target
  outside the reviewed plan. Keep this workflow separate from the skill-link
  manager.
- Codex targets are direct absolute symlinks only. Claude targets on macOS,
  Linux, and WSL are direct absolute symlinks. On native Windows, use a direct
  Claude symlink when capability exists or explicitly select the one-line
  absolute `@path` import-wrapper mode when it does not; never fall back from a
  failed link to a wrapper, copy, mirror, or hard link. Reject UNC wrapper
  sources, links or reparse points in the canonical path, unsafe targets,
  source or target drift, and backup or temporary collisions.
- Preserve an existing target by adjacent same-volume rename so rollback
  restores its exact file/link object and metadata. Bind the immutable plan to
  canonical identity and bytes, target and parent snapshots, and fixed adjacent
  artifacts; require the printed plan digest for every operation. Hold and lock
  the no-follow transaction directory for each operation, journal through that
  held directory, and revalidate its identity at journal and target-mutation
  boundaries. Use atomic no-replace moves, preflight all-target rollback before
  mutation, and preserve external collision state rather than overwriting it.
  After restoring a runtime target, retain the captured deployed artifact under
  its unique reviewed temporary name; portable path APIs cannot atomically
  compare-and-delete it without risking an external replacement.
- Filesystem verification proves topology, not runtime activation. Restart both
  runtimes after apply; inspect Codex's loaded global source and use Claude
  `/memory` or `InstructionsLoaded` evidence for the canonical import. An
  external-import approval, sign-in, hook trust, or policy load status is an
  operational fact and grants no authority beyond the user's request.
- Keep root `CLAUDE.md` as a thin import of root repository policy only. The
  user-level Claude target already supplies the canonical universal policy;
  importing it again at project scope wastes context, and copying either policy
  would create another source of truth. Before consequential Claude work,
  confirm that user-level policy loaded the canonical file. If it did not, read
  the canonical file directly for that session and report the global-policy
  installation or activation gap. Claude Code reloads project memory after
  compaction.
- Changes to the deployment manager must prove exact file and link rollback,
  source, parent, and mid-operation transaction swaps, target drift, plan
  tampering, native atomic collision refusal, crash recovery at every durable
  boundary, safe rollback-artifact retention, all-target rollback preflight,
  concurrent stale plans, Windows path and PowerShell serialization,
  unrelated-file preservation, and absence of positive authorization wording. Run every
  available native Windows, WSL, Linux, and macOS job; simulations are not
  native evidence.

## Repository Ownership Boundary

- Holy Skills owns only the six skill directories listed above and the shared
  audit harness. The
  coordinator, PostgreSQL protection skill, DevOps Board, and DevOps Console
  are owned by the independent DevCoordinator repository.
- Do not add source imports, relative checkout paths, submodules, build inputs,
  CI checkouts, commit pins, runtime declarations, deployment units, packaging,
  or application artifacts from DevCoordinator to this repository.
- `formal-web-ui-verification` may accept a caller-supplied path to a separately
  installed coordinator script to discover already-running URLs. That optional
  runtime adapter must remain path-agnostic and must not become a source,
  checkout, build, CI, or version dependency.
- Every repository completion ledger is DevCoordinator2's planning database,
  reached through its reviewed tools (`plan_overview`, `task_create`,
  `task_update`, `task_history`), which own active queries, permanent
  history, transitions, and imports.
- Run `python3 scripts/check_repository_boundaries.py --repo "$PWD"` as part of
  every validation and ownership-affecting change. Keep historical migration
  prose in `MERGE_IMPROVEMENT_LEDGER.md`; do not weaken the current-tree
  detector to hide a real dependency.
