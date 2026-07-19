import type { ReactNode } from 'react';
import { Sparkles } from 'lucide-react';
import { cx } from './util';

/** One transcript bubble. `ik` = Ikarus (left), `me` = the user (right). */
export function ChatBubble({ role, avatar, children }: { role: 'ik' | 'me'; avatar?: ReactNode; children: ReactNode }) {
  return (
    <div className={cx('msg', role)}>
      <span className="ava">{avatar ?? (role === 'me' ? 'K' : <Sparkles size={14} />)}</span>
      <div className="b">{children}</div>
    </div>
  );
}
