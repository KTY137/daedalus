// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-License-Identifier: Apache-2.0

export type NodeKind = 'project' | 'squad' | 'category' | 'agent' | 'model' | 'capability' | 'path';

export interface ApiEnvelope<T = Record<string, unknown>> {
  ok: boolean;
  generated_at: string;
  project: string | null;
  warnings: string[];
  error?: string;
  [key: string]: unknown;
}

export interface ProjectRow {
  name: string;
  repo_root: string;
  team: Record<string, unknown>;
}

export interface HierarchyNode {
  id: string;
  type: NodeKind;
  label: string;
  data: Record<string, unknown>;
}

export interface HierarchyEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  data: Record<string, unknown>;
}

export interface HierarchyPayload extends ApiEnvelope {
  nodes: HierarchyNode[];
  edges: HierarchyEdge[];
  health: Record<string, unknown>;
  capabilities: Array<Record<string, unknown>>;
  policy_flags: Record<string, unknown>;
}

/** The five health states, and there are five on purpose. Nothing may collapse
 *  them into a boolean: `unknown` must reach the user as the word "unknown". */
export type GovernanceState = 'working' | 'present' | 'degraded' | 'absent' | 'unknown';

/** Where a number came from. An unlabelled number is a rumour. */
export type Provenance = 'MEASURED' | 'INHERITED' | 'ASSUMED';

export interface GovernanceGate {
  id: string;
  question: string;
  state: GovernanceState;
  headline: string;
  provenance: Provenance;
  reason?: string;
  write_allow?: string[];
  controls?: Array<{ name: string; status: string; effect: string }>;
  detail?: Record<string, unknown> | null;
}

/** "May this system promote anything right now, and why not?"
 *  Served both standalone at /api/governance and embedded in the dashboard;
 *  tests/test_ui_governance.py pins that those two never disagree. */
export interface GovernancePayload extends ApiEnvelope {
  promotion_allowed: boolean;
  verdict: string;
  state: GovernanceState;
  head: string | null;
  repo_root?: string;
  gates: GovernanceGate[];
  blockers: Array<{ gate: string; state: GovernanceState; why: string }>;
  states_vocabulary?: string[];
}

export interface DashboardPayload extends ApiEnvelope {
  selected_project?: string;
  warnings: string[];
  queue?: Record<string, unknown>;
  provider_health?: { providers?: Array<Record<string, unknown>> };
  metrics?: Record<string, unknown>;
  routing?: Record<string, unknown>;
  governance?: GovernancePayload;
}

export interface AgentProfile {
  name: string;
  display_name: string;
  sync_status: 'unified' | 'drift' | 'daedalus_only' | 'claude_only';
  daedalus?: Record<string, unknown> | null;
  claude?: Record<string, unknown> | null;
  category: string;
  category_label: string;
  squads: string[];
  active: boolean;
  capabilities: string[];
  autonomy: Record<string, Record<string, unknown>>;
  ownership: string[];
}

export interface ControlPlanePayload extends ApiEnvelope {
  profiles: AgentProfile[];
  claude: Record<string, unknown>;
  codex: Record<string, unknown>;
  autonomy: Record<string, unknown>;
  capability_gates: Array<Record<string, unknown>>;
  runtimes: Array<Record<string, unknown>>;
}

export interface IkarusChatPayload extends ApiEnvelope {
  assistant: string;
  draft?: {
    roles: Array<Record<string, unknown>>;
    subagents: Array<Record<string, unknown>>;
    team_patch: Record<string, unknown>;
  };
  applied?: string[];
  control_plane?: ControlPlanePayload;
}

export interface IkarusAskAction {
  kind: 'queue_task';
  args: { project: string; objective: string; lane: string };
  requires_confirmation: boolean;
}

/** Reasoning effort for a freeform Ikarus chat turn. Cheap-by-default = 'low'. */
export type EffortLevel = 'low' | 'medium' | 'high';

