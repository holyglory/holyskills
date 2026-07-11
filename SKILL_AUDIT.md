# Holy Skills Audit

Date: 2026-07-11

This audit covers the six canonical skills currently owned by Holy Skills.
Descriptions state what source and deterministic tests establish, not what a
name might imply. A passing self-test proves the advertised fixture classes and
safety invariants; it does not prove that every future repository, interface,
incident, document set, or runtime will be interpreted correctly.

## Ownership and installation topology

The service coordinator, PostgreSQL protection skill, native Board, and web
Console moved together to the independent
[DevCoordinator repository](https://github.com/holyglory/DevCoordinator). Holy
Skills retains no source, build, runtime, CI checkout, or pinned dependency on
that repository. The formal web verifier can optionally receive the path of a
separately installed coordinator at runtime; this is caller-supplied discovery,
not a repository dependency.

The earlier copied/chained installation incident remains historically recorded
in `DecisionHistory.md`. The supported installation path is now
`scripts/manage_skill_links.py`: it plans and verifies explicit runtime roots,
refuses unreviewed divergent/copy/broken/chained objects, installs direct
absolute links, preserves replaced objects in a private transaction, and can
roll back the entire transaction. It manages only the six directories present
under `skills/` and leaves unrelated third-party or independently owned skills
untouched.

Operational boundaries: the manager intentionally does not discover runtime
homes. Operators must supply each absolute root and keep the transaction on the
same filesystem as the roots it mutates. Absolute links must be migrated when a
canonical checkout moves. Runtime restart and direct `readlink`/canonical
`realpath` verification remain required after installation.

## Skill-by-skill findings

### `formal-web-ui-verification`

Honest description: a Chromium/Playwright heuristic detector for rendered DOM
geometry, clipping, occlusion, off-canvas content, media health, contrast risks,
declared areas, required-target coverage, and visible scrollbars. It is
deterministic for the browser states it reaches, but it is not a mathematical
proof or a substitute for visual, product, or accessibility review.

Improvements present:

- explicit and discovered target coverage fails closed with stable exit codes
  and reported exemptions;
- open shadow roots and Playwright-reachable frames are inspected, while
  unreachable contexts remain visible coverage gaps;
- real mobile descriptors and bounded declarative interaction states cover more
  than narrow desktop resizing without allowing arbitrary injected actions;
- entered values are excluded from reports;
- realistic must-catch fixtures and intentional-layout controls cover every
  advertised rule class.

What can improve: closed shadow roots and undeclared states cannot be discovered
externally. Chromium is not WebKit or Firefox coverage. Gradients, images,
animation, aesthetics, focus order, assistive-technology behavior, and product
suitability still need their proper review surfaces.

### `full-repo-audit`

Honest description: a manifest-verified framework for repository-wide manual
source, architecture, journey, interface, and test review. Deterministic batches
and hashes prove queue coverage and evidence identity; agents still perform the
semantic judgment.

Improvements present:

- effort and worker capability are runtime-attested only with immutable
  evidence, otherwise explicitly unverified;
- detected high-risk files require a direct lead-review ledger;
- screenshots, native evidence, traces, and formal reports are confined and
  hash-bound with route/state/viewport metadata;
- formal-report target coverage and visible-scrollbar inventories are checked;
- missing/tampered evidence, dishonest effort, and skipped high-risk review
  have realistic must-catch fixtures and valid controls.

What can improve: hashes prove identity, not whether an image or judgment is
correct. The high-risk classifier is a review floor, not proof that every
important file was recognized. Generated code, external services, unusual
languages, and ambiguous user intent can require investigation beyond the
deterministic queue.

### `full-repo-test-coverage-audit`

Honest description: a manifest-verified test-assurance audit with deterministic
structural target discovery, exact `TESTED`/`UNTESTED`/`NOT_REASONABLE`
decisions, verified test references, and optional empirical coverage ingestion.
Without a supplied runtime report it is structural/manual assurance, not an
empirical coverage measurement.

Improvements present:

- exact per-unit inventories refuse omitted deterministic targets;
- `EMPIRICAL`, `STRUCTURAL`, `MANUAL`, and `NONE` evidence remain distinct;
- referenced test paths and symbols must exist rather than merely appearing in
  prose;
- LCOV, Cobertura XML, coverage.py JSON, and Istanbul JSON are hash-bound and
  mapped to measured/covered line evidence;
- realistic omission, invented-test, stale-evidence, and justified-exclusion
  fixtures prove recall and precision.

What can improve: portable symbol scanners cannot enumerate all generated,
reflective, macro-created, metaprogrammed, or framework-discovered behavior.
Line execution does not prove assertions are meaningful. Manual targets,
scenario review, and mutation-quality review remain separate needs.

### `trace-fix-root-causes`

Honest description: an evidence-structured, prevention-first workflow and
report verifier for implementation, UI, factual, reasoning, tool-use, artifact,
service, audit, regression, and verification incidents. It guides and gates the
investigation record; it cannot independently prove that a causal explanation
is true.

Improvements present:

- installed runtime variants were reconciled into one canonical source;
- `diagnose-only` and `authorized-fix` modes prevent a report from implying
  mutation authority;
- incident class, structured evidence, evidence-linked origin/immediate-
  defect/missed-detection chain, confidence, and scope are required;
- incident-specific contracts include crash evidence and sustained same-surface
  service recovery;
- realistic fixtures cover every incident class plus false-trigger cases.

What can improve: evidence quality remains bounded by what was preserved. The
verifier proves structure and references, not hidden reasoning or causal truth.
External changes and unavailable logs must remain explicitly unconfirmed rather
than being filled with a plausible narrative.

### `ui-implementation-audit`

Honest description: an interface-source and rendered-evidence audit against
mockups and journey requirements. It checks visual, responsive, interaction,
accessibility, and journey gaps and traces visible actions through handlers,
backend/API, permissions, persistence, and tests. It does not create design
truth when requirements or render evidence are missing.

Improvements present:

- screenshot filenames must resolve to real confined evidence;
- evidence hashes bind route/state/viewport metadata and formal reports;
- action traces require exact columns and existing `path#symbol` references;
- missing handler, backend, permission, persistence, or test layers create
  findings rather than accepting invented plumbing;
- tampered/missing artifacts, invented symbols, and legitimate not-applicable
  layers have deterministic fixtures.

What can improve: artifact identity does not prove semantic or aesthetic
quality. Native automation, accessibility tools, permissions, and external
integrations need runnable environments. Unconfirmed journeys and mockups must
keep conclusions assumption-based.

### `user-journey-docs-audit`

Honest description: a lexical and structural documentation inventory,
interview workflow, and final-report gate for product purpose, users, journeys,
decision models, relevance, features, UI handoff, edge cases, implementation,
tests, and usability criteria. It detects weak or missing documentation; it does
not decide the product for the user.

Improvements present:

- visible-interface hints cover major web and native UI stacks;
- agent policy and decision logs are governance context, never confirmed
  product truth;
- the report verifier gates required headings, interview status, journey
  status, unconfirmed propagation, and the shared interaction checklist;
- native-source, policy-only, missing-interaction, and confirmation-propagation
  fixtures exercise realistic failures.

What can improve: lexical evidence can locate likely omissions but cannot infer
the user's priorities. Product purpose, ambiguous journeys, and UI assumptions
still require interview and confirmation. Rich non-text artifacts may need
separate extraction before inventory.

## Verification expectation

| Gate | Required result | Evidence or boundary |
| --- | --- | --- |
| Canonical ownership | exactly six skills | No moved component path; no seventh canonical skill |
| Repository boundary | passed | Realistic moved-path, source-path, build path, CI checkout/pin, and unexpected-skill fixtures; history and installed-skill false-positive controls |
| Link manager | passed | Plan/apply/verify/rollback, divergence refusal, source device/inode/tree snapshot revalidation, source-swap rollback recall, direct-link identity, v2 rollback compatibility, concurrency, interrupted transaction, nested-source-link refusal, and unrelated-symlink/skill preservation |
| Freshness detector | passed | Current, ahead, behind, diverged, dirty stale base, and unavailable remote scenarios using real Git repositories |
| Shared harness | synchronized | Root harness hashes match all three vendored fallback copies |
| Public artifacts | passed | Private text, credential, symlink, PNG metadata/provenance must-catch fixtures and portable controls |
| Six repository self-tests | passed | Every canonical skill's deterministic suite runs from the repository |
| Six standalone-copy self-tests | passed | Every skill runs after copying only its directory; audit skills reject a stale parent harness by using their vendored copy |
| Formal web runtime | passed | A locked Playwright/Chromium runtime exercises real fixture pages for repository and standalone runs |
| Python source | passed | Root scripts, harness, and all six skill script trees compile |

`python3 scripts/validate.py` is the complete repository gate. There is no
native-app skip mode because Holy Skills no longer owns a native application.
Environment-dependent evidence must remain labeled passed, skipped, blocked, or
pending rather than being implied by a structural pass.
