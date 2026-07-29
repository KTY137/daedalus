const vscode = require("vscode");
const fs = require("fs");
const path = require("path");
const cp = require("child_process");
const http = require("http");

let projectProvider;
let queueProvider;
let dashboardProvider;
let dashboardPanel;
let watcherTerminal;
let statusBar;
let webServerProcess;
const WEB_HOST = "127.0.0.1";
const WEB_PORT = 8765;

function cfg() {
  return vscode.workspace.getConfiguration("daedalus");
}

function exists(p) {
  try { return fs.existsSync(p); } catch (_) { return false; }
}

function isHarnessRoot(p) {
  return Boolean(p) && exists(path.join(p, "daedalus", "file_bridge.py"));
}

function harnessRoot(context) {
  const configured = cfg().get("root");
  if (configured && isHarnessRoot(configured)) return configured;
  const fromExtension = path.resolve(context.extensionPath, "..");
  if (isHarnessRoot(fromExtension)) return fromExtension;
  if (isHarnessRoot(context.extensionPath)) return context.extensionPath;
  for (const folder of vscode.workspace.workspaceFolders || []) {
    if (isHarnessRoot(folder.uri.fsPath)) return folder.uri.fsPath;
    const sibling = path.join(path.dirname(folder.uri.fsPath), "daedalus");
    if (isHarnessRoot(sibling)) return sibling;
  }
  return "";
}

function python() {
  return cfg().get("python") || "python";
}

function runPython(context, args, opts = {}) {
  const root = harnessRoot(context);
  if (!root) return Promise.reject(new Error("Cannot find daedalus root. Set daedalus.root in VS Code settings."));
  return new Promise((resolve, reject) => {
    cp.execFile(python(), args, { cwd: root, timeout: opts.timeout || 30000, windowsHide: true }, (error, stdout, stderr) => {
      if (error) reject(new Error((stderr || stdout || error.message).trim()));
      else resolve(String(stdout || "").trim());
    });
  });
}

async function runJson(context, args, opts = {}) {
  const raw = await runPython(context, args, opts);
  try { return JSON.parse(raw); } catch (_) { throw new Error(`Expected JSON from ${args.join(" ")}: ${raw.slice(0, 500)}`); }
}

function terminal(context, name, args) {
  const root = harnessRoot(context);
  const term = vscode.window.createTerminal({ name, cwd: root || undefined, hideFromUser: false });
  const escaped = args.map((a) => (/\s/.test(a) ? `"${String(a).replace(/"/g, '\\"')}"` : a)).join(" ");
  term.sendText(`${python()} ${escaped}`);
  term.show();
  return term;
}

function webUrl(project) {
  const params = new URLSearchParams({ vscode: "1" });
  if (project) params.set("project", project);
  return `http://${WEB_HOST}:${WEB_PORT}/?${params.toString()}`;
}

function probeWebServer() {
  return new Promise((resolve) => {
    const req = http.get(`http://${WEB_HOST}:${WEB_PORT}/api/projects`, { timeout: 1200 }, (res) => {
      res.resume();
      resolve(res.statusCode >= 200 && res.statusCode < 500);
    });
    req.on("timeout", () => { req.destroy(); resolve(false); });
    req.on("error", () => resolve(false));
  });
}

// Thrown by ensureWebServer with a CLASSIFIED cause instead of one generic
// message, because "the backend isn't answering" collapses three different
// honest states into one otherwise: never spawned (absent), spawned then
// died (degraded -- and we captured why), or spawned and is still alive but
// hasn't answered yet (genuinely unknown, not a failure). A UI that cannot
// tell these apart cannot render them as anything but a scary blank.
class BackendUnavailable extends Error {
  constructor(state, message, detail) {
    super(message);
    this.state = state; // 'absent' | 'degraded' | 'unknown'
    this.detail = detail || "";
  }
}

async function ensureWebServer(context) {
  if (await probeWebServer()) return;
  const root = harnessRoot(context);
  if (!root) {
    // No `detail` on purpose: backendStateHtml already renders a dedicated,
    // always-visible remediation line whenever `root` comes back empty --
    // repeating the same sentence again inside a collapsed <details> would
    // hide it behind a click instead of adding information.
    throw new BackendUnavailable("absent", "Cannot find the daedalus root.", "");
  }
  let stderrTail = "";
  let spawnError = null;
  let exited = false;
  try {
    webServerProcess = cp.spawn(
      python(),
      ["-m", "daedalus.cli", "web", "--host", WEB_HOST, "--port", String(WEB_PORT)],
      { cwd: root, windowsHide: true, detached: false, stdio: ["ignore", "ignore", "pipe"] }
    );
  } catch (err) {
    throw new BackendUnavailable("absent", `Failed to launch "${python()}".`, String(err.message || err));
  }
  const proc = webServerProcess;
  proc.stderr.on("data", (chunk) => { stderrTail = (stderrTail + chunk.toString()).slice(-4000); });
  proc.on("error", (err) => { spawnError = err; });
  proc.on("exit", () => { exited = true; });
  for (let i = 0; i < 20; i += 1) {
    await new Promise((resolve) => setTimeout(resolve, 250));
    if (spawnError) {
      throw new BackendUnavailable("absent", `Could not start "${python()}".`, String(spawnError.message || spawnError));
    }
    if (await probeWebServer()) return;
    if (exited) {
      // MEASURED distinction this class exists for: a process that reported
      // healthy right up until it died is not the same claim as one that is
      // still running -- the UI must not describe both as "starting up".
      throw new BackendUnavailable(
        "degraded",
        "The Ikarus backend process exited before it answered.",
        stderrTail || "(process exited with no output captured)"
      );
    }
  }
  throw new BackendUnavailable(
    "unknown",
    "The Ikarus backend did not respond within 5s.",
    stderrTail || "(no output captured; the process is still running)"
  );
}

// Explicit user action (a right-click / command-palette invocation), so
// spawning the backend on demand here is fine -- unlike QueueProvider's tree
// render below, which must never surprise-launch a process just because a
// folder was expanded.
async function ensureWebServerForCommand(context) {
  try {
    await ensureWebServer(context);
    return true;
  } catch (err) {
    const detail = err instanceof BackendUnavailable ? err.detail : "";
    const firstDetailLine = detail ? detail.split("\n")[0] : "";
    vscode.window.showErrorMessage(`Ikarus backend unavailable: ${err.message}${firstDetailLine ? " -- " + firstDetailLine : ""}`);
    return false;
  }
}

// ---------------------------------------------------------------------------
// Task lifecycle client: GET /api/queue/<id> [/artifacts | /events]. Additive
// endpoints landed 2026-07-29 in daedalus/web_api.py's "task lifecycle"
// section -- read that section's docstring for the full vocabulary
// (queued/running/done/failed/quarantined/unknown) and why `applied` is
// tri-state. Every helper here degrades exactly like probeWebServer() /
// ensureWebServer() already do: a server that predates these endpoints, or
// simply is not running, must read as "no live status available" -- never as
// a false "done" or "failed". Nothing here ever guesses.
// ---------------------------------------------------------------------------
const TASK_ID_RE = /^[A-Za-z0-9._-]{1,160}$/; // mirrors web_api.py's _TASK_ID_RE

function apiGet(urlPath, timeoutMs = 1500) {
  return new Promise((resolve) => {
    const req = http.get(`http://${WEB_HOST}:${WEB_PORT}${urlPath}`, { timeout: timeoutMs }, (res) => {
      res.setEncoding("utf8");
      let raw = "";
      res.on("data", (chunk) => { raw += chunk; });
      res.on("end", () => {
        let body = null;
        try { body = JSON.parse(raw); } catch (_) { body = null; }
        resolve({ ok: res.statusCode >= 200 && res.statusCode < 300, status: res.statusCode, body });
      });
    });
    req.on("timeout", () => { req.destroy(); resolve({ ok: false, status: 0, body: null, error: "timeout" }); });
    req.on("error", (err) => resolve({ ok: false, status: 0, body: null, error: String(err.message || err) }));
  });
}

// The file bus names task files `<id>.json` (outbox, runs/processed) or
// `<id>.report.json` (inbox) -- `id` IS the filename stem, nothing new is
// minted here (see web_api.py's own "THE HONESTY RULE THIS SECTION IS BUILT
// TO" comment, right above _task_snapshot).
function taskIdFromFilename(name) {
  if (typeof name !== "string") return null;
  if (name.endsWith(".report.json")) return name.slice(0, -".report.json".length);
  if (name.endsWith(".json")) return name.slice(0, -".json".length);
  return null;
}

function shortAge(ageS) {
  if (ageS === null || ageS === undefined || Number.isNaN(ageS)) return "age unknown";
  if (ageS < 5) return "just now";
  if (ageS < 90) return `${Math.round(ageS)}s ago`;
  if (ageS < 5400) return `${Math.round(ageS / 60)}m ago`;
  return `${Math.round(ageS / 3600)}h ago`;
}

// THE property that matters more than anything else rendered by this file:
// `applied` is TRUE / FALSE / null-with-a-reason (daedalus/web_api.py
// `_derive_applied` never guesses true). null must never be rendered as
// either of the other two, and the reason string travels with it always.
function appliedWord(snap) {
  if (snap.applied === true) return "applied";
  if (snap.applied === false) return "NOT applied";
  return "applied: unknown";
}
function appliedLine(snap) {
  return `${appliedWord(snap)} -- ${snap.applied_reason || "no reason given"}`;
}

// A snapshot is a photograph, not a promise -- age_s rides along on every
// rendering of one so a four-minute-old "running" cannot be mistaken for a
// live one (see the section docstring's own framing of this incident class).
function describeSnapshot(snap) {
  const stalledTag = snap.stalled ? " [STALLED]" : "";
  return `${snap.state}${stalledTag} · ${shortAge(snap.age_s)}`;
}

function snapshotTooltip(snap) {
  const lines = [snap.id,
    `State: ${snap.state} (source: ${snap.source || "n/a"})`,
    `Observed: ${snap.observed_at || "n/a"} (${shortAge(snap.age_s)})`];
  if (snap.stalled) lines.push("STALLED -- no progress observed recently.");
  lines.push(appliedLine(snap));
  if (snap.summary) lines.push(`Summary: ${snap.summary}`);
  if (snap.error) lines.push(`Error: ${snap.error}`);
  if (snap.objective) lines.push(`Objective: ${snap.objective}`);
  lines.push(`Lane: ${snap.lane || "n/a"}  Project: ${snap.project || "n/a"}`);
  return lines.join("\n");
}

// Three VISUALLY distinct outcomes for a finished task -- applied / not
// applied / unknown-why -- matching appliedWord() above; "unknown" must never
// collapse into either a pass or a fail glyph. `stalled` overrides everything
// else: a stalled run in progress is the single most actionable state here.
function stateThemeIcon(snap) {
  if (snap.stalled) return new vscode.ThemeIcon("warning", new vscode.ThemeColor("editorWarning.foreground"));
  switch (snap.state) {
    case "running": return new vscode.ThemeIcon("sync", new vscode.ThemeColor("charts.blue"));
    case "queued": return new vscode.ThemeIcon("clock", new vscode.ThemeColor("descriptionForeground"));
    case "failed": return new vscode.ThemeIcon("error", new vscode.ThemeColor("testing.iconFailed"));
    case "quarantined": return new vscode.ThemeIcon("circle-slash", new vscode.ThemeColor("testing.iconFailed"));
    case "done":
      if (snap.applied === true) return new vscode.ThemeIcon("pass-filled", new vscode.ThemeColor("testing.iconPassed"));
      if (snap.applied === false) return new vscode.ThemeIcon("circle-slash", new vscode.ThemeColor("editorWarning.foreground"));
      return new vscode.ThemeIcon("question", new vscode.ThemeColor("editorWarning.foreground"));
    default: return new vscode.ThemeIcon("question", new vscode.ThemeColor("descriptionForeground"));
  }
}

// SSE client for GET /api/queue/<id>/events. Node has no built-in
// EventSource, so this parses the same "event: X\ndata: {...}\n\n" framing
// daedalus/web_api.py's _handle_task_events emits by hand. ONE-SHOT, exactly
// like the server contract: reading stops after 'final', after a non-2xx
// response (an old server without this endpoint answers 404 JSON, not SSE --
// checked explicitly below rather than fed into the frame parser), or on a
// transport error. There is no reconnect logic here to accidentally re-poll
// a finished task forever.
function watchTaskEvents(taskId, onEvent, onDone) {
  const req = http.get(`http://${WEB_HOST}:${WEB_PORT}/api/queue/${encodeURIComponent(taskId)}/events`, (res) => {
    res.setEncoding("utf8");
    if (res.statusCode !== 200) {
      let body = "";
      res.on("data", (chunk) => { body += chunk; });
      res.on("end", () => onDone(new Error(`HTTP ${res.statusCode}: ${body.slice(0, 300)}`)));
      return;
    }
    let buf = "";
    res.on("data", (chunk) => {
      buf += chunk;
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const raw = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        const eventMatch = /^event:\s?(.*)$/m.exec(raw);
        const dataMatch = /^data:\s?(.*)$/m.exec(raw);
        if (!dataMatch) continue;
        const eventName = eventMatch ? eventMatch[1].trim() : "message";
        let data = dataMatch[1];
        try { data = JSON.parse(data); } catch (_) { /* keep raw string */ }
        onEvent(eventName, data);
      }
    });
    res.on("end", () => onDone(null));
  });
  req.on("error", (err) => onDone(err));
  return { cancel: () => req.destroy() };
}

