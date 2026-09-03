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
  /** Observed by the backend on this machine; omitted by older servers. */
  reachable?: boolean;
}

/** A project registration deliberately points at an existing checkout. The
 * browser never uploads or copies the repository. */
export interface ProjectRegistration {
  repo_root: string;
  name?: string;
}

export interface ProjectRegistrationPayload extends ApiEnvelope {
  project: string;
  registered_project: Pick<ProjectRow, 'name' | 'repo_root'>;
  created: boolean;
}

/** OpenVSCode is managed by the desktop runtime, not inferred from whether an
 * iframe happened to paint. Optional aliases keep the web bundle compatible
 * with an older desktop sidecar while its additive status contract rolls out. */
export interface DesktopIdeService {
  mode?: 'native' | 'docker';
  installed?: boolean;
  available?: boolean;
  reachable?: boolean;
  running?: boolean;
  endpoint?: string;
  ui_url?: string;
  executable?: string;
  image?: string;
  container_name?: string;
  configured_executable?: string;
  managed?: boolean;
  process_running?: boolean;
  runtime_downloads?: boolean;
  state?: string;
  detail?: string;
  last_error?: string;
}

export interface DesktopStatusSnapshot {
  services?: {
    ide?: DesktopIdeService;
    [service: string]: unknown;
  };
}

