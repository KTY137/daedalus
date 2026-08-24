/* The one channel between the scene and the type that floats over it.
 *
 * Labels are DOM text, not textures: a screen-aligned label has to be hinted,
 * anti-aliased and contrast-checked like every other sentence on the page.
 * So the scene projects, and the overlay reads — through this, not through
 * React state, because a per-frame setState would re-render the conversation
 * sixty times a second for nothing.
 *
 * The bodies' silhouettes travel this way too, because the hard rule of this
 * round is that no text ever lies across one. */

export interface ScreenPoint { id: string; x: number; y: number; r: number; z: number; hit: number }
export interface Silhouette { x: number; y: number; r: number }

export const bus = {
  /** node id → position in CSS pixels, drawn radius, hit-disc size, depth */
  pts: new Map<string, ScreenPoint>(),
  /** plane → the projected circle of its body, in CSS pixels */
  spheres: new Map<string, Silhouette>(),
  /** last pointer/key interaction, ms. The ambient drift waits for stillness. */
  touched: 0,
  frame: 0,
};

export const touch = () => { bus.touched = Date.now(); };

/* The 44 px rule reaches into the scene as well, and so does the no-text-on-a-
   body rule, so verify.cjs has to be able to read both from outside. */
if (typeof window !== 'undefined') {
  const w = window as unknown as Record<string, unknown>;
  w.__auroraPts = () => [...bus.pts.values()].map(p => ({ id: p.id, px: p.hit }));
  w.__auroraSpheres = () => [...bus.spheres.entries()].map(([p, s]) => ({ plane: p, ...s }));
}
