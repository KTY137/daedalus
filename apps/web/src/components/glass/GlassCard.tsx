// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-License-Identifier: Apache-2.0

import { useMemo } from 'react';
import type { HTMLAttributes } from 'react';
import { motion } from 'framer-motion';
import { cx } from './util';
import {
  DISTANCE,
  liftProps,
  revealVariants,
  transitionFor,
  useReducedMotionPref,
  type MotionSafe
} from '../../motion';

interface GlassCardProps extends MotionSafe<HTMLAttributes<HTMLDivElement>> {
  hoverable?: boolean;
  /** Animate in on mount. On by default: in this app a GlassCard is a tile
   *  that just came into existence (a drafted network, a queued task), and
   *  its arrival IS the state change. */
  reveal?: boolean;
}

/**
 * A lighter, thinner glass tile for content nested inside a GlassPanel.
 *
 * Its reveal deliberately travels less than the surface that carries it (the
 * `nudge` token, 6px, against a chat bubble's 12px) so a card arriving inside
 * a bubble reads as depth rather than as a second animation competing with
 * the first.
 *
 * The hover lift moves from CSS to `whileHover`, not for effect but out of
 * necessity: once framer-motion has written an inline transform, the
 * stylesheet's `.glass-card:hover { transform: translateY(-1px) }` can no
 * longer win the cascade. Background and shadow stay in CSS.
 */
export function GlassCard({ className, hoverable, reveal = true, children, ...rest }: GlassCardProps) {
  const reduced = useReducedMotionPref();
  const variants = useMemo(() => revealVariants(reduced, DISTANCE.nudge), [reduced]);
  // Gesture states have no transition of their own, so without this they fall
  // back to framer-motion's built-in default spring — a number from outside
  // the system. Variant-level transitions still win, so the reveal keeps its
  // own timing; only the hover picks this up.
  const ack = useMemo(() => transitionFor('ack', reduced), [reduced]);

  return (
    <motion.div
      className={cx('glass-card', hoverable && 'hoverable', className)}
      data-motion="card"
      variants={variants}
      initial={reveal ? 'hidden' : false}
      animate="visible"
      // inert without an <AnimatePresence> above it, and free if one appears
      exit="hidden"
      transition={ack}
      whileHover={liftProps(reduced)}
      {...rest}
    >
      {children}
    </motion.div>
  );
}
