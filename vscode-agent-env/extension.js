const vscode = require("vscode");
const fs = require("fs");
const path = require("path");
const cp = require("child_process");

let projectProvider;
let queueProvider;
let dashboardProvider;
let watcherTerminal;
let statusBar;

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

async function enqueue(context, lane, source, strategy, item) {
  const project = await pickProject(context, item);
  if (!project) return;
  const objective = await vscode.window.showInputBox({ prompt: `Task for ${project} (${lane}, ${strategy})`, ignoreFocusOut: true });
  if (!objective) return;
  if (lane !== "local_only") {
    const ok = await confirmAction(`Send task to '${lane}' lane?`, `Project: ${project}\nLane: ${lane}\nObjective: ${objective}`);
    if (!ok) return;
  }
  const args = ["-m", "daedalus.file_bridge", "enqueue", objective, "--project", project, "--lane", lane, "--source", source, "--strategy", strategy];
  const filePath = currentFilePath();
  if (filePath) args.push("--paths", filePath);
  const output = await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: "Queueing Daedalus task" }, () => runPython(context, args));
  vscode.window.showInformationMessage(`Queued: ${output}`);
  queueProvider.refresh();
  updateStatusBar(context);
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

async function openLatestReport(context, state) {
  const report = state && state.queue && ((state.queue.reports || [])[0] || state.queue.latest_failed);
  if (!report || !report.path) return vscode.window.showWarningMessage("No report found yet.");
  const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(report.path));
  return vscode.window.showTextDocument(doc, { preview: true });
}

