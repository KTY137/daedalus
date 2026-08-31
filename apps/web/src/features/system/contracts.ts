import type {
  BootstrapPayload,
  ControlPlanePayload,
  DashboardPayload,
  HierarchyPayload
} from '../../types';
import type {
  LoopArchitecturePayload,
  LoopAttemptsPayload,
  LoopQueuePayload,
  ProviderStatusPayload
} from '../../api';

/** A failed read is evidence in its own right; it never becomes an empty row. */
export interface CapabilityFailure {
  kind: string;
  message: string;
}

export type CapabilityResult<T> =
  | { status: 'ready'; data: T; loadedAt: number }
  | { status: 'error'; error: CapabilityFailure; loadedAt: number };

/**
 * One project-scoped, deletable projection over the existing HTTP contracts.
 * It owns no store, scheduler, provider or authorization decision.
 */
export interface SystemCapabilitiesSnapshot {
  project: string;
  dashboard: CapabilityResult<DashboardPayload>;
  controlPlane: CapabilityResult<ControlPlanePayload>;
  claudeBootstrap: CapabilityResult<BootstrapPayload>;
  providerStatus: CapabilityResult<ProviderStatusPayload>;
  hierarchy: CapabilityResult<HierarchyPayload>;
  loopQueue: CapabilityResult<LoopQueuePayload>;
  loopAttempts: CapabilityResult<LoopAttemptsPayload>;
  loopArchitecture: CapabilityResult<LoopArchitecturePayload>;
}
