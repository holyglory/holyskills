# Holy Skills Audit

Date: 2026-08-01

This audit covers the six canonical skills currently owned by Holy Skills.
Descriptions state what source and deterministic tests establish, not what a
name might imply. A passing self-test proves the advertised fixture classes and
safety invariants; it does not prove that every future repository, interface,
incident, document set, or runtime will be interpreted correctly.

## Ownership and installation topology

The service coordinator, PostgreSQL protection skill, native Board, and web
Console moved together to an independently versioned repository. Holy Skills
retains no source, build, runtime, CI checkout, or pinned dependency on that
repository. The formal web verifier can optionally receive the path of a
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
semantic implementation, source, architecture, journey, interface, and test
review. Deterministic batches and hashes prove queue coverage and evidence
identity; responsibility-level rows with unique `Contract ID`s record the
judgment, while agents still decide whether arbitrary domain behavior is
actually complete.

Improvements present:

- effort and worker capability are runtime-attested only with immutable
  evidence, otherwise explicitly unverified;
- detected high-risk files require a direct lead-review ledger;
- every coverage unit, high-confidence named source definition, and distinct
  responsibility receives a source-backed implementation row with its own
  deterministic `batch_###:C###` ID; each row has entry anchors,
  calculation/data/side-effect trace, failure/permission/recovery evidence,
  verification, and a status-derived PASS/GAP/BLOCKED result, while PASS
  requires substantive evidence of the real outcome rather than symbol or
  type/shape presence;
- every responsibility records an enumerated authoritative or source-inferred
  basis and parsed/manual discovery bound to an assigned-unit anchor; every
  verification records one test/runtime/source-only evidence type and one
  counterfactual or invariance, while source-only evidence cannot close a
  persistence, integration, external-effect, or success PASS;
- batch prompts explicitly target marker-free gaps such as hard-coded
  calculations, ignored inputs/configuration, fake success or persistence,
  incomplete plumbing, unregistered jobs/routes, production mocks, and shallow
  outcome tests;
- a required manifest-bound `lead_reconciliation.md` maps every batch Contract
  ID exactly once into `lead:C###` cross-file traces with all nine implementation
  labels, derives each lead result from those statuses, preserves mapped gaps or
  blocked results, and records atomic lead findings and open questions; the
  lead independently reopens every PASS anchor with the same typed verification
  discipline, incrementally if needed but without sampling;
- a pass-only verification receipt binds the manifest, exact non-symlinked
  report root, and hashes for the authorized batch, journey, and lead reports;
  consolidation consumes only that receipt-bound set and merges findings only
  when all immutable fields match;
- completion-ledger plan and apply rerun the verifier while holding its exact
  report, source, effort/queue/exclusion, prompt, and artifact input closure;
  only a genuine pass whose canonical result digest matches the receipt is
  accepted, with a narrowly proven ledger-only freshness normalization;
- every verified artifact-backed audit produces a fully dispositioned external
  projection whose `review_status` is complete, including an empty projection
  when clean; an explicit user request or applicable project instruction may
  then authorize a plan/apply update that preserves unrelated active
  `CompletionLedger.md` rows and rejects raw, omitted, stale, or concurrent
  input;
- screenshots, native evidence, traces, and formal reports are confined and
  hash-bound with route/state/viewport metadata;
- formal-report target coverage and visible-scrollbar inventories are checked;
- missing/tampered evidence, dishonest effort, and skipped high-risk review
  have realistic must-catch fixtures and valid controls.
- `evals/marker-free/` can separately measure fresh-agent recall and
  intentional-lookalike precision across six marker-free gap classes when the
  cases are actually run; its self-test synthesizes oracle-derived responses
  and proves only the evaluation infrastructure, not agent performance.

What can improve: hashes and structurally valid implementation rows prove
identity and recorded coverage, not that the human/agent's semantic judgment is
correct. Static review cannot prove dynamic registration, unavailable external
services, production data behavior, or domain calculations without suitable
runtime evidence. Generated code, unusual languages, and ambiguous user intent
can require investigation beyond the deterministic queue; unresolved cases
remain blocked or open rather than being called complete.

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

### `install-delivery-efficiency-hooks`

Honest description: a cross-platform agent workflow for installing the shared
delivery-efficiency recorder into explicit Codex and Claude homes, enabling the
Codex hooks feature when the host permits it, preserving host-native trust
review, and proving fresh per-home Codex hook/task/token correlation with one
bounded persistent-history proof and filename-bearing diagnostic receipts.
Claude activation stays
host-owned and independent. The skill invokes the recorder's canonical
transactional installer; it is not another recorder, settings writer, package
manager, or trust authority.

Improvements present:

- separate macOS, Linux, native Windows, and WSL prerequisite and state-path
  guidance, including Linux-filesystem-only WSL state;
