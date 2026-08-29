#!/usr/bin/env python3
"""Self-tests for the formal web UI verifier."""

from __future__ import annotations

import json
import hashlib
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import TCPServer


ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "scripts" / "formal_web_ui_verify.mjs"
REVIEW = ROOT / "scripts" / "formal_web_ui_review.py"
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
  <main data-ui-continuation-anchor>
    {body}
  </main>
</body>
</html>
"""


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


class FastBindThreadingHTTPServer(ThreadingHTTPServer):
    # macOS CI runners black-hole reverse DNS, so HTTPServer.server_bind's
    # socket.getfqdn() call stalls fixtures ~30s between bind() and listen().
    # The FQDN is unused here — bind like a plain TCPServer.
    def server_bind(self) -> None:
        TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)


class Server:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.previous = Path.cwd()
        os.chdir(root)
        self.httpd = FastBindThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
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


class _FixedPageHandler(BaseHTTPRequestHandler):
    """Serves a body chosen by pick_body(); used for cookie/TLS fixtures."""

    def log_message(self, format: str, *args: object) -> None:
        return

    def pick_body(self) -> str:
        raise NotImplementedError

    def do_GET(self) -> None:
        data = self.pick_body().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class CookieGateHandler(_FixedPageHandler):
    """Without sess=ok the page has invisible text (a must-catch critical)."""

    def pick_body(self) -> str:
        if "sess=ok" in (self.headers.get("Cookie") or ""):
            return page("<h1>Dashboard</h1><p>Session accepted.</p><button>Save changes</button>")
        return page("<p class='bad'>Invisible message</p>", ".bad { color: #fff; background: #fff; }")


class CleanPageHandler(_FixedPageHandler):
    def pick_body(self) -> str:
        return page("<h1>Secure</h1><p>Served over self-signed TLS.</p><button>Save changes</button>")


class RedirectToSignInHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        if self.path == "/dashboard":
            self.send_response(302)
            self.send_header("Location", "/sign-in")
            self.end_headers()
            return
        data = page("<h1>Sign in</h1><form><input placeholder='Email address'></form>").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class SourceBindingHandler(BaseHTTPRequestHandler):
    revision = "deployed-revision"

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        data = page("<h1>Bound deployment</h1><p>Current page content.</p>").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("X-UI-Source-Revision", self.revision)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class DynamicServer:
    def __init__(self, handler: type[BaseHTTPRequestHandler]) -> None:
        self.httpd = FastBindThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.scheme = "http"
        self.thread: threading.Thread | None = None

    def start(self) -> "DynamicServer":
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self

    @property
    def base_url(self) -> str:
        return f"{self.scheme}://127.0.0.1:{self.httpd.server_address[1]}"

    def close(self) -> None:
        self.httpd.shutdown()
        if self.thread:
            self.thread.join(timeout=5)


def make_tls_server(tmp: Path) -> DynamicServer:
    cert = tmp / "self-test-tls.crt"
    key = tmp / "self-test-tls.key"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(key), "-out", str(cert), "-days", "2",
            "-subj", "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1",
        ],
        check=True,
        capture_output=True,
        timeout=TIMEOUT_SECONDS,
    )
    server = DynamicServer(CleanPageHandler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert), str(key))
    server.httpd.socket = context.wrap_socket(server.httpd.socket, server_side=True)
    server.scheme = "https"
    return server.start()


def node_binary() -> str:
    return os.environ.get("FORMAL_WEB_UI_NODE") or shutil.which("node") or "node"


def playwright_module_dir() -> Path:
    """Resolve the verifier dependency independently of the audited cwd."""

    candidates: list[Path] = []
    explicit = os.environ.get("FORMAL_WEB_UI_PLAYWRIGHT_NODE_MODULES")
    if explicit:
        candidates.append(Path(explicit).expanduser())
    # Installed skills are direct links to <repo>/skills/<skill>. Resolve the
    # repository's locked dependency from the canonical script path.
    candidates.append(ROOT.parents[1] / "ci" / "playwright" / "node_modules")
    for item in os.environ.get("NODE_PATH", "").split(os.pathsep):
        if item.strip():
            candidates.append(Path(item.strip()).expanduser())
    candidates.append(
        Path.home()
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
        / "node"
        / "node_modules"
    )
    checked: list[str] = []
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        if str(resolved) in checked:
            continue
        checked.append(str(resolved))
        if (resolved / "playwright" / "package.json").is_file():
            return resolved
    raise AssertionError(
        "Playwright is unavailable for the formal UI self-test. Install the "
        f"locked dependency with `npm ci --ignore-scripts --prefix {ROOT.parents[1] / 'ci' / 'playwright'}` "
        "or set FORMAL_WEB_UI_PLAYWRIGHT_NODE_MODULES to a node_modules directory containing Playwright. "
        f"Checked: {checked}"
    )


def verifier_command(*args: str) -> list[str]:
    return [
        node_binary(),
        str(VERIFY),
        "--playwright-module-dir",
        str(playwright_module_dir()),
        *args,
    ]


def verifier_env() -> dict[str, str]:
    env = os.environ.copy()
    # The command carries an explicit module directory. Leaving NODE_PATH in
    # the child would hide regressions back to cwd/environment-only discovery.
    env.pop("NODE_PATH", None)
    return env


def receipt_artifact_paths(receipt: dict) -> tuple[Path, Path]:
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, dict):
        raise AssertionError(f"Receipt must name report artifacts: {receipt}")
    if isinstance(artifacts.get("directory"), str):
        directory = Path(artifacts["directory"])
        return directory / artifacts.get("json", ""), directory / artifacts.get("markdown", "")
    if isinstance(artifacts.get("json"), str) and isinstance(artifacts.get("markdown"), str):
        return Path(artifacts["json"]), Path(artifacts["markdown"])
    raise AssertionError(f"Receipt artifact paths are incomplete: {receipt}")


def parse_bounded_receipt(stdout: str, *, expect: int) -> dict:
    value = stdout.strip()
    if not value or "\n" in value or len(value.encode("utf-8")) > 2048:
        raise AssertionError("Default stdout must be exactly one bounded receipt line")
    if "# Formal Web UI Verification" in value or "## Findings" in value:
        raise AssertionError("Default stdout leaked the Markdown report body")
    try:
        receipt = json.loads(value)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"Default stdout must be JSON, got: {value[:400]}") from exc
    if receipt.get("exitCode") != expect:
        raise AssertionError(f"Receipt exitCode mismatch: {receipt}")
    receipt_artifact_paths(receipt)
    return receipt


def assert_complete_artifacts(json_out: Path, markdown_out: Path, *, expect: int) -> dict:
    if not json_out.is_file() or not markdown_out.is_file():
        raise AssertionError(f"Verifier did not write both report artifacts: {json_out}, {markdown_out}")
    report = json.loads(json_out.read_text(encoding="utf-8"))
    markdown = markdown_out.read_text(encoding="utf-8")
    expected_heading = (
        "# Formal Web UI Verification Setup Failure"
        if expect == 2
        else "# Formal Web UI Verification Report"
    )
    if expected_heading not in markdown:
        raise AssertionError(f"Markdown artifact is not the complete expected report: {markdown_out}")
    if report.get("runId") is None or (expect == 2 and report.get("status") != "setup-failure"):
        raise AssertionError(f"JSON artifact is not the complete expected report: {json_out}")
    if expect == 2:
        if (
            not report.get("error", {}).get("message")
            or not report.get("startedAt")
            or not report.get("endedAt")
            or len(report.get("evidence", {}).get("verifier", {}).get("sha256", "")) != 64
            or "## Diagnostic" not in markdown
        ):
            raise AssertionError(f"Setup-failure artifacts omitted diagnostic evidence: {json_out}")
    elif (
        report.get("schemaVersion") != 2
        or not isinstance(report.get("pages"), list)
        or not isinstance(report.get("findings"), list)
        or not isinstance(report.get("coverage"), dict)
        or not report.get("startedAt")
        or not report.get("endedAt")
        or len(report.get("evidence", {}).get("verifier", {}).get("sha256", "")) != 64
        or len(report.get("evidence", {}).get("config", {}).get("sha256", "")) != 64
        or report.get("plan", {}).get("widthCoverage") != "sampled-only"
        or not isinstance(report.get("review"), dict)
        or len(report.get("review", {}).get("queueSha256", "")) != 64
        or len(report.get("coverage", {}).get("cells", [])) != len(report.get("pages", []))
        or any(
            "requestedPath" not in page_report
            or "finalPath" not in page_report
            or not isinstance(page_report.get("sourceBinding"), dict)
            or not page_report.get("startedAt")
            or not page_report.get("endedAt")
            for page_report in report.get("pages", [])
        )
        or "## Target Coverage" not in markdown
        or "## Changed Visual Review" not in markdown
        or "## Findings" not in markdown
    ):
        raise AssertionError(f"Verification artifacts omitted full report evidence: {json_out}")
    if expect != 2:
        queue_path = Path(report["review"]["queuePath"])
        if not queue_path.is_file() or hashlib.sha256(queue_path.read_bytes()).hexdigest() != report["review"]["queueSha256"]:
            raise AssertionError(f"Review queue is missing or not hash-bound: {queue_path}")
        queue = json.loads(queue_path.read_text(encoding="utf-8"))
        if queue.get("kind") != "formal-web-ui-review-queue" or queue.get("runId") != report.get("runId"):
            raise AssertionError(f"Review queue does not belong to the report: {queue_path}")
        for page_report in report.get("pages", []):
            if page_report.get("outcome") != "checked":
                continue
            screenshots = page_report.get("screenshots", {})
            for key in ("viewport", "fullPage"):
                evidence = screenshots.get(key)
                if not isinstance(evidence, dict):
                    raise AssertionError(f"Checked page omitted {key} screenshot evidence")
                screenshot_path = Path(evidence.get("path", ""))
                if (
                    not screenshot_path.is_file()
                    or evidence.get("mime") != "image/png"
                    or len(evidence.get("sha256", "")) != 64
                    or hashlib.sha256(screenshot_path.read_bytes()).hexdigest() != evidence.get("sha256")
                ):
                    raise AssertionError(f"Invalid {key} screenshot evidence: {evidence}")
    return report


def run_verifier_command(
    cmd: list[str],
    json_out: Path,
    markdown_out: Path,
    *,
    expect: int,
    env: dict[str, str] | None = None,
) -> dict:
    result = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=TIMEOUT_SECONDS,
        env=env or verifier_env(),
    )
    if result.returncode != expect:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise AssertionError(f"Expected exit {expect}, got {result.returncode}: {' '.join(cmd)}")
    if result.stderr.strip():
        raise AssertionError(f"Default invocation emitted non-receipt stderr: {result.stderr[:400]}")
    receipt = parse_bounded_receipt(result.stdout, expect=expect)
    receipt_json, receipt_markdown = receipt_artifact_paths(receipt)
    if receipt_json.resolve() != json_out.resolve() or receipt_markdown.resolve() != markdown_out.resolve():
        raise AssertionError(f"Receipt must point to the exact report artifacts: {receipt}")
    return assert_complete_artifacts(json_out, markdown_out, expect=expect)


def default_target_contract() -> dict:
    return {
        "journeys": [
            {
                "id": "fixture-primary",
                "name": "Exercise the fixture",
                "frequencyPercent": 100,
                "risk": "normal",
                "rationale": "Self-test target",
            }
        ],
        "primaryJourney": "fixture-primary",
        "regions": [
            {
                "selector": "main",
                "role": "primary-content",
                "journey": "fixture-primary",
                "name": "Fixture content",
            }
        ],
        "theme": "light",
        "reviewInputs": [
            {"path": "SKILL.md", "kind": "ui-code"}
        ],
    }


def with_target_contract(config: dict) -> dict:
    prepared = json.loads(json.dumps(config))
    prepared.setdefault("repoRoot", str(ROOT.resolve()))
    defaults = default_target_contract()
    target_defaults = prepared.setdefault("targetDefaults", {})
    if isinstance(target_defaults, dict):
        for key, value in defaults.items():
            target_defaults.setdefault(key, value)
    targets = prepared.get("targets")
    if isinstance(targets, list):
        normalized_targets: list[dict | str] = []
        for target in targets:
            if not isinstance(target, dict):
                normalized_targets.append(target)
                continue
            for key, value in defaults.items():
                target.setdefault(key, value)
            for state in target.get("states", []):
                if not isinstance(state, dict) or "continuation" in state:
                    continue
                actions = state.get("actions", [])
                if any(
                    isinstance(action, dict)
                    and action.get("action") in {"click", "press", "check", "uncheck", "selectOption"}
                    for action in actions
                ):
                    state["continuation"] = {
                        "kind": "in-page",
                        "anchor": "main",
                        "focusWithin": "main",
                    }
            normalized_targets.append(target)
        prepared["targets"] = normalized_targets
    return prepared


def run_verify(url: str, out: Path, *, expect: int, extra: list[str] | None = None) -> dict:
    return run_verify_config(
        {
            "targets": [{"url": url}],
            "viewports": [{"name": "mobile", "width": 390, "height": 844}],
        },
        out,
        expect=expect,
        extra=extra,
    )


def run_verify_config(
    config: dict,
    out: Path,
    *,
    expect: int,
    extra: list[str] | None = None,
    apply_contract_defaults: bool = True,
) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    json_out = out / "report.json"
    md_out = out / "report.md"
    config_path = out / "formal-web-ui.json"
    effective = with_target_contract(config) if apply_contract_defaults else config
    config_path.write_text(json.dumps(effective, ensure_ascii=False, indent=2), encoding="utf-8")
    cmd = verifier_command(
        "--config",
        str(config_path),
        "--json-out",
        str(json_out),
        "--markdown-out",
        str(md_out),
        "--fail-on",
        "critical",
    )
    if extra:
        cmd.extend(extra)
    return run_verifier_command(cmd, json_out, md_out, expect=expect)


def run_review(args: list[str], *, expect: int) -> dict:
    result = subprocess.run(
        [sys.executable, str(REVIEW), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=TIMEOUT_SECONDS,
    )
    if result.returncode != expect or result.stderr.strip():
        raise AssertionError(
            f"Expected review exit {expect}, got {result.returncode}: {result.stdout} {result.stderr}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"Review helper must emit one JSON receipt: {result.stdout}") from exc


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
    tmp = Path(tempfile.mkdtemp(prefix="fwv-"))
    server = None
    try:
        skill_contract = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        if (
            "--human-readable-stdout" not in skill_contract
            or "--receipt-only" not in skill_contract
            or "deprecated" not in skill_contract.lower()
            or "human-only" not in skill_contract
            or "default" not in skill_contract
            or "bounded" not in skill_contract
            or "control-text-clipped" not in skill_contract
            or "data-ui-verify-min-content-inset" not in skill_contract
            or "breakpointProfile" not in skill_contract
            or "maxPageCount" not in skill_contract
            or "sampled-only" not in skill_contract
            or "sourceBinding" not in skill_contract
            or "journey_review_contract.md" not in skill_contract
            or "review-queue.json" not in skill_contract
            or "formal_web_ui_review.py" not in skill_contract
            or "secondary-workflow-precedes-primary" not in skill_contract
            or "insufficient-text-contrast" not in skill_contract
            or "declared-theme-contradiction" not in skill_contract
        ):
            raise AssertionError("Skill contract omits required output, detector, breakpoint, or evidence behavior")
        journey_reference = ROOT / "references" / "journey_review_contract.md"
        if not journey_reference.is_file() or not all(
            token in journey_reference.read_text(encoding="utf-8")
            for token in ("primaryJourney", "continuation", "reviewInputs", "manual-review.json", "Screenshot SHA-256")
        ):
            raise AssertionError("Journey/theme/changed-review reference is missing or incomplete")
        fixtures = tmp / "site"
        write(fixtures / "clean.html", page("<h1>Dashboard</h1><p>Everything fits.</p><button>Save changes</button>"))
        write(
            fixtures / "source-binding-meta.html",
            page("<meta name='ui-source-revision' content='meta-deployed-revision'><h1>Meta-bound deployment</h1>"),
        )
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
        # Reachable open-shadow and iframe content must be inspected. Both
        # contexts contain a realistic clipped control that the top document
        # itself does not contain.
        write(
            fixtures / "iframe-child.html",
            page("<button class='bad'>Framed action</button>", ".bad { width: 34px; overflow: hidden; white-space: nowrap; }"),
        )
        write(
            fixtures / "shadow-iframe.html",
            page(
                "<h1>Component library</h1>"
                "<div id='host'></div>"
                "<iframe src='/iframe-child.html' width='200' height='80' title='child'></iframe>"
                "<script>"
                "const host = document.getElementById('host');"
                "const root = host.attachShadow({mode: 'open'});"
                "root.innerHTML = '<style>.bad{width:34px;overflow:hidden;white-space:nowrap}</style>' +"
                " '<button class=\"bad\">Shadow action</button>';"
                "</script>",
            ),
        )
        # A narrow viewport alone is not a mobile-device emulation. This page
        # exposes a realistic touch/UA-only responsive defect so the descriptor
        # path proves it sets device semantics as well as width and height.
        write(
            fixtures / "device-responsive.html",
            page(
                "<h1>Responsive account</h1><div id='slot'></div>"
                "<script>"
                "if (navigator.maxTouchPoints > 0 && /iPhone/.test(navigator.userAgent)) {"
                " document.getElementById('slot').innerHTML = '<button class=\"bad\">Touch account actions</button>';"
                "}"
                "</script>",
                ".bad { width: 38px; overflow: hidden; white-space: nowrap; }",
            ),
        )
        # Hidden/transient states are measured only after explicit, auditable
        # actions. The base state is clean; one opened state is broken and one
        # opened state is an intentional clean disclosure.
        write(
            fixtures / "interaction-states.html",
            page(
                "<button id='open-bad' onclick=\"document.getElementById('bad-panel').hidden=false\">Open actions</button>"
                "<button id='open-good' onclick=\"document.getElementById('good-panel').hidden=false\">Open help</button>"
                "<section id='bad-panel' hidden><button class='bad'>Destructive account action</button></section>"
                "<section id='good-panel' hidden><p>Keyboard-accessible help content.</p></section>",
                ".bad { width: 40px; overflow: hidden; white-space: nowrap; }",
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
        write(
            fixtures / "native-placeholder-clipped.html",
            page(
                "<label for='query'>Search</label>"
                "<input id='query' class='narrow' placeholder='PRIVATE_PLACEHOLDER_MUST_NOT_LEAK'>",
                ".narrow { width: 92px; padding: 5px 10px; font: 16px Arial, sans-serif; }",
            ),
        )
        write(
            fixtures / "native-select-clipped.html",
            page(
                "<label for='choice'>Choice</label>"
                "<select id='choice' class='narrow'><option selected>PRIVATE_SELECTED_LABEL_MUST_NOT_LEAK</option></select>",
                ".narrow { width: 112px; padding: 5px 10px; font: 16px Arial, sans-serif; }",
            ),
        )
        write(
            fixtures / "native-typed-scrollable.html",
            page(
                "<label for='typed'>Reference</label>"
                "<input id='typed' class='narrow' value='PRIVATE_TYPED_VALUE_MUST_NOT_LEAK'>",
                ".narrow { width: 92px; padding: 5px 10px; font: 16px Arial, sans-serif; }",
            ),
        )
        write(
            fixtures / "native-placeholder-allowed.html",
            page(
                "<input class='narrow' data-ui-allow-truncation='compact search prompt' "
                "placeholder='PRIVATE_ALLOWED_PLACEHOLDER_MUST_NOT_LEAK'>",
                ".narrow { width: 92px; padding: 5px 10px; font: 16px Arial, sans-serif; }",
            ),
        )
        write(
            fixtures / "content-inset-bad.html",
            page(
                "<section class='card' data-ui-verify-min-content-inset='12'><span>Items</span></section>",
                ".card { width: 240px; border: 1px solid #aaa; }",
            ),
        )
        write(
            fixtures / "content-inset-clean.html",
            page(
                "<section class='card'><span>Items</span><button>Add item</button></section>",
                ".card { width: 240px; padding: 16px; border: 1px solid #aaa; } .card button { display: block; margin-top: 8px; }",
            ),
        )
        write(
            fixtures / "content-inset-intentional-edges.html",
            page(
                "<fieldset><legend>Delivery</legend><label>Street <input></label></fieldset>"
                "<div class='attached'><input aria-label='Quantity'><button>Apply</button></div>",
                ".attached { display: flex; margin-top: 16px; } .attached input, .attached button { margin: 0; }",
            ),
        )
        write(
            fixtures / "breakpoint-edge.html",
            page(
                "<button class='bp'>Responsive navigation actions</button>",
                "@media (max-width: 767px) { .bp { width: 38px; overflow: hidden; white-space: nowrap; } }",
            ),
        )
        # Scroll-container reachability: a wide table row scrolled out of its own
        # overflow-x container sits (in document coordinates) under a neighboring
        # panel. That is reachable content, not an occlusion — hit-testing must
        # scroll the container into view instead of blaming the neighbor.
        write(
            fixtures / "scroll-panel-neighbor.html",
            page(
                "<div class='cols'>"
                "<div class='left'><div class='hscroll'><div class='wide'>"
                "<span class='cell'>OpenFOAM long run condition name</span>"
                "<span class='cell state'>pending</span>"
                "</div></div></div>"
                "<div class='right'><p>Neighbor panel content sits here.</p></div>"
                "</div>",
                ".cols { display: flex; gap: 8px; } .left { width: 160px; }"
                " .hscroll { overflow-x: auto; } .wide { display: flex; gap: 12px; min-width: 480px; }"
                " .cell { white-space: nowrap; flex: 0 0 auto; }"
                " .right { width: 170px; background: #f4f6f8; padding: 8px; }",
            ),
        )
        # Closed <details>: Chromium keeps layout boxes for the hidden content
        # (content-visibility), so a later sibling legitimately occupies the same
        # document coordinates. The hidden fields must not be reported occluded.
        write(
            fixtures / "details-closed-neighbor.html",
            page(
                "<details><summary>advanced settings</summary>"
                "<label>Span <input value='1.0'></label>"
                "<select><option>derived value</option></select>"
                "</details>"
                "<div class='after'>Preview panel that renders where the closed details content would be.</div>",
                ".after { background: #f4f6f8; padding: 10px; }",
            ),
        )
        # Framework dev overlays (Next.js badge portal) are dev-server artifacts,
        # not page content: they must not count as occluders.
        write(
            fixtures / "dev-overlay-badge.html",
            page(
                "<div class='msg'>Status text pinned near the bottom left corner.</div>"
                "<nextjs-portal class='badge'></nextjs-portal>",
                ".msg { position: fixed; bottom: 12px; left: 12px; width: 260px; height: 36px; }"
                " nextjs-portal.badge { position: fixed; bottom: 8px; left: 8px; width: 270px; height: 44px;"
                " display: block; background: #000; border-radius: 22px; }",
            ),
        )
        # Recall guard for the same code path: an opaque overlay covering content
        # that IS visible inside the scroll container must still be caught.
        write(
            fixtures / "overlay-in-scroll.html",
            page(
                "<div class='hscroll'><div class='wide'>"
                "<span class='cell'>Visible target text</span>"
                "</div><div class='cover'></div></div>",
                ".hscroll { position: relative; width: 300px; overflow-x: auto; }"
                " .wide { min-width: 600px; } .cell { white-space: nowrap; }"
                " .cover { position: absolute; left: 0; top: 0; width: 220px; height: 44px; background: #222; }",
            ),
        )
        write(
            fixtures / "accounts-form-first.html",
            page(
                """
