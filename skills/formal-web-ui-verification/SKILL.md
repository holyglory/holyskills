---
name: formal-web-ui-verification
description: Run deterministic browser-side formal verification of rendered web UI geometry, visibility, text fit, overlap, media health, and area-of-interest boundaries. Use when Codex implements, changes, audits, or validates frontend/web UI and needs software-detectable evidence for cropped text, hidden content, off-canvas controls, unintended overlap, broken media, invisible text, document overflow, or noisy visual-test misses across desktop and mobile viewports.
---

# Formal Web UI Verification

## Overview

Use this skill to verify rendered web interfaces with DOM geometry and computed
style measurements instead of relying only on screenshots or model vision. The
bundled verifier injects JavaScript into real pages through Playwright, checks
desktop and mobile viewports, emits JSON plus Markdown evidence, and exits
nonzero only when findings meet the configured severity threshold.
Every run inventories visible/active document and element scrollbars in the
report, even when the page has no critical layout findings.

This is a formal verification layer, not a replacement for human visual
judgment. Use it before reporting changed web UI as done, and include its
critical findings in the implementation or audit result.

## Quick Start

Resolve the skill directory and run the self-test before relying on the
verifier in a new environment:

```bash
FORMAL_WEB_UI_SKILL_DIR="${FORMAL_WEB_UI_SKILL_DIR:-$HOME/.codex/skills/formal-web-ui-verification}"
python3 "$FORMAL_WEB_UI_SKILL_DIR/scripts/self_test.py"
```

Verify explicit routes:

```bash
node "$FORMAL_WEB_UI_SKILL_DIR/scripts/formal_web_ui_verify.mjs" \
  --url "http://127.0.0.1:3000/" \
  --viewport mobile=390x844 \
  --viewport desktop=1440x900 \
  --json-out /tmp/formal-web-ui-report.json \
  --markdown-out /tmp/formal-web-ui-report.md \
  --fail-on critical
```

Verify healthy coordinator-managed web URLs without starting duplicate servers:

```bash
PROJECT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
node "$FORMAL_WEB_UI_SKILL_DIR/scripts/formal_web_ui_verify.mjs" \
  --from-coordinator \
  --coordinator-script "$PROJECT_ROOT/skills/codex-dev-coordinator/scripts/dev_coordinator.py" \
  --only-current \
  --fail-on critical
```

## Workflow

1. **Find a safe render path**
   - Prefer a test, fixture, Storybook, preview, or coordinator-managed local
     dev URL.
   - Before starting, stopping, or replacing a dev server, use
     `codex-dev-coordinator`.
   - Do not use production or side-effecting flows unless the user explicitly
     asked for them and the route is safe to inspect.

2. **Run the formal verifier**
   - Check at least one narrow/mobile viewport and one desktop viewport for web
     UI changes.
   - Use `--from-coordinator --only-current` only for already-running current
     coordinator URLs. Stopped, stale, reused-port, non-HTML, and 4xx URLs
     should be recorded as skipped evidence, not as UI failures.
   - Keep `--fail-on critical` as the default for low-noise delivery gates.
     Use stricter settings only when the project asks for warning-level gates.

3. **Interpret findings**
   - Treat `critical` as blockers before delivery.
   - Treat `warning` as review evidence: fix when relevant to the journey, or
     document why it is acceptable.
   - Do not suppress a finding globally just to pass. Per-target ignores or
     allowances must name a selector and a reason.

4. **Report evidence**
   - Include the command, output paths, checked URLs, viewports, skipped URLs,
     and critical findings count.
   - If no safe render path exists, report that formal verification is blocked
     and add the missing Playwright, Storybook, fixture route, or preview path
     to the implementation plan.

## Default Rule Set

Critical findings by default:

- Document horizontal overflow.
- Visible leaf text or controls clipped by `overflow: hidden` or `clip` without
  a scroll path or explicit truncation allowance.
- Unrelated overlap/occlusion of meaningful text or controls.
- Focusable or interactive controls outside the viewport or configured area of
  interest.
- Broken visible images/media.
- Text with effectively invisible foreground/background contrast.

Warnings by default:

- Visible/active scrollbars are always reported in `metrics.visibleScrollbars`
  and the Markdown `Visible Scrollbars` section; they are not failures by
  themselves unless they also cause overflow, clipping, or area violations.
- Small interactive targets.
- Intentional single-line ellipsis or allowed truncation.
- Low contrast that is risky but not effectively invisible.
- Broad container overflow that may belong to charts, maps, canvases, or other
  complex artifacts.

## Areas, Ignores, And Allowances

Prefer attributes in source or fixture markup when the policy should travel
with the component:

```html
<section data-ui-verify-area="editor-preview">
  <button>Save</button>
</section>

<span data-ui-allow-truncation="filename may ellipsize">very-long-file-name.pdf</span>
<div data-ui-allow-overlap="intentional floating toolbar">...</div>
<div data-ui-verify-ignore="third-party map internals">...</div>
```

Use a config file when allowances are route-specific:

```json
{
  "targets": [{"url": "http://127.0.0.1:3000/dashboard"}],
  "viewports": [{"name": "mobile", "width": 390, "height": 844}],
  "areas": [{"name": "main", "selector": "main"}],
  "ignore": [{"selector": ".third-party-map", "reason": "vendor map internals"}],
  "allowTruncation": [{"selector": ".filename", "reason": "intentional ellipsis"}],
  "allowOverlap": [{"selector": ".floating-toolbar", "reason": "intentional overlay"}],
  "rules": {"failOn": "critical", "strictTruncation": false}
}
```

## Completion Rules

- Do not report changed web UI as verified if the formal verifier found
  unresolved critical findings on the relevant desktop or mobile route.
- Do not treat screenshots alone as formal evidence for clipped text, overlap,
  off-canvas controls, or invisible text when this verifier can run.
- Keep generated reports outside the product repo unless the user asks to save
  them there.