function agentOsHtml(project) {
  const url = webUrl(project);
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    html, body { padding: 0; margin: 0; width: 100%; height: 100%; overflow: hidden; background: #070b12; }
    .bar {
      height: 34px; display: flex; align-items: center; justify-content: space-between; gap: 8px;
      padding: 0 10px; color: #d7e4f5; background: #0b111c; border-bottom: 1px solid rgba(151,171,210,.18);
      font: 12px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .bar a { color: #44d7e8; text-decoration: none; }
    iframe { width: 100%; height: calc(100% - 34px); border: 0; display: block; }
  </style>
</head>
<body>
  <div class="bar">
    <span>Daedalus Agent OS${project ? ` · ${project}` : ""}</span>
    <a href="${url}">Open in browser</a>
  </div>
  <iframe src="${url}" title="Daedalus Agent OS"></iframe>
</body>
</html>`;
}

// Five words, reused verbatim from the governance vocabulary the rest of the
// product already renders (GovernanceState in apps/web/src/types.ts): this
// widget answers one narrower question -- "is the Ikarus backend process
// reachable" -- but it must not invent a second, incompatible way to say
// "we do not know". 'checking' is the local addition: an in-flight probe is
// neither a pass nor a fail and must not be silently rendered as either.
const BACKEND_STATE_META = {
  checking: { glyph: "&#9679;", tone: "muted", label: "checking", headline: "Checking Ikarus backend…" },
  unknown: { glyph: "?", tone: "warn", label: "unknown", headline: "Ikarus backend: unknown" },
  degraded: { glyph: "&#9888;", tone: "danger", label: "degraded", headline: "Ikarus backend: degraded" },
  absent: { glyph: "&#10007;", tone: "danger", label: "absent", headline: "Ikarus backend: not running" }
};

// Rendered INSIDE the panel while ensureWebServer() is settling, and again
// on failure instead of leaving the webview blank. Deliberately not a
// spinner: a spinner implies measured progress, and nothing here has been
// measured yet beyond "did the last probe answer". A static state word does
// not make that false claim.
function backendStateHtml(n, state, info) {
  info = info || {};
  const meta = BACKEND_STATE_META[state] || BACKEND_STATE_META.unknown;
  const showRetry = state !== "checking";
  const message = info.message ? escapeHtml(info.message) : "";
  const detail = info.detail ? escapeHtml(info.detail) : "";
  const root = info.root ? escapeHtml(info.root) : "";
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${n}';">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Daedalus Ikarus</title>
<style>
  html, body { margin: 0; padding: 0; height: 100%; }
  body { font-family: var(--vscode-font-family); font-size: 13px; color: var(--vscode-foreground); background: var(--vscode-editor-background); display: flex; align-items: center; justify-content: center; }
  .wrap { max-width: 480px; padding: 24px; display: flex; flex-direction: column; gap: 10px; }
  .head { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 600; }
  .glyph.tone-muted { color: var(--vscode-descriptionForeground); }
  .glyph.tone-warn { color: var(--vscode-editorWarning-foreground); }
  .glyph.tone-danger { color: var(--vscode-testing-iconFailed); }
  .state-word { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; padding: 2px 8px; border-radius: 999px; border: 1px solid var(--vscode-panel-border); color: var(--vscode-descriptionForeground); }
  p { margin: 0; color: var(--vscode-descriptionForeground); line-height: 1.5; }
  code { font-family: ui-monospace, "Cascadia Mono", Consolas, monospace; }
  pre { white-space: pre-wrap; word-break: break-word; background: var(--vscode-textCodeBlock-background); padding: 8px 10px; border-radius: 4px; max-height: 180px; overflow: auto; font-size: 12px; margin: 0; }
  button { align-self: flex-start; background: var(--vscode-button-background); color: var(--vscode-button-foreground); border: 0; border-radius: 4px; padding: 6px 14px; cursor: pointer; font-size: 13px; }
  button:hover { background: var(--vscode-button-hoverBackground); }
  details summary { cursor: pointer; color: var(--vscode-descriptionForeground); font-size: 12px; }
  :focus-visible { outline: 2px solid var(--vscode-focusBorder); outline-offset: 2px; }
</style>
</head>
<body>
  <div class="wrap">
    <div class="head"><span class="glyph tone-${meta.tone}">${meta.glyph}</span><span>${meta.headline}</span><span class="state-word">${meta.label}</span></div>
    ${message ? "<p>" + message + "</p>" : ""}
    ${root ? "<p>Harness root: <code>" + root + "</code></p>" : "<p>No daedalus root resolved yet. Set <code>daedalus.root</code> in VS Code settings, or open a workspace folder that contains the daedalus harness.</p>"}
    ${detail ? "<details><summary>Details</summary><pre>" + detail + "</pre></details>" : ""}
    ${showRetry ? '<button id="retryBtn" type="button">Retry</button>' : ""}
  </div>
  <script nonce="${n}">
    var vscode = acquireVsCodeApi();
    var btn = document.getElementById('retryBtn');
    if (btn) btn.addEventListener('click', function () { vscode.postMessage({ type: 'retryBackend' }); });
  </script>
</body>
</html>`;
}

function projects(context) {
  const root = harnessRoot(context);
  const dir = path.join(root, "projects");
  if (!exists(dir)) return [];
  return fs.readdirSync(dir).filter((name) => name.endsWith(".json")).sort().map((name) => {
    const fullPath = path.join(dir, name);
    let data = {};
    try { data = JSON.parse(fs.readFileSync(fullPath, "utf8")); } catch (_) {}
    return { name: path.basename(name, ".json"), repoRoot: data.repo_root || "", path: fullPath, data };
  });
}

function agents(context) {
  const root = harnessRoot(context);
  const dir = path.join(root, "agents");
  if (!exists(dir)) return [];
  return fs.readdirSync(dir).filter((name) => name.endsWith(".json")).sort().map((name) => {
    try {
      const data = JSON.parse(fs.readFileSync(path.join(dir, name), "utf8"));
      return { name: data.name || path.basename(name, ".json"), callName: data.call_name || "", modelTier: data.model_tier || "", externalOk: Boolean(data.external_ok) };
    } catch (_) {
      return { name: path.basename(name, ".json"), callName: "", modelTier: "", externalOk: false };
    }
  });
}

function execTool(command, args, cwd, timeout = 10000) {
  return new Promise((resolve) => {
    cp.execFile(command, args, { cwd, timeout, windowsHide: true }, (error, stdout, stderr) => {
      resolve({ ok: !error, stdout: String(stdout || "").trim(), stderr: String(stderr || "").trim(), error: error ? String(error.message || error) : "" });
    });
  });
}

async function envStatus(context) {
  const root = harnessRoot(context);
  const extensions = vscode.extensions.all.map((ext) => {
    const pkg = ext.packageJSON || {};
    const haystack = `${ext.id} ${pkg.name || ""} ${pkg.displayName || ""} ${pkg.publisher || ""}`.toLowerCase();
    const kind = haystack.includes("claude") || haystack.includes("anthropic") ? "claude"
      : haystack.includes("codex") || haystack.includes("openai") || haystack.includes("chatgpt") ? "codex" : "";
    return kind ? { kind, id: ext.id, version: pkg.version || "", displayName: pkg.displayName || pkg.name || ext.id, active: ext.isActive } : null;
  }).filter(Boolean);
  const ollama = await execTool("ollama", ["--version"], root, 5000);
  let doctor = "";
  try { doctor = await runPython(context, ["-m", "daedalus.cli", "doctor"], { timeout: 15000 }); } catch (err) { doctor = String(err.message || err); }
  return { root, extensions, ollamaCli: { ok: ollama.ok, detail: ollama.stdout || ollama.stderr || ollama.error }, doctor };
}

async function dashboardState(context, projectName) {
  const picked = projectName || cfg().get("defaultProject") || (projects(context)[0] && projects(context)[0].name);
  const args = ["-m", "daedalus.cli", "dashboard", "--json"];
  if (picked) args.push("--project", picked);
  const state = await runJson(context, args, { timeout: 30000 });
  state.env = await envStatus(context);
  state.agents = agents(context);
  return state;
}

function saveProjectTeam(context, payload) {
  const project = projects(context).find((p) => p.name === payload.project);
  if (!project) throw new Error(`Unknown project '${payload.project}'`);
  const data = project.data || {};
  data.team = Object.assign({}, data.team || {}, {
    max_workers: Math.max(1, Math.min(32, Number(payload.maxWorkers) || 1)),
    default_lane: payload.defaultLane || "local_only",
    active_agents: Array.isArray(payload.activeAgents) ? payload.activeAgents.map(String).filter(Boolean) : [],
    model_assignments: (data.team || {}).model_assignments || {},
    semi_auto: (data.team || {}).semi_auto || {},
    squads: (data.team || {}).squads || {}
  });
  fs.writeFileSync(project.path, JSON.stringify(data, null, 2) + "\n", "utf8");
}

async function confirmAction(title, detail) {
  const choice = await vscode.window.showWarningMessage(title, { modal: true, detail: detail || undefined }, "Confirm");
  return choice === "Confirm";
}

async function enforceProject(context, projectName) {
  if (!projectName) return Promise.reject(new Error("No project selected"));
  const ok = await confirmAction("Enforce Daedalus harness?", `Project: ${projectName}\nThis rewrites AGENTS.md / CLAUDE.md and writes enforcement state.`);
  if (!ok) return null;
  return runPython(context, ["-m", "daedalus.cli", "enforce", "--project", projectName], { timeout: 30000 });
}

async function pickProject(context, item) {
  if (item && item.project) return item.project.name;
  const defaultProject = cfg().get("defaultProject");
  const all = projects(context);
  if (defaultProject && all.some((p) => p.name === defaultProject)) return defaultProject;
  if (all.length === 1) return all[0].name;
  const picked = await vscode.window.showQuickPick(all.map((p) => ({ label: p.name, description: p.repoRoot })), { placeHolder: "Select an daedalus project" });
  return picked && picked.label;
}

function currentFilePath() {
  const editor = vscode.window.activeTextEditor;
  return editor && editor.document && editor.document.uri.scheme === "file" ? editor.document.uri.fsPath : "";
}

async function enqueue(context, lane, source, strategy, item, presetObjective) {
  const project = await pickProject(context, item);
  if (!project) return;
  const objective = presetObjective || await vscode.window.showInputBox({ prompt: `Task for ${project} (${lane}, ${strategy})`, ignoreFocusOut: true });
  if (!objective) return;
  if (lane !== "local_only") {
    const ok = await confirmAction(`Send task to '${lane}' lane?`, `Project: ${project}\nLane: ${lane}\nObjective: ${objective}`);
    if (!ok) return;
  }
  const args = ["-m", "daedalus.file_bridge", "enqueue", objective, "--project", project, "--lane", lane, "--source", source, "--strategy", strategy];
  const filePath = currentFilePath();
  if (filePath) args.push("--paths", filePath);
  const output = await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: "Queueing Daedalus task" }, () => runPython(context, args));
  queueProvider.refresh();
  updateStatusBar(context);
  // file_bridge's enqueue CLI prints exactly the outbox path it wrote
  // (daedalus/file_bridge.py: `print(enqueue(...))`) -- the filename stem IS
  // the task id GET /api/queue/<id> and its siblings address (see that
  // module's own comment on why nothing new is minted). Deriving it here
  // keeps enqueue() itself unchanged -- no new dependency on the web server
  // unless the user actually asks to watch.
  const id = taskIdFromFilename(path.basename(String(output || "").trim()));
  if (id && TASK_ID_RE.test(id)) {
    vscode.window.showInformationMessage(`Queued: ${output}`, "Watch live").then((choice) => {
      if (choice === "Watch live") watchTask(context, { fullPath: String(output || "").trim() });
    });
  } else {
    vscode.window.showInformationMessage(`Queued: ${output}`);
  }
}

async function reviewDiff(context, projectName) {
  const project = projectName || await pickProject(context);
  if (!project) return null;
  const ok = await confirmAction("Queue local-only diff review?", `Project: ${project}\nLane: local_only`);
  if (!ok) return null;
  const out = await runPython(context, ["-m", "daedalus.cli", "review-diff", "--project", project, "--lane", "local_only", "--json"]);
  vscode.window.showInformationMessage(`Local-only review queued for ${project}`);
  queueProvider.refresh();
  return out;
}

async function showStatus(context, item) {
  const project = await pickProject(context, item);
  if (!project) return;
  const out = await runPython(context, ["-m", "daedalus.status", "--project", project]);
  const doc = await vscode.workspace.openTextDocument({ language: "text", content: out });
  await vscode.window.showTextDocument(doc, { preview: true });
  updateStatusBar(context);
}

async function spawnIkarus(context, item) {
  const project = await pickProject(context, item);
  if (!project) return;
  const objective = await vscode.window.showInputBox({ prompt: `Objective for Ikarus spawn (${project})`, ignoreFocusOut: true });
  if (!objective) return;
  const mode = await vscode.window.showQuickPick([{ label: "Plan only", description: "No writes; show assignments" }, { label: "Live dispatch", description: "Run verified local bench work" }], { placeHolder: "How should Ikarus run this objective?" });
  if (!mode) return;
  const ok = await confirmAction("Spawn Ikarus?", `Project: ${project}\nMode: ${mode.label}\nObjective: ${objective}`);
  if (!ok) return;
  const args = ["-m", "daedalus.cli", "spawn", objective, "--project", project];
  if (mode.label === "Live dispatch") args.push("--live");
  terminal(context, `Ikarus: ${project}`, args);
}

function openFolder(context, relative) {
  const root = harnessRoot(context);
  if (!root) return vscode.window.showErrorMessage("Cannot find daedalus root.");
  vscode.commands.executeCommand("vscode.openFolder", vscode.Uri.file(path.join(root, relative)), { forceNewWindow: false });
}

function openMemory(context) {
  const file = path.join(harnessRoot(context), "memory", "todos.local.md");
  vscode.workspace.openTextDocument(vscode.Uri.file(file)).then((doc) => vscode.window.showTextDocument(doc));
}

// A VS Code-native on-ramp into the chat-first cockpit: opens the same
// Ikarus panel other commands use, seeded with an objective about whatever
// is open. NOT a deep link -- apps/web currently reads only `project` from
// its URL (no initial-message param), so a pre-filled chat turn is an
// assumed seam the web app does not implement yet. Rather than pretend it
// does, this copies the objective to the clipboard and says so plainly; it
// upgrades for free the day the web app grows that param.
async function askAboutFile(context) {
  const filePath = currentFilePath();
  if (!filePath) {
    vscode.window.showWarningMessage("Open a file first, then ask Ikarus about it.");
    return;
  }
  const editor = vscode.window.activeTextEditor;
  const selection = editor && !editor.selection.isEmpty ? editor.document.getText(editor.selection) : "";
  const rel = vscode.workspace.asRelativePath(filePath);
  const objective = selection
    ? `About ${rel}, regarding this selection:\n\n${selection.slice(0, 2000)}\n\nWhat should I know or do here?`
    : `What should I know about ${rel}?`;
  await vscode.env.clipboard.writeText(objective);
  await openDashboard(context);
  vscode.window.showInformationMessage(
    "Objective copied to clipboard — paste it into the Ikarus chat that just opened. " +
    "(VS Code cannot pre-fill the chat turn yet.)"
  );
}

async function openLatestReport(context, state) {
  const report = state && state.queue && ((state.queue.reports || [])[0] || state.queue.latest_failed);
  if (!report || !report.path) return vscode.window.showWarningMessage("No report found yet.");
  const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(report.path));
  return vscode.window.showTextDocument(doc, { preview: true });
}

