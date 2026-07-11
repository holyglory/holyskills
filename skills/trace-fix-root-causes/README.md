# Trace Fix Root Causes

`trace-fix-root-causes` investigates mistakes caused or missed by Codex or
Claude Code: implementation and UI defects, factual and reasoning errors,
incorrect tool use, broken artifacts, local-service crashes, audit misses,
regressions, and incomplete verification.

The skill is evidence-driven rather than a generic postmortem. It requires:

- reproduction through the original user-visible surface when reasonable;
- an explicit `diagnose-only` or `authorized-fix` mode before mutation;
- one explicit incident class, so ruled-out phrases cannot trigger the wrong contract;
- a structured evidence ledger and evidence-linked causal chain;
- separate origin, immediate-defect, and missed-detection findings;
- changed-requirement and external-change checks;
- incident-specific evidence for facts, tools, artifacts, and services;
- prevention-first fixes and realistic detector recall tests when authorized;
- original-path and comprehensive post-fix verification.

A report alone does not authorize changes. In `diagnose-only`, the skill uses
read-only evidence and records proposed work. In `authorized-fix`, it updates
the smallest durable guardrail, closes the implementation gap, and proves the
result.

Policy paths are runtime-portable. Repository policies remain repository
scoped; global rules use the active runtime's supplied policy path, normally
`CODEX_HOME/AGENTS.md` or `CLAUDE_CONFIG_DIR/CLAUDE.md`. The skill never embeds
a username-specific path or assumes `$HOME` identifies the host installation.

Validate the skill and its realistic incident fixtures with:

```bash
python3 skills/trace-fix-root-causes/scripts/self_test.py
```

Validate a report with:

```bash
python3 skills/trace-fix-root-causes/scripts/verify_root_cause_report.py REPORT.md
```
