import { useMemo } from 'react';
import { motion } from 'framer-motion';
import { revealVariants, useReducedMotionPref } from '@/shared/ui/motion';
import type { CommandSpec } from './commands';

/**
 * The `/` menu. It opens above the composer the moment the draft is a slash
 * word, lists the commands that match, and says what each one does — because
 * a command whose effect is not stated is a guess, and this surface does not
 * ask people to guess what will happen when they press Enter.
 *
 * Keyboard handling lives on the textarea (Conversation.tsx) so focus never
 * leaves the box: ↑↓ move, Enter or Tab take the highlighted row, Esc closes.
 */

export interface CommandMenuProps {
  id: string;
  commands: CommandSpec[];
  activeIndex: number;
  onActive: (index: number) => void;
  onPick: (command: CommandSpec) => void;
  /** a hint about the command the draft names but has not completed */
  hint?: string;
}

export function CommandMenu({ id, commands, activeIndex, onActive, onPick, hint }: CommandMenuProps) {
  const reduced = useReducedMotionPref();
  const reveal = useMemo(() => revealVariants(reduced), [reduced]);
  return (
    <motion.div className="cmd-menu" data-motion="menu" variants={reveal} initial="hidden" animate="visible" exit="hidden">
      {commands.length > 0 ? (
        <ul id={id} className="cmd-list" role="listbox" aria-label="Befehle">
          {commands.map((c, i) => (
            <li
              key={c.name}
              id={`${id}-${c.name}`}
              role="option"
              aria-selected={i === activeIndex}
              className={i === activeIndex ? 'cmd-opt on' : 'cmd-opt'}
              onMouseEnter={() => onActive(i)}
              onMouseDown={(e) => {
                // mousedown, not click: the textarea must keep focus.
                e.preventDefault();
                onPick(c);
              }}
            >
              <span className="cmd-name">
                /{c.name}
                {c.arg && <span className="cmd-arg"> {c.arg}</span>}
              </span>
              <span className="cmd-summary">{c.summary}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="cmd-none">Kein Befehl passt. Enter sendet die Zeile so, wie sie ist.</p>
      )}
      {hint && <p className="cmd-hint">{hint}</p>}
    </motion.div>
  );
}
