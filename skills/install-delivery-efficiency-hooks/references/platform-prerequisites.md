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

## Linux

- Recorder state defaults to
  `${XDG_STATE_HOME:-$HOME/.local/state}/holyskills/delivery-efficiency`.
- Install Python through the distribution's supported packages or Python's
  official distribution, then recheck that the selected executable is 3.9+.
- Use the current official Codex and Claude Code installation methods. Keep the
  recorder state and runtime homes owned by the user running those clients.
- Resolve `CODEX_HOME` and `CLAUDE_CONFIG_DIR` from the exact target process
  before falling back to `~/.codex` and `~/.claude`.

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

## Missing-software decision

Before installing a missing runtime or interpreter, state its exact name and
role, selected official distribution, version/channel, install scope, update
behavior, privileges, path impact, and uninstall method. If the user's request
already explicitly includes prerequisite installation, proceed with the
verified selected method; otherwise obtain approval first.
