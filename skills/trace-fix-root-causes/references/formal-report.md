# Formal Incident Report

Use this artifact only for requested postmortems and serious, recurring,
systemic, or disputed incidents. Keep each field concise and replace the
guidance text with concrete evidence.

```markdown
## Outcome

Status: fixed

One sentence describing the user-visible result.

## Cause

Class: ui
Confidence: confirmed
Request: What the user expected and whether it changed.
Immediate cause: The evidence-backed defect.
Why missed: The specific verification or workflow gap.
Evidence: The smallest useful set of paths, commands, logs, sources, hashes, or screenshots.

## Changes

Product: The complete user-facing correction, or an explicit read-only/blocker statement.
Prevention: The focused regression or guardrail, or why none is proportionate for a one-off issue.

## Verification

Original path: The same surface and result the user reported, retested after the change.
Checks: Focused and risk-justified broader checks actually run.
Residual risk: Remaining uncertainty or `none`.
```

Allowed statuses are `fixed`, `diagnosed`, and `blocked`. Allowed classes are
`implementation`, `ui`, `factual`, `reasoning`, `tool-use`, `artifact`,
`service`, `audit`, `verification`, and `other`. Confidence is `confirmed`,
`source-inferred`, or `unconfirmed`.

Do not add internal evidence IDs or causal IDs merely to satisfy the template.
Human-readable source names and observations are the evidence record.
