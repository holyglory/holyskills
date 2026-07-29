"""Portable delivery-efficiency recorder shared by Codex and Claude Code."""

SCHEMA_VERSION = "1.1"
RECORDER_VERSION = "0.2.1"
ADAPTER_VERSION = "0.2.1"

# Codex kills a command hook after the configured host timeout.  Runtime-owned
# telemetry uses a smaller end-to-end budget so interpreter startup, bounded
# input/output, and host scheduling retain explicit headroom.
CODEX_HOOK_TIMEOUT_SECONDS = 3
CODEX_HOOK_RUNTIME_MARGIN_SECONDS = 0.75
CODEX_HOOK_TELEMETRY_BUDGET_SECONDS = (
    CODEX_HOOK_TIMEOUT_SECONDS - CODEX_HOOK_RUNTIME_MARGIN_SECONDS
)

# Claude Code allows a much larger per-command hook timeout.  The managed
# handler requests ten seconds and its telemetry budget keeps a doubled
# runtime margin so a cold receiver start never risks the host's limit.
CLAUDE_HOOK_TIMEOUT_SECONDS = 10
CLAUDE_HOOK_TELEMETRY_BUDGET_SECONDS = (
    CLAUDE_HOOK_TIMEOUT_SECONDS - 2 * CODEX_HOOK_RUNTIME_MARGIN_SECONDS
)

# SessionStart may need to cold-start the receiver and obtain an opaque
# declaration binding.  Ordinary Claude hooks are latency-sensitive runtime
# observations and use the same tight bound as Codex instead of holding tool or
# display progress behind a ten-second telemetry timeout.
CLAUDE_ORDINARY_HOOK_TIMEOUT_SECONDS = CODEX_HOOK_TIMEOUT_SECONDS
CLAUDE_ORDINARY_HOOK_TELEMETRY_BUDGET_SECONDS = (
    CLAUDE_ORDINARY_HOOK_TIMEOUT_SECONDS - CODEX_HOOK_RUNTIME_MARGIN_SECONDS
)

# UserPromptSubmit is on the user's interactive prompt path and therefore has
# a materially tighter bound than asynchronous/background Claude hooks.  Its
# recorder budget leaves 250 ms of explicit host/interpreter scheduling
# headroom inside Claude's one-second command-hook timeout.
CLAUDE_PROMPT_HOOK_TIMEOUT_SECONDS = 1
CLAUDE_PROMPT_HOOK_TELEMETRY_BUDGET_SECONDS = 0.75
