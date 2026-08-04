---
name: install-delivery-efficiency-hooks
description: Install, upgrade, activate, verify, or troubleshoot the HolySkills delivery-efficiency recorder and its Codex and Claude Code lifecycle hooks on macOS, Linux, native Windows, or WSL. Use when an agent needs to install required runtime dependencies, configure one or more explicit Codex or Claude homes, repair or rotate an existing recorder installation, enable the Codex hooks feature, complete host-required hook activation, or prove that fresh tasks receive task-bound token telemetry.
---

# Install Delivery Efficiency Hooks

Use the repository recorder installer as the only writer. This skill owns the
installation workflow, not another recorder, hook implementation, ledger, or
settings editor.

## Preserve the installation boundary

- Resolve the canonical repository containing
  `tools/delivery-efficiency/recorder.py`; never install from an unrelated
  mutable checkout or edit a generated installed copy.
- Name every Codex and Claude home with an explicit absolute path. Discover
  desktop, sandbox, OS-account, native-Windows, and WSL homes separately;
  never treat the invoking shell's `HOME` as proof of another runtime's home.
- A first recorder installation or retirement, Codex feature activation, hook
  trust, and credential generation or rotation can change security posture. A
  verified non-rotating repair that preserves the same named homes, endpoint
  boundary, credential, controls, and documented posture is routine execution,
  not a new posture decision. Apply `security-assumptions.md` from the durable
  project root the user selected for this user-wide installation, normally the
  canonical repository clone; do not borrow assumptions from whichever project
  happens to be active. The record must cover every named home and its
  cross-project use.
  Use its confirmed answers and read-only discovery first. Ask only when a
  concrete pending control decision depends on an unresolved assumption and a
  wrong answer could select unnecessary controls, omit a necessary control,
  expand the work, or cause meaningful rework. Ask the smallest concise set of
  material questions, with detail proportional to impact; cover the full
  baseline only when that decision materially depends on every area. If no
  durable root has been selected and one is needed for a pending decision, ask
  the user to choose one. Record confirmed answers before changing posture;
  never fill gaps with a generic threat model.
- Preserve unrelated hooks, settings, skills, telemetry exporters, and runtime
  homes. Stop on a conflicting OTel owner or edited managed block instead of
  overwriting it.
- Treat runtime authentication, recorder health, and hook activation as
  operational facts only. They grant no authority beyond the user's request.
- Never persist prompts, responses, commands, tool payloads, credentials, or
  other content in installation evidence.

## 1. Inventory the requested runtimes

1. Identify the host environment as macOS, Linux, native Windows, or WSL.
2. List the Codex and Claude runtimes the user wants covered, including each
   desktop or alternate-home instance. Resolve `CODEX_HOME` and
   `CLAUDE_CONFIG_DIR` overrides for the exact process; otherwise use that
   runtime account's native default. Give every home a stable unique name.
   When a sandboxed or desktop host hides these values, use its own diagnostic
   surface or a process inspector only to read the target executable path and
   the allowlisted `CODEX_HOME`, `CLAUDE_CONFIG_DIR`, and `HOME` variables.
   Never dump a complete environment or command line. Confirm discovered paths
   through the runtime's config or status surface; ask the user when the host
   exposes no reliable evidence.
3. If a recorder is already managed, inspect its
   `<state>/managed-targets.json` and retain every existing target during an
   upgrade or credential rotation unless the user explicitly retires it.
4. Read [platform-prerequisites.md](references/platform-prerequisites.md) only
   when a prerequisite is missing or platform-specific installation guidance
   is needed.

Do not guess an ambiguous runtime home. Ask the user only after read-only
process, environment, config, and executable discovery cannot establish it.

## 2. Prove prerequisites

- Use an absolute Python 3.9-or-newer executable. Prove the exact executable
  with `<python> -c "import sys; raise SystemExit(sys.version_info < (3, 9))"`.
  The recorder otherwise uses only the standard library.
