---
name: user-journey-docs-audit
description: Run a lexical and structural audit of product and journey documentation for app idea clarity, user context, journey decision models, information relevance, feature inventory, UI handoff constraints, edge cases, implementation expectations, test expectations, and usability acceptance criteria. Use when an agent (Codex, Claude Code) needs to determine whether docs define user intent and decision needs well enough to design, build, test, and improve an application or prepare reliable inputs for ui-implementation-audit; policy files and source hints are not product truth, and the user must be interviewed when purpose, users, journeys, feature intent, or UI assumptions remain ambiguous.
---

# User Journey Docs Audit

## Overview

Audit whether a repo's docs are sufficient to drive excellent product and UI work. This skill is not a source-code feature audit and must not prescribe layout on its own. It checks whether Markdown/product/development docs explain the app idea, users, contexts, complete journey set, complete feature set, UI elements, decisions users make, information needed for those decisions, action frequency, edge cases, implementation expectations, test expectations, and acceptance criteria well enough that designers, engineers, QA, support, and agents can build a rich, easy-to-use app without guessing.

The inventory is a lexical/structural detector, not semantic proof. It
classifies policy, decision-history, operational-skill, product, and journey
documents separately. `AGENTS.md`, `CLAUDE.md`, `DecisionHistory.md`, linked
`DecisionDetails/D-YYYYMMDD-NN.md` records, and source code can surface
missing-context hints but cannot confirm product intent. Native source hints
include SwiftUI, XAML/Avalonia/WPF, AppKit/UIKit, Compose/Kotlin, Flutter,
Qt/QML, and web UI files.

Hard reporting gate: the final answer is invalid if it omits the exact heading
`## Interaction Affordance And Metadata Gaps`. Do not merge those findings into
`Documentation Completeness Findings`, `UX Documentation Gaps`, or `UI Handoff
Constraints`. If the docs mention badges, flags, expandable rows, result/tool
blocks, scrollable lists, message streams, evidence rows, or icons, this section
must include a P1 finding unless the docs explicitly define interaction targets,
feedback, destination behavior for navigational items, transient panel
lifecycle, detail access, scrollbar separation, stable dimensions, hover-copy
behavior, concise status-summary rules, icon meaning, and message metadata
behavior.

## Required User Engagement

Do not silently infer journeys and call the audit complete.

- Inspect docs and source hints first, then actively interview the user before final scoring when app idea, user groups, journey priority, or UI intent is missing or ambiguous.
- Use the runtime's structured question tool when available (`request_user_input` in Codex, `AskUserQuestion` in Claude Code) for survey-style choices and concise direct questions for free-form details. If no such tool is available, ask in chat.
- Ask at least one user-facing clarification round before a final verdict unless the user's prompt already includes the app idea, target users, and prioritized journeys.
- If the user cannot answer or asks to proceed without clarifying, label the result `journey assumptions unconfirmed`; do not say the docs are complete or UI-ready.
- When multiple journeys exist, audit every confirmed journey and every plausible drafted journey independently before synthesizing cross-journey priorities.

Recommended first interview:

1. Confirm the app idea in one sentence.
2. Confirm target user groups and their expertise level.
3. List the full journey set, including the top 3-7 journeys by frequency and importance.
4. Identify mobile/desktop priority, stress level, and consequences of mistakes.
5. Confirm what the docs should enable: implementation, redesign, QA, onboarding, support, analytics, or all of these.

## Workflow

1. **Inventory documentation**
   - Run `python3 <skill-dir>/scripts/build_journey_docs_inventory.py --repo <repo> --json` unless the user forbids commands.
   - Inspect README, docs, specs, architecture notes, route maps, onboarding docs, product docs, MDX, Storybook notes, and operational Markdown.
   - Treat UI/source files only as supporting hints for missing docs, not as proof that documentation is complete.

