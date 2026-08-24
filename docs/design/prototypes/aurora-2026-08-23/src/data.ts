/* The fixture contract and the derivations the room needs.
   Nothing here invents a fact: every derived string is built from a value the
   fixture carries, or says plainly that the fixture does not carry it.
   (Logic lifted from spike4/atelier; the surface it fed is gone.) */

export type Plane = 'code' | 'type' | 'data' | 'knowledge';
export type Lens = 'structure' | 'evidence' | 'cost';
export type ViewMode = 'spatial' | 'ordered';
export type Depth = 1 | 2 | 0; // 0 = all

export interface GNode { id: string; plane: Plane; label: string; kind: string; parent?: string }
export interface GEdge { s: string; t: string; rel: string; cross: boolean; verified: boolean; score?: number }

export type Prov = 'M' | 'I' | 'A';

export interface Citation { label: string; node: string | null; kind: string }

export interface ChatMsg {
  role: 'owner' | 'ikarus' | 'system' | 'decision';
  text: string;
  provenance?: Prov;
  evidence?: string[];
  withheld?: number;
  decided?: 'approved' | 'rejected';
}

export interface Stage { name: string; state: 'done' | 'live' | 'waiting'; note: string }

export interface Fixture {
  project: string;
  revision: string;
  gate: string;
  rim: {
    budget: { spent_tokens: number; cap_tokens: number; spent_usd: number; cap_usd: number };
    attempts: { live: number; queued: number; done: number; rejected: number };
    evidence: { packets: number; receipts_signed: number; receipts_total: number };
    withheld: { count: number; reason: string };
    kill_switch: string;
  };
  graph: { planes: Plane[]; nodes: GNode[]; edges: GEdge[] };
  chat: ChatMsg[];
  knowledge_page: { title: string; plane: string; kind: string; body: string; provenance: string; backlinks: string[]; open_question: string };
  lenses: Lens[];
  projects: { id: string; name: string; active: boolean; watcher: string; modules: number; islands: number; dark: number }[];
  mission: { title: string; id: string; stages: Stage[] };
  slice: { state: string; refreshed: string; tokens_in_slice: number; tokens_full: number; withheld_paths: number };
  lanes: { runtime: string; read: boolean; propose: boolean; write: string; locked: boolean; reason?: string; host?: string }[];
  settings: {
    route: string; local_may_leave_machine: boolean; spending_ceiling_usd: number; autonomy: string; statements: string[];
    memory: { remember_across_sessions: boolean; do_not_remember_this_project: boolean; retention: string };
    appearance: { theme: string; accent: string; motion: string; text_size: string; density: string };
  };
  library: {
    global: { title: string; path: string }[];
    project_wiki: { title: string; path: string; backlinks: number }[];
    module_pages: { module: string; auto: { fan_in: number; fan_out: number; churn_30d: number; complexity: string }; notes: string }[];
  };
  council: { vendor: string; text: string }[];
  palette: { verb: string; hint: string }[];
  status: { lane: string; resolved_host: string; spend_today_usd: number; tokens_today: number };
}

export async function loadFixture(): Promise<Fixture> {
  const res = await fetch('./fixture.json');
  if (!res.ok) throw new Error('fixture unreachable');
  return res.json();
}

export function fmt(n: number): string { return n.toLocaleString('en-US'); }

/* ------------------------------------------------------------- provenance */

export const PROV_MEANING: Record<Prov, string> = {
  M: 'Measured — read from a receipt or the event log.',
  I: 'Inferred — derived from measured data, not itself measured.',
  A: 'Assumed — neither measured nor derived. Treat with care.',
};

export const PLANE_LABEL: Record<Plane, string> = {
  code: 'Code', type: 'Type', data: 'Data', knowledge: 'Knowledge',
};

/* -------------------------------------------------------------- citations */

/** A citation is a FILE NAME or a symbol — never an ordinary word. "Attempt"
 *  inside "17 Attempts" is not a citation, and neither is a noun that happens
 *  to match a schema title: underlining those makes a sentence unreadable and
 *  teaches the reader that an underline means nothing. */
export const isIdentifier = (s: string) => /[/]/.test(s) || /\.[a-z]{2,4}$/.test(s) || /\(\)$/.test(s);

/** matched only at a word boundary, so a plural never swallows a link */
export function mentions(text: string, label: string): number {
  let at = -1;
  for (;;) {
    at = text.indexOf(label, at + 1);
    if (at < 0) return -1;
    const before = at === 0 ? ' ' : text[at - 1];
    const after = text[at + label.length] ?? ' ';
    if (!/[A-Za-z0-9_]/.test(before) && !/[A-Za-z0-9_]/.test(after)) return at;
  }
}

