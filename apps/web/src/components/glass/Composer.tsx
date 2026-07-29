import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { Send } from 'lucide-react';
import {
  armVariants,
  listItemVariants,
  listVariants,
  pressProps,
  ringVariants,
  transitionFor,
  useReducedMotionPref
} from '../../motion';

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

/**
 * Chat composer: suggestion chips + an auto-growing textarea + send button.
 *
 * Three pieces of motion, all in the acknowledgement tier (140ms, no spring)
 * because all three are feedback about the user's input rather than about the
 * system:
 *
 *   focus ring   collapses onto the field from 103% instead of blinking on.
 *                motion.css turns off the shipped `:focus-within` shadow so
 *                the field never wears two rings — one owner per effect.
 *   send button  travels between "nothing to send" (55% / 94%) and "armed"
 *                (100% / 100%) as the field fills, so the control tells you
 *                its state before you reach for it.
 *   chips        reveal in sequence on mount and animate out individually if
 *                the suggestion set changes, via AnimatePresence.
 *
 * Under reduced motion all three keep their opacity change and drop their
 * scale: the field still lights up, the button still arms, nothing moves.
 */
export function Composer({ value, onChange, onSend, chips, onChip, busy, placeholder, extra }: ComposerProps) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const [focused, setFocused] = useState(false);
  const reduced = useReducedMotionPref();

  const ring = useMemo(() => ringVariants(reduced), [reduced]);
  const arm = useMemo(() => armVariants(reduced), [reduced]);
  const ack = useMemo(() => transitionFor('ack', reduced), [reduced]);
  const chipList = useMemo(() => listVariants(reduced, chips?.length ?? 0), [reduced, chips]);
  const chipItem = useMemo(() => listItemVariants(reduced), [reduced]);
  const press = pressProps(reduced);

  // Auto-grow. This writes `height`, which is layout — but it happens once per
  // keystroke, not once per frame, and it is guarded so an unchanged height
  // does not schedule a style recalculation. Height is deliberately NOT
  // animated: interpolating it would put a layout pass on the compositor's
  // critical path for the duration of the transition.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = 'auto';
    const next = `${Math.min(el.scrollHeight, 120)}px`;
    if (el.style.height !== next) el.style.height = next;
  }, [value]);

  const armed = value.trim().length > 0 && !busy;

  return (
    <div className="composer" data-motion="composer">
      {chips && chips.length > 0 && (
        <motion.div className="chips" variants={chipList} initial="hidden" animate="visible">
          <AnimatePresence>
            {chips.map((chip) => (
              <motion.button
                key={chip}
                type="button"
                className="chip"
                data-motion="chip"
                variants={chipItem}
                exit="hidden"
                transition={ack}
                whileTap={press}
                onClick={() => (onChip ? onChip(chip) : onChange(chip))}
              >
                {chip}
              </motion.button>
            ))}
          </AnimatePresence>
        </motion.div>
      )}
      {extra}
      <div className="inputwrap">
        <motion.span
          className="motion-ring"
          aria-hidden="true"
          variants={ring}
          initial="rest"
          animate={focused ? 'focus' : 'rest'}
        />
        <textarea
          ref={ref}
          data-ikarus-composer
          aria-label="Ask Ikarus"
          rows={1}
          value={value}
          placeholder={placeholder ?? 'Ask the OS — build an app, route a task, distill code…'}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              if (!busy) onSend();
            }
          }}
        />
        <motion.button
          type="button"
          className="send"
          data-motion="send"
          aria-label="Send"
          onClick={onSend}
          disabled={busy}
          variants={arm}
          initial={false}
          animate={armed ? 'armed' : 'idle'}
          transition={ack}
          whileTap={press}
        >
          <Send size={17} />
        </motion.button>
      </div>
    </div>
  );
}
