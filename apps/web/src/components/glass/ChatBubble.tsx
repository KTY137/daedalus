import { useMemo } from 'react';
import type { ReactNode } from 'react';
import { motion } from 'framer-motion';
import { Sparkles } from 'lucide-react';
import { cx } from './util';
import { bubbleVariants, useReducedMotionPref } from '../../motion';

/**
 * One transcript bubble. `ik` = Ikarus (left), `me` = the user (right).
 *
 * A bubble arrives from its own side of the spine — the user's from the
 * right, Ikarus's from the left — so the transcript reads as two voices
 * rather than one feed. It rises 12px and settles from 98.5% on the
 * `instrument` spring, which is damped just under critical: enough weight to
 * feel physical, not enough to bounce.
 *
 * This replaces the `rise` keyframe in styles.css, which motion.css switches
 * off for `.msg[data-motion]`. It has to be switched off rather than left
 * alongside: a CSS animation outranks inline styles in the cascade, and
 * `rise` uses `animation-fill-mode: both`, so its final frame would pin
 * transform and opacity permanently and the spring would never be seen.
 *
 * The bubble declares `exit="hidden"`, which does nothing today and costs
 * nothing: an exit definition is inert unless an `<AnimatePresence>` sits
 * above it, and the transcript container lives in App.tsx (owned by the view
 * lane). Wrapping the message list in AnimatePresence is the only change
 * needed to make removals animate — no prop, no API.
 *
 * Deliberately NOT here: `layout`. Shared-layout projection inside a
 * container that programmatically scrolls to the bottom on every new message
 * is a known way to make the two fight, and it would cost a measurement pass
 * per bubble per render on a list that grows without bound.
 */
export function ChatBubble({ role, avatar, children }: { role: 'ik' | 'me'; avatar?: ReactNode; children: ReactNode }) {
  const reduced = useReducedMotionPref();
  const variants = useMemo(() => bubbleVariants(reduced, role === 'me' ? 'right' : 'left'), [reduced, role]);

  return (
    <motion.div
      className={cx('msg', role)}
      data-motion="bubble"
      variants={variants}
      initial="hidden"
      animate="visible"
      exit="hidden"
    >
      <span className="ava">{avatar ?? (role === 'me' ? 'K' : <Sparkles size={14} />)}</span>
      <div className="b">{children}</div>
    </motion.div>
  );
}
