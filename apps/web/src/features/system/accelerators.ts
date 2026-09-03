import type { AcceleratorPayload, AcceleratorFramework, AcceleratorLane } from '@/shared/api';

/**
 * WHAT COMPUTE THIS MACHINE CAN ACTUALLY USE — the reading, separated from the
 * drawing so it can be tested without a browser.
 *
 * `daedalus/foundation/accelerators.py` opens by separating three questions
 * that "are often blurred": is NVIDIA hardware visible, is a backend installed
 * and actually CUDA-capable, and is that backend applicable to the operation
 * being discussed. It then answers all three and ships a `claims` block that
 * says in so many words that the first does not imply the second and the
 * second does not imply the third.
 *
 * A panel that drew "RTX 5080 ✓" and stopped would re-blur exactly what that
 * module spends its length separating. So the reading below refuses three
 * specific collapses, and each refusal has a test:
 *
 * 1. `probed: false` is NOT `installed: false`. The shallow answer — the one
 *    you get without `?deep=1` — reports every framework as not installed with
 *    the detail "deep probe not requested". Rendering that as "nicht
 *    verfügbar" would turn a question nobody asked into a measured absence.
 * 2. `cuda_ready: null` is NOT `false`. A framework can be installed and its
 *    CUDA capability still unknown; the field is tri-state and stays tri-state.
 * 3. `remote_compute.available: null` is NOT "offline". Nothing was probed,
 *    because no target is configured.
 *
 * The lane vocabulary is the backend's own five words, and like the health
 * vocabulary it does not collapse to a boolean:
 *
 *   ready       a backend is installed AND measured CUDA-capable
 *   unverified  it is installed, but this process could not prove it works
 *   configured  a path/SDK is configured; nothing was executed
 *   missing     the named requirement is not present
 *   unsupported not a Daedalus backend at all, on purpose (DLSS)
 */

/** How a framework row actually reads, once the two nulls are respected. */
export type FrameworkReading = 'ready' | 'unverified' | 'installed' | 'absent' | 'unchecked';

export const FRAMEWORK_WORD: Record<FrameworkReading, string> = {
  ready: 'CUDA-fähig',
  unverified: 'installiert, CUDA ungeprüft',
  installed: 'installiert',
  absent: 'nicht installiert',
  unchecked: 'nicht geprüft'
};

/**
 * Read one framework row.
 *
 * ORDER MATTERS. `probed` is consulted FIRST, before `installed`, because the
 * shallow payload sets `installed: false` on every framework whether or not it
 * is there — the probe simply did not run. Checking `installed` first would
 * report six absent frameworks on a machine that may have all six.
 */
export function frameworkReading(row: AcceleratorFramework): FrameworkReading {
  if (!row.probed) return 'unchecked';
  if (!row.installed) return 'absent';
  if (row.cuda_ready === true) return 'ready';
  if (row.cuda_ready === false) return 'unverified';
  // installed, probed, and the CUDA question came back null: still open.
  return 'installed';
}

/** Only a measured `ready` is green. Everything unproven is drawn as unproven. */
export function frameworkTone(reading: FrameworkReading): string {
  if (reading === 'ready') return 'ok';
  if (reading === 'absent') return 'bad';
  return 'warn';
}

export const LANE_WORD: Record<string, string> = {
  ready: 'einsatzbereit',
  unverified: 'installiert, ungeprüft',
  configured: 'konfiguriert, nicht ausgeführt',
  missing: 'fehlt',
  unsupported: 'kein Daedalus-Backend'
};

/**
 * `unsupported` is not a failure and must not be drawn as one. It is the
 * backend saying a lane was considered and deliberately not built — DLSS is
 * "inspiration for DSS, not an executable Daedalus backend". Painting it red
 * would read as something broken that someone should go fix.
 */
export function laneTone(state: string): string {
  if (state === 'ready') return 'ok';
  if (state === 'missing') return 'bad';
  return 'warn';
}

/** Attention first, then the merely unproven, then what holds, then the
 *  deliberate non-goals. An unrecognised word sorts with the unproven. */
const LANE_ORDER = ['ready', 'unverified', 'configured', 'missing', 'unsupported'];

export function laneRank(state: string): number {
  const at = LANE_ORDER.indexOf(state);
  return at === -1 ? LANE_ORDER.indexOf('unverified') : at;
}

export function sortLanes(lanes: AcceleratorLane[]): AcceleratorLane[] {
  return [...lanes].sort((a, b) => laneRank(a.state) - laneRank(b.state));
}

/**
 * The one-line answer, and it is deliberately about LANES rather than about
 * the GPU. `claims.hardware_visible_is_not_backend_ready` is the backend
 * telling us that counting cards answers the wrong question.
 */
export function computeSummary(payload: AcceleratorPayload | undefined): string {
  if (!payload) return 'Rechenlage nicht gelesen';
  const lanes = payload.accelerators?.lanes || [];
  if (lanes.length === 0) return 'Keine Lane gemeldet';
  const ready = lanes.filter((l) => l.state === 'ready').length;
  const devices = payload.accelerators?.hardware?.devices?.length || 0;
  const seen = devices === 1 ? '1 Gerät sichtbar' : `${devices} Geräte sichtbar`;
  // Zero ready lanes is stated as zero, never as the device count.
  return `${seen} · ${ready} von ${lanes.length} Lanes einsatzbereit`;
}

/** Was anything actually executed, or is this the shallow answer? */
export function wasDeepProbed(payload: AcceleratorPayload | undefined): boolean {
  const frameworks = payload?.accelerators?.frameworks;
  if (!frameworks) return false;
  return Object.values(frameworks).some((row) => row.probed);
}