// ===========================================================================
// Task lifecycle commands: Show Task Status / Show Task Artifacts / Watch
// Task Live. All three are pure reads (or a read-only SSE subscription) --
// no confirmation is needed, unlike enqueue()/spawnIkarus()/startWatcher(),
// because nothing here writes, spends, or reaches a hosted provider.
// ===========================================================================
function taskIdFromItem(item) {
  if (!item || !item.fullPath) return null;
  return taskIdFromFilename(path.basename(item.fullPath));
}

async function pickTaskId(item) {
  const fromItem = taskIdFromItem(item);
  if (fromItem && TASK_ID_RE.test(fromItem)) return fromItem;
  const typed = await vscode.window.showInputBox({
    prompt: "Daedalus task id (the outbox/inbox filename stem)",
    ignoreFocusOut: true,
    validateInput: (v) => (TASK_ID_RE.test(v || "") ? null : "Not a valid task id")
  });
  return typed || null;
}

function renderTaskStatusDoc(id, body) {
  const snap = body && body.task;
  const lines = [`Daedalus task ${id}`, "=".repeat(14 + id.length)];
  if (snap && snap.found) {
    lines.push(describeSnapshot(snap));
    lines.push(appliedLine(snap));
    if (snap.summary) lines.push(`Summary: ${snap.summary}`);
    if (snap.error) lines.push(`Error: ${snap.error}`);
    if (snap.objective) lines.push(`Objective: ${snap.objective}`);
    lines.push(`Lane: ${snap.lane || "n/a"}  Project: ${snap.project || "n/a"}`);
    lines.push(`Observed: ${snap.observed_at || "n/a"} (${shortAge(snap.age_s)})`);
    // conversation_dispatch is daedalus.conversation's OWN read of this
    // dispatch's timeline, and it can lag behind -- e.g. still say
    // "dispatched" after the task is long finished -- because
    // record_dispatch_event is deliberately NOT called from web_api.py (see
    // that module's "conversation + progress seam" section). The `task`
    // block above is read straight off the file bus every time and is the
    // live truth regardless of whether any conversation ever linked this id;
    // what follows is shown for context only, never to contradict it.
    if (snap.conversation_dispatch) {
      lines.push("", "Conversation dispatch (context only -- may lag the task state above):");
      lines.push(JSON.stringify(snap.conversation_dispatch, null, 2));
    }
  } else {
    lines.push(`No live snapshot: ${(body && body.error) || (snap && snap.applied_reason) || "unknown"}`);
  }
  lines.push("", "Full response:", JSON.stringify(body, null, 2));
  return lines.join("\n");
}

async function showTaskStatus(context, item) {
  const id = await pickTaskId(item);
  if (!id) return;
  if (!(await ensureWebServerForCommand(context))) return;
  const res = await apiGet(`/api/queue/${encodeURIComponent(id)}`);
  if (!res.body) {
    vscode.window.showWarningMessage(`No response for task '${id}': ${res.error || "request failed"}`);
    return;
  }
  const doc = await vscode.workspace.openTextDocument({ content: renderTaskStatusDoc(id, res.body), language: "plaintext" });
  await vscode.window.showTextDocument(doc, { preview: true });
}

function renderArtifactsDoc(id, art) {
  const lines = [`Daedalus task ${id} -- artifacts`, "=".repeat(25 + id.length)];
  lines.push(appliedLine({ applied: art.applied, applied_reason: art.applied_reason }));
  const listSection = (label, arr) => {
    lines.push(`${label} (${(arr || []).length}):`);
    (arr || []).forEach((p) => lines.push(`  - ${p}`));
  };
  listSection("Files changed", art.files_changed);
  listSection("Rolled back", art.rolled_back);
  listSection("Wrote", art.wrote);
  listSection("Draft ids", art.draft_ids);
  if ((art.tests_run || []).length) listSection("Tests run", art.tests_run);
  if ((art.risks || []).length) listSection("Risks", art.risks);
  if ((art.todos || []).length) listSection("Todos", art.todos);
  lines.push("", "Full response:", JSON.stringify(art, null, 2));
  return lines.join("\n");
}

async function showTaskArtifacts(context, item) {
  const id = await pickTaskId(item);
  if (!id) return;
  if (!(await ensureWebServerForCommand(context))) return;
  const res = await apiGet(`/api/queue/${encodeURIComponent(id)}/artifacts`);
  const art = res.body && res.body.artifacts;
  if (!art) {
    vscode.window.showWarningMessage(`Task '${id}': ${(res.body && res.body.error) || res.error || "no artifacts info available"}`);
    return;
  }
  if (art.available === false) {
    // NOT an error -- see daedalus/web_api.py: available:false while a run is
    // still in flight is the honest, expected answer, not a failure. Shown
    // as information, never as a warning or error.
    vscode.window.showInformationMessage(`Task '${id}': artifacts not available yet -- ${art.reason || "the run has not finished"}.`);
    return;
  }
  const doc = await vscode.workspace.openTextDocument({ content: renderArtifactsDoc(id, art), language: "plaintext" });
  await vscode.window.showTextDocument(doc, { preview: true });
}

const activeTaskWatches = new Map(); // task id -> { channel, cancel }

function eventSummary(eventName, data) {
  if (data && typeof data === "object" && "state" in data) {
    return `${describeSnapshot(data)} · ${appliedLine(data)}`;
  }
  return typeof data === "string" ? data : JSON.stringify(data);
}

async function watchTask(context, item) {
  const id = await pickTaskId(item);
  if (!id) return;
  const existing = activeTaskWatches.get(id);
  if (existing) { existing.channel.show(true); return; }
  if (!(await ensureWebServerForCommand(context))) return;
  const channel = vscode.window.createOutputChannel(`Daedalus Task ${id}`);
  channel.show(true);
  channel.appendLine(`Watching task ${id} live (SSE). One-shot: this closes on its own once the task reaches a terminal state.`);
  const handle = watchTaskEvents(
    id,
    (eventName, data) => {
      channel.appendLine(`[${new Date().toLocaleTimeString()}] ${eventName}: ${eventSummary(eventName, data)}`);
      if (eventName === "final") {
        channel.appendLine("-- stream closed (terminal state reached) --");
        activeTaskWatches.delete(id);
        queueProvider.refresh();
        if (data && typeof data === "object" && "state" in data) {
          vscode.window.showInformationMessage(`Task ${id} finished: ${data.state} (${appliedWord(data)}).`);
        }
      }
    },
    (err) => {
      if (err) channel.appendLine(`-- stream error: ${err.message || err} --`);
      activeTaskWatches.delete(id);
    }
  );
  activeTaskWatches.set(id, { channel, cancel: handle.cancel });
}

function nonce() {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ===========================================================================
// UNREACHABLE. MEASURED 2026-07-29: `dashboardHtml` has ZERO callers.
//
// Both webview entry points -- the `daedalus.openDashboard` command and the
// Activity Bar view provider -- go through `bindDashboardWebview`, which
// assigns `agentOsHtml(project)`: an IFRAME onto the React web app served at
// 127.0.0.1:8765. Nothing a user can click renders one byte of the ~760 lines
// below.
//
// This matters beyond tidiness, because two test files describe this template
// as a live product surface. tests/test_ui_contract.py opens with "the VS Code
// webview and the React webapp must render the SAME dashboard shape", and
// tests/test_mission_control.py pins "the JSON shapes the Mission Control
// webview depends on". Both pin `core.get_dashboard`, which is real and worth
// pinning -- but there are not two rendering surfaces here. There is ONE (the
// web app) and a window onto it. A reader who trusts those docstrings will
// believe a panel is shipping that no user has ever seen.
//
// Left in place rather than deleted: removing 760 lines is a deliberate act
// that deserves its own review, not a drive-by at the end of a session. It is
// labelled instead, and tests/test_ui_governance.py holds this comment to the
// code -- if anyone wires this template back up, that test fails until the
// claim here is corrected.
// ===========================================================================
function dashboardHtml(n) {
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${n}';">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Daedalus Mission Control</title>
<style>
  :root {
    --mc-surface: var(--vscode-editor-background);
    --mc-surface-elevated: var(--vscode-sideBar-background);
    --mc-surface-card: var(--vscode-editorWidget-background);
    --mc-text: var(--vscode-foreground);
    --mc-text-muted: var(--vscode-descriptionForeground);
    --mc-border: var(--vscode-panel-border);
    --mc-accent: var(--vscode-textLink-foreground);
    --mc-focus: var(--vscode-focusBorder);
    --mc-success: var(--vscode-testing-iconPassed);
    --mc-warning: var(--vscode-editorWarning-foreground);
    --mc-danger: var(--vscode-testing-iconFailed);
    --space-1: 4px; --space-2: 8px; --space-3: 12px; --space-4: 16px; --space-5: 24px; --space-6: 32px;
    --text-micro: 11px; --text-small: 12px; --text-base: 13px; --text-medium: 13px; --text-large: 15px; --text-xl: 18px;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body { font-family: var(--vscode-font-family); font-size: var(--text-base); color: var(--mc-text); background: var(--mc-surface); line-height: 1.45; }
  h1, h2, h3, p, ul { margin: 0; }
  ul { padding: 0; list-style: none; }
  button, select, input { font-family: inherit; font-size: inherit; }
  code, pre { font-family: ui-monospace, "Cascadia Mono", Consolas, monospace; }
  :focus-visible { outline: 2px solid var(--mc-focus); outline-offset: 2px; }
  @media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important; } }

  header.topbar { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); padding: var(--space-3) var(--space-4); border-bottom: 1px solid var(--mc-border); background: var(--mc-surface-elevated); position: sticky; top: 0; z-index: 5; flex-wrap: wrap; }
  header.topbar h1 { font-size: var(--text-large); font-weight: 600; }
  header.topbar .sub { color: var(--mc-text-muted); font-size: var(--text-small); }
  .header-actions { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; }
  select.project, #lane, #workers { color: var(--vscode-input-foreground); background: var(--vscode-input-background); border: 1px solid var(--vscode-input-border); border-radius: 3px; padding: 5px 8px; min-width: 100px; }

  nav.tabs { display: flex; gap: 2px; padding: 0 var(--space-4); border-bottom: 1px solid var(--mc-border); background: var(--mc-surface); overflow-x: auto; }
  .tab { appearance: none; border: 0; background: transparent; cursor: pointer; color: var(--mc-text-muted); padding: var(--space-3); font-size: var(--text-base); border-bottom: 2px solid transparent; white-space: nowrap; }
  .tab:hover { color: var(--mc-text); background: var(--mc-surface-elevated); }
  .tab.active { color: var(--vscode-tab-activeForeground); background: var(--vscode-tab-activeBackground); border-bottom-color: var(--mc-accent); font-weight: 600; }

  main { flex: 1; padding: var(--space-4); display: flex; flex-direction: column; gap: var(--space-5); }
  .page { display: none; flex-direction: column; gap: var(--space-5); }
  .page.active { display: flex; }

  section.block { display: flex; flex-direction: column; gap: var(--space-3); }
  section.block > h2 { font-size: var(--text-large); font-weight: 600; }
  .desc, .muted { color: var(--mc-text-muted); font-size: var(--text-small); line-height: 1.4; }

  .banner { display: flex; align-items: flex-start; gap: var(--space-2); border-left: 3px solid var(--mc-warning); background: var(--mc-surface-elevated); padding: var(--space-2) var(--space-3); border-radius: 3px; font-size: var(--text-small); }
  .banner .glyph { color: var(--mc-warning); flex: none; }
  .banner.danger { border-left-color: var(--mc-danger); }
  .banner.danger .glyph { color: var(--mc-danger); }

  .kpi-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: var(--space-3); }
  .tile { background: var(--mc-surface-card); border: 1px solid var(--mc-border); border-radius: 6px; padding: var(--space-3); display: flex; flex-direction: column; gap: var(--space-1); }
  .tile:hover { border-color: var(--mc-accent); }
  .tile .tile-head { display: flex; align-items: center; gap: var(--space-1); color: var(--mc-text-muted); font-size: var(--text-small); }
  .tile .tile-value { font-size: var(--text-xl); font-weight: 600; }
  .tile .tile-sub { font-size: var(--text-small); color: var(--mc-text-muted); }
  .tile.warn { border-left: 3px solid var(--mc-warning); }
  .tile.err { border-left: 3px solid var(--mc-danger); }
  .tile .mini-list { display: flex; flex-direction: column; gap: 2px; font-size: var(--text-small); margin-top: var(--space-1); }
  .mini-status { display: inline-flex; align-items: center; gap: 5px; }
  .mini-status .dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
  .dot.ok { background: var(--mc-success); }
  .dot.warn { background: var(--mc-warning); }
  .dot.bad { background: var(--mc-danger); }

  .badge { display: inline-flex; align-items: center; gap: 5px; border-radius: 999px; padding: 2px 8px; font-size: var(--text-micro); font-weight: 600; border: 1px solid var(--mc-border); white-space: nowrap; }
  .badge .glyph { line-height: 1; }
  .badge.lane { color: var(--mc-text); }
  .badge.lane .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--mc-text-muted); }
  .lane-local_only .dot { background: var(--vscode-charts-blue, var(--mc-accent)); }
  .lane-local .dot { background: var(--vscode-charts-purple, var(--mc-accent)); }
  .lane-auto .dot { background: var(--vscode-charts-yellow, var(--mc-warning)); }
  .lane-claude .dot { background: var(--vscode-charts-orange, var(--mc-warning)); }
  .badge.status-done { color: var(--mc-success); border-color: var(--mc-success); }
  .badge.status-blocked { color: var(--mc-warning); border-color: var(--mc-warning); }
  .badge.status-needs_review { color: var(--mc-accent); border-color: var(--mc-accent); }
  .badge.status-failed { color: var(--mc-danger); border-color: var(--mc-danger); }
  .tier-badge { display: inline-block; background: var(--mc-surface-elevated); color: var(--mc-text-muted); border-radius: 3px; padding: 2px 6px; font-size: var(--text-micro); border: 1px solid var(--mc-border); }

  .queue-list { display: flex; flex-direction: column; border: 1px solid var(--mc-border); border-radius: 6px; overflow: hidden; }
  .queue-row { display: grid; grid-template-columns: auto auto 1fr auto; align-items: center; gap: var(--space-3); padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--mc-border); cursor: pointer; }
  .queue-row:last-child { border-bottom: 0; }
  .queue-row:hover { background: var(--mc-surface-elevated); }
  .queue-row.failed { border-left: 3px solid var(--mc-danger); background: var(--mc-surface-elevated); }
  .queue-row.selected { background: var(--mc-surface-elevated); }
  .queue-row .qr-main { min-width: 0; }
  .queue-row .qr-name { font-weight: 600; font-size: var(--text-medium); }
  .queue-row .qr-summary { color: var(--mc-text-muted); font-size: var(--text-small); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .queue-row .qr-kind { font-size: var(--text-micro); color: var(--mc-text-muted); text-transform: uppercase; }
  .queue-detail { display: none; padding: 0 var(--space-3) var(--space-3) calc(var(--space-3) + 3px); border-left: 2px solid var(--mc-accent); margin-left: var(--space-1); }
  .queue-row.selected + .queue-detail { display: block; }
  .queue-detail pre { margin: 0; max-height: 160px; }

  .empty-state { display: flex; flex-direction: column; align-items: center; gap: var(--space-2); padding: var(--space-6) var(--space-4); color: var(--mc-text-muted); text-align: center; border: 1px dashed var(--mc-border); border-radius: 6px; }
  .empty-state .glyph { font-size: 22px; opacity: .6; }

  .squad-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: var(--space-3); }
  .squad-card { background: var(--mc-surface-card); border: 1px solid var(--mc-border); border-radius: 6px; padding: var(--space-3); display: flex; flex-direction: column; gap: var(--space-2); }
  .squad-card.empty { border-style: dashed; }
  .squad-card h3 { font-size: var(--text-medium); display: flex; justify-content: space-between; align-items: baseline; }
  .squad-card h3 .count { font-size: var(--text-micro); color: var(--mc-text-muted); font-weight: 400; }
  .chip-row { display: flex; flex-wrap: wrap; gap: var(--space-2); }
  .chip { display: flex; align-items: center; gap: var(--space-2); border: 1px solid var(--mc-border); border-radius: 999px; padding: 4px 6px 4px 10px; background: var(--mc-surface); }
  .chip.error { border-color: var(--mc-danger); }
  .chip .chip-name { font-size: var(--text-small); font-weight: 600; }
  .chip .chip-error-text { font-size: var(--text-micro); color: var(--mc-danger); }
  .chip .ext-glyph { font-size: var(--text-small); }
  .toggle { width: 26px; height: 15px; border-radius: 999px; border: 1px solid var(--mc-border); background: var(--mc-surface-elevated); position: relative; flex: none; cursor: pointer; }
  .toggle::after { content: ""; position: absolute; top: 1px; left: 1px; width: 11px; height: 11px; border-radius: 50%; background: var(--mc-text-muted); }
  .toggle.on { background: var(--mc-surface-elevated); border-color: var(--mc-accent); }
  .toggle.on::after { background: var(--mc-accent); left: 12px; }

  .model-list { display: flex; flex-direction: column; border: 1px solid var(--mc-border); border-radius: 6px; overflow: hidden; }
  .model-row { display: grid; grid-template-columns: 1.3fr auto auto 1.4fr auto; align-items: center; gap: var(--space-3); padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--mc-border); }
  .model-row:last-child { border-bottom: 0; }
  .model-row:hover { background: var(--mc-surface-elevated); }
  .model-row .m-name { font-weight: 600; font-size: var(--text-medium); }
  .model-row .m-meta { font-size: var(--text-micro); color: var(--mc-text-muted); }
  .size-bar-track { height: 8px; background: var(--mc-surface-elevated); border-radius: 4px; overflow: hidden; }
  .size-bar-fill { height: 100%; background: var(--vscode-charts-blue, var(--mc-accent)); }
  .m-gb { font-size: var(--text-small); text-align: right; color: var(--mc-text-muted); white-space: nowrap; }

  .resource-grid { display: grid; grid-template-columns: 2fr 1fr; gap: var(--space-3); }
  .gauge-card, .stat-card, .panel { background: var(--mc-surface-card); border: 1px solid var(--mc-border); border-radius: 6px; padding: var(--space-3); }
  .gauge-readout { display: flex; justify-content: space-between; font-size: var(--text-small); color: var(--mc-text-muted); margin-bottom: var(--space-2); }
  .gauge-track { height: 14px; border-radius: 7px; overflow: hidden; display: flex; background: var(--mc-surface-elevated); }
  .gauge-used { background: var(--vscode-charts-orange, var(--mc-warning)); height: 100%; }
  .gauge-free { background: var(--vscode-charts-green, var(--mc-success)); height: 100%; }
  .gauge-note { margin-top: var(--space-2); font-size: var(--text-small); color: var(--mc-warning); }
  .stat-card .tile-value, .panel .tile-value { font-size: var(--text-xl); font-weight: 600; }

  .pull-list { display: flex; flex-direction: column; gap: var(--space-2); }
  .pull-item { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); background: var(--mc-surface-card); border: 1px solid var(--mc-border); border-radius: 6px; padding: var(--space-2) var(--space-3); }
  .pull-item code { background: var(--vscode-textCodeBlock-background); padding: 3px 8px; border-radius: 4px; font-size: var(--text-small); }
  .pull-item .reason { font-size: var(--text-small); color: var(--mc-text-muted); }

  button.btn { display: inline-flex; align-items: center; gap: 6px; background: var(--vscode-button-secondaryBackground); color: var(--vscode-button-secondaryForeground); border: 0; border-radius: 4px; padding: 6px 10px; cursor: pointer; font-size: var(--text-small); }
  button.btn:hover { background: var(--vscode-button-hoverBackground); }
  button.btn.primary { background: var(--vscode-button-background); color: var(--vscode-button-foreground); }
  button.btn.copied { color: var(--mc-success); }
  button.btn:disabled { opacity: .5; cursor: not-allowed; }

  .field { display: flex; flex-direction: column; gap: 4px; }
  .field label { font-size: var(--text-small); color: var(--mc-text-muted); }
  .field input, .field select, .field textarea { color: var(--vscode-input-foreground); background: var(--vscode-input-background); border: 1px solid var(--vscode-input-border); border-radius: 3px; padding: 5px 8px; font-family: inherit; font-size: inherit; width: 100%; }
  .field textarea { resize: vertical; min-height: 60px; }
  .field-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: var(--space-3); }
  .field-check { display: flex; align-items: center; gap: 6px; font-size: var(--text-small); }
  .field-check label { color: var(--mc-text); }
  .status-text { font-size: var(--text-small); color: var(--mc-warning); }
  .live-dot { font-size: 10px; }

  .gate-list { display: flex; flex-direction: column; border: 1px solid var(--mc-border); border-radius: 6px; overflow: hidden; }
  .gate-row { display: flex; align-items: center; gap: var(--space-2); padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--mc-border); font-size: var(--text-small); }
  .gate-row:last-child { border-bottom: 0; }
  .gate-row .glyph { width: 16px; text-align: center; flex: none; }
  .gate-row.pass .glyph { color: var(--mc-success); }
  .gate-row.fail .glyph { color: var(--mc-danger); }
  .gate-row .g-name { font-weight: 600; flex: 1; }
  .gate-row .g-reason { color: var(--mc-text-muted); }
  .gate-row .g-result { font-weight: 600; }
  .gate-row.pass .g-result { color: var(--mc-success); }
  .gate-row.fail .g-result { color: var(--mc-danger); }
  /* An unmeasured gate must be visually distinct from a passing one on more
     than hue, so it survives a greyscale screenshot and a colourblind viewer:
     amber, a "?" glyph, and the word "unknown" all disagree with "Pass". */
  .gate-row.warn .glyph { color: var(--mc-warning); }
  .gate-row.warn .g-result { color: var(--mc-warning); font-style: italic; }

  .meter-card { background: var(--mc-surface-card); border: 1px solid var(--mc-border); border-radius: 6px; padding: var(--space-3); }
  .meter-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--space-2); font-size: var(--text-small); }
  .alarm-tag { color: var(--mc-danger); font-weight: 700; font-size: var(--text-micro); border: 1px solid var(--mc-danger); border-radius: 999px; padding: 1px 8px; }
  .meter-track { height: 12px; border-radius: 6px; background: var(--mc-surface-elevated); overflow: hidden; }
  .meter-fill { height: 100%; background: var(--mc-success); display: flex; align-items: center; justify-content: flex-end; padding-right: 6px; font-size: 9px; color: #fff; white-space: nowrap; }
  .meter-fill.warn { background: var(--mc-warning); }
  .meter-fill.danger { background: var(--mc-danger); }

  .callout { border-left: 3px solid var(--mc-accent); background: var(--mc-surface-elevated); border-radius: 4px; padding: var(--space-3); font-size: var(--text-small); display: flex; gap: var(--space-2); align-items: flex-start; }
  .callout .glyph { color: var(--mc-accent); }

  .wheel-wrap { display: flex; gap: var(--space-5); flex-wrap: wrap; align-items: flex-start; }
  .wheel-stage { position: relative; width: min(92vw, 460px); aspect-ratio: 1 / 1; flex: none; margin: 0 auto; }
  .wheel-svg { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; }
  .wheel-svg line { stroke: var(--mc-border); stroke-width: 1; transition: stroke .12s ease, stroke-width .12s ease; }
  .wheel-svg line.selected { stroke-width: 2; }
  .wheel-hub { position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); width: 26%; aspect-ratio: 1 / 1; border-radius: 50%; background: var(--mc-surface-card); border: 1px solid var(--mc-border); display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; gap: 2px; padding: var(--space-1); box-shadow: 0 0 0 6px var(--mc-surface); }
  .wheel-hub .hub-icon { font-size: 20px; }
  .wheel-hub .hub-label { font-size: var(--text-small); font-weight: 700; }
  .wheel-hub .hub-sub { font-size: 9px; color: var(--mc-text-muted); text-transform: uppercase; letter-spacing: .04em; }
  .wheel-node { position: absolute; transform: translate(-50%, -50%); display: flex; flex-direction: column; align-items: center; gap: 3px; width: 84px; text-align: center; }
  .node-btn { appearance: none; cursor: pointer; position: relative; width: 46px; height: 46px; border-radius: 50%; background: var(--mc-surface-card); border: 2px solid var(--mc-border); display: flex; align-items: center; justify-content: center; font-size: 18px; padding: 0; transition: border-color .12s ease, box-shadow .12s ease, background .12s ease; }
  .node-btn:hover { border-color: color-mix(in srgb, var(--node-color, var(--mc-accent)) 60%, var(--mc-border)); }
  .node-btn[aria-pressed="true"] { border-color: var(--mc-accent); background: var(--mc-surface-elevated); box-shadow: 0 0 0 3px color-mix(in srgb, var(--mc-accent) 35%, transparent); }
  .node-btn.is-empty { border-style: dashed; }
  .node-dot { position: absolute; right: -2px; bottom: -2px; width: 13px; height: 13px; border-radius: 50%; border: 2px solid var(--mc-surface); background: var(--node-color, var(--mc-text-muted)); }
  .wheel-node .node-label { font-size: var(--text-small); font-weight: 600; line-height: 1.2; }
  .wheel-node .node-count { font-size: var(--text-micro); color: var(--mc-text-muted); }
  .wheel-node.is-empty .node-label, .wheel-node.is-empty .node-count { color: var(--mc-text-muted); }
  .wheel-legend { font-size: var(--text-micro); color: var(--mc-text-muted); text-align: center; margin-top: var(--space-2); }
  .wheel-detail { flex: 1 1 280px; min-width: 260px; background: var(--mc-surface-card); border: 1px solid var(--mc-border); border-radius: 6px; padding: var(--space-4); display: flex; flex-direction: column; gap: var(--space-3); }
  .wheel-detail .detail-head { display: flex; align-items: center; gap: var(--space-2); }
  .wheel-detail .detail-swatch { width: 28px; height: 28px; border-radius: 50%; flex: none; background: var(--node-color, var(--mc-text-muted)); border: 1px solid var(--mc-border); display: flex; align-items: center; justify-content: center; font-size: 15px; }
  .wheel-detail h3 { font-size: var(--text-large); font-weight: 600; }
  .wheel-detail .detail-count { font-size: var(--text-small); color: var(--mc-text-muted); }
  .detail-row-label { font-size: var(--text-micro); text-transform: uppercase; letter-spacing: .03em; color: var(--mc-text-muted); margin-bottom: var(--space-1); }
  .swatch-row { display: flex; flex-wrap: wrap; gap: var(--space-2); }
  .swatch-btn { width: 22px; height: 22px; border-radius: 50%; border: 2px solid var(--mc-border); cursor: pointer; padding: 0; transition: border-color .12s ease, box-shadow .12s ease; }
  .swatch-btn:hover { border-color: var(--mc-text); }
  .swatch-btn[aria-pressed="true"] { border-color: var(--mc-accent); box-shadow: 0 0 0 2px color-mix(in srgb, var(--mc-accent) 35%, transparent); }
  .emoji-row { display: flex; flex-wrap: wrap; gap: var(--space-2); }
  .emoji-btn { width: 30px; height: 30px; border-radius: 4px; border: 1px solid var(--mc-border); background: var(--mc-surface); cursor: pointer; font-size: 15px; padding: 0; display: flex; align-items: center; justify-content: center; transition: border-color .12s ease, background .12s ease; }
  .emoji-btn:hover { border-color: color-mix(in srgb, var(--mc-accent) 60%, var(--mc-border)); }
  .emoji-btn[aria-pressed="true"] { border-color: var(--mc-accent); background: var(--mc-surface-elevated); }
  .customize-readout { font-size: var(--text-micro); color: var(--mc-text-muted); }
  .sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }

  .row { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 5px 0; border-bottom: 1px solid var(--mc-border); }
  .row:last-child { border-bottom: 0; }
  .label { color: var(--mc-text-muted); font-size: 12px; }
  .value { font-weight: 600; text-align: right; }
  .value.ok { color: var(--mc-success); }
  .value.warn { color: var(--mc-warning); }
  .value.bad { color: var(--mc-danger); }
  pre { white-space: pre-wrap; background: var(--vscode-textCodeBlock-background); padding: 10px; border-radius: 4px; max-height: 240px; overflow: auto; font-size: var(--text-small); }
  @media (max-width: 720px) { header.topbar { align-items: stretch; flex-direction: column; } }
