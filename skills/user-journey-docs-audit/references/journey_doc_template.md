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
- Primary actions:
- Secondary/rare actions:
- Details to hide behind menus/expanders:
- Critical warnings that must stay visible:
- Empty/loading/error/permission states:
- Recovery and undo:
- Mobile expectations:
- Accessibility expectations:
- Acceptance criteria:
- Analytics/support signals:

## Journey Priority Contract

| Surface | Primary user goal | Primary information | Frequent actions | Occasional controls | Rare/Admin/Configuration controls | Expected desktop order | Expected mobile order |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Screen or route | User outcome this surface must support | Decision-making content users need first | Common actions | Sometimes-needed controls | Low-frequency settings, filters, admin, or configuration | Primary content/action order on desktop | Primary content/action order on mobile |

## First Viewport Requirements

| Viewport | First visible content | Primary decision data | Low-frequency controls | Allowed control share | What can the user decide? |
| --- | --- | --- | --- | --- | --- |
| Mobile/narrow | Content visible before scroll | Data that must be visible before scroll | Settings/filters/configuration that may appear | Target share, usually below 25-30% if primary data is below | Concrete decision the user can make immediately |

### Example: Primary Metrics Dashboard

- Primary user goal: understand the most important live metrics quickly.
- Primary information: high-priority metric list and latest update time.
- Frequent actions: inspect a metric or continue the current workflow.
- Occasional controls: adjust a display filter.
- Rare/Admin/Configuration controls: advanced settings and configuration.
- Expected mobile order: high-priority metrics first; settings/filter controls after primary content or behind a secondary control.

## Screen Requirements

| Screen | Journey | Critical info | Primary actions | Secondary actions | Rare details | Mobile fit requirement |
| --- | --- | --- | --- | --- | --- | --- |

## QA And Acceptance

- Happy-path scenarios:
- Edge cases:
- Failure/recovery scenarios:
- Mobile scenarios:
- Accessibility checks:
- Test data or fixture mode:
