# Platform prerequisites

Read this reference only when required software is absent or platform-specific
path and installation guidance is needed. Recheck the linked official source
before executing an installer because distribution methods change.

## Common requirements

- Python 3.9 or newer runs the shared recorder. Verify the exact executable
  with `python --version` or `python3 --version`.
- Codex must expose the stable `hooks` feature and OTel configuration. Verify
  the intended binary with `codex --version` and `codex features list`.
- A configured Claude home requires Claude Code 2.1.212 or newer. Verify it with
  `claude --version`; use `claude doctor` for installation diagnostics.
- Install only the runtimes the user requested. Authentication is a separate
  user action and does not authorize installation or agent work.

Scope Codex feature checks to the intended home without changing the parent
agent's environment. On macOS, Linux, or WSL, run a child command equivalent to:

```bash
env CODEX_HOME="/absolute/codex-home" "/absolute/codex" features list
env CODEX_HOME="/absolute/codex-home" "/absolute/codex" features enable hooks
```

On native Windows PowerShell, restore the prior environment even on failure:

```powershell
$priorCodexHome = $env:CODEX_HOME
try {
  $env:CODEX_HOME = 'C:\absolute\codex-home'
  & 'C:\absolute\codex.exe' features list
  & 'C:\absolute\codex.exe' features enable hooks
} finally {
  $env:CODEX_HOME = $priorCodexHome
}
```

Run the enable command only after the skill's authorization and security-
assumption gates are satisfied. A feature listing is read-only; enabling is a
Codex configuration mutation.

Authoritative installers:

- Python: <https://www.python.org/downloads/>
- Codex CLI: <https://learn.chatgpt.com/docs/codex/cli>
- Claude Code: <https://code.claude.com/docs/en/installation>

Prefer an already established package manager. Do not install a new package
manager merely to install one prerequisite without presenting that additional
choice to the user.

## Agent-owned deferred handoff

The normal install and upgrade path is software-owned. After the agent creates
and the user approves the immutable plan, the agent discovers every live
same-user process for the reload-required targets, classifies transient
clients/proxies separately from persistent managed Codex app-server
daemon/helpers, and invokes `install defer` with the reviewed journal/digest
and one repeatable `--target-pid` per exact process. A managed group also uses
one `--managed-codex-daemon`, one or more `--managed-codex-client`, and any
`--managed-codex-member` bindings for the same reviewed target name. Before
arming, both agent and recorder must prove the exact daemon executable,
pathname identity, target home, running native-control status, reported CLI and
app-server versions, same-user ownership, and at least one transient client.
The user never opens Terminal, copies a command, finds a PID, or runs apply,
verify, status, cancel, or rollback.

`install defer` does not return an armed result until its detached worker has
validated the private request, plan digest, exclusive job ownership, and every
target process identity. Its single `DEFERRED_INSTALL_ARMED` receipt names the
private status-report filename without exposing absolute paths or PIDs. Only
then does the agent ask the user to close affected hosts once and wait its
announced short settling interval before reopening once. An unaffected agent or
host-owned observer may poll `install deferred-status`, but is optional. The
first reopened agent must read the saved status before any other work. A
detected premature same-image relaunch, PID reuse ambiguity, missing identity,
drift, timeout, or worker loss fails closed and never becomes a verified
receipt.

The worker waits until every bound transient client/proxy and ordinary passive
target exits. A nonempty daemon backend selects the exact captured executable's
native stop with exact `CODEX_HOME`, no shell, and a fixed platform system path.
A running version response without `backend` is not native-stop proof. On Linux
only, the reviewed legacy bridge requires pidfd support, an exact same-user
process incarnation, and explicit required feature enables. It sends graceful
`SIGTERM` through the pidfd—never a bare PID or `SIGKILL`—waits for all bound
daemon/helpers, runs Codex's own bootstrap with the reviewed features, requires
a nonempty managed backend, and uses Codex's native stop before transactional
apply. Native-stop, migration, or exit-timeout failure remains unapplied.

The worker closes inherited standard streams, inherits no application
credential intentionally, has a bounded 1-through-604800-second user wait
(86400 seconds by default), and writes only canonical bounded private status.
It is one-shot and nonpersistent, so an OS reboot ends it and requires
agent-owned replan and rearm; the user only repeats the close/reopen boundary
and never opens Terminal. Never redirect the user to SSH or a server Terminal
when topology or native control cannot be proven; fail before the close request
instead. When a strict receipt for the exact job and plan digest proves no
mutation, `deferred-status` may report the saved categorical failure even if
the reboot changed volatile filesystem device identity. This read-only fallback
never authorizes apply, trust review, activation, or success. Native survival,
identity, and managed-control behavior must be proven on each claimed platform;
a simulated branch is not native evidence.

## macOS

- Recorder state defaults to
  `~/Library/Application Support/HolySkills/DeliveryEfficiency` for the actual
  OS account running the configured clients.
- The Codex CLI can be installed through its current official npm instructions;
  the desktop app may carry a different bundled Codex binary and home.