- For each Codex target, confirm that the intended runtime exposes lifecycle
  hooks and OTel. Run the absolute intended Codex executable's
  `features list` with that target's exact `CODEX_HOME` in only the subprocess
  environment. Record the effective state, exact executable, and home before
  any enable action; this operational preflight is outside the recorder
  transaction. If `hooks` is available but disabled, the security assumptions
  are confirmed, and activation is within the request, use that same scoped
  environment and executable for `features enable hooks`, then recheck. This
  is Codex's own feature writer, separate from recorder-managed config. A
  managed policy that forces hooks off is a blocker; do not bypass it.
  `features list` proves only feature availability, not OTel activation. Treat
  OTel support as structural until the exact restarted runtime accepts the
  installed `[otel]` configuration and emits a fresh strict `codex-otel`
  observation. The installer journal does not bind a Codex executable, version,
  or feature-list result; retain this operational preflight evidence separately.
- For each Claude target, use Claude Code 2.1.212 or newer. Pass
  `--claude-executable` with the absolute intended executable when discovery
  could select another installation. One recorder plan has one Claude
  executable for all included Claude homes. If the retained homes require
  different executables, stop and explain that one plan cannot represent that
  set exactly; do not silently select one binary or split an already managed
  target set.
- Require the named home directories to exist as real directories. Native
  Windows and WSL are distinct installations and stores.

If required software is absent, use the user's existing package manager or a
current official installer from the platform reference. An invocation that
explicitly asks to install the named runtimes includes their necessary
prerequisites; a troubleshoot-or-verify-only invocation does not. Otherwise
explain the exact mutation and get approval first. Re-run every version and
feature check afterward.

## 3. Create and review the immutable plan

Run the canonical installer from the repository root with every target in one
plan. Use the platform's Python executable and path syntax:

```text
<python> <repo>/tools/delivery-efficiency/recorder.py install plan
  --source-root <absolute-repo>/tools/delivery-efficiency
  --state-dir <absolute-platform-native-state>
  --python-executable <absolute-python>
  --codex-home <name>=<absolute-home>
  --claude-home <name>=<absolute-home>
  --claude-executable <absolute-claude>
  [--rotate-auth-token]
```

Omit a runtime-specific home or executable option only when that runtime is not
requested. Repeat each home option as needed. Native Windows and WSL require
separate platform-native plans and state. Include every retained managed target.
Use `--rotate-auth-token` only when the user-confirmed assumptions and request
or concrete evidence select credential rotation; never add it merely because
the recorder version changes. A first install generates its initial credential
without this option. Use explicit `--retire-codex-home` or
`--retire-claude-home` only when the user asked to retire that exact target.

Classify the planned change from evidence. Equal recorder version and equal
source bytes is a repair or credential rotation, not an upgrade. Equal version
with different source bytes is ambiguous unversioned source drift: stop and
either restore the released bytes or version the changed recorder before
applying. A real runtime upgrade changes the recorder version.

Planning creates a private transaction, journal, and secret sidecar under the
selected state location. It does not mutate runtime homes, but it is not a
read-only command. Review and preserve those artifacts accordingly.

Review the printed `journal_path`, `plan_sha256`, source and target digests,
state directory, port provenance, target actions, and complete retained-target
set. Classify which runtime targets actually require reload from the changed
actions. A runtime requires the one shutdown/reopen boundary only when the plan
changes its handler bytes, Python binding, OTel endpoint or credential,
managed environment, or another host-loaded setting. A recorder-only install,
version, or settings-root change with identical host configuration does not.
Do not proceed with a plan whose paths, ownership, affected-target set, or
reload classification differs from the request.