<section id="add-account" class="add-account">
  <h2>Add account</h2>
  <label>Name <input></label>
  <button>Save account</button>
</section>
<section id="account-list" class="account-list">
  <h1>Accounts</h1>
  <article>Ada</article><article>Grace</article><article>Linus</article>
</section>
""",
                ".add-account { min-height: 320px; padding: 24px; background: #eef2ff; }"
                " .account-list { min-height: 420px; padding: 24px; }",
            ),
        )
        write(
            fixtures / "accounts-offscreen-add.html",
            page(
                """
<h1>Accounts</h1>
<button id="open-add">Add account</button>
<section id="account-list" class="long-list">
  <p>Ada</p><p>Grace</p><p>Linus</p><p>Margaret</p><p>Barbara</p>
</section>
<form id="add-form" hidden>
  <h2>Add account</h2>
  <label>Name <input id="account-name"></label>
</form>
<script>
document.querySelector('#open-add').addEventListener('click', () => {
  document.querySelector('#add-form').hidden = false;
});
</script>
""",
                ".long-list { min-height: 1450px; } #add-form { min-height: 260px; padding: 20px; background: #eef2ff; }",
            ),
        )
        write(
            fixtures / "accounts-modal-add.html",
            page(
                """
<h1>Accounts</h1>
<button id="open-add">Add account</button>
<section id="account-list" class="long-list"><p>Ada</p><p>Grace</p><p>Linus</p></section>
<div id="add-dialog" role="dialog" aria-modal="true" hidden>
  <h2>Add account</h2>
  <label>Name <input id="account-name"></label>
  <button>Save</button>
