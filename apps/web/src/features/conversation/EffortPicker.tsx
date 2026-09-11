import type { EffortLevel } from '@/shared/contracts';
import { EFFORT_LABEL } from './commands';

/**
 * AUFWAND — how much the model may think on the next turn.
 *
 * The turn route has accepted `effort` for a month; nothing ever sent it.
 * This is the control, on the pre-flight rail where the other two facts
 * about the next press live. `low` is the default because it is the
 * backend's default (`_LOW_EFFORT_STYLE`), and a control must not quietly
 * change what would have happened without it.
 */

const LEVELS: EffortLevel[] = ['low', 'medium', 'high'];

export function EffortPicker({ value, onChange, disabled }: { value: EffortLevel; onChange: (level: EffortLevel) => void; disabled?: boolean }) {
  return (
    <div className="effort" role="radiogroup" aria-label="Aufwand des Modells">
      <span className="effort-role">Aufwand</span>
      {LEVELS.map((level) => (
        <button
          key={level}
          type="button"
          role="radio"
          aria-checked={value === level}
          className={value === level ? 'effort-opt on' : 'effort-opt'}
          disabled={disabled}
          onClick={() => onChange(level)}
        >
          {EFFORT_LABEL[level]}
        </button>
      ))}
    </div>
  );
}
