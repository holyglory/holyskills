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
- Treat recorder installation or retirement, Codex feature activation, hook
  trust, and credential generation or rotation as security-posture decisions.
  Before any of them, apply `security-assumptions.md` from the durable project root
  the user selected to authorize this user-wide installation, normally the
  canonical repository clone. Do not borrow assumptions from whichever project
  happens to be active. The assumptions must explicitly cover every named home
  and its use across projects. If no durable root has been selected, ask the
  user to choose one. If its file is absent or insufficient, ask one
  plain-language baseline covering users and operators; runtime environment and
  ownership; asset/data sensitivity; credible adversaries and misuse; trust
  boundaries; necessary and explicitly unnecessary gates; acceptable risks;
  and review triggers. Record the user's confirmed answers before enabling or
  trusting hooks; never fill gaps with a generic threat model.
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
set. Do not apply a plan whose paths or ownership differ from the request.

## 4. Apply and verify the reviewed plan

Before applying an update that changes an active endpoint, credential, or
installed runtime, stop submitting work while the old receiver remains alive,
wait at least the configured exporter interval (five seconds by default) as a
best-effort export opportunity, then fully exit every affected Codex and Claude
process. This does not prove a flush. Apply from a separate shell or unaffected
runtime. If this skill runs inside a target process, hand off the digest-bound
commands and report restart/activation pending; never claim the same session
adopted the new OTel environment.

Use the exact journal and digest emitted by planning:

```text
<python> <repo>/tools/delivery-efficiency/recorder.py install apply
  --journal <absolute-journal.json> --plan-digest <plan_sha256>
<python> <repo>/tools/delivery-efficiency/recorder.py install verify
  --journal <absolute-journal.json> --plan-digest <plan_sha256>
```

Do not hand-edit `hooks.json`, `config.toml`, Claude `settings.json`, the
installed runtime, or the cold ledger. Keep the transaction until activation
is proven so the exact reviewed state can be rolled back.

## 5. Restart and activate each host

Fully exit every configured runtime process after apply, then start a new
session. A window close that leaves a background process alive is not a
restart. This is mandatory after a port, credential, settings, hook, or runtime
change.

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

Durable events identify runtime family, not the configured home. Verify homes
one at a time: fully exit every other client of the same family, capture a
baseline immediately before launching only the named target with its exact home
environment, submit one fresh harmless prompt, wait for its normal stop, and
then inspect only events after that baseline. If other same-family clients
cannot be quiesced, per-home activation remains unproven.

Before capturing the baseline, use the same privacy-bounded process inspection
as inventory to confirm that no other same-family client remains. If home
identity cannot be distinguished reliably, stop every same-family client; do
not infer isolation from closed windows alone.

Capture the baseline with the reviewed journal and digest:

```text
<python> <skill>/scripts/activation_status.py \
  --journal <absolute-journal.json> \
  --plan-digest <plan_sha256> \
  --runtime <codex-or-claude>
```

Retain the returned `max_sequence`, launch and exercise only that home, then
request the fresh receipt:

```text
<python> <skill>/scripts/activation_status.py \
  --journal <absolute-journal.json> \
  --plan-digest <plan_sha256> \
  --runtime <codex-or-claude> \
  --after-sequence <baseline-sequence> \
  --wait-seconds 15 \
  --require-active
```

The helper binds the current canonical recorder source to the reviewed journal,
re-verifies installed targets and receiver health, reads only the recorder's
integrity-checked authoritative snapshot, and emits no task identities or raw
events. Success requires a new task start, a new authoritative nonempty token
observation, and hook-only lifecycle evidence bound to the same task. For
Claude, hook and OTLP prompt events deliberately deduplicate into one task
start, so the receipt also requires a canonical Stop, StopFailure, or subagent
event that OTLP alone cannot create. Recorder `status`, installed config bytes,
unrelated task events, an unbound or empty token event, a terminal declaration,
or a hook listed in a file is not enough. Diagnose a failure in this order:

1. Runtime fully restarted after apply.
2. Exact runtime home selected.
3. Codex hook reviewed and trusted, or Claude settings source active.
4. Hooks feature and higher-precedence policy/settings.
5. Receiver health, endpoint/credential rotation, and bounded runtime gaps.
6. Per-home process isolation and fresh task/OTLP correlation rather than
   concurrent or historical events.

Do not declare complete while a requested runtime lacks fresh task-bound
evidence. Report installed and activated targets separately, along with
versions, the reviewed plan digest, health, verification evidence, remaining
manual trust/restart steps, any per-home attribution limitation, and the exact
rollback command. Keep secrets and raw telemetry out of the handoff.

## 7. Verify rollback when it is used

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
