import { cx } from './util';

/** A small breathing status dot (good = pulsing accent-green). */
export function LiveDot({ status = 'good', className }: { status?: 'good' | 'warn' | 'bad'; className?: string }) {
  return <span className={cx('live-dot', status, className)} />;
}
