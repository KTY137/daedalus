// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-License-Identifier: Apache-2.0

/* =========================================================================
   Executable contract for the motion system.

   There is no test runner in apps/web and adding one would mean adding a
   dependency, so this file is written as a pure function that returns its
   own results. `node src/motion/run-spec.mjs` bundles it with the esbuild
   already installed under node_modules (a vite dependency — nothing new)
   and runs it. `tsc` type-checks it as part of `npm run build`, and because
   nothing imports it from the app entry it contributes 0 bytes to dist/.

   What it pins down:
     - the two tiers stay separated (ack <= 180ms, state >= 200ms)
     - the four reduced-motion rules R1-R4 from variants.ts, on every factory
     - "we only animate transform and opacity" — audited, not asserted in a
       comment
     - the springs are damped at ~critical, i.e. the glass does not bounce
   ========================================================================= */

import type { Variants } from 'framer-motion';
import {
  ACK_CEILING_MS,
  COMPOSITED_PROPS,
  DISTANCE,
  DURATION_MS,
  SPRING,
  STAGGER,
  STATE_FLOOR_MS,
  staggerFor
} from './tokens';
import {
  armVariants,
  auditTransition,
  auditVariants,
  bubbleVariants,
  drawerVariants,
  liftProps,
  listVariants,
  pressProps,
  revealVariants,
  ringVariants,
  scrimVariants,
  surfaceVariants,
  transitionFor,
  type Tier
} from './variants';

export interface SpecResult {
  name: string;
  ok: boolean;
  detail: string;
}

const TIERS: Tier[] = ['ack', 'move', 'enter', 'exit'];

/** Every factory that produces a visible, two-state change. */
function visualFactories(reduced: boolean): Array<[string, Variants]> {
  return [
    ['surfaceVariants', surfaceVariants(reduced)],
    ['scrimVariants', scrimVariants(reduced)],
    ['drawerVariants', drawerVariants(reduced)],
    ['revealVariants', revealVariants(reduced)],
    ['bubbleVariants(left)', bubbleVariants(reduced, 'left')],
    ['bubbleVariants(right)', bubbleVariants(reduced, 'right')],
    ['ringVariants', ringVariants(reduced)],
    ['armVariants', armVariants(reduced)]
  ];
}

/** Factories whose non-reduced form must genuinely be spatial. `scrimVariants`
 *  is excluded on purpose: a full-viewport element never travels. */
const SPATIAL_FACTORIES = new Set([
  'surfaceVariants',
  'drawerVariants',
  'revealVariants',
  'bubbleVariants(left)',
  'bubbleVariants(right)',
  'ringVariants',
  'armVariants'
]);

function opacityValues(variants: Variants): number[] {
  const out: number[] = [];
  for (const state of Object.values(variants)) {
    if (!state || typeof state !== 'object') continue;
    const value = (state as Record<string, unknown>).opacity;
    if (typeof value === 'number') out.push(value);
  }
  return out;
}

function dampingRatio(spring: { stiffness: number; damping: number; mass: number }): number {
  return spring.damping / (2 * Math.sqrt(spring.stiffness * spring.mass));
}

