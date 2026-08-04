# Security Assumptions

Status: user-confirmed on 2026-08-01.

## Scope

These assumptions govern installation, repair, activation, and operation of the
HolySkills delivery-efficiency recorder for these user-owned runtimes:

- Codex at `$HOME/.codex`
- Parall Codex at
  `$HOME/Library/Application Support/Parall/ChatGPT (TT)/.codex`
- Claude Code at `$HOME/.claude`

They do not establish the security posture of unrelated applications or
projects. Reuse the confirmed answers below for routine recorder work. Ask only
about an unresolved assumption that is material to a concrete pending control
decision and whose wrong answer could cause unnecessary controls, an omitted
necessary control, expanded work, or meaningful rework.

## Confirmed assumptions

- **Users and operators:** This is a personal macOS account. The user owns and
  trusts all three named runtimes. No unrelated users or administrators operate
  them.
- **Environment and ownership:** The recorder is local-only, runs under the
  same account, and communicates over loopback. It is not a shared, remote, or
  network service.
- **Allowed telemetry:** Lifecycle metadata, timing, provider-native token
  counters, runtime and version metadata, and opaque correlation identifiers.
- **Prohibited telemetry:** Prompts, responses, source content, commands, tool
  payloads, credentials, and personal content.
- **Credible threats:** Configuration drift, an unrelated owner of the same
  runtime configuration, unintended network exposure, and unauthenticated
  local submissions.
- **Out of scope:** Root compromise, malware, and a malicious process already
  running as this same OS account.
- **Necessary gates:** One canonical repository source; immutable installed
  runtime copies; a loopback bearer credential; digest-reviewed
  plan/apply/verify/rollback; explicit runtime homes; preservation of unrelated
  settings; fail-closed conflict and drift handling; manual Codex `/hooks`
  review; and no trust bypass.
- **Explicitly unnecessary gates:** An administrator daemon, TLS on loopback,
  cross-account local hardening, credential rotation without compromise or
  contrary evidence, a remote collector, and migration or preservation of
  disposable telemetry.
- **Accepted risks and costs:** A same-account process can read the local
  credential; hooks can add minor latency or fail; local metadata is retained;
  and activation may require runtime restarts and manual trust review.
- **Review triggers:** Reassess the material assumptions if the machine or
  account becomes shared, another OS account is involved, the recorder becomes
  remotely reachable, sensitive or regulated scope is introduced, compromise
  is suspected, runtimes or homes change, ownership changes, or deployment is
  added on native Windows, WSL, or Linux.

## Current recorder decision

The recorder `0.2.4` installation upgrade keeps the established loopback
boundary, bearer credential, explicit homes, and host trust gate. It preserves
the `0.2.3` opaque per-Codex-home correlation contract and adds a same-user,
local-only, detached one-shot installer handoff. The worker is bound to one
reviewed plan and exact process incarnations, waits for their exit without
signaling them, uses private bounded state and a minimal environment, invokes
the existing transactional apply/verify/rollback implementation, saves a
privacy-bounded receipt, and expires. It is not a daemon, scheduler, login
item, remote service, authorization mechanism, or trust bypass.

The handoff wait covers a realistic delayed return but remains bounded and
nonpersistent; an OS reboot kills it and requires agent-owned replan/rearm. A
read-only recovery status may report a canonical exact job-and-digest-bound
receipt across volatile filesystem device-identity drift only when the receipt
strictly proves that mutation never started and claims no verification,
receiver health, rollback, trust, activation, or success. This narrow behavior
is supported by the confirmed single trusted account and the explicit
exclusion of a malicious same-account process. Apply, rearm, successful
verification, rollback, trust, and activation continue to require the complete
reviewed transaction and drift gates.

Compatible upgrades keep the confirmed credential and loopback port and route
managed hooks through a strictly validating version-neutral launcher. Rotation,
privilege, extra hardening, and new network or account boundaries remain
unselected without a review trigger or concrete contrary evidence. Native
Windows, WSL, or Linux deployment still requires the smallest material
assumption review for that actual host; portable implementation and tests do
not claim that such a deployment has occurred.
