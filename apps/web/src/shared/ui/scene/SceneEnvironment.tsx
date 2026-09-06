import { useEffect, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import { useThemes } from '../theme/ThemeProvider';
import { useReducedMotionPref } from '../motion';
import { environmentImage } from './environmentImages';
import type { RoomRenderer } from './roomRenderer';
import './SceneEnvironment.css';

/**
 * The room behind the glass.
 *
 * One rendered picture or optional local GLB at the bottom of the cockpit. The
 * glass panels above it do the rest: their backdrop blur frosts the render, so
 * the picture is not decoration laid over the UI but the space the UI sits in.
 * A veil in the theme's own room colours keeps bare text readable; the Studio's
 * "Intensität" slider trades veil for picture. Pointer parallax is a few
 * percent at most, scaled by "Bewegung", and off under reduced motion.
 *
 * Purely presentational: local assets, no project state or runtime effects.
 */
export function SceneEnvironment() {
  const { theme } = useThemes();
  const reduced = useReducedMotionPref();
  const id = theme.scene?.environment;
  const src = id ? environmentImage(id) : undefined;
  const weight = Math.max(0, Math.min(1, theme.scene?.intensity ?? 0.7));
  const speed = Math.max(0, Math.min(1, theme.scene?.speed ?? 0.5));
  const element = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const renderer = useRef<RoomRenderer | undefined>(undefined);
  const interactive = theme.scene?.rendering === 'interactive';
  const exposure = Math.max(.5, Math.min(1.6, theme.scene?.exposure ?? 1));
  const [state, setState] = useState<'loading' | 'webgl' | 'fallback'>('loading');
  const controls = useRef({ speed, exposure, reduced });
  controls.current = { speed, exposure, reduced };

  useEffect(() => {
    const target = canvas.current;
    if (!interactive || !id || !target || weight === 0) return;
    let cancelled = false;
    setState('loading');
    void import('./roomRenderer').then(({ createRoomRenderer }) => {
      if (!cancelled) renderer.current = createRoomRenderer(target, id, controls.current, setState);
    }).catch(() => { if (!cancelled) setState('fallback'); });
    return () => { cancelled = true; renderer.current?.dispose(); renderer.current = undefined; };
  }, [interactive, id, weight === 0]);

  useEffect(() => { renderer.current?.update({ speed, exposure, reduced }); }, [speed, exposure, reduced]);

  useEffect(() => {
    const node = element.current;
    if (!node || !src || reduced || speed === 0 || interactive) return;
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
  }, [src, reduced, speed, interactive]);

  if (!id || !src || weight === 0) return null;
  return (
    <div
      ref={element}
      className="scene-environment"
      data-environment={id}
      data-renderer={interactive ? state : 'image'}
      aria-hidden="true"
      style={{ '--env-weight': weight, '--env-exposure': exposure } as CSSProperties}
    >
      <img src={src} alt="" decoding="async" draggable={false} />
      {interactive && <canvas key={id} ref={canvas} className="scene-environment-canvas" />}
      <span className="scene-environment-veil" />
      <span className="scene-environment-vignette" />
    </div>
  );
}