function nonce() {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

function dashboardHtml(n) {
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${n}';">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Daedalus Mission Control</title>
<style>
body { font-family: var(--vscode-font-family); color: var(--vscode-foreground); background: var(--vscode-editor-background); margin: 0; }
header { display: flex; gap: 12px; align-items: center; justify-content: space-between; padding: 14px 16px; border-bottom: 1px solid var(--vscode-panel-border); }
h1 { font-size: 18px; margin: 0; font-weight: 650; letter-spacing: 0; }
h2 { font-size: 13px; margin: 0 0 10px; text-transform: uppercase; color: var(--vscode-descriptionForeground); }
select, input { color: var(--vscode-input-foreground); background: var(--vscode-input-background); border: 1px solid var(--vscode-input-border); padding: 6px 8px; min-width: 120px; }
button { color: var(--vscode-button-foreground); background: var(--vscode-button-background); border: 0; border-radius: 4px; padding: 7px 10px; cursor: pointer; }
button.secondary { color: var(--vscode-button-secondaryForeground); background: var(--vscode-button-secondaryBackground); }
.tabs { display: flex; flex-wrap: wrap; gap: 2px; padding: 8px 12px 0; border-bottom: 1px solid var(--vscode-panel-border); }
.tab { background: transparent; color: var(--vscode-descriptionForeground); border-radius: 4px 4px 0 0; }
.tab.active { background: var(--vscode-tab-activeBackground); color: var(--vscode-tab-activeForeground); }
main { padding: 14px 16px 22px; }
.page { display: none; }
.page.active { display: block; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 12px; }
.panel { border: 1px solid var(--vscode-panel-border); border-radius: 6px; padding: 12px; background: var(--vscode-sideBar-background); }
.row { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 5px 0; border-bottom: 1px solid var(--vscode-panel-border); }
.row:last-child { border-bottom: 0; }
.label { color: var(--vscode-descriptionForeground); font-size: 12px; }
.value { font-weight: 600; text-align: right; }
.pill { border: 1px solid var(--vscode-panel-border); border-radius: 999px; padding: 2px 7px; font-size: 11px; color: var(--vscode-descriptionForeground); white-space: nowrap; }
.ok { color: var(--vscode-testing-iconPassed); }
.warn { color: var(--vscode-editorWarning-foreground); }
.bad { color: var(--vscode-testing-iconFailed); }
.actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.timeline { display: grid; gap: 8px; }
.event { border-left: 3px solid var(--vscode-focusBorder); padding: 8px 10px; background: var(--vscode-textCodeBlock-background); border-radius: 4px; }
.event .top { display: flex; justify-content: space-between; gap: 10px; }
.squad { display: grid; grid-template-columns: 100px 1fr; gap: 10px; align-items: start; }
.agents { display: flex; flex-wrap: wrap; gap: 6px; }
.agent { display: inline-flex; gap: 6px; align-items: center; border: 1px solid var(--vscode-panel-border); border-radius: 999px; padding: 4px 8px; }
.gauge { height: 8px; border-radius: 4px; background: var(--vscode-input-background); border: 1px solid var(--vscode-panel-border); overflow: hidden; margin: 6px 0 10px; }
.gauge > div { height: 100%; background: var(--vscode-progressBar-background, var(--vscode-focusBorder)); }
pre { white-space: pre-wrap; background: var(--vscode-textCodeBlock-background); padding: 10px; border-radius: 4px; max-height: 240px; overflow: auto; }
.muted { color: var(--vscode-descriptionForeground); font-size: 12px; line-height: 1.4; }
@media (max-width: 720px) { header { align-items: stretch; flex-direction: column; } .squad { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<header>
  <div><h1>Daedalus Mission Control</h1><div id="subtitle" class="muted"></div></div>
  <div class="actions"><select id="project"></select><button id="refresh">Refresh</button><button id="enforce">Enforce Harness</button></div>
</header>
<nav class="tabs">
  <button class="tab active" data-tab="overview">Overview</button>
  <button class="tab" data-tab="queue">Queue Timeline</button>
  <button class="tab" data-tab="squads">Agent Squads</button>
  <button class="tab" data-tab="models">Model Resources</button>
  <button class="tab" data-tab="quality">Quality Gates</button>
  <button class="tab" data-tab="commands">Command Deck</button>
</nav>
<main>
  <section id="overview" class="page active"><div id="warnings" class="timeline"></div><div class="grid" id="overviewGrid"></div><pre id="doctor"></pre></section>
  <section id="queue" class="page"><div class="actions"><button data-action="reviewDiff">Rerun local_only diff review</button><button data-action="enqueueAuto">Queue auto task</button><button data-action="openLatest">Open latest report</button></div><div class="timeline" id="timeline"></div></section>
  <section id="squads" class="page"><div class="panel"><h2>Ikarus Hierarchy</h2><div class="muted">Ikarus routes every task through the central file bus. Squads filter active agents and make ownership visible.</div></div><div class="grid" id="squadGrid"></div></section>
  <section id="models" class="page"><div class="grid" id="modelGrid"></div></section>
  <section id="quality" class="page"><div class="grid" id="qualityGrid"></div></section>
  <section id="commands" class="page"><div class="grid"><section class="panel"><h2>Team Controls</h2><div class="row"><span class="label">Default lane</span><select id="lane"><option value="local_only">local_only</option><option value="auto">auto</option><option value="local">local</option><option value="claude">claude</option></select></div><div class="row"><span class="label">Max agents</span><input id="workers" type="number" min="1" max="32" step="1"></div><div class="muted">Toggle agents in Agent Squads, then save.</div><div class="actions"><button id="save">Save Team Settings</button></div></section><section class="panel"><h2>Run</h2><div class="actions"><button data-action="startWatcher">Start watcher</button><button data-action="stopWatcher">Stop watcher</button><button data-action="reviewDiff">Local-only review current diff</button><button data-action="ikarusPlan">Ikarus plan</button><button data-action="enqueueFile">Queue selected file/task</button><button data-action="openLatest">Open latest report</button></div><p class="muted">Claude use, live writes, and model installs stay confirmation-first.</p></section></div></section>
</main>
<script nonce="${n}">
const vscode = acquireVsCodeApi();
let state = {};
const projectEl = document.getElementById('project');
const laneEl = document.getElementById('lane');
const workersEl = document.getElementById('workers');
function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function row(label, value, cls) { return '<div class="row"><span class="label">' + esc(label) + '</span><span class="value ' + (cls || '') + '">' + esc(value) + '</span></div>'; }
function renderProjects() {
  const names = (state.projects || []).map(p => p.name);
  projectEl.innerHTML = names.map(n => '<option value="' + esc(n) + '">' + esc(n) + '</option>').join('');
  projectEl.value = state.selected_project || names[0] || '';
}
function renderOverview() {
  const env = state.env || {}, exts = env.extensions || [], models = state.models || {}, watcher = state.watcher || {}, enf = state.enforcement || {}, q = state.quality || {}, sq = state.squads || {}, providers = ((state.provider_health || {}).providers || []);
  const claude = exts.some(e => e.kind === 'claude'), codex = exts.some(e => e.kind === 'codex');
  document.getElementById('subtitle').textContent = (state.project_config && state.project_config.repo_root) || '';
  const warnings = state.warnings || [];
  document.getElementById('warnings').innerHTML = warnings.length ? warnings.map(w => '<div class="event bad">' + esc(w) + '</div>').join('') : '';
  document.getElementById('overviewGrid').innerHTML =
    '<section class="panel"><h2>Project Status</h2>' + row('Project', state.selected_project || 'none') + row('Default lane', sq.default_lane || 'local_only') + row('Max workers', sq.max_workers || 0) + '</section>' +
    '<section class="panel"><h2>Harness</h2>' + row('Enforced', enf.enabled ? 'active' : 'not active', enf.enabled ? 'ok' : 'bad') + row('Watcher', watcher.running ? (watcher.stale_count ? 'stale watcher' : 'running') : 'stopped', watcher.stale_count ? 'bad' : '') + row('Fallback alarm', q.fallback_alarm ? 'active' : 'quiet', q.fallback_alarm ? 'bad' : 'ok') + '</section>' +
    '<section class="panel"><h2>Extensions</h2>' + row('Claude extension', claude ? 'found' : 'missing', claude ? 'ok' : 'warn') + row('Codex/OpenAI extension', codex ? 'found' : 'missing', codex ? 'ok' : 'warn') + row('Harness control', 'instructions + file bus') + '</section>' +
    '<section class="panel"><h2>Ollama</h2>' + row('Server', models.server_ready ? 'ready' : 'offline', models.server_ready ? 'ok' : 'bad') + row('CLI on PATH', models.ollama_cli_on_path ? 'yes' : 'no', models.ollama_cli_on_path ? 'ok' : 'warn') + row('Installed models', (models.models || []).length) + '</section>' +
    '<section class="panel"><h2>Provider Health</h2>' + providers.slice(0, 6).map(p => row(p.display_name || p.name, p.available ? 'available' : (p.implemented ? 'unavailable' : 'planned'), p.available ? 'ok' : 'warn')).join('') + '</section>' +
    '<section class="panel"><h2>Routing</h2>' + row('Selected lane', (state.routing || {}).selected_lane || 'n/a') + row('Recommended lane', (state.routing || {}).recommended_lane || 'n/a') + row('Reason', (state.routing || {}).reason || 'n/a') + '</section>' +
    '<section class="panel"><h2>Key Metrics</h2>' + row('Offloadable tasks', (state.metrics || {}).offloadable || 0) + row('Ran on bench', (state.metrics || {}).offloaded || 0) + row('Fell back to Claude', (state.metrics || {}).fell_back_to_claude || 0) + row('Fallback rate', Math.round(((state.metrics || {}).fallback_rate || 0) * 100) + '%', (state.metrics || {}).alarm ? 'bad' : 'ok') + '</section>';
  document.getElementById('doctor').textContent = env.doctor || '';
}
function renderQueue() {
  const q = state.queue || {};
  const failedPath = (q.latest_failed || {}).path;
  const items = [].concat(q.pending || [], q.reports || [], q.processed || []).slice(0, 40);
  const banner = q.latest_failed ? '<div class="event bad"><div class="top"><b>Latest failed: ' + esc(q.latest_failed.name) + '</b><span class="pill bad">failed</span></div><div class="muted">' + esc(q.latest_failed.error || q.latest_failed.summary || 'No details available.') + '</div></div>' : '';
  const cards = items.map(i => {
    const isFailed = Boolean(failedPath) && i.path === failedPath;
    const statusCls = i.status === 'failed' || i.error ? 'bad' : (i.status === 'done' ? 'ok' : '');
    return '<div class="event' + (isFailed ? ' bad' : '') + '"><div class="top"><b>' + esc(i.kind + ': ' + i.name) + '</b><span><span class="pill">' + esc(i.lane || 'lane n/a') + '</span> <span class="pill ' + statusCls + '">' + esc(i.status || 'queued') + '</span></span></div><div class="muted">' + esc(i.summary || i.error || i.mtime) + '</div></div>';
  }).join('');
  document.getElementById('timeline').innerHTML = (banner + cards) || '<div class="panel muted">No queue activity yet.</div>';
}
function renderSquads() {
  const s = state.squads || {}, semi = s.semi_auto || {};
  const summary = '<section class="panel"><h2>Team Settings</h2>' +
    row('Max workers', s.max_workers || 0) + row('Default lane', s.default_lane || 'local_only') +
    row('Auto review', semi.auto_review ? 'on' : 'off', semi.auto_review ? 'ok' : '') +
    row('Auto docs', semi.auto_docs ? 'on' : 'off', semi.auto_docs ? 'ok' : '') +
    row('Auto tests', semi.auto_tests ? 'on' : 'off', semi.auto_tests ? 'ok' : 'warn') +
    row('Never auto-write', semi.never_auto_write ? 'enforced' : 'off', semi.never_auto_write ? 'ok' : 'bad') +
    '</section>';
  const groups = (s.squads || []).map(group => '<section class="panel squad"><h2>' + esc(group.name) + '</h2><div class="agents">' + group.agents.map(a =>
    '<span class="agent"><input type="checkbox" data-agent="' + esc(a.name) + '" ' + (a.active ? 'checked' : '') + '><b>' + esc(a.name) + '</b>' +
    (a.call_name ? '<span class="pill">' + esc(a.call_name) + '</span>' : '') +
    (a.model_tier ? '<span class="pill">' + esc(a.model_tier) + '</span>' : '') +
    '<span class="pill">' + esc(a.external_ok ? 'external-ok' : 'trusted-only') + '</span></span>'
  ).join('') + '</div></section>').join('');
  const cc = (state.claude_crew || {}).agents || [];
  const claudeCrew = '<section class="panel"><h2>Claude Crew <span class="pill">&#128269; .claude/agents</span></h2>' +
    '<div class="muted">Claude Code subagents detected in this repo &mdash; distinct from the harness roles above; these build the app itself (Claude/Codex).</div>' +
    (cc.length ? '<div class="agents">' + cc.map(a => '<span class="agent"><b>' + esc(a.name) + '</b><span class="pill">' + esc(a.model || 'inherit') + '</span></span>').join('') + '</div>'
      : '<div class="muted">None found &mdash; add <code>.claude/agents/*.md</code> and they appear here.</div>') +
    '</section>';
  document.getElementById('squadGrid').innerHTML = summary + groups + claudeCrew;
  laneEl.value = s.default_lane || 'local_only';
  workersEl.value = s.max_workers || 3;
}
function renderModels() {
  const m = state.models || {}, disk = m.disk || {};
  const usedPct = disk.total_gb ? Math.min(100, Math.round((disk.used_gb / disk.total_gb) * 100)) : 0;
  const capNote = m.capabilities_note ? '<div class="muted">⚠ ' + esc(m.capabilities_note) + '</div>' : '';
  const installed = (m.models || []).map(x => '<section class="panel"><h2>' + esc(x.name) + '</h2>' + row('Size', x.size_gb + ' GB') + row('Params', x.parameter_size || 'n/a') + row('Quant', x.quantization || 'n/a') + row('Capabilities', (x.capabilities || []).join(', ') || 'n/a') + capNote + '</section>').join('');
  const recs = (m.suggested || []).map(x => '<div class="row"><span><b>' + esc(x.name) + '</b><br><span class="muted">' + esc(x.reason) + '</span></span><button class="secondary" data-copy="' + esc(x.command) + '">Copy pull</button></div>').join('');
  document.getElementById('modelGrid').innerHTML =
    '<section class="panel"><h2>Disk Budget</h2>' +
    '<div class="gauge"><div style="width:' + usedPct + '%"></div></div>' +
    '<div class="muted">' + usedPct + '% used (' + (disk.used_gb || 0) + ' GB of ' + (disk.total_gb || 0) + ' GB)</div>' +
    row('Free disk', (disk.free_gb || 0) + ' GB') + row('Installed total', (m.total_size_gb || 0) + ' GB') + row('Safe parallel workers', m.safe_parallel_workers_estimate || 1) +
    (m.safe_parallel_workers_note ? '<div class="muted">⚠ ' + esc(m.safe_parallel_workers_note) + '</div>' : '') + '</section>' +
    installed + '<section class="panel"><h2>Suggested Pulls</h2><div class="muted">Commands are copied to your clipboard, never run automatically.</div>' + recs + '</section>';
}
function renderQuality() {
  const q = state.quality || {};
  document.getElementById('qualityGrid').innerHTML =
    '<section class="panel"><h2>Sentinels</h2>' + row('local_only never calls Claude', q.local_only_never_claude ? 'armed' : 'broken', q.local_only_never_claude ? 'ok' : 'bad') + row('Empty summaries fail', q.schema_non_empty_summary ? 'armed' : 'missing', q.schema_non_empty_summary ? 'ok' : 'bad') + row('Empty reports fail', q.empty_reports_fail ? 'armed' : 'missing', q.empty_reports_fail ? 'ok' : 'bad') + '</section>' +
    '<section class="panel"><h2>Runtime Warnings</h2>' + row('Stale watchers', q.stale_watchers || 0, q.stale_watchers ? 'bad' : 'ok') + row('Fallback rate', q.fallback_rate || 0, q.fallback_alarm ? 'bad' : 'ok') + row('Recommendation', q.recommendation || 'normal operation') + '</section>';
}
function renderAll() { renderProjects(); renderOverview(); renderQueue(); renderSquads(); renderModels(); renderQuality(); }
function save() {
  const activeAgents = Array.from(document.querySelectorAll('[data-agent]:checked')).map(el => el.dataset.agent);
  vscode.postMessage({ type: 'saveTeam', project: projectEl.value, maxWorkers: workersEl.value, defaultLane: laneEl.value, activeAgents });
}
window.addEventListener('message', event => { if (event.data.type === 'state') { state = event.data.state; renderAll(); } });
document.querySelectorAll('.tab').forEach(b => b.addEventListener('click', () => { document.querySelectorAll('.tab,.page').forEach(x => x.classList.remove('active')); b.classList.add('active'); document.getElementById(b.dataset.tab).classList.add('active'); }));
projectEl.addEventListener('change', () => vscode.postMessage({ type: 'refresh', project: projectEl.value }));
document.getElementById('save').addEventListener('click', save);
document.getElementById('refresh').addEventListener('click', () => vscode.postMessage({ type: 'refresh', project: projectEl.value }));
document.getElementById('enforce').addEventListener('click', () => vscode.postMessage({ type: 'enforce', project: projectEl.value }));
document.body.addEventListener('click', ev => {
  const action = ev.target && ev.target.dataset && ev.target.dataset.action;
  const copy = ev.target && ev.target.dataset && ev.target.dataset.copy;
  if (action) vscode.postMessage({ type: action, project: projectEl.value });
  if (copy) vscode.postMessage({ type: 'copy', text: copy });
});
vscode.postMessage({ type: 'ready' });
</script>
</body>
</html>`;
}

function bindDashboardWebview(context, webview) {
  webview.options = { enableScripts: true };
  webview.html = dashboardHtml(nonce());
  let lastState = {};
  async function postState(project) {
    lastState = await dashboardState(context, project);
    webview.postMessage({ type: "state", state: lastState });
  }
  webview.onDidReceiveMessage(async (message) => {
    try {
      if (message.type === "ready" || message.type === "refresh") {
        await postState(message.project);
      } else if (message.type === "saveTeam") {
        saveProjectTeam(context, message);
        projectProvider.refresh();
        await postState(message.project);
        vscode.window.showInformationMessage(`Saved Daedalus team settings for ${message.project}`);
      } else if (message.type === "enforce") {
        const result = await enforceProject(context, message.project);
        if (result !== null) {
          projectProvider.refresh();
          queueProvider.refresh();
          await postState(message.project);
          vscode.window.showInformationMessage(`Harness enforced for ${message.project}`);
        }
      } else if (message.type === "reviewDiff") {
        await reviewDiff(context, message.project);
        await postState(message.project);
      } else if (message.type === "enqueueAuto") {
        await enqueue(context, "auto", "codex", "single", { project: { name: message.project } });
        await postState(message.project);
      } else if (message.type === "enqueueFile") {
        await enqueue(context, "local_only", "codex", "single", { project: { name: message.project } });
        await postState(message.project);
      } else if (message.type === "ikarusPlan") {
        await spawnIkarus(context, { project: { name: message.project } });
      } else if (message.type === "startWatcher") {
        const ok = await confirmAction("Start bridge watcher?", `Project: ${message.project}\nThe watcher autonomously processes queued auto/claude tasks and may incur Claude spend with no further prompt per task. Local-only tasks stay local.`);
        if (!ok) return;
        watcherTerminal = terminal(context, `Daedalus Bridge: ${message.project}`, ["-m", "daedalus.file_bridge", "watch", "--project", message.project]);
      } else if (message.type === "stopWatcher") {
        if (watcherTerminal) watcherTerminal.dispose();
        watcherTerminal = undefined;
        await postState(message.project);
      } else if (message.type === "openLatest") {
        await openLatestReport(context, lastState);
      } else if (message.type === "copy") {
        await vscode.env.clipboard.writeText(message.text || "");
        vscode.window.showInformationMessage(`Copied: ${message.text}`);
      }
    } catch (err) {
      vscode.window.showErrorMessage(String(err.message || err));
    }
  });
}

async function openDashboard() {
  await vscode.commands.executeCommand("daedalusDashboardView.focus");
}

class DashboardProvider {
  constructor(context) { this.context = context; }
  resolveWebviewView(webviewView) { bindDashboardWebview(this.context, webviewView.webview); }
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
  getChildren(element) {
    const root = harnessRoot(this.context);
    if (!root) return [];
    if (!element) return [
      new QueueItem("outbox", path.join(root, "outbox"), vscode.TreeItemCollapsibleState.Collapsed, "daedalusQueueGroup"),
      new QueueItem("inbox", path.join(root, "inbox"), vscode.TreeItemCollapsibleState.Collapsed, "daedalusQueueGroup"),
      new QueueItem("memory", path.join(root, "memory"), vscode.TreeItemCollapsibleState.Collapsed, "daedalusQueueGroup"),
      new QueueItem("runs/processed", path.join(root, "runs", "processed"), vscode.TreeItemCollapsibleState.Collapsed, "daedalusQueueGroup")
    ];
    if (!exists(element.fullPath)) return [];
    return fs.readdirSync(element.fullPath).sort().slice(-50).map((name) => {
      const full = path.join(element.fullPath, name);
      const isDir = fs.statSync(full).isDirectory();
      return new QueueItem(name, full, isDir ? vscode.TreeItemCollapsibleState.Collapsed : vscode.TreeItemCollapsibleState.None, isDir ? "daedalusQueueGroup" : "daedalusQueueFile");
    });
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
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider("daedalusDashboardView", dashboardProvider),
    vscode.window.registerTreeDataProvider("daedalusProjects", projectProvider),
    vscode.window.registerTreeDataProvider("daedalusQueue", queueProvider)
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
    vscode.commands.registerCommand("daedalus.openDashboard", () => openDashboard(context))
  );
  updateStatusBar(context);
}

function deactivate() {
  if (watcherTerminal) watcherTerminal.dispose();
}

module.exports = { activate, deactivate };
