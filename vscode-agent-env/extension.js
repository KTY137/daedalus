const vscode = require("vscode");
const fs = require("fs");
const path = require("path");
const cp = require("child_process");

let projectProvider;
let queueProvider;
let dashboardProvider;
let dashboardPanel;
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

  .meter-card { background: var(--mc-surface-card); border: 1px solid var(--mc-border); border-radius: 6px; padding: var(--space-3); }
  .meter-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--space-2); font-size: var(--text-small); }
  .alarm-tag { color: var(--mc-danger); font-weight: 700; font-size: var(--text-micro); border: 1px solid var(--mc-danger); border-radius: 999px; padding: 1px 8px; }
  .meter-track { height: 12px; border-radius: 6px; background: var(--mc-surface-elevated); overflow: hidden; }
  .meter-fill { height: 100%; background: var(--mc-success); display: flex; align-items: center; justify-content: flex-end; padding-right: 6px; font-size: 9px; color: #fff; white-space: nowrap; }
  .meter-fill.warn { background: var(--mc-warning); }
  .meter-fill.danger { background: var(--mc-danger); }

  .callout { border-left: 3px solid var(--mc-accent); background: var(--mc-surface-elevated); border-radius: 4px; padding: var(--space-3); font-size: var(--text-small); display: flex; gap: var(--space-2); align-items: flex-start; }
  .callout .glyph { color: var(--mc-accent); }

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
  <button class="tab" data-tab="commands">Command Deck</button>
</nav>
<main>
  <section id="overview" class="page active">
    <div id="warnings"></div>
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
      <h2>Queue Timeline</h2>
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
  </section>
  <section id="models" class="page"><div id="modelGrid"></div></section>
  <section id="quality" class="page"><div id="qualityGrid"></div></section>
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
function renderQuality() {
  const q = state.quality || {};
  const gates = [
    { name: 'schema_non_empty_summary', pass: Boolean(q.schema_non_empty_summary), reason: 'Empty-summary reports are not accepted.' },
    { name: 'local_only_never_claude', pass: Boolean(q.local_only_never_claude), reason: 'local_only lane must never reach the Claude provider.' },
    { name: 'empty_reports_fail', pass: Boolean(q.empty_reports_fail), reason: 'Reports with no content must fail, not silently pass.' },
    { name: 'stale_watchers == 0', pass: !q.stale_watchers, reason: (q.stale_watchers || 0) + ' stale watcher(s) detected.' },
    { name: 'fallback_alarm == false', pass: !q.fallback_alarm, reason: 'Fallback alarm is active.' }
  ];
  const rows = gates.map(g => '<div class="gate-row ' + (g.pass ? 'pass' : 'fail') + '"><span class="glyph">' + (g.pass ? '&#10003;' : '&#10007;') + '</span><span class="g-name">' + esc(g.name) + '</span>' +
    (g.pass ? '' : '<span class="g-reason">' + esc(g.reason) + '</span>') + '<span class="g-result">' + (g.pass ? 'Pass' : 'Fail') + '</span></div>').join('');
  const ratePct = Math.round((q.fallback_rate || 0) * 100);
  const meterCls = q.fallback_alarm ? 'danger' : (ratePct >= 20 ? 'warn' : '');
  const meter = '<div class="meter-card"><div class="meter-head"><span>Fallback rate</span>' + (q.fallback_alarm ? '<span class="alarm-tag">ALARM</span>' : '') + '</div><div class="meter-track"><div class="meter-fill' + (meterCls ? ' ' + meterCls : '') + '" style="width:' + Math.max(ratePct, 4) + '%">' + ratePct + '%</div></div></div>';
  const callout = q.recommendation ? '<div class="callout"><span class="glyph">&#128161;</span><span>' + esc(q.recommendation) + '</span></div>' : '';
  document.getElementById('qualityGrid').innerHTML =
    '<section class="block"><h2>Quality Gates</h2><div class="gate-list">' + rows + '</div></section>' +
    '<section class="block">' + meter + '</section>' +
    (callout ? '<section class="block">' + callout + '</section>' : '');
}
function renderAll() { renderProjects(); renderOverview(); renderQueue(); renderSquads(); renderModels(); renderQuality(); }
function save() {
  const activeAgents = Array.from(document.querySelectorAll('.toggle.on[data-agent]')).map(el => el.dataset.agent);
  vscode.postMessage({ type: 'saveTeam', project: projectEl.value, maxWorkers: workersEl.value, defaultLane: laneEl.value, activeAgents });
}
window.addEventListener('message', event => { if (event.data.type === 'state') { state = event.data.state; renderAll(); } });
document.querySelectorAll('.tab').forEach(b => b.addEventListener('click', () => { document.querySelectorAll('.tab,.page').forEach(x => x.classList.remove('active')); b.classList.add('active'); document.getElementById(b.dataset.tab).classList.add('active'); }));
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

async function openDashboard(context) {
  if (dashboardPanel) {
    dashboardPanel.reveal(vscode.ViewColumn.Active);
    return;
  }
  dashboardPanel = vscode.window.createWebviewPanel(
    "daedalusDashboard",
    "Daedalus Mission Control",
    vscode.ViewColumn.Active,
    { enableScripts: true, retainContextWhenHidden: true }
  );
  bindDashboardWebview(context, dashboardPanel.webview);
  dashboardPanel.onDidDispose(() => { dashboardPanel = undefined; });
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