export interface IkarusAskPayload {
  ok: boolean;
  project: string;
  intent: 'status' | 'distill' | 'enqueue' | 'design' | 'chat' | 'error';
  assistant: string;              // the reply text — always present
  provider_used: string;          // e.g. 'ollama_http' | 'claude_code_cli' | 'deterministic'
  model_used?: string;            // present when a real provider ran with a resolved model
  action?: IkarusAskAction;       // present when intent==='enqueue'
  distill?: unknown;              // present for some distill answers (stats; no slice_text)
  structure?: unknown;           // present for some distill answers
  status?: unknown;              // present for status
  draft?: unknown;               // present for design (same shape as chatIkarus draft)
  warnings?: string[];
}

/* ---- Live event stream (SSE): GET /api/events?project=<name> ---- */

/** Initial snapshot pushed once on connect. */
export interface LiveHello {
  queue_depth: number;
  in_flight: number;
  unread_count: number;
  watcher_state: string;
  latest_report?: unknown;
}

/** A task finished. */
export interface LiveReport {
  name: string;
  status: string;
  lane: string;
}

/** Watcher liveness tick. */
export interface LiveHeartbeat {
  watcher_state: string;
  in_flight: number;
}

/** Queue depth changed. */
export interface LiveQueue {
  queue_depth: number;
}

export type LiveEventName = 'hello' | 'report' | 'heartbeat' | 'queue';

export interface RuntimeRow {
  id: string;
  label: string;
  mode: string;
  available: boolean;
  auth_status: string;
  command_path: string;
  version: string;
  endpoint?: string;
  models: string[];
  selected_model: string;
  model_present: boolean;
  last_error: string;
  notes: string;
  /** When this row's probe actually ran, and how old the reading is. Present
   * because /api/runtimes/status caches the slow per-CLI probe (owner decision
   * 2026-08-27): a cached "erreichbar" must show its age so it cannot lie about
   * a CLI that broke since. Absent only from the uncached direct path. */
  measured_at?: string;
  measured_age_s?: number;
}

export interface RuntimeStatusPayload extends ApiEnvelope {
  runtimes: RuntimeRow[];
}

export interface RuntimeTestPayload extends ApiEnvelope {
  test: {
    runtime: string;
    ok: boolean;
    mode: string;
    detail: string;
  };
}

export interface BootstrapPayload extends ApiEnvelope {
  prompt: string;
}

/* ---- Structure (code-health / distillation) sheet ---- */

export interface StructureHotspot {
  module: string;
  score: number;
  loc: number;
  long_functions: number;
  guard_count: number;
  cc_max: number | null;
}

export interface StructureCloneSite {
  module: string;
  line: number;
}

export interface StructureClone {
  name: string;
  language: string;
  count: number;
  loc: number;
  sites: StructureCloneSite[];
  safety: string | null;
}

export interface StructureWindowClone {
  files: string[];
  shared_runs: number;
  safety: string | null;
}

/* ---- Dependency graph (Movement II — the living code map) ---- */

/**
 * One module in the code map. `module` is the node id and is a **rel path for
 * every language** (Python included) — the backend deliberately builds this
 * from `import_edges` rather than the Python-dotted `dependencies` map so the
 * id namespace is consistent and joinable across languages.
 */
export interface StructureGraphNode {
  module: string;
  language: string;
  loc: number;
  /** churn x complexity heat — higher = hotter (the rot signal). */
  score: number;
  churn: number;
  fan_in: number;
}

/** A module -> module import edge. Both endpoints are guaranteed to exist in `nodes`. */
export interface StructureGraphEdge {
  source: string;
  target: string;
}

export interface StructureGraph {
  nodes: StructureGraphNode[];
  edges: StructureGraphEdge[];
  /** Total modules the backend ranked, before the node cap. */
  n_nodes_total: number;
  /** Total edges found, before the edge cap. */
  n_edges_total: number;
  /**
   * Edges whose BOTH endpoints survived the node cap — the only ones that can
   * be drawn at all. Optional: an older backend does not send it.
   */
  n_edges_eligible?: number;
  /** Edges actually in `edges` after the edge cap. */
  n_edges_shown?: number;
  /**
   * Edges that exist in the repository and lead OUT of the drawn map, because
   * one endpoint did not survive the node cap. A map that hides this reads as
   * a complete picture of a codebase it has only sampled, so the cockpit says
   * the number out loud.
   */
  n_edges_offmap?: number;
  /**
   * True when `nodes`/`edges` are a bounded slice of the whole graph (the
   * backend keeps the highest-heat nodes). The UI MUST surface this — this
   * project has a hard no-silent-caps rule.
   */
  truncated: boolean;
}

