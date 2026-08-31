/* =========================================================================
   Resolved motion — pure functions from (tier, reduced) to a framer-motion
   transition or variant set.

   Everything here is PURE and free of React and of framer-motion's runtime
   (the framer-motion import is type-only and erases at compile time). That
   is deliberate: it means the reduced-motion contract can be tested by
   running this file in node, with no DOM and no test framework. See
   motion.spec.ts / run-spec.mjs.

   ── the reduced-motion contract ─────────────────────────────────────────
   `prefers-reduced-motion: reduce` is not "turn the animations off". An
   interface that teleports between states is HARDER to follow, not easier:
   the user still has to work out what changed, they just get no help doing
   it. What the setting actually asks for is the removal of large-area
   vestibular motion — travel, scale, spin, parallax.

   So the reduced path here holds to four rules, each asserted in the spec:

     R1  No spatial keys at all. No x, y, scale, rotate. Zero displacement,
         not "less" displacement.
     R2  Opacity still animates, and the two states are still visibly
         different. The change is still perceptible as a change.
     R3  The duration is > 0 and <= the acknowledgement ceiling. Long enough
         to be seen happening; short enough that nothing is ever waiting.
     R4  Never a spring. Springs have an unbounded settle phase and exist to
         communicate mass, which is exactly the sensation being opted out of.

   Shared-layout transitions (`layoutId`) are switched off by the components
   in reduced mode — a layoutId animation IS spatial travel by definition.
   The state change is carried instead by cross-fading the highlight into
   its new home, which still answers "the active thing is now over there".
   ========================================================================= */

import type { Transition, Variants } from 'framer-motion';
import {
  DISTANCE,
  EASE,
  LAYOUT_TRIGGERING_PROPS,
  NON_VISUAL_VARIANT_KEYS,
  SCALE,
  SPRING,
  sec,
  staggerFor
} from './tokens';

/** The four tiers a component may ask for. `ack` is the acknowledgement
 *  tier; `move`, `enter` and `exit` are all state-change tiers. */
export type Tier = 'ack' | 'move' | 'enter' | 'exit';

export function transitionFor(tier: Tier, reduced: boolean): Transition {
  // R3 + R4: one shape for every tier under reduced motion — a short,
  // spring-free opacity tween.
  if (reduced) return { duration: sec('ack'), ease: EASE.ack };

  switch (tier) {
    case 'ack':
      return { duration: sec('ack'), ease: EASE.ack };
    case 'move':
      return { ...SPRING.instrument };
    case 'enter':
      return { ...SPRING.surface };
    case 'exit':
      return { duration: sec('exit'), ease: EASE.depart };
  }
}

/* ── surfaces ──────────────────────────────────────────────────────────── */

/** A sheet / panel arriving over the spine. Rises and settles from slightly
 *  small, so it reads as coming toward you rather than sliding past. */
export function surfaceVariants(reduced: boolean): Variants {
  if (reduced) {
    return {
      closed: { opacity: 0, transition: transitionFor('exit', true) },
      open: { opacity: 1, transition: transitionFor('enter', true) }
    };
  }
  return {
    closed: {
      opacity: 0,
      y: DISTANCE.travel,
      scale: SCALE.settle,
      transition: transitionFor('exit', false)
    },
    open: {
      opacity: 1,
      y: 0,
      scale: 1,
      transition: transitionFor('enter', false)
    }
  };
}

/** The scrim behind a sheet. Opacity only in both modes — a full-viewport
 *  element must never travel or scale, reduced motion or not. */
export function scrimVariants(reduced: boolean): Variants {
  return {
    closed: { opacity: 0, transition: transitionFor('exit', reduced) },
    open: { opacity: 1, transition: transitionFor('enter', reduced) }
  };
}

/** A drawer clearing the right edge. */
export function drawerVariants(reduced: boolean): Variants {
  if (reduced) {
    return {
      closed: { opacity: 0, transition: transitionFor('exit', true) },
      open: { opacity: 1, transition: transitionFor('enter', true) }
    };
  }
  return {
    closed: { opacity: 0, x: DISTANCE.drawer, transition: transitionFor('exit', false) },
    open: { opacity: 1, x: 0, transition: transitionFor('enter', false) }
  };
}

/* ── content ───────────────────────────────────────────────────────────── */

/** A generic in-place reveal for a tile that has just come into existence.
 *  `distance` defaults to `nudge` so a nested reveal stays smaller than its
 *  parent's and reads as depth rather than as a competing animation. */
export function revealVariants(reduced: boolean, distance: number = DISTANCE.nudge): Variants {
  if (reduced) {
    return {
      hidden: { opacity: 0 },
      visible: { opacity: 1, transition: transitionFor('enter', true) }
    };
  }
  return {
    hidden: { opacity: 0, y: distance },
    visible: { opacity: 1, y: 0, transition: transitionFor('enter', false) }
  };
}

/** A transcript bubble arriving. It enters from its own side of the spine —
 *  the user's from the right, Ikarus's from the left — so the transcript
 *  reads as two voices rather than one feed. */