</div>
<script>
document.querySelector('#open-add').addEventListener('click', () => {
  const dialog = document.querySelector('#add-dialog');
  dialog.hidden = false;
  document.querySelector('#account-name').focus();
});
</script>
""",
                ".long-list { min-height: 1400px; } #add-dialog { position: fixed; inset: 18% 12%; z-index: 20; padding: 24px; background: white; border: 2px solid #334155; }",
            ),
        )
        write(
            fixtures / "accounts-toolbar.html",
            page(
                """
<div id="account-tools"><label>Search <input></label><button>Filter</button></div>
<section id="account-list"><h1>Accounts</h1><article>Ada</article><article>Grace</article></section>
""",
                "#account-tools { min-height: 44px; display: flex; gap: 8px; } #account-list { min-height: 420px; }",
            ),
        )
        write(
            fixtures / "accounts-alert.html",
            page(
                """
<div id="blocking-alert" role="alert">Account data is unavailable until the connection is restored.</div>
<section id="account-list"><h1>Accounts</h1><p>Unavailable</p></section>
""",
                "#blocking-alert { padding: 18px; background: #fee2e2; color: #7f1d1d; } #account-list { min-height: 360px; }",
            ),
        )
        write(
            fixtures / "create-account.html",
            page(
                """
<form id="create-form">
  <h1>Add account</h1>
  <label>Name <input id="account-name" autofocus></label>
  <button>Save account</button>
