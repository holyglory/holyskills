# UX Principles For Journey Documentation Audits

Use this reference when judging whether docs are strong enough to support an easy, rich, user-centered app.

## Source Anchors

- Nielsen Norman Group's 10 usability heuristics: visibility of status, real-world language, user control, consistency, error prevention, recognition over recall, flexibility, minimalist design, error recovery, and help/documentation.
  Source: https://www.nngroup.com/articles/ten-usability-heuristics/
- MIT OpenCourseWare user-centered design material emphasizes user analysis, task analysis, contextual inquiry, and success criteria before design decisions.
  Source: https://ocw.mit.edu/courses/6-811-principles-and-practice-of-assistive-technology-fall-2014/resources/mit6_811f14_usercentered/
- WCAG organizes accessibility around perceivable, operable, understandable, and robust interfaces.
  Source: https://www.w3.org/WAI/standards-guidelines/wcag/glance/
- Apple Human Interface Guidelines for disclosure controls: expose likely controls first and hide more advanced functionality by default.
  Source: https://developer.apple.com/design/human-interface-guidelines/disclosure-controls
- Material Design responsive layout guidance treats layouts and navigation as adaptive to available screen width.
  Source: https://m1.material.io/layout/responsive-ui.html

## Documentation Must Enable These Decisions

- What the user is trying to accomplish.
- Which journeys are most frequent, most valuable, and most risky.
- Which information is required at each step.
- Which actions are primary, secondary, rare, destructive, or expert-only.
- Which details should be visible, hidden, expandable, searchable, or moved to drill-in views.
- Which states must exist: loading, empty, error, success, partial success, denied, offline, retry, undo, and recovery.
- Which constraints apply: mobile, accessibility, latency, permissions, security, data loss, stress, expertise, and localization.

## Signs Of Excellent Journey Docs

- A new designer can sketch the main screens without asking what matters most.
- A new engineer can implement states and routes without inventing user intent.
- QA can write scenario tests, edge tests, and mobile checks from the docs alone.
- Support can understand what users were trying to do when they failed.
- Product can defend why something is visible, hidden, first, grouped, or deprioritized.

## Common Gaps

- Docs list features but not user goals.
- Docs describe screens but not decisions users make on those screens.
- The happy path is documented but empty/error/permission/destructive paths are absent.
- Mobile is mentioned but no compactness or information-priority expectations are defined.
- Rare details are treated as equal to critical information.
- Navigation names are internal system terms rather than user language.
- Docs say "dashboard", "settings", or "admin" without defining what users need there.
- Accessibility is reduced to color contrast and ignores keyboard, focus, labels, and understandable language.

## Documentation Failures That Create Wrong UI

- Feature lists without journey priority let implementers treat settings, filters, and primary content as equal.
- Desktop-first ordering can be copied directly to mobile, pushing primary decision content below low-frequency controls.
- Mockups or screenshots are not enough unless the docs explain why the first viewport supports the user's main decision.
- Mobile requirements that only say "compact" or "no horizontal overflow" miss the more important question: what can the user decide before scrolling?
- Overexposed configuration is a documentation defect when docs do not say which controls are frequent, occasional, rare, or admin-only.
- A UI implementation audit needs a handoff contract: primary goal, primary information, action frequency, rare controls, expected mobile order, first visible content, and evidence expectations.