Recorder `0.2.4` and later route managed Codex and Claude handlers through the
version-neutral `<state>/recorder.py` launcher. A compatible upgrade from
recorder `0.1.2` or later preserves the same loopback host, bearer credential,
and port when rotation was not requested; it performs bounded authenticated
receiver retirement and rebind rather than signaling a PID. The `0.2.3` to
`0.2.4` migration changes existing handler commands once, so those hosts need
one reload and changed Codex hooks need one host review. A later compatible
recorder-only upgrade must render the same host configuration, leave those
actions unchanged, and require neither a host restart nor renewed hook trust.
Credential changes and upgrades from a pre-`0.1.2` recorder retain the reviewed
port-rotation behavior.

## 4. Arm the agent-owned deferred install

The agent owns target-process discovery. From the changed runtime actions,
identify every live same-user Codex or Claude process that must exit, including
background helpers. Use the privacy-bounded inventory method from step 1 and
pass each exact live PID once; never ask the user to find a PID, inspect a
process list, open Terminal, or copy a command. Do not persist a full command
line or environment. Platform-specific process identity and detached-worker
behavior are defined in
[platform-prerequisites.md](references/platform-prerequisites.md).

Stop submitting new work to the affected runtimes and leave the old receiver
alive for at least the configured exporter interval—five seconds by default—as
a best-effort export opportunity. This does not prove a flush. After the user
approves the reviewed plan, the agent runs the canonical recorder itself:

```text
<python> <repo>/tools/delivery-efficiency/recorder.py install defer
  --journal <absolute-journal.json>
  --plan-digest <plan_sha256>
  --target-pid <exact-live-pid>
  [--target-pid <another-exact-live-pid> ...]
  [--wait-seconds 86400]
```

`--target-pid` is repeatable and requires at least one affected live process.
The wait defaults to 86400 seconds and accepts only 1 through 604800 seconds.
The command creates one private digest-bound request, launches the one-shot
worker, and waits for its ready handshake. It succeeds only by emitting exactly
one bounded `DEFERRED_INSTALL_ARMED` receipt containing a nonsecret `job_id`,
the private status-report `filename`, `status="armed"`, target count, and wait
limit. It never emits a PID, path, credential, command, environment value, or
raw error. `armed` proves only that the detached worker owns the request and
exact process identities; it is not installation or verification success.

Only after that ready receipt may the agent ask the user to fully close each
affected Codex and Claude host once. Closing a window while its reviewed
background process remains alive is not an exit. The detached worker never
signals a PID. It waits for the exact captured process instances to end,
rejects detected PID reuse or same-image relaunch races, reopens the exact
journal with the reviewed digest, and invokes the existing transactional
apply-and-verify path. Drift, collision, timeout, cancellation, or an
unclassifiable process fails closed.

If an unaffected agent or host-owned observer remains available, it may poll
the saved job while the affected hosts are closed. Otherwise the first action
of the reopened agent is to read the same saved status before doing any other
work:

```text
<python> <repo>/tools/delivery-efficiency/recorder.py install deferred-status
  --journal <absolute-journal.json>
  --plan-digest <plan_sha256>
  --job-id <job_id>
```

The command emits exactly one bounded `DEFERRED_INSTALL_STATUS` receipt naming
the same private report filename. The private canonical report binds the job
and plan and records one of `verified`,
`cancelled`, `expired`, `target-race`, `failed-unapplied`,
`failed-rolled-back`, `rollback-blocked`, or `worker-lost`, plus bounded phase,
verification, receiver-health, rollback, and failure-code fields. It contains
no paths, PIDs, target references, credentials, source content, commands, or
raw exceptions. If the user cancels before apply, the agent may invoke
`install deferred-cancel` with the same journal, digest, and job ID; never ask
the user to run it. Cancellation after transactional apply begins does not
interrupt or silently roll back that transaction.

Keep the worker one-shot and nonpersistent. An OS reboot ends it and requires
the agent to create a fresh plan and rearm without asking the user to open
Terminal. If a strict receipt for the exact job and plan digest proves that no
mutation occurred, `deferred-status` may report that saved categorical failure
even when the reboot changed volatile filesystem device identity. Treat this
as failure evidence only; it never authorizes apply, trust review, activation,
or success. After the fresh armed receipt, ask the user only to repeat the
required close/reopen boundary.

