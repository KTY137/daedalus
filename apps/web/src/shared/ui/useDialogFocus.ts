import { useEffect, useRef, type RefObject } from 'react';

/**
 * THE DIALOG FOCUS CONTRACT, in one place because it was claimed twice and
 * implemented neither time.
 *
 * Both overlay panels moved focus to their close button on open and returned
 * it to the opener on close — and their comments said that this stopped "Tab
 * walking the page underneath". It did not. Focus was MOVED, not TRAPPED: two
 * Tabs from the close button landed on the theme controls behind the scrim,
 * which were then fully operable by keyboard while a dialog carrying
 * `aria-modal="true"` told assistive technology the rest of the page was
 * hidden. `aria-modal` is a promise to AT; it does nothing for a sighted
 * keyboard user, and a promise the DOM does not keep is the kind of
 * accessibility claim this repository treats as a defect.
 *
 * So the trap is real now. Tab from the last focusable element wraps to the
 * first, Shift+Tab from the first wraps to the last, and focus returns to
 * whatever opened the dialog when it closes.
 *
 * The element list is recomputed on every Tab rather than cached: these panels
 * expand gate and subsystem rows on click, so the set of focusable elements
 * changes while the dialog is open.
 */

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  'summary',
  '[tabindex]:not([tabindex="-1"])'
].join(',');

function focusable(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (el) => el.offsetParent !== null || el === document.activeElement
  );
}

/**
 * @param open    whether the dialog is mounted and visible
 * @param surface the dialog element itself — the trap's boundary
 * @param first   what should receive focus on open (usually the close button)
 */
export function useDialogFocus(
  open: boolean,
  surface: RefObject<HTMLElement | null>,
  first: RefObject<HTMLElement | null>
): void {
  const opener = useRef<Element | null>(null);

  useEffect(() => {
    if (!open) return;
    opener.current = document.activeElement;
    first.current?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return;
      const root = surface.current;
      if (!root) return;
      const items = focusable(root);
      if (items.length === 0) return;

      const edge = event.shiftKey ? items[0] : items[items.length - 1];
      // Focus may sit outside the dialog entirely if something stole it; in
      // that case pull it back rather than letting Tab continue outside.
      const inside = root.contains(document.activeElement);
      if (!inside || document.activeElement === edge) {
        event.preventDefault();
        (event.shiftKey ? items[items.length - 1] : items[0]).focus();
      }
    };

    document.addEventListener('keydown', onKeyDown, true);
    return () => {
      document.removeEventListener('keydown', onKeyDown, true);
      const back = opener.current;
      if (back instanceof HTMLElement) back.focus();
    };
  }, [open, surface, first]);
}
