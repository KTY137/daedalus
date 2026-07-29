/* =========================================================================
   Ikarus motion vocabulary — the ONLY place a duration, easing, spring or
   travel distance is allowed to be written down.
   =========================================================================

   The instrument premise: "cold glass, warm voice". Glass has mass. It does
   not bounce, it does not squash, it does not wobble to a stop like a toy.
   It arrives with weight and settles. Everything here is damped at or just
   under critical — the overshoot is never more than a hair, and it is there
   only so the motion reads as physical rather than as a timed fade.

   ── the two tiers ───────────────────────────────────────────────────────
   There are exactly two kinds of motion in this UI, and confusing them is
   what makes an interface feel cheap.

   1. ACKNOWLEDGEMENT  (<= 180ms, no spatial displacement beyond `nudge`)
      "I heard you." Hover, press, focus, a value ticking over. It is
      feedback about the INPUT, not about the world. It must be over before
      you can think about it. Never a spring — a spring has a settle phase,
      and an acknowledgement that settles reads as lag.

      Where a CSS pseudo-class already expresses the state (`:hover`,
      `:active`, `:focus-visible`), the acknowledgement STAYS IN CSS. It is
      cheaper, it needs no React state, and it cannot desync. framer-motion
      is used for an acknowledgement only when the state lives in React
      anyway (e.g. the composer's focus ring, which coordinates with the
      send button's armed state).

   2. STATE CHANGE  (220-360ms, spatial, spring or the house curve)
      "The world is now different." A sheet opens, the active view moves,
      a message arrives, a card appears. It is feedback about the SYSTEM.
      It gets distance and it gets time, because the user has to be able to
      follow where a thing went. Owned by framer-motion, because it needs
      orchestration: presence, shared layout, stagger.

   The tier boundary is asserted by motion.spec.ts: ack <= 180ms, state
   >= 200ms. If someone widens one into the other, the test fails.

   ── parity with CSS ─────────────────────────────────────────────────────
   styles.css carries `--dur-fast: 140ms`, `--dur: 240ms`, `--dur-slow: 420ms`
   and `--ease: cubic-bezier(.32,.72,0,1)`. Those are the SAME numbers as
   `ack`, `move`, `ambient` and `EASE.glass` below. useMotion.ts reads the
   custom properties once at startup and warns if the two ever drift, so the
   CSS half and the JS half of the system cannot silently diverge.
   ========================================================================= */

/** Durations in milliseconds. Milliseconds are the source of truth because
 *  that is the unit the CSS side speaks; `sec()` converts for framer-motion. */
export const DURATION_MS = {
  /** Pure press feedback. Below the threshold where you perceive a transition. */
  instant: 90,
  /** The acknowledgement tier. Mirrors CSS `--dur-fast`. */
  ack: 140,
  /** An element moves within a context it never left. Mirrors CSS `--dur`. */
  move: 240,
  /** A surface leaves. Deliberately faster than `enter` — dismissal must feel
   *  instant, arrival must feel deliberate. */
  exit: 220,
  /** A surface arrives. */
  enter: 320,
  /** Ambient / looping. Mirrors CSS `--dur-slow`. */
  ambient: 420
} as const;

export type DurationName = keyof typeof DURATION_MS;

/** Upper bound of the acknowledgement tier. */
export const ACK_CEILING_MS = 180;
/** Lower bound of the state-change tier. */
export const STATE_FLOOR_MS = 200;

/** ms -> s, for framer-motion, which speaks seconds. */
export function sec(name: DurationName): number {
  return DURATION_MS[name] / 1000;
}

export type Bezier = [number, number, number, number];

export const EASE: Record<'glass' | 'depart' | 'ack', Bezier> = {
  /** The house curve. Fast off the mark, long tail — the visionOS/iOS glass
   *  feel already used throughout styles.css. Arrivals and moves. */
  glass: [0.32, 0.72, 0, 1],
  /** Accelerate out. Departures: a thing that is leaving should look like it
   *  has somewhere to be. */
  depart: [0.4, 0, 1, 1],
  /** Snappy, no tail, no overshoot. Acknowledgements. */
  ack: [0.2, 0, 0, 1]
};