After the ready receipt, tell the user to close the named affected hosts, wait
the short settling interval announced by the agent, and reopen them once. The
user never opens Terminal, watches a private file, or copies/runs installer
commands in the normal path. The reopened agent must read deferred status
before trust review, activation, or any ordinary work. Treat only a saved
`status="verified"` receipt with `verification_ok=true` and
`receiver_healthy=true` as permission to continue. A detectable premature
matching relaunch fails closed as `target-race`. A nonverified receipt remains
incomplete: explain its bounded cause and use the recovery section only when
explicit recovery is needed. Do not fall back to publishing manual commands.

Do not hand-edit `hooks.json`, `config.toml`, Claude `settings.json`, the
installed runtime, private handoff files, or the cold ledger. Keep the
transaction until activation is proven so its exact reviewed state remains
recoverable.

## 5. Reopen once and complete host activation

After the ready handshake, the user closes only the runtime targets classified
as reload-required, waits the agent-announced short settling interval, and
reopens them once. The approve/close/reopen cycle happens once. The reopened
agent reads the saved status receipt and requires its verified result before
doing anything else. An optional unaffected observer may have
confirmed it earlier, but the workflow never requires one. Do not restart an
unchanged host merely because the recorder version or immutable install root
changed. The new session, not the closed session, adopts changed handler,
Python, endpoint, credential, environment, or host-loaded settings.

Claude Code loads the installed user hooks at session start and has no
Codex-style trust grant. Inspect `/hooks` and `/status` to confirm the active
settings source when precedence is uncertain. A still-running Claude process
retains its old OTel endpoint and credential even though new hook subprocesses
can read current recorder settings.

Codex requires the user to open `/hooks`, inspect the exact command and source
shown for each configured home, compare them with the verified managed
`hooks.json` command and immutable installed runtime root, and trust that
reviewed hook. Do not describe a host identifier as a whole-file or source-tree
digest unless the host documents that exact meaning. Tell the user when this
manual activation step pauses the workflow. Never edit Codex's trust store or
claim trust from filesystem installation alone. Never invoke or recommend
`--dangerously-bypass-hook-trust` in this workflow; it is not hook activation.

## 6. Prove fresh task correlation

For Codex, start one agent-owned watch for every reviewed target in the plan.
Use repeatable `--target <name>` only when the user requested a subset; without
it the helper selects all reviewed Codex homes.

```text
<python> <skill>/scripts/activation_status.py \
  --journal <absolute-journal.json> \
  --plan-digest <plan_sha256> \
  --runtime codex \
  --watch \
  --wait-seconds 300 \
  [--target <reviewed-name> ...]
```

Start the watch before asking the user to act. Then tell the user only to start
one fresh harmless task in each selected Codex instance. The instances may run
concurrently. Do not ask the user to open Terminal, copy a sequence, quit or
isolate another Codex app, or perform baseline choreography. The helper owns
the post-start sequence baseline and watches all selected homes for at most 900
seconds.

The helper binds the current canonical recorder source to the reviewed journal,
re-verifies installed targets and receiver health, reads only the recorder's
integrity-checked authoritative snapshot, and derives expected opaque target
identities in memory from the exact reviewed plan and private installed
credential. A Codex home is active only when one post-baseline task has a
target-bound hook `task.start`, target-bound hook evidence, and a nonempty
provider-native `codex-otel` usage observation with runtime-observed provenance
on that same target and task. A missing, null, legacy, or different target on
usage cannot activate the home.

The helper writes the complete bounded result under the recorder state's
private `activation-reports/` directory and emits exactly one concise
`REPORT_SAVED` receipt naming the file, status, active and pending counts,
SHA-256, and byte count. The report contains reviewed target names and bounded
counts only—never home paths, raw events, task/session/event identities, target
references, source content, or credentials. A timeout still saves the partial
report and returns nonzero. Treat only `status=active` with every selected
target active as per-home proof.

