import { Check, RotateCcw, Sparkles, X } from 'lucide-react';
import type { Theme } from '../hooks/useTheme';
import {
  GLASS_ACCENTS,
  GLASS_SCENES,
  GLASS_SCENE_LIST,
  useGlassTheme,
  type GlassSettings
} from '../hooks/useGlassTheme';
import { cx } from './glass/util';

type SliderKey = 'blur' | 'sat' | 'diff' | 'alpha' | 'rad';

const SLIDERS: Array<{ key: SliderKey; label: string; min: number; max: number; step: number; suffix: string }> = [
  { key: 'blur', label: 'Blur', min: 0, max: 48, step: 1, suffix: 'px' },
  { key: 'sat', label: 'Vibrancy', min: 100, max: 260, step: 5, suffix: '%' },
  { key: 'diff', label: 'Diffraction', min: 0, max: 60, step: 1, suffix: '%' },
  { key: 'alpha', label: 'Frost / opacity', min: 20, max: 95, step: 1, suffix: '%' },
  { key: 'rad', label: 'Corner radius', min: 6, max: 34, step: 1, suffix: 'px' }
];

/**
 * Live liquid-glass theme editor. Slides in from the right; every control
 * writes CSS custom properties on <html> immediately (via useGlassTheme) and
 * persists to localStorage. Ported from the mock's <script>.
 */
export function ThemeEditor({ open, onClose, theme }: { open: boolean; onClose: () => void; theme: Theme }) {
  const { settings, update, reset } = useGlassTheme(theme);

  return (
    <aside className={cx('editor', 'glass', open && 'open')} aria-hidden={!open}>
      <div className="eh">
        <h2>
          <Sparkles size={16} /> Glass editor
        </h2>
        <button type="button" className="iconbtn" onClick={onClose} aria-label="Close editor">
          <X size={15} />
        </button>
      </div>

      <div className="ebody">
        <div className="egrp-title">Material</div>
        {SLIDERS.map((slider) => (
          <div className="ctrl" key={slider.key}>
            <div className="lab">
              <span>{slider.label}</span>
              <span className="val">
                {settings[slider.key]}
                {slider.suffix}
              </span>
            </div>
            <input
              type="range"
              min={slider.min}
              max={slider.max}
              step={slider.step}
              value={settings[slider.key]}
              onChange={(event) => update({ [slider.key]: Number(event.target.value) } as Partial<GlassSettings>)}
            />
          </div>
        ))}

        <div className="egrp-title">Accent</div>
        <div className="swatches">
          {GLASS_ACCENTS.map((color) => (
            <button
              key={color || 'default'}
              type="button"
              className={cx('sw', settings.accent === color && 'on')}
              title={color || 'default'}
              style={{ background: color || 'linear-gradient(135deg,#6aa8ff,#c15fff)' }}
              onClick={() => update({ accent: color })}
            />
          ))}
        </div>

        <div className="egrp-title">Background scene</div>
        <div className="scenes">
          {GLASS_SCENE_LIST.map(([key, label]) => {
            const tone = key ? (theme === 'dark' ? GLASS_SCENES[key].d : GLASS_SCENES[key].l) : null;
            const preview = tone
              ? `radial-gradient(circle at 25% 20%,${tone.a},transparent 60%),radial-gradient(circle at 80% 30%,${tone.b},transparent 55%),linear-gradient(160deg,${tone.s1},${tone.s2})`
              : 'radial-gradient(circle at 25% 20%,var(--mesh-a),transparent 60%),radial-gradient(circle at 80% 30%,var(--mesh-b),transparent 55%),linear-gradient(160deg,var(--scene-1),var(--scene-2))';
            return (
              <button
                key={key || 'default'}
                type="button"
                className={cx('scene-b', settings.scene === key && 'on')}
                onClick={() => update({ scene: key })}
              >
                <span className="prev" style={{ background: preview }} />
                <span>{label}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="efoot">
        <button type="button" onClick={reset}>
          <RotateCcw size={14} /> Reset
        </button>
        <button type="button" className="primary" onClick={onClose}>
          <Check size={14} /> Done
        </button>
      </div>
    </aside>
  );
}
