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
  'button:not(:disabled)',
  'input:not(:disabled)',
  'select:not(:disabled)',
  'textarea:not(:disabled)',
  'summary',
  '[tabindex]:not([tabindex="-1"])'
].join(',');

function focusable(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (el) => (el.offsetParent !== null || el === document.activeElement) && el.tabIndex >= 0
  );
}

/**
 * Native `inert` is the part of the modal contract that a focus loop alone
 * cannot provide. It removes the background from pointer, keyboard and
 * accessibility-tree interaction while leaving the dialog branch operable.
 *
 * Walk up from the dialog and inert every sibling branch. Remember only the
 * attributes added here so a permanently inert surface (the closed Settings
 * drawer, for example) stays inert after this dialog closes.
 */
function isolateDialogBranch(root: HTMLElement): () => void {
  const changed: HTMLElement[] = [];
  let branch: HTMLElement | null = root;

  while (branch?.parentElement) {
    const parent: HTMLElement = branch.parentElement;
    for (const sibling of Array.from(parent.children)) {
      if (
        !(sibling instanceof HTMLElement)
        || sibling === branch
        || sibling.hasAttribute('inert')
        // A sheet may render its pointer-dismiss scrim beside the dialog
        // instead of wrapping it. The scrim is aria-hidden and unfocusable,
        // but it must remain hit-testable so an outside click can still close
        // the modal while every actual background branch stays inert.
        || sibling.hasAttribute('data-dialog-scrim')
      ) continue;
      sibling.setAttribute('inert', '');
      changed.push(sibling);
    }
    branch = parent;
    if (parent === document.body) break;
  }

  return () => {
    for (const element of changed.reverse()) element.removeAttribute('inert');
  };
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
    const root = surface.current;
    if (!root) return;
    const restoreBackground = isolateDialogBranch(root);
    (first.current || focusable(root)[0])?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return;
      const currentRoot = surface.current;
      if (!currentRoot) return;
      const items = focusable(currentRoot);
      if (items.length === 0) return;

      const active = document.activeElement;
      const activeIndex = items.indexOf(active as HTMLElement);
      // Focus may sit outside the dialog entirely if something stole it; in
      // that case pull it back rather than letting Tab continue outside. The
      // same applies when a focused action becomes disabled asynchronously:
      // it remains inside the dialog but no longer belongs to `items`.
      const outsideFocusableSet = activeIndex === -1;
      const atEdge = event.shiftKey
        ? activeIndex === 0
        : activeIndex === items.length - 1;
      if (outsideFocusableSet || atEdge) {
        event.preventDefault();
        (event.shiftKey ? items[items.length - 1] : items[0]).focus();
      }
    };

    document.addEventListener('keydown', onKeyDown, true);
    return () => {
      document.removeEventListener('keydown', onKeyDown, true);
      restoreBackground();
      const back = opener.current;
      if (back instanceof HTMLElement) back.focus();
    };
  }, [open, surface, first]);
}
