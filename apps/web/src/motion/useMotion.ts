// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useMemo } from 'react';
import { useReducedMotion } from 'framer-motion';
import type { Transition } from 'framer-motion';
import { DURATION_MS, EASE } from './tokens';
import { transitionFor, type Tier } from './variants';

/**
 * The one place a component asks "am I allowed to move?".
 *
 * framer-motion animates in JS, so the global
 * `@media (prefers-reduced-motion: reduce)` rule in styles.css — which zeroes
 * CSS transition and animation durations — has no effect on it whatsoever.
 * Every motion-driven primitive in the glass set therefore reads this hook
 * and picks a variant set through the pure resolvers in variants.ts.
 *
 * Returns `false` rather than `null` before the media query resolves, so a
 * component never has to handle a third state.
 */
export function useReducedMotionPref(): boolean {
  const reduced = useReducedMotion();
  useEffect(checkCssTokenParity, []);
  return reduced ?? false;
}

/** Convenience: a memoised transition for a tier, already reduced-aware. */
export function useTransition(tier: Tier): Transition {
  const reduced = useReducedMotionPref();
  return useMemo(() => transitionFor(tier, reduced), [tier, reduced]);
}

/* ── CSS / JS token parity ───────────────────────────────────────────────
   Half of this motion system is CSS (hover, press, focus — the
   acknowledgements a pseudo-class already expresses) and half is JS (state
   changes, which need orchestration). Two halves means two places a number
   can live, which is exactly how a design system rots.

   styles.css is owned by another lane, so tokens.ts cannot write into it.
   What it can do is check, once, at startup, that the two halves still agree
   — and say so loudly if they ever stop. Cost: a single getComputedStyle on
   first mount of the first motion-driven component. */

let parityChecked = false;

function checkCssTokenParity(): void {
  if (parityChecked) return;
  parityChecked = true;
  if (typeof document === 'undefined' || typeof getComputedStyle !== 'function') return;

  try {
    const css = getComputedStyle(document.documentElement);
    const drift: string[] = [];

    const pairs: Array<[string, number]> = [
      ['--dur-fast', DURATION_MS.ack],
      ['--dur', DURATION_MS.move],
      ['--dur-slow', DURATION_MS.ambient]
    ];
    for (const [prop, expected] of pairs) {
      const raw = css.getPropertyValue(prop).trim();
      if (!raw) continue;
      const ms = raw.endsWith('ms') ? parseFloat(raw) : parseFloat(raw) * 1000;
      if (Number.isFinite(ms) && Math.abs(ms - expected) > 0.5) {
        drift.push(`${prop}: css ${ms}ms vs tokens ${expected}ms`);
      }
    }

    const rawEase = css.getPropertyValue('--ease').trim();
    const nums = rawEase.match(/-?\d*\.?\d+/g);
    if (nums && nums.length === 4) {
      const cssEase = nums.map(Number);
      const drifted = cssEase.some((n, i) => Math.abs(n - EASE.glass[i]) > 0.001);
      if (drifted) drift.push(`--ease: css ${rawEase} vs tokens cubic-bezier(${EASE.glass.join(', ')})`);
    }

    if (drift.length > 0) {
      // eslint-disable-next-line no-console
      console.warn(
        '[motion] CSS and JS motion tokens have drifted apart. ' +
          'Reconcile styles.css with src/motion/tokens.ts:\n  ' +
          drift.join('\n  ')
      );
    }
  } catch {
    /* a hostile or headless environment — parity is a dev aid, never a crash */
  }
}