2. **Build a preliminary app model**
   - Extract documented app purpose, user roles, tasks, routes/screens, workflows, states, feature families, UI elements, implementation expectations, test expectations, constraints, and success criteria.
   - Draft likely journeys only when docs are missing, and mark every such journey `draft-needs-user-confirmation`.

3. **Interview the user**
   - Ask about the app idea, users, journey list, feature set, UI element set, journey priority, device/context, decision needs, action frequency, and quality bar.
   - Prefer concrete survey choices for priority/frequency and concise free-form questions for app-specific journeys.
   - Use the user's answers as the source of truth over source-code guesses.

4. **Audit documentation completeness**
   - Load `references/ux_principles.md` for the rubric and literature-backed checks.
   - For each journey, check whether docs define target user, goal, trigger, entry point, route/screen sequence, preconditions, decision points, required information, warning/flag conditions, primary actions, secondary/rare actions, required UI elements, implementation behavior, failure/recovery states, permission states, device/context constraints, test expectations, and acceptance criteria.
   - Require the docs to classify information by decision importance, not by source availability. Critical decision information, primary frequent information, secondary/occasional information, rare detail, expert-only/debug information, and conditional information must be distinguishable enough that UI implementation can decide placement and disclosure without guessing.
   - Treat UI/source files only as hints. Do not infer final layout from source hints, screenshots, or generic words like "dense", "dashboard", "command center", "overview", "compact", or "expert UI"; require the docs or user to define which decisions those terms support.

5. **Audit UI implementation readiness**
   - For each primary journey/screen, require a journey decision model: primary user goal, primary decision, required facts, warning/flag conditions, frequent actions, secondary/rare actions, and unresolved assumptions.
   - Require an information relevance inventory: what is critical-always, primary-frequent, secondary-occasional, rare-under-5-percent, conditional, destructive, debug, or expert-only for each journey.
   - Require UI handoff constraints, not layout prescriptions: screens/routes/states to verify, decision and relevance facts to preserve, mockups/screenshots to use, evidence expected from `ui-implementation-audit`, and unresolved assumptions.
   - Require docs to define access expectations for lower-importance information. Secondary, rare, expert, debug, destructive, or conditional information should say whether it belongs inline, in a hover/focus hint, behind row selection, in an expansion, drawer, modal, or deep detail view. The docs do not need to pick exact widgets unless product intent truly depends on that widget.
   - Require docs to define interaction affordance expectations for decision signals and disclosure surfaces when those interactions matter to the journey: whether a whole row/card is the activation target or only a control, whether hover/focus/click feedback is expected, whether badges open a popover/detail, which elements navigate to another surface, what destination they open, and whether pointer/focus affordance is required.
   - Require docs to define the lifecycle of transient disclosure surfaces when they can obscure or distract from the journey: explicit close, outside click, focus loss, idle leave timer, persistence while hovered/focused, or a documented reason to stay open.
   - Require docs to classify message metadata separately from message content. Sender labels, timestamps, tool/runtime labels, copy controls, concise status indicators, and raw execution details should each be marked by decision relevance and access path; docs should say when metadata should be visible, hidden until hover/focus, unselectable, or moved to detail to avoid polluting the readable content stream.
   - If the docs mention badges, flags, expandable rows, result/tool blocks, message streams, scrollable lists, evidence rows, or icon-only controls, file a distinct interaction/metadata readiness finding when the docs do not define activation target, hover/focus/click feedback, navigational destination/cursor behavior, transient disclosure lifecycle, detail access, stable expanded/collapsed dimensions, scrollbar/control separation, hover-copy reachability, concise status summary rules, icon meaning, and passive metadata rules. Do not bury this under a broad documentation-completeness finding.
   - Flag handoff docs that turn evidence into always-visible layout requirements. Phrases such as "must show", "must display", "required visible evidence", or long default visible lists are acceptable only when they are explicitly tied to critical/primary decision information, separated from secondary/rare/debug detail access, or directly confirmed by the user for that exact default layout.
   - Treat docs as not UI-ready when they describe a surface, "dense" interface, dashboard, command center, or compact layout without explaining the user decisions, action frequency, required facts, warning conditions, and rare/conditional detail needs.
   - Treat missing feature inventory, UI element inventory, implementation expectations, or test expectations as documentation gaps.

