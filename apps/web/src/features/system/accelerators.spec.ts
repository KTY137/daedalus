import type { AcceleratorFramework, AcceleratorLane, AcceleratorPayload } from '@/shared/api';
import {
  FRAMEWORK_WORD,
  LANE_WORD,
  computeSummary,
  frameworkReading,
  frameworkTone,
  laneRank,
  laneTone,
  memoryText,
  sortLanes,
  type FrameworkReading
} from './accelerators';

/**
 * The accelerator reading, pinned EXHAUSTIVELY.
 *
 * An earlier version of this spec checked four of the six readings and left
 * `FRAMEWORK_WORD.installed` and `frameworkTone('absent')` unasserted. An
 * independent reviewer planted two mutations there — flipping the word for an
 * installed framework to "nicht installiert", and deleting the red from a
 * measured absence — and both survived a 160/160 green run. A vocabulary is
 * only pinned if every entry is pinned, so the tables below are iterated
 * rather than sampled.
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

/** Every reading the type admits. A new member without a row here fails to
 *  compile, so the tables below cannot silently fall out of date. */
const ALL_READINGS: FrameworkReading[] = [
  'ready',
  'no_cuda',
  'cuda_untested',
  'importable',
  'absent',
  'unchecked'
];

export function runAcceleratorSpec(): Result[] {
  const results: Result[] = [];
  const check = (name: string, ok: boolean, detail = '') => results.push({ name, ok, detail });

  // ---- 1. the shallow answer carries a real measurement -------------------
  // `_framework_rows(deep=False)` calls `_has_module()`, a live find_spec.
  // Reading it as "nothing is known" throws away the measured half.
  check(
    'a shallow row that found the module reads as importable, not unchecked',
    frameworkReading(fw({ installed: true, probed: false, detail: 'deep probe not requested' })) === 'importable'
  );
  check(
    'a shallow row that did not find the module reads as absent',
    frameworkReading(fw({ installed: false, probed: false, detail: 'deep probe not requested' })) === 'absent'
  );
  check(
    'importable never claims CUDA',
    !FRAMEWORK_WORD.importable.includes('CUDA-fähig') && FRAMEWORK_WORD.importable.includes('nicht ausgeführt'),
    FRAMEWORK_WORD.importable
  );

  // ---- 2. a dead probe is not an absence ----------------------------------
  // When the probe subprocess dies, `_framework_rows(deep=True)` still stamps
  // `probed: True` on all six with `installed: False` and an EMPTY detail.
  // Read naively that is six confident red rows about six modules nobody
  // looked at — the exact collapse this surface exists to prevent.
  const dead = fw({ installed: false, cuda_ready: null, detail: '', probed: true });
  check(
    'a probed row with no detail is a fill-in, not a measured absence',
    frameworkReading(dead) === 'unchecked',
    frameworkReading(dead)
  );
  check('a fill-in row is not painted as a failure', frameworkTone(frameworkReading(dead)) === 'warn');
  check(
    'a probed row WITH a detail is a real answer and may be absent',
    frameworkReading(fw({ installed: false, detail: "ModuleNotFoundError: No module named 'torch'", probed: true })) === 'absent'
  );

  // ---- 3. cuda_ready stays tri-state --------------------------------------
  const probed = (cuda: boolean | null) =>
    frameworkReading(fw({ installed: true, probed: true, detail: '2.6.0', cuda_ready: cuda }));
  check('CUDA measured available is ready', probed(true) === 'ready');
  check('CUDA measured unavailable is no_cuda, not absent', probed(false) === 'no_cuda');
  check('CUDA left unanswered by the probe is cuda_untested', probed(null) === 'cuda_untested');
  check(
    'the three CUDA outcomes are three distinct readings',
    new Set([probed(true), probed(false), probed(null)]).size === 3
  );

  // ---- 4. the vocabulary, every entry ------------------------------------
  // B2: both of these tables had unasserted rows, and a mutation to each
  // survived a fully green run.
  for (const reading of ALL_READINGS) {
    check(`the word for "${reading}" exists and is not empty`, Boolean(FRAMEWORK_WORD[reading]?.trim()));
  }
  check(
    'every reading has a DISTINCT word',
    new Set(ALL_READINGS.map((r) => FRAMEWORK_WORD[r])).size === ALL_READINGS.length,
    ALL_READINGS.map((r) => FRAMEWORK_WORD[r]).join(' | ')
  );
  // The direction that matters: a word must not say the opposite of its state.
  check('installed readings do not say "nicht installiert"', (
    ['ready', 'no_cuda', 'cuda_untested', 'importable'] as FrameworkReading[]
  ).every((r) => !FRAMEWORK_WORD[r].includes('nicht installiert')));
  check('absent says it is absent', FRAMEWORK_WORD.absent === 'nicht installiert');
  check('unchecked says it was not checked', FRAMEWORK_WORD.unchecked === 'nicht geprüft');

  const TONES: Record<FrameworkReading, string> = {
    ready: 'ok',
    no_cuda: 'warn',
    cuda_untested: 'warn',
    importable: 'warn',
    absent: 'bad',
    unchecked: 'warn'
  };
  for (const reading of ALL_READINGS) {
    check(`"${reading}" is drawn ${TONES[reading]}`, frameworkTone(reading) === TONES[reading], frameworkTone(reading));
  }
  check(
    'exactly one reading is green, and it is the measured one',
    ALL_READINGS.filter((r) => frameworkTone(r) === 'ok').join() === 'ready'
  );
  check(
    'exactly one reading is red, and it is the measured absence',
    ALL_READINGS.filter((r) => frameworkTone(r) === 'bad').join() === 'absent'
  );
  // The distinction the whole surface rests on: "not checked" and "checked and
  // not there" must not look the same.
  check(
    'a fill-in and a measured absence are drawn differently',
    frameworkTone('unchecked') !== frameworkTone('absent')
  );

  // ---- 5. the lane vocabulary does not collapse ---------------------------
  const LANE_TONES: Record<string, string> = {
    ready: 'ok',
    unverified: 'warn',
    configured: 'warn',
    missing: 'bad',
    unsupported: 'warn'
  };
  for (const [state, tone] of Object.entries(LANE_TONES)) {
    check(`lane "${state}" has a German word`, Boolean(LANE_WORD[state]?.trim()));
    check(`lane "${state}" is drawn ${tone}`, laneTone(state) === tone, laneTone(state));
  }
  // `unsupported` means "considered and deliberately not built" — DLSS. Red
  // would read as something broken that somebody should go fix.
  check('an unsupported lane is not painted as broken', laneTone('unsupported') !== 'bad');
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

  // ---- 6. VRAM that nvidia-smi could not report --------------------------
  // The backend turns `[N/A]` into null. `Math.round(null / 1024)` is 0, so a
  // card whose memory is unknown was stated to have none.
  check('unreported VRAM is not rendered as zero', memoryText(null) === 'VRAM nicht gemeldet', memoryText(null));
  check('undefined VRAM is not rendered as NaN', memoryText(undefined) === 'VRAM nicht gemeldet');
  check('a reported VRAM is rendered in GiB', memoryText(16303) === '16 GiB', memoryText(16303));

  // ---- 7. the summary counts lanes, not cards ----------------------------
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
      remote_rtx_ollama: { configured: false, available: false, endpoint: '', models: [], error: '', warning: '' },
      remote_compute: { configured: false, available: null, target: '', devices: [], error: '', hint: '' },
      claims: {},
      ...over
    }
  } as AcceleratorPayload);

  const live = computeSummary(payload({ lanes: [lane({ state: 'missing' }), lane({ id: 'z', state: 'unsupported' })] }));
  check('a visible GPU with no ready lane reports zero ready lanes', live.includes('0 von 2'), live);
  check('the visible device is still reported', live.includes('1 Gerät sichtbar'), live);
  check(
    'a read that never happened is not summarised as an empty machine',
    computeSummary(undefined) === 'Rechenlage nicht gelesen'
  );
  // A malformed 200 whose `accelerators` block never arrived is not a machine
  // that reported zero lanes.
  check(
    'a payload missing its snapshot is not reported as zero lanes',
    computeSummary({ ok: true } as AcceleratorPayload) === 'Rechenlage unvollständig gelesen',
    computeSummary({ ok: true } as AcceleratorPayload)
  );

  return results;
}
