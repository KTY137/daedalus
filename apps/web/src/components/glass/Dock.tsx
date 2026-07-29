import { createContext, useContext, useId, useMemo } from 'react';
import type { ReactNode } from 'react';
import { motion } from 'framer-motion';
import { cx } from './util';
import {
  DISTANCE,
  listItemVariants,
  listVariants,
  pressProps,
  transitionFor,
  useReducedMotionPref
} from '../../motion';

/**
 * The 64px icon rail on the far left.
 *
 * The dock reveals its items in sequence on first mount — the one moment in
 * the app where a staggered entrance is honest, because the instrument is
 * genuinely coming up. The stagger tightens automatically as items are added
 * (see `staggerFor`) so the whole reveal never runs past 240ms.
 */
export function Dock({ children, className }: { children: ReactNode; className?: string }) {
  const reduced = useReducedMotionPref();
  const variants = useMemo(() => listVariants(reduced, 8), [reduced]);
  return (
    <motion.nav
      className={cx('dock', 'glass', className)}
      data-motion="dock"
      variants={variants}
      initial="hidden"
      animate="visible"
    >
      {children}
    </motion.nav>
  );
}

/**
 * A dock section. Each group owns its own travelling highlight, because
 * "active" is scoped to a group: the top group tracks which view is showing,
 * the bottom group tracks whether the theme editor is open, and both can be
 * active at the same time. One shared `layoutId` across the whole dock would
 * mean two elements claiming the same shared-layout identity, which
 * framer-motion resolves by picking one and jumping.
 */
const DockGroupContext = createContext<string | null>(null);

export function DockGroup({ children, className }: { children: ReactNode; className?: string }) {
  const reduced = useReducedMotionPref();
  const groupId = useId();
  const variants = useMemo(() => listVariants(reduced, 8), [reduced]);
  return (
    <DockGroupContext.Provider value={groupId}>
      <motion.div className={cx('grp', className)} data-motion="dock-group" variants={variants}>
        {children}
      </motion.div>
    </DockGroupContext.Provider>
  );
}

export function DockSpacer() {
  return <div className="sp" />;
}

interface DockItemProps {
  icon: ReactNode;
  label: string;
  active?: boolean;
  badge?: boolean;
  onClick?: () => void;
  /** Extra class for a view lane that wants to mark a subset of the dock
   *  (spaces vs tool sheets, say). Note that the motion pill owns
   *  background / border-color / box-shadow on `.dockbtn.active` — decorate
   *  through a pseudo-element rather than those three. */
  className?: string;
}

/**
 * One dock button.
 *
 * The active surface is a real element (`.motion-pill`) rather than a class
 * on the button, so switching views slides the highlight from the old button
 * to the new one instead of repainting it in place. motion.css strips the
 * background, border and shadow from `.dockbtn.active` so the two do not
 * both paint; the accent *colour* stays in CSS, where it is a cheap
 * acknowledgement.
 *
 * The press scale also moves here. That is not a preference: an entrance
 * animation leaves an inline transform on the button, and an inline transform
 * outranks the stylesheet, so `button:active { transform: scale(.97) }` would
 * silently stop working. Anything whose transform framer-motion touches has
 * to have its press feedback re-expressed in framer-motion.
 */
export function DockItem({ icon, label, active, badge, onClick, className }: DockItemProps) {
  const reduced = useReducedMotionPref();
  const groupId = useContext(DockGroupContext) ?? 'root';
  const item = useMemo(() => listItemVariants(reduced, DISTANCE.nudge), [reduced]);
  const move = useMemo(() => transitionFor('move', reduced), [reduced]);
  const ack = useMemo(() => transitionFor('ack', reduced), [reduced]);

  return (
    <motion.button
      type="button"
      className={cx('dockbtn', active && 'active', className)}
      data-motion="dock-item"
      onClick={onClick}
      title={label}
      aria-label={label}
      aria-pressed={active}
      variants={item}
      whileTap={pressProps(reduced)}
      transition={ack}
    >
      {active &&
        (reduced ? (
          <motion.span
            className="motion-pill"
            aria-hidden="true"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={ack}
          />
        ) : (
          <motion.span
            className="motion-pill"
            aria-hidden="true"
            layoutId={`dock-pill-${groupId}`}
            transition={move}
          />
        ))}
      {icon}
      <span className="tip">{label}</span>
      {badge ? <span className="dot" /> : null}
    </motion.button>
  );
}
