# Formal Web UI Verification

This skill runs a deterministic Playwright/Chromium heuristic over rendered
web pages. It measures DOM geometry, computed visibility, clipping, occlusion,
off-canvas controls, broken media, contrast risks, document overflow, and
visible scrollbars. It traverses discoverable open shadow roots, evaluates
Playwright-reachable frames, supports mobile device descriptors, and can open
declared interaction states with bounded actions. It complements screenshots
and human review; it cannot discover closed shadow roots or prove undeclared UI
states correct, and it reports reachable contexts it cannot evaluate as
coverage limits.

Run the self-test before relying on it:

```bash
python3 skills/formal-web-ui-verification/scripts/self_test.py
```

Verify explicit targets with JSON evidence:

```bash
node skills/formal-web-ui-verification/scripts/formal_web_ui_verify.mjs \
  --url http://127.0.0.1:3000/ \
  --viewport mobile=390x844 \
  --viewport desktop=1440x900 \
  --json-out /tmp/formal-web-ui.json \
  --fail-on critical
```

Exit codes:

- `0`: required pages were checked and no configured finding threshold failed.
- `1`: blocking UI findings were detected.
- `2`: configuration, browser, or dependency setup failed.
- `3`: a required target could not be checked or the minimum checked-page count was not met.

Explicit target failures are fail-closed. Coordinator-discovered failures can
be tolerated only with the explicit `--allow-discovered-target-failures` flag,
and remain visible in the report.
