import type { HierarchyPayload } from '@/shared/contracts';
import {
  agentRowsFromPayload,
  ceilingFromPayload,
  draftFromPayload,
  lanesFromPayload,
  teamChanged,
  teamPatch,
  FALLBACK_CEILING,
  type TeamDraft
} from './teamModel';

export interface TeamSpecResult {
  name: string;
  ok: boolean;
  detail: string;
}

function payload(extra: Record<string, unknown> = {}): HierarchyPayload {
  return {
    ok: true,
    generated_at: '',
    project: 'atlas',
    warnings: [],
    nodes: [
      {
        id: 'project:atlas',
        type: 'project',
        label: 'atlas',
        data: { max_workers: 7, default_lane: 'claude' }
      },
      { id: 'agent:talos', type: 'agent', label: 'Talos', data: { name: 'talos', active: true } },
      { id: 'agent:minos', type: 'agent', label: 'Minos', data: { name: 'minos', active: false } },
      { id: 'agent:clio', type: 'agent', label: 'Clio', data: { name: 'clio', active: true } }
    ],
    edges: [],
    health: {},
    capabilities: [],
    policy_flags: {},
    ...extra
  } as unknown as HierarchyPayload;
}

const BASE: TeamDraft = { maxWorkers: 7, lane: 'claude', agents: ['talos', 'clio'] };

export function runTeamSettingsSpec(): TeamSpecResult[] {
  const results: TeamSpecResult[] = [];
  const check = (name: string, ok: boolean, detail = '') => results.push({ name, ok, detail });

  const draft = draftFromPayload(payload());
  check(
    'the draft is read from the hierarchy the backend actually sends',
    draft.maxWorkers === 7 && draft.lane === 'claude' && draft.agents.join(',') === 'talos,clio',
    JSON.stringify(draft)
  );

  const rows = agentRowsFromPayload(payload());
  check(
    'every registered agent is offered, active or not, sorted by label',
    rows.map((r) => r.name).join(',') === 'clio,minos,talos',
    rows.map((r) => r.name).join(',')
  );

  // The whole point of sourcing lanes from the payload: a hardcoded list
  // eventually offers one save_team refuses.
  check(
    'the lane choices are the ones the backend named',
    lanesFromPayload(payload({ lanes: ['auto', 'local_only', 'claude'] }), 'claude').join(',') ===
      'auto,local_only,claude'
  );
  check(
    'a backend that names no lanes yields only the current one, never a guess',
    lanesFromPayload(payload(), 'claude').join(',') === 'claude'
  );
  check(
    'the worker ceiling comes from the backend, with a fallback',
    ceilingFromPayload(payload({ max_workers_ceiling: 12 })) === 12 &&
      ceilingFromPayload(payload()) === FALLBACK_CEILING
  );

  check('an untouched draft is not dirty', !teamChanged({ ...BASE }, BASE));
  check(
    'reordering the agent list is not a change',
    !teamChanged({ ...BASE, agents: ['clio', 'talos'] }, BASE)
  );
  check('dropping an agent is a change', teamChanged({ ...BASE, agents: ['talos'] }, BASE));

  // save_team MERGES what it receives. A full-object PUT would rewrite
  // squads / model_assignments / semi_auto, which this form never showed.
  check(
    'an untouched draft sends nothing at all',
    Object.keys(teamPatch({ ...BASE }, BASE)).length === 0
  );
  const onlyWorkers = teamPatch({ ...BASE, maxWorkers: 9 }, BASE);
  check(
    'changing one field sends exactly that field',
    Object.keys(onlyWorkers).join(',') === 'max_workers' && onlyWorkers.max_workers === 9,
    JSON.stringify(onlyWorkers)
  );
  const everything = teamPatch({ maxWorkers: 1, lane: 'local_only', agents: ['minos'] }, BASE);
  check(
    'changing everything sends the three fields and no others',
    Object.keys(everything).sort().join(',') === 'active_agents,default_lane,max_workers',
    JSON.stringify(everything)
  );

  return results;
}