const citable = (fx: Fixture, text: string) =>
  fx.graph.nodes.filter(n => isIdentifier(n.label) && mentions(text, n.label) >= 0);

const LOCATOR_ALIASES: [RegExp, string][] = [
  [/events\.jsonl/i, 'runs/events.jsonl'],
  [/ledger\.json/i, 'runs/budget/ledger.json'],
  [/receipt/i, 'runs/receipts/'],
  [/module_pages|library\./i, 'daedalus/policy/enforce.py'],
  [/^slice$/i, 'runs/events.jsonl'],
  [/rim\.withheld/i, '.agentenv/tool-allowances.json'],
];

function nodeByLabel(fx: Fixture, label: string): GNode | null {
  return fx.graph.nodes.find(n => n.label === label) ?? null;
}

export function citationsFor(fx: Fixture, m: ChatMsg): Citation[] {
  const out: Citation[] = [];
  const seen = new Set<string>();
  const push = (label: string, node: GNode | null, kind: string) => {
    if (seen.has(label)) return;
    seen.add(label);
    out.push({ label, node: node?.id ?? null, kind });
  };
  const hits = citable(fx, m.text).sort((a, b) => mentions(m.text, a.label) - mentions(m.text, b.label));
  for (const n of hits) push(n.label, n, n.kind);
  for (const raw of m.evidence ?? []) {
    const alias = LOCATOR_ALIASES.find(([re]) => re.test(raw));
    const node = alias ? nodeByLabel(fx, alias[1]) : null;
    push(raw, node, node ? node.kind : 'locator');
  }
  return out;
}

/** The claim cut into runs of plain text and the identifiers it names, so a
 *  citation sits beside the words it supports rather than in a row underneath. */
export type ClaimPart = { text: string } | { cite: Citation };

export function claimParts(fx: Fixture, m: ChatMsg): ClaimPart[] {
  const hits = citable(fx, m.text)
    .map(n => ({ n, at: mentions(m.text, n.label) }))
    .sort((a, b) => a.at - b.at || b.n.label.length - a.n.label.length);
  const out: ClaimPart[] = [];
  let cursor = 0;
  for (const { n } of hits) {
    const at = m.text.indexOf(n.label, cursor);
    if (at < 0) continue;
    if (at > cursor) out.push({ text: m.text.slice(cursor, at) });
    out.push({ cite: { label: n.label, node: n.id, kind: n.kind } });
    cursor = at + n.label.length;
  }
  if (cursor < m.text.length) out.push({ text: m.text.slice(cursor) });
  return out;
}

/** Evidence locators that name no node of their own: they ride at the end of
 *  the claim they belong to, never in a row below it. */
export function trailingCitations(fx: Fixture, m: ChatMsg): Citation[] {
  const inline = new Set(citable(fx, m.text).map(n => n.label));
  const out: Citation[] = [];
  const seen = new Set<string>();
  for (const raw of m.evidence ?? []) {
    const alias = LOCATOR_ALIASES.find(([re]) => re.test(raw));
    const node = alias ? nodeByLabel(fx, alias[1]) : null;
    if (node && inline.has(node.label)) continue;
    if (seen.has(raw)) continue;
    seen.add(raw);
    out.push({ label: raw, node: node?.id ?? null, kind: node ? node.kind : 'locator' });
  }
  return out;
}

/** The nodes the conversation on screen is actually about — newest claim
 *  first. They are the only nodes allowed to be emissive at rest. */
export function conversationNodes(fx: Fixture, chat: ChatMsg[]): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (let i = chat.length - 1; i >= 0; i--) {
    for (const c of citationsFor(fx, chat[i])) {
      if (!c.node || seen.has(c.node)) continue;
      seen.add(c.node);
      out.push(c.node);
    }
    if (out.length >= 2) break;
  }
  return out.slice(0, 2);
}

/* --------------------------------------------------------------- withheld */

export const WITHHELD_RULE_LABEL = '.agentenv/tool-allowances.json';

/** What was withheld is named by kind in the turn itself; what is missing is
 *  the PLACE, so the rule file rides at the end of the claim as a locator. */
export function withheldTitle(fx: Fixture, n: number): string {
  return `${n} ${n === 1 ? 'path' : 'paths'} withheld — kind: ${fx.rim.withheld.reason}. `
    + 'The index records their kind and their count, not their paths. This file is the rule that withheld them.';
}

/* ------------------------------------------------------------------ graph */

