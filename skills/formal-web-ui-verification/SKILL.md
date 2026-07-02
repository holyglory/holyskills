---
name: formal-web-ui-verification
description: Run deterministic browser-side formal verification of rendered web UI geometry, visibility, text fit, overlap, media health, and area-of-interest boundaries. Use when a coding agent (Codex, Claude Code) implements, changes, audits, or validates frontend/web UI and needs software-detectable evidence for cropped text, hidden content, off-canvas controls, unintended overlap, broken media, invisible text, document overflow, or noisy visual-test misses across desktop and mobile viewports.
---

# Formal Web UI Verification

## Overview

Use this skill to verify rendered web interfaces with DOM geometry and computed
style measurements instead of relying only on screenshots or model vision. The
bundled verifier injects JavaScript into real pages through Playwright, checks
desktop and mobile viewports, emits JSON plus Markdown evidence, and exits
nonzero only when findings meet the configured severity threshold.
Text detection covers any element that directly owns rendered text (including
`div`-based layouts), not just classic heading/paragraph tags, and clipping
checks cover both self-overflow and cuts made by ancestor `overflow` clipping
(absolute children, negative offsets, parent crops). By default it runs a
full-page scroll pass before measuring so below-the-fold and lazy-loaded
content is exercised. Every run inventories visible/active document and
element scrollbars, records contrast it could not measure against a solid
background, counts shadow roots and iframes it did not inspect, and lists
allowed ellipsis/line-clamp truncations, hidden text-like elements, and
still-loading media, even when the page has no critical layout findings.

This is a formal verification layer, not a replacement for human visual
judgment. Use it before reporting changed web UI as done, and include its
critical findings in the implementation or audit result.

## Quick Start

Resolve the skill directory from the loaded skill path and run the self-test
before relying on the verifier in a new environment. When the loaded path is
not known, fall back to the runtime's skill home (`~/.codex/skills` for Codex,
`~/.claude/skills` for Claude Code):

