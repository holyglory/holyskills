#!/usr/bin/env python3
"""Self-test for the universal-policy semantic contract checker."""

from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).with_name("check_app_wide_policy.py")
SPEC = importlib.util.spec_from_file_location("check_app_wide_policy", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("unable to load policy checker")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


VALID_POLICY = """# Universal Agent Instructions

## Use authoritative context and informed decisions

- Before asking the user to decide, present realistic options in plain language,
  including costs, risks, and a recommendation.
- For every third-party option give its exact name, capabilities, limitations,
  and specifications. Verify facts with current authoritative sources, covering
  maturity, maintenance, licensing, security, privacy, lock-in, and integration;
  distinguish facts, inferences, and unknowns.
- Use an industry-standard foundation. Under-engineering is the more serious
  failure; over-provisioned capacity is acceptable, and present scale alone
  does not justify an inadequate foundation.
- Keep project-root `DecisionHistory.md` as a dense, concise index of major
  decisions, not a report, timeline, or implementation log. Each entry contains
  only `Decision` and `Why`, plus a stable ID and detail-link metadata.
- In `Why`, name the options considered and why the selected option is better.
  If an option was previously tried, state why it did not work. Capture project
  direction, quality bar, workflow expectations, UI preferences, and taste.
- Keep supporting evidence in exactly one project-root
  `DecisionDetails/<decision-id>.md` file per decision. Do not load detail files
  into routine context; read only the relevant file for application, revisit,
  explicit historical work, or audit.
- Maintain a concise evidence-linked `Direction` summary in `DecisionHistory.md`
  that distinguishes confirmed user intent from inferred patterns and cites
  decision IDs. Apply it to analogous work, but not from one ambiguous choice.
- Do not retry a rejected or failed option without new evidence; record what
  changed. When superseding a decision, prevent context loss from reviving it.

## Deliver the complete requested scope

- Maintain project-root `CompletionLedger.md` containing only active unresolved
  partial implementations, TODOs, improvements, and generalizations. Remove an
  item in the same change once implemented and verified; never retain resolved,
  completed, or closed entries or evidence. Delete `CompletionLedger.md` when
  no active items remain. Version control is the default completion history;
  keep consequential decisions in `DecisionHistory.md`. Create project-root
  `CompletionHistory.md` only when explicit audit retention is required; keep
  it out of routine agent context and read it only for explicit historical or
  audit work. Before readiness, verify the end-to-end result.

## Learn from agent-made mistakes

Distinguish changed user intent from a mistake. Before fixing the product,
strengthen a guardrail and retest the original path.

## Put requested interface content first

- A destination label is a content promise. For a list or collection, show its
  real items or honest loading, error, or empty state as the first substantial
  content in the first viewport, including on narrow screens.
- An add or create action must show its focused dialog, sheet, or dedicated page
  in the current viewport; never append it below a long list or off-screen.
  Successful creation returns to the collection and reveals the new item.
- A compact title, search, filter, count, or critical alert may precede the list
  without displacing it. A form may lead on a destination explicitly dedicated
  to creating one item or editing one selected item.
- Use visual exploration only for new directions or redesigns. Persist the
  approval state and exact response request, embedding both when no follow-up
  can appear.
"""


def messages(text: str) -> str:
    return "\n".join(MODULE.find_policy_violations(text))


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    check(not MODULE.find_policy_violations(VALID_POLICY), "complete universal policy should pass")

    uninformed = VALID_POLICY.replace(
        "- Before asking the user to decide, present realistic options in plain language,\n"
        "  including costs, risks, and a recommendation.\n"
        "- For every third-party option give its exact name, capabilities, limitations,\n"
        "  and specifications. Verify facts with current authoritative sources, covering\n"
        "  maturity, maintenance, licensing, security, privacy, lock-in, and integration;\n"
        "  distinguish facts, inferences, and unknowns.",
        "- Ask the user to choose option A or option B and follow their answer.",
    )
    check("informed-decisions contract" in messages(uninformed), "uninformed choice must fail")

    symmetric_foundation = VALID_POLICY.replace(
        "- Use an industry-standard foundation. Under-engineering is the more serious\n"
        "  failure; over-provisioned capacity is acceptable, and present scale alone\n"
        "  does not justify an inadequate foundation.",
        "- Use an industry-standard foundation. Balance under-engineering and\n"
        "  over-provisioned capacity equally; both are acceptable, and present scale\n"
        "  determines which foundation to choose.",
    )
    check("foundation asymmetry" in messages(symmetric_foundation), "symmetric sizing rule must fail")

    no_decision_file = VALID_POLICY.replace("`DecisionHistory.md`", "the decision record")
    check("DecisionHistory.md" in messages(no_decision_file), "unnamed decision record must fail")

    negated_decision_file = VALID_POLICY.replace(
        "- Keep project-root `DecisionHistory.md` as a dense, concise index of major",
        "- Do not use project-root `DecisionHistory.md`; keep an unnamed index of major",
    )
    check("negative instruction" in messages(negated_decision_file), "negated decision file must fail")

    verbose_decision_log = VALID_POLICY.replace(
        "- Keep project-root `DecisionHistory.md` as a dense, concise index of major\n"
        "  decisions, not a report, timeline, or implementation log. Each entry contains\n"
        "  only `Decision` and `Why`, plus a stable ID and detail-link metadata.",
        "- Record implementation, verification, results, and timelines in project-root\n"
        "  `DecisionHistory.md` so every detail remains in the main history.",
    )
    check(
        "informed-decisions contract" in messages(verbose_decision_log),
        "a verbose main decision archive must fail",
    )

    shared_details = VALID_POLICY.replace(
        "exactly one project-root\n  `DecisionDetails/<decision-id>.md` file per decision",
        "one shared project-root decision-details file",
    )
    check("detail file" in messages(shared_details), "shared decision details must fail")

    no_direction = VALID_POLICY.replace(
        "- Maintain a concise evidence-linked `Direction` summary in `DecisionHistory.md`\n"
        "  that distinguishes confirmed user intent from inferred patterns and cites\n"
        "  decision IDs. Apply it to analogous work, but not from one ambiguous choice.",
        "- Follow the latest local technical choice without inferring broader intent.",
    )
    check("project direction" in messages(no_direction), "missing direction synthesis must fail")

    eager_details = VALID_POLICY.replace(
        "read only the relevant file for application, revisit,",
        "read all `DecisionDetails/` files for every task,",
    )
    check("routine context" in messages(eager_details), "eager detail loading must fail")

    no_ledger_file = VALID_POLICY.replace("`CompletionLedger.md`", "the shared ledger")
    check("CompletionLedger.md" in messages(no_ledger_file), "unnamed completion ledger must fail")

    negated_ledger_file = VALID_POLICY.replace(
        "- Maintain project-root `CompletionLedger.md` containing only active unresolved",
        "- Do not maintain project-root `CompletionLedger.md` containing only active unresolved",
    )
    check("negative instruction" in messages(negated_ledger_file), "negated ledger file must fail")

    retained_history = VALID_POLICY.replace(
        "- Maintain project-root `CompletionLedger.md` containing only active unresolved\n"
        "  partial implementations, TODOs, improvements, and generalizations. Remove an\n"
        "  item in the same change once implemented and verified; never retain resolved,\n"
        "  completed, or closed entries or evidence. Delete `CompletionLedger.md` when\n"
        "  no active items remain. Version control is the default completion history;\n"
        "  keep consequential decisions in `DecisionHistory.md`. Create project-root\n"
        "  `CompletionHistory.md` only when explicit audit retention is required; keep\n"
        "  it out of routine agent context and read it only for explicit historical or\n"
        "  audit work. Before readiness, verify the end-to-end result.",
        "- Create project-root `CompletionLedger.md` for each partial implementation,\n"
        "  TODO, improvement, and generalization. Resolve every entry before readiness\n"
        "  and retain it as history after verifying the end-to-end result.",
    )
    check(
        "completion-ledger contract" in messages(retained_history),
        "a completion ledger that retains resolved history must fail",
    )

    contradictory_history = VALID_POLICY.replace(
        "  audit work. Before readiness, verify the end-to-end result.",
        "  audit work. Keep resolved entries or evidence in the active ledger as history.\n"
        "  Before readiness, verify the end-to-end result.",
    )
    check(
        "must not preserve terminal entries" in messages(contradictory_history),
        "a contradictory terminal-retention rule must fail",
    )

    for contradiction in (
        "Resolved entries may remain.",
        "Do not remove completed rows.",
        "Preserve entries after they are closed.",
        "Never delete tests; keep resolved rows.",
        "Remove closed items in a separate change.",
    ):
        contradictory_policy = VALID_POLICY.replace(
            "  audit work. Before readiness, verify the end-to-end result.",
            f"  audit work. {contradiction}\n  Before readiness, verify the end-to-end result.",
        )
        check(
            "must not preserve terminal entries" in messages(contradictory_policy),
            f"terminal-retention wording must fail: {contradiction}",
        )

    cold_history = VALID_POLICY.replace(
        "  audit work. Before readiness, verify the end-to-end result.",
        "  audit work. `CompletionHistory.md` may preserve resolved evidence.\n"
        "  Version control may preserve completed entries as history. Before readiness,\n"
        "  verify the end-to-end result.",
    )
    check(
        not MODULE.find_policy_violations(cold_history),
        "explicit cold history must not be mistaken for active-ledger retention",
    )

    missing_same_change = VALID_POLICY.replace("in the same change once", "eventually after")
    check(
        "same change" in messages(missing_same_change),
        "terminal entries left for later cleanup must fail",
    )

    retained_empty_file = VALID_POLICY.replace(
        "Delete `CompletionLedger.md` when\n  no active items remain.",
        "Keep `CompletionLedger.md` as an empty template when no active items remain.",
    )
    check(
        "empty CompletionLedger.md" in messages(retained_empty_file),
        "an empty retained ledger must fail",
    )

    buried_collection = VALID_POLICY.replace(
        "- A destination label is a content promise. For a list or collection, show its\n"
        "  real items or honest loading, error, or empty state as the first substantial\n"
        "  content in the first viewport, including on narrow screens.",
        "- Keep the primary artifact prominent and progressively disclose secondary controls.",
    )
    check("collection-destination contract" in messages(buried_collection), "buried list policy must fail")

    offscreen_create = VALID_POLICY.replace(
        "- An add or create action must show its focused dialog, sheet, or dedicated page\n"
        "  in the current viewport; never append it below a long list or off-screen.\n"
        "  Successful creation returns to the collection and reveals the new item.",
        "- Place creation forms where they fit the page layout.",
    )
    check("visible-create-flow contract" in messages(offscreen_create), "off-screen create policy must fail")

    transient_approval = VALID_POLICY.replace(
        "- Use visual exploration only for new directions or redesigns. Persist the\n"
        "  approval state and exact response request, embedding both when no follow-up\n"
        "  can appear.",
        "- Ask for visual approval only in a transient progress message.",
    )
    check(
        "persistent-approval contract" in messages(transient_approval),
        "transient-only visual approval must fail",
    )

    named_tool = VALID_POLICY + "\nUse Codex for implementation.\n"
    check("named product or tool" in messages(named_tool), "named assistant must fail")

    absolute_path = VALID_POLICY + "\nLoad /opt/example/policy before work.\n"
    check("filesystem path" in messages(absolute_path), "absolute path must fail")

    print("app-wide policy checker self-test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
