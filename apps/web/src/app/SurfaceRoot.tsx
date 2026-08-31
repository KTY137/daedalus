import { lazy, Suspense } from 'react';
import { Cockpit } from '../cockpit/Cockpit';
import { ThemeProvider } from '../theme/ThemeProvider';
import { resolveSurface } from './surface';

/**
 * The previous dock application remains lazy and isolated while Cockpit
 * absorbs its remaining runtime, control-plane, and inbox contracts. Its
 * stylesheet contains global selectors, so a static import would alter the
 * Cockpit even when the compatibility surface never renders.
 */
const ClassicSurface = lazy(() => import('../App'));

export function SurfaceRoot({ search }: { search: string }) {
  if (resolveSurface(search) === 'classic') {
    return (
      <Suspense fallback={null}>
        <ClassicSurface />
      </Suspense>
    );
  }

  return (
    <ThemeProvider>
      <Cockpit />
    </ThemeProvider>
  );
}
