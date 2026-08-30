// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-License-Identifier: Apache-2.0

import { useMemo } from 'react';
import type { ReactNode } from 'react';
import { motion } from 'framer-motion';
import { ChevronLeft } from 'lucide-react';
import { cx } from './util';
import { scrimVariants, surfaceVariants, useReducedMotionPref } from '../../motion';

interface GlassSheetProps {
  open: boolean;
  title: ReactNode;
  subtitle?: ReactNode;
  onClose: () => void;
  children: ReactNode;
}

/**
 * A glass overlay that slides up over the chat spine (scrim + panel).
 *
 * The sheet stays MOUNTED when closed — it is not wrapped in AnimatePresence.
 * That is deliberate and load-bearing: its children are the heavy views
 * (the sigma graph, the code map), and unmounting them on close would throw
 * away their state and pay a full re-init on every open. The `open` class is
 * still applied so the shipped `pointer-events` and `aria-hidden` rules keep
 * working exactly as before; only transform and opacity change hands.
 *
 * Motion: the panel rises 24px and settles from 98.5% on the `surface`
 * spring, so it reads as coming toward you. It leaves faster than it arrives
 * (220ms, accelerating) because a dismissal that lingers feels like lag.
 * Under reduced motion both become a 140ms cross-fade with no travel and no
 * scale — the state change is still visible, it just does not move.
 */
export function GlassSheet({ open, title, subtitle, onClose, children }: GlassSheetProps) {
  const reduced = useReducedMotionPref();
  const sheet = useMemo(() => surfaceVariants(reduced), [reduced]);
  const scrim = useMemo(() => scrimVariants(reduced), [reduced]);
  const state = open ? 'open' : 'closed';

  return (
    <>
      <motion.div
        className={cx('scrim', open && 'open')}
        data-motion="scrim"
        onClick={onClose}
        variants={scrim}
        initial={false}
        animate={state}
      />
      <motion.div
        className={cx('sheet', 'glass', open && 'open')}
        data-motion="sheet"
        role="dialog"
        aria-modal="true"
        aria-hidden={!open}
        variants={sheet}
        initial={false}
        animate={state}
      >
        <div className="sheet-head">
          <button type="button" className="iconbtn" onClick={onClose} aria-label="Back to chat">
            <ChevronLeft size={16} />
          </button>
          <div>
            <h2>{title}</h2>
            {subtitle ? <p>{subtitle}</p> : null}
          </div>
        </div>
        <div className="sheet-body">{children}</div>
      </motion.div>
    </>
  );
}
