---
name: trace-fix-root-causes
description: Investigate Codex implementation mistakes, recently fixed bugs, UI flaws, audit misses, regressions, or user-reported quality problems to explain how the mistake was created, update the nearest workflow/documentation/verifier/test/skill/policy guardrail first when prevention is needed, audit testing procedures for other missed failures, close the implementation gap, and run comprehensive post-fix tests. Use when a user reports a Codex-made implementation mistake, after a fix, after an audit miss, for postmortem requests, "why did this happen", "why did the audit miss this", or "how do we prevent this next time" prompts.
---

# Trace Fix Root Causes

## Purpose

Use this skill when a Codex implementation mistake, bug, UI flaw, audit miss,
or quality regression has been reported or fixed. The goal is not blame and not
a vague postmortem. The goal is to reproduce the reported failure when
possible, distinguish changed requirements from Codex-created gaps, trace the
creation path of the mistake, patch the nearest durable guardrail first when
prevention is needed, audit the testing procedure for other possible missed
failures, close the implementation gap, and run comprehensive tests that prove
the user gets the expected result.

## Workflow

1. **Reproduce the reported failure**
   - Record what failed, who noticed it, and the same surface the user saw:
     browser route, CLI command, app screen, test, generated artifact, audit
     output, or integration path.
   - Try to replicate the error when it is possible and reasonable. If it is
     not possible, record why and capture the closest concrete evidence:
     user report, screenshot, log, diff, test output, before/after artifact, or
     source trace.
   - If evidence is missing, label the causal chain `unconfirmed`; do not
     invent root causes.

2. **Check user intent and scope**
   - Compare the original request, latest user clarification, accepted plan,
     project documentation, journey docs, and delivered behavior.
   - If the issue is caused by the user changing their mind or changing the
     requirement after implementation, mark it as a scope change instead of a
     Codex mistake.
   - If the requirement did not change, trace how Codex perceived the request:
     what was misread, over-assumed, omitted, or incorrectly prioritized.

3. **Trace the creation path**
   - Check the nearest sources that could have created or missed the problem:
     requirements, user intention, journey docs, mockups, design handoff, audit
     reports, skill instructions, verifier scripts, implementation code, tests,
     review notes, policies, `AGENTS.md`, context, tool choices, and handoff
     assumptions.
   - Separate the immediate defect from the detection failure. A UI can be
     wrong because the code rendered the wrong thing, because docs asked for
     the wrong thing, because Codex misread the request, because an audit
     accepted it, or because tests never exercised the actual journey.
   - Mark each causal link as `confirmed`, `source-inferred`, or `unconfirmed`.

4. **Classify recurrence risk**
   - `generalizable`: the same class of mistake is likely to recur across tasks, repos, skills, or UI surfaces.
   - `local-repeatable`: the mistake is specific to this repo or workflow but likely to recur there.
   - `one-off`: the mistake was local and unlikely to recur after the direct fix.
   - `unconfirmed`: evidence is insufficient to choose.

5. **Fix the system first**
   - For generalizable or local-repeatable causes, update the nearest durable
     guardrail before closing the product gap when practical: local
     `AGENTS.md`, project docs, acceptance criteria, skill instructions,
     verifier checks, regression fixtures, unit/visual tests, policy updates,
     context docs, or review checklists.
   - If a skill or audit was run and missed the issue, improve that skill or
     its deterministic checks before declaring the incident handled. Re-run it
     on the same code or evidence and verify that it now catches the gap.
   - For one-off causes, add the smallest targeted test, fixture, or code
     review note needed; do not add broad process for a non-repeatable mistake.
   - Prefer guardrails that run automatically or are hard to skip.

6. **Audit the testing procedure**
   - When the user finds a mistake that Codex testing did not catch, inspect
     the tests, verifiers, audits, smoke checks, fixtures, mocks, seeded data,
     acceptance criteria, and manual validation that should have caught it.
   - Look for other possible missed failures in adjacent journeys, edge cases,
     failure paths, integrations, generated artifacts, permissions, persistence,
     filtering, actions, charts, and user-visible results.
   - Add or update tests for those risks before calling the testing procedure
     repaired. Do not stop at a single regression test if the missed symptom
     exposes broader coverage weakness.

7. **Close the implementation gap**
   - Fix the product issue itself after the prevention layer is patched, or
     explicitly record why the product fix had to happen first.
   - Keep the product fix scoped to the reported mistake unless the root-cause
     evidence proves a broader correction is needed.

8. **Retest the original path and guardrail**
   - Re-run the original reproduction path: same route, command, screen, test,
     artifact, audit, or integration where the user saw the failure.
   - Run the new or updated guardrail: test, verifier, audit, screenshot check,
     fixture, self-test, or policy validation.
   - If you edit a skill or verifier, add a self-test fixture that fails before
     the guardrail and passes after it.
   - Optional: validate the final report shape with
     `scripts/verify_root_cause_report.py`.

9. **Run comprehensive post-fix tests**
   - After the detected gap is closed, run the broader test set identified by
     the testing-procedure audit, not only the focused regression.
   - Cover the user's expected result through representative unit,
     integration, end-to-end, visual, artifact, data, and failure-path checks as
     appropriate for the product surface.
   - If comprehensive testing is blocked, report the blocker and do not claim
     the user-facing result is fully verified.

## Output

Return these headings:

```markdown
## Fixed Symptom
## Reproduction
## User Intent And Scope Check
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

Under `Reproduction`, name the original surface or explain why replication was
not possible or not reasonable. Under `User Intent And Scope Check`, say whether
the user changed the requirement or Codex misread/omitted the original request.
Under `Causal Chain`, include the origin point, immediate defect, missed
detection point, and evidence status for each causal link. Under `System Fix
First`, name owner files or systems such as `AGENTS.md`, docs, skills,
verifiers, tests, policies, or context sources. Under `Testing Procedure Audit`,
identify other likely missed failures and the tests/verifiers/audits added or
updated to cover them. Under `Retest Results`, include both the original
reproduction path and the new or updated guardrail check. Under `Comprehensive
Retest Results`, list the broader post-gap test commands, checks, or manual
journeys that prove the user gets the expected result after the implementation
gap is closed.

## Completion Rules

- Do not skip reproduction when it is possible and reasonable.
- Do not invent root causes or present a root cause as confirmed without
  concrete evidence.
- Do not treat a changed requirement as a Codex implementation mistake.
- Do not stop at fixing the symptom when the creation path exposes a repeatable
  workflow gap.
- Do not close the implementation gap before patching the nearest durable
  guardrail unless you explain why that ordering was not practical.
- Do not stop at one targeted regression when Codex testing missed a
  user-visible mistake; audit the testing procedure for adjacent gaps and run
  comprehensive tests after the detected gap is closed.
- Do not add global process for a one-off mistake unless there is evidence that the mistake class is recurring.
- If the user asks to implement prevention, update the relevant docs, skill,
  verifier, policy, or tests and run the validation path before reporting done.
