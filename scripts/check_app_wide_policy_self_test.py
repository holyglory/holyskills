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
- Use project-root `DecisionHistory.md` to record the decision.

## Deliver the complete requested scope

- Create project-root `CompletionLedger.md` for each partial implementation,
  TODO, improvement, and generalization. Resolve every entry before readiness
  and verify the end-to-end result.

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
        "- Use project-root `DecisionHistory.md` to record the decision.",
        "- Do not use project-root `DecisionHistory.md`; use an unnamed record.",
    )
    check("negative instruction" in messages(negated_decision_file), "negated decision file must fail")

    no_ledger_file = VALID_POLICY.replace("`CompletionLedger.md`", "the shared ledger")
    check("CompletionLedger.md" in messages(no_ledger_file), "unnamed completion ledger must fail")

    negated_ledger_file = VALID_POLICY.replace(
        "- Create project-root `CompletionLedger.md` for each partial implementation,",
        "- Do not create project-root `CompletionLedger.md` for a partial implementation,",
    )
    check("negative instruction" in messages(negated_ledger_file), "negated ledger file must fail")

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

    oversized = VALID_POLICY + ("word " * (MODULE.MAX_WORDS + 1))
    check("exceeds" in messages(oversized), "oversized policy must fail")

    print("app-wide policy checker self-test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