export interface SpringToken {
  readonly type: 'spring';
  readonly stiffness: number;
  readonly damping: number;
  readonly mass: number;
}

/* Damping ratio zeta = c / (2*sqrt(k*m)). Both springs below sit at
 * zeta ~= 0.98-1.01 — critically damped to within a percent. That is the
 * whole aesthetic argument: an instrument settles, it does not bounce. */
export const SPRING = {
  /** Small parts with little mass: the segmented thumb, the dock pill, a
   *  message arriving. 2*sqrt(420*0.9) = 38.9 -> zeta 0.977. */
  instrument: { type: 'spring', stiffness: 420, damping: 38, mass: 0.9 },
  /** Whole surfaces: the sheet. 2*sqrt(260*1.1) = 33.8 -> zeta 1.005,
   *  a shade over-damped so a full-screen panel never rebounds. */
  surface: { type: 'spring', stiffness: 260, damping: 34, mass: 1.1 }
} as const satisfies Record<string, SpringToken>;

/** Travel distances in px. A state change you cannot see travel is a fade
 *  wearing a costume. */
export const DISTANCE = {
  /** A tile lifting off its surface under the cursor. The smallest legible
   *  displacement there is; anything less is noise. */
  hairline: 1,
  /** Acknowledgement-scale displacement. The most a press or hover may move. */
  nudge: 6,
  /** A message or a card arriving in place. */
  rise: 12,
  /** A surface arriving from off-context. Mirrors the sheet's shipped 24px. */
  travel: 24,
  /** A drawer clearing its own edge. */
  drawer: 32
} as const;

export const SCALE = {
  /** Press. */
  press: 0.97,
  /** A surface settling in from slightly small. Mirrors the sheet's .99. */
  settle: 0.985,
  /** A focus ring collapsing onto its target. */
  ring: 1.03
} as const;

/** Stagger, in seconds (framer-motion's unit for orchestration). */
export const STAGGER = {
  /** Per-child offset in a revealed list. */
  child: 0.034,
  /** Hard cap on total stagger — beyond this a list reveal stops reading as
   *  one gesture and starts reading as a slow page load. */
  totalCap: 0.24
} as const;

/** Given n children, the per-child stagger that keeps the whole reveal under
 *  STAGGER.totalCap. Long lists tighten rather than dragging on. */
export function staggerFor(count: number): number {
  if (count <= 1) return 0;
  return Math.min(STAGGER.child, STAGGER.totalCap / (count - 1));
}

/* ── property policy ─────────────────────────────────────────────────────
   Performance is a property of the system, not a hope about it. Only these
   may be animated; motion.spec.ts audits every variant factory against the
   lists and fails the build's test step if a layout-triggering property
   ever appears in one. */

/** Composited: the compositor can run these without the main thread doing
 *  layout or paint work. */
export const COMPOSITED_PROPS: readonly string[] = [
  'opacity',
  'x',
  'y',
  'z',
  'scale',
  'scaleX',
  'scaleY',
  'rotate',
  'rotateX',
  'rotateY',
  'rotateZ',
  'transform'
];

/** Animating any of these forces layout on every frame. Banned outright. */
export const LAYOUT_TRIGGERING_PROPS: readonly string[] = [
  'width',
  'height',
  'minWidth',
  'minHeight',
  'maxWidth',
  'maxHeight',
  'top',
  'right',
  'bottom',
  'left',
  'inset',
  'margin',
  'marginTop',
  'marginRight',
  'marginBottom',
  'marginLeft',
  'padding',
  'paddingTop',
  'paddingRight',
  'paddingBottom',
  'paddingLeft',
  'borderWidth',
  'fontSize',
  'lineHeight',
  'gap',
  'rowGap',
  'columnGap',
  'flexBasis',
  'gridTemplateColumns',
  'gridTemplateRows'
];

/** Keys that are orchestration or bookkeeping, not animated values. */
export const NON_VISUAL_VARIANT_KEYS: readonly string[] = ['transition', 'transitionEnd'];
