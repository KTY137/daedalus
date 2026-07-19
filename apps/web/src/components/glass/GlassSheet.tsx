import type { ReactNode } from 'react';
import { ChevronLeft } from 'lucide-react';
import { cx } from './util';

interface GlassSheetProps {
  open: boolean;
  title: ReactNode;
  subtitle?: ReactNode;
  onClose: () => void;
  children: ReactNode;
}

/** A glass overlay that slides up over the chat spine (scrim + panel). */
export function GlassSheet({ open, title, subtitle, onClose, children }: GlassSheetProps) {
  return (
    <>
      <div className={cx('scrim', open && 'open')} onClick={onClose} />
      <div className={cx('sheet', 'glass', open && 'open')} role="dialog" aria-modal="true" aria-hidden={!open}>
        <div className="sheet-head">
          <button type="button" className="iconbtn" onClick={onClose} aria-label="Back to chat">
            <ChevronLeft size={16} />
          </button>
          <div>
            <h2>{title}</h2>
            {subtitle ? <p>{subtitle}</p> : null}
          </div>
        </div>
        <div className="sheet-body">{children}</div>
      </div>
    </>
  );
}