</style>
</head>
<body>
<header class="topbar">
  <div><h1>Daedalus Mission Control</h1><div id="subtitle" class="sub"></div></div>
  <div class="header-actions"><select id="project" class="project"></select><button class="btn" id="refresh">Refresh</button><button class="btn" id="enforce">Enforce Harness</button></div>
</header>
<nav class="tabs">
  <button class="tab active" data-tab="overview">Overview</button>
  <button class="tab" data-tab="queue">Queue Timeline</button>
  <button class="tab" data-tab="squads">Agent Squads</button>
  <button class="tab" data-tab="models">Model Resources</button>
  <button class="tab" data-tab="quality">Quality Gates</button>
  <button class="tab" data-tab="wheel">Role Wheel</button>
  <button class="tab" data-tab="commands">Command Deck</button>
</nav>
<main>
  <section id="overview" class="page active">
    <div id="warnings"></div>
    <section class="block">
      <h2>Promotion</h2>
      <div class="desc">May this system promote anything right now, and why not?</div>
      <div id="governanceGrid"></div>
    </section>
    <section class="block">
      <h2>Status</h2>
      <div class="kpi-row" id="overviewGrid"></div>
    </section>
    <section class="block">
      <h2>Key Metrics</h2>
      <div class="kpi-row" id="metricsGrid"></div>
    </section>
    <pre id="doctor"></pre>
  </section>
  <section id="queue" class="page">
    <section class="block">
      <h2>Assign Task</h2>
      <div class="desc">Queues a task straight onto the file bus. Non-local lanes still require confirmation before dispatch.</div>
      <div class="panel">
        <div class="field"><label for="taskObjective">Objective</label><textarea id="taskObjective" rows="3" placeholder="Describe the task..."></textarea></div>
        <div class="field-row" style="margin-top:var(--space-2);">
          <div class="field"><label for="taskLane">Lane</label><select id="taskLane"><option value="local_only">local_only</option><option value="local">local</option><option value="auto">auto</option><option value="claude">claude</option></select></div>
          <div class="field"><label for="taskAgent">Agent hint (optional)</label><input id="taskAgent" type="text" placeholder="e.g. core-dev"></div>
        </div>
        <div class="header-actions" style="margin-top:var(--space-3);"><button class="btn primary" id="queueTaskBtn">Queue task</button><span class="status-text" id="taskStatus"></span></div>
      </div>
    </section>
    <section class="block">
      <div class="header-actions" style="justify-content:space-between;">
        <h2>Queue Timeline</h2>
        <div class="header-actions"><span class="badge" id="liveIndicator"><span class="live-dot value ok" id="liveDot">&#9679;</span><span id="liveText">Live</span></span><button class="btn" id="livePause">Pause</button></div>
      </div>
      <div class="desc">Click a row to expand. Failed reports get a red rail so they can't be scrolled past unnoticed.</div>
      <div class="header-actions"><button class="btn" data-action="reviewDiff">Rerun local_only diff review</button><button class="btn" data-action="enqueueAuto">Queue auto task</button><button class="btn" data-action="openLatest">Open latest report</button></div>
      <div id="timeline"></div>
    </section>
  </section>
  <section id="squads" class="page">
    <section class="block">
      <h2>Agent Squads</h2>
      <div class="desc">Ikarus routes every task through the central file bus. Squads filter active agents and make ownership visible.</div>
      <div id="squadGrid"></div>
    </section>
    <section class="block">
      <h2>New Agent</h2>
      <div class="desc">Registers a new agent role via <code>daedalus.cli agents add</code>. Agents are local-only by default; enable "external ok" only for roles cleared to reach hosted providers.</div>
      <div class="panel">
        <div class="field-row">
          <div class="field"><label for="naName">Name</label><input id="naName" type="text" placeholder="e.g. scribe"></div>
          <div class="field"><label for="naCallName">Call name</label><input id="naCallName" type="text" placeholder="e.g. Scribe"></div>
          <div class="field"><label for="naModelTier">Model tier</label><select id="naModelTier"><option value="opus">opus</option><option value="sonnet" selected>sonnet</option><option value="haiku">haiku</option></select></div>
          <div class="field"><label for="naCategory">Category</label><select id="naCategory"><option value="">(none)</option></select></div>
        </div>
        <div class="field-row" style="margin-top:var(--space-2);">
          <div class="field" style="grid-column: span 2;"><label for="naTriggers">Triggers (comma-separated)</label><input id="naTriggers" type="text" placeholder="e.g. docs, readme, changelog"></div>
          <div class="field-check"><input id="naExternalOk" type="checkbox"><label for="naExternalOk">External ok (may reach hosted providers)</label></div>
        </div>
        <div class="header-actions" style="margin-top:var(--space-3);"><button class="btn primary" id="addAgentBtn">Create agent</button><span class="status-text" id="naStatus"></span></div>
      </div>
    </section>
  </section>
  <section id="models" class="page"><div id="modelGrid"></div></section>
  <section id="quality" class="page"><div id="qualityGrid"></div></section>
  <section id="wheel" class="page">
    <section class="block">
      <h2>Role Wheel</h2>
      <div class="desc">Radial browser for the role-category taxonomy. Ikarus sits at the hub; each spoke is a role category. Click a node (or arrow-key between nodes, then Enter/Space) to inspect its agents and routing preset, and to recolor / re-icon it.</div>
      <div class="wheel-wrap">
        <div>
          <div class="wheel-stage" id="wheel-stage" role="group" aria-label="Role categories">
            <svg class="wheel-svg" id="wheel-svg" viewBox="0 0 100 100" aria-hidden="true"></svg>
            <div class="wheel-hub"><div class="hub-icon">&#9992;&#65039;</div><div class="hub-label">Ikarus</div><div class="hub-sub">hub</div></div>
          </div>
          <div class="wheel-legend" id="wheel-legend"></div>
        </div>
        <div class="wheel-detail" id="wheel-detail"></div>
      </div>
      <div class="sr-only" role="status" aria-live="polite" id="wheel-status"></div>
    </section>
  </section>
  <section id="commands" class="page">
    <div class="kpi-row">
      <section class="panel">
        <h2 style="font-size:var(--text-large);margin-bottom:var(--space-2);">Team Controls</h2>
        <div class="row"><span class="label">Default lane</span><select id="lane"><option value="local_only">local_only</option><option value="auto">auto</option><option value="local">local</option><option value="claude">claude</option></select></div>
        <div class="row"><span class="label">Max agents</span><input id="workers" type="number" min="1" max="32" step="1"></div>
        <div class="muted" style="margin-top:var(--space-2);">Toggle agents in Agent Squads, then save.</div>
        <div class="header-actions" style="margin-top:var(--space-3);"><button class="btn primary" id="save">Save Team Settings</button></div>
      </section>
      <section class="panel">
        <h2 style="font-size:var(--text-large);margin-bottom:var(--space-2);">Run</h2>
        <div class="header-actions">
          <button class="btn" data-action="startWatcher">Start watcher</button>
          <button class="btn" data-action="stopWatcher">Stop watcher</button>
          <button class="btn" data-action="reviewDiff">Local-only review current diff</button>
          <button class="btn" data-action="ikarusPlan">Ikarus plan</button>
          <button class="btn" data-action="enqueueFile">Queue selected file/task</button>
          <button class="btn" data-action="openLatest">Open latest report</button>
        </div>
        <p class="muted" style="margin-top:var(--space-2);">Claude use, live writes, and model installs stay confirmation-first.</p>
      </section>
    </div>
  </section>
