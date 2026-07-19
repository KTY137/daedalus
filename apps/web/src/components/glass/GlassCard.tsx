import type { HTMLAttributes } from 'react';
import { cx } from './util';

interface GlassCardProps extends HTMLAttributes<HTMLDivElement> {
  hoverable?: boolean;
}

/** A lighter, thinner glass tile for content nested inside a GlassPanel. */
export function GlassCard({ className, hoverable, children, ...rest }: GlassCardProps) {
  return (
    <div className={cx('glass-card', hoverable && 'hoverable', className)} {...rest}>
      {children}
    </div>
  );
}
