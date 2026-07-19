import { cx } from './util';

interface SegmentedControlProps {
  options: string[];
  value?: string;
  onChange: (value: string) => void;
  className?: string;
}

/** iOS-style segmented control over the shipped `.segmented` styles. */
export function SegmentedControl({ options, value, onChange, className }: SegmentedControlProps) {
  return (
    <div className={cx('segmented', className)}>
      {options.map((option) => (
        <button
          key={option}
          type="button"
          className={option === value ? 'active' : ''}
          onClick={() => onChange(option)}
        >
          {option}
        </button>
      ))}
    </div>
  );
}
