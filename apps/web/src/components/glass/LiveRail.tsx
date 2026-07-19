import type { ReactNode } from 'react';
import { cx } from './util';

/** The collapsible right-hand column of live monitoring cards. */
export function LiveRail({ children, className }: { children: ReactNode; className?: string }) {
  return <aside className={cx('rail', className)}>{children}</aside>;
}

interface RailCardProps {
  title: ReactNode;
  icon?: ReactNode;
  badge?: ReactNode;
  children?: ReactNode;
  className?: string;
}

export function RailCard({ title, icon, badge, children, className }: RailCardProps) {
  return (
    <div className={cx('railcard', 'glass', className)}>
      <div className="h">
        <span className="t">
          {icon}
          {title}
        </span>
        {badge}
      </div>
      {children}
    </div>
  );
}
