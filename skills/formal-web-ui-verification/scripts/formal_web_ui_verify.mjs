#!/usr/bin/env node
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const SEVERITY_ORDER = { info: 0, warning: 1, critical: 2 };
const DEFAULT_VIEWPORTS = [
  { name: "mobile", width: 390, height: 844 },
  { name: "desktop", width: 1440, height: 900 },
];

function usage() {
  return `Usage:
  node scripts/formal_web_ui_verify.mjs --url <url> [--viewport name=390x844] [--json-out out.json] [--markdown-out out.md]
  node scripts/formal_web_ui_verify.mjs --config formal-web-ui.json
  node scripts/formal_web_ui_verify.mjs --from-coordinator --coordinator-script path/to/dev_coordinator.py --only-current

Options:
  --url <url>                       Add a URL target. Can be repeated.
  --config <path>                   Load JSON config.
  --viewport <name=WIDTHxHEIGHT>    Add viewport. Can be repeated.
  --json-out <path>                 Write JSON report.
  --markdown-out <path>             Write Markdown report.
  --fail-on <critical|warning|info> Exit 1 when this severity or higher is found. Default: critical.
  --browser-executable <path>       Use a specific Chrome/Chromium executable.
  --from-coordinator                Read current URLs from codex-dev-coordinator inventory.
  --coordinator-script <path>       Coordinator script path for --from-coordinator.
  --coordinator-project <path>      Optional inventory project filter for --from-coordinator.
  --only-current                    With --from-coordinator, skip stale/stopped/reused URLs.
  --area <name=selector>            Add an area of interest.
  --ignore <selector=reason>        Ignore selector with reason.
  --allow-truncation <selector=reason>
  --allow-overlap <selector=reason>
  --screenshot-dir <path>           Save full-page screenshots for evidence.
`;
}

function parseKeyValue(value, optionName) {
  const index = value.indexOf("=");
  if (index <= 0) {
    throw new Error(`${optionName} expects key=value, got ${value}`);
  }
  return [value.slice(0, index), value.slice(index + 1)];
}

function parseViewport(value) {
  const [name, dims] = parseKeyValue(value, "--viewport");
  const match = /^(\d+)x(\d+)$/i.exec(dims.trim());
  if (!match) {
    throw new Error(`--viewport expects name=WIDTHxHEIGHT, got ${value}`);
  }
  return { name, width: Number(match[1]), height: Number(match[2]) };
}

function parseSelectorReason(value, optionName) {
  const [selector, reason] = parseKeyValue(value, optionName);
  if (!selector.trim() || !reason.trim()) {
    throw new Error(`${optionName} requires both selector and reason`);
  }
  return { selector: selector.trim(), reason: reason.trim() };
}

function parseArgs(argv) {
  const cli = {
    urls: [],
    viewports: [],
    areas: [],
    ignore: [],
    allowTruncation: [],
    allowOverlap: [],
    failOn: undefined,
    configPath: undefined,
    jsonOut: undefined,
    markdownOut: undefined,
    browserExecutable: process.env.FORMAL_WEB_UI_BROWSER || process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
    fromCoordinator: false,
    coordinatorScript: undefined,
    coordinatorProject: undefined,
    onlyCurrent: false,
    screenshotDir: undefined,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const next = () => {
      if (i + 1 >= argv.length) throw new Error(`${arg} requires a value`);
      i += 1;
      return argv[i];
    };
    if (arg === "--help" || arg === "-h") {
      console.log(usage());
      process.exit(0);
    } else if (arg === "--url") {
      cli.urls.push(next());
    } else if (arg === "--config") {
      cli.configPath = next();
    } else if (arg === "--viewport") {
      cli.viewports.push(parseViewport(next()));
    } else if (arg === "--json-out") {
      cli.jsonOut = next();
    } else if (arg === "--markdown-out") {
      cli.markdownOut = next();
    } else if (arg === "--fail-on") {
      cli.failOn = next();
    } else if (arg === "--browser-executable") {
      cli.browserExecutable = next();
    } else if (arg === "--from-coordinator") {
      cli.fromCoordinator = true;
    } else if (arg === "--coordinator-script") {
      cli.coordinatorScript = next();
    } else if (arg === "--coordinator-project") {
      cli.coordinatorProject = next();
    } else if (arg === "--only-current") {
      cli.onlyCurrent = true;
    } else if (arg === "--area") {
      const [name, selector] = parseKeyValue(next(), "--area");
      cli.areas.push({ name: name.trim(), selector: selector.trim() });
    } else if (arg === "--ignore") {
      cli.ignore.push(parseSelectorReason(next(), "--ignore"));
    } else if (arg === "--allow-truncation") {
      cli.allowTruncation.push(parseSelectorReason(next(), "--allow-truncation"));
    } else if (arg === "--allow-overlap") {
      cli.allowOverlap.push(parseSelectorReason(next(), "--allow-overlap"));
    } else if (arg === "--screenshot-dir") {
      cli.screenshotDir = next();
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }
  return cli;
}

function loadConfig(configPath) {
  if (!configPath) return {};
  const parsed = JSON.parse(fs.readFileSync(configPath, "utf8"));
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Config must be a JSON object");
  }
  return parsed;
}

function normalizeSelectorReasonList(value, name) {
  if (!value) return [];
  if (!Array.isArray(value)) throw new Error(`${name} must be an array`);
  return value.map((item) => {
    if (typeof item === "string") return { selector: item, reason: "configured selector" };
    if (item && typeof item === "object" && typeof item.selector === "string" && typeof item.reason === "string") {
      return { selector: item.selector, reason: item.reason };
    }
    throw new Error(`${name} entries must be strings or {selector, reason}`);
  });
}

