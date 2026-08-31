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

async function capture<T>(work: () => Promise<T>, now: () => number): Promise<CapabilityResult<T>> {
  try {
    return { status: 'ready', data: await work(), loadedAt: now() };
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
    capture(() => ports.getProviderStatus(), now),
    capture(() => ports.getHierarchy(project), now),
    capture(() => ports.getLoopQueue(project, 10), now),
    capture(() => ports.getLoopAttempts(20), now),
    capture(() => ports.getLoopArchitecture(project), now)
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
