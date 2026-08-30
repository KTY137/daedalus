// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-License-Identifier: Apache-2.0

import { useId, useMemo } from 'react';
import { motion } from 'framer-motion';
import { cx } from './util';
import { pressProps, transitionFor, useReducedMotionPref } from '../../motion';

interface SegmentedControlProps {
  options: string[];
  value?: string;
  onChange: (value: string) => void;
  className?: string;
}

/**
 * iOS-style segmented control over the shipped `.segmented` styles.
 *
 * The selection is ONE element that travels, not two that cross-fade. The
 * thumb carries a `layoutId` scoped to this control instance, so when the
 * value changes framer-motion measures where the highlight was and where it
 * is going and animates the difference with a transform. That is the whole
 * distinction the brief asks for: the highlight genuinely persists across
 * states, so it moves; it does not blink out on the left and back in on the
 * right.
 *
 * `.segmented` is a `repeat(N, 1fr)` grid, so every segment is the same
 * width and the shared-layout animation is pure translation — no scale
 * correction, so nothing inside the thumb can distort.
 *
 * Reduced motion: `layoutId` is dropped entirely, because a shared-layout
 * animation IS travel by definition. The thumb instead fades into its new
 * home over 140ms, which still answers "the selection is now here" without
 * moving anything across the screen.
 */
export function SegmentedControl({ options, value, onChange, className }: SegmentedControlProps) {
  const reduced = useReducedMotionPref();
  const instance = useId();
  const move = useMemo(() => transitionFor('move', reduced), [reduced]);
  const ack = useMemo(() => transitionFor('ack', reduced), [reduced]);
  const press = pressProps(reduced);

  return (
    <div className={cx('segmented', className)} data-motion="segmented" role="group">
      {options.map((option) => {
        const active = option === value;
        return (
          <motion.button
            key={option}
            type="button"
            className={active ? 'active' : ''}
            data-motion="segment"
            aria-pressed={active}
            whileTap={press}
            transition={ack}
            onClick={() => onChange(option)}
          >
            {active &&
              (reduced ? (
                <motion.span
                  className="motion-thumb"
                  aria-hidden="true"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={ack}
                />
              ) : (
                <motion.span
                  className="motion-thumb"
                  aria-hidden="true"
                  layoutId={`segmented-thumb-${instance}`}
                  transition={move}
                />
              ))}
            <span className="seg-label">{option}</span>
          </motion.button>
        );
      })}
    </div>
  );
}
