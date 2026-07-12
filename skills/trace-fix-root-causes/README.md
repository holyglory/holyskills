# Trace Fix Root Causes

`trace-fix-root-causes` handles requested postmortems and serious, repeated,
systemic, disputed, or previously missed Codex/Claude Code failures. Ordinary
isolated bugs with a clear bounded fix should use the direct reproduce, fix,
focused-regression, and original-surface-retest path without loading the skill.

When the skill applies, a clear report of a broken in-scope product, service,
configuration, or artifact normally authorizes a safe bounded fix; the user
does not need to repeat “fix it.” Explicit requests for explanation, review,
audit, or no changes remain read-only.

The default path is intentionally small:

1. reproduce through the user's surface;
2. establish the immediate cause and missed check;
3. fix the complete in-scope behavior and add focused regression coverage;
4. retest the original path; and
5. return a concise cause/change/verification summary.

Formal evidence work is reserved for requested postmortems and serious,
recurring, systemic, destructive, or disputed incidents. Those reports use the
four readable sections in `references/formal-report.md`: `Outcome`, `Cause`,
`Changes`, and `Verification`. The deterministic verifier checks that formal
artifact without forcing it into ordinary bug-fix replies.

Validate the skill and its realistic incident fixtures with:

```bash
python3 skills/trace-fix-root-causes/scripts/self_test.py
```

Validate a formal report with:

```bash
python3 skills/trace-fix-root-causes/scripts/verify_root_cause_report.py REPORT.md
```
