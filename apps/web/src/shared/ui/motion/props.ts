/**
 * React's DOM props that framer-motion redefines with a different signature.
 * Spreading a plain `HTMLAttributes` bag onto a motion component collides on
 * exactly these, so the glass primitives declare their prop types through
 * `MotionSafe<...>`.
 *
 * None of them are used by any caller in this app — the glass primitives are
 * passed `className`, `style`, `title`, aria-* and click handlers — so this
 * narrowing costs nothing at the call sites.
 */
export type MotionSafe<T> = Omit<
  T,
  | 'onAnimationStart'
  | 'onAnimationEnd'
  | 'onAnimationIteration'
  | 'onDrag'
  | 'onDragStart'
  | 'onDragEnd'
  | 'onDragEnter'
  | 'onDragExit'
  | 'onDragLeave'
  | 'onDragOver'
  | 'onDrop'
>;
