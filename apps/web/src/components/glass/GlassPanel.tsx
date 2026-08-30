// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-License-Identifier: Apache-2.0

import { useMemo } from 'react';
import type { HTMLAttributes } from 'react';
import { motion } from 'framer-motion';
import { cx } from './util';
import { revealVariants, useReducedMotionPref, type MotionSafe } from '../../motion';

interface GlassPanelProps extends MotionSafe<HTMLAttributes<HTMLDivElement>> {
  /** Animate the surface in when it mounts. Off by default: a panel that is
   *  part of the shell has always been there, and animating it on every
   *  mount is how a UI starts to feel busy. Turn it on for a surface that
   *  genuinely just came into existence. */
  reveal?: boolean;
  /** Travel distance for the reveal, in px. Defaults to the `nudge` token. */
  revealDistance?: number;
}

/**
 * The base liquid-glass surface: backdrop blur + saturate, 1px light edge and
 * the iridescent diffraction ring (both live-tunable from the Theme editor).
 * Wraps the `.glass` class shipped in styles.css.
 */
export function GlassPanel({ className, reveal, revealDistance, children, ...rest }: GlassPanelProps) {
  const reduced = useReducedMotionPref();
  const variants = useMemo(() => revealVariants(reduced, revealDistance), [reduced, revealDistance]);

  if (!reveal) {
    return (
      <div className={cx('glass', className)} {...rest}>
        {children}
      </div>
    );
  }

  return (
    <motion.div
      className={cx('glass', className)}
      data-motion="panel"
      variants={variants}
      initial="hidden"
      animate="visible"
      {...rest}
    >
      {children}
    </motion.div>
  );
}
