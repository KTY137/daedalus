import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { DURATION_MS, EASE, useReducedMotionPref } from '../../motion';

/**
 * The camera over the stage, and the depth it looks into.
 *
 * Two things live here because they are the same idea seen twice: a pan is a
 * camera move, and parallax is what a camera move does to a scene that has
 * depth. Keeping them apart is how the previous version ended up with a flat
 * diagram that could be dragged around.
 *
 * The camera is CALM. A wheel or a drag is direct — the reader's hand is on it
 * and any easing there reads as lag. Everything else (the zoom buttons, the
 * keyboard, a reset, a new focus) GLIDES, on the house curve, for the length
 * of the motion system's `move` step. Under `prefers-reduced-motion` the glide
 * is a jump and the parallax is zero; both come from the same preference so
 * they can never disagree.
 */

export interface View {
  x: number;
  y: number;
  k: number;
}

export const MIN_ZOOM = 0.45;
export const MAX_ZOOM = 3.2;

export const HOME: View = { x: 0, y: 0, k: 1 };

/**
 * How much each plane resists the camera, as a fraction of the pan.
 *
 * The focus overtakes the camera slightly and the far field lags it; the
 * direct neighbours ARE the camera's plane and never move relative to it, so
 * the reader always has one stable reference. Values this small are deliberate
 * — the owner asked for a calm camera, and a scene where the background slides
 * a quarter of a screen is a video game, not an instrument.
 */
const PLANE_LAG: Record<0 | 1 | 2, number> = { 0: -0.09, 1: 0, 2: 0.15 };

/**
 * The offset a node on `level` gets, in STAGE units, for the current pan.
 *
 * Stage units, not screen units, because the value is added to the node's own
 * coordinates inside the camera transform. Applying it to edge endpoints as
 * well as to glyphs is what keeps a line touching both of its nodes — a
 * parallax that moves the dots but not the lines is a rendering bug wearing a
 * design word.
 */
export function planeShift(view: View, level: 0 | 1 | 2, reduced: boolean, strength = 1): { dx: number; dy: number } {
  if (reduced || !strength) return { dx: 0, dy: 0 };
  const m = PLANE_LAG[level] * strength;
  if (!m) return { dx: 0, dy: 0 };
  return { dx: (-view.x / view.k) * m, dy: (-view.y / view.k) * m };
}

function ease([x1, y1, x2, y2]: readonly number[], t: number): number {
  // Cubic bezier with P0=(0,0), P3=(1,1), solved for y at the x nearest t.
  const bx = (u: number) => 3 * (1 - u) * (1 - u) * u * x1 + 3 * (1 - u) * u * u * x2 + u * u * u;
  const by = (u: number) => 3 * (1 - u) * (1 - u) * u * y1 + 3 * (1 - u) * u * u * y2 + u * u * u;
  let lo = 0;
  let hi = 1;
  for (let i = 0; i < 18; i += 1) {
    const mid = (lo + hi) / 2;
    if (bx(mid) < t) lo = mid;
    else hi = mid;
  }
  return by((lo + hi) / 2);
}

export interface Camera {
  view: View;
  reduced: boolean;
  /** direct, un-eased — the reader's hand is on it */
  set: (next: View | ((v: View) => View)) => void;
  /** eased over the motion system's `move` step, or instant when reduced */
  glide: (next: View | ((v: View) => View)) => void;
  /** zoom by a factor about a point in frame coordinates */
  zoomAt: (factor: number, px: number, py: number, glide?: boolean) => void;
}

export function useCamera(resetKey: string): Camera {
  const [view, setView] = useState<View>(HOME);
  const reduced = useReducedMotionPref();
  const raf = useRef(0);
  const live = useRef(view);
  live.current = view;

  const stop = useCallback(() => {
    if (raf.current) cancelAnimationFrame(raf.current);
    raf.current = 0;
  }, []);

  const set = useCallback(
    (next: View | ((v: View) => View)) => {
      stop();
      setView(next);
    },
    [stop]
  );

  const glide = useCallback(
    (next: View | ((v: View) => View)) => {
      const from = live.current;
      const to = typeof next === 'function' ? next(from) : next;
      if (reduced) {
        set(to);
        return;
      }
      stop();
      const t0 = performance.now();
      const tick = (now: number) => {
        const t = Math.min(1, (now - t0) / DURATION_MS.move);
        const e = ease(EASE.glass, t);
        setView({
          x: from.x + (to.x - from.x) * e,
          y: from.y + (to.y - from.y) * e,
          k: from.k + (to.k - from.k) * e
        });
        if (t < 1) raf.current = requestAnimationFrame(tick);
        else raf.current = 0;
      };
      raf.current = requestAnimationFrame(tick);
    },
    [reduced, set, stop]
  );

  const zoomAt = useCallback(
    (factor: number, px: number, py: number, smooth = false) => {
      const move = smooth ? glide : set;
      move((v) => {
        const k = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, v.k * factor));
        if (k === v.k) return v;
        const s = k / v.k;
        return { k, x: px - (px - v.x) * s, y: py - (py - v.y) * s };
      });
    },
    [glide, set]
  );

  // A new focus is a new picture. The camera returns home rather than leaving
  // the reader looking at empty space where the old neighbourhood used to be.
  useEffect(() => {
    setView(HOME);
    stop();
  }, [resetKey, stop]);

  useEffect(() => stop, [stop]);

  return useMemo(() => ({ view, reduced, set, glide, zoomAt }), [view, reduced, set, glide, zoomAt]);
}
