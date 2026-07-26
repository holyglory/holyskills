#!/usr/bin/env python3
"""Self-test for the universal-policy semantic contract checker."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path


SCRIPT = Path(__file__).with_name("check_app_wide_policy.py")
SPEC = importlib.util.spec_from_file_location("check_app_wide_policy", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("unable to load policy checker")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
CANONICAL_POLICY = SCRIPT.parents[1] / "reference" / "codex-app-wide" / "AGENTS.md"


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

## Measure delivery efficiency truthfully

- Efficiency telemetry is observational and subordinate to complete scope,
  correctness, safety, maintainability, verification, and honest reporting.
  Never omit required work, context, tests, or explanation to improve a metric.
- When measurement is configured, use a runtime- or harness-owned recorder from
  request receipt through terminal delivery, recording first model or tool
  activity separately. Report request-to-delivery wall time and execution wall
  time separately so queue or scheduling delay remains visible. Append durably
  and concurrency-safely to a cold `EfficiencyLedger.jsonl` outside source
  worktrees and routine context. This policy does not itself capture telemetry;
  a missing recorder or unsupported counter is an explicit instrumentation gap,
  never a reason to reconstruct or estimate an unknown value. Record zero only
  when complete instrumentation proves no usage; otherwise record `unknown` or
  `not-applicable`.
- Record task start and a terminal status of complete, incomplete, blocked,
  cancelled, superseded, or interrupted. Preserve prior events; append linked
  continuations and corrections instead of rewriting history. Append later
  defects, retries, rollback, and rework to the original lineage when known,
  without double-counting an event. Classify linked later work on separate
  dimensions: its kind is continuation, retry, rollback, defect repair, or
  rework; its cause is agent-caused mistake, changed user intent, new scope,
  external cause, or unknown.
- Use only authoritative runtime or provider token counters and a monotonic
  clock, with their provenance and instrumentation coverage. Preserve available
  provider-native input, output, cached, reasoning, and other token categories.
  Include the root and delegated agents, tool work, failed attempts, retries,
  and rework; mark unobserved or self-reported fields explicitly rather than
  implying precision.
- Label every observed model, tool, and wait span on two independent dimensions.
  Its phase is planning, implementation, testing, deployment, reporting, or
  unattributed. Its activity state is model-active, tool-active, external-wait,
  user-wait, or blocked-wait. A test or deployment operation remains in that
  phase while waiting. Test authoring and a fix after a failed test are
  implementation; test execution and post-deployment verification are testing.
  Planning covers requirements, context, research, diagnosis, design, and
  sequencing. Implementation covers changes to code, configuration,
  documentation, data, and test artifacts. Testing covers executing and
  reviewing verification. Deployment covers release or environment mutation;
  reporting covers user-facing status and handoff. Ambiguous mixed work is
  unattributed.
- Keep measurement provenance separate from attribution provenance. Mark every
  phase, activity state, scope, outcome, verification, task-type, scope-size,
  and method classification as runtime-observed, agent-declared, inferred, or
  unknown, with its classifier or schema version. Never present an inferred
  allocation as measured.
- For each phase, report authoritative token counters, phase-inclusive elapsed
  interval unions, and activity-state duration. Deduplicate overlapping spans.
  Report end-to-end wall time separately from summed per-agent active time;
  concurrent phase unions may overlap and must not be summed as wall time.
- A terminal event identifies task lineage, nonsensitive opaque project and
  revision identifiers when known, schema, recorder, policy, model or runtime
  configuration versions, outcome, counters, coverage, and measurement
  overhead. Bind it to the agreed requested-scope and acceptance baseline plus
  user-approved scope changes. Record each nonsensitive requirement ID or
  evidence reference as satisfied, partial, blocked, or explicitly removed,
  with delivered scope, verification, evidence provenance, and known defect and
  rework links. A task cannot be complete while an in-scope requirement remains
  unresolved.
- Use stable, versioned, low-cardinality, nonsensitive task-type, scope-size, and
  method tags so compatible approaches can be compared. Compare efficiency only
  under compatible measurement semantics and alongside outcome, scope,
  verification, defects, and rework. Keep collection passive and proportionate;
  do not add material calls or delay solely to improve measurement precision.
- Never retain prompts, source content, tool payloads, secrets, credentials, or
  personal data in efficiency telemetry.

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


def replace_section(text: str, heading: str, replacement: str) -> str:
    pattern = rf"^## {re.escape(heading)}\s*$\n.*?(?=^## |\Z)"
    updated, count = re.subn(pattern, replacement, text, flags=re.MULTILINE | re.DOTALL)
    if count != 1:
        raise AssertionError(f"expected exactly one {heading!r} section")
    return updated


def main() -> int:
    canonical_efficiency = MODULE.section(
        CANONICAL_POLICY.read_text(encoding="utf-8"),
        "Measure delivery efficiency truthfully",
    )
    check(
        MODULE.section(VALID_POLICY, "Measure delivery efficiency truthfully") == canonical_efficiency,
        "self-test efficiency fixture must exactly match the canonical policy section",
    )
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

    no_efficiency = replace_section(VALID_POLICY, "Measure delivery efficiency truthfully", "")
    check(
        "delivery-efficiency section is missing" in messages(no_efficiency),
        "missing efficiency policy must fail",
    )

    privacy_marker = (
        "- Never retain prompts, source content, tool payloads, secrets, credentials, or\n"
        "  personal data in efficiency telemetry.\n"
    )

    def add_efficiency_rule(rule: str) -> str:
        return VALID_POLICY.replace(privacy_marker, privacy_marker + rule + "\n")

    def add_outside_efficiency(rule: str) -> str:
        return VALID_POLICY + "\n## Telemetry Overrides\n\n" + rule + "\n"

    contradictions = (
        (
            "- Store `EfficiencyLedger.jsonl` in project-root routine context.",
            "must not become hot project context",
        ),
        (
            "- Token counters may be estimated when missing from the provider.",
            "must not be estimated",
        ),
        (
            "- Record missing token counters as zero.",
            "must not be zero-filled",
        ),
        (
            "- Agents may skip tests to improve the efficiency metric.",
            "must not reward reduced delivery quality or scope",
        ),
        (
            "- Agents may rewrite prior events after a corrected measurement.",
            "must be corrected append-only",
        ),
        (
            "- Agents may combine phase and activity state into one label.",
            "must not be collapsed",
        ),
        (
            "- Agents may omit failed attempts from efficiency totals.",
            "must include failed and delegated work",
        ),
        (
            "- Telemetry may retain prompts for later analysis.",
            "must not retain sensitive content",
        ),
        (
            "- Only record the terminal event for each task.",
            "must include start and terminal lifecycle events",
        ),
        (
            "- Retain prompts and source content for later efficiency analysis.",
            "must not retain sensitive content",
        ),
        (
            "- Do not include delegated agents or failed attempts in efficiency totals.",
            "must include failed and delegated work",
        ),
        (
            "- Estimate missing efficiency counters.",
            "must not be estimated",
        ),
        (
            "- Rewrite prior events when a later correction arrives.",
            "must be corrected append-only",
        ),
        (
            "- Combine phase and activity state into one label.",
            "must not be collapsed",
        ),
        (
            "- Use heuristic estimates when authoritative counters are unavailable.",
            "must not be estimated",
        ),
        (
            "- Report inferred phase allocation as measured.",
            "must not be presented as measured",
        ),
        (
            "- Report inferred phase allocations as measured values.",
            "must not be presented as measured",
        ),
        (
            "- Count inferred phase allocations as measurements.",
            "must not be presented as measured",
        ),
        (
            "- A task may be complete with unresolved in-scope requirements.",
            "must not ignore unresolved in-scope requirements",
        ),
        (
            "- A task may be complete while an in-scope requirement remains unresolved.",
            "must not ignore unresolved in-scope requirements",
        ),
        (
            "- A task can be called complete despite an unresolved in-scope requirement.",
            "must not ignore unresolved in-scope requirements",
        ),
        (
            "- Complete the task even when an in-scope requirement is unresolved.",
            "must not ignore unresolved in-scope requirements",
        ),
        (
            "- Use successful as an additional terminal status.",
            "exact terminal status set",
        ),
        (
            "- Add ready as another terminal status.",
            "exact terminal status set",
        ),
        (
            "- Use done as an extra terminal outcome.",
            "exact terminal status set",
        ),
        (
            "- Collapse provider-native input, output, cached, and reasoning token categories.",
            "token categories must not be collapsed",
        ),
        (
            "- Report one total instead of provider-native token categories.",
            "token categories must not be collapsed",
        ),
        (
            "- Treat research and diagnosis as implementation.",
            "planning work must not be reclassified as implementation",
        ),
        (
            "- Combine request-to-delivery and execution wall time.",
            "wall time must remain separate",
        ),
        (
            "- Record uninstrumented activity as zero.",
            "must not be zero-filled",
        ),
        (
            "- Treat changed user intent and new scope as agent-caused rework.",
            "must not be counted as agent-caused rework",
        ),
        (
            "- Store raw private project and revision names.",
            "must remain nonsensitive and opaque",
        ),
    )
    for rule, expected in contradictions:
        for location, policy in (
            ("inside", add_efficiency_rule(rule)),
            ("outside", add_outside_efficiency(rule)),
            ("outside prose", add_outside_efficiency(rule.removeprefix("- "))),
        ):
            check(
                expected in messages(policy),
                f"contradictory efficiency rule must fail {location} its section: {rule}",
            )

    explicit_privacy = add_efficiency_rule(
        "- Include an explicit safeguard so prompts and secrets are never retained."
    )
    check(
        not MODULE.find_policy_violations(explicit_privacy),
        "an additional negative privacy safeguard must not be treated as retention",
    )

    excluded_privacy = add_efficiency_rule(
        "- Record that prompts were excluded from efficiency telemetry."
    )
    check(
        not MODULE.find_policy_violations(excluded_privacy),
        "recording that sensitive payloads were excluded must remain valid",
    )

    explicit_cold_storage = add_efficiency_rule(
        "- Keep `EfficiencyLedger.jsonl` outside source worktrees and routine context.\n"
        "- Never store `EfficiencyLedger.jsonl` in a source worktree.\n"
        "- Never record missing counters as zero."
    )
    check(
        not MODULE.find_policy_violations(explicit_cold_storage),
        "an additional cold-storage safeguard must not be treated as hot storage",
    )

    provenance_guard = add_efficiency_rule(
        "- Phase attribution may be inferred only when marked inferred; never present it as measured."
    )
    check(
        not MODULE.find_policy_violations(provenance_guard),
        "explicitly labeled inferred attribution must remain valid",
    )

    proven_zero = add_efficiency_rule(
        "- Record zero only when complete instrumentation proves no usage; otherwise record unknown."
    )
    check(
        not MODULE.find_policy_violations(proven_zero),
        "zero backed by complete instrumentation must remain valid",
    )

    policy_as_recorder = VALID_POLICY.replace(
        "This policy does not itself capture telemetry;\n  a missing",
        "This policy itself captures telemetry;\n  a missing",
    )
    check(
        "operational recorder" in messages(policy_as_recorder),
        "policy text must not claim to implement the recorder",
    )

    delayed_start = VALID_POLICY.replace(
        "use a runtime- or harness-owned recorder from\n  request receipt through terminal delivery, recording first model or tool\n  activity separately",
        "use a runtime- or harness-owned recorder after\n  the first model or tool activity through terminal delivery",
    )
    check(
        "request delay" in messages(delayed_start),
        "measurement beginning after first activity must fail",
    )

    weakened_terminal = VALID_POLICY.replace(
        "terminal status of complete, incomplete, blocked,",
        "terminal status of successful, incomplete, blocked,",
    )
    check(
        "exact terminal status set" in messages(weakened_terminal),
        "renaming the complete terminal status must fail",
    )

    extra_terminal = VALID_POLICY.replace(
        "cancelled, superseded, or interrupted.",
        "cancelled, superseded, interrupted, or successful.",
    )
    check(
        "exact terminal status set" in messages(extra_terminal),
        "adding an unapproved terminal status must fail",
    )

    missing_attribution = VALID_POLICY.replace(
        "Keep measurement provenance separate from attribution provenance.",
        "Treat every phase allocation as an authoritative measurement.",
    )
    check(
        "attribution" in messages(missing_attribution),
        "phase splits without attribution provenance must fail",
    )

    missing_phase_taxonomy = VALID_POLICY.replace(
        "Planning covers requirements, context, research, diagnosis, design, and\n"
        "  sequencing. Implementation covers changes to code, configuration,\n"
        "  documentation, data, and test artifacts. Testing covers executing and\n"
        "  reviewing verification. Deployment covers release or environment mutation;\n"
        "  reporting covers user-facing status and handoff. Ambiguous mixed work is\n"
        "  unattributed.",
        "Classify phases using local judgment.",
    )
    check(
        "operational boundaries" in messages(missing_phase_taxonomy),
        "undefined phase taxonomy must fail",
    )

    collapsed_rework_cause = VALID_POLICY.replace(
        "Classify linked later work on separate\n"
        "  dimensions: its kind is continuation, retry, rollback, defect repair, or\n"
        "  rework; its cause is agent-caused mistake, changed user intent, new scope,\n"
        "  external cause, or unknown.",
        "Classify all linked later work as agent-caused rework.",
    )
    check(
        "separate kind from cause" in messages(collapsed_rework_cause),
        "work kind and cause collapsed into agent rework must fail",
    )

    collapsed_scope = VALID_POLICY.replace(
        "Bind it to the agreed requested-scope and acceptance baseline plus\n"
        "  user-approved scope changes. Record each nonsensitive requirement ID or\n"
        "  evidence reference as satisfied, partial, blocked, or explicitly removed,\n"
        "  with delivered scope, verification, evidence provenance, and known defect and\n"
        "  rework links. A task cannot be complete while an in-scope requirement remains\n"
        "  unresolved.",
        "Record the delivered scope without the original requirements or accepted changes.",
    )
    check(
        "agreed-scope" in messages(collapsed_scope),
        "delivered scope without the agreed baseline must fail",
    )

    collapsed_timing = VALID_POLICY.replace(
        "For each phase, report authoritative token counters, phase-inclusive elapsed\n"
        "  interval unions, and activity-state duration. Deduplicate overlapping spans.\n"
        "  Report end-to-end wall time separately from summed per-agent active time;\n"
        "  concurrent phase unions may overlap and must not be summed as wall time.",
        "For each phase, report one elapsed total for all agents and waits.",
    )
    check(
        "timing" in messages(collapsed_timing) or "wall time" in messages(collapsed_timing),
        "collapsed concurrent timing must fail",
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
