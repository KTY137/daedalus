import type { ReactNode } from 'react';
import { cx } from './util';

/** The 64px icon rail on the far left. */
export function Dock({ children, className }: { children: ReactNode; className?: string }) {
  return <nav className={cx('dock', 'glass', className)}>{children}</nav>;
}

export function DockGroup({ children }: { children: ReactNode }) {
  return <div className="grp">{children}</div>;
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
}

export function DockItem({ icon, label, active, badge, onClick }: DockItemProps) {
  return (
    <button
      type="button"
      className={cx('dockbtn', active && 'active')}
      onClick={onClick}
      title={label}
      aria-label={label}
      aria-pressed={active}
    >
      {icon}
      <span className="tip">{label}</span>
      {badge ? <span className="dot" /> : null}
    </button>
  );
}
