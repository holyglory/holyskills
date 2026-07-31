#!/usr/bin/env python3
"""Validate the outcome-bearing contracts of the universal agent policy."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "reference" / "codex-app-wide" / "AGENTS.md"
DEFAULT_CLAUDE_IMPORTER = ROOT / "CLAUDE.md"

REQUIRED_SECTIONS = (
    "Use relevant authoritative context",
    "Ground security-posture decisions in confirmed assumptions",
    "Keep decisions compact and usable",
    "Deliver the complete agreed scope",
    "Finish diagnostic cycles before batch fixing",
    "Keep behavior truthful",
    "Learn from agent-made mistakes",
    "Verify real behavior",
    "Measure delivery efficiency truthfully",
    "Put requested interface content first",
    "Respect data and system boundaries",
    "Protect sources, repositories, and running systems",
    "Report status honestly",
)

# A universal policy must not depend on one runtime, product, framework, or
# repository. Runtime adapters and project policy own those names.
FORBIDDEN_NAMES = (
    "Codex",
    "Claude",
    "ImageGen",
    "Next.js",
    "Vercel",
    "Swift",
    "macOS",
    "Docker",
    "PostgreSQL",
    "systemd",
    "formal-web-ui-verification",
    "codex-dev-coordinator",
    "postgres-docker-backup",
)


def section(text: str, heading: str) -> str:
    match = re.search(
        rf"^## {re.escape(heading)}\s*$\n(?P<body>.*?)(?=^## |\Z)",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    return match.group("body") if match else ""


def _fold(text: str) -> str:
    return " ".join(text.casefold().split())


def _require_terms(
    violations: list[str], body: str, label: str, terms: tuple[str, ...]
) -> None:
    folded = _fold(body)
    missing = [term for term in terms if term.casefold() not in folded]
    if missing:
        violations.append(f"{label} missing required concepts: {', '.join(missing)}")


def _require_pattern(
    violations: list[str], body: str, label: str, pattern: str
) -> None:
    if not re.search(pattern, body, flags=re.IGNORECASE | re.DOTALL):
        violations.append(label)


def _bullet_starting_with(body: str, opening: str) -> str:
    match = re.search(
        rf"^-\s+{opening}.*?(?=^-\s+|\Z)",
        body,
        flags=re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    return match.group(0) if match else ""


def find_policy_violations(text: str) -> list[str]:
    violations: list[str] = []

    if not text.startswith("# Universal Agent Instructions\n"):
        violations.append("policy must use the universal title")

    bodies = {heading: section(text, heading) for heading in REQUIRED_SECTIONS}
    for heading, body in bodies.items():
        if not body:
            violations.append(f"required section is missing: {heading}")

    context = bodies["Use relevant authoritative context"]
    if context:
        _require_terms(
            violations,
            context,
            "relevant-context contract",
            (
                "unchanged rule",
                "live context",
                "task matches",
                "targeted",
                "smallest useful result",
                "cold artifact",
                "raw logs",
                "realistic materially distinct options",
                "plain language",
                "recommend",
                "third-party",
                "exact name",
                "authoritative sources",
                "facts",
                "inferences",
                "unknowns",
                "production-grade",
                "industry-standard",
                "under-engineering the agreed result is unacceptable",
                "implementation gaps",
                "more serious",
                "more punishable",
                "reasonable over-engineering",
                "silent scope expansion",
                "every potential over-engineering expansion",
                "requested result",
                "credible project need",
                "ask the user",
                "explicit approval",
                "highly informative question",
                "disposable test data",
                "single-user environment",
            ),
        )
        _require_pattern(
            violations,
            context,
            "under-engineering must be unacceptable and more punishable than reasonable over-engineering",
            r"under-engineering\s+the\s+agreed\s+result\s+is\s+unacceptable"
            r".{0,120}implementation\s+gaps?\s+are\s+more\s+serious\s+and\s+more"
            r"\s+punishable\s+than\s+reasonable\s+over-engineering",
        )
        _require_pattern(
            violations,
            context,
            "the engineering asymmetry must explicitly prohibit silent scope expansion",
            r"(?:never|must\s+not|do\s+not).{0,40}authorize.{0,40}silent\s+scope\s+expansion",
        )
        expansion_question = _bullet_starting_with(context, r"Before\s+acting\s+on\s+every")
        if not expansion_question:
            violations.append(
                "every potential engineering expansion must trigger an informative user question before action"
            )
        else:
            _require_terms(
                violations,
                expansion_question,
                "engineering-expansion question contract",
                (
                    "potential over-engineering expansion",
                    "requested result",
                    "credible project need",
                    "security",
                    "privacy",
                    "backup",
                    "migration",
                    "preservation",
                    "data-safety",
                    "ask the user",
                    "explicit approval",
                    "highly informative question",
                    "concrete proposal",
                    "evidence",
                    "scenario",
                    "assessed likelihood",
                    "expected benefit",
                    "cost",
                    "complexity",
                    "ongoing maintenance",
                    "risks of doing it and not doing it",
                    "realistic alternatives",
                    "reversibility",
                    "clear recommendation",
                    "do not begin the expansion until the user approves it",
                ),
            )
            _require_pattern(
                violations,
                expansion_question,
                "expansion approval must precede action",
                r"before\s+acting.{0,500}ask\s+the\s+user.{0,120}explicit\s+approval"
                r".{0,900}do\s+not\s+begin\s+the\s+expansion\s+until\s+the\s+user\s+approves",
            )

    security = bodies["Ground security-posture decisions in confirmed assumptions"]
    if security:
        _require_terms(
            violations,
            security,
            "security-assumptions gate",
            (
                "every decision that adds, changes, weakens, removes, or intentionally omits",
                "security-posture control",
                "before proposing or making such a decision",
                "project-root `security-assumptions.md`",
                "non-security changes do not trigger a security interview",
                "read-only discovery",
                "identify material assumptions or questions",
                "does not select, apply, alter, or omit",
                "project-specific",
                "user-confirmed assumptions",
                "every security-posture decision and resulting implemented security measure",
                "cite",
                "templates, defaults, and agent guesses are not confirmed project facts",
                "users and operators",
                "deployment or runtime environment and ownership",
                "assets and data sensitivity",
                "credible adversaries and misuse",
                "trust boundaries",
                "necessary gates",
                "explicitly unnecessary gates",
                "acceptable risks",
                "review triggers",
                "is absent",
                "stop before the security-posture decision or implementation",
                "elaborate, plain-language baseline question",
                "covering every assumption area",
                "create the file",
                "confirmed answers",
                "exists but is insufficient for the current decision",
                "ask only about unresolved assumptions material to that decision",
                "update the file",
                "do not repeat already resolved areas",
                "before resuming security work",
                "never invent or infer a project assumption",
                "unconfirmed template",
                "record unknowns explicitly",
                "unconfirmed assumption cannot justify",
                "never default to blanket hardening",
                "cumulative",
                "every potential expansion",
                "requested result",
                "credible project need",
                "explicit approval before action",
                "never satisfies or waives the other",
            ),
        )
        _require_pattern(
            violations,
            security,
            "every security-posture change or omission must read confirmed assumptions first",
            r"every\s+decision\s+that\s+adds,\s+changes,\s+weakens,\s+removes,\s+or"
            r"\s+intentionally\s+omits.{0,100}before\s+proposing\s+or\s+making"
            r".{0,100}read\s+the\s+project-root\s+`security-assumptions\.md`",
        )
        _require_pattern(
            violations,
            security,
            "every security-posture decision and implementation must cite confirmed assumptions",
            r"every\s+security-posture\s+decision\s+and\s+resulting\s+implemented\s+security"
            r"\s+measure\s+must\s+cite.{0,120}user-confirmed\s+assumptions",
        )
        _require_pattern(
            violations,
            security,
            "an absent assumptions file must trigger the complete baseline question",
            r"is\s+absent.{0,160}stop\s+before.{0,180}baseline\s+question"
            r".{0,120}every\s+assumption\s+area.{0,160}create\s+the\s+file"
            r".{0,100}confirmed\s+answers",
        )
        _require_pattern(
            violations,
            security,
            "an insufficient assumptions file must trigger only material unresolved questions",
            r"exists\s+but\s+is\s+insufficient.{0,160}ask\s+only\s+about\s+unresolved"
            r"\s+assumptions\s+material.{0,180}update\s+the\s+file.{0,180}do\s+not"
            r"\s+repeat\s+already\s+resolved\s+areas",
        )
        _require_pattern(
            violations,
            security,
            "unknown security assumptions must be explicit and cannot justify posture decisions",
            r"record\s+unknowns\s+explicitly.{0,100}(?:unknown|unconfirmed\s+assumption)"
            r".{0,80}cannot\s+justify\s+adding,\s+changing,\s+weakening,\s+removing,"
            r"\s+or\s+intentionally\s+omitting",
        )
        _require_pattern(
            violations,
            security,
            "the security-assumptions gate and expansion approval must remain cumulative",
            r"assumption\s+gate\s+and\s+the\s+informed-approval\s+rule.{0,180}cumulative"
            r".{0,260}explicit\s+approval\s+before\s+action.{0,160}never\s+satisfies\s+or"
            r"\s+waives\s+the\s+other",
        )

    decisions = bodies["Keep decisions compact and usable"]
    if decisions:
        _require_terms(
            violations,
            decisions,
            "decision-memory contract",
            (
                "project-root `DecisionHistory.md`",
                "dense",
                "concise",
                "not a report",
                "DecisionDetails/<decision-id>.md",
                "exactly one",
                "only `Decision` and `Why`",
                "routine context",
                "Direction",
                "confirmed user intent",
                "inferred patterns",
                "decision IDs",
                "ambiguous choice",
                "rejected or failed option",
                "new evidence",
                "superseding decision",
            ),
        )

    delivery = bodies["Deliver the complete agreed scope"]
    if delivery:
        _require_terms(
            violations,
            delivery,
            "complete-delivery contract",
            (
                "full agreed scope",
                "only an explicit user decision",
                "project-root `CompletionLedger.md`",
                "only active unresolved",
                "partial implementations",
                "same change",
                "implemented and verified",
                "never retain",
                "delete the file",
                "no active items remain",
                "CompletionHistory.md",
                "explicit audit retention",
                "before readiness",
                "end-to-end",
                "unblock condition",
            ),
        )

    cycle = bodies["Finish diagnostic cycles before batch fixing"]
    if cycle:
        _require_terms(
            violations,
            cycle,
            "complete-cycle contract",
            (
                "continue to the end",
                "non-critical failures",
                "CompletionLedger.md",
                "cold artifact",
                "do not fix one small gap and restart",
                "security or safety harm",
                "data loss",
                "shared-state corruption",
                "destruction of useful evidence",
                "group findings by cause",
                "fix the batch",
                "rerun the complete relevant cycle",
                "test server",
                "already included in the agreed task",
                "deploy it",
                "tell the user what remains",
                "incomplete test deployment",
            ),
        )
        _require_pattern(
            violations,
            cycle,
            "non-critical findings must be collected before the batch fix",
            r"continue\s+to\s+the\s+end.{0,900}after\s+the\s+complete\s+evidence\s+pass"
            r".{0,300}fix\s+the\s+batch",
        )

    truthful = bodies["Keep behavior truthful"]
    if truthful:
        _require_terms(
            violations,
            truthful,
            "truthful-behavior contract",
            (
                "never present invented",
                "control must perform",
                "end to end",
                "unavailable data",
                "mockups",
                "production behavior",
            ),
        )

    mistakes = bodies["Learn from agent-made mistakes"]
    if mistakes:
        _require_terms(
            violations,
            mistakes,
            "agent-mistake contract",
            (
                "changed user intent",
                "finish its useful diagnostic cycle",
                "before the product fix",
                "batch",
                "retest",
                "guardrail",
                "project-root `UserIssueLedgers/`",
                "concise routine context",
                "confirmed user-indicated agent mistakes",
                "durable user corrections",
                "absence is valid",
                "multiple narrowly scoped ledgers",
                "mixed catch-all",
                "BusinessLogic/<Perspective>.md",
                "# User Issue Ledger: <scope>",
                "`ID`",
                "`Applies to`",
                "`Mistake pattern`",
                "`Required behavior`",
                "`Prevention and verification`",
                "UIL-<SCOPE>-NNN",
                "relative file path owns the scope",
                "same path components",
                "ID namespace derives from all of them",
                "Never mix another path's namespace",
                "narrowest owning ledger",
                "before planning or implementing",
                "repository-wide or cross-cutting work",
                "negative acceptance criterion",
                "delegated-agent tasks",
                "one row per distinct pattern",
                "merging duplicates",
                "reuse its ID",
                "persist after the immediate fix",
                "explicit user retraction",
                "version control",
                "raw conversation",
            ),
        )
        for route in ("UI work always reads UI", "code changes read coding-style", "automation reads automation"):
            if route.casefold() not in _fold(mistakes):
                violations.append(f"mandatory issue-ledger routing is missing: {route}")

    verify = bodies["Verify real behavior"]
    if verify:
        _require_terms(
            violations,
            verify,
            "verification contract",
            (
                "same visible or operational surface",
                "acceptance criteria",
                "end to end",
                "recall",
                "precision",
                "must-catch failures",
                "false-positive guards",
                "never delete shared records",
            ),
        )

    efficiency = bodies["Measure delivery efficiency truthfully"]
    if efficiency:
        _require_terms(
            violations,
            efficiency,
            "delivery-efficiency contract",
            (
                "observational",
                "never omit work",
                "approved configured recorder",
                "exact stable launcher",
                "without authority",
                "request receipt",
                "first activity",
                "authoritative provider counters",
                "monotonic time",
                "EfficiencyLedger.jsonl",
                "outside source worktrees",
                "never reconstruct or estimate",
                "complete instrumentation proves zero",
                "complete, incomplete, blocked, cancelled, superseded, or interrupted",
                "append linked continuations",
                "without double counting",
                "kind separately from cause",
                "phase",
                "activity state",
                "measurement provenance",
                "attribution provenance",
                "runtime-observed",
                "agent-declared",
                "inferred",
                "unknown",
                "request-to-delivery wall time",
                "execution wall time",
                "summed per-agent active time",
                "deduplicate overlaps",
                "provider-native input, output, cached, reasoning",
                "never collapse",
                "Planning covers requirements",
                "research",
                "diagnosis",
                "Implementation covers changes to code",
                "configuration",
                "documentation",
                "test artifacts",
                "test authoring",
                "Testing covers executing and reviewing verification",
                "Deployment covers release or environment mutation",
                "reporting covers the user-facing handoff",
                "ambiguous mixed work is unattributed",
                "agreed scope",
                "requirement coverage",
                "cannot be complete",
                "prompts",
                "tool payloads",
                "secrets",
                "personal data",
            ),
        )

    interface = bodies["Put requested interface content first"]
    if interface:
        _require_terms(
            violations,
            interface,
            "interface-content contract",
            (
                "content promise",
                "first substantial",
                "first viewport",
                "collection destination",
                "must not lead",
                "add or edit form",
                "immediately reveal",
                "current viewport",
                "below a long list",
                "success returns",
                "new item",
                "narrow constraints",
                "loading, empty, error, populated, and long-content states",
                "functional defect",
                "visual exploration only for new directions or redesigns",
            ),
        )

    boundaries = bodies["Respect data and system boundaries"]
    if boundaries:
        _require_terms(
            violations,
            boundaries,
            "data-boundary contract",
            ("domain meaning", "ownership", "lifecycle", "does not imply shared ownership"),
        )

    protection = bodies["Protect sources, repositories, and running systems"]
    if protection:
        _require_terms(
            violations,
            protection,
            "source-and-system protection contract",
            (
                "canonical sources",
                "current remote",
                "Remote-unavailable means unknown",
                "valuable dirty work",
                "shared resource",
                "data loss",
                "recoverable backup",
                "disposable and isolated",
                "unambiguous mutation targets",
            ),
        )

    reporting = bodies["Report status honestly"]
    if reporting:
        _require_terms(
            violations,
            reporting,
            "honest-status contract",
            ("outcomes and evidence", "facts", "inferences", "assumptions", "never ready"),
        )

    for name in FORBIDDEN_NAMES:
        if re.search(rf"\b{re.escape(name)}\b", text):
            violations.append(f"universal policy must not name runtime/project-specific term: {name}")

    positive_authorization = re.search(
        r"(?i)(?:authenticated|signed[ -]?in|telemetry|recorder).{0,80}"
        r"(?:agent\s+is\s+authorized|authorizes\s+(?:the\s+)?agent|grants\s+(?:the\s+)?agent\s+permission)",
        text,
    )
    if positive_authorization:
        violations.append("operational runtime state must not grant agent authority")

    contradictory_instructions = (
        (r"(?i)\balways\s+reread\b|\bload\s+every\s+(?:skill|tool)\b", "context must remain relevant and non-redundant"),
        (r"(?i)(?<!never )(?<!do not )(?<!must not )\bstop\s+(?:the\s+)?(?:test|suite|debug|audit|rehearsal|deployment|cycle|pass)\s+at\s+(?:the\s+)?first\b", "diagnostic cycles must not stop at the first ordinary failure"),
        (r"(?i)(?<!never )(?<!do not )(?<!must not )\bfix\s+each\s+(?:error|failure|gap).{0,100}\brestart\b", "diagnostic findings must be batch-fixed after the evidence pass"),
        (r"(?i)(?<!never )(?<!do not )(?<!must not )\bimplement\s+(?:unrequested|hypothetical).{0,100}\bwithout\s+(?:asking|approval)\b", "unrequested engineering must never proceed without informed approval"),
        (r"(?i)\b(?:under-engineering|implementation\s+gaps?)\s+(?:is|are)\s+(?:acceptable|less\s+serious|less\s+punishable)\b", "under-engineering and implementation gaps must remain the more serious failure"),
        (r"(?i)\breasonable\s+over-engineering\s+is\s+(?:more\s+serious|more\s+punishable)\s+than\s+(?:under-engineering|implementation\s+gaps?)\b", "under-engineering asymmetry must not be inverted"),
        (r"(?i)\bsilent\s+scope\s+expansion\s+is\s+(?:acceptable|allowed|authorized|permitted)\b", "silent scope expansion must remain prohibited"),
        (r"(?i)(?<!never )(?<!do not )(?<!must not )\b(?:implement|perform|begin|proceed\s+with|automatically\s+add).{0,100}(?:security|privacy|backup|migration|preservation|data[- ]safety|hardening|infrastructure).{0,120}\bwithout\s+(?:asking|approval)\b", "risk-control expansion must not proceed without user approval"),
        (r"(?i)\b(?:automatically|always)\s+(?:add|implement|perform|create|preserve|migrate|back\s*up|harden).{0,160}(?:even\s+(?:if|when).{0,80}(?:unrequested|not\s+(?:requested|required|needed))|without\s+(?:evidence|a\s+credible\s+(?:project\s+)?need))", "hypothetical engineering must not expand scope automatically"),
        (r"(?i)(?<!never )(?<!do not )(?<!must not )\b(?:if|when)\s+`?security-assumptions\.md`?\s+is\s+(?:absent|missing|unavailable|incomplete|insufficient).{0,180}\b(?:implement|apply|begin|continue|proceed\s+with)\b.{0,180}\b(?:before\s+(?:asking|confirmation)|document|record|update).{0,80}\b(?:later|afterward|after\s+implementation)\b", "missing security assumptions must stop implementation before controls are applied"),
        (r"(?i)\b(?:agent|agents|we|you)\s+(?:may|can|should|must|will)\s+(?:infer|assume|presume)\b.{0,140}\b(?:security\s+assumptions?|threat\s+model|credible\s+adversar(?:y|ies)|misuse|trust\s+boundaries?|maximum\s+threat|multi[- ]tenant|internet[- ]facing)\b", "security assumptions and threats must be user-confirmed, not inferred"),
        (r"(?im)(?:^|(?<=[.!?]))\s*(?:-\s*)?(?:weaken|remove|disable|omit|intentionally\s+omit)\b.{0,120}\b(?:security(?:-posture)?\s+(?:control|gate|measure)|authentication\s+control|authorization\s+control|access-control\s+gate)\b.{0,120}\bwithout\s+(?:reading|citing|confirmed|user-confirmed)\b", "weakened, removed, or omitted controls require confirmed security assumptions"),
        (r"(?i)\b(?:populate|create|fill|update)\b.{0,100}`?security-assumptions\.md`?.{0,120}\b(?:template|defaults?)\b.{0,120}\b(?:treat|mark|regard|count)\b.{0,60}\b(?:as\s+)?confirmed\b", "security-assumption templates and defaults are unconfirmed until the user confirms them"),
        (r"(?im)(?:^|(?<=[.!?]))\s*(?:-\s*)?(?:always|automatically|by\s+default|regardless\s+of\s+(?:context|assumptions))\b.{0,100}\b(?:apply|implement|enable|require|add|use)\b.{0,100}\b(?:maximum|blanket|all|every)\b.{0,60}\b(?:hardening|security\s+controls?|security\s+gates?|security\s+measures?)\b", "blanket security controls must not replace assumption-backed proportional controls"),
        (r"(?i)\balways\s+(?:preserve|migrate|back\s*up)\s+disposable\s+test\s+data\b", "disposable test data must not trigger automatic preservation work"),
        (r"(?i)(?<!never )(?<!do not )(?<!must not )\brequest\s+(?:unbounded|unlimited)\s+(?:tool\s+)?output\b", "model-facing tool output must remain bounded"),
        (r"(?i)(?<!never )(?<!do not )(?<!must not )\bcollapse\s+provider-native\s+(?:token\s+)?counters\b", "provider-native token categories must remain distinct"),
        (r"(?i)(?<!never )(?<!do not )(?<!must not )\btreat\s+(?:research|diagnosis|test execution)\s+as\s+implementation\b", "operational phase boundaries must remain stable"),
        (r"(?i)\bdelegated\s+agents?\s+may\s+(?:skip|ignore)\s+(?:the\s+)?(?:issue\s+)?ledgers?\b", "delegated work must receive relevant issue-ledger constraints"),
        (r"(?i)(?<!never )(?<!do not )(?<!must not )\bestimate\s+(?:missing|unknown).{0,60}\b(?:token|counter|time)", "missing telemetry must not be estimated"),
        (r"(?i)(?<!never )(?<!do not )(?<!must not )\bstore\s+(?:prompts|tool payloads).{0,80}`?EfficiencyLedger", "telemetry must not retain private model content"),
        (r"(?i)(?<!never )(?<!do not )(?<!must not )\bretain\s+(?:resolved|completed|closed).{0,80}`?CompletionLedger", "the completion ledger must remain active-only"),
        (r"(?i)\bcollection(?!.{0,80}\b(?:must not|never|do not)\b).{0,100}\bform\s+first\b", "collection destinations must not lead with forms"),
    )
    for pattern, label in contradictory_instructions:
        if re.search(pattern, text, flags=re.DOTALL):
            violations.append(label)

    return violations


def audit_policy(path: Path) -> list[str]:
    try:
        return find_policy_violations(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return [f"could not read policy: {exc}"]


def audit_claude_importer(path: Path) -> list[str]:
    """Keep project memory from importing the global policy a second time."""

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"could not read Claude project importer: {exc}"]
    import_lines = [line.strip() for line in text.splitlines() if line.lstrip().startswith("@")]
    violations: list[str] = []
    if import_lines.count("@AGENTS.md") != 1:
        violations.append("Claude project memory must import root AGENTS.md exactly once")
    if any("codex-app-wide/AGENTS.md" in line for line in import_lines):
        violations.append("Claude project memory must not re-import the user-level universal policy")
    if "# Universal Agent Instructions" in text or "# Repo Agent Instructions" in text:
        violations.append("Claude project memory must not copy either authoritative policy")
    folded = _fold(text)
    if (
        "confirm the user-level memory loaded" not in folded
        or "read `reference/codex-app-wide/agents.md` directly" not in folded
        or "installation or activation gap" not in folded
    ):
        violations.append("Claude project memory must provide a session fallback for missing global policy")
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    args = parser.parse_args()

    violations = audit_policy(args.policy)
    try:
        is_canonical = args.policy.resolve() == DEFAULT_POLICY.resolve()
    except OSError:
        is_canonical = False
    if is_canonical:
        violations.extend(audit_claude_importer(DEFAULT_CLAUDE_IMPORTER))
    if violations:
        for violation in violations:
            print(f"policy violation: {violation}")
        return 1
    print(f"app-wide policy check ok ({args.policy})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