/** Containment is written twice in the fixture — as `parent` and as `defines`
 *  edges. The missing half is derived rather than left invisible. */
export function allEdges(fx: Fixture): GEdge[] {
  const seen = new Set(fx.graph.edges.map(e => e.s + '>' + e.t));
  const extra: GEdge[] = [];
  for (const n of fx.graph.nodes) {
    if (n.parent && !seen.has(n.parent + '>' + n.id) && !seen.has(n.id + '>' + n.parent)) {
      extra.push({ s: n.parent, t: n.id, rel: 'defines', cross: false, verified: true });
    }
  }
  return [...fx.graph.edges, ...extra];
}

/** Relations touching a node. This is what sizes it, and the interface says so
 *  in those words — the fixture's own in-degree spans 0..2 and has no rhythm. */
export function degrees(edges: GEdge[]): Record<string, number> {
  const d: Record<string, number> = {};
  for (const e of edges) { d[e.s] = (d[e.s] ?? 0) + 1; d[e.t] = (d[e.t] ?? 0) + 1; }
  return d;
}

export function inDegrees(edges: GEdge[]): Record<string, number> {
  const d: Record<string, number> = {};
  for (const e of edges) d[e.t] = (d[e.t] ?? 0) + 1;
  return d;
}

/** The backbone: verified, non-cross relations. That is the structural spine —
 *  everything else arrives on hover, on selection or with a lens. */
export function backbone(edges: GEdge[]): number[] {
  const out: number[] = [];
  edges.forEach((e, i) => { if (e.verified && !e.cross) out.push(i); });
  return out;
}

export function neighbourhood(edges: GEdge[], root: string, depth: number): Set<string> {
  const seen = new Set([root]);
  if (depth === 0) { for (const e of edges) { seen.add(e.s); seen.add(e.t); } return seen; }
  let frontier = [root];
  for (let d = 0; d < depth; d++) {
    const next: string[] = [];
    for (const e of edges) {
      if (frontier.includes(e.s) && !seen.has(e.t)) { seen.add(e.t); next.push(e.t); }
      if (frontier.includes(e.t) && !seen.has(e.s)) { seen.add(e.s); next.push(e.s); }
    }
    frontier = next;
  }
  return seen;
}

/** The live attempt's path through the index: compile → run → charge → ledger.
 *  Every hop is an edge the fixture actually carries. */
export const LIVE_PATH = ['c2', 'c3', 'c9', 'd2'];

export function measuredCost(fx: Fixture): Record<string, { fan_in: number; fan_out: number; churn_30d: number; complexity: string }> {
  const byLabel: Record<string, string> = {};
  for (const n of fx.graph.nodes) byLabel[n.label] = n.id;
  const out: Record<string, { fan_in: number; fan_out: number; churn_30d: number; complexity: string }> = {};
  for (const m of fx.library.module_pages) { const id = byLabel[m.module]; if (id) out[id] = m.auto; }
  return out;
}

export function wikiPathFor(fx: Fixture, node: GNode): string | null {
  const wiki = fx.library.project_wiki.find(p => p.title === node.label);
  if (wiki) return wiki.path;
  const mod = fx.library.module_pages.find(m => m.module === node.label);
  if (mod) return 'module:' + mod.module;
  return null;
}

/* --------------------------------------------------------------- projects */

export interface ProjectView {
  id: string; name: string; watcher: string;
  modules: number; islands: number; dark: number; indexed: boolean;
}

export function projectViews(fx: Fixture): ProjectView[] {
  return fx.projects.map(p => ({
    id: p.id, name: p.name, watcher: p.watcher,
    modules: p.modules, islands: p.islands, dark: p.dark,
    indexed: p.id === fx.project,
  }));
}

/** The lane/host corner line, scoped to the project on screen. An unindexed
 *  project is never given the indexed project's lane, host or spend. */
export function laneLine(fx: Fixture, p: ProjectView, localMayLeave: boolean): string {
  if (!p.indexed) return `${p.name} — no lane running, watcher ${p.watcher}, no index compiled`;
  const host = localMayLeave
    ? `${fx.status.resolved_host}, local traffic may leave this machine`
    : fx.status.resolved_host;
  return `${p.name} · ${fx.status.lane} lane · ${host}`;
}

export function spendLine(fx: Fixture, p: ProjectView): string {
  if (!p.indexed) return 'Nothing spent on this project today';
  return `$${fx.status.spend_today_usd.toFixed(2)} and ${fmt(fx.status.tokens_today)} tokens today`;
}

