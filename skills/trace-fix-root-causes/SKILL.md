---
name: trace-fix-root-causes
description: Investigate and fix Codex or Claude Code mistakes when the user requests a root-cause analysis or postmortem, the failure is serious, repeated, systemic, or disputed, or a skill, audit, verifier, detector, or prior claimed verification missed it. Treat a clear report of broken in-scope behavior as authorization for a safe bounded repair unless the user explicitly requests diagnosis only, and scale evidence, prevention, testing, and reporting to risk. Do not invoke for an ordinary isolated product bug with a clear local fix; handle that directly with reproduce, fix, focused regression coverage, and original-surface retesting.
---

# Trace and Fix Root Causes

## Purpose

Use this skill for requested or materially significant agent-error incidents.
For an ordinary isolated product bug with a clear bounded fix, follow the same
short reproduce, fix, focused-regression, and original-surface-retest pattern
directly without loading this skill.

When the skill applies, restore the behavior the user expected and prevent
credible recurrence without turning the work into a larger postmortem than the
evidence warrants. Reproduce the original surface, establish the immediate
cause, fix it when authorized, and verify the result with effort proportional
to impact and uncertainty.

Use the same workflow for implementation and UI defects, factual mistakes,
reasoning mistakes, incorrect tool use, broken artifacts, audit or verifier
misses, regressions, and user-visible local-service failures after an agent
touched the service.

## Authorization

Select an action mode internally before mutation:

- `authorized-fix` is the default for a concrete report that an in-scope
  product, service, configuration, or artifact is broken. A direct statement
  such as “the hamburger menu doesn't open” normally asks for repair. It
  authorizes safe, bounded product/configuration edits, focused regression
  coverage, and any ordinary local verification or coordinator-managed local
  restart needed to prove the fix. A clear in-scope bug report is authorization
  for that safe bounded work; do not require the user to repeat “fix it.”
- `diagnose-only` applies when the user explicitly asks only to explain,
  investigate, audit, review, or avoid changes. It also applies when the
  supplied text merely quotes or documents somebody else's bug report rather
  than reporting a problem in the active scope.

Ask before an action that is destructive or difficult to reverse, changes
production or an external system, contacts other people, requires a credential
or security choice, expands into another repository or unrelated subsystem, or
depends on a materially ambiguous target or expected behavior. Continue safe
read-only diagnosis while waiting when useful. A local bug report never
silently authorizes production deployment, data deletion, history rewriting,
or unrelated global-policy changes.

Do not expose the selected mode as ceremony. Mention it only when a read-only
boundary, blocker, or requested formal report makes it useful to the user.

## Choose Proportionate Depth

Use the routine path by default. Escalate to a formal incident only when at
least one of these is true:

- the user requests a root-cause report, postmortem, or evidence ledger;
- the incident involves security, privacy, data loss, production impact,
  destructive actions, or a crash-class service failure;
- the same failure is recurring or evidence indicates a systemic cross-project
  workflow problem;
- a detector, verifier, audit, monitor, or this skill itself failed to catch a
  failure it claimed to cover; or
- the cause or scope is materially disputed and a durable evidence record is
  needed.

Do not escalate merely because a similar failure is imaginable. An isolated,
well-understood bug does not require a repository-wide audit, global policy
edit, Decision History entry, fresh-agent evaluation, or broad test matrix.

## Routine Fix Workflow

1. **Preserve and reproduce**
   - Preserve valuable dirty work and volatile evidence that a command or
     restart could overwrite.
   - Reproduce through the same route, screen, command, artifact, tool path, or
     integration surface the user saw whenever reasonable.
   - If exact reproduction is unavailable, use the closest concrete evidence
     and say so without inventing a cause.

2. **Trace the immediate cause**
   - Check the implementation, configuration, logs, and the test or verifier
     that should have caught the symptom.
   - Check changed requirements or external state only when they are plausible.
   - Separate the defect from why existing verification missed it, but keep the
     analysis as short as the evidence permits.

3. **Fix the user-facing gap**
   - Make the smallest complete in-scope correction.
   - Add a focused regression check when practical.
   - Add or repair a broader guardrail only when evidence shows a repeatable
     creation or detection gap. Do it before or alongside the product fix when
     cheap and safe; do not delay restoration for speculative policy work.

4. **Verify proportionally**
   - Retest the original path exactly as the user experienced it.
   - Run focused tests for the affected behavior and adjacent failure paths
     that the identified cause can realistically affect.
   - Expand to package, repository, or cross-project checks only when change
     scope or concrete recurrence evidence justifies them.

5. **Hand off concisely**
   - Concise output is the default for routine fixes.
   - Lead with fixed, not fixed, or blocked.
   - State the cause, the change, and the verification in a few readable
     sentences or compact bullets.
   - Do not print internal action modes, incident classes, evidence IDs, causal
     IDs, or a testing-procedure audit in an ordinary bug-fix response.

## Formal Incident Workflow

For an escalated incident, perform the routine workflow plus the evidence work
that the incident actually needs:

- distinguish the user's original intent from a later requirement or external
  change;
- record confidence as `confirmed`, `source-inferred`, or `unconfirmed`;
- connect the request, immediate cause, and missed detection to concrete
  evidence without claiming hidden reasoning;
- classify one primary Incident Class: `implementation`, `ui`, `factual`,
  `reasoning`, `tool-use`, `artifact`, `service`, `audit`, `verification`, or
  `other`;
- for factual or reasoning incidents, preserve the disputed claim, timestamp,
  and supporting primary source;
- for incorrect tool use, preserve redacted arguments, result/error, and
  resulting state;
- for broken artifacts, preserve the input, output hash, render/parser result,
  and visual evidence when layout matters;
- for crash-class services (`unhealthy`, `pid_alive=false`, connection refused,
  crash, or timeout), capture coordinator status, `log_path`, recent exit
  events, PID/health state, requested URL, wrapper/toolchain output, generated
  cache/build state, and dependencies before restart; then prove sustained
  recovery through the same surface; and
- when a detector or audit missed the problem, prove recall with a realistic
  must-catch fixture for the advertised detection class plus false-positive
  guards for common intentional behavior.

Use the concise four-section format in
[`references/formal-report.md`](references/formal-report.md). Create that formal
artifact only for the escalation cases above. Validate it with
`python3 scripts/verify_root_cause_report.py REPORT.md`.

## Guardrail Scope

Use the narrowest durable owner: a focused test or verifier for a code path,
project documentation or repository policy for a local repeatable rule, and
global policy only for behavior that genuinely applies across tasks or
repositories. Keep incident narratives out of policy files.

Resolve global policy through the active runtime. Codex normally supplies
`CODEX_HOME/AGENTS.md`; Claude Code normally supplies
`CLAUDE_CONFIG_DIR/CLAUDE.md`. Do not hardcode a private username path or infer
the active desktop installation from `$HOME`.

## Completion Rules

- Do not skip a reasonable original-surface reproduction.
- Do not mutate when the user explicitly requested `diagnose-only`.
- Do not invent evidence or promote inference to confirmed fact.
- Do not restart a crash-class service before preserving available failure
  evidence.
- Do not claim completion without retesting the original symptom.
- Do not make a full incident report the default output for a routine fix.
