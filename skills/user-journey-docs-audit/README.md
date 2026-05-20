# User Journey Docs Audit

`user-journey-docs-audit` checks whether a repo has enough product and development documentation to build an app that is genuinely easy to use, not just feature-complete.

Use it before UI implementation, redesign, or a full-repo interface audit when the app idea, target users, priority journeys, screen hierarchy, mobile constraints, or acceptance criteria are unclear.

## What It Audits

- App idea, user groups, expertise, context, and mistake cost.
- Complete journey inventory, including frequent, rare, failure, permission, onboarding, recovery, and power-user paths.
- Per-journey screen requirements: primary information, probable navigation routes, critical warnings, secondary detail, and rare detail that should live behind menus, expanders, tabs, or drill-in routes.
- Journey priority contracts for UI implementation: primary goal, decision-making information, frequent actions, occasional controls, rare/admin/configuration controls, and expected desktop/mobile order.
- First-viewport documentation, especially on mobile: what appears before scroll, whether primary decision data is visible, how much space low-frequency controls may consume, and what the user can decide immediately.
- Mobile and desktop fit for critical information and actions.
- Accessibility, states, acceptance criteria, QA hooks, analytics/support clues, and implementation readiness.

## Required Behavior

The skill must actively interview the user when journey information is missing or ambiguous. It should not silently infer journeys and call the docs complete. If the user cannot answer during the run, the report must label those journeys as `journey assumptions unconfirmed`.

For UI handoff, the skill should flag a P1 when docs leave mobile priority ambiguous enough that implementers might put settings, filters, target/configuration panels, or other low-frequency controls above primary decision content.

## Helper Command

```bash
python3 skills/user-journey-docs-audit/scripts/build_journey_docs_inventory.py --repo <repo>
```

Use `--json` when another script or agent needs machine-readable inventory output.

## References

- `references/ux_principles.md`: compact rubric of UX principles used by the audit.
- `references/journey_doc_template.md`: reusable documentation template for app idea, users, journeys, screen requirements, and QA acceptance criteria.
