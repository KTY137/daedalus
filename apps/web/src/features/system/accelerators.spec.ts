import type { AcceleratorFramework, AcceleratorLane, AcceleratorPayload } from '@/shared/api';
import {
  FRAMEWORK_WORD,
  LANE_WORD,
  computeSummary,
  frameworkReading,
  frameworkTone,
  laneRank,
  laneTone,
  sortLanes,
  wasDeepProbed
} from './accelerators';

/**
 * The accelerator reading, pinned.
 *
 * Every check here exists because the payload contains a field whose falsy
 * value means "nobody asked" rather than "no". Those are the collapses that
 * turn an unmeasured machine into a confidently wrong inventory.
 */

interface Result {
  name: string;
  ok: boolean;
  detail?: string;
}

function fw(over: Partial<AcceleratorFramework> = {}): AcceleratorFramework {
  return { installed: false, cuda_ready: null, detail: '', probed: false, ...over };
}

function lane(over: Partial<AcceleratorLane> = {}): AcceleratorLane {
  return {
    id: 'l',
    label: 'L',
    state: 'missing',
    applicable_to: [],
    evidence: [],
    missing: [],
    warning: '',
    ...over
  };
}

export function runAcceleratorSpec(): Result[] {
  const results: Result[] = [];
  const check = (name: string, ok: boolean, detail = '') => results.push({ name, ok, detail });

  // ---- 1. `probed: false` is not `installed: false` ------------------------
  // This is the live shape of every framework row on the shallow answer. The
  // real payload sets installed:false on all six whether or not they exist.
  const shallow = fw({ installed: false, probed: false, detail: 'deep probe not requested' });
  check(
    'an unprobed framework reads as unchecked, never as absent',
    frameworkReading(shallow) === 'unchecked',
    frameworkReading(shallow)
  );
  check('an unchecked framework is not painted as a failure', frameworkTone('unchecked') === 'warn');
  check('an unchecked framework does not say "nicht installiert"', FRAMEWORK_WORD.unchecked === 'nicht geprüft');
  // The order dependency itself: if `installed` were consulted first, the
  // shallow row would read `absent` and this machine would report six missing
  // backends it never looked for.
  check(
    'probed is consulted before installed',
    frameworkReading(fw({ installed: false, probed: false })) !== frameworkReading(fw({ installed: false, probed: true }))
  );
  check(
    'a probed and genuinely absent framework does read as absent',
    frameworkReading(fw({ installed: false, probed: true })) === 'absent'
  );

  // ---- 2. `cuda_ready: null` is not `false` --------------------------------
  check(
    'installed with an open CUDA question is neither ready nor unverified',
    frameworkReading(fw({ installed: true, probed: true, cuda_ready: null })) === 'installed'
  );
  check(
    'installed and measured CUDA-capable is ready',
    frameworkReading(fw({ installed: true, probed: true, cuda_ready: true })) === 'ready'
  );
  check(
    'installed and measured NOT CUDA-capable is unverified, not absent',
    frameworkReading(fw({ installed: true, probed: true, cuda_ready: false })) === 'unverified'
  );
  check(
    'only a measured ready framework is green',
    frameworkTone('ready') === 'ok'
      && frameworkTone('installed') === 'warn'
      && frameworkTone('unverified') === 'warn'
  );

  // ---- 3. the lane vocabulary does not collapse ----------------------------
  check('every backend lane word has a German reading',
    ['ready', 'unverified', 'configured', 'missing', 'unsupported'].every((s) => Boolean(LANE_WORD[s])));
  check('only a ready lane is green', laneTone('ready') === 'ok');
  check('a missing lane is a failure', laneTone('missing') === 'bad');
  // `unsupported` means "considered and deliberately not built" — DLSS. Red
  // would read as something broken that somebody should go fix.
  check('an unsupported lane is not painted as broken', laneTone('unsupported') === 'warn');
  check('a lane word this interface does not know is not green', laneTone('brandneu') === 'warn');
  check('an unknown lane word sorts with the unproven, not first',
    laneRank('brandneu') === laneRank('unverified') && laneRank('brandneu') > laneRank('ready'));

  const sorted = sortLanes([
    lane({ id: 'a', state: 'unsupported' }),
    lane({ id: 'b', state: 'missing' }),
    lane({ id: 'c', state: 'ready' }),
    lane({ id: 'd', state: 'unverified' })
  ]);
  check(
    'lanes sort attention first and deliberate non-goals last',
    sorted.map((l) => l.id).join('') === 'cdba',
    sorted.map((l) => `${l.id}:${l.state}`).join(' ')
  );
  check('sorting does not mutate the payload array', (() => {
    const input = [lane({ id: 'x', state: 'missing' }), lane({ id: 'y', state: 'ready' })];
    sortLanes(input);
    return input[0].id === 'x';
  })());

  // ---- 4. the summary counts lanes, not cards -----------------------------
  const payload = (over: Partial<AcceleratorPayload['accelerators']> = {}): AcceleratorPayload => ({
    ok: true,
    generated_at: '',
    project: null,
    warnings: [],
    accelerators: {
      schema: 'daedalus-accelerators/1',
      hardware: { available: true, command: '', devices: [{ name: 'RTX 5080', compute_capability: '12.0', memory_mib: 16303, driver_version: '610.47' }], error: '' },
      frameworks: {},
      lanes: [],
      remote_compute: { configured: false, available: null, target: '', devices: [], error: '', hint: '' },
      claims: {},
      ...over
    }
  } as AcceleratorPayload);

  // The live machine: one visible card, zero ready lanes. A summary that let
  // the card stand in for capability would be the exact claim the backend's
  // `hardware_visible_is_not_backend_ready` exists to deny.
  const live = computeSummary(payload({ lanes: [lane({ state: 'missing' }), lane({ id: 'z', state: 'unsupported' })] }));
  check('a visible GPU with no ready lane reports zero ready lanes', live.includes('0 von 2'), live);
  check('the visible device is still reported', live.includes('1 Gerät sichtbar'), live);
  check(
    'a read that never happened is not summarised as an empty machine',
    computeSummary(undefined) === 'Rechenlage nicht gelesen'
  );

  // ---- 5. "was anything actually executed?" -------------------------------
  check('the shallow answer is not reported as probed',
    wasDeepProbed(payload({ frameworks: { torch: fw(), cupy: fw() } })) === false);
  check('one probed framework makes the answer a deep one',
    wasDeepProbed(payload({ frameworks: { torch: fw(), cupy: fw({ probed: true }) } })) === true);
  check('an unread payload is not claimed to be probed', wasDeepProbed(undefined) === false);

  return results;
}
