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
  --no-scroll                       Skip the full-page scroll pass (default: scroll on).
  --cookie <name=value>             Send a cookie with every target (repeatable). Use for
                                    auth-gated pages; scoped to the target URL by default.
  --ignore-https-errors             Accept invalid/self-signed TLS certificates.
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
    noScroll: false,
    cookies: [],
    ignoreHttpsErrors: false,
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
    } else if (arg === "--no-scroll") {
      cli.noScroll = true;
    } else if (arg === "--cookie") {
      const [name, value] = parseKeyValue(next(), "--cookie");
      cli.cookies.push({ name: name.trim(), value });
    } else if (arg === "--ignore-https-errors") {
      cli.ignoreHttpsErrors = true;
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

function normalizeCookieList(value) {
  if (!value) return [];
  if (!Array.isArray(value)) throw new Error("cookies must be an array");
  return value.map((item) => {
    if (typeof item === "string") {
      const [name, val] = parseKeyValue(item, "cookies");
      return { name: name.trim(), value: val };
    }
    if (item && typeof item === "object" && typeof item.name === "string" && typeof item.value === "string") {
      const normalized = { name: item.name.trim(), value: item.value };
      if (!normalized.name) throw new Error("cookies entries must have a non-empty name");
      // Validate optional scoping fields here so a malformed config fails
      // with a clear message instead of a confusing Playwright error later.
      for (const field of ["url", "domain", "path"]) {
        if (item[field] === undefined || item[field] === null) continue;
        if (typeof item[field] !== "string" || !item[field].trim()) {
          throw new Error(`cookies entry '${normalized.name}': ${field} must be a non-empty string`);
        }
        normalized[field] = item[field].trim();
      }
      return normalized;
    }
    throw new Error("cookies entries must be 'name=value' strings or {name, value, url?, domain?, path?}");
  });
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
    scroll: cli.noScroll ? false : (config.scroll === undefined ? true : Boolean(config.scroll)),
    cookies: [...normalizeCookieList(config.cookies), ...cli.cookies],
    ignoreHttpsErrors: cli.ignoreHttpsErrors || Boolean(config.ignoreHttpsErrors),
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

// Runs a full-page scroll pass in viewport-height steps so lazy-loaded content and
// IntersectionObservers fire before measurement. `page.evaluate` handles the settle
// wait between steps. Robust to pages that grow while scrolling via a hard iteration cap.
async function scrollThroughPage(page, { maxIterations = 30, settleMs = 120 } = {}) {
  const metrics = { scrollPasses: 0, scrolledTo: 0, maxScrollHeight: 0, capped: false };
  const originalY = await page.evaluate(() => window.scrollY).catch(() => 0);
  for (let i = 0; i < maxIterations; i += 1) {
    const state = await page
      .evaluate(() => {
        const scrolling = document.scrollingElement || document.documentElement;
        const step = window.innerHeight || 600;
        const before = window.scrollY;
        const maxScroll = Math.max(0, scrolling.scrollHeight - window.innerHeight);
        const nextY = Math.min(before + step, maxScroll);
        window.scrollTo(0, nextY);
        return {
          scrollHeight: scrolling.scrollHeight,
          innerHeight: window.innerHeight,
          scrollY: window.scrollY,
          atBottom: window.scrollY >= maxScroll - 1,
        };
      })
      .catch(() => null);
    if (!state) break;
    metrics.scrollPasses += 1;
    metrics.scrolledTo = Math.max(metrics.scrolledTo, Math.round(state.scrollY));
    metrics.maxScrollHeight = Math.max(metrics.maxScrollHeight, Math.round(state.scrollHeight));
    await page.waitForTimeout(settleMs);
    if (state.atBottom) break;
    if (i === maxIterations - 1) metrics.capped = true;
  }
  await page.evaluate((y) => window.scrollTo(0, y), originalY).catch(() => {});
  await page.waitForTimeout(settleMs).catch(() => {});
  return metrics;
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
  const unmeasurableContrast = [];
  const ellipsisTruncations = [];
  const hiddenTextLike = { displayNone: 0, visibilityHidden: 0, zeroOpacity: 0, zeroSize: 0 };
  let pendingMedia = 0;

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

  const styleCache = new WeakMap();
  const cs = (el) => {
    let style = styleCache.get(el);
    if (!style) {
      style = getComputedStyle(el);
      styleCache.set(el, style);
    }
    return style;
  };
  const opacityCache = new WeakMap();
  const effectiveOpacity = (el) => {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return 1;
    const cached = opacityCache.get(el);
    if (cached !== undefined) return cached;
    const value = Number(cs(el).opacity || 1) * effectiveOpacity(el.parentElement);
    opacityCache.set(el, value);
    return value;
  };

  // Complex-artifact detection is token-bounded so ordinary sections named
  // "roadmap", "sitemap", or "org-chart-team" are NOT excluded from checks.
  // An element is artifact context only when an ancestor is a real svg/canvas,
  // matches a known visualization/map library token, or carries a generic
  // map/chart token AND actually contains a substantial svg/canvas/video.
  const ARTIFACT_LIB_TOKENS = /(^|[^a-z0-9])(leaflet|mapbox|maplibre|gm-style|recharts|echarts|highcharts|chartjs|apexcharts|plotly|nivo|visx|vega|cesium|deckgl|deck-gl|openlayers|ol-viewport)([^a-z0-9]|$)/;
  const ARTIFACT_GENERIC_TOKENS = /(^|[^a-z0-9])(map|chart|graph|plot|gauge|sparkline|axis|legend|marker|cluster|heatmap|treemap|diagram)([^a-z0-9]|$)/;
  const CAROUSEL_TOKENS = /(^|[^a-z0-9])(carousel|swiper|slider|slick|embla|glide|flickity|splide|marquee|ticker)([^a-z0-9]|$)/;
  const markerText = (node) => `${node.localName || ""} ${node.id || ""} ${typeof node.className === "string" ? node.className : node.className?.baseVal || ""}`.toLowerCase();
  const artifactCache = new WeakMap();
  const nodeIsArtifact = (node) => {
    const cached = artifactCache.get(node);
    if (cached !== undefined) return cached;
    let isArtifact = false;
    if (node.localName === "svg" || node.localName === "canvas" || node.ownerSVGElement) {
      isArtifact = true;
    } else {
      const marker = markerText(node);
      if (ARTIFACT_LIB_TOKENS.test(marker)) {
        isArtifact = true;
      } else if (ARTIFACT_GENERIC_TOKENS.test(marker)) {
        for (const media of node.querySelectorAll("svg,canvas,video")) {
          const rect = media.getBoundingClientRect();
          if (rect.width * rect.height >= 10000) {
            isArtifact = true;
            break;
          }
        }
      }
    }
    artifactCache.set(node, isArtifact);
    return isArtifact;
  };
  const complexArtifactContext = (el) => {
    let node = el;
    while (node && node.nodeType === Node.ELEMENT_NODE && node !== document.body) {
      if (nodeIsArtifact(node)) return true;
      node = node.parentElement;
    }
    return false;
  };

  const visible = (el) => {
    const style = cs(el);
    if (style.display === "none" || style.visibility === "hidden" || style.visibility === "collapse") return false;
    if (effectiveOpacity(el) <= 0.01) return false;
    const rect = nowRect(el);
    return rect.width > 1 && rect.height > 1;
  };
  const hasVisibleElementChild = (el) => Array.from(el.children).some((child) => visible(child));
  const hasDirectText = (el) => {
    for (const node of el.childNodes) {
      if (node.nodeType === Node.TEXT_NODE && node.textContent && node.textContent.trim().length > 0) return true;
    }
    return false;
  };
  const isControl = (el) => el.matches(controlSelector);
  const isTextCandidate = (el) => el.matches(textSelector) && textOf(el).length > 0;
  const classicLeafText = (el) => isTextCandidate(el) && (!hasVisibleElementChild(el) || el.matches("h1,h2,h3,h4,h5,h6,p,li,td,th,label"));
  // Any element that directly owns rendered text (including div/section/dd/etc.)
  // is a text candidate; the fixed tag list alone misses most modern app text.
  const isLeafText = (el) => hasDirectText(el) || classicLeafText(el);

  const MAX_PER_RULE = 40;
  const ruleCounts = {};
  const suppressed = {};
  const add = (severity, rule, el, message, extra = {}) => {
    ruleCounts[rule] = (ruleCounts[rule] || 0) + 1;
    if (ruleCounts[rule] > MAX_PER_RULE) {
      suppressed[rule] = (suppressed[rule] || 0) + 1;
      return;
    }
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

  const SKIP_TAGS = new Set([
    "script", "style", "template", "noscript", "meta", "link", "title", "base",
    "br", "hr", "wbr", "source", "track", "param", "slot", "option", "optgroup",
    "datalist", "iframe", "object", "embed", "area", "map", "svg", "canvas", "portal",
  ]);
  const walkRoot = document.body || document.documentElement;
  const candidates = [];
  for (const el of walkRoot.querySelectorAll("*")) {
    if (SKIP_TAGS.has(el.localName) || el.ownerSVGElement) continue;
    if (isIgnored(el)) continue;
    const textLike = isControl(el) || isLeafText(el);
    if (!textLike && !el.matches("img,video")) continue;
    if (!visible(el)) {
      // Inventory text/controls that exist but are invisible so hidden-content
      // regressions are at least countable in evidence.
      if (textLike) {
        const style = cs(el);
        if (style.display === "none") hiddenTextLike.displayNone += 1;
        else if (style.visibility === "hidden" || style.visibility === "collapse") hiddenTextLike.visibilityHidden += 1;
        else if (effectiveOpacity(el) <= 0.01) hiddenTextLike.zeroOpacity += 1;
        else hiddenTextLike.zeroSize += 1;
      }
      continue;
    }
    candidates.push(el);
  }

  // Blind spots: querySelectorAll does not pierce open shadow roots and we do not
  // traverse iframe documents. Count them so the gap is visible in evidence rather
  // than silently reporting ~0 elements as clean.
  let shadowRootCount = 0;
  for (const el of document.querySelectorAll("*")) {
    if (el.shadowRoot) shadowRootCount += 1;
  }
  const iframeCount = document.querySelectorAll("iframe").length;
  const notInspected = { shadowRoots: shadowRootCount, iframes: iframeCount };
  if (shadowRootCount > 0 || iframeCount > 0) {
    findings.push({
      severity: "warning",
      rule: "not-inspected",
      message: `${shadowRootCount} shadow roots / ${iframeCount} iframes were not inspected; findings may be incomplete.`,
      selector: "document",
      textSnippet: "",
      rect: null,
      area: null,
      evidence: notInspected,
    });
  }

  const establishesContainingBlock = (style) =>
    style.position !== "static" ||
    style.transform !== "none" ||
    style.perspective !== "none" ||
    (style.filter && style.filter !== "none") ||
    (style.backdropFilter && style.backdropFilter !== "none") ||
    (style.contain || "").includes("paint") ||
    (style.contain || "").includes("layout") ||
    (style.willChange || "").includes("transform");
  const fixedContextCache = new WeakMap();
  const hasFixedContext = (el) => {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return false;
    const cached = fixedContextCache.get(el);
    if (cached !== undefined) return cached;
    const value = cs(el).position === "fixed" || hasFixedContext(el.parentElement);
    fixedContextCache.set(el, value);
    return value;
  };

  // Walks ancestors and reports content cut off by an ancestor's overflow
  // clipping. This is the common real-world crop: the element itself has
  // overflow visible, but a parent with overflow hidden/clip cuts it. Scrollable
  // ancestors on the cut axis count as a reachability path (not a defect), and
  // absolutely positioned elements skip ancestors outside their containing-block
  // chain because CSS does not clip them there.
  function ancestorClipReport(el) {
    const report = { scrollPathX: false, scrollPathY: false, cut: null };
    const elStyle = cs(el);
    if (elStyle.position === "fixed") return report;
    const rect = nowRect(el);
    // Content spills beyond the element's own box only when the element does not
    // clip/scroll that axis itself; a self-clipping element (ellipsis, hidden,
    // scrollable) is already handled by the self-overflow rule.
    const spillsX = elStyle.overflowX === "visible";
    const spillsY = elStyle.overflowY === "visible";
    const effRight = spillsX ? Math.max(rect.right, rect.left + (el.clientLeft || 0) + (el.scrollWidth || 0)) : rect.right;
    const effBottom = spillsY ? Math.max(rect.bottom, rect.top + (el.clientTop || 0) + (el.scrollHeight || 0)) : rect.bottom;
    const box = { left: rect.left, top: rect.top, right: effRight, bottom: effBottom };
    const width = Math.max(1, box.right - box.left);
    const height = Math.max(1, box.bottom - box.top);
    let carouselContext = CAROUSEL_TOKENS.test(markerText(el));
    let awaitingContainingBlock = elStyle.position === "absolute";
    let node = el.parentElement;
    while (node && node.nodeType === Node.ELEMENT_NODE) {
      const style = cs(node);
      if (!carouselContext && CAROUSEL_TOKENS.test(markerText(node))) carouselContext = true;
      const isContainingBlock = establishesContainingBlock(style);
      if (awaitingContainingBlock && !isContainingBlock) {
        node = node.parentElement;
        continue;
      }
      awaitingContainingBlock = false;
      const scrollableX = ["auto", "scroll", "overlay"].includes(style.overflowX);
      const scrollableY = ["auto", "scroll", "overlay"].includes(style.overflowY);
      const clipsX = ["hidden", "clip"].includes(style.overflowX) && !report.scrollPathX;
      const clipsY = ["hidden", "clip"].includes(style.overflowY) && !report.scrollPathY;
      if (clipsX || clipsY) {
        const nodeRect = nowRect(node);
        const clip = {
          left: nodeRect.left + (node.clientLeft || 0),
          top: nodeRect.top + (node.clientTop || 0),
        };
        clip.right = clip.left + node.clientWidth;
        clip.bottom = clip.top + node.clientHeight;
        const cutLeft = clipsX ? Math.max(0, clip.left - box.left) : 0;
        const cutRight = clipsX ? Math.max(0, box.right - clip.right) : 0;
        const cutTop = clipsY ? Math.max(0, clip.top - box.top) : 0;
        const cutBottom = clipsY ? Math.max(0, box.bottom - clip.bottom) : 0;
        const maxCut = Math.max(cutLeft, cutRight, cutTop, cutBottom);
        const visX = clipsX ? Math.max(0, Math.min(box.right, clip.right) - Math.max(box.left, clip.left)) / width : 1;
        const visY = clipsY ? Math.max(0, Math.min(box.bottom, clip.bottom) - Math.max(box.top, clip.top)) / height : 1;
        const cutFraction = 1 - visX * visY;
        if (maxCut > 4 && cutFraction > 0.08) {
          report.cut = {
            clipperSelector: selectorPath(node),
            cutLeft: round(cutLeft),
            cutRight: round(cutRight),
            cutTop: round(cutTop),
            cutBottom: round(cutBottom),
            cutFraction: round(cutFraction),
            fullyHidden: visX <= 0 || visY <= 0,
            singleLineEllipsis:
              style.textOverflow === "ellipsis" && style.whiteSpace === "nowrap" && cutTop === 0 && cutBottom === 0,
            lineClamp: Boolean(style.webkitLineClamp && style.webkitLineClamp !== "none"),
            carouselContext,
            overflowX: style.overflowX,
            overflowY: style.overflowY,
          };
          return report;
        }
      }
      if (scrollableX) report.scrollPathX = true;
      if (scrollableY) report.scrollPathY = true;
      if (style.position === "fixed") break;
      if (style.position === "absolute") awaitingContainingBlock = true;
      node = node.parentElement;
    }
    return report;
  }

  for (const el of candidates) {
    const style = cs(el);
    const rect = nowRect(el);
    const text = textOf(el);
    const complexArtifact = complexArtifactContext(el);
    const isSingleLineEllipsis = style.textOverflow === "ellipsis" && style.whiteSpace === "nowrap";
    const lineClampAllowed = Boolean(style.webkitLineClamp && style.webkitLineClamp !== "none");
    const allowedTruncation = truncationReason(el);
    const meaningful = isControl(el) || isLeafText(el);
    if (meaningful && text) {
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
      } else if ((clipsX || clipsY) && !(allowedTruncation || (!config.rules.strictTruncation && (isSingleLineEllipsis || lineClampAllowed)))) {
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
      } else if ((clipsX || clipsY) && ellipsisTruncations.length < 100) {
        ellipsisTruncations.push({
          selector: selectorPath(el),
          textSnippet: snippet(el),
          kind: isSingleLineEllipsis ? "text-overflow-ellipsis" : "line-clamp",
        });
      }
    }

    // Ancestor clipping: the element itself may not clip, but a parent's
    // overflow hidden/clip can still cut it (the most common crop mechanism).
    let geo = null;
    if (meaningful && (text || isControl(el))) {
      geo = ancestorClipReport(el);
      const cut = geo.cut;
      if (cut) {
        const evidence = { evidence: cut };
        if (cut.singleLineEllipsis && !config.rules.strictTruncation && cut.cutTop === 0 && cut.cutBottom === 0) {
          if (ellipsisTruncations.length < 100) {
            ellipsisTruncations.push({ selector: selectorPath(el), textSnippet: snippet(el), kind: "ancestor-text-overflow-ellipsis" });
          }
        } else if (cut.lineClamp && !config.rules.strictTruncation) {
          if (ellipsisTruncations.length < 100) {
            ellipsisTruncations.push({ selector: selectorPath(el), textSnippet: snippet(el), kind: "ancestor-line-clamp" });
          }
        } else if (allowedTruncation) {
          add("warning", "allowed-truncation", el, "Content is cut by an ancestor clip but has an explicit truncation allowance.", {
            evidence: { reason: allowedTruncation, ...cut },
          });
        } else if (complexArtifact) {
          add("warning", "complex-artifact-overflow", el, "Complex map/chart/media internals are cut by an ancestor clip; review visually if this artifact is the primary content.", evidence);
        } else if (cut.fullyHidden) {
          add("warning", "clipped-hidden", el, "Text/control is fully hidden by an ancestor's overflow clipping; verify this state is intentional.", evidence);
        } else if (cut.carouselContext) {
          add("warning", "clipped-by-ancestor", el, "Text/control is partially cut by an ancestor clip inside a carousel/slider context.", evidence);
        } else {
          add("critical", "clipped-by-ancestor", el, "Visible text/control is cut by an ancestor's overflow clipping without a scroll path or allowance.", evidence);
        }
      }
    }

    // Off-canvas geometry. Fixed-context content cannot be scrolled into view,
    // so any viewport cut is a defect. Static/absolute content before the
    // document origin (negative document coordinates) is equally unreachable.
    if (meaningful && !complexArtifact) {
      if (hasFixedContext(el)) {
        const cutLeft = Math.max(0, -rect.left);
        const cutRight = Math.max(0, rect.right - window.innerWidth);
        const cutTop = Math.max(0, -rect.top);
        const cutBottom = Math.max(0, rect.bottom - window.innerHeight);
        const visW = Math.max(0, Math.min(rect.right, window.innerWidth) - Math.max(rect.left, 0));
        const visH = Math.max(0, Math.min(rect.bottom, window.innerHeight) - Math.max(rect.top, 0));
        const maxCut = Math.max(cutLeft, cutRight, cutTop, cutBottom);
        const cutFraction = 1 - (visW * visH) / Math.max(1, rect.width * rect.height);
        if (visW <= 0 || visH <= 0) {
          add("warning", "fixed-offscreen-hidden", el, "Fixed-position text/control is entirely outside the viewport and cannot be scrolled to; verify this state is intentional.", {
            evidence: { viewportWidth: window.innerWidth, viewportHeight: window.innerHeight },
          });
        } else if (maxCut > 4 && cutFraction > 0.08) {
          add("critical", "fixed-offscreen-cut", el, "Fixed-position text/control is partially cut by the viewport edge and cannot be scrolled into view.", {
            evidence: {
              cutLeft: round(cutLeft),
              cutRight: round(cutRight),
              cutTop: round(cutTop),
              cutBottom: round(cutBottom),
              viewportWidth: window.innerWidth,
              viewportHeight: window.innerHeight,
            },
          });
        }
      } else {
        const rtl = (document.documentElement.getAttribute("dir") || "").toLowerCase() === "rtl";
        const absLeft = rect.left + window.scrollX;
        const absTop = rect.top + window.scrollY;
        const cutLeft = rtl ? 0 : Math.max(0, -absLeft);
        const cutTop = Math.max(0, -absTop);
        if ((cutLeft > 4 && cutLeft / Math.max(1, rect.width) > 0.08) || (cutTop > 4 && cutTop / Math.max(1, rect.height) > 0.08)) {
          const fullyOut = absLeft + rect.width <= 0 || absTop + rect.height <= 0;
          if (fullyOut) {
            add("warning", "offcanvas-hidden", el, "Text/control is positioned entirely before the document origin (possible visually-hidden pattern); verify it is intentional.", {
              evidence: { documentLeft: round(absLeft), documentTop: round(absTop) },
            });
          } else {
            add("critical", "offcanvas-cut", el, "Text/control is partially cut by the document edge and cannot be scrolled into view.", {
              evidence: { documentLeft: round(absLeft), documentTop: round(absTop), cutLeft: round(cutLeft), cutTop: round(cutTop) },
            });
          }
        }
        if (isControl(el) && rect.left > window.innerWidth + 2 && !(geo && geo.scrollPathX)) {
          const reachableByDocScroll = rect.left + window.scrollX < doc.scrollWidth - 2;
          if (!reachableByDocScroll) {
            add("critical", "interactive-offscreen-x", el, "Interactive element is outside the horizontal viewport and beyond the document scroll range.", {
              evidence: { viewportWidth: window.innerWidth, documentScrollWidth: doc.scrollWidth },
            });
          }
        }
      }
    }

    for (const area of configuredAreaRoots) {
      if (area.el === el || area.el.contains(el)) {
        const areaRect = nowRect(area.el);
        if (rect.left < areaRect.left - 2 || rect.right > areaRect.right + 2 || rect.top < areaRect.top - 2 || rect.bottom > areaRect.bottom + 2) {
          add(meaningful ? "critical" : "warning", "outside-area", el, "Element is rendered outside its declared area of interest.", {
            area: area.name,
            evidence: { areaRect: rectObj(areaRect) },
          });
        }
      }
    }
    if (meaningful && text && !complexArtifact) {
      const contrast = contrastAgainstBackground(el);
      if (contrast.transparentText) {
        add("critical", "invisible-text", el, "Text is effectively transparent.", { evidence: contrast });
      } else if (contrast.unmeasurable) {
        // Effective background is a gradient/image or a translucent stack: contrast
        // against white would be a false positive, so never emit a critical here.
        if (unmeasurableContrast.length < 200) {
          unmeasurableContrast.push({
            selector: selectorPath(el),
            reason: contrast.unmeasurableReason || "unmeasurable-background",
            color: contrast.color,
            backgroundColor: contrast.backgroundColor,
          });
        }
        add("warning", "unmeasurable-contrast", el, "Text contrast could not be measured against a solid background; review visually.", { evidence: contrast });
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

  // Media health runs over every img/video that participates in rendering,
  // regardless of rect size: a broken image usually collapses to ~0x0, which is
  // exactly why it must not be filtered out by the visibility size gate.
  for (const el of document.querySelectorAll("img,video")) {
    if (isIgnored(el)) continue;
    const style = cs(el);
    if (style.display === "none" || style.visibility === "hidden" || style.visibility === "collapse") continue;
    if (effectiveOpacity(el) <= 0.01) continue;
    if (el.localName === "img") {
      if (el.complete && el.naturalWidth === 0 && (el.currentSrc || el.getAttribute("src"))) {
        const rect = nowRect(el);
        add("critical", "broken-image", el, "Image failed to load.", {
          evidence: {
            currentSrc: el.currentSrc || el.src,
            rect: rectObj(rect),
            collapsed: rect.width <= 1 || rect.height <= 1,
          },
        });
      } else if (!el.complete) {
        pendingMedia += 1;
      }
    } else if (el.error) {
      add("critical", "broken-video", el, "Visible video has a media error.", { evidence: { code: el.error.code } });
    }
  }

  const occlusionCandidates = [
    ...candidates.filter((el) => isControl(el) && !overlapReason(el) && !complexArtifactContext(el)),
    ...candidates.filter((el) => !isControl(el) && isLeafText(el) && !overlapReason(el) && !complexArtifactContext(el)),
  ].slice(0, 400);
  const originalScroll = { x: window.scrollX, y: window.scrollY };
  const inViewport = (rect) =>
    rect.bottom > 0 && rect.right > 0 && rect.top < window.innerHeight && rect.left < window.innerWidth;
  const occluderOpacity = (node) => {
    // Effective opacity of an occluder for the purpose of "does it hide content":
    // combine element opacity with its own background-color alpha. Low values mean
    // the covered content can plausibly still be seen through the occluder.
    let ancestorOpacity = 1;
    let walk = node;
    while (walk && walk.nodeType === Node.ELEMENT_NODE) {
      ancestorOpacity *= Number(getComputedStyle(walk).opacity || 1);
      walk = walk.parentElement;
    }
    const bg = parseCssColor(getComputedStyle(node).backgroundColor);
    const bgAlpha = bg ? bg.a : 0;
    return ancestorOpacity * bgAlpha;
  };
  for (const el of occlusionCandidates) {
    if (!document.body.contains(el) || !visible(el)) continue;
    let measuredAfterScroll = false;
    if (!inViewport(nowRect(el))) {
      // Only elements outside the current viewport may be scrolled into view; those
      // are flagged so the finding reflects "occluded when scrolled to" not "as seen".
      el.scrollIntoView({ block: "center", inline: "center" });
      measuredAfterScroll = true;
    }
    const rect = nowRect(el);
    if (rect.width <= 1 || rect.height <= 1) continue;
    const insetX = Math.min(8, Math.max(2, rect.width / 4));
    const insetY = Math.min(8, Math.max(2, rect.height / 4));
    const points = [
      { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 },
      { x: rect.left + insetX, y: rect.top + insetY },
      { x: rect.right - insetX, y: rect.top + insetY },
      { x: rect.left + insetX, y: rect.bottom - insetY },
      { x: rect.right - insetX, y: rect.bottom - insetY },
    ].filter((point) => point.x >= 0 && point.y >= 0 && point.x <= window.innerWidth && point.y <= window.innerHeight);
    if (points.length < 2) continue;
    let covered = 0;
    let maxOccluderOpacity = 0;
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
      if (!ok) {
        covered += 1;
        if (top) maxOccluderOpacity = Math.max(maxOccluderOpacity, occluderOpacity(top));
      }
    }
    if (covered >= 2) {
      const coveredFraction = covered / points.length;
      // A translucent occluder may still leave the content legible: warn instead of fail.
      const lowOpacityOccluder = maxOccluderOpacity < 0.5;
      const evidence = {
        evidence: {
          samplePoints: evidencePoints,
          measuredAfterScroll,
          occluderOpacity: round(maxOccluderOpacity),
          coveredFraction: round(coveredFraction),
        },
      };
      if (covered === points.length) {
        add(lowOpacityOccluder ? "warning" : "critical", "occluded", el, "Meaningful text/control appears fully covered by an unrelated element.", evidence);
      } else if (coveredFraction >= 0.6) {
        add(lowOpacityOccluder ? "warning" : "critical", "partially-occluded", el, "Meaningful text/control is substantially covered by an unrelated element.", evidence);
      } else {
        add("warning", "partially-occluded", el, "Meaningful text/control is partially covered by an unrelated element.", evidence);
      }
    }
  }
  window.scrollTo(originalScroll.x, originalScroll.y);

  const suppressedTotal = Object.values(suppressed).reduce((total, count) => total + count, 0);
  if (suppressedTotal > 0) {
    findings.push({
      severity: "warning",
      rule: "findings-truncated",
      message: `${suppressedTotal} additional findings were suppressed after the per-rule cap of ${MAX_PER_RULE}; fix the reported instances and re-run.`,
      selector: "document",
      textSnippet: "",
      rect: null,
      area: null,
      evidence: { suppressed },
    });
  }

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
  // Walk ancestors accumulating solid background layers. Returns a resolved opaque
  // background color only when the chain up to the first opaque layer is a genuine
  // stack of solid colors. If any ancestor in that chain paints a non-'none'
  // background-image (gradient/image) or the accumulated alpha never reaches opaque,
  // the effective background cannot be measured against white: return unmeasurable.
  function backgroundFor(el) {
    let node = el;
    let accum = null; // color painted so far, over an unknown backdrop
    while (node && node.nodeType === Node.ELEMENT_NODE) {
      const style = getComputedStyle(node);
      if (style.backgroundImage && style.backgroundImage !== "none") {
        return { unmeasurable: true, reason: "background-image/gradient", raw: style.backgroundImage };
      }
      const bg = parseCssColor(style.backgroundColor);
      if (bg && bg.a > 0.001) {
        if (bg.a >= 0.999) {
          const solid = accum ? blended(accum, bg) : bg;
          return { r: solid.r, g: solid.g, b: solid.b, a: 1, raw: bg.raw };
        }
        // Semi-transparent layer: composite over whatever accumulates below it.
        accum = accum ? blended(accum, bg) : { ...bg };
      }
      node = node.parentElement;
    }
    // Reached the root without an opaque solid backdrop.
    return { unmeasurable: true, reason: "translucent-stack", raw: accum ? accum.raw || "translucent" : "no-solid-background" };
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
    if (bg.unmeasurable) {
      return {
        ratio: null,
        color: fg.raw,
        backgroundColor: bg.raw,
        transparentText: false,
        unmeasurable: true,
        unmeasurableReason: bg.reason,
      };
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
      unmeasurableContrast,
      notInspected,
      ellipsisTruncations,
      hiddenTextLike,
      pendingMedia,
      suppressedFindings: suppressed,
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
  let scrollMetrics = { skipped: true };
  if (config.scroll) {
    scrollMetrics = await scrollThroughPage(page).catch(() => ({ skipped: true, error: true }));
  }
  const evaluated = await page.evaluate(pageVerifier);
  result.title = evaluated.title;
  result.url = evaluated.url;
  result.actualViewport = evaluated.viewport;
  result.metrics = { ...evaluated.metrics, scroll: scrollMetrics };
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
  lines.push("", "## Coverage & Unmeasurable", "");
  const coverageRows = [];
  for (const page of report.pages) {
    const notInspected = page.metrics?.notInspected;
    const scroll = page.metrics?.scroll;
    const unmeasurable = page.metrics?.unmeasurableContrast || [];
    const ellipsis = page.metrics?.ellipsisTruncations || [];
    const hidden = page.metrics?.hiddenTextLike || {};
    const pending = page.metrics?.pendingMedia || 0;
    if (page.skipped && !notInspected && !scroll) continue;
    const label = `${page.target.name || page.target.url} (${page.viewport.name})`;
    const shadow = notInspected ? notInspected.shadowRoots : 0;
    const iframes = notInspected ? notInspected.iframes : 0;
    const hiddenTotal = (hidden.displayNone || 0) + (hidden.visibilityHidden || 0) + (hidden.zeroOpacity || 0) + (hidden.zeroSize || 0);
    const scrollNote = scroll && !scroll.skipped
      ? `scrolled to ${scroll.scrolledTo}px over ${scroll.scrollPasses} pass(es)${scroll.capped ? " (capped)" : ""}`
      : "scroll off";
    coverageRows.push({ label, shadow, iframes, unmeasurable: unmeasurable.length, ellipsis: ellipsis.length, hiddenTotal, pending, scrollNote });
  }
  if (!coverageRows.length) {
    lines.push("No coverage gaps recorded.");
  } else {
    lines.push("| Target | Shadow roots (not inspected) | Iframes (not inspected) | Unmeasurable contrast | Allowed ellipsis/clamp | Hidden text/controls | Pending media | Scroll pass |");
    lines.push("| --- | --- | --- | --- | --- | --- | --- | --- |");
    for (const row of coverageRows) {
      lines.push(`| ${escapeMd(row.label)} | ${row.shadow} | ${row.iframes} | ${row.unmeasurable} | ${row.ellipsis} | ${row.hiddenTotal} | ${row.pending} | ${escapeMd(row.scrollNote)} |`);
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
        const page = await browser.newPage(config.ignoreHttpsErrors ? { ignoreHTTPSErrors: true } : {});
        try {
          if (config.cookies.length) {
            await page.context().addCookies(
              config.cookies.map((cookie) => ({
                name: cookie.name,
                value: cookie.value,
                ...(cookie.domain
                  ? { domain: cookie.domain, path: cookie.path || "/" }
                  : { url: cookie.url || target.url }),
              })),
            );
          }
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
