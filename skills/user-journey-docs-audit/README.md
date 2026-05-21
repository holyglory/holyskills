# User Journey Docs Audit

`user-journey-docs-audit` checks whether a repo has enough product and
development documentation to build an app that is genuinely easy to use and
complete: journeys, features, UI elements, implementation expectations, and
tests are all spelled out.

Use it before UI implementation, redesign, or a full-repo interface audit when
the app idea, target users, journey set, feature set, UI element set, screen
decision needs, device constraints, implementation expectations, tests, or
acceptance criteria are unclear.

## What It Audits

- App idea, user groups, expertise, context, and mistake cost.
- Complete feature inventory, required UI element inventory, implementation
  expectations, and test expectations.
- Complete journey inventory, including frequent, rare, failure, permission, onboarding, recovery, and power-user paths.
- Per-journey decision model: primary decision, required facts, warning/flag conditions, frequent actions, secondary/rare actions, and unresolved assumptions.
- Information relevance inventory for UI implementation: critical-always, primary-frequent, secondary-occasional, rare-under-5-percent, conditional, destructive, and expert-only information/actions.
- UI handoff constraints for the implementation audit: screens/routes/states to verify, evidence expected from screenshots or rendered surfaces, and assumptions that remain unconfirmed.
- Mobile and desktop fit for critical information and actions.
- Accessibility, states, acceptance criteria, QA hooks, analytics/support clues, and implementation readiness.

## Required Behavior

The skill must actively interview the user when journey information is missing or ambiguous. It should not silently infer journeys and call the docs complete. If the user cannot answer during the run, the report must label those journeys as `journey assumptions unconfirmed`.

For UI handoff, the skill should flag a P1 when docs use terms such as `dense`, `dashboard`, `command center`, `overview`, or `compact` without defining the decisions, information relevance, action frequency, and assumptions behind those terms.

## Helper Command

```bash
python3 skills/user-journey-docs-audit/scripts/build_journey_docs_inventory.py --repo <repo>
```

Use `--json` when another script or agent needs machine-readable inventory output.

## References

- `references/ux_principles.md`: compact rubric of UX principles used by the audit.
- `references/journey_doc_template.md`: reusable documentation template for app idea, users, journeys, screen requirements, and QA acceptance criteria.