```bash
FORMAL_WEB_UI_SKILL_DIR="${FORMAL_WEB_UI_SKILL_DIR:-$HOME/.codex/skills/formal-web-ui-verification}"
[ -d "$FORMAL_WEB_UI_SKILL_DIR" ] || FORMAL_WEB_UI_SKILL_DIR="$HOME/.claude/skills/formal-web-ui-verification"
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
   - The verifier scrolls the full page top-to-bottom before measuring so
     below-the-fold and lazy-loaded content is exercised; how far it scrolled is
     reported in `metrics.scroll`. Pass `--no-scroll` (or `"scroll": false` in a
     config) only when the page must not scroll during inspection.
   - Use `--from-coordinator --only-current` only for already-running current
     coordinator URLs. Stopped, stale, reused-port, non-HTML, and 4xx URLs
     should be recorded as skipped evidence, not as UI failures.
   - Keep `--fail-on critical` as the default for low-noise delivery gates.
     Use stricter settings only when the project asks for warning-level gates.

3. **Interpret findings**
   - Treat `critical` as blockers before delivery.
   - Treat `warning` as review evidence: fix when relevant to the journey, or
     document why it is acceptable.
   - `unmeasurable-contrast` and `not-inspected` are always warnings, never
     criticals: they mark coverage gaps (gradient/image or translucent
     backgrounds; uninspected shadow roots and iframes). Review those elements
     visually rather than trusting a pass.
   - `clipped-hidden`, `offcanvas-hidden`, and `fixed-offscreen-hidden` mark
     content that is fully invisible in a way that is often intentional
     (closed accordions, offscreen slides/drawers, skip links). When the
     hidden element belongs to the journey under verification, confirm the
     state is intentional instead of treating the warning as noise.
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

- Document horizontal overflow (`document-horizontal-overflow`).
- Text/controls clipped by their own `overflow: hidden`/`clip`
  (`clipped-x`/`clipped-y`) without a scroll path or explicit allowance.
- Text/controls partially cut by an ancestor's `overflow: hidden`/`clip`
  (`clipped-by-ancestor`): absolute children sticking out of cropped
  containers, negative-margin cuts, nowrap text spilling into a clipping
  parent. Scrollable ancestors on the cut axis count as a reachability path and
  do not fail. Inside carousel/slider-marked containers the finding is
  downgraded to a warning; fully hidden content becomes a `clipped-hidden`
  warning because closed accordions/tabs/slides are often intentional.
- Unrelated overlap/occlusion of meaningful text or controls: fully covered
  (`occluded`) or covered on ≥60% of sampled points (`partially-occluded`).
  Elements already in the viewport are checked at their natural on-screen
  position; only off-screen elements are scrolled into view first and their
  findings are tagged `measuredAfterScroll`. A near-transparent occluder is
  downgraded to a warning.
- Text/controls partially cut by an unreachable edge: before the document
  origin (`offcanvas-cut`), fixed-position content cut by the viewport
  (`fixed-offscreen-cut`), or interactive controls beyond the horizontal
  document scroll range (`interactive-offscreen-x`).
- Controls or text outside a configured area of interest (`outside-area`).
- Broken images/videos (`broken-image`/`broken-video`), including broken
  images that collapsed to ~0x0 because their source failed.
- Text with effectively invisible foreground/background contrast against a
  genuine solid background (`invisible-text`). When the effective background is
  a gradient, image, or translucent stack, contrast is not computed against
  white; the element is recorded in `metrics.unmeasurableContrast` and reported
  only as a warning.

Warnings by default:

- Visible/active scrollbars are always reported in `metrics.visibleScrollbars`
  and the Markdown `Visible Scrollbars` section; they are not failures by
  themselves unless they also cause overflow, clipping, or area violations.
- Coverage gaps are always reported in the Markdown `Coverage & Unmeasurable`
  section: `metrics.unmeasurableContrast`, `metrics.notInspected`
  (`shadowRoots`/`iframes` counted but not traversed, raising a `not-inspected`
  warning), `metrics.ellipsisTruncations` (allowed single-line ellipsis and
  line-clamp truncations), `metrics.hiddenTextLike` (text/controls present in
  the DOM but not rendered), and `metrics.pendingMedia` (media still loading at
  measurement time).
- Fully hidden clipped content (`clipped-hidden`), fully offscreen
  fixed/static content (`fixed-offscreen-hidden`/`offcanvas-hidden` — the
  skip-link/visually-hidden pattern), and carousel-context cuts.
- Partial overlap below the 60% threshold (`partially-occluded` with ≥2 covered
  sample points).
- Small interactive targets (`tiny-interactive-target`).
- Explicitly allowed truncation (`allowed-truncation`).
- Low contrast that is risky but not effectively invisible
  (`low-contrast-risk`).
- Broad container overflow that belongs to charts, maps, canvases, or other
  complex artifacts (`complex-artifact-overflow`). Artifact detection is
  token-bounded: an ancestor must be a real `svg`/`canvas`, match a known
  map/chart library token (leaflet, mapbox, recharts, echarts, plotly, …), or
  carry a generic map/chart token while actually containing a substantial
  svg/canvas/video. Sections merely named `roadmap`, `sitemap`, or similar are
  NOT excluded from checks.
- Findings are capped at 40 per rule per page; a `findings-truncated` warning
  with per-rule suppressed counts is emitted when the cap is hit, so mass
  breakage cannot silently vanish from the report.

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
  "scroll": true,
  "rules": {"failOn": "critical", "strictTruncation": false}
}
```

Set `"scroll": false` (or pass `--no-scroll`) to disable the full-page scroll
pass when a page must not scroll during inspection.

## Completion Rules

- Do not report changed web UI as verified if the formal verifier found
  unresolved critical findings on the relevant desktop or mobile route.
- Do not treat screenshots alone as formal evidence for clipped text, overlap,
  off-canvas controls, or invisible text when this verifier can run.
- Keep generated reports outside the product repo unless the user asks to save
  them there.
