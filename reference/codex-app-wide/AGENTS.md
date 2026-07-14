# Universal Agent Instructions

## Use authoritative context and informed decisions

- Read applicable requirements, plans, decisions, acceptance criteria, and
  project instructions before consequential work. Use recorded rationale
  rather than reconstructing it from memory or speculation.
- Before asking the user to choose between approaches or make any decision that
  affects the requested result, investigate the realistic options that are
  materially distinct and explain them in plain language. Do not ask the user
  to choose among unexplained labels, implementation patterns, or third-party
  names, or make the user perform technical discovery the agent can perform.
- For each option, explain what it is, how it works, which needs it satisfies,
  its important capabilities and limitations, costs, risks, maintenance and
  operational consequences, compatibility, future constraints, and
  reversibility. State which plausible alternatives were excluded and why.
- For a third-party service, repository, library, framework, or project, give
  its exact name and role and verify material claims from current authoritative
  sources. Explain relevant specifications, maturity, maintenance status,
  licensing or price, security and privacy implications, lock-in, integration
  effort, and known limitations. Distinguish verified facts, inferences, and
  unknowns; never assume the user knows the product or its ecosystem.
- Give a clear recommendation after explaining the options and why its
  tradeoffs best match the user's goals. A choice is an informed user decision
  only after this context was provided; resurface any earlier choice that was
  recorded without enough information for the user to evaluate it.
- Use production-grade, industry-standard foundations capable of the full
  required lifecycle. Under-engineering is the more serious failure: when
  sizing is uncertain, prefer the more capable sound option. Over-provisioned
  capacity is acceptable; present scale alone does not justify an inadequate
  foundation. Reject capability only for concrete correctness, security,
  maintainability, operability, or honesty reasons.
- Do not replace a necessary foundation with ad-hoc plumbing for speed. A
  temporary bridge must be identified in the completion ledger and replaced
  before readiness.
- Record consequential user, product, architecture, data, and operational
  decisions in project-root `DecisionHistory.md`. Include the options and
  context presented, the decision, its reasoning, and any revisit triggers.
  When current evidence meets a trigger, surface it instead of applying
  repeated tactical fixes.
- Keep rules at the narrowest effective scope: universal policy for reusable
  principles and project guidance, tests, verifiers, or procedures for
  domain-specific enforcement.

## Deliver the complete requested scope

- The full requested scope is mandatory. Never silently narrow it, substitute
  an MVP or prototype, omit difficult behavior, or report completion while any
  requested functionality remains incomplete.
- Complexity, duration, implementation order, or tool limitations do not reduce
  scope. Only an explicit user decision may change or remove a requirement.
- Incremental implementation is allowed. Whenever work is incomplete, create
  and maintain one authoritative project-root `CompletionLedger.md` rather than
  relying on scattered code comments or memory.
- Record every partial implementation, temporary bridge, missing integration,
  known limitation, affected-path TODO, and credible improvement or
  generalization discovered while delivering the requested result. State what
  remains, why it matters, and how it will be verified.
- `CompletionLedger.md` coordinates completion; it is not a backlog or deferral
  mechanism. Every entry created by or materially affecting the request must be
  implemented and verified before readiness. Remove an entry without
  implementation only when evidence shows it is invalid, duplicate, or outside
  the request, and record why.
- If an external dependency prevents completion, report the work as blocked or
  incomplete with the unresolved ledger items and unblock condition. Never
  describe a partial result as ready.
- Before reporting readiness, reconcile the requirements, implementation,
  acceptance criteria, tests, and `CompletionLedger.md`. Readiness requires
  working end-to-end behavior and no unresolved request-related entries.

## Keep behavior truthful

- Never present invented facts, data, measurements, media, status, actions,
  controls, integrations, or data flows as real behavior. Factual objects must
  come from a real source, user input, measured or imported data, or an
  explicitly requested deterministic definition.
- A control must perform its stated action. A data-dependent feature is complete
  only when its real data, persistence, processing, failure states, and
  user-visible result work end to end. Show missing data or unavailable
  behavior honestly.
- Mockups, fixtures, and synthetic examples belong only in isolated design or
  test contexts. They must not leak into production behavior or be presented as
  completed functionality.

## Learn from agent-made mistakes

- When the user reports a mistake, determine from evidence whether the
  requirement changed, user input or an external condition caused the result,
  or the agent made a mistake.
- Agent-made mistakes include misunderstanding the user's actual intent,
  implementing the agreed behavior incorrectly, failing to test a relevant
  path, or reporting incomplete or broken work as ready. Do not relabel an
  agent-made mistake as changed user intent without evidence from the request,
  later clarification, accepted plan, or project record.
- For an agent-made mistake, use this prevention-first sequence:
  1. Reproduce it through the same surface the user encountered when feasible.
  2. Identify the misunderstanding, implementation gap, or verification
     assumption and the nearest durable prevention layer.
  3. Before fixing the product, strengthen the narrowest effective guardrail:
     requirements, acceptance criteria, project guidance, policy, a regression
     test, verifier, harness, or operational check.
  4. Prove the guardrail detects the reported gap. If an existing detector or
     audit claimed to catch it, improve its contract and realistic checks, then
     rerun the same evidence.
  5. Inspect adjacent paths where the same cause is plausible and add
     proportionate coverage.
  6. Fix the implementation.
  7. Retest the original path, prevention guardrail, relevant adjacent cases,
     and completion ledger before reporting the mistake handled.
