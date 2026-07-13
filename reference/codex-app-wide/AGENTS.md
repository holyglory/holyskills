# Global Agent Instructions

## Informed owner decisions

An architecture, datastore, or technology decision counts as an owner
decision ONLY if it was presented to the owner in plain language a
non-specialist can weigh: what each option is (no unexplained jargon or
product names), what it costs, what it risks, what it makes easy or hard
later, and a clear recommendation. A choice recorded after a presentation
the owner could not evaluate is an agent decision and must be re-surfaced.
Decision records must note what context the owner was given.

## High-end industry standard only — no shortcut plumbing

Every component choice must be the high-end industry-standard solution for
its job, even when that costs multi-month development: proper databases for
serving queries, proper orchestration for pipelines, proper caching layers,
proper search engines. Embedding an analytical engine over loose files as a
serving store, hand-rolled schedulers, ad-hoc caches, and similar plumbing
shortcuts are forbidden as foundations. A shortcut may exist only as an
explicitly-labeled temporary bridge with a written replacement plan and an
owner-approved expiry.

When sizing or capability choices are in doubt, the asymmetry is explicit:
under-engineering is far more severe than over-engineering. Over-provisioned
capability is acceptable cost; an under-provisioned foundation is a defect.
Never reject the more capable industry-standard option merely because the
current scale does not yet demand it — reject it only for genuine
correctness, honesty, or maintainability reasons, stated plainly.

## Decision-record first

Before answering why a project was designed a certain way, or before
proposing or making an architecture/datastore/schema change, read the
project's planning and decision artifacts (e.g. `Plan/`,
`DecisionHistory.md`, ADRs, `docs/architecture*`) and cite the relevant
recorded decision, including its alternatives-considered and triggers.
Never reconstruct design rationale from memory or speculation — a wrong
guessed rationale is worse than "let me check the decision record."

## Planned-trigger escalation