/**
 * `GET /api/topology` — the spectral read of the import graph.
 *
 * This is a DIFFERENT graph from `StructureGraph`: an undirected projection of
 * the directed import edges over the whole scanned index, where the map the
 * stage draws is the heat-ranked, capped subset. The two report different node
 * counts on purpose and the cockpit labels both, because one number quietly
 * replacing the other is how a surface starts describing a codebase it never
 * looked at.
 *
 * `method` and `reason` are the honest half: when the graph is disconnected
 * there is no unique Fiedler vector, and the backend says so instead of
 * returning a partition it could not justify.
 */
export interface TopologyPayload extends ApiEnvelope {
  topology: {
    available: boolean;
    graph_type: string;
    node_count: number;
    edge_count: number;
    connected_components: number;
    method: string;
    reason: string;
    partition_a: string[];
    partition_b: string[];
    cut_edges: number;
    conductance: number;
    algebraic_connectivity: number;
  };
}

/**
 * `GET /api/context/plan?project=&q=` — what the system would READ to work on
 * an objective, before anything reads it.
 *
 * This is the distillation claim made inspectable: a ranked seed list with
 * scores, the query terms actually derived, whether the latent route was
 * consulted (and why not, when it was not), and receipt digests over the
 * objective and the seed evidence. Until 2026-08-25 it had no caller.
 */
export interface ContextPlanPayload extends ApiEnvelope {
  context_plan: {
    schema: string;
    objective: string;
    project: string;
    seeds: {
      lexical_weight: number;
      latent_weight: number;
      latent_applied: boolean;
      effective_latent_weight: number;
      /** module -> score, already fused */
      scores: Record<string, number>;
      lexical?: { projector_version?: string; query_terms?: string[] };
      latent?: { status?: string; message?: string; consulted?: boolean; answered?: boolean };
    };
    receipt: {
      receipt_sha256: string;
      objective_sha256: string;
      seed_evidence_sha256?: string;
      dss_receipt_sha256?: string;
      scope_key?: string;
    };
  };
}

export interface StructurePayload {
  ok: boolean;
  project: string;
  structure: {
    backend: { tree_sitter: boolean; lizard: boolean };
    repo_root: string;
    n_files: number;
    /**
     * Scope withholding (center / .daedalusignore). Optional so the panel
     * degrades against an older backend or a cached payload without it.
     *
     * Rendering this is not cosmetic: `n_files` is the CORE count, so a scoped
     * project shows a much smaller number, and a duplication report that
     * quietly shrank is indistinguishable from a codebase that got cleaner.
     */
    ignored?: {
      count: number;
      n_files_scanned: number;
      center: string[];
      ignore_patterns: string[];
      source: string;
      sample: string[];
      truncated: boolean;
    };
    languages: Record<string, { files: number; loc: number }>;
    totals: { unit_clusters: number; window_clusters: number; safety_fenced: number };
    hotspots: StructureHotspot[];
    clones: StructureClone[];
    window_clones: StructureWindowClone[];
    fan_in: { module: string; count: number }[];
    /**
     * Module dependency graph for the code map. Optional so the UI degrades
     * gracefully against an older backend / a cached payload without it.
     */
    graph?: StructureGraph;
  };
  warnings?: string[];
}

export interface DistillIncluded {
  file: string;
  role: string;
  mode: string;
  tokens: number;
}

export interface DistillPayload {
  ok: boolean;
  project: string;
  distill: {
    target: string;
    focus_file: string;
    focus_symbol: string | null;
    included: DistillIncluded[];
    slice_tokens: number;
    whole_repo_tokens: number;
    reduction_pct: number;
    backend: { tree_sitter: boolean; lizard: boolean };
    slice_text: string;
  };
  warnings?: string[];
}