6. **Find missing journeys**
   - Look for absent onboarding, first-run, returning-user, empty-state, search/filter, create/edit/delete, import/export/upload, collaboration, admin/moderation, permission-denied, error recovery, destructive action, notification, payment/upgrade, support, and mobile/narrow-screen journeys as applicable.

7. **Produce a documentation plan**
   - Recommend exact docs or sections to add.
   - Use `references/journey_doc_template.md` when proposing replacement or new documentation structure.
   - Include enough detail that another engineer or agent can write the missing docs without inventing product intent.
   - When a deterministic completion gate is required, save the final Markdown
     report and run
     `python3 <skill-dir>/scripts/verify_journey_docs_audit_results.py <report.md>`.
     This checks report shape, interview/confirmation status, journey-status
     labels, unconfirmed-assumption propagation, and the interaction/metadata
     checklist; it does not replace lead judgment.

## Audit Rubric

Score each dimension as `0 missing`, `1 weak`, `2 usable`, or `3 excellent`.

- App idea and product promise.
- User groups, context of use, expertise, device, frequency, urgency, and mistake cost.
- Journey inventory and prioritization across all user journeys.
- Feature inventory, UI element inventory, implementation expectations, and test expectations.
- Task and decision model: what users decide, what information they need, which information is critical, primary, secondary, rare, expert-only, debug, or conditional, and what can be ignored in the current decision state.
- UI implementation readiness: journey decision model, information relevance inventory, UI handoff constraints, and clear evidence inputs for `ui-implementation-audit`.
- Route and navigation priority: most likely paths first, escape/back paths clear.
- Information hierarchy: critical-always, primary-frequent, secondary-occasional, rare-under-5-percent, conditional, debug, and expert-only information are separated and justified by journey decisions.
- Detail relevance and access: secondary, rare, destructive, debug, expert-only, or conditional details are identified separately from facts needed for the user's current decision, with enough access guidance for implementation to decide inline placement versus hint, row selection, expansion, drawer, modal, or deep detail view.
- Interaction affordance readiness: docs explain which decision signals, badges, rows, and disclosure surfaces are clickable or hoverable; what feedback or popover/detail appears; and which interaction targets must remain stable, large enough, and separated from scrollbars or adjacent controls.
- Message content and metadata: docs identify whether authorship, routing labels, timestamps, tool/runtime status, and execution details are decision-relevant content or lower-priority metadata, including whether metadata should be selectable.
- State coverage: loading, empty, error, offline, permission denied, success, partial success, retry, undo, destructive confirmation, and recovery.
- Device and context constraints: supported sizes, stress level, input mode, fit risks, and information that must remain available without cropping or accidental overflow.
- Accessibility and inclusive use: keyboard/focus, labels, contrast, understandable language, assistive technology expectations.
- Rich functionality and power-user paths: shortcuts, bulk actions, filters, saved views, history, export, automation, or customization when relevant.
- Acceptance criteria and testability: observable outcomes, fixtures/test mode, QA checks, analytics/support signals.

## Final Output

Return exactly these top-level headings:

```markdown
## Coverage
## Interview Summary
## Confirmed App Idea
## Confirmed Users And Contexts
## Confirmed Journey Inventory
## Missing Or Weak Journeys
## Journey Decision Model Gaps
## Information Relevance Inventory Gaps
## Documentation Completeness Findings
## Information Hierarchy And Navigation Gaps
## Interaction Affordance And Metadata Gaps
## UX Documentation Gaps
## UI Handoff Constraints
## Recommended Documentation Plan
## Readiness Score
## Questions Still Unanswered
```

