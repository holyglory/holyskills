#!/usr/bin/env python3
"""Self-tests for the formal web UI verifier."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "scripts" / "formal_web_ui_verify.mjs"
TIMEOUT_SECONDS = int(os.environ.get("FORMAL_WEB_UI_SELF_TEST_TIMEOUT", "45"))
KEEP_TEMP = os.environ.get("FORMAL_WEB_UI_SELF_TEST_KEEP_TEMP", "").lower() in {"1", "true", "yes", "on"}


def write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def page(body: str, css: str = "") -> str:
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>formal fixture</title>
  <style>
    body {{ margin: 0; font: 16px system-ui, sans-serif; background: #fff; color: #111; }}
    main {{ padding: 20px; }}
    {css}
  </style>
</head>
<body>
  <main>
    {body}
  </main>
</body>
</html>
"""


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


class Server:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.previous = Path.cwd()
        os.chdir(root)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self) -> str:
        port = self.httpd.server_address[1]
        return f"http://127.0.0.1:{port}"

    def close(self) -> None:
        self.httpd.shutdown()
        self.thread.join(timeout=5)
        os.chdir(self.previous)


def node_binary() -> str:
    return os.environ.get("FORMAL_WEB_UI_NODE") or shutil.which("node") or "node"


def verifier_env() -> dict[str, str]:
    env = os.environ.copy()
    bundled_node_modules = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules"
    if bundled_node_modules.is_dir():
        env["NODE_PATH"] = str(bundled_node_modules) + (os.pathsep + env["NODE_PATH"] if env.get("NODE_PATH") else "")
    return env


def run_verifier_command(cmd: list[str], json_out: Path, *, expect: int) -> dict:
    result = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=TIMEOUT_SECONDS,
        env=verifier_env(),
    )
    if result.returncode != expect:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise AssertionError(f"Expected exit {expect}, got {result.returncode}: {' '.join(cmd)}")
    if not json_out.exists():
        raise AssertionError("Verifier did not write JSON report")
    return json.loads(json_out.read_text(encoding="utf-8"))


def run_verify(url: str, out: Path, *, expect: int, extra: list[str] | None = None) -> dict:
    json_out = out / "report.json"
    md_out = out / "report.md"
    cmd = [
        node_binary(),
        str(VERIFY),
        "--url",
        url,
        "--viewport",
        "mobile=390x844",
        "--json-out",
        str(json_out),
        "--markdown-out",
        str(md_out),
        "--fail-on",
        "critical",
    ]
    if extra:
        cmd.extend(extra)
    return run_verifier_command(cmd, json_out, expect=expect)


def run_verify_config(config: dict, out: Path, *, expect: int) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    json_out = out / "report.json"
    md_out = out / "report.md"
    config_path = out / "formal-web-ui.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    cmd = [
        node_binary(),
        str(VERIFY),
        "--config",
        str(config_path),
        "--json-out",
        str(json_out),
        "--markdown-out",
        str(md_out),
        "--fail-on",
        "critical",
    ]
    return run_verifier_command(cmd, json_out, expect=expect)


def finding_rules(report: dict) -> set[str]:
    return {item["rule"] for item in report.get("findings", [])}


def assert_rules(report: dict, *rules: str) -> None:
    present = finding_rules(report)
    missing = set(rules) - present
    if missing:
        raise AssertionError(f"Missing expected rules {sorted(missing)}; present={sorted(present)}")


def assert_no_critical(report: dict) -> None:
    critical = [item for item in report.get("findings", []) if item.get("severity") == "critical"]
    if critical:
        raise AssertionError(f"Unexpected critical findings: {critical}")


def assert_no_rule(report: dict, rule: str) -> None:
    matches = [item for item in report.get("findings", []) if item.get("rule") == rule]
    if matches:
        raise AssertionError(f"Unexpected '{rule}' findings: {matches}")


def assert_critical_rule(report: dict, rule: str) -> None:
    matches = [
        item
        for item in report.get("findings", [])
        if item.get("rule") == rule and item.get("severity") == "critical"
    ]
    if not matches:
        present = sorted({(item.get("severity"), item.get("rule")) for item in report.get("findings", [])})
        raise AssertionError(f"Expected critical '{rule}' finding; present={present}")


def assert_warning_rule(report: dict, rule: str) -> None:
    matches = [
        item
        for item in report.get("findings", [])
        if item.get("rule") == rule and item.get("severity") == "warning"
    ]
    if not matches:
        present = sorted({(item.get("severity"), item.get("rule")) for item in report.get("findings", [])})
        raise AssertionError(f"Expected warning '{rule}' finding; present={present}")


def page_metrics(report: dict) -> list[dict]:
    return [p.get("metrics", {}) for p in report.get("pages", []) if not p.get("skipped")]


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="formal-web-ui-self-test-"))
    server = None
    try:
        fixtures = tmp / "site"
        write(fixtures / "clean.html", page("<h1>Dashboard</h1><p>Everything fits.</p><button>Save changes</button>"))
        write(
            fixtures / "clipped-button.html",
            page("<button class='bad'>Save changes now</button>", ".bad { width: 42px; overflow: hidden; white-space: nowrap; }"),
        )
        write(
            fixtures / "clipped-text.html",
            page("<p class='bad'>This paragraph is intentionally too tall for the container.</p>", ".bad { width: 180px; height: 12px; overflow: hidden; }"),
        )
        write(
            fixtures / "occluded.html",
            page("<button class='target'>Checkout</button><div class='cover'></div>", ".target { margin-top: 40px; } .cover { position: fixed; inset: 50px auto auto 20px; width: 140px; height: 50px; background: rgba(0,0,0,.85); z-index: 20; }"),
        )
        write(
            fixtures / "outside-area.html",
            page("<section data-ui-verify-area='card' class='card'><button class='bad'>Open</button></section>", ".card { position: relative; width: 120px; height: 80px; border: 1px solid #000; overflow: visible; } .bad { position: absolute; left: 150px; top: 20px; }"),
        )
        write(fixtures / "broken-image.html", page("<h1>Media</h1><img src='/missing-image.png' alt='Missing asset' width='120' height='80'>"))
        write(fixtures / "invisible-text.html", page("<p class='bad'>Invisible message</p>", ".bad { color: #fff; background: #fff; }"))
        write(
            fixtures / "lab-color.html",
            page("<button class='lab'>Save</button>", ".lab { color: white; background: lab(1.76974 1.32743 -9.28855); }"),
        )
        write(
            fixtures / "oklab-color.html",
            page("<span class='badge'>0:08</span>", ".badge { color: white; background: oklab(0.128998 -0.0038857 -0.0418156 / 0.8); }"),
        )
        write(
            fixtures / "allowed-ellipsis.html",
            page("<span class='file' data-ui-allow-truncation='filename ellipsis'>very-long-file-name-for-a-report.pdf</span>", ".file { display: block; width: 80px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }"),
        )
        write(
            fixtures / "ignored.html",
            page("<button data-ui-verify-ignore='fixture intentionally broken' class='bad'>Save changes now</button>", ".bad { width: 42px; overflow: hidden; white-space: nowrap; }"),
        )
        write(
            fixtures / "chart-overflow.html",
            page("<div class='chart'><svg width='1200' height='160'><rect width='1200' height='160' fill='#ddd'/></svg></div>", ".chart { width: 300px; height: 160px; overflow: hidden; }"),
        )
        write(
            fixtures / "scrollbars.html",
            page("<div class='scrollbox'><p>One</p><p>Two</p><p>Three</p><p>Four</p></div>", ".scrollbox { width: 180px; height: 48px; overflow-y: scroll; overflow-x: hidden; border: 1px solid #aaa; }"),
        )
        # Fix 2: white text on a gradient must NOT be a critical invisible-text finding,
        # and must be recorded under metrics.unmeasurableContrast.
        write(
            fixtures / "gradient-contrast.html",
            page(
                "<p class='hero'>Readable on a gradient</p>",
                ".hero { color: #fff; background: linear-gradient(90deg, #0a3d62, #3c6382); padding: 24px; }",
            ),
        )
        # Fix 3: a shadow-root host plus an iframe must surface metrics.notInspected and
        # emit a not-inspected warning.
        write(fixtures / "iframe-child.html", page("<p>Framed content.</p>"))
        write(
            fixtures / "shadow-iframe.html",
            page(
                "<h1>Component library</h1>"
                "<div id='host'></div>"
                "<iframe src='/iframe-child.html' width='200' height='80' title='child'></iframe>"
                "<script>"
                "const host = document.getElementById('host');"
                "const root = host.attachShadow({mode: 'open'});"
                "root.innerHTML = '<button>Inside shadow</button>';"
                "</script>",
            ),
        )
        # Fix 1: a tall lazy-load page whose below-the-fold control is only created when
        # it scrolls into view. With scrolling on it is found (and its clip is critical);
        # with --no-scroll it is never created.
        write(
            fixtures / "lazy-scroll.html",
            page(
                "<div class='spacer'>Scroll down for lazy content.</div>"
                "<div id='sentinel'></div>"
                "<div id='lazy-slot'></div>"
                "<script>"
                "const io = new IntersectionObserver((entries) => {"
                "  for (const entry of entries) {"
                "    if (entry.isIntersecting) {"
                "      const slot = document.getElementById('lazy-slot');"
                "      if (!slot.dataset.filled) {"
                "        slot.dataset.filled = '1';"
                "        slot.innerHTML = '<button class=\"lazybad\">Lazy loaded action button</button>';"
                "      }"
                "    }"
                "  }"
                "});"
                "io.observe(document.getElementById('sentinel'));"
                "</script>",
                ".spacer { height: 2400px; } "
                "#sentinel { height: 1px; } "
                ".lazybad { width: 40px; overflow: hidden; white-space: nowrap; }",
            ),
        )
        # Realistic-breakage regressions: each of these fixtures reproduces a defect
        # class the verifier previously missed entirely (agent-report 2026-07-03:
        # "doesn't report problems in most of the cases").
        write(
            fixtures / "div-clipped-ancestor.html",
            page(
                "<div class='card'><div class='title'>Monthly report</div>"
                "<div class='body'>This body text is long enough to need four lines of vertical space "
                "inside the card so the fixed card height visibly cuts the text mid-line.</div></div>",
                ".card { width: 220px; height: 58px; overflow: hidden; border: 1px solid #ccc; padding: 8px; }",
            ),
        )
        write(
            fixtures / "abs-button-cut.html",
            page(
                "<div class='panel'><button class='cta'>Confirm order</button></div>",
                ".panel { position: relative; width: 240px; height: 90px; overflow: hidden; border: 1px solid #ccc; }"
                " .cta { position: absolute; left: 170px; top: 30px; width: 140px; }",
            ),
        )
        write(
            fixtures / "negative-top-cut.html",
            page(
                "<div class='hero'><h2 class='title'>Quarterly results overview</h2></div>",
                ".hero { width: 320px; height: 80px; overflow: hidden; border: 1px solid #ccc; } .title { margin-top: -14px; }",
            ),
        )
        write(
            fixtures / "partial-overlap.html",
            page(
                "<div class='row'><span class='price'>$1,299.00</span><span class='badge'>SALE</span></div>",
                ".row { position: relative; width: 300px; height: 44px; }"
                " .price { position: absolute; left: 0; top: 8px; display: block; width: 120px; height: 20px; }"
                " .badge { position: absolute; left: 40px; top: 4px; display: block; width: 100px; height: 28px; background: #d33; color: #fff; }",
            ),
        )
        write(
            fixtures / "broken-image-collapsed.html",
            page("<h1>Product</h1><img src='/missing-photo.png' alt=''><p>Great product.</p>"),
        )
        write(
            fixtures / "roadmap-invisible.html",
            page(
                "<div class='roadmap-section'><p class='ghost'>Phase 2: launch billing</p></div>",
                ".ghost { color: #fff; background: #fff; }",
            ),
        )
        write(
            fixtures / "div-invisible-text.html",
            page("<div class='note'>Your subscription expired</div>", ".note { color: #fff; }"),
        )
        write(
            fixtures / "offcanvas-left-cut.html",
            page(
                "<button class='back'>Back to dashboard</button>",
                ".back { position: absolute; left: -60px; top: 40px; width: 180px; }",
            ),
        )
        write(
            fixtures / "fixed-toolbar-cut.html",
            page(
                "<p>Content</p><div class='toolbar'><button>Accept</button><button>Reject</button></div>",
                ".toolbar { position: fixed; left: 0; right: 0; bottom: -30px; height: 52px; background: #eee; }"
                " .toolbar button { height: 44px; }",
            ),
        )
        write(
            fixtures / "nowrap-spill-cut.html",
            page(
                "<div class='cell'><div class='val'>4111 1111 1111 1111 (Visa)</div></div>",
                ".cell { width: 120px; overflow: hidden; border: 1px solid #ccc; } .val { white-space: nowrap; }",
            ),
        )
        # Composite clean modern page: sticky header, ellipsis card titles inside
        # overflow-hidden cards, line-clamp, scrollable table, FAB, sr-only link.
        # Guards against false criticals from rule interplay (a card h3 with its own
        # ellipsis inside an overflow-hidden card once produced a false
        # clipped-by-ancestor via the scrollWidth spill extension).
        write(
            fixtures / "modern-clean.html",
            page(
                "<header class='app'><span class='logo'>Acme</span><span class='chip'>Berlin · synced</span>"
                "<nav><a href='#a'>Home</a><a href='#b'>Reports</a></nav></header>"
                "<div class='card'><h3 class='title'>Quarterly-financial-forecast-and-planning-notes.xlsx</h3>"
                "<div class='desc'>Latest revision includes the updated growth assumptions for the EMEA region and "
                "the revised hiring plan for the platform team.</div>"
                "<div class='row'><span class='chip'>Updated 2h ago</span><button>Open</button></div></div>"
                "<div class='scroll-table'><table><tr><th>Project</th><th>Owner</th><th>Status</th><th>Notes</th></tr>"
                "<tr><td>Atlas</td><td>J. Rivera</td><td>Active</td><td>Waiting on vendor quote</td></tr></table></div>"
                "<button class='fab' aria-label='New item'>+</button>"
                "<a class='sr-only' href='#main'>Skip to content</a>",
                "header.app { position: sticky; top: 0; display: flex; gap: 10px; align-items: center; background: #fff; padding: 10px; }"
                " .chip { font-size: 12px; background: #eef1f5; border-radius: 999px; padding: 4px 10px; color: #444; }"
                " .card { width: 260px; background: #fff; border: 1px solid #e3e6ea; border-radius: 10px; padding: 12px; overflow: hidden; }"
                " .card h3.title { margin: 0 0 6px; font-size: 16px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }"
                " .card .desc { color: #555; font-size: 14px; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; }"
                " .card .row { display: flex; gap: 8px; margin-top: 10px; }"
                " .scroll-table { overflow-x: auto; margin-top: 16px; } table { border-collapse: collapse; min-width: 900px; }"
                " td, th { padding: 10px 12px; white-space: nowrap; text-align: left; }"
                " .fab { position: fixed; right: 16px; bottom: 16px; width: 56px; height: 56px; border-radius: 50%; background: #2a5bd7; color: #fff; border: 0; }"
                " .sr-only { position: absolute; width: 1px; height: 1px; margin: -1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }",
            ),
        )
        # False-positive guards: common intentional patterns must not become criticals.
        write(
            fixtures / "truncate-inner-span.html",
            page(
                "<div class='cell'><span>very-long-file-name-that-should-ellipsize.pdf</span></div>",
                ".cell { width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }",
            ),
        )
        write(
            fixtures / "line-clamp.html",
            page(
                "<div class='clamp'>Long description text that wraps over many lines and is intentionally "
                "clamped to two lines with a standard line-clamp pattern used across modern apps.</div>",
                ".clamp { width: 220px; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; }",
            ),
        )
        write(
            fixtures / "carousel-peek.html",
            page(
                "<div class='swiper'><div class='track'>"
                "<div class='slide'>First slide content</div>"
                "<div class='slide'>Second slide peeks out</div>"
                "<div class='slide'>Third slide fully hidden</div>"
                "</div></div>",
                ".swiper { width: 300px; overflow: hidden; } .track { display: flex; gap: 8px; }"
                " .slide { flex: 0 0 220px; height: 80px; background: #eef; padding: 8px; }",
            ),
        )
        write(
            fixtures / "app-shell-scroll.html",
            page(
                "<div class='shell'><div class='spacer'>Top of the app shell.</div>"
                "<button class='deep'>Deep action</button></div>",
                "html, body { height: 100%; overflow: hidden; } main { padding: 0; height: 100%; }"
                " .shell { height: 100%; overflow-y: auto; } .spacer { height: 1900px; }",
            ),
        )
        write(
            fixtures / "skip-link.html",
            page(
                "<a class='skip' href='#main'>Skip to content</a><h1 id='main'>Welcome</h1>",
                ".skip { position: absolute; left: -9999px; top: 0; }",
            ),
        )
        write(
            fixtures / "fab-over-text.html",
            page(
                "<div class='msg'>A long status message pinned near the bottom of the screen.</div>"
                "<button class='fab' aria-label='Compose'>+</button>",
                ".msg { position: fixed; bottom: 10px; left: 10px; width: 300px; height: 40px; }"
                " .fab { position: fixed; bottom: 10px; left: 250px; width: 70px; height: 70px; border-radius: 50%; background: #06c; color: #fff; }",
            ),
        )
        write(
            fixtures / "accordion-closed.html",
            page(
                "<div class='acc'><p>Hidden panel content that is intentionally collapsed.</p></div><p>Visible content.</p>",
                ".acc { max-height: 0; overflow: hidden; }",
            ),
        )
        write(
            fixtures / "form-controls.html",
            page(
                "<input class='f' value='a very long value that exceeds the field width for sure'>"
                "<select><option>Pick one option here</option></select>",
                ".f { width: 120px; }",
            ),
        )
        server = Server(fixtures)

        clean = run_verify(f"{server.base_url}/clean.html", tmp / "clean", expect=0)
        assert_no_critical(clean)

        wait_for_config = run_verify_config(
            {
                "targets": [{"url": f"{server.base_url}/clean.html"}],
                "viewports": [{"name": "mobile", "width": 390, "height": 844}],
                "waitFor": {"selector": "main", "networkIdleMs": 500, "settleMs": 25},
                "rules": {"failOn": "critical"},
            },
            tmp / "wait-for-config",
            expect=0,
        )
        if not any(not page_report.get("skipped") for page_report in wait_for_config.get("pages", [])):
            raise AssertionError("Structured waitFor config skipped every page")
        assert_no_critical(wait_for_config)

        clipped_button = run_verify(f"{server.base_url}/clipped-button.html", tmp / "clipped-button", expect=1)
        assert_rules(clipped_button, "clipped-x")

        clipped_text = run_verify(f"{server.base_url}/clipped-text.html", tmp / "clipped-text", expect=1)
        assert_rules(clipped_text, "clipped-y")

        occluded = run_verify(f"{server.base_url}/occluded.html", tmp / "occluded", expect=1)
        assert_rules(occluded, "occluded")

        outside_area = run_verify(f"{server.base_url}/outside-area.html", tmp / "outside-area", expect=1)
        assert_rules(outside_area, "outside-area")

        broken_image = run_verify(f"{server.base_url}/broken-image.html", tmp / "broken-image", expect=1)
        assert_rules(broken_image, "broken-image")

        invisible_text = run_verify(f"{server.base_url}/invisible-text.html", tmp / "invisible-text", expect=1)
        assert_rules(invisible_text, "invisible-text")

        lab_color = run_verify(f"{server.base_url}/lab-color.html", tmp / "lab-color", expect=0)
        assert_no_critical(lab_color)

        oklab_color = run_verify(f"{server.base_url}/oklab-color.html", tmp / "oklab-color", expect=0)
        assert_no_critical(oklab_color)

        allowed = run_verify(f"{server.base_url}/allowed-ellipsis.html", tmp / "allowed-ellipsis", expect=0)
        assert_no_critical(allowed)

        ignored = run_verify(f"{server.base_url}/ignored.html", tmp / "ignored", expect=0)
        assert_no_critical(ignored)

        chart = run_verify(f"{server.base_url}/chart-overflow.html", tmp / "chart-overflow", expect=0)
        assert_no_critical(chart)

        scrollbars = run_verify(f"{server.base_url}/scrollbars.html", tmp / "scrollbars", expect=0)
        reported_scrollbars = [
            item
            for page_report in scrollbars.get("pages", [])
            for item in page_report.get("metrics", {}).get("visibleScrollbars", [])
        ]
        if not any(item.get("selector", "").endswith(".scrollbox") and item.get("axis") == "y" for item in reported_scrollbars):
            raise AssertionError(f"Expected .scrollbox vertical scrollbar in report, got {reported_scrollbars}")
        markdown = (tmp / "scrollbars" / "report.md").read_text(encoding="utf-8")
        if "## Visible Scrollbars" not in markdown or ".scrollbox" not in markdown:
            raise AssertionError("Markdown report did not include visible scrollbar inventory")

        # Fix 2: gradient background must not yield an invisible-text critical and must be
        # recorded as unmeasurable contrast.
        gradient = run_verify(f"{server.base_url}/gradient-contrast.html", tmp / "gradient-contrast", expect=0)
        assert_no_critical(gradient)
        assert_no_rule(gradient, "invisible-text")
        unmeasurable = [
            entry
            for metrics in page_metrics(gradient)
            for entry in metrics.get("unmeasurableContrast", [])
        ]
        if not any("gradient" in (entry.get("reason") or "") for entry in unmeasurable):
            raise AssertionError(f"Expected gradient entry in unmeasurableContrast, got {unmeasurable}")

        # Fix 3: shadow root + iframe must surface notInspected and a not-inspected warning.
        shadow = run_verify(f"{server.base_url}/shadow-iframe.html", tmp / "shadow-iframe", expect=0)
        assert_rules(shadow, "not-inspected")
        not_inspected_totals = [m.get("notInspected", {}) for m in page_metrics(shadow)]
        if not any(ni.get("shadowRoots", 0) >= 1 for ni in not_inspected_totals):
            raise AssertionError(f"Expected >=1 shadow root in notInspected, got {not_inspected_totals}")
        if not any(ni.get("iframes", 0) >= 1 for ni in not_inspected_totals):
            raise AssertionError(f"Expected >=1 iframe in notInspected, got {not_inspected_totals}")

        # Fix 1: below-the-fold lazy content is only found when scrolling is on.
        lazy_scroll_on = run_verify(f"{server.base_url}/lazy-scroll.html", tmp / "lazy-scroll-on", expect=1)
        assert_rules(lazy_scroll_on, "clipped-x")
        scroll_metrics = [m.get("scroll", {}) for m in page_metrics(lazy_scroll_on)]
        if not any((sm.get("scrolledTo") or 0) > 844 for sm in scroll_metrics):
            raise AssertionError(f"Expected scroll pass to advance beyond one viewport, got {scroll_metrics}")

        lazy_scroll_off = run_verify(
            f"{server.base_url}/lazy-scroll.html", tmp / "lazy-scroll-off", expect=0, extra=["--no-scroll"]
        )
        assert_no_critical(lazy_scroll_off)
        assert_no_rule(lazy_scroll_off, "clipped-x")

        # Realistic-breakage regressions (previously all reported zero findings).
        div_clip = run_verify(f"{server.base_url}/div-clipped-ancestor.html", tmp / "div-clipped-ancestor", expect=1)
        assert_critical_rule(div_clip, "clipped-by-ancestor")

        abs_cut = run_verify(f"{server.base_url}/abs-button-cut.html", tmp / "abs-button-cut", expect=1)
        assert_critical_rule(abs_cut, "clipped-by-ancestor")

        neg_cut = run_verify(f"{server.base_url}/negative-top-cut.html", tmp / "negative-top-cut", expect=1)
        assert_critical_rule(neg_cut, "clipped-by-ancestor")

        overlap = run_verify(f"{server.base_url}/partial-overlap.html", tmp / "partial-overlap", expect=1)
        assert_critical_rule(overlap, "partially-occluded")

        collapsed_img = run_verify(f"{server.base_url}/broken-image-collapsed.html", tmp / "broken-image-collapsed", expect=1)
        assert_critical_rule(collapsed_img, "broken-image")

        roadmap = run_verify(f"{server.base_url}/roadmap-invisible.html", tmp / "roadmap-invisible", expect=1)
        assert_critical_rule(roadmap, "invisible-text")

        div_invisible = run_verify(f"{server.base_url}/div-invisible-text.html", tmp / "div-invisible-text", expect=1)
        assert_critical_rule(div_invisible, "invisible-text")

        offcanvas = run_verify(f"{server.base_url}/offcanvas-left-cut.html", tmp / "offcanvas-left-cut", expect=1)
        assert_critical_rule(offcanvas, "offcanvas-cut")

        fixed_cut = run_verify(f"{server.base_url}/fixed-toolbar-cut.html", tmp / "fixed-toolbar-cut", expect=1)
        assert_critical_rule(fixed_cut, "fixed-offscreen-cut")

        nowrap_spill = run_verify(f"{server.base_url}/nowrap-spill-cut.html", tmp / "nowrap-spill-cut", expect=1)
        assert_critical_rule(nowrap_spill, "clipped-by-ancestor")

        modern_clean = run_verify(f"{server.base_url}/modern-clean.html", tmp / "modern-clean", expect=0)
        assert_no_critical(modern_clean)

        # False-positive guards: intentional patterns stay below critical.
        truncate_span = run_verify(f"{server.base_url}/truncate-inner-span.html", tmp / "truncate-inner-span", expect=0)
        assert_no_critical(truncate_span)
        truncations = [
            entry
            for metrics in page_metrics(truncate_span)
            for entry in metrics.get("ellipsisTruncations", [])
        ]
        if not any("ellipsis" in (entry.get("kind") or "") for entry in truncations):
            raise AssertionError(f"Expected ellipsis entry in ellipsisTruncations, got {truncations}")

        clamp = run_verify(f"{server.base_url}/line-clamp.html", tmp / "line-clamp", expect=0)
        assert_no_critical(clamp)

        carousel = run_verify(f"{server.base_url}/carousel-peek.html", tmp / "carousel-peek", expect=0)
        assert_no_critical(carousel)

        app_shell = run_verify(f"{server.base_url}/app-shell-scroll.html", tmp / "app-shell-scroll", expect=0)
        assert_no_critical(app_shell)

        skip_link = run_verify(f"{server.base_url}/skip-link.html", tmp / "skip-link", expect=0)
        assert_no_critical(skip_link)
        assert_warning_rule(skip_link, "offcanvas-hidden")

        fab = run_verify(f"{server.base_url}/fab-over-text.html", tmp / "fab-over-text", expect=0)
        assert_no_critical(fab)

        accordion = run_verify(f"{server.base_url}/accordion-closed.html", tmp / "accordion-closed", expect=0)
        assert_no_critical(accordion)
        assert_warning_rule(accordion, "clipped-hidden")

        form = run_verify(f"{server.base_url}/form-controls.html", tmp / "form-controls", expect=0)
        assert_no_critical(form)

        print("self-test ok")
        return 0
    finally:
        if server:
            server.close()
        if KEEP_TEMP:
            print(f"Preserved self-test workspace: {tmp}", file=sys.stderr)
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
