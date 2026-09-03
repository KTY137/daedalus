import type { AcceleratorPayload, AcceleratorFramework, AcceleratorLane } from '@/shared/api';

/**
 * WHAT COMPUTE THIS MACHINE CAN ACTUALLY USE — the reading, separated from the
 * drawing so it can be tested without a browser.
 *
 * `daedalus/foundation/accelerators.py` opens by separating three questions
 * that "are often blurred": is NVIDIA hardware visible, is a backend installed
 * and actually CUDA-capable, and is that backend applicable to the operation
 * being discussed. It then answers all three and ships a `claims` block saying
 * the first does not imply the second and the second does not imply the third.
 *
 * A panel that drew "RTX 5080 ✓" and stopped would re-blur exactly what that
 * module spends its length separating.
 *
 * SIX READINGS, BECAUSE THE PAYLOAD EXPRESSES SIX THINGS. An earlier version
 * of this file had four and got the shallow answer wrong in both directions.
 * It assumed `installed` was a meaningless placeholder until a deep probe ran.
 * It is not: `_framework_rows(deep=False)` calls `_has_module(name)`, which is
 * a live `importlib.util.find_spec`. So the shallow answer carries a real
 * measurement of presence and a genuinely open question about CUDA — two
 * facts, which the old reading collapsed into one word ("nicht geprüft") and
 * thereby discarded the measured half.
 *
 * The failure directions this file exists to refuse:
 *
 * 1. A DEAD PROBE MUST NOT READ AS ABSENCE. When the probe subprocess times
 *    out, crashes, or prints unparseable output, `deep_framework_status()`
 *    returns `{"probe": {...}}` with no framework keys — and `_framework_rows`
 *    still stamps `probed: True` on all six, filling in `installed: False` and
 *    an EMPTY `detail`. Read naively that is six confident red rows saying
 *    "nicht installiert" about six modules nobody looked at. The discriminator
 *    is the detail: `_DEEP_PROBE` writes a non-empty detail on every row it
 *    produces — the version string on success, `"ExcName: msg"` on failure —
 *    so `probed` with an empty detail can only mean the row is a fill-in.
 * 2. A MEASURED PRESENCE MUST NOT BE THROWN AWAY. `installed: true` with
 *    `probed: false` means find_spec found it and nothing was executed.
 * 3. `cuda_ready: null` IS NOT `false`. `_DEEP_PROBE` deliberately sets null
 *    for cuvs, cugraph and newton because import success "alone must not claim
 *    CUDA readiness". Three values in, three readings out.
 */

export type FrameworkReading =
  /** probed, imported, and a device check said CUDA works */
  | 'ready'
  /** probed, imported, and a device check said CUDA does NOT work */
  | 'no_cuda'
  /** probed and imported, but the probe deliberately left CUDA unanswered */
  | 'cuda_untested'
  /** not probed: find_spec found it, nothing was executed */
  | 'importable'
  /** the check ran and the module is not importable */
  | 'absent'
  /** the deep probe died; this row is a fill-in and says nothing */
  | 'unchecked';

export const FRAMEWORK_WORD: Record<FrameworkReading, string> = {
  ready: 'CUDA-fähig',
  no_cuda: 'installiert, kein CUDA',
  cuda_untested: 'installiert, CUDA nicht geprüft',
  importable: 'importierbar, nicht ausgeführt',
  absent: 'nicht installiert',
  unchecked: 'nicht geprüft'
};

export function frameworkReading(row: AcceleratorFramework): FrameworkReading {
  if (row.probed) {
    // See refusal 1 above: an empty detail on a probed row is a fill-in for a
    // framework the probe process never reported on.
    if (!row.detail) return 'unchecked';
    if (!row.installed) return 'absent';
    if (row.cuda_ready === true) return 'ready';
    if (row.cuda_ready === false) return 'no_cuda';
    return 'cuda_untested';
  }
  // Shallow. `installed` is a live find_spec, so it is evidence either way.
  return row.installed ? 'importable' : 'absent';
}

/**
 * Only a measured `ready` is green; only a measured absence is red. Everything
 * in between is unproven, including a row the probe failed to produce — which
 * must never look like the confident red of "we looked, it is not there".
 */
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
  // A payload whose `accelerators` block never arrived is not a machine that
  // reported zero lanes. Saying "keine Lane gemeldet" for a malformed 200
  // asserts something the response never contained.
  if (!payload.accelerators) return 'Rechenlage unvollständig gelesen';
  const lanes = payload.accelerators.lanes || [];
  if (lanes.length === 0) return 'Keine Lane gemeldet';
  const ready = lanes.filter((l) => l.state === 'ready').length;

  /*
   * BOTH SIDES OF THE MACHINE, because counting one of them was a quiet lie.
   *
   * This counted `hardware.devices` only — the card in the box this process
   * runs on. `accelerators.py` was rewritten specifically because that is the
   * wrong question here: "this module answered hardware questions about the
   * machine it RUNS on while the capable card lives on the bench". On exactly
   * that setup — no local card, a probed RTX 5080 over ssh — the summary read
   * "0 Geräte sichtbar" directly above a section listing the bench GPU.
   *
   * The two are counted separately rather than added. A local card and a
   * remote one are not interchangeable, and a single total would invite
   * exactly the substitution the module refuses to make.
   */
  const local = payload.accelerators.hardware?.devices?.length || 0;
  const bench = payload.accelerators.remote_compute?.devices?.length || 0;
  const seen = local === 1 ? '1 Gerät sichtbar' : `${local} Geräte sichtbar`;
  const remote = bench > 0 ? ` · ${bench} auf der Bench` : '';

  // Zero ready lanes is stated as zero, never as a device count.
  return `${seen}${remote} · ${ready} von ${lanes.length} Lanes einsatzbereit`;
}

/**
 * What the backend said this architecture can host, in its own words.
 *
 * `capability_lanes()` answers "could this silicon run the lane AT ALL",
 * which is not the question "is a library installed". Its docstring is blunt
 * about why the distinction earns its keep: "'missing' invites someone to go
 * install a library. 'impossible' tells them to stop."
 *
 * This returns the backend's `note` and never derives one. The compute-
 * capability floors live in `_CC_FLOORS` on the Python side and a second
 * opinion computed in a browser would be a second source of truth for a
 * hardware fact — exactly the duplication the plan forbids. An unparseable
 * capability comes back `known: false` with its own note, which is also the
 * backend's to write.
 */
export function capabilityNote(capability: Record<string, unknown> | undefined): string {
  if (!capability) return '';
  const note = capability.note;
  return typeof note === 'string' ? note : '';
}

/** VRAM, or an honest absence. `nvidia-smi` reports `[N/A]` for some cards and
 *  the backend turns that into `null` — which `Math.round(null / 1024)` would
 *  render as a confident "0 GiB", i.e. a card stated to have no memory. */
export function memoryText(mib: number | null | undefined): string {
  if (typeof mib !== 'number' || !Number.isFinite(mib)) return 'VRAM nicht gemeldet';
  return `${Math.round(mib / 1024)} GiB`;
}