export function bubbleVariants(reduced: boolean, side: 'left' | 'right'): Variants {
  if (reduced) {
    return {
      hidden: { opacity: 0 },
      visible: { opacity: 1, transition: transitionFor('enter', true) }
    };
  }
  return {
    hidden: {
      opacity: 0,
      y: DISTANCE.rise,
      x: side === 'right' ? DISTANCE.nudge : -DISTANCE.nudge,
      scale: SCALE.settle
    },
    visible: {
      opacity: 1,
      y: 0,
      x: 0,
      scale: 1,
      transition: transitionFor('move', false)
    }
  };
}

/* ── orchestration ─────────────────────────────────────────────────────── */

/** Container that reveals its motion children in sequence. Carries no visual
 *  properties of its own — if the container faded too, every child would
 *  fade twice. */
export function listVariants(reduced: boolean, count = 6): Variants {
  const stagger = reduced ? 0 : staggerFor(count);
  return {
    hidden: {},
    visible: {
      transition: { staggerChildren: stagger, delayChildren: reduced ? 0 : stagger }
    }
  };
}

/** A child of `listVariants`. */
export function listItemVariants(reduced: boolean, distance: number = DISTANCE.rise): Variants {
  return revealVariants(reduced, distance);
}

/* ── acknowledgements that live in React state ─────────────────────────── */

/** The composer's focus ring: collapses onto the field rather than blinking
 *  on. Under reduced motion it fades with no scale. */
export function ringVariants(reduced: boolean): Variants {
  if (reduced) {
    return {
      rest: { opacity: 0, transition: transitionFor('ack', true) },
      focus: { opacity: 1, transition: transitionFor('ack', true) }
    };
  }
  return {
    rest: { opacity: 0, scale: SCALE.ring, transition: transitionFor('ack', false) },
    focus: { opacity: 1, scale: 1, transition: transitionFor('ack', false) }
  };
}

/** The send button, disarmed (nothing to send) vs armed (there is). */
export function armVariants(reduced: boolean): Variants {
  if (reduced) {
    return {
      idle: { opacity: 0.55, transition: transitionFor('ack', true) },
      armed: { opacity: 1, transition: transitionFor('ack', true) }
    };
  }
  return {
    idle: { opacity: 0.55, scale: 0.94, transition: transitionFor('ack', false) },
    armed: { opacity: 1, scale: 1, transition: transitionFor('ack', false) }
  };
}

/** Press feedback for a control whose transform framer-motion has taken over
 *  (once an inline transform exists, the CSS `button:active` rule can no
 *  longer win, so the press has to be re-expressed here). Returns undefined
 *  under reduced motion, which is a valid `whileTap` — no press scale. */
export function pressProps(reduced: boolean): { scale: number } | undefined {
  return reduced ? undefined : { scale: SCALE.press };
}

/** Hover lift, for the same reason as `pressProps`: a tile that framer-motion
 *  has given an inline transform can no longer be lifted by a CSS `:hover`
 *  rule. Undefined under reduced motion — the tile still lights up, it just
 *  does not move. */
export function liftProps(reduced: boolean): { y: number } | undefined {
  return reduced ? undefined : { y: -DISTANCE.hairline };
}

/* ── the audit ─────────────────────────────────────────────────────────── */

export interface VariantAudit {
  /** Layout-triggering properties found. Any entry here is a failure. */
  layoutProps: string[];
  /** Every animated property key seen, deduped. */
  animatedProps: string[];
  /** True if any transition in the set is a spring. */
  usesSpring: boolean;
  /** Longest explicit tween duration in the set, in ms. -1 if none. */
  maxDurationMs: number;
}

/**
 * Walk a variant set and report what it actually animates. This is what makes
 * "we only animate transform and opacity" a checkable claim instead of a
 * comment. Used by motion.spec.ts across every factory above.
 */
export function auditVariants(variants: Variants): VariantAudit {
  const animated = new Set<string>();
  const layout: string[] = [];
  let usesSpring = false;
  let maxDuration = -1;

  for (const state of Object.values(variants)) {
    if (!state || typeof state !== 'object') continue;
    const target = state as Record<string, unknown>;

    for (const [key, value] of Object.entries(target)) {
      if (NON_VISUAL_VARIANT_KEYS.includes(key)) continue;
      animated.add(key);
      if (LAYOUT_TRIGGERING_PROPS.includes(key)) layout.push(key);
      void value;
    }

    const transition = target.transition as Record<string, unknown> | undefined;
    if (transition && typeof transition === 'object') {
      if (transition.type === 'spring') usesSpring = true;
      if (typeof transition.duration === 'number') {
        maxDuration = Math.max(maxDuration, transition.duration * 1000);
      }
    }
  }

  return {
    layoutProps: layout,
    animatedProps: [...animated].sort(),
    usesSpring,
    maxDurationMs: maxDuration
  };
}

/** Same audit, for a bare transition object. */
export function auditTransition(transition: Transition): { isSpring: boolean; durationMs: number } {
  const t = transition as Record<string, unknown>;
  return {
    isSpring: t.type === 'spring',
    durationMs: typeof t.duration === 'number' ? t.duration * 1000 : -1
  };
}
