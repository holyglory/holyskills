# User Journey Documentation Template

Use this template when recommending docs to add or repair.

## App Idea

- Product promise:
- Primary users:
- Primary value:
- Non-goals:
- Main devices/contexts:

## User Contexts

| User type | Expertise | Frequency | Environment | Stress/urgency | Mistake cost |
| --- | --- | --- | --- | --- | --- |

## Journey Inventory

| Journey | User | Frequency | Importance | Risk if broken | Entry point | Success state |
| --- | --- | ---: | ---: | ---: | --- | --- |

## Journey Detail

### Journey Name

- User:
- Goal:
- Trigger:
- Preconditions:
- Entry point:
- Route/screen sequence:
- Primary decisions:
- Required information per step:
- Warning/flag conditions:
- Primary actions:
- Secondary/rare actions:
- Conditional or rare details and when they matter:
- Unresolved UI assumptions:
- Empty/loading/error/permission states:
- Recovery and undo:
- Device/context constraints:
- Accessibility expectations:
- Acceptance criteria:
- Analytics/support signals:

## Journey Decision Model

| Surface | Primary user goal | Primary decision | Required facts | Warning/flag conditions | Frequent actions | Secondary/rare actions | Unresolved assumptions |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Screen or route | User outcome this surface must support | Decision the user must be able to make | Facts the UI must provide for that decision | Conditions that change urgency, safety, or next action | Common actions | Occasional, expert, destructive, admin, or configuration actions | Product or journey questions that remain open |

## Information Relevance Inventory

| Journey | Surface | Item | Relevance | Why it matters | Condition/frequency | Evidence source |
| --- | --- | --- | --- | --- | --- | --- |
| Journey name | Screen or route | Fact, control, status, warning, or detail | critical-always / primary-frequent / secondary-occasional / rare-under-5-percent | Decision or task this item supports | Always, frequent, conditional, rare, destructive, admin, or expert-only | Doc, user answer, metric, support signal, or source hint |

## UI Handoff Constraints

| Surface | Decisions the UI must support | Required evidence for UI audit | States to verify | Mockups/screenshots/assets | Unconfirmed assumptions |
| --- | --- | --- | --- | --- | --- |
| Screen or route | Decisions and required facts from the journey model | Screenshot, rendered state, visual tree, DOM/native measurement, accessibility evidence, or blocker | Loading, empty, error, permission, success, warning, destructive, or recovery states | Relevant design artifacts | Open product/journey questions |

### Example: Primary Decision Surface

- Primary user goal: decide whether the current item needs action.
- Primary decision: act now, inspect detail, or continue monitoring.
- Required facts: current status, latest update time, severity, and any threshold warning.
- Frequent actions: perform the current workflow action or inspect the item.
- Secondary/rare actions: adjust display preferences or open advanced configuration when needed.
- UI handoff constraint: the implementation audit must verify that the rendered surface lets the user make this decision and that conditional detail is reachable without overwhelming the decision path.

## Screen Requirements

| Screen | Journey | Critical info | Primary actions | Secondary actions | Rare details | Device/context constraints |
| --- | --- | --- | --- | --- | --- | --- |

## QA And Acceptance

- Happy-path scenarios:
- Edge cases:
- Failure/recovery scenarios:
- Mobile scenarios:
- Accessibility checks:
- Test data or fixture mode:
