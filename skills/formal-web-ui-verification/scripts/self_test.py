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


def run_verify(url: str, out: Path, *, expect: int) -> dict:
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
