import { useEffect, useRef } from 'react';
import type { CSSProperties } from 'react';
import { useThemes } from '../theme/ThemeProvider';
import { useReducedMotionPref } from '../motion';
import { environmentImage } from './environmentImages';
import './SceneEnvironment.css';

/**
 * The room behind the glass.
 *
 * One full-bleed picture at the bottom of the cockpit's stacking context. The
 * glass panels above it do the rest: their backdrop blur frosts the render, so
 * the picture is not decoration laid over the UI but the space the UI sits in.
 * A veil in the theme's own room colours keeps bare text readable; the Studio's
 * "Intensität" slider trades veil for picture. Pointer parallax is a few
 * percent at most, scaled by "Bewegung", and off under reduced motion.
 *
 * Purely presentational: no project state, no network, no effect controls.
 */
export function SceneEnvironment() {
  const { theme } = useThemes();
  const reduced = useReducedMotionPref();
  const id = theme.scene?.environment;
  const src = id ? environmentImage(id) : undefined;
  const weight = Math.max(0, Math.min(1, theme.scene?.intensity ?? 0.7));
  const speed = Math.max(0, Math.min(1, theme.scene?.speed ?? 0.5));
  const element = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = element.current;
    if (!node || !src || reduced || speed === 0) return;
    let frame = 0;
    let x = 0;
    let y = 0;
    const paint = () => {
      frame = 0;
      node.style.setProperty('--env-x', `${(-x * speed * 1.6).toFixed(3)}%`);
      node.style.setProperty('--env-y', `${(-y * speed * 1.1).toFixed(3)}%`);
    };
    const move = (event: PointerEvent) => {
      x = event.clientX / innerWidth - 0.5;
      y = event.clientY / innerHeight - 0.5;
      if (!frame) frame = requestAnimationFrame(paint);
    };
    window.addEventListener('pointermove', move, { passive: true });
    return () => {
      window.removeEventListener('pointermove', move);
      cancelAnimationFrame(frame);
      node.style.removeProperty('--env-x');
      node.style.removeProperty('--env-y');
    };
  }, [src, reduced, speed]);

  if (!id || !src || weight === 0) return null;
  return (
    <div
      ref={element}
      className="scene-environment"
      data-environment={id}
      aria-hidden="true"
      style={{ '--env-weight': weight } as CSSProperties}
    >
      <img src={src} alt="" decoding="async" draggable={false} />
      <span className="scene-environment-veil" />
      <span className="scene-environment-vignette" />
    </div>
  );
}