export interface DesktopStatusPayload extends ApiEnvelope {
  desktop?: DesktopStatusSnapshot;
  service?: DesktopIdeService;
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

/**
 * One entry in the capability REGISTRY: what a grant is, and what it costs.
 *
 * Served identically by `/api/capabilities` and inside `hierarchy` (verified
 * against both endpoints 2026-09-03). It was typed as an opaque
 * `Record<string, unknown>`, which is the same defect as an undeclared field:
 * the data is present and unreachable, so nothing rendered it and an agent's
 * grants printed as a flat list of bare names.
 *
 * `risk` is deliberately a plain string, not a union. The four classes seen
 * live are external_read, local_write, external_advisory and
 * trusted_frontier; pinning a union here would make a NEW class a type error
 * in the browser rather than an unrecognised word the surface can report.
 */
export interface CapabilityEntry {
  id: string;
  name?: string;
  description?: string;
  risk?: string;
  /** true when using this grant requires a configured secret */
  requires_secret?: boolean;
}

export interface HierarchyPayload extends ApiEnvelope {
  nodes: HierarchyNode[];
  edges: HierarchyEdge[];
  health: Record<string, unknown>;
  capabilities: CapabilityEntry[];
  policy_flags: Record<string, unknown>;
  /** The lanes `save_team` will accept, from `daedalus.core.KNOWN_LANES`.
   *  Sent by the backend rather than hardcoded here: a frontend that keeps its
   *  own copy eventually offers one the validator refuses, and the user learns
   *  that from a 400. */
  lanes?: string[];
  /** Upper bound `save_team` enforces on `max_workers`. */
  max_workers_ceiling?: number;
}

/** What `PUT /api/projects/<name>/team` answers with. `ignored_fields` names
 *  the keys the backend dropped — it drops unknown keys rather than failing,
 *  which is what keeps a patch inside the team subtree, but a dropped field
 *  and a saved one look identical from this side of the wire. */
export interface TeamPayload extends ApiEnvelope {
  team: {
    max_workers: number;
    default_lane: string;
    active_agents: string[];
    squads: Record<string, string[]>;
    model_assignments: Record<string, string>;
    semi_auto: Record<string, boolean>;
  };
  ignored_fields: string[];
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
  /*
   * Gate-specific fields, measured against `daedalus/core.py` on 2026-09-03:
   *   discrimination     receipt_path, kill_rate_floor
   *   write_confinement  write_allow, high_risk_paths
   *   operability_drill  receipt_path, controls
   * They were consumed through a local `as GovernanceGate & {...}` cast, which
   * meant this contract — the single agreement between the two sides — described
   * a payload smaller than the one being read, and `tsc` could not catch a
   * rename on either side.
   */
  receipt_path?: string;
  kill_rate_floor?: number;
  high_risk_paths?: string[];
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
  /**
   * THE SAFETY GATES, and they are probes that actually ran.
   *
   * `daedalus/core.py` builds this by executing two checks and escalates
   * either failure as SAFETY: "local_only fail-closed guard did not verify
   * -- investigate before queueing" and "empty-report schema gate did not
   * verify". Undeclared until 2026-09-03, so unreachable through the typed
   * path: the card that had it in hand rendered a raw JSON dump instead.
   *
   * Every member is optional because an older server sends none of them, and
   * a gate nobody reported is not a gate that held.
   */
  quality?: {
    local_only_never_claude?: boolean;
    schema_non_empty_summary?: boolean;
    empty_reports_fail?: boolean;
    stale_watchers?: number;
    fallback_alarm?: boolean;
    fallback_rate?: number;
    recommendation?: string;
  };
  /** Live bridge watchers, with their pids and whether each has gone stale. */
  watcher?: {
    running?: boolean;
    watchers?: Array<{ pid: number; command: string; stale: boolean }>;
    stale_count?: number;
  };
  /*
   * THE REST OF WHAT /api/dashboard SENDS.
   *
   * Declared shallowly and deliberately: naming them makes them reachable
   * and lets `tests/contracts/test_ui_contract_matches_live_payloads.py`
   * watch this endpoint at all, which it could not while eight fields were
   * undeclared. Their inner shapes stay `unknown` because nothing renders
   * them yet, and inventing a structure nobody consumes would be a contract
   * asserting more than anyone has checked.
   *
   * Measured on the live endpoint 2026-09-03.
   */
  status?: Record<string, unknown>;
  models?: Record<string, unknown>;
  squads?: Record<string, unknown>;
  categories?: Array<Record<string, unknown>>;
  claude_crew?: Record<string, unknown>;
  enforcement?: Record<string, unknown>;
  project_config?: Record<string, unknown>;
  projects?: Array<Record<string, unknown>>;
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

/** Client-visible response path; it grants no provider or action authority. */
export type IkarusDeliveryMode = 'blocking' | 'stream';

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
  /** Canonical conversation-spine row written for this exact exchange. */
  turn_id?: number;
  /** False means the answer succeeded but its conversation append did not. */
  conversation_persisted?: boolean;
  /** Which response transport produced this envelope. Additive to legacy fields. */
  delivery_mode?: IkarusDeliveryMode;
  /** True means the text may be partial and no action affordance is safe. */
  stream_interrupted?: boolean;
}

/* ---- Live event stream (SSE): GET /api/events?project=<name> ---- */

/** Initial snapshot pushed once on connect. */
export interface LiveHello {
  queue_depth: number;
  in_flight: number;
  unread_count: number;
  quarantined_count: number;
  watcher_state: string;
  reports_total: number;
  latest_report?: unknown;
}

/** A task finished. `report_brief` (interfaces/bridge/projection.py) emits
 *  all five; the cockpit used to decode three and drop the payload. */
export interface LiveReport {
  name: string;
  status: string;
  lane: string;
  project?: string;
  summary?: string;
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
  /*
   * CAPABILITY AND TRUST, sent since this endpoint shipped and undeclared
   * until 2026-09-03 -- so unreachable through the typed path, and the
   * reachability list showed none of it. Same failure shape as `asked` on
   * the health payload.
   *
   * `trusted_with_ip` is "approved to receive proprietary/sensitive source"
   * (daedalus/runtimes/providers/contracts.py) and is ENFORCED at the egress
   * gate, not advisory. Optional here because a row that omits it has not
   * been approved, and `undefined` must not read as `true`.
   */
  local?: boolean;
  trusted_with_ip?: boolean;
  can_write?: boolean;
  agentic?: boolean;
  /** the executable this runtime shells out to, when it is a CLI */
  command?: string;
  /** the environment variable holding its key, when it is an API */
  env_key?: string;
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