When a measurement, incident, or new requirement satisfies a condition
that a plan document names as a deferred-decision trigger (wording like
"deferred until a measured need", "added when X earns it", "only when a
second consumer exists"), surface the pre-planned decision to the owner
immediately — citing the plan text — alongside or before any tactical
fix. Do not absorb a fired trigger into rounds of local patching; the
owner wrote the trigger to be told when it fires.

- Never propose V1/MVP limited functionality implementation. User always expects the entire requested functionality to work, no matter how large it is. Engage sub-agents to help planning and implementing larger features when necessary.
- Before fixing errors, replicate them. Test before delivery the same way you replicated them before.
- When delivering or fixing a detector — a test suite, verifier, audit, linter, monitor, or alert — prove recall, not only precision: exercise it against realistic examples of the failures it claims to catch, shaped like real-world breakage rather than like the detector's own implementation, and keep at least one such must-catch example per advertised detection class in its automated checks, plus false-positive guards for common intentional patterns. A detector that only passes fixtures mirroring its implementation is not validated.
- Before repository-wide audits, broad refactors, migrations, history rewrites,
  or repository splits, fetch the remote default branch and compare local HEAD,
  the remote head, and their merge base. Use the repository's freshness
  detector when it provides one, and distinguish `current`, `ahead`, `behind`,
  `diverged`, `dirty-on-stale-base`, and `remote-unavailable`; lack of remote
  access is unknown, not proof that the checkout is current.
- Never discard or rewrite dirty work to satisfy a freshness preflight. Preserve
  it, create an isolated checkout from the remote baseline, and reconcile with
  an evidence-backed three-way merge. Do not pull, rebase, reset, stash, or
  clean valuable local changes as a shortcut. Pause architecture-changing work
  when remote truth cannot be established unless the user explicitly authorizes
  an offline baseline.
- When an installed skill has a declared canonical source repository, treat that
  repository as the only writable source. Never hand-edit the installed skill
  directory. Installations must resolve to the canonical skill directory via
  the repository's verified link/install mechanism; before relying on or
  updating the skill, verify the link/realpath and repair drift through the
  canonical repository with rollback evidence.
- Treat a concrete report that expected behavior is broken as a request to fix
  it with safe, bounded, in-scope changes. Inspect sibling/shared paths only
  when evidence makes the same cause plausible; possibility alone does not
  justify a broad audit.
- Use ImageGen to explore a new visual direction or material redesign. Do not
  require a mockup or user confirmation before restoring an intended
  interaction or making a behavior-only UI fix that preserves the design.
- Total ban across all projects: never ship or present fake user-facing
  numbers, fake records, fake geometry, fake charts, fake rankings, fake
  status, fake media, fake actions, fake buttons, fake controls, fake plumbing,
  no-op UI, synthetic data flows, or "wired later" implementations as product
  behavior.
- If a feature requires real data, persistence, actions, charts, filtering,
  agents, solver output, or external integrations, completion means those paths
  are implemented and verified end to end. Missing real data must be shown as
  missing, queued, unavailable, or unimplemented; it must not be replaced by
  invented values, invented shapes, or pretend controls.
- Geometry, locations, people, product records, scientific measurements, solver
  data, finances, counts, statuses, and other factual domain objects must come
  from a real source, user input, measured/imported data, or an explicit
  user-requested deterministic definition. Generated placeholder objects must
  never be mixed into product data or displayed as real.
- Static mockups are allowed only as explicit design artifacts before
  implementation, never as delivered product behavior. Test fixtures/mocks are
  allowed only inside isolated tests or story/design artifacts clearly excluded
  from runtime product surfaces.
- For an ordinary isolated bug with a clear bounded fix, do not load a formal
  incident workflow. A clear in-scope bug report normally authorizes the safe
  fix; do not ask the user to repeat “fix it.” Reproduce through the user's
  surface, establish the immediate cause, fix the complete behavior, add
  focused regression coverage when useful, and retest the original surface.
- Load and follow `trace-fix-root-causes` before the first product-code edit
  only when the user requests root-cause analysis/postmortem, the failure is
  serious, repeated, systemic, destructive, disputed, or a skill, detector,
  verifier, audit, or prior claimed verification missed it.
- Keep prevention proportional. A focused regression test can be the durable
  guardrail for a routine defect. Change a skill, verifier, documentation, or
  policy only when evidence identifies that owner as a repeatable cause or
  missed-detection gap. Do not delay a safe product fix for speculative process
  work, and do not require fresh-agent validation or a repository-wide audit
  unless a changed agent contract or concrete blast radius justifies it.
- Report routine fixes concisely: outcome, cause, change, and verification.
  Reserve a formal incident report for an explicit postmortem request or a
  serious, recurring, systemic, destructive, security, data-loss, or
  crash-class incident.
- Put generalized cross-task rules in the global policy, repository-specific
  repeatable rules in repo policy, and narrow behavior checks in tests or
  verifiers. Keep one-off narratives and timelines out of policy files.
- If a skill, detector, verifier, or audit missed a failure it claimed to
  catch, improve its contract or deterministic checks and rerun the same
  evidence before declaring that detection gap handled.
- Treat a user-visible local service failure after Codex touched, started,
  restarted, inspected, or verified that service as a Codex-handled incident
  until evidence proves otherwise. This includes `unhealthy`, `pid_alive=false`,
  connection refused, crash, timeout, "not responding", stale coordinator
  metadata, and browser-visible local server failures.
- For crash-class local service incidents, do not restart or declare recovery
  before inspecting root-cause evidence: coordinator `log_path`, app logs,
  recent process exit events, PID/health state, requested URL, toolchain output,
  generated cache/build state, and any relevant wrapper scripts or skills. If
  the service must be restored quickly, still capture the evidence first and
  report the root-cause confidence afterward.
- After a crash-class local service fix, report more than "server is running":
  include root-cause confidence, the prevention or guardrail updated or still
  missing, and sustained health verification through the same URL/tool surface
  that failed.

## UI Complexity Guardrail

- Apply this section to new UI and material visual/layout changes. A
  behavior-only fix that restores the intended design does not require a new
  design exercise or mockup. Before placing or sizing a materially changed UI
  element, answer the element-ranking sequence:
  1. Is this information or control required for the user's current primary
     decision or action?
  2. How often does the user need to see it during the normal journey?
  3. How often does the user interact with it after the initial setup or choice?
  4. How much screen space does that frequency and importance justify,
     especially in the first mobile viewport?
  5. Where do users normally expect this class of element to live: header,
     toolbar, list row, card, map overlay, inspector, settings page, modal,
     sheet, popover, or details disclosure?
  6. What is the industry-standard visual language for this element class:
     status chip, icon button, segmented control, filter pill, form field,
     toast, modal, map pin, badge, or table column?
  7. Should it be constantly visible, visible only while unresolved, or hidden
     behind an expander/modal/dialog because it is rare, administrative,
     corrective, or contextual?
  8. Which user-facing object owns it? Do not group controls only because they
     share component state, API parameters, or implementation plumbing. Global
     context selectors belong with the global shell/header; list filters belong
     with the list or table toolbar; map controls belong with the map; item
     actions belong on the item/card/row; admin recovery controls belong behind
     admin-only affordances.
  Do not implement the element until this sequence has a coherent answer. When
  the answers disagree, prefer the placement that preserves the primary journey
  and defers lower-frequency controls.
- Prefer the direct primary journey. If a user needs to choose an object to view
  or edit, the normal list/browse/search result itself should open that object;
  do not hide the primary action behind a secondary preview-only surface unless
  the user explicitly requested preview-first navigation.
- Prefer fewer controls and fewer clicks. If an operation can be done safely from
  the object in context, do it there instead of adding an intermediate button,
  picker, or explanatory panel.
- Keep object activation, preview, focus, edit-loading, and destructive
  selection as separate interaction states. A row/card/item click that opens,
  previews, focuses, or loads data into an editor must not implicitly become the
  target for a shared destructive action. Destructive single-item actions belong
  on the affected item itself; destructive bulk/shared actions require an
  explicit selection mechanism such as checkboxes or radios, visible selected
  state, a selected count when useful, and clear action copy.
- Preserve the primary visual or decision artifact as the first substantial
  content in inspectors, previews, dialogs, and evidence viewers. For image,
  video, chart, document, map, simulation, or media inspection, the stored
  artifact itself must appear before advanced controls, provenance panels,
  backend setup cards, raw metadata, or customization forms.
- Advanced controls must be progressive disclosures near the artifact they
  affect. Show compact current-value links/chips first; reveal sliders,
  steppers, pickers, range controls, aspect-ratio locks, and custom render
  parameters only after the user asks to adjust that property.
- Do not let a full custom-configuration form consume the initial viewport of a
  viewer. If customization is secondary, collapse it behind an explicit action
  such as "custom render" or a property link, and keep the default stored media
  visible while the user adjusts it.
- Technical context such as solver setup, boundary conditions, data provenance,
  request payloads, or evidence manifests belongs below the artifact or behind a
  details disclosure unless that context is the user's primary task.
- Current context state such as detected location, active region, sync status,
  selected account, filter count, or permission state is usually metadata, not
  the primary content. Show it as a compact chip/dropdown/link in the relevant
  global shell area, usually the header or occasionally footer. Do not use
  floating badges for ordinary global context when a header/footer placement is
  available. Open a dialog, sheet, popover, or details surface only when the
  user needs to change or repair it.
- Header context chips must stay closed by default unless the user explicitly
  opens them. Permission denial, fallback state, stale data, or incomplete
  setup may change the chip's compact status affordance, but must not auto-open
  a popover or modal unless the page is otherwise blocked and the user cannot
  continue. Header popovers must close on outside click, Escape, navigation, and
  successful selection.
- Do not expose precise private values such as GPS coordinates, raw account ids,
  tokens, internal identifiers, or detailed diagnostics in persistent header
  chips or ordinary header popovers. Show a human-readable summary there and put
  precise values only in explicit edit/admin/details surfaces when genuinely
  needed.
- Header chips must reserve clear space from navigation and hamburger controls
  at every responsive breakpoint. When space is tight, shorten the chip text,
  hide secondary labels, or collapse to an icon before allowing overlap or
  ambiguous tap targets.
- Keep context selection and result filtering separate. Location/account/region
  selection answers "what context am I in?" and belongs in the shell. Filters
  such as open/closed, sort, availability, category, date, and price answer
  "which results in this list/table/map?" and belong in that result surface's
  toolbar, tabs, chips, or column controls.
- Do not let successful automatic detection create a persistent configuration
  panel. If a value was inferred or detected and needs no immediate action, keep
  it compact; reserve full selectors, maps, troubleshooting text, and retry
  controls for unresolved states or explicit user expansion.
- Admin-only or rare recovery controls must not consume the default public
  viewport. Expose them only after authorization and behind an explicit compact
  affordance, and keep the ordinary user's main decision content visible first.
- For mobile/narrow UI verification, measure the first viewport. If secondary
  controls, filters, selectors, or status panels push the primary list, map,
  media, chart, or decision artifact materially downward, treat that as a
  primary-journey defect even when all controls technically work.
- After implementing or materially changing web layout, shared DOM/CSS,
  responsive behavior, or visibility geometry, run
  `$formal-web-ui-verification` on the relevant desktop and mobile routes when
  a safe render path exists. For an interaction/configuration-only fix that
  preserves geometry, exercise the affected journey and viewport instead of
  automatically running the full geometry matrix. Do not report a material UI
  change as done while critical formal findings remain for clipped text, hidden
  controls, unintended overlap, off-canvas controls, broken media, invisible
  text, document overflow, or area violations. Include the verifier's visible
  scrollbar inventory when the verifier runs.
- When checking or implementing web UI backed by Next.js server actions, route
  handlers, API routes, background work, or other server-side request paths,
  load and apply `$vercel:vercel-functions` before judging the implementation.
  UI actions that may process many records must be bounded, truthful about
  queued/running/completed work, and designed around function/runtime limits
  instead of hiding long-running work inside an unbounded browser request.
- Do not put implementation invariants, data-pipeline rules, backend guarantees,
  or technical caveats into primary UI copy when the behavior already follows
  from the interface. Copy should help the user decide or act; move technical
  details to contextual tooltips, evidence/detail views, admin/debug surfaces,
  or docs.
- For search, import, lookup, connect, add-by-url, invite-by-email, join-by-code,
  create-from-link, upload, or similar journeys where the normal first action is
  entering one string or choosing one file, default to a Google-search-style
  surface: the required input, one primary action, and essential validation only.
- Do not expose type pickers, policy selectors, monitoring toggles, optional
  metadata fields, synthetic hints, explanatory panels, debug ids, or rare
  settings before the first submit unless the user's first decision truly
  depends on them.
- Put defaults and inferred fields in the backend or post-submit editor. Put rare
  choices behind manual/advanced disclosure or the relevant settings page.
- Never expose JSON, serialized blobs, raw database payloads, or schema-shaped
  internals as editable UI. If users can edit a concept, provide typed fields,
  validated rows, or a purpose-built editor backed by real columns/tables.
- Automated tests that create database records must clean up those records in
  foreign-key dependency order (or assert they are isolated from normal product
  and worker flows), scoped to fixtures that test run created. Rows produced by
  find-or-create/dedupe mechanisms (canonical keys, upserts) can be shared with
  concurrently running tests: delete them only when no references remain, never
  unconditionally, and when hardening one test file's cleanup against such a
  flake, sweep sibling test files for the same pattern in the same change.
- During UI audits, flag overexposed secondary controls on single-primary-input
  journeys as primary journey defects, not as copy polish.

## Schema Boundary Guardrail

- Before implementing a new registry/table or adding fields to an existing one,
  classify every field by domain meaning: material property, physical state,
  boundary/inlet condition, mesh profile, solver/numerical profile,
  execution/scheduling policy, output/media policy, or immutable result
  evidence.
- Do not mix unrelated concepts into one record because they appear in one UI
  form, one "advanced" expander, one API payload, one solver request, or one
  convenience DTO. UI grouping and transport shape do not determine data
  ownership.
- If fields have different lifecycles, owners, reuse patterns, validation
  rules, or audit/evidence meaning, model them as separate records and compose
  them at request/job time.
- Entity names must match contents. A table or API resource named for a
  physical/domain concept must not silently own numerical, scheduling, output,
  debug, or presentation settings.

## macOS App Build And Test Workflow

- For Swift/macOS app work, load and follow the Build macOS Apps plugin before
  building, testing, packaging, launching, debugging, or running native UI
  automation.
- Do not take over the user's desktop, drive the app through ad-hoc mouse or
  keyboard control, invoke `open`, or substitute direct `swift`, `swiftc`,
  `xcodebuild`, or XCUI commands for the plugin workflow.
- If the plugin is not installed or unavailable in the current session, stop
  the Swift/macOS validation path and report it as pending. Continue only work
  that does not build, launch, or control the app until the plugin is available.

## Local Services, Docker, And Databases

- In system-level systemd units, never use `%h` for a non-root `User=`
  account's home. The system manager resolves `%h` from its own root context,
  not from `User=`. Pin or deliberately provision the service-account path,
  add a realistic detector check, and inspect loaded `systemctl show` paths
  before the first production start.
- Before starting, stopping, restarting, or replacing any dev/test server,
  Docker Compose service, Docker container, or local database stack, use
  `$codex-dev-coordinator` and run its `inventory --project "$PWD"` command.
- Do not start services on default ports directly. Do not follow the pattern
  "try the default port, then try another one if busy." Lease ports or manage
  servers through the coordinator.
- Reuse a healthy coordinator-managed URL when it matches the task instead of
  launching a duplicate server.
- Before destructive PostgreSQL-in-Docker operations such as migrations, resets,
  imports, seed rewrites, `DROP`, or `TRUNCATE`, use `$postgres-docker-backup`
  to create and verify a backup.

## Decision there history
- For every project keep a DecisionHistory.md file where you track all the architectural decisions, why were they made and how did they work. Track user decisions as well. 
- If later you find a code which contradict previous decision, find our how this may affect general behavior, what can possibly go wrong and report to the user

## Shell Working-Directory Discipline

- Shell working directories persist across tool calls within a session. Never
  rely on an inherited CWD for commands whose target matters: start each
  compound shell command with an explicit `cd` to the repo root (or use
  absolute paths for every file argument, including script heredocs and ssh
  identity files).
- After any command chain that includes `cd`, treat the CWD as unknown for
  the next call.
- Verify that multi-step chains actually performed their mutating steps:
  a failed `git add <path>` after a CWD drift produces a commit whose message
  claims changes it does not contain. When a patch script and a commit run in
  one chain, check the patch applied (grep the change) before pushing.
