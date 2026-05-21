---
name: user-journey-docs-audit
description: Audit Markdown and development documentation for app idea clarity, user context, complete user journeys, journey decision models, information relevance, feature inventory, UI handoff constraints, edge cases, implementation expectations, test expectations, and usability acceptance criteria. Use when Codex needs to inspect README/docs/MDX/product specs for whether they define user intent and decision needs well enough to design, build, test, and improve a rich, easy-to-use application or prepare reliable inputs for ui-implementation-audit; must actively interview the user with questions or surveys when app purpose, users, journeys, feature intent, decision needs, or UI assumptions are missing or ambiguous.
---

# User Journey Docs Audit

## Overview

Audit whether a repo's docs are sufficient to drive excellent product and UI work. This skill is not a source-code feature audit and must not prescribe layout on its own. It checks whether Markdown/product/development docs explain the app idea, users, contexts, complete journey set, complete feature set, UI elements, decisions users make, information needed for those decisions, action frequency, edge cases, implementation expectations, test expectations, and acceptance criteria well enough that designers, engineers, QA, support, and agents can build a rich, easy-to-use app without guessing.

## Required User Engagement

Do not silently infer journeys and call the audit complete.

- Inspect docs and source hints first, then actively interview the user before final scoring when app idea, user groups, journey priority, or UI intent is missing or ambiguous.
- Use `request_user_input` when available for survey-style choices and concise direct questions for free-form details. If the tool is unavailable, ask in chat.
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
   - Treat UI/source files only as hints. Do not infer final layout from source hints, screenshots, or generic words like "dense", "dashboard", "command center", "overview", "compact", or "expert UI"; require the docs or user to define which decisions those terms support.

5. **Audit UI implementation readiness**
   - For each primary journey/screen, require a journey decision model: primary user goal, primary decision, required facts, warning/flag conditions, frequent actions, secondary/rare actions, and unresolved assumptions.
   - Require an information relevance inventory: what is critical-always, primary-frequent, secondary-occasional, rare-under-5-percent, conditional, destructive, or expert-only for each journey.
   - Require UI handoff constraints, not layout prescriptions: screens/routes/states to verify, decision and relevance facts to preserve, mockups/screenshots to use, evidence expected from `ui-implementation-audit`, and unresolved assumptions.
   - Treat docs as not UI-ready when they describe a surface, "dense" interface, dashboard, command center, or compact layout without explaining the user decisions, action frequency, required facts, warning conditions, and rare/conditional detail needs.
   - Treat missing feature inventory, UI element inventory, implementation expectations, or test expectations as documentation gaps.

6. **Find missing journeys**
   - Look for absent onboarding, first-run, returning-user, empty-state, search/filter, create/edit/delete, import/export/upload, collaboration, admin/moderation, permission-denied, error recovery, destructive action, notification, payment/upgrade, support, and mobile/narrow-screen journeys as applicable.

7. **Produce a documentation plan**
   - Recommend exact docs or sections to add.
   - Use `references/journey_doc_template.md` when proposing replacement or new documentation structure.
   - Include enough detail that another engineer or agent can write the missing docs without inventing product intent.

## Audit Rubric

Score each dimension as `0 missing`, `1 weak`, `2 usable`, or `3 excellent`.

- App idea and product promise.
- User groups, context of use, expertise, device, frequency, urgency, and mistake cost.
- Journey inventory and prioritization across all user journeys.
- Feature inventory, UI element inventory, implementation expectations, and test expectations.
- Task and decision model: what users decide, what information they need, and what they can ignore.
- UI implementation readiness: journey decision model, information relevance inventory, UI handoff constraints, and clear evidence inputs for `ui-implementation-audit`.
- Route and navigation priority: most likely paths first, escape/back paths clear.
- Information hierarchy: critical-always, primary-frequent, secondary-occasional, and rare-under-5-percent details separated.
- Detail relevance: rare, destructive, expert-only, or conditional details are identified separately from facts needed for the user's current decision.
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
## UX Documentation Gaps
## UI Handoff Constraints
## Recommended Documentation Plan
## Readiness Score
## Questions Still Unanswered
```

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
- `P2`: Missing docs weaken usability, mobile fit, accessibility, edge cases, or rich functionality.
- `P3`: Polish, consistency, naming, examples, or maintainability improvement.

## Completion Rules

- Do not claim `excellent` or `complete` unless the user has confirmed app idea, users, and prioritized journeys, or the repo docs already do so explicitly.
- If journey assumptions are unconfirmed, include `journey assumptions unconfirmed` in `Coverage`, `Readiness Score`, and `Questions Still Unanswered`.
- Distinguish documented truth from source-code inference.
- Prefer a practical documentation plan over broad UX advice. Name the exact files or sections to create.