Installer apply, verify, and rollback remain exact. For activation
inspection only, a changed Codex `config.toml` action's whole-file hash drift
may conform when the target remains a safe regular no-link file, its managed
OTel block is byte-exact—including reviewed newline encoding—for the reviewed
installed settings, and supported single-line TOML outside that block has no
competing OTel definition. Multiline-string syntax outside the block and every
other action or malformed, duplicate, missing, or edited ownership remain
fail-closed. Target-aware hook and OTel evidence requires recorder `0.2.3` and
schema `1.2`. A legacy Codex installation may still produce honest fresh
family-level evidence, but the report marks every requested home unproven and
returns nonzero; never assign family events to homes by timing or user action.
Upgrade through a new reviewed plan to obtain target-aware proof. Claude remains
on its independent family-level workflow; do not use or claim Codex target
attribution for Claude.

Recorder `status`, installed config bytes, unrelated task events, an unbound,
empty, null-target, or cross-target usage event, a terminal declaration, or a
hook listed in a file is not enough. Diagnose a failure in this order:

1. Every reload-required runtime reopened once after the settling interval, and
   its reopened agent validated the verified deferred receipt before other work.
2. Exact runtime home selected.
3. Codex hook reviewed and trusted, or Claude settings source active.
4. Hooks feature and higher-precedence policy/settings.
5. Receiver health, endpoint/credential rotation, and bounded runtime gaps.
6. Fresh same-target task/hook/OTLP correlation rather than historical,
   family-only, null-target, or cross-target events.

Do not declare complete while a requested runtime lacks fresh task-bound
evidence. Report installed and activated targets separately, along with
versions, the reviewed plan digest, health, verification evidence, remaining
manual trust/restart steps, any per-home attribution limitation, the deferred
receipt filename and digest, and the available recovery reference. Keep secrets
and raw telemetry out of the handoff.

## 7. Keep Claude activation independent

The deferred receipt proves installation and receiver health for every target
in its exact plan, not fresh Claude task correlation. Claude remains on its
independent family-level activation workflow. Use its active settings sources,
hooks, and fresh task-bound evidence; never infer Claude activation from the
Codex concurrent watch or from successful installation alone.

## 8. Recovery only: direct installer commands

The commands in this section are recovery interfaces for an agent or operator
diagnosing a failed/lost deferred job. They are never the normal user journey,
never a fallback shown after `install defer` fails, and never instructions for
the user to open Terminal. Reopen the exact private deferred status first. Use
direct apply or verify only when the reviewed recovery state specifically calls
for it:

```text
<python> <repo>/tools/delivery-efficiency/recorder.py install apply
  --journal <absolute-journal.json> --plan-digest <plan_sha256>
<python> <repo>/tools/delivery-efficiency/recorder.py install verify
  --journal <absolute-journal.json> --plan-digest <plan_sha256>
```

Run rollback only against the exact reviewed transaction while its installed
targets still match:

```text
<python> <repo>/tools/delivery-efficiency/recorder.py install rollback
  --journal <absolute-journal.json> --plan-digest <plan_sha256>
```

A successful command proves exact restoration only for the recorder-managed
filesystem actions captured by that transaction; retain every reported
collision artifact. It does not undo installed prerequisites, runtime
authentication, Codex feature state changed before planning, or operator trust.
If this workflow changed `hooks` from observed disabled to enabled and the user
requests whole-workflow rollback, run the same absolute Codex executable with
the same scoped `CODEX_HOME` and `features disable hooks` after recorder
rollback, then recheck. Never disable it when the original state was enabled or
unknown. Review any trust reversal through the host rather than editing its
trust store. Fully exit and restart all affected runtimes again. Never reuse
the rolled-back journal as activation proof. If the restored installation has
its own retained reviewed journal, verify that journal and repeat the fresh
per-home correlation procedure; otherwise report activation as unproven until
it is established from a new reviewed plan.
