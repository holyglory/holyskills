# Claude Code Repo Instructions

Universal cross-runtime policy lives in
`reference/codex-app-wide/AGENTS.md` and is loaded by Claude Code through its
user-level canonical policy target. This repository's narrower policy lives in
root `AGENTS.md` and is the only project import below. Codex receives the same
pair through its global policy symlink and repository discovery. Keep the two
`AGENTS.md` sources authoritative rather than copying or re-importing their
rules here. Before consequential work, confirm the user-level memory loaded the
canonical universal file. If it did not, read
`reference/codex-app-wide/AGENTS.md` directly for this session and report the
global-policy installation or activation gap.

@AGENTS.md
