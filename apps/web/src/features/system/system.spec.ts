import { ApiError } from '@/shared/api';
import type { ControlPlanePayload } from '@/shared/contracts';
import {
  agentAutonomyPatch,
  loadSystemCapabilities,
  updateAgentAutonomy,
  type SystemCapabilityPorts
} from './api';

export interface SystemSpecResult {
  name: string;
  ok: boolean;
  detail: string;
}

function envelope(extra: Record<string, unknown> = {}) {
  return { ok: true, generated_at: '', project: 'atlas', warnings: [], ...extra } as any;
}

function control(agents: Record<string, string> = { alpha: 'manual' }): ControlPlanePayload {
  return envelope({
    profiles: [],
    claude: {},
    codex: {},
    autonomy: { agents },
    capability_gates: [],
    runtimes: []
  });
}

export async function runSystemCapabilitiesSpec(): Promise<SystemSpecResult[]> {
  const results: SystemSpecResult[] = [];
  const check = (name: string, ok: boolean, detail = '') => results.push({ name, ok, detail });
  const calls: string[] = [];
  const plane = control();
  const ports = {
    getDashboard: async (project: string) => { calls.push(`dashboard:${project}`); return envelope(); },
    getControlPlane: async (project: string) => { calls.push(`control:${project}`); return plane; },
    getClaudeBootstrap: async (project: string) => { calls.push(`bootstrap:${project}`); return envelope({ prompt: 'bounded prompt' }); },
    getProviderStatus: async () => {
      calls.push('providers');
      throw new ApiError('network', 'provider probe did not answer', '/api/providers/status');
    },
    getHierarchy: async (project: string) => { calls.push(`hierarchy:${project}`); return envelope({ nodes: [], edges: [], health: {}, capabilities: [], policy_flags: {} }); },
    getLoopQueue: async (project?: string, limit = 10) => { calls.push(`queue:${project}:${limit}`); return envelope({ queue: { candidates: [], n_candidates: 0, limit, sources: {}, notes: [], degraded_sources: [], incomplete: false, opt_in_sources_available: false } }); },
    getLoopAttempts: async (limit = 20) => { calls.push(`attempts:${limit}`); return envelope({ attempts: { intents: [], limit, kind: '', task_id: null, ledger: { path: '', exists: false, read_only: true, error: null, note: null }, degraded_sources: [], incomplete: false, attempt_intent_kind: '' } }); },
    getLoopArchitecture: async (project?: string) => { calls.push(`architecture:${project}`); return envelope({ architecture: { path: '', read: true, schema: 1, digest: 'a'.repeat(64), note: '', counts: {}, measured_lengths: {}, count_disagreements: {}, trusted: true, trust_reason: 'fixture', trust: {}, degraded_sources: [], incomplete: false } }); },
    updateAutonomy: async () => plane
  } as SystemCapabilityPorts;

  let tick = 100;
  const snapshot = await loadSystemCapabilities('atlas', ports, () => ++tick);
  check(
    'all former Classic-only read contracts are called with the selected project and stable bounds',
    calls.join('|') === 'dashboard:atlas|control:atlas|bootstrap:atlas|providers|hierarchy:atlas|queue:atlas:10|attempts:20|architecture:atlas',
    calls.join('|')
  );
  check('a failed provider sample remains an explicit network failure', snapshot.providerStatus.status === 'error' && snapshot.providerStatus.error.kind === 'network');
  check('one failed source does not erase the successful control plane', snapshot.controlPlane.status === 'ready' && snapshot.controlPlane.data === plane);
  check('one failed source does not erase loop evidence', snapshot.loopArchitecture.status === 'ready' && snapshot.loopArchitecture.data.architecture.trusted);

  const patch = agentAutonomyPatch(control({ alpha: 'manual', beta: 'semi_auto' }), 'alpha', 'autonomous');
  check('agent autonomy patches preserve sibling policy entries', patch.agents.beta === 'semi_auto' && patch.agents.alpha === 'autonomous', JSON.stringify(patch));

  let updateProject = '';
  let updatePatch: Record<string, unknown> | undefined;
  const updated = control({ alpha: 'autonomous' });
  const result = await updateAgentAutonomy('atlas', plane, 'alpha', 'autonomous', {
    updateAutonomy: async (project, value) => {
      updateProject = project;
      updatePatch = value;
      return updated;
    }
  });
  check('autonomy still uses the existing project-scoped PUT port', updateProject === 'atlas' && (updatePatch?.agents as Record<string, string>).alpha === 'autonomous');
  check('the canonical PUT response replaces the local projection', result === updated);

  return results;
}
