import { useEffect, useRef } from 'react';
import type { ReactNode } from 'react';
import { Send } from 'lucide-react';

interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  chips?: string[];
  onChip?: (chip: string) => void;
  busy?: boolean;
  placeholder?: string;
  /** Optional slot rendered above the input (e.g. an inline confirm row). */
  extra?: ReactNode;
}

/** Chat composer: suggestion chips + an auto-growing textarea + send button. */
export function Composer({ value, onChange, onSend, chips, onChip, busy, placeholder, extra }: ComposerProps) {
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
  }, [value]);

  return (
    <div className="composer">
      {chips && chips.length > 0 && (
        <div className="chips">
          {chips.map((chip) => (
            <button key={chip} type="button" className="chip" onClick={() => (onChip ? onChip(chip) : onChange(chip))}>
              {chip}
            </button>
          ))}
        </div>
      )}
      {extra}
      <div className="inputwrap">
        <textarea
          ref={ref}
          data-ikarus-composer
          aria-label="Ask Ikarus"
          rows={1}
          value={value}
          placeholder={placeholder ?? 'Ask the OS — build an app, route a task, distill code…'}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              if (!busy) onSend();
            }
          }}
        />
        <button type="button" className="send" aria-label="Send" onClick={onSend} disabled={busy}>
          <Send size={17} />
        </button>
      </div>
    </div>
  );
}
