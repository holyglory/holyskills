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

Treat a concrete report of broken in-scope behavior as authorization for a
safe, bounded repair unless the user explicitly requests diagnosis, review, or
no changes. Do not require a second “fix it” message.

For an ordinary isolated bug, use this direct proportional path without loading
a formal incident workflow:

1. Reproduce through the same surface the user saw, or preserve the closest
   concrete evidence when exact reproduction is unavailable.
2. Establish the immediate cause and the check that missed it. Investigate
   changed requirements, broader documentation, policies, or other subsystems
   only when evidence makes them plausible contributors.
3. Fix the complete user-facing gap and add a focused regression check when
   practical. Do not delay the safe fix for speculative policy or process work.
4. Update a skill, verifier, documentation, or policy only when it is the
   evidence-backed owner of a repeatable creation or detection gap. Keep
   one-off narratives out of policy files.
5. Retest the original surface and run risk-proportionate adjacent checks.
   Expand to a repository-wide audit or broad matrix only when explicitly
   requested or concrete blast-radius evidence justifies it.
6. Report routine fixes with a concise outcome, cause, change, and verification.
   Use the formal four-section incident report only for an explicit postmortem
   or a serious, recurring, systemic, destructive, or disputed incident.

Load `trace-fix-root-causes` before the first product-code edit when the user
requests root-cause analysis/postmortem, the failure meets that formal-incident
threshold, or a skill, audit, verifier, detector, or prior claimed verification
missed it.

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

- This repository is the only writable canonical source for its six skills:
  `formal-web-ui-verification`, `full-repo-audit`,
  `full-repo-test-coverage-audit`, `trace-fix-root-causes`,
  `ui-implementation-audit`, and `user-journey-docs-audit`.
  Do not hand-edit copies under Codex, Claude, Parall, or another runtime home.
- Install each repo-owned skill through `scripts/manage_skill_links.py` as a
  direct symlink to `skills/<skill>`. Preserve unrelated runtime/system skills.
- Before relying on an installed repo skill, verify its direct `readlink` and
  canonical `realpath`. Treat copied directories, chained links, broken links,
  or content drift as installation failures and repair them from this repo with
  a hash-verified rollback record.
- A reviewed link plan authorizes only the exact canonical source identity and
  bytes it captured. Apply must revalidate repository/skills/skill identities
  and tree digest at every mutation boundary; never follow a source symlink or
  accept a checkout/skill swap between plan and link creation. Rollback must
  compare exact link text so source drift cannot prevent restoring the saved
  installation.

## Global Policy Source Of Truth

- `reference/codex-app-wide/AGENTS.md` is the repository-owned canonical source
  for app-wide Codex policy. Root `AGENTS.md` is repository policy and must not
  be installed globally.
- On a runtime intentionally managed from this checkout, make each discovered
  Codex global `AGENTS.md` a direct absolute symlink to that canonical reference
  rather than maintaining copied mirrors. Preserve and compare an existing file
  before replacement, and verify both exact `readlink` text and canonical
  `realpath` afterward.

## Repository Ownership Boundary

- Holy Skills owns only the six skill directories listed above and the shared
  audit harness. The coordinator, PostgreSQL protection skill, DevOps Board,
  and DevOps Console are owned by the independent DevCoordinator repository.
- Do not add source imports, relative checkout paths, submodules, build inputs,
  CI checkouts, commit pins, runtime declarations, deployment units, packaging,
  or application artifacts from DevCoordinator to this repository.
- `formal-web-ui-verification` may accept a caller-supplied path to a separately
  installed coordinator script to discover already-running URLs. That optional
  runtime adapter must remain path-agnostic and must not become a source,
  checkout, build, CI, or version dependency.
- Run `python3 scripts/check_repository_boundaries.py --repo "$PWD"` as part of
  every validation and ownership-affecting change. Keep historical migration
  prose in `DecisionHistory.md` or `MERGE_IMPROVEMENT_LEDGER.md`; do not weaken
  the current-tree detector to hide a real dependency.