The `Interaction Affordance And Metadata Gaps` section is required even when it is short. It must explicitly say whether the docs define:

- decision signal, flag, badge, row, card, and disclosure activation targets, including whether the whole row/card or only a small icon/control is interactive
- hover, focus, pressed, and click feedback for interactive badges, flags, rows, and disclosure surfaces
- destination and cursor/focus affordance for any element that navigates to another screen, region, row, dialog, or detail surface
- lifecycle for temporary expanded panels, flyouts, popovers, and contextual detail surfaces, including whether they close on outside click, focus loss, leave/idle timeout, or only explicit close
- popover, tooltip, inline, expansion, drawer, modal, or deep-detail access for secondary/rare details
- placement constraints that prevent disclosure controls from colliding with scrollbars, selection affordances, or other controls
- stable collapsed/expanded dimensions for tool, result, and evidence blocks when size stability affects scanning or comparison
- hover-revealed copy controls and whether they stay in a stable reachable position while the pointer moves toward them
- concise status-summary rules for tool/result blocks, including which status, error count, duration, success, or severity signals are visible by default versus moved to detail
- message content versus metadata rules for authorship/routing labels, timestamps, tool/runtime labels, raw execution details, and whether passive metadata should be selectable

If any of those checks are absent for a documented surface that mentions badges, flags, message streams, tool/result blocks, expandable rows, evidence rows, scrollable lists, or icons, include at least one `P1` finding in this section with file evidence. A result that only reports generic "UI handoff" or "documentation completeness" gaps is incomplete.

For each finding include:

- Priority: `P0`, `P1`, `P2`, or `P3`
- Docs/files: repo-relative Markdown or spec files
- Journey(s): confirmed or drafted journey names
- Evidence: concrete quote/heading/source hint
- Missing detail: what the docs do not explain
- Why it matters: implementation, UI, QA, accessibility, support, or user risk
- Suggested documentation: exact section or content to add

Use this priority scale:

- `P0`: Missing docs could cause unsafe, destructive, legally sensitive, or core unusable behavior.
- `P1`: Missing docs block confident design/build/test of a primary journey, intended feature, UI element, or user group, or use UI intent words such as "dense", "dashboard", "command center", "overview", or "compact" without defining the decisions, information relevance, action frequency, and unresolved assumptions behind them.
- `P1`: Docs convert UI audit evidence or source-observed fields into always-visible layout requirements without explaining the information importance and access model, because this can make downstream implementation and audits preserve an overloaded or wrongly prioritized interface.
- `P1`: Docs describe flags, badges, message streams, tool/result blocks, or expandable rows without defining interaction targets, hover/click feedback, navigation destination/cursor behavior, transient disclosure lifecycle, popover/detail access, copy-control visibility, metadata relevance, concise status-summary rules, and stable-size expectations needed for an intuitive implementation.
- `P2`: Missing docs weaken usability, mobile fit, accessibility, edge cases, or rich functionality.
- `P3`: Polish, consistency, naming, examples, or maintainability improvement.

## Completion Rules

- Do not claim `excellent` or `complete` unless the user has confirmed app idea, users, and prioritized journeys, or the repo docs already do so explicitly.
- If journey assumptions are unconfirmed, include `journey assumptions unconfirmed` in `Coverage`, `Readiness Score`, and `Questions Still Unanswered`.
- Do not omit the `Interaction Affordance And Metadata Gaps` heading. If the docs contain no relevant interactive or metadata-bearing surfaces, write `No relevant interaction or message-metadata surfaces documented.`
- Before finalizing, check the generated report text for the literal string `## Interaction Affordance And Metadata Gaps`. If absent, rewrite the report instead of returning it.
- Distinguish documented truth from source-code inference.
- Prefer a practical documentation plan over broad UX advice. Name the exact files or sections to create.
