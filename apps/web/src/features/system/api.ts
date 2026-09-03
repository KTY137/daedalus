import {
  ApiError,
  getClaudeBootstrap,
  getControlPlane,
  getDashboard,
  getHierarchy,
  getLoopArchitecture,
  getLoopAttempts,
  getLoopQueue,
  getProviderStatus,
  updateAutonomy
} from '@/shared/api';
import type { ControlPlanePayload } from '@/shared/contracts';
import type {
  CapabilityFailure,
  CapabilityResult,
  SystemCapabilitiesSnapshot
} from './contracts';

/** Injection keeps this feature a consumer of the existing API authority. */
export interface SystemCapabilityPorts {
  getDashboard: typeof getDashboard;
  getControlPlane: typeof getControlPlane;
  getClaudeBootstrap: typeof getClaudeBootstrap;
  getProviderStatus: typeof getProviderStatus;
  getHierarchy: typeof getHierarchy;
  getLoopQueue: typeof getLoopQueue;
  getLoopAttempts: typeof getLoopAttempts;
  getLoopArchitecture: typeof getLoopArchitecture;
  updateAutonomy: typeof updateAutonomy;
}

export const systemCapabilityPorts: SystemCapabilityPorts = {
  getDashboard,
  getControlPlane,
  getClaudeBootstrap,
  getProviderStatus,
  getHierarchy,
  getLoopQueue,
  getLoopAttempts,
  getLoopArchitecture,
  updateAutonomy
};

export function capabilityFailure(error: unknown): CapabilityFailure {
  if (error instanceof ApiError) return { kind: error.kind, message: error.message };
  return {
    kind: 'http',
    message: error instanceof Error ? error.message : String(error)
  };
}

async function capture<T>(
  work: () => Promise<T>,
  now: () => number,
  /**
   * The key this projection PROMISES to carry.
   *
   * `status: 'ready'` used to mean only "the HTTP call did not throw", and the
   * cards dereference a second level straight off it — `data.queue
   * .n_candidates`, `data.architecture.digest`. A 200 whose body lacks the key
   * therefore threw a TypeError during render, which unmounted the ENTIRE
   * settings drawer: every other capability with it, including the ones that
   * had answered perfectly, plus any unrelated section rendered alongside.
   * [MEASURED 2026-09-03] a loop-queue body without `queue` left the drawer
   * with zero team sections and a bare page error.
   *
   * A failed read is evidence in its own right, says the contract above. So is
   * a malformed one, and it is reported the same way instead of thrown.
   */
  promises?: keyof T & string
): Promise<CapabilityResult<T>> {
  try {
    const data = await work();
    if (promises && (data as Record<string, unknown> | null)?.[promises] === undefined) {
      return {
        status: 'error',
        error: { kind: 'contract', message: `the response carries no "${promises}"` },
        loadedAt: now()
      };
    }
    return { status: 'ready', data, loadedAt: now() };
  } catch (error) {
    return { status: 'error', error: capabilityFailure(error), loadedAt: now() };
  }
}

/**
 * Read every former Classic-only projection independently. `Promise.all`
 * joins already-captured outcomes, so one refused endpoint cannot erase the
 * other seven results.
 */
export async function loadSystemCapabilities(
  project: string,
  ports: SystemCapabilityPorts = systemCapabilityPorts,
  now: () => number = Date.now
): Promise<SystemCapabilitiesSnapshot> {
  const [
    dashboard,
    controlPlane,
    claudeBootstrap,
    providerStatus,
    hierarchy,
    loopQueue,
    loopAttempts,
    loopArchitecture
  ] = await Promise.all([
    capture(() => ports.getDashboard(project), now),
    capture(() => ports.getControlPlane(project), now),
    capture(() => ports.getClaudeBootstrap(project), now),
    capture(() => ports.getProviderStatus(), now, 'providers'),
    capture(() => ports.getHierarchy(project), now, 'nodes'),
    capture(() => ports.getLoopQueue(project, 10), now, 'queue'),
    capture(() => ports.getLoopAttempts(20), now, 'attempts'),
    capture(() => ports.getLoopArchitecture(project), now, 'architecture')
  ]);

  return {
    project,
    dashboard,
    controlPlane,
    claudeBootstrap,
    providerStatus,
    hierarchy,
    loopQueue,
    loopAttempts,
    loopArchitecture
  };
}

export function agentAutonomyPatch(
  controlPlane: ControlPlanePayload,
  profileName: string,
  mode: string
): { agents: Record<string, string> } {
  return {
    agents: {
      ...((controlPlane.autonomy.agents as Record<string, string> | undefined) || {}),
      [profileName]: mode
    }
  };
}

export function updateAgentAutonomy(
  project: string,
  controlPlane: ControlPlanePayload,
  profileName: string,
  mode: string,
  ports: Pick<SystemCapabilityPorts, 'updateAutonomy'> = systemCapabilityPorts
): Promise<ControlPlanePayload> {
  return ports.updateAutonomy(project, agentAutonomyPatch(controlPlane, profileName, mode));
}