</main>
<script nonce="${n}">
const vscode = acquireVsCodeApi();
let state = {};
const projectEl = document.getElementById('project');
const laneEl = document.getElementById('lane');
const workersEl = document.getElementById('workers');
function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function row(label, value, cls) { return '<div class="row"><span class="label">' + esc(label) + '</span><span class="value ' + (cls || '') + '">' + esc(value) + '</span></div>'; }
function tile(cls, head, value, sub, miniList) {
  return '<div class="tile' + (cls ? ' ' + cls : '') + '" tabindex="0"><div class="tile-head">' + head + '</div><div class="tile-value">' + esc(value) + '</div>' +
    (sub ? '<div class="tile-sub">' + esc(sub) + '</div>' : '') + (miniList ? '<div class="mini-list">' + miniList + '</div>' : '') + '</div>';
}
function miniStatus(dotCls, label) { return '<span class="mini-status"><span class="dot ' + dotCls + '"></span>' + esc(label) + '</span>'; }
const STATUS_GLYPH = { done: '&#10003;', blocked: '&#10074;&#10074;', needs_review: '&#128065;', failed: '&#10007;' };
function statusBadge(status) {
  const s = status || 'queued';
  const cls = STATUS_GLYPH[s] ? 'status-' + s : '';
  const glyph = STATUS_GLYPH[s] || '';
  return '<span class="badge ' + cls + '">' + (glyph ? '<span class="glyph">' + glyph + '</span>' : '') + esc(s) + '</span>';
}
function laneBadge(lane) {
  const l = lane || 'n/a';
  const cls = ['local_only', 'local', 'auto', 'claude'].indexOf(l) >= 0 ? 'lane-' + l : '';
  return '<span class="badge lane ' + cls + '"><span class="dot"></span>' + esc(l) + '</span>';
}
function chip(agent) {
  const unresolved = !agent.call_name && !agent.model_tier;
  if (unresolved) {
    return '<div class="chip error" title="config error"><span class="chip-name">' + esc(agent.name) + '</span><span class="chip-error-text">config error</span></div>';
  }
  const tierBadge = agent.model_tier ? '<span class="tier-badge">' + esc(agent.model_tier) + '</span>' : '';
  const extGlyph = '<span class="ext-glyph" title="' + (agent.external_ok ? 'external ok' : 'local only') + '">' + (agent.external_ok ? '&#128275;' : '&#128274;') + '</span>';
  const toggle = '<span class="toggle' + (agent.active ? ' on' : '') + '" data-agent="' + esc(agent.name) + '" role="switch" aria-checked="' + (agent.active ? 'true' : 'false') + '" tabindex="0" title="' + (agent.active ? 'active — click to disable' : 'inactive — click to enable') + '"></span>';
  return '<div class="chip"><span class="chip-name">' + esc(agent.call_name || agent.name) + '</span>' + tierBadge + extGlyph + toggle + '</div>';
}
function renderProjects() {
  const names = (state.projects || []).map(p => p.name);
  projectEl.innerHTML = names.map(n => '<option value="' + esc(n) + '">' + esc(n) + '</option>').join('');
  projectEl.value = state.selected_project || names[0] || '';
}
function renderOverview() {
  const env = state.env || {}, watcher = state.watcher || {}, enf = state.enforcement || {}, routing = state.routing || {}, metrics = state.metrics || {}, providers = ((state.provider_health || {}).providers || []);
  document.getElementById('subtitle').textContent = (state.project_config && state.project_config.repo_root) || '';
  const warnings = state.warnings || [];
  document.getElementById('warnings').innerHTML = warnings.map(w => '<div class="banner"><span class="glyph">&#9888;</span><span>' + esc(w) + '</span></div>').join('');

  const providerOk = providers.filter(p => p.available).length;
  const providerDown = providers.find(p => !p.available);
  const providerCls = providers.length && providerOk < providers.length ? (providerOk === 0 ? 'err' : 'warn') : '';
  const providerMini = providers.slice(0, 6).map(p => miniStatus(p.available ? 'ok' : (p.implemented ? 'bad' : 'warn'), (p.display_name || p.name) + ' — ' + (p.available ? 'ready' : (p.implemented ? 'unavailable' : 'planned')))).join('');

  const watcherStale = Boolean(watcher.stale_count);
  const watcherVal = watcherStale ? 'Stale' : (watcher.running ? 'Running' : 'Stopped');
  const watcherCls = watcherStale ? 'err' : (watcher.running ? '' : 'warn');
  const watcherSub = watcherStale ? watcher.stale_count + ' stale watcher(s) — restart required' : (watcher.running ? 'processing queued tasks' : 'not running');

  const routingSub = 'selected: ' + (routing.selected_lane || 'n/a') + (routing.recommended_lane && routing.recommended_lane !== routing.selected_lane ? ' → recommended: ' + routing.recommended_lane : '') + (routing.reason ? ' (' + routing.reason + ')' : '');

  const enfCount = [enf.agents_md, enf.claude_md, enf.state_file].filter(Boolean).length;
  const enfMini = [
    miniStatus(enf.agents_md ? 'ok' : 'bad', 'AGENTS.md ' + (enf.agents_md ? 'managed' : 'missing')),
    miniStatus(enf.claude_md ? 'ok' : 'bad', 'CLAUDE.md ' + (enf.claude_md ? 'managed' : 'missing')),
    miniStatus(enf.state_file ? 'ok' : 'bad', 'state file ' + (enf.state_file ? 'present' : 'missing'))
  ].join('');

  const exts = env.extensions || [];
  const hasClaude = exts.some(e => e.kind === 'claude');
  const hasCodex = exts.some(e => e.kind === 'codex');
  const ollamaCli = Boolean((env.ollamaCli || {}).ok);
  const envMini = [
    miniStatus(hasClaude ? 'ok' : 'warn', 'Claude extension ' + (hasClaude ? 'installed' : 'not found')),
    miniStatus(hasCodex ? 'ok' : 'warn', 'Codex/OpenAI extension ' + (hasCodex ? 'installed' : 'not found')),
    miniStatus(ollamaCli ? 'ok' : 'warn', 'Ollama CLI ' + (ollamaCli ? 'on PATH' : 'not on PATH'))
  ].join('');

  document.getElementById('overviewGrid').innerHTML =
    tile(providerCls, '&#128225; Provider Health', providerOk + ' / ' + providers.length, providerDown ? (providerDown.display_name || providerDown.name) + ' unavailable' : 'all providers ready', providerMini) +
    tile(watcherCls, '&#128065; Watcher', watcherVal, watcherSub) +
    tile('', '&#8644; Routing Lane', routing.selected_lane || 'n/a', routingSub) +
    tile(enfCount < 3 ? 'warn' : '', '&#128274; Enforcement', enfCount + ' / 3', enf.enabled ? 'active' : 'not active', enfMini) +
    tile('', '&#129520; Environment', (Number(hasClaude) + Number(hasCodex)) + ' AI tools', 'VS Code extensions detected', envMini);

  document.getElementById('metricsGrid').innerHTML =
    tile('', 'Offloadable tasks', metrics.offloadable || 0, 'tasks eligible for the local bench') +
    tile('', 'Ran on bench', metrics.offloaded || 0, 'completed locally') +
    tile(metrics.fell_back_to_claude ? 'warn' : '', 'Fell back to Claude', metrics.fell_back_to_claude || 0, 'local bench declined or failed') +
    tile(metrics.alarm ? 'err' : '', 'Fallback rate', Math.round((metrics.fallback_rate || 0) * 100) + '%', metrics.alarm ? 'alarm threshold exceeded' : 'within normal range');

  document.getElementById('doctor').textContent = env.doctor || '';
}
function renderQueue() {
  const q = state.queue || {};
  const failedPath = (q.latest_failed || {}).path;
  const items = [].concat(q.pending || [], q.reports || [], q.processed || []).slice(0, 40);
  const banner = q.latest_failed ? '<div class="banner danger"><span class="glyph">&#10007;</span><span><strong>Latest failed: ' + esc(q.latest_failed.name) + '</strong> — ' + esc(q.latest_failed.error || q.latest_failed.summary || 'No details available.') + '</span></div>' : '';
  if (!items.length) {
    document.getElementById('timeline').innerHTML = banner + '<div class="empty-state"><div class="glyph">&#128203;</div><div><strong>No queue activity yet.</strong></div><div>Tasks appear here once queued via <code>daedalus.file_bridge enqueue</code> or Ikarus dispatch.</div></div>';
    return;
  }
  const rows = items.map((i, idx) => {
    const isFailed = (Boolean(failedPath) && i.path === failedPath) || i.status === 'failed' || Boolean(i.error);
    const detail = esc(i.summary || i.error || i.mtime || 'No details available.');
    return '<div class="queue-row' + (isFailed ? ' failed' : '') + '" data-row="' + idx + '" tabindex="0">' +
      laneBadge(i.lane) + statusBadge(i.status) +
      '<div class="qr-main"><div class="qr-name">' + esc((i.kind ? i.kind + ': ' : '') + (i.name || '')) + '</div><div class="qr-summary">' + detail + '</div></div>' +
      '<span class="qr-kind">' + esc(i.kind || '') + '</span></div>' +
      '<div class="queue-detail"><pre>' + esc(i.summary || i.error || i.mtime || 'No details available.') + '</pre></div>';
  }).join('');
  document.getElementById('timeline').innerHTML = banner + '<div class="queue-list">' + rows + '</div>';
}
function renderSquads() {
  const s = state.squads || {}, semi = s.semi_auto || {};
  const summary = '<section class="panel"><h2 style="font-size:var(--text-large);margin-bottom:var(--space-2);">Team Settings</h2>' +
    row('Max workers', s.max_workers || 0) + row('Default lane', s.default_lane || 'local_only') +
    row('Auto review', semi.auto_review ? 'on' : 'off', semi.auto_review ? 'ok' : '') +
    row('Auto docs', semi.auto_docs ? 'on' : 'off', semi.auto_docs ? 'ok' : '') +
    row('Auto tests', semi.auto_tests ? 'on' : 'off', semi.auto_tests ? 'ok' : 'warn') +
    row('Never auto-write', semi.never_auto_write ? 'enforced' : 'off', semi.never_auto_write ? 'ok' : 'bad') +
    '</section>';
  const groups = (s.squads || []).map(group => {
    const count = (group.agents || []).length;
    return '<div class="squad-card' + (count === 0 ? ' empty' : '') + '"><h3>' + esc(group.name) + ' <span class="count">' + count + (count === 1 ? ' agent' : ' agents') + '</span></h3>' +
      (count === 0 ? '<div class="desc">No agents assigned.</div>' : '<div class="chip-row">' + group.agents.map(chip).join('') + '</div>') + '</div>';
  }).join('');
  const cc = (state.claude_crew || {}).agents || [];
  const claudeCrew = '<section class="panel"><h2 style="font-size:var(--text-large);margin-bottom:var(--space-2);">Claude Crew <span class="tier-badge">&#128269; .claude/agents</span></h2>' +
    '<div class="desc">Claude Code subagents detected in this repo &mdash; distinct from the harness roles above; these build the app itself (Claude/Codex).</div>' +
    (cc.length ? '<div class="chip-row" style="margin-top:var(--space-2);">' + cc.map(a => '<div class="chip"><span class="chip-name">' + esc(a.name) + '</span><span class="tier-badge">' + esc(a.model || 'inherit') + '</span></div>').join('') + '</div>'
      : '<div class="desc" style="margin-top:var(--space-2);">None found &mdash; add <code>.claude/agents/*.md</code> and they appear here.</div>') +
    '</section>';
  document.getElementById('squadGrid').innerHTML = summary + '<div class="squad-grid" style="margin-top:var(--space-3);">' + groups + '</div>' + claudeCrew;
  laneEl.value = s.default_lane || 'local_only';
  workersEl.value = s.max_workers || 3;
  const naCategory = document.getElementById('naCategory');
  if (naCategory) {
    const cats = state.categories || [];
    const prevVal = naCategory.value;
    naCategory.innerHTML = '<option value="">(none)</option>' + cats.map(c => '<option value="' + esc(c.id) + '">' + esc(c.name) + '</option>').join('');
    if (cats.some(c => c.id === prevVal)) naCategory.value = prevVal;
  }
}
function modelRow(x, maxSize) {
  const pct = maxSize ? Math.max(2, Math.round((x.size_gb / maxSize) * 100)) : 0;
  const meta = [x.parameter_size, x.quantization, x.context_length ? (x.context_length + ' ctx') : ''].filter(Boolean).join(' · ');
  const caps = (x.capabilities || []).join(', ');
  return '<div class="model-row"><div><div class="m-name">' + esc(x.name) + '</div><div class="m-meta">' + esc(meta || 'n/a') + '</div></div>' +
    '<span class="tier-badge">' + esc(caps || 'n/a') + '</span><span></span>' +
    '<div class="size-bar-track"><div class="size-bar-fill" style="width:' + pct + '%"></div></div>' +
    '<span class="m-gb">' + esc(x.size_gb || 0) + ' GB</span></div>';
}
function renderModels() {
  const m = state.models || {}, disk = m.disk || {};
  const models = m.models || [];
  const maxSize = models.reduce((mx, x) => Math.max(mx, x.size_gb || 0), 0);
  const capNote = m.capabilities_note ? '<div class="gauge-note">&#9888; ' + esc(m.capabilities_note) + '</div>' : '';
  const usedPct = disk.total_gb ? Math.min(100, Math.round((disk.used_gb / disk.total_gb) * 100)) : 0;
  const freePct = 100 - usedPct;
  const lowHeadroom = maxSize > 0 && (disk.free_gb || 0) < maxSize * 2;
  const installedList = models.length
    ? '<div class="model-list">' + models.map(x => modelRow(x, maxSize)).join('') + '</div>' + capNote
    : '<div class="empty-state"><div class="glyph">&#128230;</div><div><strong>No local models installed.</strong></div><div>See suggested pulls below.</div></div>';
  const recs = (m.suggested || []).map(x => '<div class="pull-item"><div><code>' + esc(x.command) + '</code><div class="reason">' + esc(x.reason) + '</div></div><button class="btn copy-btn" data-copy="' + esc(x.command) + '">&#128203; Copy</button></div>').join('');
  document.getElementById('modelGrid').innerHTML =
    '<section class="block"><h2>Installed Models</h2>' + installedList + '</section>' +
    '<section class="block"><div class="resource-grid">' +
      '<div class="gauge-card"><h3 style="font-size:var(--text-medium);margin-bottom:var(--space-2);">Disk usage</h3>' +
      '<div class="gauge-readout"><span>' + (disk.free_gb || 0) + ' GB free of ' + (disk.total_gb || 0) + ' GB</span><span>' + freePct + '% free</span></div>' +
      '<div class="gauge-track"><div class="gauge-used" style="width:' + usedPct + '%"></div><div class="gauge-free" style="width:' + freePct + '%;' + (lowHeadroom ? 'background:var(--mc-warning);' : '') + '"></div></div>' +
      (lowHeadroom ? '<div class="gauge-note">Low headroom for pulling additional models.</div>' : '') + '</div>' +
      '<div class="stat-card"><div class="tile-head" style="color:var(--mc-text-muted);font-size:var(--text-small);">Safe parallel workers</div><div class="tile-value">' + (m.safe_parallel_workers_estimate || 1) + '</div><div class="tile-sub">estimated from free disk &divide; (2 &times; largest model)</div>' +
      (m.safe_parallel_workers_note ? '<div class="tile-sub" style="color:var(--mc-warning);">&#9888; ' + esc(m.safe_parallel_workers_note) + '</div>' : '') + '</div>' +
    '</div></section>' +
    '<section class="block"><h2>Suggested Pulls</h2><div class="desc">Commands are copied to your clipboard, never run automatically.</div><div class="pull-list">' + (recs || '<div class="desc">No suggestions right now.</div>') + '</div></section>';
}
// FIVE states, and they must never collapse into green. "unknown" is rendered
// as the word "unknown" on purpose: a UI that shows a plausible zero for a
// number nobody measured is worse than one that admits it does not know.
// (No backticks anywhere below: this whole block lives inside a template
// literal, and a stray backtick silently truncates the entire webview.)
const GOV_STATE_META = {
  working:  { glyph: '&#10003;', cls: 'pass', label: 'working'  },
  present:  { glyph: '&#9679;',  cls: 'warn', label: 'present'  },
  degraded: { glyph: '&#9888;',  cls: 'fail', label: 'degraded' },
  absent:   { glyph: '&#10007;', cls: 'fail', label: 'absent'   },
  unknown:  { glyph: '?',        cls: 'warn', label: 'unknown'  }
};
function govMeta(s) { return GOV_STATE_META[s] || GOV_STATE_META.unknown; }
function renderGovernance() {
  const el = document.getElementById('governanceGrid');
  if (!el) { return; }
  const g = state.governance;
  // No payload is NOT "fine". An older backend that does not serve this block
  // must read as unknown, never as permission.
  if (!g) {
    el.innerHTML = '<div class="banner danger"><span class="glyph">?</span><span>' +
      'Promotion status is <strong>unknown</strong>: this backend did not report a ' +
      'governance verdict. Treat it as unproven, not as permission.</span></div>';
    return;
  }
  const allowed = g.promotion_allowed === true;
  const meta = govMeta(g.state);
  const head = g.head ? String(g.head).slice(0, 12) : 'unknown';
  const banner = '<div class="banner' + (allowed ? '' : ' danger') + '">' +
    '<span class="glyph">' + (allowed ? '&#10003;' : '&#10007;') + '</span><span><strong>' +
    (allowed ? 'Promotion allowed' : 'Promotion REFUSED') + '</strong> &middot; ' +
    esc(g.verdict || '') + '</span></div>';
  const rows = (g.gates || []).map(function (gate) {
    const m = govMeta(gate.state);
    return '<div class="gate-row ' + m.cls + '"><span class="glyph">' + m.glyph + '</span>' +
      '<span class="g-name">' + esc(gate.id || '') + '</span>' +
      '<span class="g-reason">' + esc(gate.headline || '') + '</span>' +
      '<span class="g-result">' + esc(m.label) + '</span></div>';
  }).join('');
  // Provenance is rendered, not just recorded: an INHERITED verdict is a
  // measurement of some other tree until proven otherwise.
  const prov = (g.gates || []).map(function (gate) {
    return esc(gate.id || '') + ': ' + esc(gate.provenance || 'ASSUMED');
  }).join(' &middot; ');
  el.innerHTML = banner +
    (rows ? '<div class="gate-list" style="margin-top:var(--space-3);">' + rows + '</div>' : '') +
    '<div class="desc" style="margin-top:var(--space-2);">Aggregate state: <strong>' +
    esc(meta.label) + '</strong> &middot; HEAD ' + esc(head) + '</div>' +
    (prov ? '<div class="desc">Provenance &mdash; ' + prov + '</div>' : '');
}
function renderQuality() {
  const q = state.quality || {};
  // MEASURED DEFECT, fixed here: these gates used to negate q.stale_watchers
  // and q.fallback_alarm directly. When the quality block was missing -- a
  // failed dashboard fetch, an older backend -- both operands were undefined,
  // so both negations were TRUE and the panel rendered two green PASSES for
  // measurements that had never been taken. "We did not ask" was rendering
  // identically to "we asked and it was fine". A gate whose input is absent is
  // now UNKNOWN, which is not a pass.
  const known = k => Object.prototype.hasOwnProperty.call(q, k) && q[k] !== null && q[k] !== undefined;
  const bgate = (name, key, reason) => ({
    name: name,
    state: known(key) ? (q[key] ? 'pass' : 'fail') : 'unknown',
    reason: reason
  });
  const gates = [
    bgate('schema_non_empty_summary', 'schema_non_empty_summary', 'Empty-summary reports are not accepted.'),
    bgate('local_only_never_claude', 'local_only_never_claude', 'local_only lane must never reach the Claude provider.'),
    bgate('empty_reports_fail', 'empty_reports_fail', 'Reports with no content must fail, not silently pass.'),
    { name: 'stale_watchers == 0',
      state: known('stale_watchers') ? (q.stale_watchers ? 'fail' : 'pass') : 'unknown',
      reason: (q.stale_watchers || 0) + ' stale watcher(s) detected.' },
    { name: 'fallback_alarm == false',
      state: known('fallback_alarm') ? (q.fallback_alarm ? 'fail' : 'pass') : 'unknown',
      reason: 'Fallback alarm is active.' }
  ];
  const GLYPH = { pass: '&#10003;', fail: '&#10007;', unknown: '?' };
  const WORD = { pass: 'Pass', fail: 'Fail', unknown: 'unknown' };
  const CLS = { pass: 'pass', fail: 'fail', unknown: 'warn' };
  const UNMEASURED = 'Not measured in this run -- this is NOT a pass.';
  const rows = gates.map(g => '<div class="gate-row ' + CLS[g.state] + '"><span class="glyph">' + GLYPH[g.state] + '</span><span class="g-name">' + esc(g.name) + '</span>' +
    (g.state === 'pass' ? '' : '<span class="g-reason">' + esc(g.state === 'unknown' ? UNMEASURED : g.reason) + '</span>') +
    '<span class="g-result">' + WORD[g.state] + '</span></div>').join('');
  // Same rule for the meter: an unmeasured rate rendered "0%", which is the
  // most flattering number it could possibly have invented.
  const rateKnown = known('fallback_rate');
  const ratePct = Math.round((q.fallback_rate || 0) * 100);
  const meterCls = q.fallback_alarm ? 'danger' : (rateKnown && ratePct >= 20 ? 'warn' : '');
  const meter = '<div class="meter-card"><div class="meter-head"><span>Fallback rate</span>' + (q.fallback_alarm ? '<span class="alarm-tag">ALARM</span>' : '') + '</div>' +
    (rateKnown
      ? '<div class="meter-track"><div class="meter-fill' + (meterCls ? ' ' + meterCls : '') + '" style="width:' + Math.max(ratePct, 4) + '%">' + ratePct + '%</div></div>'
      : '<div class="desc">unknown &mdash; no fallback rate was reported, so no rate is shown.</div>') +
    '</div>';
  const callout = q.recommendation ? '<div class="callout"><span class="glyph">&#128161;</span><span>' + esc(q.recommendation) + '</span></div>' : '';
  document.getElementById('qualityGrid').innerHTML =
    '<section class="block"><h2>Quality Gates</h2><div class="gate-list">' + rows + '</div></section>' +
    '<section class="block">' + meter + '</section>' +
    (callout ? '<section class="block">' + callout + '</section>' : '');
}
const WHEEL_COLOR_CHOICES = ['#3794ff', '#b180d7', '#e07b53', '#d7ba7d', '#73c991', '#f14c4c', '#4fc1c1', '#d97ad9', '#6b8afd', '#a3a3a3'];
const WHEEL_ICON_CHOICES = ['🛠️', '🔍', '🎨', '📚', '🧪', '🔭', '⚙️', '🗄️', '🚀', '🧩', '🔐', '📊', '🖥️', '🧬'];
let selectedCategoryId = null;
function wheelAnnounce(msg) { const el = document.getElementById('wheel-status'); if (el) el.textContent = msg; }
function wheelCatById(id) { return (state.categories || []).find(c => c.id === id) || null; }
function wheelAgentChip(a) {
  const tierBadge = a.model_tier ? '<span class="tier-badge">' + esc(a.model_tier) + '</span>' : '';
  const extGlyph = '<span class="ext-glyph" title="' + (a.external_ok ? 'external ok' : 'local only') + '">' + (a.external_ok ? '&#128275;' : '&#128274;') + '</span>';
  return '<div class="chip"><span class="chip-name">' + esc(a.call_name || a.name) + '</span>' + tierBadge + extGlyph + '</div>';
}
function renderWheelStage() {
  const stage = document.getElementById('wheel-stage');
  const svg = document.getElementById('wheel-svg');
  const legend = document.getElementById('wheel-legend');
  if (!stage || !svg) return;
  stage.querySelectorAll('.wheel-node').forEach(node => node.remove());
  svg.innerHTML = '';
  const cats = state.categories || [];
  const n = cats.length;
  if (legend) legend.textContent = n + ' role categor' + (n === 1 ? 'y' : 'ies') + ' · click a node to inspect & customize';
  if (!n) return;
  const radius = 37;
  cats.forEach((cat, i) => {
    const angleDeg = -90 + (i * 360 / n);
    const angleRad = angleDeg * Math.PI / 180;
    const cx = 50 + radius * Math.cos(angleRad);
    const cy = 50 + radius * Math.sin(angleRad);

    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', '50');
    line.setAttribute('y1', '50');
    line.setAttribute('x2', String(cx));
    line.setAttribute('y2', String(cy));
    line.setAttribute('data-cat', cat.id);
    if (cat.id === selectedCategoryId) { line.classList.add('selected'); line.setAttribute('stroke', cat.color); }
    svg.appendChild(line);

    const isEmpty = !cat.count;
    const isSelected = cat.id === selectedCategoryId;
    const node = document.createElement('div');
    node.className = 'wheel-node' + (isEmpty ? ' is-empty' : '');
    node.style.left = cx + '%';
    node.style.top = cy + '%';

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'node-btn' + (isEmpty ? ' is-empty' : '');
    btn.style.setProperty('--node-color', cat.color);
    btn.setAttribute('aria-pressed', isSelected ? 'true' : 'false');
    btn.setAttribute('data-cat', cat.id);
    btn.setAttribute('aria-label', cat.name + ' category, ' + cat.count + ' agent' + (cat.count === 1 ? '' : 's'));
    btn.innerHTML = esc(cat.icon) + '<span class="node-dot" style="--node-color:' + esc(cat.color) + '"></span>';
    btn.addEventListener('click', () => selectWheelCategory(cat.id, true));
    btn.addEventListener('keydown', ev => {
      const idx = cats.findIndex(c => c.id === cat.id);
      let next = null;
      if (ev.key === 'ArrowRight' || ev.key === 'ArrowDown') next = cats[(idx + 1) % n];
      else if (ev.key === 'ArrowLeft' || ev.key === 'ArrowUp') next = cats[(idx - 1 + n) % n];
      if (next) {
        ev.preventDefault();
        selectWheelCategory(next.id, true);
        const nextBtn = stage.querySelector('.node-btn[data-cat="' + next.id + '"]');
        if (nextBtn) nextBtn.focus();
      }
    });

    const label = document.createElement('div');
    label.className = 'node-label';
    label.textContent = cat.name;
    const count = document.createElement('div');
    count.className = 'node-count';
    count.textContent = cat.count + ' agent' + (cat.count === 1 ? '' : 's');

    node.appendChild(btn);
    node.appendChild(label);
    node.appendChild(count);
    stage.appendChild(node);
  });
}
function renderWheelDetail() {
  const detail = document.getElementById('wheel-detail');
  if (!detail) return;
  const cat = wheelCatById(selectedCategoryId);
  if (!cat) {
    detail.innerHTML = '<div class="empty-state"><div class="glyph">&#127920;</div><div><strong>No role categories configured.</strong></div></div>';
    return;
  }
  let html = '';
  html += '<div class="detail-head"><div class="detail-swatch" style="--node-color:' + esc(cat.color) + '">' + esc(cat.icon) + '</div><div><h3>' + esc(cat.name) + '</h3><div class="detail-count">' + cat.count + ' agent' + (cat.count === 1 ? '' : 's') + '</div></div></div>';
  html += '<div><div class="detail-row-label">Routing preset</div><div class="chip-row">' + laneBadge(cat.lane) + '<span class="tier-badge">' + esc(cat.tier) + '</span></div></div>';
  html += '<div><div class="detail-row-label">Agents</div>';
  if (!cat.agents || !cat.agents.length) {
    html += '<div class="empty-state"><div class="glyph">&#128101;</div><div><strong>No agents assigned to this category yet.</strong></div><div>Assign one via the New Agent form (category dropdown) or <code>daedalus agents edit &lt;name&gt; --category ' + esc(cat.id) + '</code></div></div>';
  } else {
    html += '<div class="chip-row">' + cat.agents.map(wheelAgentChip).join('') + '</div>';
  }
  html += '</div>';
  html += '<div><div class="detail-row-label">Customize &mdash; color</div><div class="swatch-row" role="group" aria-label="Recolor ' + esc(cat.name) + '">' +
    WHEEL_COLOR_CHOICES.map(hex => '<button type="button" class="swatch-btn" style="background:' + hex + '" data-hex="' + hex + '" aria-pressed="' + (hex.toLowerCase() === String(cat.color).toLowerCase()) + '" aria-label="Set color ' + hex + '"></button>').join('') +
    '</div><div class="customize-readout">Color: ' + esc(cat.color) + '</div></div>';
  html += '<div><div class="detail-row-label">Customize &mdash; icon</div><div class="emoji-row" role="group" aria-label="Re-icon ' + esc(cat.name) + '">' +
    WHEEL_ICON_CHOICES.map(icon => '<button type="button" class="emoji-btn" data-icon="' + icon + '" aria-pressed="' + (icon === cat.icon) + '" aria-label="Set icon">' + icon + '</button>').join('') +
    '</div><div class="customize-readout">Icon: ' + esc(cat.icon) + '</div></div>';
  detail.innerHTML = html;
}
function selectWheelCategory(id, userInitiated) {
  selectedCategoryId = id;
  renderWheelStage();
  renderWheelDetail();
  if (userInitiated) {
    const cat = wheelCatById(id);
    if (cat) wheelAnnounce('Selected ' + cat.name + ' — ' + cat.count + ' agent' + (cat.count === 1 ? '' : 's') + '.');
  }
}
function renderRoleWheel() {
  const cats = state.categories || [];
  if (!selectedCategoryId || !cats.some(c => c.id === selectedCategoryId)) {
    selectedCategoryId = cats.length ? cats[0].id : null;
  }
  renderWheelStage();
  renderWheelDetail();
}
function renderAll() { renderProjects(); renderOverview(); renderGovernance(); renderQueue(); renderSquads(); renderModels(); renderQuality(); renderRoleWheel(); }
function save() {
  const activeAgents = Array.from(document.querySelectorAll('.toggle.on[data-agent]')).map(el => el.dataset.agent);
  vscode.postMessage({ type: 'saveTeam', project: projectEl.value, maxWorkers: workersEl.value, defaultLane: laneEl.value, activeAgents });
}
window.addEventListener('message', event => { if (event.data.type === 'state') { state = event.data.state; renderAll(); } });
let activeTab = 'overview';
document.querySelectorAll('.tab').forEach(b => b.addEventListener('click', () => { document.querySelectorAll('.tab,.page').forEach(x => x.classList.remove('active')); b.classList.add('active'); document.getElementById(b.dataset.tab).classList.add('active'); activeTab = b.dataset.tab; }));
projectEl.addEventListener('change', () => vscode.postMessage({ type: 'refresh', project: projectEl.value }));
document.getElementById('save').addEventListener('click', save);
document.getElementById('refresh').addEventListener('click', () => vscode.postMessage({ type: 'refresh', project: projectEl.value }));
document.getElementById('enforce').addEventListener('click', () => vscode.postMessage({ type: 'enforce', project: projectEl.value }));
document.getElementById('timeline').addEventListener('click', ev => {
  const rowEl = ev.target.closest('.queue-row');
  if (!rowEl) return;
  const wasSelected = rowEl.classList.contains('selected');
  document.querySelectorAll('#timeline .queue-row.selected').forEach(r => r.classList.remove('selected'));
  if (!wasSelected) rowEl.classList.add('selected');
});
document.getElementById('squadGrid').addEventListener('click', ev => {
  const t = ev.target.closest('.toggle[data-agent]');
  if (!t) return;
  t.classList.toggle('on');
  t.setAttribute('aria-checked', t.classList.contains('on') ? 'true' : 'false');
});
document.getElementById('squadGrid').addEventListener('keydown', ev => {
  const t = ev.target && ev.target.closest && ev.target.closest('.toggle[data-agent]');
  if (!t || (ev.key !== 'Enter' && ev.key !== ' ')) return;
  ev.preventDefault();
  t.classList.toggle('on');
  t.setAttribute('aria-checked', t.classList.contains('on') ? 'true' : 'false');
});
document.body.addEventListener('click', ev => {
  const action = ev.target && ev.target.dataset && ev.target.dataset.action;
  const copy = ev.target && ev.target.dataset && ev.target.dataset.copy;
  if (action) vscode.postMessage({ type: action, project: projectEl.value });
  if (copy) vscode.postMessage({ type: 'copy', text: copy });
});
document.getElementById('wheel-detail').addEventListener('click', ev => {
  const swatch = ev.target.closest('.swatch-btn[data-hex]');
  const emoji = ev.target.closest('.emoji-btn[data-icon]');
  if (!swatch && !emoji) return;
  const cat = wheelCatById(selectedCategoryId);
  if (!cat) return;
  const payload = { type: 'setCategory', project: projectEl.value, id: cat.id };
  if (swatch) payload.color = swatch.dataset.hex; else payload.icon = emoji.dataset.icon;
  vscode.postMessage(payload);
});
document.getElementById('addAgentBtn').addEventListener('click', () => {
  const naStatus = document.getElementById('naStatus');
  const name = document.getElementById('naName').value.trim();
  if (!name) { naStatus.textContent = 'Name is required.'; return; }
  naStatus.textContent = '';
  vscode.postMessage({
    type: 'addAgent',
    name,
    callName: document.getElementById('naCallName').value.trim(),
    modelTier: document.getElementById('naModelTier').value,
    externalOk: document.getElementById('naExternalOk').checked,
    triggers: document.getElementById('naTriggers').value.trim(),
    category: document.getElementById('naCategory').value,
    project: projectEl.value
  });
});
document.getElementById('queueTaskBtn').addEventListener('click', () => {
  const taskStatus = document.getElementById('taskStatus');
  const objective = document.getElementById('taskObjective').value.trim();
  if (!objective) { taskStatus.textContent = 'Objective is required.'; return; }
  taskStatus.textContent = '';
  vscode.postMessage({
    type: 'assignTask',
    objective,
    lane: document.getElementById('taskLane').value,
    agentHint: document.getElementById('taskAgent').value.trim(),
    project: projectEl.value
  });
  document.getElementById('taskObjective').value = '';
  document.getElementById('taskAgent').value = '';
});
let liveEnabled = true;
function updateLiveIndicator() {
  const dot = document.getElementById('liveDot');
  const text = document.getElementById('liveText');
  const btn = document.getElementById('livePause');
  if (!dot || !text || !btn) return;
  const onQueueTab = activeTab === 'queue';
  dot.className = 'live-dot value ' + (liveEnabled && onQueueTab ? 'ok' : 'warn');
  text.textContent = liveEnabled ? (onQueueTab ? 'Live' : 'Live (idle off-tab)') : 'Paused';
  btn.textContent = liveEnabled ? 'Pause' : 'Resume';
}
document.getElementById('livePause').addEventListener('click', () => { liveEnabled = !liveEnabled; updateLiveIndicator(); });
document.querySelectorAll('.tab').forEach(b => b.addEventListener('click', updateLiveIndicator));
updateLiveIndicator();
setInterval(() => { if (liveEnabled && activeTab === 'queue') vscode.postMessage({ type: 'refresh', project: projectEl.value }); }, 5000);
vscode.postMessage({ type: 'ready' });
</script>
</body>
</html>`;
}

async function bindDashboardWebview(context, webview, projectName) {
  webview.options = { enableScripts: true };
  const project = projectName || cfg().get("defaultProject") || (projects(context)[0] && projects(context)[0].name) || "";
  let inFlight = false;
  const attempt = async () => {
    if (inFlight) return;
    inFlight = true;
    // Rendered BEFORE the probe, not after: leaving webview.html untouched
    // during the ~0-5s connect window means "unknown" would render as a
    // blank panel, which reads as broken rather than as not-yet-checked.
    webview.html = backendStateHtml(nonce(), "checking", {});
    try {
      await ensureWebServer(context);
      webview.html = agentOsHtml(project);
    } catch (err) {
      const state = err instanceof BackendUnavailable ? err.state : "unknown";
      const detail = err instanceof BackendUnavailable ? err.detail : "";
      webview.html = backendStateHtml(nonce(), state, { message: err.message, detail, root: harnessRoot(context) });
    } finally {
      inFlight = false;
    }
  };
  webview.onDidReceiveMessage((msg) => {
    if (msg && msg.type === "retryBackend") attempt();
  });
  await attempt();
}

async function openDashboard(context) {
  if (dashboardPanel) {
    dashboardPanel.reveal(vscode.ViewColumn.Active);
    return;
  }
  const project = await pickProject(context);
  dashboardPanel = vscode.window.createWebviewPanel(
    "daedalusAgentOs",
    "Daedalus Agent OS",
    vscode.ViewColumn.Active,
    { enableScripts: true, retainContextWhenHidden: true }
  );
  await bindDashboardWebview(context, dashboardPanel.webview, project);
  dashboardPanel.onDidDispose(() => { dashboardPanel = undefined; });
}

class DashboardProvider {
  constructor(context) { this.context = context; }
  async resolveWebviewView(webviewView) { await bindDashboardWebview(this.context, webviewView.webview); }
}

class ProjectItem extends vscode.TreeItem {
  constructor(project) {
    super(project.name, vscode.TreeItemCollapsibleState.None);
    this.project = project;
    this.contextValue = "daedalusProject";
    this.description = project.repoRoot;
    this.tooltip = project.repoRoot || project.path;
    this.iconPath = new vscode.ThemeIcon("repo");
    this.command = { command: "daedalus.status", title: "Show Status", arguments: [this] };
  }
}

class ProjectsProvider {
  constructor(context) { this.context = context; this._onDidChangeTreeData = new vscode.EventEmitter(); this.onDidChangeTreeData = this._onDidChangeTreeData.event; }
  refresh() { this._onDidChangeTreeData.fire(); }
  getTreeItem(element) { return element; }
  getChildren() { return projects(this.context).map((p) => new ProjectItem(p)); }
}

class QueueItem extends vscode.TreeItem {
  constructor(label, fullPath, collapsible, contextValue) {
    super(label, collapsible);
    this.fullPath = fullPath;
    this.contextValue = contextValue;
    this.tooltip = fullPath;
    this.iconPath = contextValue === "daedalusQueueGroup" ? new vscode.ThemeIcon("folder") : new vscode.ThemeIcon("json");
    if (contextValue === "daedalusQueueFile") this.command = { command: "vscode.open", title: "Open", arguments: [vscode.Uri.file(fullPath)] };
  }
}

class QueueProvider {
  constructor(context) { this.context = context; this._onDidChangeTreeData = new vscode.EventEmitter(); this.onDidChangeTreeData = this._onDidChangeTreeData.event; }
  refresh() { this._onDidChangeTreeData.fire(); }
  getTreeItem(element) { return element; }
  async getChildren(element) {
    const root = harnessRoot(this.context);
    if (!root) return [];
    if (!element) return [
      new QueueItem("outbox", path.join(root, "outbox"), vscode.TreeItemCollapsibleState.Collapsed, "daedalusQueueGroup"),
      new QueueItem("inbox", path.join(root, "inbox"), vscode.TreeItemCollapsibleState.Collapsed, "daedalusQueueGroup"),
      new QueueItem("memory", path.join(root, "memory"), vscode.TreeItemCollapsibleState.Collapsed, "daedalusQueueGroup"),
      new QueueItem("runs/processed", path.join(root, "runs", "processed"), vscode.TreeItemCollapsibleState.Collapsed, "daedalusQueueGroup")
    ];
    if (!exists(element.fullPath)) return [];
    const items = fs.readdirSync(element.fullPath).sort().slice(-50).map((name) => {
      const full = path.join(element.fullPath, name);
      const isDir = fs.statSync(full).isDirectory();
      return new QueueItem(name, full, isDir ? vscode.TreeItemCollapsibleState.Collapsed : vscode.TreeItemCollapsibleState.None, isDir ? "daedalusQueueGroup" : "daedalusQueueFile");
    });
    // Live decoration (state / tri-state applied / staleness) for the three
    // groups the file bus assigns task ids in -- "memory" holds unrelated
    // artifacts (todos.local.md, event logs) with no task id to look up. A
    // PASSIVE tree render must never itself spawn the backend (that is
    // reserved for explicit actions -- see ensureWebServerForCommand's own
    // comment), so this only decorates when a server happens to already be
    // reachable, and otherwise silently reproduces the plain file listing
    // above byte-for-byte -- the same degrade path as an old backend that
    // predates these endpoints entirely.
    const liveGroups = new Set([
      path.join(root, "outbox"), path.join(root, "inbox"), path.join(root, "runs", "processed")
    ]);
    if (!liveGroups.has(element.fullPath) || !(await probeWebServer())) return items;
    await Promise.all(items.map(async (item) => {
      if (item.contextValue !== "daedalusQueueFile") return;
      const id = taskIdFromFilename(path.basename(item.fullPath));
      if (!id || !TASK_ID_RE.test(id)) return;
      const res = await apiGet(`/api/queue/${encodeURIComponent(id)}`);
      const snap = res.body && res.body.task;
      if (!res.ok || !snap || !snap.found) return; // unknown id / old backend / transient error -- leave undecorated, never guess
      item.description = describeSnapshot(snap);
      item.tooltip = snapshotTooltip(snap);
      item.iconPath = stateThemeIcon(snap);
    }));
    return items;
  }
}

async function updateStatusBar(context) {
  try {
    const project = cfg().get("defaultProject") || (projects(context)[0] && projects(context)[0].name);
    if (!project) { statusBar.text = "$(hubot) Daedalus: no projects"; return; }
    const data = await runJson(context, ["-m", "daedalus.status", "--project", project, "--json"], { timeout: 10000 });
    statusBar.text = `$(hubot) Daedalus: ${project} | ${data.outbox_count} pending | ${data.open_todos} TODOs`;
    statusBar.tooltip = `Inbox: ${data.inbox_count}, memory events: ${data.memory_events}`;
  } catch (err) {
    statusBar.text = "$(hubot) Daedalus: attention";
    statusBar.tooltip = String(err.message || err);
  }
}

function activate(context) {
  projectProvider = new ProjectsProvider(context);
  queueProvider = new QueueProvider(context);
  dashboardProvider = new DashboardProvider(context);
  // createTreeView (not registerTreeDataProvider) so live-status polling below
  // can check `.visible` and cost nothing while the Activity Bar is hidden.
  // It still registers the provider (tests/test_extension_manifest.py's
  // registered_treeview_ids() recognizes both call shapes as a registration).
  const queueTreeView = vscode.window.createTreeView("daedalusQueue", { treeDataProvider: queueProvider });
  // Live-status refresh for the Queue view: cheap (loopback-only HTTP) and
  // gated on the view actually being visible. Firing refresh() with no
  // element re-queries every currently EXPANDED node only -- see
  // QueueProvider.getChildren, which does the actual decoration and itself
  // degrades to a no-op fetch whenever the backend is unreachable.
  const queueLiveTimer = setInterval(() => {
    if (queueTreeView.visible) queueProvider.refresh();
  }, 10000);
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider("daedalusDashboardView", dashboardProvider),
    vscode.window.registerTreeDataProvider("daedalusProjects", projectProvider),
    queueTreeView,
    { dispose: () => clearInterval(queueLiveTimer) },
    // Registered once here rather than inside ensureWebServer(): that function
    // can now run more than once per session (the webview's Retry button),
    // and pushing a fresh dispose closure on every attempt would accumulate
    // one per retry. webServerProcess is read fresh at dispose time either way.
    { dispose: () => { if (webServerProcess) webServerProcess.kill(); } }
  );
  statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
  statusBar.command = "daedalus.openDashboard";
  statusBar.show();
  context.subscriptions.push(statusBar);
  context.subscriptions.push(
    vscode.commands.registerCommand("daedalus.refresh", () => { projectProvider.refresh(); queueProvider.refresh(); updateStatusBar(context); }),
    vscode.commands.registerCommand("daedalus.startWatcher", async (item) => { const project = await pickProject(context, item); if (!project) return; const ok = await confirmAction("Start bridge watcher?", `Project: ${project}\nThe watcher autonomously processes queued auto/claude tasks and may incur Claude spend with no further prompt per task. Local-only tasks stay local.`); if (ok) watcherTerminal = terminal(context, `Daedalus Bridge: ${project}`, ["-m", "daedalus.file_bridge", "watch", "--project", project]); }),
    vscode.commands.registerCommand("daedalus.stopWatcher", () => { if (watcherTerminal) watcherTerminal.dispose(); watcherTerminal = undefined; }),
    vscode.commands.registerCommand("daedalus.status", (item) => showStatus(context, item)),
    vscode.commands.registerCommand("daedalus.enqueueLocalOnly", (item) => enqueue(context, "local_only", "codex", "single", item)),
    vscode.commands.registerCommand("daedalus.enqueueAuto", (item) => enqueue(context, "auto", "codex", "single", item)),
    vscode.commands.registerCommand("daedalus.enqueueClaude", (item) => enqueue(context, "claude", "codex", "single", item)),
    vscode.commands.registerCommand("daedalus.reviewDiff", (item) => pickProject(context, item).then((project) => reviewDiff(context, project))),
    vscode.commands.registerCommand("daedalus.spawn", (item) => spawnIkarus(context, item)),
    vscode.commands.registerCommand("daedalus.openInbox", () => openFolder(context, "inbox")),
    vscode.commands.registerCommand("daedalus.openOutbox", () => openFolder(context, "outbox")),
    vscode.commands.registerCommand("daedalus.openMemory", () => openMemory(context)),
    vscode.commands.registerCommand("daedalus.openDashboard", () => openDashboard(context)),
    // Same panel, same underlying openDashboard() flow -- the web app already
    // opens into its chat space by default (apps/web/src/App.tsx: `useState
    // <Space>('chat')`), so "chat-first" here is a real, separately-discoverable
    // front door onto the SAME cockpit, not a second implementation of one.
    vscode.commands.registerCommand("daedalus.openChat", () => openDashboard(context)),
    vscode.commands.registerCommand("daedalus.askAboutFile", () => askAboutFile(context)),
    vscode.commands.registerCommand("daedalus.showTaskStatus", (item) => showTaskStatus(context, item)),
    vscode.commands.registerCommand("daedalus.showTaskArtifacts", (item) => showTaskArtifacts(context, item)),
    vscode.commands.registerCommand("daedalus.watchTask", (item) => watchTask(context, item))
  );
  updateStatusBar(context);
}

function deactivate() {
  if (watcherTerminal) watcherTerminal.dispose();
  if (webServerProcess) webServerProcess.kill();
  for (const [, entry] of activeTaskWatches) {
    try { entry.cancel(); } catch (_) { /* already closed */ }
    entry.channel.dispose();
  }
  activeTaskWatches.clear();
}

module.exports = { activate, deactivate };
