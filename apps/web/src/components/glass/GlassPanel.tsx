import type { HTMLAttributes } from 'react';
import { cx } from './util';

/**
 * The base liquid-glass surface: backdrop blur + saturate, 1px light edge and
 * the iridescent diffraction ring (both live-tunable from the Theme editor).
 * Wraps the `.glass` class shipped in styles.css.
 */
export function GlassPanel({ className, children, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cx('glass', className)} {...rest}>
      {children}
    </div>
  );
}
