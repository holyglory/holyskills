---
name: trace-fix-root-causes
description: Investigate recently fixed bugs, UI flaws, audit misses, regressions, or user-reported quality problems to explain how the mistake was created and recommend workflow, documentation, verifier, test, skill, or policy improvements that prevent the same class of mistake from recurring. Use after a fix, audit miss, postmortem request, "why did this happen", "why did the audit miss this", or "how do we prevent this next time" prompt.
---

# Trace Fix Root Causes

## Purpose

Use this skill after a bug, UI flaw, audit miss, or quality regression has been reported or fixed. The goal is not blame and not a vague postmortem. The goal is to trace the creation path of the mistake, distinguish one-off defects from repeatable workflow gaps, and recommend guardrails that make the same class of mistake harder to repeat.

## Workflow

1. **Identify the fixed symptom**
   - Record what failed, who noticed it, and what evidence proves the failure.
   - If the problem is already fixed, capture the before/after evidence, test, screenshot, audit output, commit diff, or user report that establishes the original failure.
   - If evidence is missing, label the causal chain `unconfirmed`; do not invent root causes.

2. **Trace the creation path**
   - Check the nearest sources that could have created or missed the problem: requirements, journey docs, mockups, audit reports, skill instructions, verifier scripts, implementation code, tests, review notes, policies, and handoff assumptions.
   - Separate the immediate defect from the detection failure. A UI can be wrong because the code rendered the wrong thing, because docs asked for the wrong thing, because an audit accepted it, or because tests never exercised the actual journey.
   - Mark each causal link as `confirmed`, `source-inferred`, or `unconfirmed`.

3. **Classify recurrence risk**
   - `generalizable`: the same class of mistake is likely to recur across tasks, repos, skills, or UI surfaces.
   - `local-repeatable`: the mistake is specific to this repo or workflow but likely to recur there.
   - `one-off`: the mistake was local and unlikely to recur after the direct fix.
   - `unconfirmed`: evidence is insufficient to choose.

4. **Recommend prevention**
   - For generalizable or local-repeatable causes, recommend concrete guardrails: docs contract changes, skill instructions, verifier checks, regression fixtures, unit/visual tests, policy updates, acceptance criteria, or review checklist changes.
   - For one-off causes, recommend the smallest targeted test or code review note needed; do not add global process for a non-repeatable mistake.
   - Prefer guardrails that run automatically or are hard to skip.

5. **Validate the prevention plan**
   - Name the command, test, audit, screenshot, verifier, or manual journey that proves the guardrail works.
   - If you edit a skill or verifier, add a self-test fixture that fails before the guardrail and passes after it.
   - Optional: validate the final report shape with `scripts/verify_root_cause_report.py`.

## Output

Return these headings:

```markdown
## Fixed Symptom
## Evidence Used
## Causal Chain
## Root Cause Classification
## Workflow Improvements
## Validation Plan
## Boundaries And Non-Generalizable Notes
```

Under `Causal Chain`, include the origin point, immediate defect, missed detection point, and evidence status for each causal link. Under `Workflow Improvements`, name owner files or systems when they are known.

## Completion Rules

- Do not present a root cause as confirmed without concrete evidence.
- Do not stop at fixing the symptom when the creation path exposes a repeatable workflow gap.
- Do not add global process for a one-off mistake unless there is evidence that the mistake class is recurring.
- If the user asks to implement prevention, update the relevant docs, skill, verifier, policy, or tests and run the validation path before reporting done.
