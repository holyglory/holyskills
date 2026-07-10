---
name: trace-fix-root-causes
description: Investigate user-reported Codex or Claude Code implementation mistakes, factual or reasoning errors, incorrect tool use, broken artifacts, local-service incidents, audit misses, regressions, and incomplete verification. Reproduce the original surface, distinguish changed requirements and external changes from agent-created gaps, trace creation and missed detection with structured evidence, update the nearest durable guardrail first when authorized, close the implementation gap only when authorized, and run comprehensive post-fix verification.
---

# Trace Fix Root Causes

## Purpose

Use this skill when a user reports or asks to explain an error likely caused or
missed by Codex or Claude Code. This includes implementation defects, UI flaws,
missed requirements, factual mistakes, reasoning mistakes, unsafe assumptions,
incorrect citations, inappropriate or incorrect tool use, broken generated
artifacts, incomplete verification, audit misses, regressions, and quality
problems.

Also use it for a user-visible local service failure after an agent touched,
started, restarted, inspected, or verified that service. Treat `unhealthy`,
`pid_alive=false`, connection refused, crashes, timeouts, "not responding",
stale coordinator metadata, and browser-visible local failures as
agent-handled incidents until evidence proves otherwise.

The goal is not blame or a speculative postmortem. The goal is to reproduce or
otherwise confirm the symptom, distinguish an agent-created gap from changed
requirements or external state, trace how it was created and missed, repair the
nearest durable prevention layer when authorized, close the user-facing gap
when authorized, and prove the expected result through the original path and
broader tests.

## Authorization And Action Mode

Choose and state one mode before any mutation:

- `diagnose-only`: use when the user asks to explain, investigate, audit,
  review, or report. Read-only reproduction and diagnostics are allowed. Do
  not edit product code, policy, skills, tests, external state, or services.
  Record proposed prevention and implementation work, and state that closure
  was not authorized.
- `authorized-fix`: use only when the user explicitly asks to fix, change,
  implement, repair, or apply prevention. Make only in-scope changes. A bug
  report by itself is not authorization for mutations.

If a service must be restored urgently, capture crash evidence before restart.
Urgency does not broaden authorization or permit unrelated changes.

Also select one exact incident class: `implementation`, `ui`, `factual`,
`reasoning`, `tool-use`, `artifact`, `service`, `audit`, `verification`, or
`other`. Use the primary reported failure, not words that merely occur in a
boundary or ruled-out explanation. This prevents phrases such as "not a
service crash" from activating an unrelated evidence contract.

## Evidence Contract

Do not use an unstructured paragraph as the evidence ledger. In `Evidence
Used`, record one or more entries using this exact field structure:

```markdown
- E1 | kind: log | source: coordinator events.jsonl | observation: process exited with code 1 | status: confirmed
```

Allowed evidence statuses are `confirmed`, `source-inferred`, and
`unconfirmed`. Status describes what that evidence proves; it does not promote
an inferred cause to a confirmed cause. Give every entry a stable unique ID.
Valid kinds include `user-report`, `screenshot`, `log`, `test`, `verifier`,
`diff`, `commit`, `file`, `source`, `source-citation`, `tool-trace`, `command`,
`artifact`, and `audit`.

In `Causal Chain`, use evidence-linked entries:

```markdown
- C1 | link: origin | evidence: E1 | status: confirmed | finding: the requested behavior was explicit
- C2 | link: immediate-defect | evidence: E2 | status: confirmed | finding: the implementation omitted the persisted field
- C3 | link: missed-detection | evidence: E3 | status: source-inferred | finding: the test asserted success but not persisted state
```

Every report must include `origin`, `immediate-defect`, and
`missed-detection`. Evidence references must resolve to the evidence ledger.
Use `evidence: none` only with `status: unconfirmed`. Never invent a causal
link to fill the structure.

## Workflow

1. **Select mode and preserve the original state**
   - State `diagnose-only` or `authorized-fix`.
   - Preserve logs, artifacts, current diffs, service state, and other volatile
     evidence before commands or changes can overwrite it.
   - Respect existing user changes and unrelated dirty-worktree state.