export function sliceLine(fx: Fixture, p: ProjectView): string {
  if (!p.indexed) return 'No slice — this project has no compiled index';
  return `Slice ${fx.slice.state} · ${fmt(fx.slice.tokens_in_slice)} of ${fmt(fx.slice.tokens_full)} tokens · ${fx.slice.withheld_paths} ${fx.rim.withheld.reason} withheld`;
}

/* -------------------------------------------------------------- url state */

export interface UrlState {
  overlay: 'palette' | 'library' | 'settings' | null;
  state: 'selected' | 'ordered' | 'decision' | null;
}

export function urlState(): UrlState {
  const q = new URLSearchParams(window.location.search);
  const o = q.get('open');
  const st = q.get('state');
  return {
    overlay: o === 'palette' || o === 'library' || o === 'settings' ? o : null,
    state: st === 'selected' || st === 'ordered' || st === 'decision' ? st : null,
  };
}

/* ------------------------------------------------------------- the answer */

/* Ikarus answers out of the index or it says plainly that it cannot. There is
   no third case: every sentence below is assembled from a value the fixture
   carries, and the one sentence that is not carries no provenance mark because
   no model produced it. */

export const SERVICE_NOTICE =
  'No model is connected in this prototype, so nothing reached a service and nothing was guessed at. '
  + 'What I can answer is what the compiled index holds: name a module, a schema, a store or a page, or ask about spend, attempts or what was withheld.';

export function answerFor(fx: Fixture, edges: GEdge[], q: string): ChatMsg {
  const t = q.toLowerCase();
  const byLabel = fx.graph.nodes.find(n => t.includes(n.label.toLowerCase()));
  const byTail = fx.graph.nodes.find(n => {
    const tail = n.label.split('/').pop()!.replace(/\(\)$/, '');
    return tail.length > 5 && t.includes(tail.toLowerCase());
  });
  const hit = byLabel ?? byTail;
  if (hit) {
    const mine = edges.filter(e => e.s === hit.id || e.t === hit.id);
    const ver = mine.filter(e => e.verified).length;
    const c = measuredCost(fx)[hit.id];
    return {
      role: 'ikarus',
      text: `${hit.label} is a ${hit.kind} on the ${PLANE_LABEL[hit.plane].toLowerCase()} plane. `
        + `The index records ${mine.length} relations at it, ${ver} of them verified`
        + (c
          ? `. Fan-in ${c.fan_in}, fan-out ${c.fan_out}, ${c.churn_30d} changes in 30 days, complexity ${c.complexity}.`
          : `. It carries no measured cost in the index, so I am not ranking it.`),
      provenance: 'M',
      evidence: c ? ['library.module_pages'] : [],
    };
  }
  if (/kost|spend|token|budget|teuer|cost|geld|ausgegeben/.test(t)) {
    return {
      role: 'ikarus',
      text: `$${fx.status.spend_today_usd.toFixed(2)} and ${fmt(fx.status.tokens_today)} tokens have been spent today, `
        + `against a ceiling of $${fx.settings.spending_ceiling_usd.toFixed(2)} and ${fmt(fx.rim.budget.cap_tokens)} tokens. `
        + `The kill switch is ${fx.rim.kill_switch}.`,
      provenance: 'M', evidence: ['ledger.json'],
    };
  }
  if (/withheld|zurückgehalten|zurueckgehalten|secret|geheim/.test(t)) {
    return {
      role: 'ikarus',
      text: `${fx.rim.withheld.count} paths were withheld from the slice — kind: ${fx.rim.withheld.reason}. `
        + `The index records their kind and their count, not their paths.`,
      provenance: 'M', withheld: fx.rim.withheld.count, evidence: ['rim.withheld'],
    };
  }
  if (/attempt|versuch|lauf|run/.test(t)) {
    const a = fx.rim.attempts;
    return {
      role: 'ikarus',
      text: `${a.live} attempts are live, ${a.queued} queued, ${a.done} done and ${a.rejected} rejected. `
        + `The one running now is ${fx.mission.stages.find(s => s.state === 'live')?.note ?? 'unnamed'}.`,
      provenance: 'M', evidence: ['events.jsonl'],
    };
  }
  if (/gate|promotion|merge|approve/.test(t)) {
    return {
      role: 'ikarus',
      text: `${fx.gate}. ${fx.rim.evidence.packets} evidence packets are sealed and `
        + `${fx.rim.evidence.receipts_signed} of ${fx.rim.evidence.receipts_total} receipts are signed. `
        + `Nothing is promoted without your approval.`,
      provenance: 'M', evidence: ['receipt'],
    };
  }
  return { role: 'system', text: SERVICE_NOTICE };
}