function normalizeWaitFor(value, name) {
  if (!value) return {};
  if (typeof value === "string") {
    if (!value.trim()) throw new Error(`${name} selector must not be empty`);
    return { selector: value.trim() };
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${name} must be a selector string or object`);
  }
  const normalized = {};
  if (value.selector !== undefined) {
    if (typeof value.selector !== "string" || !value.selector.trim()) {
      throw new Error(`${name}.selector must be a non-empty string`);
    }
    normalized.selector = value.selector.trim();
  }
  if (value.loadState !== undefined) {
    if (!["load", "domcontentloaded", "networkidle"].includes(value.loadState)) {
      throw new Error(`${name}.loadState must be one of load, domcontentloaded, networkidle`);
    }
    normalized.loadState = value.loadState;
  }
  for (const key of ["timeoutMs", "loadStateTimeoutMs", "networkIdleMs", "settleMs"]) {
    if (value[key] !== undefined) {
      const numberValue = Number(value[key]);
      if (!Number.isFinite(numberValue) || numberValue < 0) {
        throw new Error(`${name}.${key} must be a non-negative number`);
      }
      normalized[key] = numberValue;
    }
  }
  return normalized;
}

function mergeWaitFor(configWaitFor, targetWaitFor) {
  return {
    ...normalizeWaitFor(configWaitFor, "waitFor"),
    ...normalizeWaitFor(targetWaitFor, "target.waitFor"),
  };
}

async function applyWaitFor(page, waitFor) {
  if (waitFor.selector) {
    await page.waitForSelector(waitFor.selector, { timeout: waitFor.timeoutMs ?? 10000 });
  }
  if (waitFor.loadState) {
    await page.waitForLoadState(waitFor.loadState, { timeout: waitFor.loadStateTimeoutMs ?? 5000 });
  } else if (waitFor.networkIdleMs !== undefined) {
    await page.waitForLoadState("networkidle", { timeout: waitFor.networkIdleMs }).catch(() => {});
  } else if (!waitFor.selector) {
    await page.waitForLoadState("networkidle", { timeout: 5000 }).catch(() => {});
  }
  if (waitFor.settleMs) {
    await page.waitForTimeout(waitFor.settleMs);
  }
}

function normalizeTargets(config, cli) {
  const targets = [];
  if (Array.isArray(config.targets)) {
    for (const item of config.targets) {
      if (typeof item === "string") targets.push({ url: item });
      else if (item && typeof item === "object" && typeof item.url === "string") targets.push({ ...item });
      else throw new Error("targets entries must be strings or objects with url");
    }
  }
  for (const url of cli.urls) targets.push({ url });
  return targets;
}

function normalizeViewports(config, cli) {
  const viewports = [];
  if (Array.isArray(config.viewports)) {
    for (const item of config.viewports) {
      if (typeof item === "string") viewports.push(parseViewport(item));
      else if (item && typeof item === "object" && item.name && item.width && item.height) {
        viewports.push({ name: String(item.name), width: Number(item.width), height: Number(item.height) });
      } else {
        throw new Error("viewports entries must be name=WIDTHxHEIGHT strings or {name,width,height}");
      }
    }
  }
  viewports.push(...cli.viewports);
  return viewports.length ? viewports : DEFAULT_VIEWPORTS;
}

function normalizeConfig(config, cli) {
  const rules = config.rules && typeof config.rules === "object" ? config.rules : {};
  const failOn = cli.failOn || rules.failOn || "critical";
  if (!(failOn in SEVERITY_ORDER)) throw new Error(`Invalid failOn severity: ${failOn}`);
  const areas = [
    ...(Array.isArray(config.areas) ? config.areas : []),
    ...cli.areas,
  ].map((item) => {
    if (!item || typeof item.name !== "string" || typeof item.selector !== "string") {
      throw new Error("areas entries must be {name, selector}");
    }
    return { name: item.name, selector: item.selector };
  });
  return {
    targets: normalizeTargets(config, cli),
    viewports: normalizeViewports(config, cli),
    waitFor: config.waitFor,
    areas,
    ignore: [...normalizeSelectorReasonList(config.ignore, "ignore"), ...cli.ignore],
    allowTruncation: [...normalizeSelectorReasonList(config.allowTruncation, "allowTruncation"), ...cli.allowTruncation],
    allowOverlap: [...normalizeSelectorReasonList(config.allowOverlap, "allowOverlap"), ...cli.allowOverlap],
    rules: {
      failOn,
      strictTruncation: Boolean(rules.strictTruncation),
    },
    jsonOut: cli.jsonOut || config.jsonOut,
    markdownOut: cli.markdownOut || config.markdownOut,
    browserExecutable: cli.browserExecutable || config.browserExecutable,
    fromCoordinator: cli.fromCoordinator || Boolean(config.fromCoordinator),
    coordinatorScript: cli.coordinatorScript || config.coordinatorScript,
    coordinatorProject: cli.coordinatorProject || config.coordinatorProject,
    onlyCurrent: cli.onlyCurrent || Boolean(config.onlyCurrent),
    screenshotDir: cli.screenshotDir || config.screenshotDir,
  };
}

function resolvePlaywright() {
  const candidates = [];
  const cwd = process.cwd();
  candidates.push(cwd);
  if (process.env.NODE_PATH) {
    for (const item of process.env.NODE_PATH.split(path.delimiter)) {
      if (item.trim()) candidates.push(item.trim());
    }
  }
  candidates.push(path.join(os.homedir(), ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules"));
  const errors = [];
  for (const base of candidates) {
    try {
      const resolved = require.resolve("playwright", { paths: [base] });
      return require(resolved);
    } catch (error) {
      errors.push(`${base}: ${error.message}`);
    }
  }
  throw new Error(`Cannot resolve Playwright. Checked:\n${errors.join("\n")}`);
}

function localBrowserCandidates(explicitPath) {
  const candidates = [];
  if (explicitPath) candidates.push(explicitPath);
  if (process.platform === "darwin") {
    candidates.push(
      "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
      "/Applications/Chromium.app/Contents/MacOS/Chromium",
      "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
      "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    );
  } else if (process.platform === "win32") {
    const roots = [process.env.PROGRAMFILES, process.env["PROGRAMFILES(X86)"], process.env.LOCALAPPDATA].filter(Boolean);
    for (const root of roots) {
      candidates.push(
        path.join(root, "Google/Chrome/Application/chrome.exe"),
        path.join(root, "Microsoft/Edge/Application/msedge.exe"),
      );
    }
  } else {
    candidates.push("/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser", "/snap/bin/chromium");
  }
  return [...new Set(candidates)].filter((item) => item && fs.existsSync(item));
}

async function launchBrowser(chromium, executablePath) {
  const attempts = [];
  if (executablePath) attempts.push({ label: executablePath, options: { executablePath } });
  attempts.push({ label: "playwright-managed-browser", options: {} });
  for (const candidate of localBrowserCandidates(executablePath)) {
    if (candidate !== executablePath) attempts.push({ label: candidate, options: { executablePath: candidate } });
  }
  const errors = [];
  for (const attempt of attempts) {
    try {
      const browser = await chromium.launch({ headless: true, ...attempt.options });
      return { browser, browserLabel: attempt.label };
    } catch (error) {
      errors.push(`${attempt.label}: ${error.message.split("\n")[0]}`);
    }
  }
  throw new Error(`Unable to launch a Chromium browser:\n${errors.join("\n")}`);
}

function coordinatorTargets(config) {
  if (!config.fromCoordinator) return [];
  const script = config.coordinatorScript;
  if (!script) throw new Error("--from-coordinator requires --coordinator-script");
  const args = [script, "inventory", "--no-docker"];
  if (config.coordinatorProject) args.splice(2, 0, "--project", config.coordinatorProject);
  const result = spawnSync("python3", args, {
    cwd: process.cwd(),
    encoding: "utf8",
    maxBuffer: 10 * 1024 * 1024,
  });
  if (result.status !== 0) {
    throw new Error(`Coordinator inventory failed:\n${result.stderr || result.stdout}`);
  }
  const inventory = JSON.parse(result.stdout);
  const urls = Array.isArray(inventory.urls) ? inventory.urls : [];
  const targets = [];
  for (const item of urls) {
    if (!item || typeof item.url !== "string") continue;
    if (config.onlyCurrent && item.status && item.status !== "running") continue;
    targets.push({
      url: item.url,
      name: item.name || item.url,
      project: item.project || null,
      source: "coordinator",
      healthUrl: item.health_url || null,
      status: item.status || null,
    });
  }
  return targets;
}

function sanitizeFilePart(value) {
  return String(value).replace(/[^a-z0-9_.-]+/gi, "_").replace(/^_+|_+$/g, "").slice(0, 80) || "page";
}

function pageVerifier() {
  const config = window.__FORMAL_WEB_UI_CONFIG__;
  const controlSelector = [
    "button",
    "a[href]",
    "input",
    "select",
    "textarea",
    "summary",
    "[role='button']",
    "[role='link']",
    "[role='checkbox']",
    "[role='tab']",
    "[role='menuitem']",
    "[tabindex]:not([tabindex='-1'])",
    "[contenteditable='true']",
  ].join(",");
  const textSelector = [
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "li",
    "td",
    "th",
    "label",
    "span",
    "[data-ui-verify-text]",
  ].join(",");
  const selectorLists = {
    ignore: config.ignore || [],
    allowTruncation: config.allowTruncation || [],
    allowOverlap: config.allowOverlap || [],
  };
  const findings = [];

  const nowRect = (el) => el.getBoundingClientRect();
  const round = (value) => Math.round(value * 100) / 100;
  const rectObj = (rect) => ({
    x: round(rect.x),
    y: round(rect.y),
    width: round(rect.width),
    height: round(rect.height),
    right: round(rect.right),
    bottom: round(rect.bottom),
  });
  const textOf = (el) => (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim();
  const snippet = (el) => (textOf(el) || el.getAttribute("aria-label") || el.getAttribute("title") || el.tagName).slice(0, 140);
  const selectorPath = (el) => {
    if (el.id) return `#${CSS.escape(el.id)}`;
    const parts = [];
    let node = el;
    while (node && node.nodeType === Node.ELEMENT_NODE && node !== document.body && parts.length < 5) {
      let part = node.localName;
      if (node.classList && node.classList.length) {
        part += `.${Array.from(node.classList).slice(0, 2).map((item) => CSS.escape(item)).join(".")}`;
      }
      const parent = node.parentElement;
      if (parent) {
        const siblings = Array.from(parent.children).filter((child) => child.localName === node.localName);
        if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(node) + 1})`;
      }
      parts.unshift(part);
      node = parent;
    }
    return parts.join(" > ") || el.localName || "element";
  };
  const matchesList = (el, entries) => {
    for (const entry of entries) {
      try {
        if (el.matches(entry.selector) || el.closest(entry.selector)) return entry.reason || "configured";
      } catch {
        continue;
      }
    }
    return "";
  };
  const hasAttrReason = (el, attr) => {
    const owner = el.closest(`[${attr}]`);
    return owner ? owner.getAttribute(attr) || attr : "";
  };
  const isIgnored = (el) => Boolean(hasAttrReason(el, "data-ui-verify-ignore") || matchesList(el, selectorLists.ignore));
  const truncationReason = (el) => hasAttrReason(el, "data-ui-allow-truncation") || matchesList(el, selectorLists.allowTruncation);
  const overlapReason = (el) => hasAttrReason(el, "data-ui-allow-overlap") || matchesList(el, selectorLists.allowOverlap);
  const complexArtifactContext = (el) => {
    let node = el;
    while (node && node.nodeType === Node.ELEMENT_NODE && node !== document.body) {
      const marker = `${node.localName || ""} ${node.id || ""} ${typeof node.className === "string" ? node.className : node.className?.baseVal || ""}`.toLowerCase();
      if (/(svg|canvas|leaflet|map|chart|recharts|marker|cluster|axis|legend)/.test(marker)) return true;
      node = node.parentElement;
    }
    return false;
  };
  const visible = (el) => {
    const style = getComputedStyle(el);
    const rect = nowRect(el);
    return style.display !== "none" &&
      style.visibility !== "hidden" &&
      style.visibility !== "collapse" &&
      Number(style.opacity || 1) > 0.01 &&
      rect.width > 1 &&
      rect.height > 1;
  };
  const hasVisibleElementChild = (el) => Array.from(el.children).some((child) => visible(child));
  const isControl = (el) => el.matches(controlSelector);
  const isTextCandidate = (el) => el.matches(textSelector) && textOf(el).length > 0;
  const isLeafText = (el) => isTextCandidate(el) && (!hasVisibleElementChild(el) || el.matches("h1,h2,h3,h4,h5,h6,p,li,td,th,label"));
  const add = (severity, rule, el, message, extra = {}) => {
    findings.push({
      severity,
      rule,
      message,
      selector: el ? selectorPath(el) : "document",
      textSnippet: el ? snippet(el) : "",
      rect: el ? rectObj(nowRect(el)) : null,
      area: extra.area || null,
      evidence: extra.evidence || {},
    });
  };
  const doc = document.documentElement;
  if (doc.scrollWidth > doc.clientWidth + 2) {
    findings.push({
      severity: "critical",
      rule: "document-horizontal-overflow",
      message: "Document scrollWidth exceeds viewport width.",
      selector: "document.documentElement",
      textSnippet: "",
      rect: null,
      area: null,
      evidence: { scrollWidth: doc.scrollWidth, clientWidth: doc.clientWidth },
    });
  }

  const configuredAreaRoots = [];
  for (const area of config.areas || []) {
    try {
      for (const el of document.querySelectorAll(area.selector)) configuredAreaRoots.push({ name: area.name, el });
    } catch {
      findings.push({
        severity: "warning",
        rule: "invalid-area-selector",
        message: `Area selector could not be evaluated: ${area.selector}`,
        selector: area.selector,
        textSnippet: "",
        rect: null,
        area: area.name,
        evidence: {},
      });
    }
  }
  for (const el of document.querySelectorAll("[data-ui-verify-area]")) {
    configuredAreaRoots.push({ name: el.getAttribute("data-ui-verify-area") || selectorPath(el), el });
  }

  const rawCandidates = Array.from(document.querySelectorAll(`${controlSelector},${textSelector},img,video`));
  const candidates = rawCandidates
    .filter((el) => !isIgnored(el) && visible(el))
    .filter((el) => isControl(el) || isLeafText(el) || el.matches("img,video"));

  for (const el of candidates) {
    const style = getComputedStyle(el);
    const rect = nowRect(el);
    const text = textOf(el);
    const complexArtifact = complexArtifactContext(el);
    const isSingleLineEllipsis = style.textOverflow === "ellipsis" && style.whiteSpace === "nowrap";
    const allowedTruncation = truncationReason(el);
    if ((isControl(el) || isLeafText(el)) && text) {
      const clipsX = ["hidden", "clip"].includes(style.overflowX) && el.scrollWidth > el.clientWidth + 3;
      const clipsY = ["hidden", "clip"].includes(style.overflowY) && el.scrollHeight > el.clientHeight + 3;
      if ((clipsX || clipsY) && complexArtifact) {
        add("warning", "complex-artifact-overflow", el, "Complex map/chart/media internals are scroll-clipped; review visually if this artifact is the primary content.", {
          evidence: {
            overflowX: style.overflowX,
            overflowY: style.overflowY,
            scrollWidth: el.scrollWidth,
            clientWidth: el.clientWidth,
            scrollHeight: el.scrollHeight,
            clientHeight: el.clientHeight,
          },
        });
      } else if ((clipsX || clipsY) && !(allowedTruncation || (!config.rules.strictTruncation && isSingleLineEllipsis))) {
        add("critical", clipsX ? "clipped-x" : "clipped-y", el, "Visible text/control content is clipped without an explicit allowance.", {
          evidence: {
            overflowX: style.overflowX,
            overflowY: style.overflowY,
            scrollWidth: el.scrollWidth,
            clientWidth: el.clientWidth,
            scrollHeight: el.scrollHeight,
            clientHeight: el.clientHeight,
          },
        });
      } else if ((clipsX || clipsY) && allowedTruncation) {
        add("warning", "allowed-truncation", el, "Content is clipped but has an explicit truncation allowance.", {
          evidence: { reason: allowedTruncation },
        });
      }
    }
    if (isControl(el) && (rect.right < -2 || rect.left > window.innerWidth + 2)) {
      add("critical", "interactive-offscreen-x", el, "Interactive element is outside the horizontal viewport.", {
        evidence: { viewportWidth: window.innerWidth },
      });
    }
    for (const area of configuredAreaRoots) {
      if (area.el === el || area.el.contains(el)) {
        const areaRect = nowRect(area.el);
        if (rect.left < areaRect.left - 2 || rect.right > areaRect.right + 2 || rect.top < areaRect.top - 2 || rect.bottom > areaRect.bottom + 2) {
          add(isControl(el) || isLeafText(el) ? "critical" : "warning", "outside-area", el, "Element is rendered outside its declared area of interest.", {
            area: area.name,
            evidence: { areaRect: rectObj(areaRect) },
          });
        }
      }
    }
    if (el.matches("img")) {
      if (el.complete && el.naturalWidth === 0) {
        add("critical", "broken-image", el, "Visible image failed to load.", { evidence: { currentSrc: el.currentSrc || el.src } });
      }
    } else if (el.matches("video") && el.error) {
      add("critical", "broken-video", el, "Visible video has a media error.", { evidence: { code: el.error.code } });
    }
    if ((isControl(el) || isLeafText(el)) && text && !complexArtifact) {
      const contrast = contrastAgainstBackground(el);
      if (contrast.transparentText) {
        add("critical", "invisible-text", el, "Text is effectively transparent.", { evidence: contrast });
      } else if (contrast.ratio !== null && contrast.ratio < 1.15) {
        add("critical", "invisible-text", el, "Text foreground/background contrast is effectively invisible.", { evidence: contrast });
      } else if (contrast.ratio !== null && contrast.ratio < 3) {
        add("warning", "low-contrast-risk", el, "Text contrast is below a conservative readability threshold.", { evidence: contrast });
      }
    }
    if (isControl(el) && !complexArtifact && rect.width * rect.height < 400) {
      add("warning", "tiny-interactive-target", el, "Interactive target is very small.", { evidence: { area: Math.round(rect.width * rect.height) } });
    }
  }

  const occlusionCandidates = candidates
    .filter((el) => (isControl(el) || isLeafText(el)) && !overlapReason(el) && !complexArtifactContext(el))
    .slice(0, 300);
  const originalScroll = { x: window.scrollX, y: window.scrollY };
  for (const el of occlusionCandidates) {
    if (!document.body.contains(el) || !visible(el)) continue;
    el.scrollIntoView({ block: "center", inline: "center" });
    const rect = nowRect(el);
    if (rect.width <= 1 || rect.height <= 1) continue;
    const points = [
      { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 },
      { x: rect.left + Math.min(8, rect.width / 2), y: rect.top + Math.min(8, rect.height / 2) },
      { x: rect.right - Math.min(8, rect.width / 2), y: rect.bottom - Math.min(8, rect.height / 2) },
    ].filter((point) => point.x >= 0 && point.y >= 0 && point.x <= window.innerWidth && point.y <= window.innerHeight);
    if (!points.length) continue;
    let covered = 0;
    const evidencePoints = [];
    for (const point of points) {
      const stack = document.elementsFromPoint(point.x, point.y).filter((node) => node.nodeType === Node.ELEMENT_NODE && !isIgnored(node));
      const top = stack.find((node) => getComputedStyle(node).pointerEvents !== "none");
      const ok = top && (top === el || el.contains(top) || top.contains(el));
      evidencePoints.push({
        x: round(point.x),
        y: round(point.y),
        topSelector: top ? selectorPath(top) : "",
        covered: !ok,
      });
      if (!ok) covered += 1;
    }
    if (covered === points.length) {
      add("critical", "occluded", el, "Meaningful text/control appears fully covered by an unrelated element.", {
        evidence: { samplePoints: evidencePoints },
      });
    }
  }
  window.scrollTo(originalScroll.x, originalScroll.y);

  function parseCssColor(value) {
    const raw = String(value || "").trim();
    if (!raw || raw === "transparent") return { r: 0, g: 0, b: 0, a: 0, raw };
    const match = /^rgba?\(([^)]+)\)$/.exec(raw);
    if (match) {
      const parts = match[1]
        .replace(/\//g, " ")
        .split(/[,\s]+/)
        .map((part) => part.trim())
        .filter(Boolean);
      if (parts.length < 3) return null;
      return {
        r: cssRgbChannel(parts[0]),
        g: cssRgbChannel(parts[1]),
        b: cssRgbChannel(parts[2]),
        a: parts.length > 3 ? cssAlpha(parts[3]) : 1,
        raw,
      };
    }
    const labMatch = /^lab\(([^)]+)\)$/.exec(raw);
    if (labMatch) {
      const parsed = parseColorFunctionParts(labMatch[1]);
      if (parsed.channels.length < 3) return null;
      return { ...labToRgb(parsed.channels[0], parsed.channels[1], parsed.channels[2]), a: parsed.alpha, raw };
    }
    const oklabMatch = /^oklab\(([^)]+)\)$/.exec(raw);
    if (oklabMatch) {
      const parsed = parseColorFunctionParts(oklabMatch[1]);
      if (parsed.channels.length < 3) return null;
      const lightness = parsed.rawChannels[0]?.endsWith("%") ? parsed.channels[0] / 100 : parsed.channels[0];
      return { ...oklabToRgb(lightness, parsed.channels[1], parsed.channels[2]), a: parsed.alpha, raw };
    }
    return null;
  }
  function parseColorFunctionParts(body) {
    const [channelsRaw, alphaRaw] = body.split("/");
    const rawChannels = channelsRaw
      .replace(/\//g, " ")
      .split(/[,\s]+/)
      .map((part) => part.trim())
      .filter(Boolean);
    return {
      rawChannels,
      channels: rawChannels.map(cssNumber),
      alpha: alphaRaw === undefined ? 1 : cssAlpha(alphaRaw.trim()),
    };
  }
  function cssNumber(value) {
    if (value === "none") return 0;
    if (value.endsWith("%")) return Number(value.slice(0, -1));
    return Number(value);
  }
  function cssAlpha(value) {
    if (value === "none") return 1;
    if (value.endsWith("%")) return clamp(Number(value.slice(0, -1)) / 100, 0, 1);
    return clamp(Number(value), 0, 1);
  }
  function cssRgbChannel(value) {
    if (value.endsWith("%")) return clamp(Number(value.slice(0, -1)) * 2.55, 0, 255);
    return clamp(Number(value), 0, 255);
  }
  function clamp(value, min, max) {
    if (!Number.isFinite(value)) return min;
    return Math.max(min, Math.min(max, value));
  }
  function linearToSrgb(value) {
    const clamped = clamp(value, 0, 1);
    return (clamped <= 0.0031308 ? clamped * 12.92 : 1.055 * clamped ** (1 / 2.4) - 0.055) * 255;
  }
  function labToRgb(lightness, a, b) {
    const fy = (lightness + 16) / 116;
    const fx = fy + a / 500;
    const fz = fy - b / 200;
    const epsilon = 216 / 24389;
    const kappa = 24389 / 27;
    const inverse = (value) => {
      const cubed = value ** 3;
      return cubed > epsilon ? cubed : (116 * value - 16) / kappa;
    };
    const x = 0.96422 * inverse(fx);
    const y = inverse(fy);
    const z = 0.82521 * inverse(fz);
    return {
      r: linearToSrgb(3.1338561 * x - 1.6168667 * y - 0.4906146 * z),
      g: linearToSrgb(-0.9787684 * x + 1.9161415 * y + 0.033454 * z),
      b: linearToSrgb(0.0719453 * x - 0.2289914 * y + 1.4052427 * z),
    };
  }
  function oklabToRgb(lightness, a, b) {
    const l1 = lightness + 0.3963377774 * a + 0.2158037573 * b;
    const m1 = lightness - 0.1055613458 * a - 0.0638541728 * b;
    const s1 = lightness - 0.0894841775 * a - 1.291485548 * b;
    const l = l1 ** 3;
    const m = m1 ** 3;
    const s = s1 ** 3;
    return {
      r: linearToSrgb(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
      g: linearToSrgb(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
      b: linearToSrgb(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s),
    };
  }
  function blended(color, background) {
    const a = Number.isFinite(color.a) ? color.a : 1;
    return {
      r: color.r * a + background.r * (1 - a),
      g: color.g * a + background.g * (1 - a),
      b: color.b * a + background.b * (1 - a),
      a: 1,
    };
  }
  function luminance(color) {
    const channel = (value) => {
      const n = value / 255;
      return n <= 0.03928 ? n / 12.92 : ((n + 0.055) / 1.055) ** 2.4;
    };
    return 0.2126 * channel(color.r) + 0.7152 * channel(color.g) + 0.0722 * channel(color.b);
  }
  function contrastRatio(a, b) {
    const l1 = luminance(a);
    const l2 = luminance(b);
    const light = Math.max(l1, l2);
    const dark = Math.min(l1, l2);
    return round((light + 0.05) / (dark + 0.05));
  }
  function backgroundFor(el) {
    let node = el;
    while (node && node.nodeType === Node.ELEMENT_NODE) {
      const bg = parseCssColor(getComputedStyle(node).backgroundColor);
      if (bg && bg.a > 0.05) return bg;
      node = node.parentElement;
    }
    return { r: 255, g: 255, b: 255, a: 1, raw: "default-white" };
  }
  function contrastAgainstBackground(el) {
    const fg = parseCssColor(getComputedStyle(el).color);
    if (!fg) {
      return { ratio: null, color: getComputedStyle(el).color, backgroundColor: "unparsed", transparentText: false };
    }
    const bg = backgroundFor(el);
    if (fg.a < 0.05) {
      return { ratio: null, color: fg.raw, backgroundColor: bg.raw, transparentText: true };
    }
    const effectiveFg = fg.a < 1 ? blended(fg, bg) : fg;
    return {
      ratio: contrastRatio(effectiveFg, bg),
      color: fg.raw,
      backgroundColor: bg.raw,
      transparentText: false,
    };
  }
  function scrollbarVisibleForAxis(el, axis, style) {
    const overflow = axis === "x" ? style.overflowX : style.overflowY;
    const canScroll = axis === "x" ? el.scrollWidth > el.clientWidth + 2 : el.scrollHeight > el.clientHeight + 2;
    return canScroll && ["auto", "scroll", "overlay"].includes(overflow);
  }
  function collectVisibleScrollbars() {
    const scrollbars = [];
    const scrolling = document.scrollingElement || document.documentElement;
    const scrollingStyle = getComputedStyle(scrolling);
    const docRect = { x: 0, y: 0, width: window.innerWidth, height: window.innerHeight, right: window.innerWidth, bottom: window.innerHeight };
    if (scrolling.scrollWidth > scrolling.clientWidth + 2) {
      scrollbars.push({
        selector: "document.scrollingElement",
        axis: "x",
        rect: docRect,
        scrollWidth: scrolling.scrollWidth,
        clientWidth: scrolling.clientWidth,
        scrollHeight: scrolling.scrollHeight,
        clientHeight: scrolling.clientHeight,
        overflowX: scrollingStyle.overflowX,
        overflowY: scrollingStyle.overflowY,
      });
    }
    if (scrolling.scrollHeight > scrolling.clientHeight + 2) {
      scrollbars.push({
        selector: "document.scrollingElement",
        axis: "y",
        rect: docRect,
        scrollWidth: scrolling.scrollWidth,
        clientWidth: scrolling.clientWidth,
        scrollHeight: scrolling.scrollHeight,
        clientHeight: scrolling.clientHeight,
        overflowX: scrollingStyle.overflowX,
        overflowY: scrollingStyle.overflowY,
      });
    }
    for (const el of Array.from(document.querySelectorAll("body *"))) {
      if (isIgnored(el) || !visible(el)) continue;
      const style = getComputedStyle(el);
      const hasX = scrollbarVisibleForAxis(el, "x", style);
      const hasY = scrollbarVisibleForAxis(el, "y", style);
      if (!hasX && !hasY) continue;
      const base = {
        selector: selectorPath(el),
        rect: rectObj(nowRect(el)),
        scrollWidth: el.scrollWidth,
        clientWidth: el.clientWidth,
        scrollHeight: el.scrollHeight,
        clientHeight: el.clientHeight,
        overflowX: style.overflowX,
        overflowY: style.overflowY,
      };
      if (hasX) scrollbars.push({ ...base, axis: "x" });
      if (hasY) scrollbars.push({ ...base, axis: "y" });
    }
    return scrollbars;
  }

  return {
    title: document.title,
    url: location.href,
    viewport: { width: window.innerWidth, height: window.innerHeight },
    metrics: {
      candidateCount: candidates.length,
      findingCount: findings.length,
      visibleScrollbars: collectVisibleScrollbars(),
      document: {
        scrollWidth: doc.scrollWidth,
        clientWidth: doc.clientWidth,
        scrollHeight: doc.scrollHeight,
        clientHeight: doc.clientHeight,
      },
    },
    findings,
  };
}

async function verifyTarget(page, target, viewport, config, screenshotDir) {
  await page.setViewportSize({ width: viewport.width, height: viewport.height });
  const result = {
    target,
    viewport,
    skipped: false,
    skipReason: null,
    url: target.url,
    status: null,
    contentType: null,
    title: "",
    metrics: {},
    findings: [],
    screenshot: null,
  };
  let response;
  try {
    response = await page.goto(target.url, { waitUntil: "domcontentloaded", timeout: 15000 });
    await applyWaitFor(page, mergeWaitFor(config.waitFor, target.waitFor));
  } catch (error) {
    result.skipped = true;
    result.skipReason = `navigation-failed: ${error.message}`;
    return result;
  }
  result.status = response ? response.status() : null;
  result.contentType = response ? response.headers()["content-type"] || "" : "";
  if (!response || result.status >= 400 || (result.contentType && !/html|xhtml/i.test(result.contentType))) {
    result.skipped = true;
    result.skipReason = result.status >= 400 ? `non-success-status-${result.status}` : `non-html-content-type-${result.contentType || "unknown"}`;
    result.title = await page.title().catch(() => "");
    return result;
  }
  await page.addInitScript(() => {});
  const pageConfig = {
    areas: [...config.areas, ...(Array.isArray(target.areas) ? target.areas : [])],
    ignore: [...config.ignore, ...normalizeTargetList(target.ignore)],
    allowTruncation: [...config.allowTruncation, ...normalizeTargetList(target.allowTruncation)],
    allowOverlap: [...config.allowOverlap, ...normalizeTargetList(target.allowOverlap)],
    rules: config.rules,
  };
  await page.evaluate((injected) => {
    window.__FORMAL_WEB_UI_CONFIG__ = injected;
  }, pageConfig);
  const evaluated = await page.evaluate(pageVerifier);
  result.title = evaluated.title;
  result.url = evaluated.url;
  result.actualViewport = evaluated.viewport;
  result.metrics = evaluated.metrics;
  result.findings = evaluated.findings;
  if (screenshotDir) {
    fs.mkdirSync(screenshotDir, { recursive: true });
    const file = path.join(screenshotDir, `${sanitizeFilePart(target.name || target.url)}-${sanitizeFilePart(viewport.name)}.png`);
    await page.screenshot({ path: file, fullPage: true }).catch(() => {});
    if (fs.existsSync(file)) result.screenshot = file;
  }
  return result;
}

function normalizeTargetList(value) {
  if (!Array.isArray(value)) return [];
  return value.map((item) => typeof item === "string" ? { selector: item, reason: "target configured selector" } : item);
}

function summarizeFindings(pages) {
  const findings = [];
  for (const page of pages) {
    for (const finding of page.findings || []) {
      findings.push({
        ...finding,
        url: page.target.url,
        targetName: page.target.name || page.target.url,
        viewport: page.viewport.name,
      });
    }
  }
  return findings;
}

function markdownReport(report) {
  const findings = report.findings;
  const criticalCount = findings.filter((item) => item.severity === "critical").length;
  const warningCount = findings.filter((item) => item.severity === "warning").length;
  const lines = [];
  lines.push("# Formal Web UI Verification Report", "");
  lines.push(`- Run ID: ${report.runId}`);
  lines.push(`- Generated: ${report.generatedAt}`);
  lines.push(`- Browser: ${report.browser}`);
  lines.push(`- Targets: ${report.targets.length}`);
  lines.push(`- Pages checked: ${report.pages.filter((page) => !page.skipped).length}`);
  lines.push(`- Pages skipped: ${report.pages.filter((page) => page.skipped).length}`);
  lines.push(`- Critical findings: ${criticalCount}`);
  lines.push(`- Warning findings: ${warningCount}`, "");
  lines.push("## Pages", "");
  lines.push("| Target | Viewport | Status | Result | Findings | Screenshot |");
  lines.push("| --- | --- | --- | --- | --- | --- |");
  for (const page of report.pages) {
    const result = page.skipped ? `skipped: ${page.skipReason}` : "checked";
    lines.push(`| ${escapeMd(page.target.name || page.target.url)} | ${escapeMd(page.viewport.name)} ${page.viewport.width}x${page.viewport.height} | ${page.status ?? ""} | ${escapeMd(result)} | ${(page.findings || []).length} | ${page.screenshot ? escapeMd(page.screenshot) : ""} |`);
  }
  lines.push("", "## Visible Scrollbars", "");
  const scrollbarRows = [];
  for (const page of report.pages) {
    for (const scrollbar of page.metrics?.visibleScrollbars || []) {
      scrollbarRows.push({ page, scrollbar });
    }
  }
  if (!scrollbarRows.length) {
    lines.push("No visible/active scrollbars detected.");
  } else {
    lines.push("| Target | Viewport | Axis | Selector | Rect | Scroll Metrics |");
    lines.push("| --- | --- | --- | --- | --- | --- |");
    for (const row of scrollbarRows) {
      const sb = row.scrollbar;
      const rect = sb.rect ? `${Math.round(sb.rect.width)}x${Math.round(sb.rect.height)} at ${Math.round(sb.rect.x)},${Math.round(sb.rect.y)}` : "";
      const metrics = `scroll ${sb.scrollWidth}x${sb.scrollHeight}; client ${sb.clientWidth}x${sb.clientHeight}; overflow ${sb.overflowX}/${sb.overflowY}`;
      lines.push(`| ${escapeMd(row.page.target.name || row.page.target.url)} | ${escapeMd(row.page.viewport.name)} | ${escapeMd(sb.axis)} | ${escapeMd(sb.selector)} | ${escapeMd(rect)} | ${escapeMd(metrics)} |`);
    }
  }
  lines.push("", "## Findings", "");
  if (!findings.length) {
    lines.push("No findings.");
  } else {
    lines.push("| Severity | Rule | Target | Viewport | Selector | Evidence |");
    lines.push("| --- | --- | --- | --- | --- | --- |");
    for (const finding of findings) {
      const evidence = finding.textSnippet || JSON.stringify(finding.evidence || {});
      lines.push(`| ${finding.severity} | ${escapeMd(finding.rule)} | ${escapeMd(finding.targetName)} | ${escapeMd(finding.viewport)} | ${escapeMd(finding.selector)} | ${escapeMd(String(evidence).slice(0, 180))} |`);
    }
  }
  return `${lines.join("\n")}\n`;
}

function escapeMd(value) {
  return String(value).replace(/\|/g, "\\|").replace(/\n/g, " ");
}

function ensureTargets(config) {
  const all = [...config.targets, ...coordinatorTargets(config)];
  const seen = new Set();
  const unique = [];
  for (const target of all) {
    if (!target.url || seen.has(target.url)) continue;
    seen.add(target.url);
    unique.push(target);
  }
  if (!unique.length) throw new Error("No targets to verify. Provide --url, --config targets, or --from-coordinator.");
  return unique;
}

async function main() {
  const cli = parseArgs(process.argv.slice(2));
  const config = normalizeConfig(loadConfig(cli.configPath), cli);
  const targets = ensureTargets(config);
  const { chromium } = resolvePlaywright();
  const { browser, browserLabel } = await launchBrowser(chromium, config.browserExecutable);
  const report = {
    runId: `formal-web-ui-${Date.now().toString(36)}`,
    generatedAt: new Date().toISOString(),
    browser: browserLabel,
    targets,
    pages: [],
    findings: [],
  };
  try {
    for (const target of targets) {
      for (const viewport of config.viewports) {
        const page = await browser.newPage();
        try {
          report.pages.push(await verifyTarget(page, target, viewport, config, config.screenshotDir));
        } finally {
          await page.close().catch(() => {});
        }
      }
    }
  } finally {
    await browser.close().catch(() => {});
  }
  report.findings = summarizeFindings(report.pages);
  if (config.jsonOut) {
    fs.mkdirSync(path.dirname(path.resolve(config.jsonOut)), { recursive: true });
    fs.writeFileSync(config.jsonOut, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  }
  const markdown = markdownReport(report);
  if (config.markdownOut) {
    fs.mkdirSync(path.dirname(path.resolve(config.markdownOut)), { recursive: true });
    fs.writeFileSync(config.markdownOut, markdown, "utf8");
  }
  console.log(markdown);
  const failThreshold = SEVERITY_ORDER[config.rules.failOn];
  const blocking = report.findings.filter((finding) => SEVERITY_ORDER[finding.severity] >= failThreshold);
  process.exit(blocking.length ? 1 : 0);
}

main().catch((error) => {
  console.error(`formal-web-ui-verification setup error: ${error.stack || error.message}`);
  process.exit(2);
});
