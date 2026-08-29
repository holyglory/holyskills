# Journey, Theme, And Changed-Review Contract

Use this reference when preparing a formal Web UI verifier configuration or
finalizing its visual review. Every target—including login, utility, and
component-demo targets—needs a complete contract. A bare `--url` intentionally
fails target coverage.

## Complete Target Example

```json
{
  "repoRoot": "/absolute/path/to/repository",
  "targets": [{
    "name": "accounts",
    "url": "http://127.0.0.1:3000/accounts",
    "journeys": [
      {
        "id": "view-accounts",
        "name": "View and manage accounts",
        "frequencyPercent": 99,
        "risk": "normal",
        "rationale": "Normal destination use"
      },
      {
        "id": "add-account",
        "name": "Add an account",
        "frequencyPercent": 1,
        "risk": "normal",
        "rationale": "Occasional creation"
      }
    ],
    "primaryJourney": "view-accounts",
    "regions": [
      {
        "name": "Account collection",
        "selector": "[data-ui-region='accounts']",
        "role": "primary-content",
        "journey": "view-accounts"
      },
      {
        "name": "Compact account tools",
        "selector": "[data-ui-region='account-tools']",
        "role": "supporting"
      }
    ],
    "theme": "light",
    "reviewInputs": [
      {"path": "src/accounts", "kind": "ui-code"},
      {"path": "src/styles/accounts.css", "kind": "style"},
      {"path": "src/design/tokens.css", "kind": "tokens"},
      {"path": "public/account-icons", "kind": "asset"}
    ],
    "states": [{
      "name": "add-account-open",
      "actions": [{"action": "click", "selector": "[data-action='add-account']"}],
      "primaryJourney": "add-account",
      "priorityOverrideReason": "The user explicitly activated account creation",
      "regions": [{
        "name": "Add account dialog",
        "selector": "[role='dialog'][data-purpose='add-account']",
        "role": "primary-content",
        "journey": "add-account"
      }],
      "continuation": {
        "kind": "in-page",
        "anchor": "[role='dialog'][data-purpose='add-account'] h2",
        "focusWithin": "[role='dialog'][data-purpose='add-account']",
        "maxScrollDelta": 8
      }
    }]
  }],
  "viewports": [
    {"name": "mobile", "width": 390, "height": 844},
    {"name": "desktop", "width": 1440, "height": 900}
  ]
}
```

`targetDefaults` may provide the same fields for coordinator-discovered or
repeated fixture targets, but every effective target/state still must resolve a
complete contract.

## Journey And Region Rules

- Journey IDs are stable. Each definition includes `frequencyPercent` and
  `risk` (`critical`, `high`, `normal`, or `low`).
- Exactly one `primaryJourney` owns each target/state. If it is not the
  highest-frequency journey, provide `priorityOverrideReason`; rare urgent work
  can legitimately be primary, but the decision must be explicit.
- `primary-content` is the named destination object or current task.
- `workflow-surface` is another journey such as create, edit, configuration,
  or administration. A lower-priority workflow before primary content fails.
- `supporting` is a compact title, search, filter, sort, or toolbar. When it
  consumes more than a compact share before primary content, it fails.
- `blocking-alert` may precede primary content only with a non-empty reason.
- Product/journey documentation defines these semantic roles. The verifier
  configuration maps them to exact selectors; do not put CSS selectors into
  product intent merely to satisfy the tool.

## Continuation Rules

Every state containing an activating click, press, check, uncheck, or selection
declares `continuation`.

- `in-page`: the anchor must be visible in the user's current viewport, focus
  must be inside `focusWithin`, and document movement must stay within
  `maxScrollDelta` (8 CSS pixels by default). A modal, mobile sheet, or nearby
  expansion can pass; a form appended below a long collection fails.
- The anchor is the revealed heading or first field. A custom component may
  mark an equivalent recognizable element with `data-ui-continuation-anchor`;
  using a broad container merely because it intersects the viewport fails.
- `navigation`: set `expectedPath`. The destination must stay on the expected
  origin and render the declared anchor in its initial viewport. Focus is not
  required merely because a new document loaded.
- `triggerActionIndex` identifies the action immediately before which the
  verifier records the user's current scroll position. It defaults to the last
  action.

## Theme And Palette Rules

- Every target/state declares `light`, `dark`, or `mixed` theme intent.
- WCAG 2.2 AA text thresholds are critical: 4.5:1 for normal text and 3:1 for
  rendered large text. Use `allowContrast` or
  `data-ui-allow-contrast="reason"` only for a documented inactive,
  incidental, decorative, or logo exception.
- A 24×24 visible-surface sample blocks a large contradiction of declared
  light/dark intent. Use `themeExceptions` or
  `data-ui-theme-exception="reason"` for an intentional local exception.
- High-chroma surface coverage, four or more prominent accent-hue clusters,
  gradients, media, and unmeasurable compositing are warnings for screenshot
  review. They are not automatic claims that a palette is ugly.

## Review Inputs And Evidence

- `repoRoot` is explicit and canonical. Each `reviewInputs` entry is a
  repository-relative regular file or directory. Missing, empty, external, or
  symlinked inputs fail coverage.
- Inputs identify only UI code, styles, tokens, fonts, assets, and genuinely
  shared presentation files that can change that target/state. Do not include
  the entire repository merely to avoid mapping ownership.
- Every checked cell produces a redacted initial-viewport PNG and full-page
  PNG. Native control values, placeholders, selected labels, and declarative
  fill payloads are removed or masked. Add `screenshotMasks` with a reason for
  other sensitive regions.
- Screenshot SHA-256 values bind evidence integrity only. Pixel changes never
  enter the manual-review queue.

## Changed Visual Review

After the formal verifier and all other automatic tests finish, read only
`review-queue.json`. Open both images for each queued cell, record decisions in
a small JSON artifact, and finalize the immutable reviewed manifest:

```json
{
  "decisions": [
    {
      "reviewCellKey": "key from review-queue.json",
      "decision": "pass",
      "note": ""
    }
  ]
}
```

```bash
python3 "$FORMAL_WEB_UI_SKILL_DIR/scripts/formal_web_ui_review.py" \
  --report /path/report.json \
  --queue /path/review-queue.json \
  --decisions /path/decisions.json \
  --out /path/manual-review.json
```

Use `gap` or `blocked` with a concrete note when appropriate. The finalizer
returns `1` while any decision blocks delivery and `2` for an invalid or
tampered evidence chain.

Supply a prior reviewed manifest explicitly on the next run:

```bash
node "$FORMAL_WEB_UI_SKILL_DIR/scripts/formal_web_ui_verify.mjs" \
  --config formal-web-ui.json \
  --review-against /path/prior-manual-review.json
```

Unchanged prior passes and gaps are carried without reopening their images;
gaps remain blocking. New cells and changed review-input or intent fingerprints
enter the queue. When a previously reviewed cell is deliberately removed,
declare its key and reason under `reviewRemovedCells`; silent removal fails
coverage.