2. **Reproduce the reported failure**
   - Record what failed, who noticed it, and the same surface the user saw:
     browser route, app screen, CLI command, test, prompt/answer, citation,
     tool call, generated artifact, audit output, or integration path.
   - Replicate with the same input, environment, tool path, and observable
     result whenever possible and reasonable.
   - If reproduction is impossible or unsafe, state why and capture the
     closest concrete substitute: user report, screenshot, log, source
     citation, tool trace, diff, test output, or before/after artifact.
   - If evidence is missing, mark affected evidence and causal links
     `unconfirmed`; do not invent root causes.

3. **Check user intent, requirement history, and external state**
   - Compare the original request, later clarification, accepted plan, project
     and journey documentation, delivered behavior, and relevant external
     changes.
   - If the user changed the requirement after delivery, classify it as a
     scope change rather than an agent mistake.
   - If facts changed after the answer or an external dependency changed,
     distinguish that from a factual or implementation error at delivery time.
   - Otherwise identify what the agent misread, over-assumed, omitted, or
     incorrectly prioritized.

4. **Collect incident-specific evidence**
   - Factual or citation mistakes: preserve the exact claim, answer timestamp,
     cited source, relevant source passage or primary-source result, and any
     freshness requirement. Separate unsupported claims from facts that
     changed later.
   - Reasoning mistakes: preserve the input facts, intermediate assumption or
     decision, constraint that was missed, and a counterexample or executable
     check when one exists. Do not claim access to hidden reasoning; trace only
     the observable rationale, assumptions, source, and outputs.
   - Tool-use mistakes: preserve the requested operation, selected tool,
     arguments with secrets redacted, tool result or error, resulting external
     state, and the safer or required tool path. Do not expose tokens or other
     credentials in the report.
   - Broken artifacts: preserve the input, generator/render command, output
     file hash, render or parser output, and a screenshot or structural check
     appropriate to the artifact.
   - Local-service failures: before restarting or replacing anything, capture
     coordinator status and inventory, coordinator `log_path`, app stdout and
     stderr, recent process-exit events, PID and health fields, requested URL,
     wrapper command, toolchain output, generated cache/build state, and
     dependency state. Distinguish crash, slow response, wrong URL/port,
     dependency failure, stale metadata, and cache/toolchain failure.

5. **Trace creation and missed detection**
   - Inspect the nearest sources that could have created or missed the problem:
     requirements, user-intent interpretation, journey docs, mockups, source
     material, citations, audit reports, skill instructions, verifiers,
     implementation, tests, review notes, policies, context, tool choice,
     toolchains, coordinator/server wrappers, generated cache/build output,
     missed skill triggers, and handoff assumptions.
   - Treat the immediate defect and the missed detection as separate links.
   - Mark each causal link `confirmed`, `source-inferred`, or `unconfirmed` and
     reference its evidence IDs.

6. **Classify recurrence risk**
   - `generalizable`: likely across tasks, repositories, runtimes, or products.
   - `local-repeatable`: specific to this repository or workflow but likely to
     recur there.
   - `one-off`: local and unlikely to recur after a targeted correction.
   - `unconfirmed`: evidence is insufficient to choose.

7. **Fix the system guardrail first when authorized**
   - In `diagnose-only`, recommend the smallest suitable guardrail but do not
     mutate it.
   - In `authorized-fix`, update the nearest durable guardrail before the
     product correction when practical: tests, realistic fixtures, verifier,
     skill, requirements, acceptance criteria, docs, checklist, persistent
     context, or policy.
   - If a detector, test, verifier, or audit missed the issue, prove recall:
     add a realistic must-catch case shaped like the reported failure and
     false-positive guards for common intentional behavior. Rerun it against
     the original evidence.
   - Use policy only for generalized reusable rules. Put incident narratives
     and timelines in the report, `DecisionHistory.md`, or targeted fixtures.

