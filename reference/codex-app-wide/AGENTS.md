# Global Agent Instructions
- Never propose V1/MVP limited functionality implementation. User always expects the entire requested functionality to work, no matter how large it is. Engage sub-agents to help planning and implementing larger features when necessary.
- Before fixing errors, replicate them. Test before delivery the same way you replicated them before.
- When delivering or fixing a detector — a test suite, verifier, audit, linter, monitor, or alert — prove recall, not only precision: exercise it against realistic examples of the failures it claims to catch, shaped like real-world breakage rather than like the detector's own implementation, and keep at least one such must-catch example per advertised detection class in its automated checks, plus false-positive guards for common intentional patterns. A detector that only passes fixtures mirroring its implementation is not validated.
- Generalize user bug or wrong behavior reports. See if such potential wrong behavior may happen elsewhere. 
- Use ImageGen2 to design interfaces when fixing interfaces on user prompts. Confirm mockups with the user.
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
- When the user reports a problem likely made by an AI agent, first load and
  follow `trace-fix-root-causes` SKILL before
  the first product-code edit or fix attempt. This applies even when the report
  arrives as a browser comment, a visual/UI complaint, or a small-looking CSS
  issue. Loading the skill only after patching does not satisfy this gate. Then
  follow this order:
  1. Reproduce the problem through the same surface the user saw, when reproduction makes sense.
  2. Trace why the problem happened before changing the product code. Check the requirements, user intention, journey docs, design handoff, implementation, tests, verifier rules, audit outputs, tool choices, and handoff assumptions.
  3. If the cause is wrong context, missed user intent, weak documentation, weak verifier coverage, or a reusable workflow gap, update the nearest durable guardrail first: docs, AGENTS instructions, tests, verifier, skill, checklist, or policy.
     - If the prevention rule is general enough to apply across Codex tasks,
       repos, or app-wide agent behavior, update this global Codex app-wide
       `AGENTS.md` with a generalized reusable instruction. Do not satisfy an
       app-wide policy need by editing only a repo `AGENTS.md`.
     - Use repo `AGENTS.md` for repo-specific repeatable rules. Use tests,
       verifiers, skills, or docs when they are the narrowest guardrail that
       will actually prevent the recurrence.
     - Keep one-off incident explanations, timelines, and exact bug narratives
       out of global and repo policy files; put those in the root-cause report,
       `DecisionHistory.md`, targeted tests, or fixtures.
  4. If a skill or audit was run and failed to catch the issue, improve that skill or its deterministic checks before declaring the incident handled. Re-run it on the same code or evidence and verify it now catches the issue.
  5. When practical, validate the new guardrail from a fresh-agent perspective: a new agent with only the updated instructions and source should avoid the same mistake.
  6. Then fix the product issue itself.
  7. Re-test through the original reproduction path and any new guardrail/check before reporting done.
  8. If the wrong or weak guardrails could result in other similar errors or wrong behavior, audit the entire codebase and present user with possible gaps, plans for testing and fixing
- Keep one-off local mistakes separate from general process fixes, but bias toward durable prevention when the mistake could recur.
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

- Before placing or sizing any UI element, answer the element-ranking sequence:
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
- After implementing or materially changing web UI, run
  `$formal-web-ui-verification` on the relevant desktop and mobile routes when
  a safe render path exists. Do not report the UI as done while critical formal
  findings remain for clipped text, hidden controls, unintended overlap,
  off-canvas controls, broken media, invisible text, document overflow, or area
  violations. Include the verifier's visible scrollbar inventory in the
  evidence when the verifier can run.
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
- Automated UI tests that create database records must clean up those records or
  assert they are isolated from normal product and worker flows before finishing.
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

## Local Services, Docker, And Databases

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