export function runMotionSpec(): SpecResult[] {
  const results: SpecResult[] = [];
  const check = (name: string, ok: boolean, detail = '') => results.push({ name, ok, detail });

  /* ── the vocabulary itself ──────────────────────────────────────────── */

  check(
    'tiers do not overlap: ack ceiling is below state floor',
    ACK_CEILING_MS < STATE_FLOOR_MS,
    `${ACK_CEILING_MS}ms < ${STATE_FLOOR_MS}ms`
  );

  check(
    'acknowledgement durations sit in the acknowledgement tier',
    DURATION_MS.instant <= ACK_CEILING_MS && DURATION_MS.ack <= ACK_CEILING_MS,
    `instant=${DURATION_MS.instant} ack=${DURATION_MS.ack} ceiling=${ACK_CEILING_MS}`
  );

  check(
    'state-change durations sit in the state tier',
    DURATION_MS.move >= STATE_FLOOR_MS &&
      DURATION_MS.enter >= STATE_FLOOR_MS &&
      DURATION_MS.exit >= STATE_FLOOR_MS,
    `move=${DURATION_MS.move} enter=${DURATION_MS.enter} exit=${DURATION_MS.exit}`
  );

  check(
    'surfaces leave faster than they arrive',
    DURATION_MS.exit < DURATION_MS.enter,
    `exit=${DURATION_MS.exit} < enter=${DURATION_MS.enter}`
  );

  for (const [name, spring] of Object.entries(SPRING)) {
    const zeta = dampingRatio(spring);
    check(
      `spring "${name}" is damped at ~critical (no bounce)`,
      zeta >= 0.9 && zeta <= 1.1,
      `zeta=${zeta.toFixed(3)}`
    );
  }

  check('staggerFor(1) is 0', staggerFor(1) === 0, `${staggerFor(1)}`);
  check(
    'staggerFor(3) uses the nominal per-child offset',
    Math.abs(staggerFor(3) - STAGGER.child) < 1e-9,
    `${staggerFor(3)}`
  );
  check(
    'a long list tightens rather than dragging past the cap',
    staggerFor(40) * 39 <= STAGGER.totalCap + 1e-9,
    `total=${(staggerFor(40) * 39).toFixed(3)}s cap=${STAGGER.totalCap}s`
  );

  /* ── tier resolution ────────────────────────────────────────────────── */

  const fullAck = auditTransition(transitionFor('ack', false));
  check(
    'ack tier is a short tween, never a spring',
    !fullAck.isSpring && fullAck.durationMs > 0 && fullAck.durationMs <= ACK_CEILING_MS,
    `spring=${fullAck.isSpring} duration=${fullAck.durationMs}ms`
  );

  for (const tier of ['move', 'enter'] as Tier[]) {
    check(
      `${tier} tier carries mass (spring)`,
      auditTransition(transitionFor(tier, false)).isSpring,
      ''
    );
  }

  const fullExit = auditTransition(transitionFor('exit', false));
  check(
    'exit tier is a timed departure, not a spring',
    !fullExit.isSpring && fullExit.durationMs >= STATE_FLOOR_MS,
    `duration=${fullExit.durationMs}ms`
  );

  /* ── R3 + R4: reduced motion never springs, never stalls ────────────── */

  for (const tier of TIERS) {
    const t = auditTransition(transitionFor(tier, true));
    check(
      `reduced/${tier}: R4 no spring`,
      !t.isSpring,
      `spring=${t.isSpring}`
    );
    check(
      `reduced/${tier}: R3 visible but bounded (0 < d <= ${ACK_CEILING_MS}ms)`,
      t.durationMs > 0 && t.durationMs <= ACK_CEILING_MS,
      `duration=${t.durationMs}ms`
    );
  }

  /* ── R1 + R2: reduced motion is flat, but still legible ─────────────── */

  for (const [name, variants] of visualFactories(true)) {
    const audit = auditVariants(variants);
    const spatial = audit.animatedProps.filter((p) => p !== 'opacity');

    check(
      `reduced/${name}: R1 no spatial keys`,
      spatial.length === 0,
      spatial.length ? `found ${spatial.join(', ')}` : 'opacity only'
    );

    const opacities = new Set(opacityValues(variants));
    check(
      `reduced/${name}: R2 the state change is still perceptible`,
      opacities.size >= 2,
      `opacity values ${[...opacities].join(' -> ')}`
    );

    check(
      `reduced/${name}: R4 no spring in the variant set`,
      !audit.usesSpring,
      ''
    );

    check(
      `reduced/${name}: R3 no variant transition exceeds the ack ceiling`,
      audit.maxDurationMs <= ACK_CEILING_MS,
      `max=${audit.maxDurationMs}ms`
    );
  }

  check(
    'reduced: list orchestration drops the stagger entirely',
    (() => {
      const visible = listVariants(true, 8).visible as Record<string, unknown> | undefined;
      const transition = visible?.transition as Record<string, unknown> | undefined;
      return transition?.staggerChildren === 0;
    })(),
    ''
  );

  check(
    'reduced: press feedback is removed, not shrunk',
    pressProps(true) === undefined,
    ''
  );
  check(
    'full: press feedback is a scale-down',
    (pressProps(false)?.scale ?? 1) < 1,
    `scale=${pressProps(false)?.scale}`
  );
  check(
    'reduced: hover lift is removed',
    liftProps(true) === undefined,
    ''
  );
  check(
    'full: hover lift is upward and hairline-small',
    (liftProps(false)?.y ?? 0) < 0 && Math.abs(liftProps(false)?.y ?? 0) <= DISTANCE.nudge,
    `y=${liftProps(false)?.y}`
  );

  /* ── performance is a property: audit every factory, both modes ─────── */

  for (const reduced of [false, true]) {
    const label = reduced ? 'reduced' : 'full';
    for (const [name, variants] of visualFactories(reduced)) {
      const audit = auditVariants(variants);

      check(
        `${label}/${name}: no layout-triggering property`,
        audit.layoutProps.length === 0,
        audit.layoutProps.length ? `found ${audit.layoutProps.join(', ')}` : 'clean'
      );

      const offenders = audit.animatedProps.filter((p) => !COMPOSITED_PROPS.includes(p));
      check(
        `${label}/${name}: composited properties only`,
        offenders.length === 0,
        offenders.length ? `found ${offenders.join(', ')}` : audit.animatedProps.join(', ')
      );
    }
  }

  /* ── the full-motion path really is spatial ─────────────────────────── */

  for (const [name, variants] of visualFactories(false)) {
    if (!SPATIAL_FACTORIES.has(name)) continue;
    const spatial = auditVariants(variants).animatedProps.filter((p) => p !== 'opacity');
    check(
      `full/${name}: the state change is spatial, not a dressed-up fade`,
      spatial.length > 0,
      spatial.join(', ')
    );
  }

  const scrimFull = auditVariants(scrimVariants(false)).animatedProps;
  check(
    'full/scrimVariants: a full-viewport element stays opacity-only',
    scrimFull.length === 1 && scrimFull[0] === 'opacity',
    scrimFull.join(', ')
  );

  return results;
}
