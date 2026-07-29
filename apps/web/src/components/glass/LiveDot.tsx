import { cx } from './util';
// LiveDot needs the motion stylesheet but none of the motion runtime.
import '../../motion/motion.css';

/**
 * A small breathing status dot (good = pulsing accent-green).
 *
 * The pulse itself stays in CSS — it is an ambient loop with no React state
 * behind it, and a declarative @keyframes costs the main thread nothing per
 * frame where a JS loop would. What `data-motion` changes is *what* it
 * animates: motion.css replaces the shipped `breathe` keyframe (which
 * animated `box-shadow` spread, a paint property, forever, on every dot on
 * screen) with a pseudo-element that scales and fades. Same look, transform
 * and opacity only.
 */
export function LiveDot({ status = 'good', className }: { status?: 'good' | 'warn' | 'bad'; className?: string }) {
  return <span className={cx('live-dot', status, className)} data-motion="dot" />;
}