- one immutable plan retains every managed target and binds exact source,
  target, state, digest, and rollback data before apply;
- one agent-owned, digest-bound detached worker snapshots the reviewed runtime,
  proves its ready state, waits for exact affected process incarnations to
  exit, invokes the existing transaction, and saves a private filename-bearing
  terminal receipt; direct apply, verify, and rollback commands are recovery
  interfaces rather than the normal user journey;
- managed hooks migrate once to a strictly validating version-neutral launcher;
  later compatible upgrades preserve the established credential and loopback
  port and leave byte-identical host configuration untouched;
- recorder `0.2.4` writes schema `1.2` while immutable schema `1.0` and `1.1`
  events remain validated and reportable without rewriting legacy rows;
- installation, filesystem verification, Codex host trust, and fresh per-home
  task correlation are reported as distinct states;
- Codex feature activation is allowed only for the exact requested home, while
  `/hooks` review remains a visible user action and persistent trust bypass is
  prohibited;
- each reviewed Codex home receives a stable versioned reference that becomes
  an installation-keyed opaque target identity; paths, friendly labels,
  credentials, and derivation inputs do not enter durable telemetry;
- one agent-owned watch captures its own baseline and checks all selected Codex
  homes concurrently while the user only trusts each exact hook and starts one
  ordinary fresh task per instance; it requires no client quitting for serial
  proof, process isolation, sequence handling, or repeated Terminal commands,
  while preserving any one-time restart that the host requires after install;
- first installation, retirement, feature/trust changes, and credential
  generation or rotation use project-specific user-confirmed security
  assumptions, while a verified non-rotating repair that preserves established
  controls reuses the recorded posture without a blanket interview;
- the bounded status helper and watch validate the immutable plan plus
  canonical and installed payloads before importing recorder code, import only
  a private digest-matched snapshot, bracket integrity-checked store reads with
  install verification and receiver/source rechecks, and reject unbound,
  empty, wrong-source, cross-task, historical, or concurrent-drift evidence;
- the watch writes its bounded private result outside the source worktree and
  emits exactly one `REPORT_SAVED` line naming the file and aggregate
  active/pending result; timeouts and legacy family-only evidence remain honest
  non-success reports rather than activating named homes;
- rollback proof is limited to recorder-managed actions and separately restores
  a Codex feature enabled by the workflow only from a confirmed disabled state;
- realistic contract mutations plus source-drift, transaction-race,
  tool-owned-temp-alias, and fresh-versus-historical event fixtures prove the
  self-test catches the advertised safety boundaries.

What can improve: prerequisite distribution commands and host UI change outside
this repository and must be rechecked against current official sources. The CI
matrix now runs the skill contract with the recorder on native Windows, Linux,
and macOS plus a gated WSL runner, but those jobs are evidence only after they
complete for the revision; a simulated platform branch is not native proof.
Codex trust prompts remain operator-owned. Claude activation stays host-owned
and independent, and per-home target attribution is Codex-only in recorder
`0.2.3` and newer with schema `1.2`.

### `ui-implementation-audit`

Honest description: an interface-source and rendered-evidence audit against
mockups and journey requirements. It checks visual, responsive, interaction,
accessibility, and journey gaps and traces visible actions through handlers,
backend/API, permissions, persistence, and tests. It does not create design
truth when requirements or render evidence are missing, and it does not apply
before a substantive repo-owned target UI surface has been implemented.

Improvements present:

- a lead-inspected implementation file and substantive visible UI construction
  are required before artifacts or workers; an exact, verifier-bound imported,
  inherited/conformed, or constructed UI type-to-component-definition fallback
  covers manually confirmed unrecognized toolkits;
- arbitrary backend paths, UI-looking backend strings, null/route/root-mount
  scaffolds, imports, empty native shells, multi-tag/native placeholders,
  evidence-only, style-only, story/test-only, and untouched scaffold fixtures
  exit as inapplicable without artifacts;
- manifest and verifier checks bind the qualification and applicability evidence
  to source hashes, while genuinely partial web, native, custom-component, and
  uncommon-toolkit surfaces remain eligible;
- the lead records actual runtime effort provenance without a fixed high-effort
  requirement;
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
| Decision history | dense direction/decision index with one linked detail per ID | Verbose-field, weak-options, unexplained-prior-attempt, context-loss-revisit, missing/orphan/traversal/symlink-detail, and unlabeled-inference must-catch fixtures; extensive detail-file false-positive control |
| Completion ledger | canonical active-only table or absent | Terminal-row, mixed-state, contradictory-status, unknown-status, non-schema-content, duplicate-ID, and empty-ledger must-catch fixtures; active-row verification-text false-positive control |
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