8. **Resolve policy scope portably**
   - Repo `AGENTS.md` or `CLAUDE.md` is repository policy, never global policy.
   - For generalizable agent behavior, use the global policy path supplied by
     the active runtime or execution context. For Codex this is normally
     `CODEX_HOME/AGENTS.md`; for Claude Code it is normally
     `CLAUDE_CONFIG_DIR/CLAUDE.md`. Mirror a cross-runtime rule when it truly
     governs both runtimes.
   - Do not embed a username-specific absolute path and do not infer a host
     installation from `$HOME`; desktop runtimes can override it. If the
     runtime's global policy path is unavailable or ambiguous, report the
     needed scope and ask before mutating.
   - For `one-off` or `unconfirmed` causes, prefer a targeted test, fixture, or
     report/Decision History note instead of policy.

9. **Audit the testing procedure**
   - Identify exactly which checks ran before the user caught the mistake and
     what each actually asserted.
   - Find adjacent missed failure modes in journeys, edge cases, failure paths,
     source freshness, citations, tool output, permissions, persistence,
     generated artifacts, services, and user-visible acceptance criteria.
   - Add or propose broader coverage; do not stop at a single symptom fixture
     when the testing weakness is wider.

10. **Close the implementation gap when authorized**
    - In `authorized-fix`, correct the user-facing issue after the prevention
      layer, or state why the product correction had to come first.
    - In `diagnose-only`, make no implementation change and explicitly record
      that closure awaits authorization.
    - Do not broaden the fix beyond what the causal evidence supports.

11. **Retest the original path and guardrail**
    - Rerun the same route, command, screen, prompt, citation check, tool path,
      artifact render, audit, or integration surface.
    - Rerun the new or updated guardrail and its realistic recall fixture.
    - For crash-class service fixes, verify sustained health through
      coordinator state and the same URL/tool/browser surface that failed.

12. **Run comprehensive post-fix tests**
    - In `authorized-fix`, run the broader test matrix found during the testing
      audit after the gap is closed. Prove the expected user result, not merely
      internal implementation details.
    - If comprehensive testing is blocked, name the blocker, substitute
      evidence, and residual risk; do not claim complete verification.
    - In `diagnose-only`, list the tests required for closure and clearly mark
      them not run because mutation was not authorized.

## Output

Return these headings exactly:

```markdown
## Fixed Symptom
## Reproduction
## User Intent And Scope Check
## Authorization And Action Mode
## Incident Class
## Evidence Used
## Causal Chain
## Root Cause Classification
## System Fix First
## Testing Procedure Audit
## Implementation Gap Closure
## Retest Results
## Comprehensive Retest Results
## Boundaries And Non-Generalizable Notes
```

Use the structured evidence and causal-chain formats above. Under
`Authorization And Action Mode`, include exactly one mode. Under `Incident
Class`, include exactly one allowed class. Under `System Fix First`, state
whether proposed or applied and name the owning system or file.
Under `Testing Procedure Audit`, distinguish checks that ran from coverage that
was absent. Under both retest sections, distinguish completed tests from tests
required but not run in `diagnose-only` mode.

## Completion Rules

- Do not skip reproduction when it is possible and reasonable.
- Do not mutate in `diagnose-only` mode or infer authorization from a report.
- Do not invent root causes or promote inference to confirmed evidence.
- Do not treat changed requirements or later external changes as original
  agent defects.
- Do not restart a crash-class service before preserving root-cause evidence.
- Do not claim a factual correction without source-backed evidence, a tool fix
  without tool-result evidence, or an artifact fix without inspecting the
  generated artifact.
- Do not stop at the symptom when a repeatable creation or detection gap exists.
- Do not update policy with incident-specific narratives or use repo policy as
  a substitute for a runtime-global policy.
- Do not hardcode private runtime policy paths or infer them from `$HOME`.
- Do not claim a detector is repaired without realistic recall and
  false-positive tests for its advertised detection classes.
- Do not claim implementation closure or comprehensive post-fix verification
  in `diagnose-only` mode.
