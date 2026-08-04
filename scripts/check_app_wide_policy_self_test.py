#!/usr/bin/env python3
"""Recall and precision self-test for the universal-policy checker."""

from __future__ import annotations

import importlib.util
import re
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("check_app_wide_policy.py")
SPEC = importlib.util.spec_from_file_location("check_app_wide_policy", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("unable to load policy checker")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
CANONICAL = SCRIPT.parents[1] / "reference" / "codex-app-wide" / "AGENTS.md"


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def messages(text: str) -> str:
    return "\n".join(MODULE.find_policy_violations(text))


def replace_section(text: str, heading: str, body: str) -> str:
    pattern = rf"^## {re.escape(heading)}\s*$\n.*?(?=^## |\Z)"
    replacement = f"## {heading}\n\n{body.rstrip()}\n\n"
    updated, count = re.subn(pattern, replacement, text, flags=re.MULTILINE | re.DOTALL)
    if count != 1:
        raise AssertionError(f"expected one section {heading!r}")
    return updated


def replace_last(text: str, old: str, new: str) -> str:
    head, separator, tail = text.rpartition(old)
    if not separator:
        raise AssertionError(f"expected text fragment {old!r}")
    return head + new + tail


def main() -> int:
    policy = CANONICAL.read_text(encoding="utf-8")
    check(not MODULE.find_policy_violations(policy), "canonical policy must pass")

    cases = (
        (
            "redundant context",
            policy + "\nAlways reread every unchanged file and load every skill or tool.\n",
            "context must remain relevant",
        ),
        (
            "automatic scope expansion",
            policy + "\nImplement unrequested hypothetical hardening without asking.\n",
            "unrequested engineering must never proceed without informed approval",
        ),
        (
            "automatic risk-control expansion",
            policy
            + "\nProceed with privacy hardening and backup infrastructure without approval "
            "whenever it seems safer.\n",
            "risk-control expansion must not proceed without user approval",
        ),
        (
            "missing security-assumptions section",
            replace_section(
                policy,
                "Ground security-posture decisions in confirmed assumptions",
                "- Apply generally accepted security practices in proportion to the work.\n"
                "- Ask before expanding the requested scope.",
            ),
            "security-assumptions gate",
        ),
        (
            "missing security-assumptions file bypass",
            policy
            + "\nIf security-assumptions.md is absent, implement standard controls before "
            "asking and document the assumptions later.\n",
            "missing security assumptions must stop implementation",
        ),
        (
            "unconditional absent-file baseline",
            policy
            + "\nIf security-assumptions.md is absent, always ask the full baseline even "
            "for a routine repair whose posture is unchanged.\n",
            "must not trigger an unconditional full baseline",
        ),
        (
            "routine reviewed tool reopens assumptions",
            policy
            + "\nRoutine invocation of a reviewed tool always triggers a full baseline "
            "security interview even when its posture is preserved.\n",
            "routine posture-preserving tool use must not trigger a security interview",
        ),
        (
            "one assumption triggers unrelated baseline",
            policy
            + "\nThe only material assumption is whether the service is remote, but it "
            "must trigger a full baseline before the control decision.\n",
            "one material assumption must not trigger an unrelated full baseline",
        ),
        (
            "fixed exhaustive question",
            policy
            + "\nAlways present every decision detail whether or not it can materially "
            "affect the choice.\n",
            "decision questions must not require fixed exhaustive detail",
        ),
        (
            "unresolved material control assumption",
            policy
            + "\nProceed with the security control despite an unresolved material "
            "assumption.\n",
            "material control decision must not proceed on an unresolved material assumption",
        ),
        (
            "inferred threat model",
            policy
            + "\nAgents should infer an internet-facing threat model when project facts "
            "are unavailable.\n",
            "security assumptions and threats must be user-confirmed",
        ),
        (
            "blanket hardening",
            policy
            + "\nAlways apply maximum hardening controls regardless of project assumptions.\n",
            "blanket security controls must not replace assumption-backed proportional controls",
        ),
        (
            "weakened control bypass",
            policy
            + "\nRemove the authorization control without reading confirmed security "
            "assumptions.\n",
            "weakened, removed, or omitted controls require confirmed security assumptions",
        ),
        (
            "omitted control bypass",
            policy
            + "\nIntentionally omit the authentication control without citing confirmed "
            "security assumptions.\n",
            "weakened, removed, or omitted controls require confirmed security assumptions",
        ),
        (
            "unconfirmed assumptions template",
            policy
            + "\nCreate security-assumptions.md from the standard template and mark it as "
            "confirmed.\n",
            "security-assumption templates and defaults are unconfirmed",
        ),
        (
            "unknown assumption can justify a control",
            policy.replace(
                "an unknown or otherwise\n  unconfirmed assumption cannot justify",
                "an unknown or otherwise\n  unconfirmed assumption may justify",
                1,
            ),
            "security-assumptions gate",
        ),
        (
            "non-security work triggers an interview",
            policy.replace(
                "Non-security\n  changes do not trigger a security interview",
                "Non-security\n  changes always trigger a security interview",
                1,
            ),
            "security-assumptions gate",
        ),
        (
            "read-only discovery selects a control",
            policy.replace(
                "provided it\n  does not select, apply, alter, or omit a security-posture control",
                "and may select a security-posture control before confirmation",
                1,
            ),
            "security-assumptions gate",
        ),
        (
            "automatic hypothetical preservation",
            policy
            + "\nAutomatically preserve and migrate all user data even when not requested.\n",
            "hypothetical engineering must not expand scope automatically",
        ),
        (
            "softened under-engineering rule",
            policy.replace(
                "Under-engineering the agreed\n  result is unacceptable",
                "Under-engineering the agreed\n  result is merely unfortunate",
                1,
            ),
            "under-engineering must be unacceptable",
        ),
        (
            "inverted under-engineering asymmetry",
            policy
            + "\nImplementation gaps are less serious and less punishable than extra work.\n",
            "implementation gaps must remain the more serious failure",
        ),
        (
            "silent expansion allowed",
            policy + "\nSilent scope expansion is permitted when an agent prefers it.\n",
            "silent scope expansion must remain prohibited",
        ),
        (
            "blanket question for every potential expansion",
            policy
            + "\nEvery potential over-engineering expansion must trigger a comprehensive "
            "question, even when no answer can change the work.\n",
            "immaterial potential expansions must not trigger blanket questions",
        ),
        (
            "restart at first gap",
            policy + "\nStop the test at the first failure, fix each gap, and restart.\n",
            "must not stop at the first ordinary failure",
        ),
        (
            "deployment stopped at first gap",
            policy + "\nStop deployment at the first failure and patch immediately.\n",
            "must not stop at the first ordinary failure",
        ),
        (
            "automatic disposable-data preservation",
            policy + "\nAlways preserve disposable test data before every change.\n",
            "must not trigger automatic preservation work",
        ),
        (
            "unbounded tool output",
            policy + "\nRequest unbounded tool output for all diagnostics.\n",
            "tool output must remain bounded",
        ),
        (
            "missing expansion approval",
            policy.replace(
                "Do not begin a material expansion until the user approves\n  it",
                "The agent may begin the expansion while waiting for a response",
                1,
            ),
            "user approves it",
        ),
        (
            "missing complete-cycle behavior",
            replace_section(
                policy,
                "Finish diagnostic cycles before batch fixing",
                "- Stop on the first issue, fix it, and restart the suite.",
            ),
            "complete-cycle contract",
        ),
        (
            "missing active-only completion ledger",
            replace_section(
                policy,
                "Deliver the complete agreed scope",
                "- Keep a historical list of completed work and call partial work done.",
            ),
            "complete-delivery contract",
        ),
        (
            "missing scoped issue-ledger schema",
            replace_section(
                policy,
                "Learn from agent-made mistakes",
                "- Remember mistakes informally and fix them immediately.",
            ),
            "agent-mistake contract",
        ),
        (
            "weak detector verification",
            replace_section(
                policy,
                "Verify real behavior",
                "- Run one happy-path unit test.",
            ),
            "verification contract",
        ),
        (
            "estimated telemetry",
            policy + "\nEstimate unknown token counters when the recorder is missing.\n",
            "missing telemetry must not be estimated",
        ),
        (
            "collapsed native counters",
            policy + "\nCollapse provider-native counters into one total.\n",
            "token categories must remain distinct",
        ),
        (
            "phase boundary collapse",
            policy + "\nTreat test execution as implementation.\n",
            "phase boundaries must remain stable",
        ),
        (
            "delegated ledger bypass",
            policy + "\nDelegated agents may skip issue ledgers.\n",
            "delegated work must receive relevant issue-ledger constraints",
        ),
        (
            "missing telemetry lifecycle",
            replace_section(
                policy,
                "Measure delivery efficiency truthfully",
                "- Store a manual total in the repository.",
            ),
            "delivery-efficiency contract",
        ),
        (
            "form-first collection",
            policy + "\nA collection should show the creation form first.\n",
            "collection destinations must not lead with forms",
        ),
        (
            "missing implemented-product-behavior contract",
            replace_section(
                policy,
                "Prohibit unimplemented product behavior",
                "- Render each requested screen and verify its routes and screenshots.",
            ),
            "implemented-product-behavior contract",
        ),
        (
            "enabled placeholder control",
            policy + "\nPlaceholder controls may remain enabled until backend work begins.\n",
            "must not remain enabled",
        ),
        (
            "complete UI with inert behavior",
            policy + "\nThe agent may report the interface complete with inert agreed controls.\n",
            "must not be reported complete",
        ),
        (
            "optional interaction inventory",
            policy + "\nThe interaction inventory is optional for ordinary UI work.\n",
            "must not be optional or skippable",
        ),
        (
            "agent may skip interaction inventory",
            policy + "\nAgents may skip the interaction inventory for ordinary UI work.\n",
            "must not be optional or skippable",
        ),
        (
            "representative controls replace inventory",
            policy + "\nTesting representative controls is sufficient for UI completion.\n",
            "must not substitute for the complete agreed UI inventory",
        ),
        (
            "representative subset replaces inventory",
            policy + "\nOnly a representative subset of controls needs to be exercised.\n",
            "must not substitute for the complete agreed UI inventory",
        ),
        (
            "generic UI gap ledger",
            policy + "\nA generic future-production completion-ledger item is acceptable.\n",
            "must not conceal distinct missing UI behavior",
        ),
        (
            "catch-all ledger covers UI gaps",
            policy + "\nA single catch-all ledger entry may cover all missing UI behavior.\n",
            "must not conceal distinct missing UI behavior",
        ),
        (
            "unlabelled future control",
            policy + "\nFuture controls need not be labelled unavailable.\n",
            "must retain the disabled, unavailable, and ledger gates",
        ),
        (
            "clickable future control",
            policy + "\nFuture controls may remain clickable while marked as planned.\n",
            "must not remain enabled",
        ),
        (
            "interaction inventory authorizes audit",
            policy + "\nThe interaction inventory automatically authorizes a broader exhaustive audit.\n",
            "must not authorize a broader audit",
        ),
        (
            "complete with tracked future control",
            policy
            + "\nThe agent may report the UI complete while a future control remains "
            "unimplemented in the completion ledger.\n",
            "must not be reported complete",
        ),
        (
            "screenshots substitute for interaction",
            policy + "\nScreenshots count as interaction verification for visible controls.\n",
            "must not count as interaction verification",
        ),
        (
            "screenshots substitute despite later negation",
            policy
            + "\nScreenshots prove interaction verification, so rendered interaction is "
            "not needed.\n",
            "must not count as interaction verification",
        ),
        (
            "handler substitutes for interaction",
            policy + "\nA handler proves working behavior without exercising the control.\n",
            "must not prove product interaction",
        ),
        (
            "missing content-first UI",
            replace_section(
                policy,
                "Put requested interface content first",
                "- Put setup and administration above the named content.",
            ),
            "interface-content contract",
        ),
        (
            "positive authorization wording",
            policy + "\nAuthenticated telemetry means the agent is authorized.\n",
            "must not grant agent authority",
        ),
        (
            "runtime-specific policy",
            policy + "\nCodex must apply this product-specific rule.\n",
            "runtime/project-specific term: Codex",
        ),
    )
    for name, candidate, expected in cases:
        result = messages(candidate)
        check(expected in result, f"{name} fixture did not trigger {expected!r}: {result}")

    missing_proportional_question_terms = (
        (
            "wrong-answer materiality threshold",
            "only when an unresolved answer could plausibly change",
            "whenever the agent notices an optional idea",
            "only when an unresolved answer could plausibly change",
        ),
        (
            "meaningful rework threshold",
            "meaningful rework or over-engineering",
            "any amount of work",
            "meaningful rework or over-engineering",
        ),
        (
            "concise default",
            "concise by\n  default",
            "comprehensive by\n  default",
            "concise by default",
        ),
        (
            "impact-proportional detail",
            "detail proportional to the impact",
            "same exhaustive detail for every choice",
            "detail proportional to the impact",
        ),
        (
            "decision-factor boundary",
            "only to the extent they\n  affect the choice",
            "whether or not they affect the choice",
            "only to the extent they affect the choice",
        ),
        (
            "reviewed-tool false-positive boundary",
            "does not trigger an expansion\n  interview",
            "always triggers an expansion\n  interview",
            "does not trigger an expansion interview",
        ),
    )
    for name, old, new, expected in missing_proportional_question_terms:
        candidate = replace_last(policy, old, new)
        result = messages(candidate)
        check(
            "engineering-expansion question contract" in result and expected in result,
            f"missing {name} fixture did not identify {expected!r}: {result}",
        )

    # Length itself is not a failure. This protects the earlier decision against
    # arbitrary word limits while semantic checks keep the policy focused.
    long_but_semantically_same = policy + "\n" + ("Neutral explanatory context. " * 2000)
    check(
        not MODULE.find_policy_violations(long_but_semantically_same),
        "policy checker must not impose a numeric size ceiling",
    )

    explicit_safeguards = policy + (
        "\nNever stop deployment at the first failure. Do not request unbounded tool output. "
        "Never collapse provider-native counters. Delegated agents may not skip issue ledgers. "
        "Never estimate unknown counters. A collection must not show a form first. "
        "Never implement security, privacy, backup, migration, preservation, or data-safety "
        "expansions without asking the user. Silent scope expansion is never permitted.\n"
    )
    check(
        not MODULE.find_policy_violations(explicit_safeguards),
        "explicit negative safeguards must not be treated as contradictory instructions",
    )

    truthful_prototype = policy + (
        "\nA mock-data prototype may use a synthetic catalog while every enabled filter, "
        "form, cancellation path, and validation error works within the declared prototype "
        "boundary. It is reported as a prototype, not as production integration.\n"
    )
    check(
        not MODULE.find_policy_violations(truthful_prototype),
        "truthful synthetic prototype interactions must remain valid",
    )

    specified_future_control = policy + (
        "\nThe specification asks the interface to communicate a future export action. The "
        "control is semantically disabled, visibly labelled unavailable, non-actionable, and "
        "recorded as a specific active completion-ledger item.\n"
    )
    check(
        not MODULE.find_policy_violations(specified_future_control),
        "an explicitly specified disabled future control must remain valid",
    )

    negative_interaction_safeguards = policy + (
        "\nScreenshots fail to prove interaction verification, and a handler is insufficient "
        "to prove working behavior. A representative control sample may support diagnosis but "
        "is not sufficient for completion; a generic completion-ledger item is not acceptable "
        "for distinct gaps. Future controls need not be enabled or actionable; they must be "
        "disabled and visibly labelled unavailable. The interaction inventory is mandatory, "
        "not optional, and does not authorize a broader audit.\n"
    )
    check(
        not MODULE.find_policy_violations(negative_interaction_safeguards),
        "negative UI safeguards must not trigger positive-weakening detectors",
    )

    credible_in_scope_backup = policy + (
        "\nA backup required by an agreed destructive persistent-data operation is a credible "
        "project need, not an unrequested expansion. Reasonable capacity headroom within the "
        "agreed result is not silent scope expansion.\n"
    )
    check(
        not MODULE.find_policy_violations(credible_in_scope_backup),
        "credible in-scope safety work and reasonable headroom must remain valid",
    )

    non_security_change = policy + (
        "\nA copy-only UI change does not add, change, weaken, remove, or intentionally "
        "omit a security-posture control, so it requires no security interview.\n"
    )
    check(
        not MODULE.find_policy_violations(non_security_change),
        "non-security work must not trigger the security-assumptions gate",
    )

    read_only_discovery = policy + (
        "\nRead-only discovery may inventory the current deployment and trust boundaries "
        "to identify material questions; it does not select or alter a control.\n"
    )
    check(
        not MODULE.find_policy_violations(read_only_discovery),
        "read-only discovery that does not choose a control must pass",
    )

    assumption_backed_control = policy + (
        "\n`security-assumptions.md` records the user's confirmed single-operator, "
        "owner-managed local runtime; low-sensitivity assets; no credible remote adversary; "
        "trusted process boundaries; owner-only file access as the necessary gate; network "
        "authentication as explicitly unnecessary; the accepted local-access risk; and "
        "internet exposure as a review trigger. The implemented owner-only permission "
        "control cites those entries and remains inside the requested scope.\n"
    )
    check(
        not MODULE.find_policy_violations(assumption_backed_control),
        "a project-specific, user-confirmed, cited, proportional security control must pass",
    )

    assumption_backed_expansion = policy + (
        "\nThe proposed network authentication control cites the user's confirmed assumptions, "
        "but it is outside the requested result. Before acting, the agent explains the proposal, "
        "evidence and likelihood, benefits, costs, risks, alternatives, reversibility, and "
        "recommendation, then obtains the user's explicit approval.\n"
    )
    check(
        not MODULE.find_policy_violations(assumption_backed_expansion),
        "confirmed assumptions must not replace expansion approval",
    )

    reviewed_non_rotating_repair = policy + (
        "\nA reviewed non-rotating recorder repair preserves the named homes, endpoint "
        "boundary, credential, controls, and documented posture. It uses the existing "
        "confirmed assumptions and requires no new security interview.\n"
    )
    check(
        not MODULE.find_policy_violations(reviewed_non_rotating_repair),
        "posture-preserving reviewed tool execution must pass without an interview",
    )

    one_material_question = policy + (
        "\nThe sole unresolved material assumption is whether another OS account uses the "
        "runtime. Ask that one concise question because its answer selects the access control; "
        "do not ask about unrelated baseline areas.\n"
    )
    check(
        not MODULE.find_policy_violations(one_material_question),
        "one concise decision-material security question must pass",
    )

    justified_full_baseline = policy + (
        "\nA new remotely operated multi-user service has no assumptions record, and the "
        "pending architecture and control set materially depend on every baseline area. Ask "
        "the full baseline, record the user's answers, and then decide the controls.\n"
    )
    check(
        not MODULE.find_policy_violations(justified_full_baseline),
        "a full baseline must pass when every area is material to the concrete decision",
    )

    explicit_security_safeguards = policy + (
        "\nIf security-assumptions.md is missing, stop before implementation and ask the "
        "user. Agents must not infer a threat model. Never automatically apply maximum "
        "hardening controls.\n"
    )
    check(
        not MODULE.find_policy_violations(explicit_security_safeguards),
        "explicit security safeguards must not be mistaken for prohibited instructions",
    )

    with tempfile.TemporaryDirectory(prefix="app-wide-importer-") as raw:
        importer = Path(raw) / "CLAUDE.md"
        importer.write_text(
            "# Project memory\n\nConfirm the user-level memory loaded the canonical file. "
            "Otherwise read `reference/codex-app-wide/AGENTS.md` directly and report the "
            "installation or activation gap.\n\n@AGENTS.md\n",
            encoding="utf-8",
        )
        check(not MODULE.audit_claude_importer(importer), "single project import must pass")
        importer.write_text(
            "@reference/codex-app-wide/AGENTS.md\n@AGENTS.md\n",
            encoding="utf-8",
        )
        check(
            "must not re-import" in "\n".join(MODULE.audit_claude_importer(importer)),
            "duplicate universal-policy import must fail",
        )
        importer.write_text(
            "Confirm the user-level memory loaded the canonical file. Otherwise read "
            "`reference/codex-app-wide/AGENTS.md` directly and report the installation or "
            "activation gap.\n@AGENTS.md\n@AGENTS.md\n",
            encoding="utf-8",
        )
        check(
            "exactly once" in "\n".join(MODULE.audit_claude_importer(importer)),
            "duplicate repository-policy import must fail",
        )
        importer.write_text("@AGENTS.md\n", encoding="utf-8")
        check(
            "session fallback" in "\n".join(MODULE.audit_claude_importer(importer)),
            "missing global-policy fallback must fail",
        )

    print("app-wide policy checker self-test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
