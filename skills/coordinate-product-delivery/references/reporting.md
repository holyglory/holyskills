# Plain-Language Delivery Reporting

## Contents

1. Status report
2. Blocker report
3. Product expansion decision
4. Release completion

## Status Report

```text
Overall approved-roadmap progress: <percent>% at <baseline or scope revision>

<Release name>: <percent>% complete, <ready|not ready|at risk|blocked>

Monitoring: <armed|unarmed|blocked|stopped>
Schedule: <same-chat scheduled-task ID>, every <minutes> minutes, next run <time>
First run: <verified evidence|not verified>

What now works
<user-visible outcomes>

What is next
<next user-visible result>

Unfinished work
<count and plain-language release impact>

Decision needed
<none, or one concise decision>
```

Do not list files, functions, APIs, libraries, database columns, logs, or internal agent names unless the user asks. Translate a technical blocker into the affected user outcome and the next result.

When ongoing supervision was requested and monitoring is not armed, lead with `Monitoring is unarmed and blocked.` Do not use an ordinary progress report or wording that implies the coordinator will keep watching after the current turn.

## Blocker Report

```text
Affected outcome
<what the user cannot receive yet>

Why it is blocked
<plain-language cause>

What continues meanwhile
<unblocked delivery work>

Decision or external change needed
<one concrete need>

Release effect
<timing, scope, readiness, or none>

Recommendation
<coordinator recommendation>
```

## Product Expansion Decision

```text
The execution team proposes adding:
<new user-visible behavior>

Why:
<reason>

Without it:
<effect on the already approved result>

If approved:
<effect on release scope, progress, timing, cost, risk, or maintenance>

Recommendation:
<approve now|adjust|defer|decline, with one reason>

Decision:
Should I add this behavior to <release>?
```

Do not expose the executor's implementation proposal when the user only needs the product decision. Preserve material privacy, security, cost, and maintenance consequences even when technical detail is removed.

## Release Completion

```text
<Release name> is ready.

Delivered outcome
<what users can now do>

Final progress
100% against <scope baseline>

Completion Ledger
<implemented and verified issue count; any remaining non-blocking work>

Evidence
<observable acceptance results in user language>

Next release
<next approved outcome or no approved next release>
```

Never call a release ready merely because its percentage is high. Readiness comes from the database gate, accepted outcomes, and verification.