</form>
""",
                "#create-form { min-height: 420px; padding: 24px; }",
            ),
        )
        write(
            fixtures / "accounts-navigation.html",
            page(
                "<h1>Accounts</h1><a id='go-create' href='/create-account.html'>Add account</a><section id='account-list'><p>Ada</p></section>",
                "#account-list { min-height: 420px; }",
            ),
        )
        write(
            fixtures / "theme-dark-with-bright-surface.html",
            page(
                "<section id='primary' class='bright'><h1>Dark workspace</h1><p>A bright sheet dominates this dark target.</p></section>",
                "body { background: #0b1020; color: #e5e7eb; } .bright { min-height: 760px; background: #fff; color: #111; padding: 24px; }",
            ),
        )
        write(
            fixtures / "theme-light-with-dark-surface.html",
            page(
                "<section id='primary' class='dark'><h1>Light workspace</h1><p>A dark sheet dominates this light target.</p></section>",
                ".dark { min-height: 760px; background: #111827; color: #fff; padding: 24px; }",
            ),
        )
        write(
            fixtures / "theme-mixed.html",
            page(
                "<section id='primary' class='mixed'><div class='light'><h1>Mixed canvas</h1></div><div class='dark'>Dark comparison surface</div></section>",
                ".mixed { display: grid; grid-template-columns: 1fr 1fr; min-height: 760px; } .light { background: white; color: #111; padding: 24px; } .dark { background: #111827; color: white; padding: 24px; }",
            ),
        )
        write(
            fixtures / "contrast-aa-fail.html",
            page("<section id='primary'><h1>Accounts</h1><p class='low'>Normal text below AA contrast.</p></section>", ".low { color: #888; background: #fff; } #primary { min-height: 360px; }"),
        )
        write(
            fixtures / "contrast-large-pass.html",
            page("<section id='primary'><h1>Accounts</h1><p class='large'>Large text passes its 3:1 threshold.</p></section>", ".large { color: #777; background: #fff; font-size: 24px; } #primary { min-height: 360px; }"),
        )
        write(
            fixtures / "contrast-allowed.html",
            page("<section id='primary'><h1>Accounts</h1><p data-ui-allow-contrast='inactive decorative watermark' class='low'>Watermark</p></section>", ".low { color: #aaa; background: #fff; } #primary { min-height: 360px; }"),
        )
        write(
            fixtures / "palette-competing.html",
            page(
                "<section id='primary' class='palette'><div class='red'></div><div class='green'></div><div class='blue'></div><div class='purple'></div><h1>Palette lab</h1></section>",
                ".palette { position: relative; display: grid; grid-template-columns: 1fr 1fr; min-height: 760px; }"
                " .palette > div { min-height: 380px; } .red { background: #ef233c; } .green { background: #00a878; }"
                " .blue { background: #0057ff; } .purple { background: #b517ff; }"
                " .palette h1 { position: absolute; top: 12px; left: 12px; margin: 0; padding: 8px; color: white; background: #111; }",
            ),
        )
        write(
            fixtures / "dynamic-review.html",
            page(
                "<section id='primary'><h1>Dynamic review fixture</h1><p id='dynamic'></p></section><script>document.querySelector('#dynamic').textContent = String(Date.now());</script>",
                "#primary { min-height: 420px; }",
            ),
        )
        server = Server(fixtures)
        clean_contract_config = tmp / "clean-contract.json"
        clean_contract_config.write_text(
            json.dumps(
                with_target_contract(
                    {
                        "targets": [{"url": f"{server.base_url}/clean.html"}],
                        "viewports": [{"name": "desktop", "width": 1280, "height": 800}],
                    }
                ),
                indent=2,
            ),
            encoding="utf-8",
        )

        # The normal no-output-path invocation must create both complete
        # artifacts outside the audited working tree and print only a receipt.
        audited_worktree = tmp / "audited-worktree"
        audited_worktree.mkdir()
        default_root = tmp / "auto-artifacts"
        default_root.mkdir()
        default_env = verifier_env()
        default_env["TMPDIR"] = str(default_root)
        automatic = subprocess.run(
            verifier_command(
                "--config",
                str(clean_contract_config),
            ),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=TIMEOUT_SECONDS,
            env=default_env,
            cwd=audited_worktree,
        )
        if automatic.returncode != 0 or automatic.stderr.strip():
            diagnostic: object = None
            try:
                failure_receipt = parse_bounded_receipt(
                    automatic.stdout,
                    expect=automatic.returncode,
                )
                failure_json, _ = receipt_artifact_paths(failure_receipt)
                diagnostic = json.loads(failure_json.read_text(encoding="utf-8")).get("error")
            except Exception as error:  # noqa: BLE001 - retain the primary verifier failure
                diagnostic = f"unreadable setup-failure artifact: {error}"
            raise AssertionError(
                "Automatic artifact run failed: "
                f"returncode={automatic.returncode}; diagnostic={diagnostic!r}; "
                f"stderr={automatic.stderr!r}"
            )
        automatic_receipt = parse_bounded_receipt(automatic.stdout, expect=0)
        automatic_json, automatic_markdown = receipt_artifact_paths(automatic_receipt)
        assert_complete_artifacts(automatic_json, automatic_markdown, expect=0)
        if not automatic_json.resolve().is_relative_to(default_root.resolve()):
            raise AssertionError(f"Default artifacts were not allocated under the external temp root: {automatic_receipt}")
        if automatic_json.parent.name == default_root.name or not automatic_json.parent.name.startswith("formal-web-ui-verification-"):
            raise AssertionError(f"Default artifacts must use a unique per-run directory: {automatic_receipt}")
        if automatic_json.resolve().is_relative_to(audited_worktree.resolve()):
            raise AssertionError("Default artifacts must stay outside the audited repository")

        # Commands published while receipt mode was opt-in remain safe: the
        # old CLI flag is accepted as a no-op, never as an output-mode switch.
        alias_dir = tmp / "deprecated-receipt-alias"
        alias_json = alias_dir / "report.json"
        alias_markdown = alias_dir / "report.md"
        alias_report = run_verifier_command(
            verifier_command(
                "--config",
                str(clean_contract_config),
                "--json-out",
                str(alias_json),
                "--markdown-out",
                str(alias_markdown),
                "--receipt-only",
            ),
            alias_json,
            alias_markdown,
            expect=0,
        )
        assert_no_critical(alias_report)

        # Both legacy config booleans are accepted as compatibility no-ops.
        # In particular, false cannot revive full Markdown stdout.
        for receipt_only in (True, False):
            compatibility_report = run_verify_config(
                {
                    "targets": [{"url": f"{server.base_url}/clean.html"}],
                    "viewports": [{"name": "desktop", "width": 1280, "height": 800}],
                    "receiptOnly": receipt_only,
                },
                tmp / f"receipt-config-{str(receipt_only).lower()}",
                expect=0,
            )
            assert_no_critical(compatibility_report)

        # Full Markdown stdout is compatibility behavior for an attended human
        # terminal and must require the explicit human-only flag.
        human_dir = tmp / "human-readable-stdout"
        human_json = human_dir / "report.json"
        human_markdown = human_dir / "report.md"
        human = subprocess.run(
            verifier_command(
                "--config",
                str(clean_contract_config),
                "--json-out",
                str(human_json),
                "--markdown-out",
                str(human_markdown),
                "--human-readable-stdout",
            ),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=TIMEOUT_SECONDS,
            env=verifier_env(),
        )
        if human.returncode != 0 or human.stderr.strip() or "# Formal Web UI Verification Report" not in human.stdout:
            raise AssertionError("Explicit human-readable stdout mode must print the full Markdown report")
        assert_complete_artifacts(human_json, human_markdown, expect=0)

        # Configuration/setup exit 2 remains artifact-first. Explicit output
        # paths are honored when they are valid and the receipt stays bounded.
        setup_dir = tmp / "setup-failure"
        setup_json = setup_dir / "report.json"
        setup_markdown = setup_dir / "report.md"
        setup_report = run_verifier_command(
            verifier_command(
                "--url",
                f"{server.base_url}/clean.html",
                "--json-out",
                str(setup_json),
                "--markdown-out",
                str(setup_markdown),
                "--fail-on",
                "not-a-severity",
            ),
            setup_json,
            setup_markdown,
            expect=2,
        )
        if "Invalid failOn severity" not in setup_report.get("error", {}).get("message", ""):
            raise AssertionError("Setup-failure JSON artifact must preserve the actionable configuration error")

        bad_receipt_config = run_verify_config(
            {
                "targets": [{"url": f"{server.base_url}/clean.html"}],
                "receiptOnly": "yes",
            },
            tmp / "receipt-config-invalid",
            expect=2,
        )
        if "receiptOnly must be a boolean" not in bad_receipt_config.get("error", {}).get("message", ""):
            raise AssertionError("Non-boolean receiptOnly config must fail through the artifact-first setup contract")

        # Even a parse failure with no caller paths gets a machine-readable
        # failure artifact in the software-owned external directory.
        no_path_failure = subprocess.run(
            verifier_command("--unknown-option"),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=TIMEOUT_SECONDS,
            env=default_env,
        )
        if no_path_failure.returncode != 2 or no_path_failure.stderr.strip():
            raise AssertionError(f"No-path setup failure was not bounded: {no_path_failure.stderr}")
        no_path_receipt = parse_bounded_receipt(no_path_failure.stdout, expect=2)
        no_path_json, no_path_markdown = receipt_artifact_paths(no_path_receipt)
        assert_complete_artifacts(no_path_json, no_path_markdown, expect=2)

        # Coverage recall: an explicit target that cannot be checked must fail
        # the run instead of producing a successful zero-page report.
        dead_target = run_verify("http://127.0.0.1:9/", tmp / "dead-target", expect=3)
        if not dead_target.get("coverage", {}).get("failed"):
            raise AssertionError("Dead explicit target should record a coverage failure")

        not_found = run_verify(f"{server.base_url}/missing-route.html", tmp / "not-found", expect=3)
        if not not_found.get("coverage", {}).get("failed"):
            raise AssertionError("404 explicit target should record a coverage failure")

        write(fixtures / "plain.txt", "not html\n")
        non_html = run_verify(f"{server.base_url}/plain.txt", tmp / "non-html", expect=3)
        if not non_html.get("coverage", {}).get("failed"):
            raise AssertionError("Non-HTML explicit target should record a coverage failure")

        redirect_server = DynamicServer(RedirectToSignInHandler).start()
        try:
            redirected = run_verify(
                f"{redirect_server.base_url}/dashboard",
                tmp / "redirected-to-sign-in",
                expect=3,
            )
            redirected_page = redirected.get("pages", [{}])[0]
            if (
                redirected_page.get("outcome") != "route_mismatch"
                or redirected_page.get("requestedPath") != "/dashboard"
                or redirected_page.get("finalPath") != "/sign-in"
                or redirected.get("coverage", {}).get("checkedPages") != 0
            ):
                raise AssertionError(f"Sign-in redirect counted as checked coverage: {redirected_page}")
        finally:
            redirect_server.close()

        binding_server = DynamicServer(SourceBindingHandler).start()
        try:
            binding_config = {
                "targets": [{
                    "url": f"{binding_server.base_url}/bound",
                    "sourceBinding": {"expected": SourceBindingHandler.revision},
                }],
                "viewports": [{"name": "desktop", "width": 1280, "height": 800}],
                "maxPageCount": 1,
            }
            binding_match = run_verify_config(
                binding_config,
                tmp / "source-binding-match",
                expect=0,
            )
            binding_page = binding_match.get("pages", [{}])[0]
            if binding_page.get("sourceBinding", {}).get("status") != "matched":
                raise AssertionError(f"Matching deployment/source binding was not recorded: {binding_page}")
            if binding_page.get("requestedPath") != "/bound" or binding_page.get("finalPath") != "/bound":
                raise AssertionError("Matching page omitted requested/final path evidence")

            binding_repeat = run_verify_config(
                binding_config,
                tmp / "source-binding-match-repeat",
                expect=0,
            )
            evidence = binding_match.get("evidence", {})
            verifier_hash = evidence.get("verifier", {}).get("sha256", "")
            config_hash = evidence.get("config", {}).get("sha256", "")
            expected_verifier_hash = hashlib.sha256(VERIFY.read_bytes()).hexdigest()
            if verifier_hash != expected_verifier_hash or len(config_hash) != 64:
                raise AssertionError(f"Verifier/config hashes are incomplete: {evidence}")
            if config_hash != binding_repeat.get("evidence", {}).get("config", {}).get("sha256"):
                raise AssertionError("Equivalent effective configs did not produce a stable hash")
            if not binding_match.get("startedAt") or not binding_match.get("endedAt"):
                raise AssertionError("Run start/end times are missing")
            if binding_match.get("durationMs", -1) < 0 or binding_page.get("durationMs", -1) < 0:
                raise AssertionError("Run/cell durations must be non-negative")
            if binding_match.get("plan", {}).get("widthCoverage") != "sampled-only":
                raise AssertionError("Plan omitted sampled-only width coverage")
            binding_markdown = (tmp / "source-binding-match" / "report.md").read_text(encoding="utf-8")
            if "## Evidence Identity" not in binding_markdown or "Requested path" not in binding_markdown:
                raise AssertionError("Markdown report omitted evidence identity or exact path cells")

            stale_config = {
                **binding_config,
                "targets": [{
                    "url": f"{binding_server.base_url}/bound",
                    "sourceBinding": {"expected": "newer-source-revision"},
                }],
            }
            stale = run_verify_config(stale_config, tmp / "source-binding-stale", expect=3)
            stale_page = stale.get("pages", [{}])[0]
            if (
                stale_page.get("outcome") != "stale_deployment"
                or stale_page.get("sourceBinding", {}).get("status") != "mismatched"
                or stale.get("coverage", {}).get("checkedPages") != 0
            ):
                raise AssertionError(f"Stale deployment counted as checked coverage: {stale_page}")
        finally:
            binding_server.close()

        missing_binding = run_verify_config(
            {
                "targets": [{
                    "url": f"{server.base_url}/clean.html",
                    "sourceBinding": {"expected": "required-revision"},
                }],
                "viewports": [{"name": "desktop", "width": 1280, "height": 800}],
            },
            tmp / "source-binding-missing",
            expect=3,
        )
        if missing_binding.get("pages", [{}])[0].get("outcome") != "source_binding_missing":
            raise AssertionError("A missing required deployment binding did not fail coverage")

        meta_binding = run_verify_config(
            {
                "targets": [{
                    "url": f"{server.base_url}/source-binding-meta.html",
                    "sourceBinding": {"expected": "meta-deployed-revision"},
                }],
                "viewports": [{"name": "desktop", "width": 1280, "height": 800}],
            },
            tmp / "source-binding-meta",
            expect=0,
        )
        meta_evidence = meta_binding.get("pages", [{}])[0].get("sourceBinding", {})
        if meta_evidence.get("status") != "matched" or meta_evidence.get("observedFrom") != "meta:ui-source-revision":
            raise AssertionError(f"Meta deployment/source binding fallback was not exercised: {meta_evidence}")

        allowed_missing = run_verify_config(
            {
                "targets": [
                    {"url": f"{server.base_url}/clean.html"},
                    {"url": f"{server.base_url}/optional.html", "allowFailure": "optional route is absent in this fixture"},
                ],
                "viewports": [{"name": "desktop", "width": 1280, "height": 800}],
            },
            tmp / "allowed-missing",
            expect=0,
        )
        if allowed_missing.get("coverage", {}).get("failed") or len(allowed_missing.get("coverage", {}).get("tolerated", [])) != 1:
            raise AssertionError("A reasoned optional-target exemption should remain reported without failing a checked run")

        fake_coordinator = tmp / "fake-coordinator.py"
        write(
            fake_coordinator,
            "import json\nprint(json.dumps({'urls': [{'url': 'http://127.0.0.1:9/', 'status': 'running'}]}))\n",
        )
        discovered_default = run_verify_config(
            {
                "fromCoordinator": True,
                "coordinatorScript": str(fake_coordinator),
                "minCheckedPages": 0,
                "viewports": [{"name": "desktop", "width": 1280, "height": 800}],
            },
            tmp / "discovered-default",
            expect=3,
        )
        if not discovered_default.get("coverage", {}).get("failed"):
            raise AssertionError("Coordinator-discovered failures should fail unless explicitly tolerated")
        discovered_tolerated = run_verify_config(
            {
                "fromCoordinator": True,
                "coordinatorScript": str(fake_coordinator),
                "allowDiscoveredTargetFailures": True,
                "minCheckedPages": 0,
                "viewports": [{"name": "desktop", "width": 1280, "height": 800}],
            },
            tmp / "discovered-tolerated",
            expect=0,
        )
        if discovered_tolerated.get("coverage", {}).get("failed") or not discovered_tolerated.get("coverage", {}).get("tolerated"):
            raise AssertionError("Explicitly tolerated discovered failures should stay visible without failing")

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

        narrow_not_device = run_verify_config(
            {
                "targets": [{"url": f"{server.base_url}/device-responsive.html"}],
                "viewports": [{"name": "narrow-browser", "width": 390, "height": 844}],
            },
            tmp / "narrow-not-device",
            expect=0,
        )
        assert_no_rule(narrow_not_device, "clipped-x")
        mobile_descriptor = run_verify_config(
            {
                "targets": [{"url": f"{server.base_url}/device-responsive.html"}],
                "viewports": [{"name": "iphone", "device": "iPhone 13"}],
            },
            tmp / "mobile-device-descriptor",
            expect=1,
        )
        assert_critical_rule(mobile_descriptor, "clipped-x")

        interaction_state = run_verify_config(
            {
                "targets": [{
                    "url": f"{server.base_url}/interaction-states.html",
                    "states": [{
                        "name": "actions-open",
                        "actions": [{"action": "click", "selector": "#open-bad"}],
                        "waitFor": {"selector": "#bad-panel:not([hidden])", "settleMs": 25},
                    }],
                }],
                "viewports": [{"name": "desktop", "width": 1280, "height": 800}],
            },
            tmp / "interaction-state",
            expect=1,
        )
        pages_by_state = {page_report.get("target", {}).get("stateName"): page_report for page_report in interaction_state.get("pages", [])}
        if set(pages_by_state) != {"base", "actions-open"}:
            raise AssertionError(f"Expected independently checked base/open states, got {pages_by_state.keys()}")
        if any(item.get("rule") == "clipped-x" for item in pages_by_state["base"].get("findings", [])):
            raise AssertionError("Hidden base-state content must not be reported as a visible clip")
        if not any(item.get("rule") == "clipped-x" for item in pages_by_state["actions-open"].get("findings", [])):
            raise AssertionError("Opened transient state clip was not detected")
        if any("actions" in page_report.get("target", {}) for page_report in interaction_state.get("pages", [])):
            raise AssertionError("Interaction action payloads must not leak into public reports")

        same_url_distinct_states = run_verify_config(
            {
                "targets": [
                    {
                        "name": "base-only",
                        "url": f"{server.base_url}/interaction-states.html",
                    },
                    {
                        "name": "opened-only",
                        "url": f"{server.base_url}/interaction-states.html",
                        "includeBase": False,
                        "states": [{
                            "name": "actions-open",
                            "actions": [{"action": "click", "selector": "#open-bad"}],
                            "waitFor": {"selector": "#bad-panel:not([hidden])", "settleMs": 25},
                        }],
                    },
                ],
                "viewports": [{"name": "desktop", "width": 1280, "height": 800}],
            },
            tmp / "same-url-distinct-states",
            expect=1,
        )
        same_url_pages = same_url_distinct_states.get("pages", [])
        same_url_states = [page_report.get("target", {}).get("stateName") for page_report in same_url_pages]
        if len(same_url_pages) != 2 or set(same_url_states) != {"base", "actions-open"}:
            raise AssertionError(
                "Distinct target configurations for the same URL must preserve both base and interaction states; "
                f"got {same_url_states}"
            )

        clean_interaction_state = run_verify_config(
            {
                "targets": [{
                    "url": f"{server.base_url}/interaction-states.html",
                    "includeBase": False,
                    "states": [{
                        "name": "help-open",
                        "actions": [{"action": "click", "selector": "#open-good"}],
                    }],
                }],
                "viewports": [{"name": "desktop", "width": 1280, "height": 800}],
            },
            tmp / "clean-interaction-state",
            expect=0,
        )
        assert_no_critical(clean_interaction_state)

        failed_interaction_state = run_verify_config(
            {
                "targets": [{
                    "url": f"{server.base_url}/interaction-states.html",
                    "includeBase": False,
                    "states": [{
                        "name": "missing-trigger",
                        "actions": [{
                            "action": "fill",
                            "selector": "#does-not-exist",
                            "value": "SECRET_ACTION_VALUE_MUST_NOT_LEAK",
                            "timeoutMs": 100,
                        }],
                    }],
                }],
                "viewports": [{"name": "desktop", "width": 1280, "height": 800}],
            },
            tmp / "failed-interaction-state",
            expect=3,
        )
        if not failed_interaction_state.get("coverage", {}).get("failed"):
            raise AssertionError("A failed required interaction state must fail the coverage gate")
        if "SECRET_ACTION_VALUE_MUST_NOT_LEAK" in json.dumps(failed_interaction_state):
            raise AssertionError("Failed interaction report leaked an action value")

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

        # Reachable open-shadow and iframe content is part of coverage and both
        # clipped controls must be caught.
        shadow = run_verify(f"{server.base_url}/shadow-iframe.html", tmp / "shadow-iframe", expect=1)
        clipped_contexts = [item for item in shadow.get("findings", []) if item.get("rule") == "clipped-x"]
        if len(clipped_contexts) < 2:
            raise AssertionError(f"Expected clipped controls from shadow root and iframe, got {clipped_contexts}")
        not_inspected_totals = [m.get("notInspected", {}) for m in page_metrics(shadow)]
        if any(ni.get("openShadowRoots", 0) for ni in not_inspected_totals):
            raise AssertionError(f"Reachable open shadow roots should be inspected, got {not_inspected_totals}")
        if any(ni.get("iframes", 0) for ni in not_inspected_totals):
            raise AssertionError(f"Reachable iframes should be inspected, got {not_inspected_totals}")

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

        # Native control text is not represented by DOM text geometry. Measure
        # placeholders and selected labels against the true inner content width,
        # but never persist the text being measured or a typed value.
        placeholder = run_verify(
            f"{server.base_url}/native-placeholder-clipped.html",
            tmp / "native-placeholder-clipped",
            expect=1,
        )
        assert_critical_rule(placeholder, "control-text-clipped")
        placeholder_blob = json.dumps(placeholder)
        if "PRIVATE_PLACEHOLDER_MUST_NOT_LEAK" in placeholder_blob:
            raise AssertionError("Clipped placeholder text leaked into the privacy-safe report")
        placeholder_findings = [
            item for item in placeholder.get("findings", []) if item.get("rule") == "control-text-clipped"
        ]
        if not placeholder_findings or any(item.get("textSnippet") for item in placeholder_findings):
            raise AssertionError("control-text-clipped findings must redact their text snippet")
        if not all(
            item.get("evidence", {}).get("measuredTextWidth", 0)
            > item.get("evidence", {}).get("availableInnerWidth", 0)
            for item in placeholder_findings
        ):
            raise AssertionError("Placeholder finding omitted real inner-width evidence")

        selected = run_verify(
            f"{server.base_url}/native-select-clipped.html",
            tmp / "native-select-clipped",
            expect=1,
        )
        assert_critical_rule(selected, "control-text-clipped")
        if "PRIVATE_SELECTED_LABEL_MUST_NOT_LEAK" in json.dumps(selected):
            raise AssertionError("Selected option label leaked into the privacy-safe report")
        selected_evidence = [
            item.get("evidence", {})
            for item in selected.get("findings", [])
            if item.get("rule") == "control-text-clipped"
        ]
        if not any(
            evidence.get("controlTextKind") == "selected-option"
            and evidence.get("nativeAffordanceWidth", 0) > 0
            for evidence in selected_evidence
        ):
            raise AssertionError("Selected option measurement did not account for the native select affordance")

        typed = run_verify(
            f"{server.base_url}/native-typed-scrollable.html",
            tmp / "native-typed-scrollable",
            expect=0,
        )
        assert_no_critical(typed)
        assert_no_rule(typed, "control-text-clipped")
        if "PRIVATE_TYPED_VALUE_MUST_NOT_LEAK" in json.dumps(typed):
            raise AssertionError("A typed, scrollable native control value leaked into the report")

        allowed_control = run_verify(
            f"{server.base_url}/native-placeholder-allowed.html",
            tmp / "native-placeholder-allowed",
            expect=0,
        )
        assert_no_critical(allowed_control)
        assert_no_rule(allowed_control, "control-text-clipped")
        assert_warning_rule(allowed_control, "allowed-truncation")
        if "PRIVATE_ALLOWED_PLACEHOLDER_MUST_NOT_LEAK" in json.dumps(allowed_control):
            raise AssertionError("Allowed placeholder text leaked into the report")

        inset_bad = run_verify(
            f"{server.base_url}/content-inset-bad.html",
            tmp / "content-inset-bad",
            expect=1,
        )
        assert_critical_rule(inset_bad, "content-inset-below-minimum")
        inset_clean = run_verify_config(
            {
                "targets": [{
                    "url": f"{server.base_url}/content-inset-clean.html",
                    "contentInsets": [{"selector": ".card", "min": 12, "name": "items card"}],
                }],
                "viewports": [{"name": "desktop", "width": 1280, "height": 800}],
            },
            tmp / "content-inset-clean",
            expect=0,
        )
        assert_no_critical(inset_clean)
        inset_entries = [
            entry
            for metrics in page_metrics(inset_clean)
            for entry in metrics.get("contentInsetMeasurements", [])
        ]
        if not any(entry.get("status") == "passed" and entry.get("requiredInset") == 12 for entry in inset_entries):
            raise AssertionError(f"Configured content inset was not measured as passing: {inset_entries}")
        intentional_edges = run_verify(
            f"{server.base_url}/content-inset-intentional-edges.html",
            tmp / "content-inset-intentional-edges",
            expect=0,
        )
        assert_no_critical(intentional_edges)
        assert_no_rule(intentional_edges, "content-inset-below-minimum")

        breakpoint_config = {
            "targets": [
                {
                    "name": "breakpoint edge",
                    "url": f"{server.base_url}/breakpoint-edge.html",
                    "breakpointProfile": {
                        "name": "navigation",
                        "breakpoints": [768],
                        "height": 800,
                    },
                },
                {"name": "plain target", "url": f"{server.base_url}/clean.html"},
            ],
            "viewports": [{"name": "configured-768", "width": 768, "height": 800}],
            "maxPageCount": 4,
        }
        breakpoint_report = run_verify_config(
            breakpoint_config,
            tmp / "breakpoint-profile",
            expect=1,
        )
        edge_pages = [
            item for item in breakpoint_report.get("pages", [])
            if item.get("target", {}).get("name") == "breakpoint edge"
        ]
        plain_pages = [
            item for item in breakpoint_report.get("pages", [])
            if item.get("target", {}).get("name") == "plain target"
        ]
        if sorted(page_item.get("viewport", {}).get("width") for page_item in edge_pages) != [767, 768, 769]:
            raise AssertionError(f"Breakpoint profile did not generate exact boundary widths: {edge_pages}")
        if len(plain_pages) != 1 or plain_pages[0].get("viewport", {}).get("width") != 768:
            raise AssertionError("Breakpoint profile leaked onto a target that did not declare it")
        if not any(
            page_item.get("viewport", {}).get("width") == 767
            and any(finding.get("rule") == "clipped-x" for finding in page_item.get("findings", []))
            for page_item in edge_pages
        ):
            raise AssertionError("The breakpoint-minus-one must-catch defect was not detected")
        exact_cells = breakpoint_report.get("coverage", {}).get("cells", [])
        if len(exact_cells) != 4 or any(not cell.get("cellId") for cell in exact_cells):
            raise AssertionError(f"Coverage omitted exact route/state/viewport cells: {exact_cells}")
        if breakpoint_report.get("coverage", {}).get("widthCoverageMode") != "sampled-only":
            raise AssertionError("Width coverage must be labelled sampled-only")
        exact_viewport = next(
            page_item.get("viewport", {})
            for page_item in edge_pages
            if page_item.get("viewport", {}).get("width") == 768
        )
        if set(exact_viewport.get("sampling", {}).get("sources", [])) != {"configured", "breakpoint-profile"}:
            raise AssertionError("Equivalent configured/breakpoint cells were not deterministically de-duplicated")

        over_budget = {**breakpoint_config, "maxPageCount": 3}
        budget_failure = run_verify_config(over_budget, tmp / "breakpoint-budget", expect=2)
        if "exceeding maxPageCount 3" not in budget_failure.get("error", {}).get("message", ""):
            raise AssertionError("Breakpoint expansion did not fail closed at the hard page-count budget")

        # --cookie: the gated fixture is broken for anonymous visitors and clean
        # with the session cookie, proving the cookie reaches the page (recall
        # both ways: the anon run must still catch the critical).
        cookie_server = DynamicServer(CookieGateHandler).start()
        try:
            cookie_anon = run_verify(f"{cookie_server.base_url}/gated.html", tmp / "cookie-anon", expect=1)
            assert_critical_rule(cookie_anon, "invisible-text")
            cookie_authed = run_verify(
                f"{cookie_server.base_url}/gated.html",
                tmp / "cookie-authed",
                expect=0,
                extra=["--cookie", "sess=ok"],
            )
            assert_no_critical(cookie_authed)
            if not page_metrics(cookie_authed):
                raise AssertionError("Cookie-authenticated page was skipped")

            # Config-object cookie form with domain/path scoping: must travel
            # through normalizeCookieList's object branch AND the addCookies
            # domain/path plumbing (not the url fallback) and still reach the
            # gated page — recall, not just parse acceptance.
            cookie_scoped = run_verify_config(
                {
                    "targets": [{"url": f"{cookie_server.base_url}/gated.html"}],
                    "cookies": [{"name": "sess", "value": "ok", "domain": "127.0.0.1", "path": "/"}],
                },
                tmp / "cookie-config-scoped",
                expect=0,
            )
            assert_no_critical(cookie_scoped)
            if not page_metrics(cookie_scoped):
                raise AssertionError("Config-scoped cookie page was skipped")

            # Malformed scoping fields must fail fast with the validator's
            # message in the cold setup artifact, not a downstream Playwright
            # error or a verbose process payload.
            bad_out = tmp / "cookie-config-bad"
            bad_out.mkdir(parents=True, exist_ok=True)
            bad_config = bad_out / "formal-web-ui.json"
            bad_config.write_text(
                json.dumps(
                    {
                        "targets": [{"url": f"{cookie_server.base_url}/gated.html"}],
                        "cookies": [{"name": "sess", "value": "ok", "domain": True}],
                    }
                ),
                encoding="utf-8",
            )
            bad_result = subprocess.run(
                verifier_command("--config", str(bad_config)),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=TIMEOUT_SECONDS,
                env=verifier_env(),
            )
            if bad_result.returncode != 2 or bad_result.stderr.strip():
                raise AssertionError("Malformed cookie domain should fail with one bounded setup receipt")
            bad_receipt = parse_bounded_receipt(bad_result.stdout, expect=2)
            bad_json, bad_markdown = receipt_artifact_paths(bad_receipt)
            bad_report = assert_complete_artifacts(bad_json, bad_markdown, expect=2)
            if "domain must be a non-empty string" not in bad_report.get("error", {}).get("message", ""):
                raise AssertionError("Malformed cookie domain should preserve the validator message in the JSON artifact")
        finally:
            cookie_server.close()

        # --ignore-https-errors: a self-signed TLS target must be verifiable.
        tls_server = make_tls_server(tmp)
        try:
            tls_clean = run_verify(
                f"{tls_server.base_url}/clean.html",
                tmp / "tls-clean",
                expect=0,
                extra=["--ignore-https-errors"],
            )
            assert_no_critical(tls_clean)
            if not page_metrics(tls_clean):
                raise AssertionError("Self-signed TLS page was skipped")
        finally:
            tls_server.close()

        # Scroll-container reachability: content scrolled out of an inner
        # overflow-x container must not be reported as occluded by whatever
        # neighbors its document coordinates.
        scroll_neighbor = run_verify(
            f"{server.base_url}/scroll-panel-neighbor.html", tmp / "scroll-panel-neighbor", expect=0
        )
        assert_no_critical(scroll_neighbor)
        assert_no_rule(scroll_neighbor, "occluded")
        assert_no_rule(scroll_neighbor, "partially-occluded")

        # ...while an overlay really covering visible content inside a scroll
        # container must still be caught (recall guard for the same code path).
        overlay_scroll = run_verify(f"{server.base_url}/overlay-in-scroll.html", tmp / "overlay-in-scroll", expect=1)
        assert_critical_rule(overlay_scroll, "occluded")

        # Closed-details content keeps layout boxes but is not rendered: no
        # occlusion findings for it.
        details_closed = run_verify(
            f"{server.base_url}/details-closed-neighbor.html", tmp / "details-closed-neighbor", expect=0
        )
        assert_no_critical(details_closed)
        assert_no_rule(details_closed, "occluded")
        assert_no_rule(details_closed, "partially-occluded")

        # Framework dev overlays are ignored as occluders.
        dev_overlay = run_verify(f"{server.base_url}/dev-overlay-badge.html", tmp / "dev-overlay-badge", expect=0)
        assert_no_critical(dev_overlay)
        assert_no_rule(dev_overlay, "occluded")
        assert_no_rule(dev_overlay, "partially-occluded")

        # Journey contracts are mandatory for every target, including an
        # otherwise healthy bare URL.
        missing_contract = run_verify_config(
            {
                "targets": [{"url": f"{server.base_url}/clean.html"}],
                "viewports": [{"name": "mobile", "width": 390, "height": 844}],
            },
            tmp / "missing-journey-contract",
            expect=3,
            apply_contract_defaults=False,
        )
        if missing_contract.get("pages", [{}])[0].get("outcome") != "journey_contract_error":
            raise AssertionError("A target without journey/theme/review-input intent did not fail coverage")

        account_journeys = [
            {"id": "view-accounts", "frequencyPercent": 99, "risk": "normal", "rationale": "Normal destination use"},
            {"id": "add-account", "frequencyPercent": 1, "risk": "normal", "rationale": "Occasional creation"},
        ]
        account_review_inputs = [{"path": "SKILL.md", "kind": "ui-code"}]
        account_base = {
            "journeys": account_journeys,
            "primaryJourney": "view-accounts",
            "theme": "light",
            "reviewInputs": account_review_inputs,
        }
        form_first = run_verify_config(
            {
                "targets": [{
                    **account_base,
                    "url": f"{server.base_url}/accounts-form-first.html",
                    "regions": [
                        {"selector": "#add-account", "role": "workflow-surface", "journey": "add-account"},
                        {"selector": "#account-list", "role": "primary-content", "journey": "view-accounts"},
                    ],
                }],
                "viewports": [{"name": "mobile", "width": 390, "height": 844}],
            },
            tmp / "accounts-form-first",
            expect=1,
        )
        assert_critical_rule(form_first, "secondary-workflow-precedes-primary")

        compact_toolbar = run_verify_config(
            {
                "targets": [{
                    **account_base,
                    "url": f"{server.base_url}/accounts-toolbar.html",
                    "regions": [
                        {"selector": "#account-tools", "role": "supporting"},
                        {"selector": "#account-list", "role": "primary-content", "journey": "view-accounts"},
                    ],
                }],
                "viewports": [{"name": "mobile", "width": 390, "height": 844}],
            },
            tmp / "accounts-toolbar",
            expect=0,
        )
        assert_no_rule(compact_toolbar, "supporting-content-dominates-primary")

        blocking_alert = run_verify_config(
            {
                "targets": [{
                    **account_base,
                    "url": f"{server.base_url}/accounts-alert.html",
                    "regions": [
                        {"selector": "#blocking-alert", "role": "blocking-alert", "reason": "The collection cannot load"},
                        {"selector": "#account-list", "role": "primary-content", "journey": "view-accounts"},
                    ],
                }],
                "viewports": [{"name": "mobile", "width": 390, "height": 844}],
            },
            tmp / "accounts-blocking-alert",
            expect=0,
        )
        assert_no_critical(blocking_alert)

        dedicated_create = run_verify_config(
            {
                "targets": [{
                    "url": f"{server.base_url}/create-account.html",
                    "journeys": [{"id": "add-account", "frequencyPercent": 100, "risk": "normal"}],
                    "primaryJourney": "add-account",
                    "regions": [{"selector": "#create-form", "role": "primary-content", "journey": "add-account"}],
                    "theme": "light",
                    "reviewInputs": account_review_inputs,
                }],
                "viewports": [{"name": "mobile", "width": 390, "height": 844}],
            },
            tmp / "dedicated-create",
            expect=0,
        )
        assert_no_critical(dedicated_create)

        offscreen_add = run_verify_config(
            {
                "targets": [{
                    **account_base,
                    "url": f"{server.base_url}/accounts-offscreen-add.html",
                    "includeBase": False,
                    "regions": [{"selector": "#account-list", "role": "primary-content", "journey": "view-accounts"}],
                    "states": [{
                        "name": "add-open",
                        "actions": [{"action": "click", "selector": "#open-add"}],
                        "primaryJourney": "add-account",
                        "priorityOverrideReason": "The user explicitly activated account creation",
                        "regions": [{"selector": "#add-form", "role": "primary-content", "journey": "add-account"}],
                        "continuation": {"kind": "in-page", "anchor": "#add-form h2", "focusWithin": "#add-form"},
                    }],
                }],
                "viewports": [{"name": "mobile", "width": 390, "height": 844}],
            },
            tmp / "accounts-offscreen-add",
            expect=1,
        )
        assert_critical_rule(offscreen_add, "continuation-anchor-offscreen")
        assert_critical_rule(offscreen_add, "continuation-focus-missing")

        modal_add = run_verify_config(
            {
                "targets": [{
                    **account_base,
                    "url": f"{server.base_url}/accounts-modal-add.html",
                    "includeBase": False,
                    "regions": [{"selector": "#account-list", "role": "primary-content", "journey": "view-accounts"}],
                    "states": [{
                        "name": "add-dialog",
                        "actions": [{"action": "click", "selector": "#open-add"}],
                        "primaryJourney": "add-account",
                        "priorityOverrideReason": "The user explicitly activated account creation",
                        "regions": [{"selector": "#add-dialog", "role": "primary-content", "journey": "add-account"}],
                        "continuation": {"kind": "in-page", "anchor": "#add-dialog h2", "focusWithin": "#add-dialog"},
                    }],
                }],
                "viewports": [{"name": "mobile", "width": 390, "height": 844}],
            },
            tmp / "accounts-modal-add",
            expect=0,
        )
        assert_no_critical(modal_add)
        if not modal_add.get("pages", [{}])[0].get("continuation", {}).get("evidence", {}).get("focusSatisfied"):
            raise AssertionError("Visible modal continuation did not preserve focus evidence")

        broad_container_anchor = run_verify_config(
            {
                "targets": [{
                    **account_base,
                    "url": f"{server.base_url}/accounts-modal-add.html",
                    "includeBase": False,
                    "regions": [{"selector": "#account-list", "role": "primary-content", "journey": "view-accounts"}],
                    "states": [{
                        "name": "add-dialog-broad-anchor",
                        "actions": [{"action": "click", "selector": "#open-add"}],
                        "primaryJourney": "add-account",
                        "priorityOverrideReason": "The user explicitly activated account creation",
                        "regions": [{"selector": "#add-dialog", "role": "primary-content", "journey": "add-account"}],
                        "continuation": {"kind": "in-page", "anchor": "#add-dialog", "focusWithin": "#add-dialog"},
                    }],
                }],
                "viewports": [{"name": "mobile", "width": 390, "height": 844}],
            },
            tmp / "accounts-broad-container-anchor",
            expect=1,
        )
        assert_critical_rule(broad_container_anchor, "continuation-anchor-not-recognizable")

        navigation_add = run_verify_config(
            {
                "targets": [{
                    **account_base,
                    "url": f"{server.base_url}/accounts-navigation.html",
                    "includeBase": False,
                    "regions": [{"selector": "#account-list", "role": "primary-content", "journey": "view-accounts"}],
                    "states": [{
                        "name": "dedicated-create",
                        "actions": [{"action": "click", "selector": "#go-create"}],
                        "primaryJourney": "add-account",
                        "priorityOverrideReason": "The user explicitly activated account creation",
                        "regions": [{"selector": "#create-form", "role": "primary-content", "journey": "add-account"}],
                        "continuation": {"kind": "navigation", "anchor": "#create-form h1", "expectedPath": "/create-account.html"},
                    }],
                }],
                "viewports": [{"name": "mobile", "width": 390, "height": 844}],
            },
            tmp / "accounts-navigation",
            expect=0,
        )
        if navigation_add.get("pages", [{}])[0].get("finalPath") != "/create-account.html":
            raise AssertionError("Expected journey navigation was not accepted and recorded")

        dark_inversion = run_verify_config(
            {
                "targets": [{
                    "url": f"{server.base_url}/theme-dark-with-bright-surface.html",
                    "theme": "dark",
                    "regions": [{"selector": "#primary", "role": "primary-content", "journey": "fixture-primary"}],
                }],
                "viewports": [{"name": "desktop", "width": 1280, "height": 800}],
            },
            tmp / "dark-theme-inversion",
            expect=1,
        )
        assert_critical_rule(dark_inversion, "declared-theme-contradiction")
        light_inversion = run_verify_config(
            {
                "targets": [{
                    "url": f"{server.base_url}/theme-light-with-dark-surface.html",
                    "theme": "light",
                    "regions": [{"selector": "#primary", "role": "primary-content", "journey": "fixture-primary"}],
                }],
                "viewports": [{"name": "desktop", "width": 1280, "height": 800}],
            },
            tmp / "light-theme-inversion",
            expect=1,
        )
        assert_critical_rule(light_inversion, "declared-theme-contradiction")
        mixed_theme = run_verify_config(
            {
                "targets": [{
                    "url": f"{server.base_url}/theme-mixed.html",
                    "theme": "mixed",
                    "regions": [{"selector": "#primary", "role": "primary-content", "journey": "fixture-primary"}],
                }],
                "viewports": [{"name": "desktop", "width": 1280, "height": 800}],
            },
            tmp / "mixed-theme",
            expect=0,
        )
        assert_no_rule(mixed_theme, "declared-theme-contradiction")

        contrast_fail = run_verify(f"{server.base_url}/contrast-aa-fail.html", tmp / "contrast-aa-fail", expect=1)
        assert_critical_rule(contrast_fail, "insufficient-text-contrast")
        contrast_large = run_verify(f"{server.base_url}/contrast-large-pass.html", tmp / "contrast-large-pass", expect=0)
        assert_no_rule(contrast_large, "insufficient-text-contrast")
        contrast_allowed = run_verify(f"{server.base_url}/contrast-allowed.html", tmp / "contrast-allowed", expect=0)
        assert_warning_rule(contrast_allowed, "allowed-contrast")
        palette_risk = run_verify_config(
            {
                "targets": [{
                    "url": f"{server.base_url}/palette-competing.html",
                    "theme": "mixed",
                    "regions": [{"selector": "#primary", "role": "primary-content", "journey": "fixture-primary"}],
                }],
                "viewports": [{"name": "desktop", "width": 1280, "height": 800}],
            },
            tmp / "palette-competing",
            expect=0,
        )
        assert_warning_rule(palette_risk, "high-chroma-surface-risk")
        assert_warning_rule(palette_risk, "competing-accent-hues")

        # Review selection follows declared implementation inputs and intent,
        # never screenshot pixels or unrelated files.
        review_repo = (tmp / "review-repo").resolve()
        write(review_repo / "ui" / "screen.css", ".screen { padding: 16px; }\n")
        write(review_repo / "backend.txt", "unrelated backend v1\n")
        review_config = {
            "repoRoot": str(review_repo),
            "targets": [{
                "url": f"{server.base_url}/dynamic-review.html",
                "reviewInputs": [{"path": "ui/screen.css", "kind": "style"}],
            }],
            "viewports": [{"name": "mobile", "width": 390, "height": 844}],
        }
        review_first_dir = tmp / "review-first"
        review_first = run_verify_config(review_config, review_first_dir, expect=0)
        if review_first.get("review", {}).get("pendingCount") != 1:
            raise AssertionError("A newly covered cell must enter changed visual review")
        first_cell = review_first["review"]["cells"][0]
        decisions_path = review_first_dir / "decisions.json"
        decisions_path.write_text(
            json.dumps({"decisions": [{"reviewCellKey": first_cell["reviewCellKey"], "decision": "pass"}]}),
            encoding="utf-8",
        )
        prior_pass = review_first_dir / "manual-review.json"
        run_review(
            [
                "--report", str(review_first_dir / "report.json"),
                "--queue", str(review_first_dir / "review-queue.json"),
                "--decisions", str(decisions_path),
                "--out", str(prior_pass),
            ],
            expect=0,
        )

        review_second_dir = tmp / "review-second"
        review_second = run_verify_config(
            {**review_config, "reviewAgainst": str(prior_pass)},
            review_second_dir,
            expect=0,
        )
        if review_second.get("review", {}).get("pendingCount") != 0 or review_second.get("review", {}).get("carriedPassCount") != 1:
            raise AssertionError("Unchanged UI inputs and intent should carry the pass without reopening screenshots")
        first_hash = first_cell["screenshots"]["viewport"]["sha256"]
        second_hash = review_second["review"]["cells"][0]["screenshots"]["viewport"]["sha256"]
        if first_hash == second_hash:
            raise AssertionError("Dynamic fixture did not prove that pixel drift is ignored as a review trigger")

        write(review_repo / "backend.txt", "unrelated backend v2\n")
        unrelated = run_verify_config(
            {**review_config, "reviewAgainst": str(prior_pass)},
            tmp / "review-unrelated-change",
            expect=0,
        )
        if unrelated.get("review", {}).get("pendingCount") != 0:
            raise AssertionError("An unrelated file change incorrectly triggered manual UI review")

        write(review_repo / "ui" / "screen.css", ".screen { padding: 24px; }\n")
        mapped_change = run_verify_config(
            {**review_config, "reviewAgainst": str(prior_pass)},
            tmp / "review-mapped-change",
            expect=0,
        )
        if mapped_change.get("review", {}).get("pendingCount") != 1:
            raise AssertionError("A declared UI-input change did not trigger manual review")
        write(review_repo / "ui" / "screen.css", ".screen { padding: 16px; }\n")

        intent_change = run_verify_config(
            {
                **review_config,
                "reviewAgainst": str(prior_pass),
                "targets": [{
                    "url": f"{server.base_url}/dynamic-review.html",
                    "theme": "mixed",
                    "reviewInputs": [{"path": "ui/screen.css", "kind": "style"}],
                }],
            },
            tmp / "review-intent-change",
            expect=0,
        )
        if intent_change.get("review", {}).get("pendingCount") != 1:
            raise AssertionError("Changed journey/theme intent did not trigger manual review")

        new_viewport = run_verify_config(
            {
                **review_config,
                "reviewAgainst": str(prior_pass),
                "viewports": [
                    {"name": "mobile", "width": 390, "height": 844},
                    {"name": "desktop", "width": 1280, "height": 800},
                ],
            },
            tmp / "review-new-viewport",
            expect=0,
        )
        if new_viewport.get("review", {}).get("pendingCount") != 1 or new_viewport.get("review", {}).get("carriedPassCount") != 1:
            raise AssertionError("A new viewport should be reviewed without reopening the unchanged existing viewport")

        raw_prior = run_verify_config(
            {**review_config, "reviewAgainst": str(review_first_dir / "report.json")},
            tmp / "review-raw-prior-rejected",
            expect=2,
        )
        if "not a supported reviewed manifest" not in raw_prior.get("error", {}).get("message", ""):
            raise AssertionError("An unreviewed formal report was accepted as a manual-review baseline")

        removed_undisposed = run_verify_config(
            {
                **review_config,
                "reviewAgainst": str(prior_pass),
                "viewports": [{"name": "desktop", "width": 1280, "height": 800}],
            },
            tmp / "review-removed-undisposed",
            expect=3,
        )
        if not removed_undisposed.get("coverage", {}).get("reviewFailures"):
            raise AssertionError("A removed reviewed cell disappeared without an explicit disposition")
        removed_key = first_cell["reviewCellKey"]
        removed_disposed = run_verify_config(
            {
                **review_config,
                "reviewAgainst": str(prior_pass),
                "reviewRemovedCells": [{"reviewCellKey": removed_key, "reason": "The mobile viewport is no longer supported"}],
                "viewports": [{"name": "desktop", "width": 1280, "height": 800}],
            },
            tmp / "review-removed-disposed",
            expect=0,
        )
        if removed_disposed.get("coverage", {}).get("reviewFailures"):
            raise AssertionError("An explicitly dispositioned removed cell still failed review coverage")

        gap_decisions = review_first_dir / "gap-decisions.json"
        gap_decisions.write_text(
            json.dumps({"decisions": [{"reviewCellKey": first_cell["reviewCellKey"], "decision": "gap", "note": "Palette needs correction"}]}),
            encoding="utf-8",
        )
        prior_gap = review_first_dir / "manual-review-gap.json"
        run_review(
            [
                "--report", str(review_first_dir / "report.json"),
                "--queue", str(review_first_dir / "review-queue.json"),
                "--decisions", str(gap_decisions),
                "--out", str(prior_gap),
            ],
            expect=1,
        )
        carried_gap = run_verify_config(
            {**review_config, "reviewAgainst": str(prior_gap)},
            tmp / "review-carried-gap",
            expect=1,
        )
        if carried_gap.get("review", {}).get("pendingCount") != 0:
            raise AssertionError("An unchanged prior gap should remain blocking without reopening images")
        assert_critical_rule(carried_gap, "manual-review-gap-carried")

        first_screenshot = Path(first_cell["screenshots"]["viewport"]["path"])
        first_screenshot.write_bytes(first_screenshot.read_bytes() + b"tampered")
        tampered_review = run_review(
            [
                "--report", str(review_first_dir / "report.json"),
                "--queue", str(review_first_dir / "review-queue.json"),
                "--review", str(prior_pass),
            ],
            expect=2,
        )
        if "hash mismatch" not in tampered_review.get("error", ""):
            raise AssertionError("Screenshot replacement was not rejected as an integrity failure")

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