- Claude's supported native installer or Homebrew cask can install Claude Code.
  Fully restart desktop and CLI processes after recorder changes.
- Enumerate app-specific homes explicitly. Sandboxed desktop processes may
  override `HOME`; do not reuse the terminal home by assumption.
- Claude's default user settings home is `~/.claude`, unless the exact process
  sets `CLAUDE_CONFIG_DIR`.
- Before the ready handshake, bind each supplied PID to the same account UID,
  executable path, and libproc process-start identity. The detached macOS
  worker must survive the arming process and its terminal/session ending.
  Recheck process identity and same-image relaunch immediately before apply.
- When the app-server is managed, bind desktop/client connections as transient
  clients and prove the exact bundled or installed Codex executable's native
  daemon version/stop capability under that target's real `CODEX_HOME`; never
  substitute `kill`, `launchctl`, or a Terminal command.

## Linux

- Recorder state defaults to
  `${XDG_STATE_HOME:-$HOME/.local/state}/holyskills/delivery-efficiency`.
- Install Python through the distribution's supported packages or Python's
  official distribution, then recheck that the selected executable is 3.9+.
- Use the current official Codex and Claude Code installation methods. Keep the
  recorder state and runtime homes owned by the user running those clients.
- Resolve `CODEX_HOME` and `CLAUDE_CONFIG_DIR` from the exact target process
  before falling back to `~/.codex` and `~/.claude`.
- Bind each supplied PID to the same UID, `/proc/<pid>/stat` start time, and the
  `/proc/<pid>/exe` path plus device/inode identity before acknowledging ready.
  The worker runs in a detached session with closed standard streams. Treat a
  changed PID identity as exit of the original instance, then reject a detected
  matching-image relaunch before apply.
- A remote macOS client disconnect may leave a durable Linux app-server and
  helpers. Bind the proxy, persistent app-server, and every owned helper
  separately. Require a nonempty reported backend before native daemon stop.
  If the macOS remote client created legacy `app-server --listen unix://`
  without a backend, require Linux pidfd APIs, bind `code_mode_host`, gracefully
  terminate only the exact reviewed process through its pidfd after the proxy
  exits, then require Codex bootstrap to establish a managed backend. Never ask
  the user to SSH into the VPS or run a server-side command.

## WSL

- Treat WSL as Linux, not as native Windows. Install and launch Linux Codex,
  Claude, and Python inside the WSL distribution when those WSL runtimes are
  the targets.
- Prefer a canonical repository clone on the WSL Linux filesystem. A checkout
  on a Windows-mounted path may be the explicit `--source-root` only when the
  user deliberately chose it as canonical, every source component passes the
  installer's link/reparse checks, and the reviewed digest remains byte-stable
  through apply. Never place recorder state, runtime homes, the installed
  runtime, or the selected Python executable under `/mnt/*`.
- Keep recorder state on the WSL Linux filesystem. Reject `/mnt/*`, UNC, and
  `\\wsl$` state locations.
- Do not point WSL hooks at a native-Windows recorder, Python executable,
  runtime home, or state directory. Configure native Windows separately.
- Discover and bind Linux PIDs inside the exact WSL distribution. A native
  Windows PID or process image is never WSL process evidence. Use the Linux
  `/proc` identity and detached-session rules above and save the handoff receipt
  only in the WSL Linux state directory.

## Native Windows

- Recorder state defaults to
  `%LOCALAPPDATA%\HolySkills\DeliveryEfficiency`.
- Default runtime homes are `%USERPROFILE%\.codex` and
  `%USERPROFILE%\.claude` unless the exact target process sets `CODEX_HOME` or
  `CLAUDE_CONFIG_DIR`.
- Use an absolute `python.exe` 3.9+ path and PowerShell-native absolute home,
  journal, executable, and state paths.
- Use the current official Codex installation method. Claude Code's official
  native installer or WinGet package is supported; Git for Windows is useful
  for Claude's Bash tool but is not required by the recorder itself.
- Run installer arguments as a PowerShell array or ordinary quoted arguments;
  do not translate POSIX quoting literally. WSL remains a separate target.
- Before acknowledging ready, bind each PID to the invoking user's owner SID,
  process-creation FILETIME, and exact process image. Launch the worker without
  a console and detached from the arming process; if the host job boundary does
  not allow the worker to survive, fail before asking the user to close
  anything. Recheck the exact identities and detected same-image relaunches
  before apply. The private request and receipt remain under the selected local
  state directory and inherit its ACL; do not claim stronger ACL hardening.
- For a managed app-server, require the exact Windows Codex executable's native
  daemon control to pass under the target `CODEX_HOME`. The worker uses an argv
  array without a console or shell; never substitute `taskkill`, a service stop,
  or a PowerShell command supplied to the user.

## Missing-software decision

Before installing a missing runtime or interpreter, state its exact name and
role, selected official distribution, version/channel, install scope, update
behavior, privileges, path impact, and uninstall method. If the user's request
already explicitly includes prerequisite installation, proceed with the
verified selected method; otherwise obtain approval first.
