import type { HierarchyNode, HierarchyPayload } from '@/shared/contracts';

/**
 * The team editor's pure half: read a draft out of the hierarchy payload, and
 * work out the minimal patch to send back.
 *
 * Kept out of the component so it can be tested without rendering. The patch
 * being MINIMAL is the part that matters: `save_team` merges what it receives,
 * so sending a whole team object would rewrite `squads`, `model_assignments`
 * and `semi_auto` — fields this form never showed the user — with whatever the
 * page happened to be holding.
 */

export interface TeamDraft {
  maxWorkers: number;
  lane: string;
  agents: string[];
}

export interface AgentRow {
  name: string;
  label: string;
}

export const FALLBACK_CEILING = 64;
export const FALLBACK_LANE = 'local_only';

function str(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
}

function agentName(node: HierarchyNode): string {
  return str(node.data.name) || node.id.replace(/^agent:/, '');
}

export function draftFromPayload(payload: HierarchyPayload): TeamDraft {
  const nodes = payload.nodes || [];
  const project = nodes.find((node) => node.type === 'project');
  return {
    maxWorkers:
      typeof project?.data.max_workers === 'number' ? project.data.max_workers : 3,
    lane: str(project?.data.default_lane, FALLBACK_LANE),
    agents: nodes
      .filter((node) => node.type === 'agent' && node.data.active === true)
      .map(agentName)
      .filter(Boolean)
  };
}

export function agentRowsFromPayload(payload: HierarchyPayload): AgentRow[] {
  return (payload.nodes || [])
    .filter((node) => node.type === 'agent')
    .map((node) => ({ name: agentName(node), label: node.label || agentName(node) }))
    .filter((row) => row.name)
    .sort((a, b) => a.label.localeCompare(b.label, 'de'));
}

/** The lanes the BACKEND named. Falling back to the current one is deliberate:
 *  offering a guessed list would mean offering a choice save_team refuses. */
export function lanesFromPayload(payload: HierarchyPayload, current: string): string[] {
  return payload.lanes && payload.lanes.length ? payload.lanes : [current];
}

export function ceilingFromPayload(payload: HierarchyPayload): number {
  return payload.max_workers_ceiling || FALLBACK_CEILING;
}

export function sameAgentSet(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  const left = [...a].sort();
  const right = [...b].sort();
  return left.every((value, index) => value === right[index]);
}

export function teamChanged(draft: TeamDraft, baseline: TeamDraft): boolean {
  return (
    draft.maxWorkers !== baseline.maxWorkers ||
    draft.lane !== baseline.lane ||
    !sameAgentSet(draft.agents, baseline.agents)
  );
}

/** Only what actually moved. An empty object means nothing to send. */
export function teamPatch(draft: TeamDraft, baseline: TeamDraft): Record<string, unknown> {
  const patch: Record<string, unknown> = {};
  if (draft.maxWorkers !== baseline.maxWorkers) patch.max_workers = draft.maxWorkers;
  if (draft.lane !== baseline.lane) patch.default_lane = draft.lane;
  if (!sameAgentSet(draft.agents, baseline.agents)) patch.active_agents = draft.agents;
  return patch;
}
