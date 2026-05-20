---
name: user-journey-docs-audit
description: Audit Markdown and development documentation for app idea clarity, user context, complete user journeys, UI/UX information hierarchy requirements, journey priority contracts, first-viewport usefulness, route priority, edge cases, and usability acceptance criteria. Use when Codex needs to inspect README/docs/MDX/product specs for whether they are detailed enough to design, build, test, and improve a rich, extremely easy-to-use application or prepare reliable inputs for ui-implementation-audit; must actively interview the user with questions or surveys when app purpose, users, journeys, or mobile priority are missing or ambiguous.
---

# User Journey Docs Audit

## Overview

Audit whether a repo's docs are sufficient to drive excellent product and UI work. This skill is not a source-code feature audit; it checks whether Markdown/product/development docs explain the app idea, users, contexts, journeys, decision points, UI priorities, edge cases, and acceptance criteria well enough that designers, engineers, QA, support, and future agents can build a rich, easy-to-use app without guessing.

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
3. List the top 3-7 journeys by frequency and importance.
4. Identify mobile/desktop priority, stress level, and consequences of mistakes.
5. Confirm what the docs should enable: implementation, redesign, QA, onboarding, support, analytics, or all of these.

## Workflow

1. **Inventory documentation**
   - Run `python3 <skill-dir>/scripts/build_journey_docs_inventory.py --repo <repo> --json` unless the user forbids commands.
   - Inspect README, docs, specs, architecture notes, route maps, onboarding docs, product docs, MDX, Storybook notes, and operational Markdown.
   - Treat UI/source files only as supporting hints for missing docs, not as proof that documentation is complete.

2. **Build a preliminary app model**
   - Extract documented app purpose, user roles, tasks, routes/screens, workflows, states, feature families, constraints, and success criteria.
   - Draft likely journeys only when docs are missing, and mark every such journey `draft-needs-user-confirmation`.

3. **Interview the user**
   - Ask about the app idea, users, journey list, journey priority, device/context, and quality bar.
   - Prefer concrete survey choices for priority/frequency and concise free-form questions for app-specific journeys.
   - Use the user's answers as the source of truth over source-code guesses.

4. **Audit documentation completeness**
   - Load `references/ux_principles.md` for the rubric and literature-backed checks.
   - For each journey, check whether docs define target user, goal, trigger, entry point, route/screen sequence, preconditions, decision points, required information, primary actions, secondary/rare actions, failure/recovery states, permission states, mobile/desktop expectations, and acceptance criteria.
   - Compare documented UI requirements against what would make the journey easy: most relevant information first, most probable route first, critical warnings visible, rare detail hidden behind progressive disclosure, and relevant information fitting mobile screens.

5. **Audit UI implementation readiness**
   - For each primary journey/screen, require a documented journey priority contract: primary user goal, primary decision-making information, frequent actions, occasional controls, rare/admin/configuration controls, expected desktop order, and expected mobile order.
   - Require first-viewport documentation for mobile/narrow screens: first visible content, primary decision data, low-frequency controls, allowed control/header/settings share, and what the user can decide before scrolling.
   - Treat missing mobile order or missing first-viewport usefulness as a P1 when it can cause implementers to put settings, filters, menus, or configuration above primary decision content.
   - Distinguish "matches a mockup" from "supports the journey"; docs must explain why the first viewport is useful, especially before handoff to `ui-implementation-audit`.
   - Produce a concrete UI implementation audit handoff: screens/routes to verify, priority contract rows, first viewport expectations, mockups/screenshots to use, and unresolved assumptions.

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
- Journey inventory and prioritization across multiple user journeys.
- Task and decision model: what users decide, what information they need, and what they can ignore.
- UI implementation readiness: journey priority contract, first-viewport usefulness, and clear handoff inputs for `ui-implementation-audit`.
- Route and navigation priority: most likely paths first, escape/back paths clear.
- Information hierarchy: critical-always, primary-frequent, secondary-occasional, and rare-under-5-percent details separated.
- Progressive disclosure: rare details hidden behind menus, expanders, tabs, drill-ins, or details panels without hiding critical warnings.
- State coverage: loading, empty, error, offline, permission denied, success, partial success, retry, undo, destructive confirmation, and recovery.
- Mobile and responsive requirements: compactness, fit, no accidental horizontal scroll, no cropped decision data.
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
## Journey Priority Contract Gaps
## First Viewport Documentation Gaps
## Documentation Completeness Findings
## Information Hierarchy And Navigation Gaps
## UX Documentation Gaps
## UI Implementation Audit Handoff
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
- `P1`: Missing docs block confident design/build/test of a primary journey or user group, or leave mobile priority ambiguous enough that low-frequency settings/filters/configuration may appear before primary decision content.
- `P2`: Missing docs weaken usability, mobile fit, accessibility, edge cases, or rich functionality.
- `P3`: Polish, consistency, naming, examples, or maintainability improvement.

## Completion Rules

- Do not claim `excellent` or `complete` unless the user has confirmed app idea, users, and prioritized journeys, or the repo docs already do so explicitly.
- If journey assumptions are unconfirmed, include `journey assumptions unconfirmed` in `Coverage`, `Readiness Score`, and `Questions Still Unanswered`.
- Distinguish documented truth from source-code inference.
- Prefer a practical documentation plan over broad UX advice. Name the exact files or sections to create.
