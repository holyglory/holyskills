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

When the user reports an implementation mistake likely made by the agent,
handle it as a prevention-first incident unless the evidence shows the user
changed their mind or the requested behavior changed after implementation.

1. Reproduce the reported error through the same surface the user saw whenever
   it is possible and reasonable. If it cannot be reproduced, record why and
   gather the closest concrete evidence available.
2. Check whether the failure is actually a changed requirement. Compare the
   original request, later clarifications, accepted plans, project docs, and
   delivered behavior before treating it as an agent mistake.
3. If the request was not changed, trace why the mistake happened before
   changing product code. Inspect the user intent, how the agent perceived the
   request, requirements, journey docs, design handoff, implementation, tests,
   verifier rules, audit outputs, tool choices, policies, skills, context, and
   handoff assumptions.
4. Identify the nearest durable guardrail that allowed the mistake: local
   `AGENTS.md`, project documentation, acceptance criteria, tests, verifier,
   skill instructions, checklist, policy, or context source.
5. Before editing `AGENTS.md` or another policy file, check guardrail scope and
   proportionality. A repo `AGENTS.md` is repo policy, not global policy.
   Policy text must be a generalized reusable rule, not an explanation of a
   specific incident. Put incident narratives, timelines, and one-off root
   causes in the root-cause report, `DecisionHistory.md`, or a targeted test.
6. Fix that system guardrail first when practical. If a skill or audit missed
   the issue, update the skill or deterministic check and rerun it against the
   same evidence so it now catches the gap.
7. Audit the testing procedure that failed to catch the mistake. Look for other
   likely missed failures in adjacent journeys, edge cases, failure paths,
   integrations, generated artifacts, and user-visible acceptance criteria.
   Add or update tests for those risks, not only the one reported symptom.
8. Close the implementation gap only after the prevention layer is patched, or
   explicitly explain why the product fix had to be done first.
9. After the detected gap is closed, run comprehensive tests that prove the
   user gets the expected result. Include the original reproduction path, the
   new or updated guardrail/check, and the broader tests from the testing
   procedure audit before reporting done.

Keep one-off local mistakes separate from broad process changes, but bias
toward durable prevention when the same class of mistake could recur.

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
- When a test or verifier missed a user-visible mistake, audit neighboring
  testing gaps and add comprehensive post-fix coverage before delivery.
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
