import { Children, useMemo } from 'react';
import type { ReactNode } from 'react';
import { motion } from 'framer-motion';
import { cx } from './util';
import { listItemVariants, listVariants, useReducedMotionPref } from '../../motion';

/**
 * The collapsible right-hand column of live monitoring cards.
 *
 * The rail reveals its cards in sequence when it first mounts, tightening the
 * per-card offset so the whole column is settled inside 240ms regardless of
 * how many cards it carries.
 *
 * NOT animated here: the collapse itself. App.tsx currently collapses the
 * rail by switching the shell's grid track to `0` and setting
 * `display: none`, and `display: none` cannot be transitioned — the element
 * is simply gone. Animating it needs a prop from the view layer; the
 * interface is described in the report rather than faked with a crossfade.
 */
export function LiveRail({ children, className }: { children: ReactNode; className?: string }) {
  const reduced = useReducedMotionPref();
  const count = Children.count(children);
  const variants = useMemo(() => listVariants(reduced, count), [reduced, count]);

  return (
    <motion.aside
      className={cx('rail', className)}
      data-motion="rail"
      variants={variants}
      initial="hidden"
      animate="visible"
    >
      {children}
    </motion.aside>
  );
}

interface RailCardProps {
  title: ReactNode;
  icon?: ReactNode;
  badge?: ReactNode;
  children?: ReactNode;
  className?: string;
}

export function RailCard({ title, icon, badge, children, className }: RailCardProps) {
  const reduced = useReducedMotionPref();
  const variants = useMemo(() => listItemVariants(reduced), [reduced]);

  return (
    <motion.div className={cx('railcard', 'glass', className)} data-motion="rail-card" variants={variants}>
      <div className="h">
        <span className="t">
          {icon}
          {title}
        </span>
        {badge}
      </div>
      {children}
    </motion.div>
  );
}
