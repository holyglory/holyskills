# Trace Fix Root Causes

`trace-fix-root-causes` investigates Codex implementation mistakes, recently
fixed bugs, UI flaws, regressions, or audit misses and turns the evidence into
a prevention-first fix plan.

Use it when a user reports an implementation mistake made by Codex, asks why a
problem happened, asks why an audit missed it, or asks how to adjust workflow
so the same class of mistake is caught next time.

It requires reproduction when possible, checks whether the user changed the
requirement, traces how Codex perceived the request, patches the nearest
system guardrail first, audits the testing procedure for other possible missed
failures, closes the implementation gap, and runs comprehensive post-fix tests
that prove the user gets the expected result. It outputs a fixed symptom,
reproduction, intent/scope check, evidence, causal chain, recurrence
classification, system fix, testing procedure audit, implementation closure,
focused retest results, comprehensive retest results, and boundaries for
one-off causes.

Guardrail updates must be scoped and proportional: repo `AGENTS.md` is
repo-wide policy, not global policy; policy text should contain generalized
reusable rules only. Put one-off incident explanations in the root-cause report,
`DecisionHistory.md`, a targeted test, or a fixture.

When the problem is general enough to affect Codex behavior across tasks or
repos, and a global instruction would prevent recurrence, the global Codex
app-wide `/Users/holyglory/.codex/AGENTS.md` must be updated with that
generalized reusable instruction.

Validation:

```bash
python3 skills/trace-fix-root-causes/scripts/self_test.py
```