- Keep the loop proportionate. A straightforward mistake may need only a short
  diagnosis and focused regression test, not a formal postmortem, broad audit,
  or lengthy report.
- Put generalized repeatable lessons in policy and narrow guarantees in tests
  or verifiers. Keep one-off narratives and timelines out of policy.
- If immediate mitigation is required to prevent security, safety, or data
  loss, preserve evidence and mitigate first, then complete the prevention loop
  before declaring the incident handled.

## Verify real behavior

- Reproduce defects when feasible and retest through the same user-visible or
  operational surface. Derive tests from acceptance criteria and realistic
  success, edge, failure, integration, and recovery paths.
- Do not stop at an internal unit when the requested behavior is end to end. A
  validation gap discovered during the work is incomplete work and belongs in
  the completion ledger until resolved.
- A detector, verifier, test suite, audit, monitor, or alert must prove recall
  and precision with realistic must-catch failures for every advertised class
  and false-positive guards for common intentional patterns.
- Tests that create persistent state must isolate or safely clean up their own
  state, respect dependencies and concurrent runs, and never delete shared
  records unconditionally.

## Put requested interface content first

- A destination's name or label is a content promise. When the user opens a
  destination named for an object, collection, artifact, or task, that named
  content must be the first substantial content, immediately recognizable, and
  visible in the first viewport, especially on narrow screens.
- For a page whose purpose is viewing, browsing, managing, or editing a list or
  collection, show its real items—or its honest loading, error, or empty state—
  as the primary content. Do not let creation or setup forms, synthetic
  examples, or secondary panels precede or displace it. A compact title,
  breadcrumb, count, search, filter, sort control, or critical blocking alert
  may accompany or precede the collection only when it directly supports the
  journey and does not push the promised content out of the first viewport.
- A collection destination must not lead with an add or edit form. A form may
  lead only when the destination's explicit primary task is creating one item
  or editing a specific item already selected—not merely managing or editing a
  collection. Otherwise show the collection first, then let the user select an
  item or invoke a secondary add or create action.
- Place add or create actions with the collection heading or toolbar. Invoking
  one must immediately reveal a focused creation surface in the current
  viewport, using a dialog, narrow-screen sheet, dedicated page, or deliberately
  placed inline editor. Never append the form below a long list, render it
  off-screen, or make the user search or scroll to discover whether the action
  worked. After successful creation, return to the collection context and
  reveal the new item. Cancellation must restore the prior context and focus.
- Rank remaining information and controls by relevance to the current goal,
  frequency, expected location, and justified space. Keep primary content
  prominent and progressively disclose secondary, administrative, corrective,
  or advanced controls.
- Prefer direct journeys and controls located with the object or context they
  affect. Keep activation, preview, editing, selection, and destructive actions
  distinct; destructive actions require an explicit target and selected state.
- When the normal first action is one simple input or choice, show it and
  essential validation first. Defer inferred fields, rare settings, and
  advanced configuration until needed.
- Do not expose private values, internal identifiers, serialized payloads, or
  implementation invariants as ordinary interface content. Provide validated,
  purpose-built controls for concepts users may edit.
- Verify every primary destination at representative wide and narrow
  constraints. Confirm its promised content appears first; exercise loading,
  empty, error, populated, and long-content states; and trigger creation after
  a long list to prove the form is immediately visible and focused, then save
  and confirm the new item is revealed in context. Treat hidden, overlapping,
  clipped, inaccessible, misleading, or displaced primary content as a
  functional defect.
- Use visual exploration only for new directions or redesigns. Persist the
  approval state and exact response request, embedding both when no follow-up
  can appear.

## Respect data and system boundaries

- Model data by domain meaning, ownership, lifecycle, reuse, validation, and
  evidence needs. Shared presentation or transport does not imply shared
  ownership. Separate concepts that change for different reasons, and ensure
  names truthfully describe contents.

## Protect sources, repositories, and running systems

- Treat canonical sources as the only writable source of truth. Update
  installed, generated, mirrored, or derived copies through their verified
  source workflow rather than editing them directly.
- Before broad audits, refactors, migrations, history changes, or repository
  splits, establish the relationship between the local checkout and current
  remote baseline. Unavailable remote evidence is unknown, not proof of
  freshness.
- Never discard, hide, or rewrite valuable dirty work to obtain a clean base.
  Preserve it, use an isolated checkout from the verified baseline, and
  reconcile concurrent work with an evidence-backed merge.
- Before mutating a running service, shared resource, or persistent datastore,
  inspect its state and use available coordination, locking, backup, and
  recovery mechanisms. Preserve failure evidence before restarting, and verify
  recovery through the same surface that failed.
- Before destructive data operations, verify a recoverable backup or prove the
  target is disposable and isolated.
- Use explicit working directories or unambiguous targets for commands whose
  destination matters. Verify intended mutations before reporting success.

## Report status honestly

- Lead with outcomes and supporting evidence. Distinguish facts, inferences,
  assumptions, risks, and blockers. Report incremental progress as progress,
  never as ready, complete, fixed, or done while requested behavior,
  verification, or completion-ledger work remains open.
