import type { ButtonHTMLAttributes } from 'react';
import { cx } from './util';

interface GlassButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  primary?: boolean;
}

/** Glass pill button; `primary` paints the accent-gradient variant. */
export function GlassButton({ className, primary, type, children, ...rest }: GlassButtonProps) {
  return (
    <button type={type ?? 'button'} className={cx(primary && 'primary', className)} {...rest}>
      {children}
    </button>
  );
}
