# Trace Fix Root Causes

`trace-fix-root-causes` investigates recently fixed bugs, UI flaws, regressions,
or audit misses and turns the evidence into a prevention plan.

Use it when a user asks why a problem happened, why an audit missed it, or how
to adjust workflow so the same class of mistake is caught next time.

It outputs a fixed symptom, evidence, causal chain, recurrence classification,
workflow improvements, validation plan, and boundaries for one-off causes.

Validation:

```bash
python3 skills/trace-fix-root-causes/scripts/self_test.py
```
