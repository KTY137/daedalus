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

export interface DashboardPayload extends ApiEnvelope {
  selected_project?: string;
  warnings: string[];
  queue?: Record<string, unknown>;
  provider_health?: { providers?: Array<Record<string, unknown>> };
  metrics?: Record<string, unknown>;
  routing?: Record<string, unknown>;
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
