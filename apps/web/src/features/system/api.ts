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
  promises?: keyof T & string,
  expectedProject?: string
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
    if (
      expectedProject
      && (data as Record<string, unknown> | null)?.project !== expectedProject
    ) {
      return {
        status: 'error',
        error: {
          kind: 'contract',
          message: `the response does not confirm project "${expectedProject}"`
        },
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
    // This is also the confirming read after an ambiguous autonomy write.
    // Another project's projection must never clear this project's draft.
    capture(() => ports.getControlPlane(project), now, undefined, project),
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
  profileName: string,
  mode: string
): { agent_updates: Record<string, string> } {
  return {
    agent_updates: { [profileName]: mode }
  };
}

/**
 * The mutation answered, but its projection did not prove whether the
 * requested profile value was committed. This is deliberately distinct from
 * a definite validation refusal: callers must retain the draft and perform a
 * canonical read before releasing their per-project write lock.
 */
export class UnconfirmedAutonomyWriteError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'UnconfirmedAutonomyWriteError';
  }
}

export async function updateAgentAutonomy(
  project: string,
  profileName: string,
  mode: string,
  ports: Pick<SystemCapabilityPorts, 'updateAutonomy'> = systemCapabilityPorts
): Promise<ControlPlanePayload> {
  const updated = await ports.updateAutonomy(project, agentAutonomyPatch(profileName, mode));
  const agents = updated.autonomy?.agents;
  const updatedProfile = updated.profiles?.find((profile) => profile.name === profileName);
  const profileOverride = updatedProfile?.autonomy?.read_files?.agent_override;
  if (
    updated.project !== project
    || !updatedProfile
    || typeof agents !== 'object'
    || agents === null
    || Array.isArray(agents)
    || (agents as Record<string, unknown>)[profileName] !== mode
    || profileOverride !== mode
  ) {
    throw new UnconfirmedAutonomyWriteError(
      `Das Control-Plane-Backend bestätigte den Autonomie-Modus ${mode} für ${profileName} nicht. `
      + 'Der Entwurf bleibt erhalten; möglicherweise unterstützt dieses Backend noch keine profilweisen Updates.'
    );
  }
  return updated;
}
